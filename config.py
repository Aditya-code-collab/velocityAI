import os
from dotenv import load_dotenv

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://34.47.255.166:80")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "indiamart_sops")

# LiteLLM proxy — same setup as buyleadagent
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://imllm.intermesh.net/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
VIOLATION_EMAIL_TO = os.getenv("VIOLATION_EMAIL_TO", "yashwantsinghchandra258@gmail.com")

DATABASE_PATH = os.getenv("DATABASE_PATH", "jobs.db")
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
