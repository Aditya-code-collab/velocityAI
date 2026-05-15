"""Centralized configuration loaded from .env"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the sync-pipeline directory
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)


class Config:
    # Freshdesk
    FRESHDESK_DOMAIN: str = os.getenv("FRESHDESK_DOMAIN", "indiamartkb.freshdesk.com")
    FRESHDESK_API_KEY: str = os.getenv("FRESHDESK_API_KEY", "DUMMY_API_KEY_REPLACE_ME")
    FRESHDESK_BASE_URL: str = f"https://{FRESHDESK_DOMAIN}"

    # Local KB storage
    KB_BASE_DIR: Path = Path(os.getenv("KB_BASE_DIR", "../IndiaMART-KB")).resolve()
    SYNC_STATE_FILE: Path = Path(os.getenv("SYNC_STATE_FILE", ".sync_state.json"))

    # Qdrant
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "indiamart_kb")

    # Embedding
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    # Chunking
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "64"))

    @classmethod
    def is_dummy_key(cls) -> bool:
        return cls.FRESHDESK_API_KEY in ("DUMMY_API_KEY_REPLACE_ME", "", None)

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of config warnings."""
        warnings = []
        if cls.is_dummy_key():
            warnings.append(
                "Freshdesk API key is a placeholder. "
                "Set FRESHDESK_API_KEY in .env with your real key."
            )
        if not cls.KB_BASE_DIR.exists():
            warnings.append(f"KB directory not found: {cls.KB_BASE_DIR}")
        return warnings
