"""
Qdrant Ingestion Module
------------------------
Reads local markdown KB files, chunks them, generates embeddings
using fastembed (lightweight, no PyTorch needed), and upserts into Qdrant.

Each chunk is stored with rich metadata (category, folder, title, filepath)
for filtered retrieval.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Generator

from tqdm import tqdm

from config import Config

logger = logging.getLogger(__name__)


# ── Text Chunker ────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """
    Split text into overlapping chunks by character count,
    respecting paragraph and sentence boundaries where possible.
    """
    if not text or not text.strip():
        return []

    # Split into paragraphs
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph exceeds chunk size, save current and start new
        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(current_chunk.strip())
            # Overlap: keep tail of previous chunk
            if chunk_overlap > 0 and len(current_chunk) > chunk_overlap:
                current_chunk = current_chunk[-chunk_overlap:] + "\n\n" + para
            else:
                current_chunk = para
        else:
            current_chunk = (current_chunk + "\n\n" + para).strip()

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Handle case where a single paragraph is larger than chunk_size
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= chunk_size * 1.5:  # Allow some flexibility
            final_chunks.append(chunk)
        else:
            # Force-split long chunks by sentences
            sentences = re.split(r"(?<=[.!?])\s+", chunk)
            sub_chunk = ""
            for sent in sentences:
                if sub_chunk and len(sub_chunk) + len(sent) + 1 > chunk_size:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = sent
                else:
                    sub_chunk = (sub_chunk + " " + sent).strip()
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())

    return final_chunks


# ── File Scanner ────────────────────────────────────────────────────

def scan_kb_files(kb_dir: Path) -> Generator[dict, None, None]:
    """
    Walk the KB directory and yield metadata for each markdown file.

    Yields:
        dict with keys: filepath, category, folder, title, content
    """
    if not kb_dir.exists():
        logger.error(f"KB directory does not exist: {kb_dir}")
        return

    for md_file in sorted(kb_dir.rglob("*.md")):
        # Skip index files and hidden files
        if md_file.name.startswith(".") or md_file.name == "INDEX.md":
            continue

        rel = md_file.relative_to(kb_dir)
        parts = rel.parts

        # Expected structure: Category/Folder/article.md
        category = parts[0] if len(parts) > 0 else "Unknown"
        folder = parts[1] if len(parts) > 1 else "General"
        # Could be deeper nesting
        if len(parts) > 3:
            folder = "/".join(parts[1:-1])

        content = md_file.read_text(encoding="utf-8", errors="replace")

        # Extract title from first H1 or filename
        title_match = re.match(r"^#\s+(.+)", content)
        title = title_match.group(1).strip() if title_match else md_file.stem

        yield {
            "filepath": str(md_file),
            "relative_path": str(rel),
            "category": category,
            "folder": folder,
            "title": title,
            "content": content,
        }


# ── Deterministic ID Generator ──────────────────────────────────────

def make_chunk_id(filepath: str, chunk_index: int) -> str:
    """Generate a deterministic ID for a chunk so re-ingestion is idempotent."""
    raw = f"{filepath}::chunk_{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── Main Ingestion Logic ────────────────────────────────────────────

class QdrantIngestor:
    """Handles embedding generation and Qdrant upserts.

    Uses fastembed (lightweight ONNX-based embeddings, no PyTorch needed).
    Falls back to sentence-transformers if fastembed is not available.
    """

    # fastembed model → dimension mapping
    MODEL_DIMS = {
        "all-MiniLM-L6-v2": 384,
        "BAAI/bge-small-en-v1.5": 384,
        "BAAI/bge-base-en-v1.5": 768,
    }

    def __init__(self, config: type[Config] = Config):
        self.config = config
        self.model = None       # Lazy-loaded
        self.qdrant = None      # Lazy-loaded
        self.stats = {
            "files_processed": 0,
            "chunks_created": 0,
            "chunks_upserted": 0,
            "errors": 0,
        }

    def _load_model(self):
        """Lazy-load the fastembed model."""
        if self.model is None:
            from fastembed import TextEmbedding
            model_name = self.config.EMBEDDING_MODEL
            logger.info(f"Loading embedding model: {model_name}")
            self.model = TextEmbedding(model_name=model_name)
            logger.info("Model loaded successfully")

    def _get_embedding_dim(self) -> int:
        """Get embedding dimension for current model."""
        dim = self.MODEL_DIMS.get(self.config.EMBEDDING_MODEL)
        if dim:
            return dim
        # Fallback: encode a test string
        self._load_model()
        test = list(self.model.embed(["test"]))[0]
        return len(test)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts using fastembed."""
        self._load_model()
        # fastembed returns a generator of numpy arrays
        embeddings = list(self.model.embed(texts, batch_size=self.config.BATCH_SIZE))
        return [e.tolist() for e in embeddings]

    def _connect_qdrant(self):
        """Lazy-connect to Qdrant."""
        if self.qdrant is None:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            logger.info(
                f"Connecting to Qdrant at "
                f"{self.config.QDRANT_HOST}:{self.config.QDRANT_PORT}"
            )
            self.qdrant = QdrantClient(
                host=self.config.QDRANT_HOST,
                port=self.config.QDRANT_PORT,
            )

            # Ensure collection exists
            collections = [c.name for c in self.qdrant.get_collections().collections]
            if self.config.QDRANT_COLLECTION not in collections:
                dim = self._get_embedding_dim()
                logger.info(
                    f"Creating collection '{self.config.QDRANT_COLLECTION}' "
                    f"with dim={dim}"
                )
                self.qdrant.create_collection(
                    collection_name=self.config.QDRANT_COLLECTION,
                    vectors_config=VectorParams(
                        size=dim,
                        distance=Distance.COSINE,
                    ),
                )
            logger.info("Qdrant connected")

    def ingest(self, dry_run: bool = False) -> dict:
        """
        Main ingestion: scan KB → chunk → embed → upsert.

        Args:
            dry_run: If True, skip Qdrant upsert (useful for testing).
        """
        if not dry_run:
            self._connect_qdrant()

        kb_dir = self.config.KB_BASE_DIR
        logger.info(f"Scanning KB at: {kb_dir}")

        files = list(scan_kb_files(kb_dir))
        logger.info(f"Found {len(files)} article files")

        all_chunks = []
        all_ids = []
        all_metadata = []

        for file_info in tqdm(files, desc="Chunking articles"):
            try:
                chunks = chunk_text(
                    file_info["content"],
                    chunk_size=self.config.CHUNK_SIZE,
                    chunk_overlap=self.config.CHUNK_OVERLAP,
                )
                if not chunks:
                    continue

                self.stats["files_processed"] += 1

                for i, chunk in enumerate(chunks):
                    chunk_id = make_chunk_id(file_info["filepath"], i)
                    metadata = {
                        "category": file_info["category"],
                        "folder": file_info["folder"],
                        "title": file_info["title"],
                        "relative_path": file_info["relative_path"],
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "text": chunk,  # Store raw text for retrieval
                    }
                    all_chunks.append(chunk)
                    all_ids.append(chunk_id)
                    all_metadata.append(metadata)
                    self.stats["chunks_created"] += 1

            except Exception as e:
                logger.error(f"Error processing {file_info['filepath']}: {e}")
                self.stats["errors"] += 1

        if not all_chunks:
            logger.warning("No chunks to ingest")
            return self.stats

        # Generate embeddings
        logger.info(f"Generating embeddings for {len(all_chunks)} chunks...")
        embeddings = self._embed(all_chunks)
        logger.info("Embeddings generated")

        if dry_run:
            logger.info(f"DRY RUN — would upsert {len(all_chunks)} chunks")
            self.stats["chunks_upserted"] = 0
            self.stats["mode"] = "dry_run"
            self.stats["embedding_dim"] = len(embeddings[0]) if embeddings else 0
            return self.stats

        # Upsert to Qdrant in batches
        from qdrant_client.models import PointStruct

        batch_size = 100
        for start in tqdm(
            range(0, len(all_chunks), batch_size),
            desc="Upserting to Qdrant",
        ):
            end = min(start + batch_size, len(all_chunks))
            points = [
                PointStruct(
                    id=all_ids[i],
                    vector=embeddings[i],
                    payload=all_metadata[i],
                )
                for i in range(start, end)
            ]
            self.qdrant.upsert(
                collection_name=self.config.QDRANT_COLLECTION,
                points=points,
            )
            self.stats["chunks_upserted"] += len(points)

        logger.info(f"Ingestion complete: {self.stats}")
        return self.stats

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """
        Search the Qdrant collection.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            category: Optional category filter

        Returns:
            List of result dicts with score, text, and metadata
        """
        self._connect_qdrant()

        query_vector = self._embed([query])[0]

        search_params = {
            "collection_name": self.config.QDRANT_COLLECTION,
            "query_vector": query_vector,
            "limit": top_k,
            "with_payload": True,
        }

        # Optional category filter
        if category:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            search_params["query_filter"] = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )

        results = self.qdrant.search(**search_params)

        return [
            {
                "score": hit.score,
                "text": hit.payload.get("text", ""),
                "title": hit.payload.get("title", ""),
                "category": hit.payload.get("category", ""),
                "folder": hit.payload.get("folder", ""),
                "relative_path": hit.payload.get("relative_path", ""),
            }
            for hit in results
        ]


# ── CLI Entry Point ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Ingest KB into Qdrant")
    parser.add_argument("--dry-run", action="store_true", help="Skip Qdrant upsert")
    parser.add_argument("--search", type=str, help="Run a test search query")
    parser.add_argument("--top-k", type=int, default=5, help="Number of search results")
    args = parser.parse_args()

    ingestor = QdrantIngestor()

    if args.search:
        results = ingestor.search(args.search, top_k=args.top_k)
        for i, r in enumerate(results, 1):
            print(f"\n--- Result {i} (score: {r['score']:.4f}) ---")
            print(f"Title: {r['title']}")
            print(f"Category: {r['category']} > {r['folder']}")
            print(f"Text: {r['text'][:200]}...")
    else:
        stats = ingestor.ingest(dry_run=args.dry_run)
        print(json.dumps(stats, indent=2))
