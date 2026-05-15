"""
Qdrant helper — uses the REST API directly to avoid qdrant-client/server
version compatibility issues (client v1.18 vs server v1.9.2).
"""
import uuid
import httpx
from openai import OpenAI
from config import (
    QDRANT_URL, QDRANT_COLLECTION,
    EMBEDDING_MODEL, EMBEDDING_DIM,
    OPENAI_API_KEY, OPENAI_API_BASE,
)

_openai = None
_http = None


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(base_url=QDRANT_URL, timeout=30)
    return _http


def openai_client() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)
    return _openai


def embed(text: str) -> list[float]:
    resp = openai_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIM,
    )
    return resp.data[0].embedding


def ensure_collection():
    r = _http_client().get("/collections")
    r.raise_for_status()
    existing = [c["name"] for c in r.json()["result"]["collections"]]
    if QDRANT_COLLECTION not in existing:
        payload = {
            "vectors": {"size": EMBEDDING_DIM, "distance": "Cosine"}
        }
        r2 = _http_client().put(f"/collections/{QDRANT_COLLECTION}", json=payload)
        r2.raise_for_status()
        print(f"Created collection: {QDRANT_COLLECTION}")
    else:
        print(f"Collection '{QDRANT_COLLECTION}' already exists")


def upsert_sop(category: str, title: str, content: str, rules: list[str],
               keywords: list[str] = None, description: str = None):
    # Embed the rich description (title + overview + rules + call phrases).
    # Falls back to content if description not provided.
    embed_text = description or content
    vector = embed(embed_text)
    point = {
        "id": str(uuid.uuid4()),
        "vector": vector,
        "payload": {
            "category": category,
            "title": title,
            "content": content,
            "description": embed_text,
            "rules": rules,
            "keywords": keywords or [],
        },
    }
    r = _http_client().put(
        f"/collections/{QDRANT_COLLECTION}/points",
        json={"points": [point]},
    )
    r.raise_for_status()


def search_sops(transcription: str, top_k: int = 3) -> list[dict]:
    vector = embed(transcription)
    r = _http_client().post(
        f"/collections/{QDRANT_COLLECTION}/points/search",
        json={
            "vector": vector,
            "limit": top_k,
            # Fetch only what the agent prompt needs — skip description and keywords
            "with_payload": {"include": ["category", "title", "content", "rules"]},
        },
    )
    r.raise_for_status()
    hits = r.json()["result"]
    results = []
    for i, h in enumerate(hits):
        p = h["payload"]
        entry = {
            "category": p.get("category"),
            "title": p.get("title"),
            "content": p.get("content"),
            "score": round(h["score"], 4),
            # Rules only needed for the top hit — runner-ups are category context only
            "rules": p.get("rules", []) if i == 0 else [],
        }
        results.append(entry)
    return results
