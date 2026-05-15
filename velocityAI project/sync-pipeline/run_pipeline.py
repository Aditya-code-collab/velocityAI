#!/usr/bin/env python3
"""
IndiaMART KB Sync Pipeline
===========================
Orchestrates the full flow:
  1. Sync articles from Freshdesk API → local markdown files
  2. Ingest local markdown files → Qdrant vector database

Usage:
  python run_pipeline.py                  # Full pipeline (sync + ingest)
  python run_pipeline.py --sync-only      # Only sync from Freshdesk
  python run_pipeline.py --ingest-only    # Only ingest into Qdrant
  python run_pipeline.py --dry-run        # Test run (no Qdrant writes)
  python run_pipeline.py --full-sync      # Force full re-sync from Freshdesk
  python run_pipeline.py --search "query" # Search the vector DB
"""

import argparse
import json
import logging
import sys
from datetime import datetime

from config import Config
from freshdesk_sync import FreshdeskKBSync
from qdrant_ingest import QdrantIngestor

logger = logging.getLogger("pipeline")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_sync(full: bool = False) -> dict:
    """Step 1: Sync from Freshdesk API to local files."""
    logger.info("=" * 60)
    logger.info("STEP 1: Freshdesk KB Sync")
    logger.info("=" * 60)

    syncer = FreshdeskKBSync()
    stats = syncer.sync(full=full)
    return stats


def run_ingest(dry_run: bool = False) -> dict:
    """Step 2: Ingest local files into Qdrant."""
    logger.info("=" * 60)
    logger.info("STEP 2: Qdrant Ingestion")
    logger.info("=" * 60)

    ingestor = QdrantIngestor()
    stats = ingestor.ingest(dry_run=dry_run)
    return stats


def run_search(query: str, top_k: int = 5, category: str | None = None):
    """Search the vector database."""
    ingestor = QdrantIngestor()
    results = ingestor.search(query, top_k=top_k, category=category)

    if not results:
        print("No results found.")
        return

    print(f"\nSearch results for: \"{query}\"\n")
    for i, r in enumerate(results, 1):
        print(f"{'─' * 60}")
        print(f"  #{i}  Score: {r['score']:.4f}")
        print(f"  Title: {r['title']}")
        print(f"  Path:  {r['category']} > {r['folder']}")
        print(f"  Text:  {r['text'][:300]}...")
    print(f"{'─' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="IndiaMART KB Sync Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sync-only", action="store_true",
        help="Only run Freshdesk sync (skip Qdrant ingestion)",
    )
    parser.add_argument(
        "--ingest-only", action="store_true",
        help="Only run Qdrant ingestion (skip Freshdesk sync)",
    )
    parser.add_argument(
        "--full-sync", action="store_true",
        help="Force full re-sync from Freshdesk (ignore incremental state)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Test mode: sync + chunk + embed, but skip Qdrant writes",
    )
    parser.add_argument(
        "--search", type=str,
        help="Search the Qdrant collection with a query",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Number of search results (default: 5)",
    )
    parser.add_argument(
        "--category", type=str,
        help="Filter search by category name",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Print config warnings
    warnings = Config.validate()
    for w in warnings:
        logger.warning(f"CONFIG: {w}")

    # Search mode
    if args.search:
        run_search(args.search, top_k=args.top_k, category=args.category)
        return

    start_time = datetime.now()
    results = {"started_at": start_time.isoformat()}

    # Step 1: Sync
    if not args.ingest_only:
        sync_stats = run_sync(full=args.full_sync)
        results["sync"] = sync_stats
        logger.info(f"Sync stats: {json.dumps(sync_stats, indent=2)}")

    # Step 2: Ingest
    if not args.sync_only:
        ingest_stats = run_ingest(dry_run=args.dry_run)
        results["ingest"] = ingest_stats
        logger.info(f"Ingest stats: {json.dumps(ingest_stats, indent=2)}")

    elapsed = (datetime.now() - start_time).total_seconds()
    results["elapsed_seconds"] = round(elapsed, 2)

    logger.info("=" * 60)
    logger.info(f"Pipeline complete in {elapsed:.1f}s")
    logger.info("=" * 60)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
