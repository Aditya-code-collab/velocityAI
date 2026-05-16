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
        key=lambda p: p.get("created_at") or "",
        reverse=True,
    )
    next_offset = result.get("next_page_offset")
    return points, next_offset


def get_reports_by_filter(caller_id: str | None = None, caller_name: str | None = None, agent_name: str | None = None) -> list[dict]:
    """Fetch analyses filtered by caller_id (exact), caller_name and/or agent_name (partial, case-insensitive).

    All filters applied together (AND).
    """
    body: dict = {"limit": 100, "with_payload": True, "with_vector": False}
    if caller_id:
        body["filter"] = {"must": [{"key": "caller_id", "match": {"value": caller_id}}]}

    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    payloads = [p["payload"] for p in r.json()["result"].get("points", [])]

    # partial case-insensitive matches in Python
    if caller_name:
        needle = caller_name.lower()
        payloads = [p for p in payloads if needle in (p.get("caller_name") or "").lower()]
    if agent_name:
        needle = agent_name.lower()
        payloads = [p for p in payloads if needle in (p.get("agent_name") or "").lower()]

    return sorted(payloads, key=lambda p: p.get("created_at") or "")


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
    return sorted(payloads, key=lambda p: p.get("created_at") or "")


def get_agent_scores(agent_id: str = None, agent_name: str = None) -> dict:
    """Aggregate per-dimension scores across all reports for an agent.

    Returns { agent_name, agent_id, total_calls, avg_scores: {dim: avg}, recent_calls: [...] }
    """
    body: dict = {"limit": 200, "with_payload": True, "with_vector": False}
    must = []
    if agent_id:
        must.append({"key": "agent_id", "match": {"value": agent_id}})
    if must:
        body["filter"] = {"must": must}

    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    payloads = [p["payload"] for p in r.json()["result"].get("points", [])]

    if agent_name and not agent_id:
        needle = agent_name.lower()
        payloads = [p for p in payloads if needle in (p.get("agent_name") or "").lower()]

    if not payloads:
        return {"agent_name": agent_name, "agent_id": agent_id, "total_calls": 0, "avg_scores": {}, "recent_calls": []}

    dims = ["script_compliance", "objection_handling", "call_checkpoints",
            "wait_compliance", "agent_sentiment", "customer_sentiment",
            "call_outcome", "knowledge_accuracy"]
    sums = {d: 0 for d in dims}
    counts = {d: 0 for d in dims}

    for p in payloads:
        scores = p.get("scores", {})
        for d in dims:
            if d in scores and scores[d] is not None:
                sums[d] += scores[d]
                counts[d] += 1

    avg_scores = {d: round(sums[d] / counts[d], 1) if counts[d] > 0 else None for d in dims}
    avg_overall = round(sum(v for v in avg_scores.values() if v is not None) / max(sum(1 for v in avg_scores.values() if v is not None), 1), 1)

    sorted_payloads = sorted(payloads, key=lambda p: p.get("created_at") or "", reverse=True)

    return {
        "agent_name": sorted_payloads[0].get("agent_name") if sorted_payloads else agent_name,
        "agent_id": sorted_payloads[0].get("agent_id") if sorted_payloads else agent_id,
        "total_calls": len(payloads),
        "avg_compliance_score": avg_overall,
        "avg_scores": avg_scores,
        "recent_calls": sorted_payloads[:10],
    }


def get_all_agents_summary() -> list[dict]:
    """Return aggregated scores for all agents, sorted by avg compliance score."""
    body: dict = {"limit": 500, "with_payload": True, "with_vector": False}
    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    payloads = [p["payload"] for p in r.json()["result"].get("points", [])]

    # Group by agent_id
    agents: dict[str, list] = {}
    for p in payloads:
        aid = p.get("agent_id") or p.get("agent_name") or "unknown"
        agents.setdefault(aid, []).append(p)

    dims = ["script_compliance", "objection_handling", "call_checkpoints",
            "wait_compliance", "agent_sentiment", "customer_sentiment",
            "call_outcome", "knowledge_accuracy"]

    results = []
    for aid, reports in agents.items():
        sums = {d: 0 for d in dims}
        counts = {d: 0 for d in dims}
        for p in reports:
            scores = p.get("scores", {})
            for d in dims:
                if d in scores and scores[d] is not None:
                    sums[d] += scores[d]
                    counts[d] += 1
        avg_scores = {d: round(sums[d] / counts[d], 1) if counts[d] > 0 else None for d in dims}
        valid = [v for v in avg_scores.values() if v is not None]
        avg_overall = round(sum(valid) / len(valid), 1) if valid else 0

        results.append({
            "agent_id": reports[0].get("agent_id") or aid,
            "agent_name": reports[0].get("agent_name") or "Unknown",
            "total_calls": len(reports),
            "avg_compliance_score": avg_overall,
            "avg_scores": avg_scores,
            "last_call": max((p.get("created_at") or "" for p in reports), default=""),
        })

    return sorted(results, key=lambda x: x["avg_compliance_score"], reverse=True)


def get_agent_trends(agent_id: str, weeks: int = 12) -> dict:
    """Return weekly score trends for an agent over the last N weeks.

    Returns { agent_id, weeks: [ { week_start, week_end, call_count, avg_scores, avg_overall } ] }
    """
    from datetime import datetime, timedelta

    body: dict = {"limit": 500, "with_payload": True, "with_vector": False}
    if agent_id:
        body["filter"] = {"must": [{"key": "agent_id", "match": {"value": agent_id}}]}

    r = _http_client().post(f"/collections/{REPORTS_COLLECTION}/points/scroll", json=body)
    r.raise_for_status()
    payloads = [p["payload"] for p in r.json()["result"].get("points", [])]

    if not payloads:
        return {"agent_id": agent_id, "weeks": []}

    dims = ["script_compliance", "objection_handling", "call_checkpoints",
            "wait_compliance", "agent_sentiment", "customer_sentiment",
            "call_outcome", "knowledge_accuracy"]

    # Build weekly buckets
    now = datetime.utcnow()
    week_start = now - timedelta(weeks=weeks)

    # Group payloads by ISO week
    weekly: dict[str, list] = {}
    for p in payloads:
        created = p.get("created_at", "")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(created.replace("Z", ""))
        except Exception:
            continue
        if dt < week_start:
            continue
        # ISO week key: "2026-W20"
        iso_year, iso_week, _ = dt.isocalendar()
        wk = f"{iso_year}-W{iso_week:02d}"
        weekly.setdefault(wk, []).append(p)

    # Compute averages per week
    result_weeks = []
    for wk in sorted(weekly.keys()):
        reports = weekly[wk]
        sums = {d: 0 for d in dims}
        counts = {d: 0 for d in dims}
        for p in reports:
            scores = p.get("scores", {})
            for d in dims:
                if d in scores and scores[d] is not None:
                    sums[d] += scores[d]
                    counts[d] += 1
        avg_scores = {d: round(sums[d] / counts[d], 1) if counts[d] > 0 else None for d in dims}
        valid = [v for v in avg_scores.values() if v is not None]
        avg_overall = round(sum(valid) / len(valid), 1) if valid else None

        # Compute week start/end dates from ISO week
        import datetime as dt_mod
        iso_year, iso_week_num = int(wk.split("-W")[0]), int(wk.split("-W")[1])
        wk_start_date = dt_mod.date.fromisocalendar(iso_year, iso_week_num, 1)
        wk_end_date = wk_start_date + timedelta(days=6)

        result_weeks.append({
            "week": wk,
            "week_start": wk_start_date.isoformat(),
            "week_end": wk_end_date.isoformat(),
            "call_count": len(reports),
            "avg_scores": avg_scores,
            "avg_overall": avg_overall,
        })

    return {"agent_id": agent_id, "weeks": result_weeks}


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
            "agent_id": job.get("agent_id"),
            "caller_id": job.get("caller_id"),
            "caller_name": job.get("caller_name"),
            "created_at": datetime.utcnow().isoformat(),
            "category": report.get("category"),
            "violations_found": bool(report.get("violations_found", False)),
            "human_review_required": bool(report.get("human_review_required", False)),
            "sop_outdated": bool(report.get("sop_outdated", False)),
            "compliance_score": report.get("compliance_score"),
            "violations": report.get("violations", []),
            "compliance_summary": summary,
            "recommendation": recommendation,
            # ── per-dimension scores ──
            "scores": report.get("scores", {}),
            "score_reasons": report.get("score_reasons", {}),
            "checkpoints": report.get("checkpoints", {}),
            "call_outcome_type": report.get("call_outcome_type"),
            "customer_sentiment_trajectory": report.get("customer_sentiment_trajectory"),
        },
    }
    r = _http_client().put(
        f"/collections/{REPORTS_COLLECTION}/points",
        json={"points": [point]},
    )
    r.raise_for_status()
