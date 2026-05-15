"""
Freshdesk Knowledge Base Sync Module
-------------------------------------
Pulls categories → folders → articles from the Freshdesk Solutions API,
converts HTML to Markdown, and saves to a local folder hierarchy.

Supports incremental sync using article `updated_at` timestamps.

API docs: https://developers.freshdesk.com/api/#solution-category
"""

import json
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
import html2text

from config import Config

logger = logging.getLogger(__name__)


# ── Freshdesk API Client ────────────────────────────────────────────

class FreshdeskClient:
    """Thin wrapper around the Freshdesk Solutions API."""

    def __init__(self, domain: str, api_key: str):
        self.base_url = f"https://{domain}/api/v2"
        self.auth = (api_key, "X")  # Freshdesk uses API key as username, "X" as password
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Content-Type": "application/json"})

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        """Make a GET request with rate-limit handling."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Failed after 3 retries: {url}")

    def get_categories(self) -> list[dict]:
        """GET /api/v2/solutions/categories"""
        results = []
        page = 1
        while True:
            data = self._get("/solutions/categories", {"per_page": 100, "page": page})
            if not data:
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results

    def get_folders(self, category_id: int) -> list[dict]:
        """GET /api/v2/solutions/categories/:id/folders"""
        results = []
        page = 1
        while True:
            data = self._get(
                f"/solutions/categories/{category_id}/folders",
                {"per_page": 100, "page": page},
            )
            if not data:
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results

    def get_articles(self, folder_id: int) -> list[dict]:
        """GET /api/v2/solutions/folders/:id/articles"""
        results = []
        page = 1
        while True:
            data = self._get(
                f"/solutions/folders/{folder_id}/articles",
                {"per_page": 100, "page": page},
            )
            if not data:
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results


# ── HTML → Markdown Converter ───────────────────────────────────────

def html_to_markdown(html_content: str) -> str:
    """Convert Freshdesk article HTML to clean Markdown."""
    if not html_content:
        return ""

    # Clean up with BeautifulSoup first
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove script and style tags
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = False
    converter.body_width = 0  # No wrapping
    converter.protect_links = True
    converter.unicode_snob = True

    md = converter.handle(str(soup))

    # Clean up excessive whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ── Filename Sanitizer ──────────────────────────────────────────────

def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Make a string safe for use as a filename."""
    # Replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .-")
    return name or "untitled"


# ── Sync State Management ──────────────────────────────────────────

class SyncState:
    """Track last-synced timestamps per article for incremental sync."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.data: dict = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            text = self.state_file.read_text().strip()
            if text:
                return json.loads(text)
        return {"last_sync": None, "articles": {}}

    def save(self):
        self.state_file.write_text(json.dumps(self.data, indent=2))

    def needs_update(self, article_id: int, updated_at: str) -> bool:
        """Check if article has been updated since last sync."""
        stored = self.data["articles"].get(str(article_id))
        if not stored:
            return True
        return stored != updated_at

    def mark_synced(self, article_id: int, updated_at: str):
        self.data["articles"][str(article_id)] = updated_at

    def set_last_sync(self):
        self.data["last_sync"] = datetime.now(timezone.utc).isoformat()


# ── Main Sync Logic ─────────────────────────────────────────────────

class FreshdeskKBSync:
    """Orchestrates the full KB sync from Freshdesk to local markdown files."""

    def __init__(self, config: type[Config] = Config):
        self.config = config
        self.kb_dir = config.KB_BASE_DIR
        self.state = SyncState(config.SYNC_STATE_FILE)
        self.client = FreshdeskClient(config.FRESHDESK_DOMAIN, config.FRESHDESK_API_KEY)
        self.stats = {"categories": 0, "folders": 0, "articles_checked": 0,
                      "articles_updated": 0, "articles_skipped": 0, "errors": 0}

    def sync(self, full: bool = False) -> dict:
        """
        Run the sync process.

        Args:
            full: If True, ignore sync state and re-download everything.

        Returns:
            Dictionary of sync statistics.
        """
        if self.config.is_dummy_key():
            logger.error(
                "Cannot sync from Freshdesk API with a dummy key. "
                "Please set FRESHDESK_API_KEY in .env"
            )
            return self._run_local_only_mode()

        logger.info("Starting Freshdesk KB sync...")
        if full:
            logger.info("Full sync mode — ignoring previous state")

        try:
            categories = self.client.get_categories()
            self.stats["categories"] = len(categories)
            logger.info(f"Found {len(categories)} categories")

            for cat in categories:
                self._sync_category(cat, full=full)

            self.state.set_last_sync()
            self.state.save()
            logger.info(f"Sync complete: {self.stats}")

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                logger.error("Authentication failed — check your FRESHDESK_API_KEY")
            else:
                logger.error(f"HTTP error during sync: {e}")
            self.stats["errors"] += 1

        return self.stats

    def _sync_category(self, category: dict, full: bool):
        cat_name = sanitize_filename(category["name"])
        cat_dir = self.kb_dir / cat_name
        cat_dir.mkdir(parents=True, exist_ok=True)

        folders = self.client.get_folders(category["id"])
        self.stats["folders"] += len(folders)

        for folder in folders:
            self._sync_folder(cat_dir, folder, full=full)

    def _sync_folder(self, cat_dir: Path, folder: dict, full: bool):
        folder_name = sanitize_filename(folder["name"])
        folder_dir = cat_dir / folder_name
        folder_dir.mkdir(parents=True, exist_ok=True)

        articles = self.client.get_articles(folder["id"])

        for article in articles:
            self.stats["articles_checked"] += 1
            self._sync_article(folder_dir, article, full=full)

    def _sync_article(self, folder_dir: Path, article: dict, full: bool):
        article_id = article["id"]
        updated_at = article.get("updated_at", "")
        title = article.get("title", "Untitled")

        if not full and not self.state.needs_update(article_id, updated_at):
            self.stats["articles_skipped"] += 1
            return

        try:
            filename = sanitize_filename(title) + ".md"
            filepath = folder_dir / filename

            body_html = article.get("description", "") or article.get("description_text", "")
            body_md = html_to_markdown(body_html)

            content = f"# {title}\n\n{body_md}\n"
            filepath.write_text(content, encoding="utf-8")

            self.state.mark_synced(article_id, updated_at)
            self.stats["articles_updated"] += 1
            logger.debug(f"Updated: {filepath.name}")

        except Exception as e:
            logger.error(f"Error syncing article {article_id} ({title}): {e}")
            self.stats["errors"] += 1

    def _run_local_only_mode(self) -> dict:
        """
        When no API key is available, just scan existing local files
        and return stats about what's on disk — useful for the Qdrant
        ingestion step which doesn't need the API.
        """
        logger.info("Running in LOCAL-ONLY mode (no Freshdesk API call)")
        article_count = 0
        cat_count = 0
        folder_count = 0

        if self.kb_dir.exists():
            for cat_dir in sorted(self.kb_dir.iterdir()):
                if cat_dir.is_dir() and cat_dir.name != ".git":
                    cat_count += 1
                    for folder_dir in sorted(cat_dir.iterdir()):
                        if folder_dir.is_dir():
                            folder_count += 1
                            article_count += len(list(folder_dir.glob("*.md")))

        self.stats.update({
            "categories": cat_count,
            "folders": folder_count,
            "articles_checked": article_count,
            "articles_updated": 0,
            "articles_skipped": article_count,
            "mode": "local_only",
        })
        logger.info(
            f"Local KB: {cat_count} categories, {folder_count} folders, "
            f"{article_count} articles on disk"
        )
        return self.stats


# ── CLI Entry Point ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Sync Freshdesk KB to local markdown")
    parser.add_argument("--full", action="store_true", help="Full re-sync (ignore state)")
    args = parser.parse_args()

    syncer = FreshdeskKBSync()
    stats = syncer.sync(full=args.full)
    print(json.dumps(stats, indent=2))
