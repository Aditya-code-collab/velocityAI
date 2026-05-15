#!/usr/bin/env python3
"""
Pipeline Unit & Integration Tests
===================================
Tests the chunking, file scanning, config, and sync state logic
without requiring Freshdesk API or Qdrant connection.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from freshdesk_sync import sanitize_filename, html_to_markdown, SyncState
from qdrant_ingest import chunk_text, scan_kb_files, make_chunk_id


def test_sanitize_filename():
    print("  Test: sanitize_filename")
    assert sanitize_filename("Hello World") == "Hello World"
    assert sanitize_filename('How to "fix" bugs?') == "How to -fix- bugs-"
    assert sanitize_filename("a" * 200) == "a" * 100
    assert sanitize_filename("   ") == "untitled"
    assert sanitize_filename("path/to\\file:name") == "path-to-file-name"
    print("    ✓ All assertions passed")


def test_html_to_markdown():
    print("  Test: html_to_markdown")

    # Basic conversion
    md = html_to_markdown("<p>Hello <strong>world</strong></p>")
    assert "Hello" in md
    assert "world" in md

    # Script removal
    md = html_to_markdown("<p>Text</p><script>alert('bad')</script>")
    assert "alert" not in md
    assert "Text" in md

    # Empty input
    assert html_to_markdown("") == ""
    assert html_to_markdown(None) == ""
    print("    ✓ All assertions passed")


def test_chunk_text():
    print("  Test: chunk_text")

    # Simple short text
    chunks = chunk_text("Hello world", chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == "Hello world"

    # Multi-paragraph splitting
    long_text = "\n\n".join([f"Paragraph {i}. " * 20 for i in range(10)])
    chunks = chunk_text(long_text, chunk_size=300, chunk_overlap=50)
    assert len(chunks) > 1
    # All chunks should be non-empty
    assert all(len(c.strip()) > 0 for c in chunks)

    # Empty input
    assert chunk_text("") == []
    assert chunk_text("   ") == []

    print(f"    ✓ All assertions passed ({len(chunks)} chunks from long text)")


def test_sync_state():
    print("  Test: SyncState")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        state_path = Path(f.name)

    try:
        state = SyncState(state_path)

        # New article should need update
        assert state.needs_update(123, "2024-01-01T00:00:00Z") is True

        # Mark as synced
        state.mark_synced(123, "2024-01-01T00:00:00Z")

        # Same timestamp → no update needed
        assert state.needs_update(123, "2024-01-01T00:00:00Z") is False

        # New timestamp → needs update
        assert state.needs_update(123, "2024-02-01T00:00:00Z") is True

        # Save and reload
        state.set_last_sync()
        state.save()

        state2 = SyncState(state_path)
        assert state2.needs_update(123, "2024-01-01T00:00:00Z") is False
        assert state2.data["last_sync"] is not None

        print("    ✓ All assertions passed")
    finally:
        state_path.unlink(missing_ok=True)


def test_scan_kb_files():
    print("  Test: scan_kb_files")

    with tempfile.TemporaryDirectory() as tmp:
        kb_dir = Path(tmp) / "KB"
        # Create test structure
        cat_dir = kb_dir / "TestCategory" / "TestFolder"
        cat_dir.mkdir(parents=True)
        (cat_dir / "article1.md").write_text("# My Article\n\nSome content here.")
        (cat_dir / "article2.md").write_text("# Another Article\n\nMore content.")
        (kb_dir / "INDEX.md").write_text("# Index\nShould be skipped")

        files = list(scan_kb_files(kb_dir))
        assert len(files) == 2

        # Check metadata extraction
        f1 = files[0]
        assert f1["category"] == "TestCategory"
        assert f1["folder"] == "TestFolder"
        assert "Article" in f1["title"]
        assert f1["content"].startswith("# ")

        # INDEX.md should be skipped
        assert not any(f["title"] == "Index" for f in files)

        print(f"    ✓ All assertions passed ({len(files)} files scanned)")


def test_make_chunk_id():
    print("  Test: make_chunk_id")

    # Deterministic
    id1 = make_chunk_id("/path/to/file.md", 0)
    id2 = make_chunk_id("/path/to/file.md", 0)
    assert id1 == id2

    # Different inputs → different IDs
    id3 = make_chunk_id("/path/to/file.md", 1)
    assert id1 != id3

    id4 = make_chunk_id("/other/file.md", 0)
    assert id1 != id4

    print("    ✓ All assertions passed")


def test_config():
    print("  Test: Config validation")

    assert Config.is_dummy_key() is True  # Since we're using dummy key
    warnings = Config.validate()
    assert len(warnings) > 0  # Should warn about dummy key
    assert any("API key" in w for w in warnings)

    print(f"    ✓ Config warnings: {len(warnings)}")


def test_local_only_sync():
    print("  Test: FreshdeskKBSync local-only mode")

    from freshdesk_sync import FreshdeskKBSync

    syncer = FreshdeskKBSync()
    stats = syncer.sync()  # Should auto-detect dummy key and run local mode

    assert stats.get("mode") == "local_only"
    assert stats["categories"] > 0  # We have our downloaded KB
    assert stats["articles_checked"] > 0

    print(f"    ✓ Local mode: {stats['categories']} categories, "
          f"{stats['articles_checked']} articles found")


def test_dry_run_ingest():
    print("  Test: QdrantIngestor dry-run mode")

    from qdrant_ingest import QdrantIngestor

    ingestor = QdrantIngestor()
    stats = ingestor.ingest(dry_run=True)

    assert stats.get("mode") == "dry_run"
    assert stats["files_processed"] > 0
    assert stats["chunks_created"] > 0
    assert stats["chunks_upserted"] == 0  # Dry run = no upserts

    print(f"    ✓ Dry run: {stats['files_processed']} files, "
          f"{stats['chunks_created']} chunks created")


# ── Run All Tests ───────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("IndiaMART KB Pipeline — Test Suite")
    print("=" * 60)

    tests = [
        ("Config", test_config),
        ("Filename Sanitizer", test_sanitize_filename),
        ("HTML to Markdown", test_html_to_markdown),
        ("Text Chunker", test_chunk_text),
        ("Sync State", test_sync_state),
        ("KB File Scanner", test_scan_kb_files),
        ("Chunk ID Generator", test_make_chunk_id),
        ("Freshdesk Sync (local mode)", test_local_only_sync),
        ("Qdrant Ingest (dry run)", test_dry_run_ingest),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            failed += 1
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
