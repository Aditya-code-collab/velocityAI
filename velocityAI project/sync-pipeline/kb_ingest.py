"""
KB Ingest — embed IndiaMART-KB markdown articles into Qdrant.

Standalone, mirrors the root project's qdrant_helper.py conventions:
  - raw httpx against the shared remote Qdrant (NO qdrant-client)
  - OpenAI client pointed at the LiteLLM proxy, 1536-dim embeddings

One article = one Qdrant point (no chunking — KB articles are short,
self-contained answers and chunking hurts retrieval quality here).

Usage:
  python3 kb_ingest.py --dry-run                       # scan + count only
  python3 kb_ingest.py                                  # embed + upsert
  python3 kb_ingest.py --subdir "BuyLead & Tender"      # scope (default)
  python3 kb_ingest.py --limit 5                        # first N files only
  python3 kb_ingest.py --search "how to mark BLNI"      # smoke-test query
"""
import argparse
import os
import re
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

# ── Config (load the ROOT project .env so we reuse the LiteLLM creds) ──
ROOT_DIR = Path(__file__).resolve().parents[2]            # .../velocityAI
load_dotenv(ROOT_DIR / ".env")

QDRANT_URL = os.getenv("QDRANT_URL", "http://34.47.255.166:80")
KB_COLLECTION = os.getenv("KB_QDRANT_COLLECTION", "indiamart_kb")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://imllm.intermesh.net/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

KB_BASE_DIR = (ROOT_DIR / "velocityAI project" / "IndiaMART-KB").resolve()

# Deterministic namespace so re-ingestion upserts the same points.
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "indiamart-kb")

_openai = None
_http = None


def openai_client() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)
    return _openai


def http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(base_url=QDRANT_URL, timeout=60)
    return _http


def embed(text: str) -> list[float]:
    resp = openai_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIM,
    )
    return resp.data[0].embedding


def ensure_collection():
    r = http_client().get("/collections")
    r.raise_for_status()
    existing = [c["name"] for c in r.json()["result"]["collections"]]
    if KB_COLLECTION in existing:
        print(f"Collection '{KB_COLLECTION}' already exists")
        return
    r2 = http_client().put(
        f"/collections/{KB_COLLECTION}",
        json={"vectors": {"size": EMBEDDING_DIM, "distance": "Cosine"}},
    )
    r2.raise_for_status()
    print(f"Created collection: {KB_COLLECTION} (dim={EMBEDDING_DIM}, Cosine)")


# ── Scan ──────────────────────────────────────────────────────────────

def scan(subdir: str) -> list[dict]:
    root = (KB_BASE_DIR / subdir).resolve()
    if not root.exists():
        sys.exit(f"Subdir not found: {root}")

    out = []
    for md in sorted(root.rglob("*.md")):
        if md.name.startswith(".") or md.name == "INDEX.md":
            continue
        rel = md.relative_to(KB_BASE_DIR)
        parts = rel.parts
        category = parts[0]                                  # "BuyLead & Tender"
        folder = parts[1] if len(parts) > 2 else "General"   # subfolder
        if len(parts) > 3:
            folder = "/".join(parts[1:-1])

        content = md.read_text(encoding="utf-8", errors="replace").strip()
        m = re.match(r"^#\s+(.+)", content)
        title = m.group(1).strip() if m else md.stem

        out.append({
            "id": str(uuid.uuid5(_NS, str(rel))),
            "relative_path": str(rel),
            "category": category,
            "folder": folder,
            "title": title,
            "content": content,
        })
    return out


# ── Ingest ────────────────────────────────────────────────────────────

def ingest(files: list[dict]):
    ensure_collection()
    points = []
    for i, f in enumerate(files, 1):
        embed_text = f"{f['title']}\n\n{f['content']}"
        points.append({
            "id": f["id"],
            "vector": embed(embed_text),
            "payload": {
                "category": f["category"],
                "folder": f["folder"],
                "title": f["title"],
                "content": f["content"],
                "relative_path": f["relative_path"],
                "source": "freshdesk-kb",
            },
        })
        print(f"  [{i}/{len(files)}] embedded: {f['relative_path']}")

    for start in range(0, len(points), 8):
        batch = points[start:start + 8]
        r = http_client().put(
            f"/collections/{KB_COLLECTION}/points",
            json={"points": batch},
        )
        r.raise_for_status()
    print(f"Upserted {len(points)} points into '{KB_COLLECTION}'")


def search(query: str, top_k: int):
    vec = embed(query)
    r = http_client().post(
        f"/collections/{KB_COLLECTION}/points/search",
        json={"vector": vec, "limit": top_k, "with_payload": True},
    )
    r.raise_for_status()
    for i, h in enumerate(r.json()["result"], 1):
        p = h["payload"]
        print(f"\n--- #{i}  score={h['score']:.4f} ---")
        print(f"  {p['category']} > {p['folder']}")
        print(f"  {p['title']}")
        print(f"  {p['content'][:200]}...")


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest IndiaMART-KB into Qdrant")
    ap.add_argument("--subdir", default="BuyLead & Tender",
                    help="KB subdirectory to ingest (default: 'BuyLead & Tender')")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan + count only; no embed or upsert")
    ap.add_argument("--limit", type=int, help="Process only the first N files")
    ap.add_argument("--search", type=str, help="Run a test search and exit")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    if args.search:
        search(args.search, args.top_k)
        sys.exit(0)

    files = scan(args.subdir)
    if args.limit:
        files = files[:args.limit]

    print(f"KB base : {KB_BASE_DIR}")
    print(f"Subdir  : {args.subdir}")
    print(f"Qdrant  : {QDRANT_URL}  collection={KB_COLLECTION}")
    print(f"Files   : {len(files)} markdown articles\n")

    by_folder: dict[str, int] = {}
    for f in files:
        by_folder[f["folder"]] = by_folder.get(f["folder"], 0) + 1
    for folder, n in sorted(by_folder.items()):
        print(f"  {folder:35s} {n:3d}")

    if args.dry_run:
        print("\nDRY RUN — nothing embedded or written.")
        sys.exit(0)

    print()
    ingest(files)
