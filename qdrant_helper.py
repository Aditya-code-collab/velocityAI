"""
Qdrant helper — uses the REST API directly to avoid qdrant-client/server
version compatibility issues (client v1.18 vs server v1.9.2).
"""
import uuid
import httpx
from openai import OpenAI
from config import (
    QDRANT_URL, QDRANT_COLLECTION, SOP_SEARCH_COLLECTION, REPORTS_COLLECTION,
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
    """Semantic search for compliance reference material.

    Reads from SOP_SEARCH_COLLECTION (default: the indiamart_kb help
    articles). KB articles have no `rules[]` field — compliance reasoning
    runs against each hit's `content`. Falls back to `rules[]` when the
    collection is the legacy indiamart_sops (so old behaviour still works
    if SOP_SEARCH_COLLECTION is repointed there).
    """
    vector = embed(transcription)
    r = _http_client().post(
        f"/collections/{SOP_SEARCH_COLLECTION}/points/search",
        json={
            "vector": vector,
            "limit": top_k,
            "with_payload": {
                "include": ["category", "folder", "title", "content", "rules"]
            },
        },
    )
    r.raise_for_status()
    hits = r.json()["result"]
    results = []
    for i, h in enumerate(hits):
        p = h["payload"]
        entry = {
            "category": p.get("category"),
            "folder": p.get("folder"),
            "title": p.get("title"),
            "content": p.get("content"),
            "score": round(h["score"], 4),
            # Legacy SOPs carry rules[]; KB articles don't (reason over content).
            # Rules only needed for the top hit — runner-ups are context only.
            "rules": p.get("rules", []) if i == 0 else [],
        }
        results.append(entry)
    return results


def list_reports(limit: int = 20, offset: str | None = None) -> tuple[list[dict], str | None]:
    """Scroll through stored reports. Returns (records, next_offset)."""
    body: dict = {"limit": limit, "with_payload": True, "with_vector": False}
    if offset:
        body["offset"] = offset
    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    result = r.json()["result"]
    points = sorted(
        [p["payload"] for p in result.get("points", [])],
        key=lambda p: p.get("created_at", ""),
        reverse=True,
    )
    next_offset = result.get("next_page_offset")
    return points, next_offset


def get_report(job_id: str) -> list[dict]:
    """Fetch all analysis points for a job_id, sorted oldest-first."""
    body = {
        "limit": 100,
        "with_payload": True,
        "with_vector": False,
        "filter": {"must": [{"key": "job_id", "match": {"value": job_id}}]},
    }
    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    points = r.json()["result"].get("points", [])
    payloads = [p["payload"] for p in points]
    return sorted(payloads, key=lambda p: p.get("created_at", ""))


def delete_report(job_id: str):
    """Delete all analysis points for a job_id from Qdrant."""
    r = _http_client().post(
        f"/collections/{REPORTS_COLLECTION}/points/delete",
        json={"filter": {"must": [{"key": "job_id", "match": {"value": job_id}}]}},
    )
    r.raise_for_status()


def ensure_reports_collection():
    r = _http_client().get("/collections")
    r.raise_for_status()
    existing = [c["name"] for c in r.json()["result"]["collections"]]
    if REPORTS_COLLECTION not in existing:
        payload = {"vectors": {"size": EMBEDDING_DIM, "distance": "Cosine"}}
        r2 = _http_client().put(f"/collections/{REPORTS_COLLECTION}", json=payload)
        r2.raise_for_status()
        print(f"Created collection: {REPORTS_COLLECTION}")
    else:
        print(f"Collection '{REPORTS_COLLECTION}' already exists")


def store_report(job: dict, report: dict):
    """Embed and persist a single compliance analysis as a new Qdrant point.

    Each call creates a distinct point (analysis_id UUID) so the full history
    for a caller_id is preserved. job_id and caller_id are stored in the
    payload for filtering.
    """
    from datetime import datetime
    summary = report.get("compliance_summary", "")
    recommendation = report.get("recommendation", "")
    embed_text = f"{summary} {recommendation}".strip() or report.get("category", "compliance report")
    vector = embed(embed_text)

    point = {
        "id": str(uuid.uuid4()),   # unique per analysis — never overwrites
        "vector": vector,
        "payload": {
            "job_id": job["id"],
            "agent_name": job.get("agent_name"),
            "caller_id": job.get("caller_id"),
            "created_at": datetime.utcnow().isoformat(),
            "category": report.get("category"),
            "violations_found": bool(report.get("violations_found", False)),
            "compliance_score": report.get("compliance_score"),
            "violations": report.get("violations", []),
            "compliance_summary": summary,
            "recommendation": recommendation,
        },
    }
    r = _http_client().put(
        f"/collections/{REPORTS_COLLECTION}/points",
        json={"points": [point]},
    )
    r.raise_for_status()
