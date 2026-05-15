"""
VelocityAI — SOP Compliance Checker API
POST /api/transcription  → submit a call transcription as a job
GET  /api/jobs/{job_id}  → poll job status and fetch the report
GET  /api/jobs           → list recent jobs
GET  /health             → liveness probe
"""
import io
import json
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import SARVAM_API_KEY, VIOLATION_EMAIL_TO
from database import create_job, get_job, get_job_by_caller_id, init_db, list_jobs, update_job
from email_helper import send_email
from qdrant_helper import delete_report, get_report, get_reports_by_filter, list_reports, get_agent_scores, get_all_agents_summary

app = FastAPI(
    title="VelocityAI SOP Compliance Checker",
    description="Submit call transcriptions for automated IndiaMart SOP compliance analysis.",
    version="1.0.0",
)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return FileResponse("static/index.html")


# ── request / response models ────────────────────────────────────────────────

class TranscriptionRequest(BaseModel):
    transcription: str
    caller_id: str
    caller_name: str
    agent_name: str
    agent_id: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    category: Optional[str] = None
    violations_found: bool = False
    report: Optional[list] = None   # list of per-analysis report dicts, newest last
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_response(row: dict) -> JobResponse:
    report = None
    if row.get("report"):
        try:
            parsed = json.loads(row["report"])
            # normalise: old jobs stored a single dict; new ones store a list
            report = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            pass
    return JobResponse(
        job_id=row["id"],
        status=row["status"],
        category=row.get("category"),
        violations_found=bool(row.get("violations_found", 0)),
        report=report,
        error=row.get("error"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ── endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/transcription", response_model=JobResponse, status_code=202)
def submit_transcription(req: TranscriptionRequest):
    """Queue a call transcription for compliance analysis."""
    if not req.transcription.strip():
        raise HTTPException(status_code=400, detail="transcription cannot be empty")
    if not req.agent_name.strip():
        raise HTTPException(status_code=400, detail="agent_name is required")
    if not req.agent_id.strip():
        raise HTTPException(status_code=400, detail="agent_id is required")
    if not req.caller_id.strip():
        raise HTTPException(status_code=400, detail="caller_id is required")
    if not req.caller_name.strip():
        raise HTTPException(status_code=400, detail="caller_name is required")

    # reuse existing job_id when caller_id matches a previous job
    if req.caller_id:
        existing = get_job_by_caller_id(req.caller_id)
        if existing:
            update_job(
                existing["id"],
                transcription=req.transcription,
                caller_name=req.caller_name,
                agent_name=req.agent_name,
                agent_id=req.agent_id,
                status="pending",
                error=None,
            )
            return JobResponse(job_id=existing["id"], status="pending")

    job_id = str(uuid.uuid4())
    create_job(
        job_id=job_id,
        transcription=req.transcription,
        caller_id=req.caller_id,
        caller_name=req.caller_name,
        agent_name=req.agent_name,
        agent_id=req.agent_id,
    )
    return JobResponse(job_id=job_id, status="pending")


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str):
    """Fetch a job's current status and compliance report (once completed)."""
    row = get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _row_to_response(row)


@app.get("/api/jobs", response_model=list[JobResponse])
def list_recent_jobs(limit: int = 20):
    """List the most recent jobs (default 20)."""
    return [_row_to_response(r) for r in list_jobs(limit)]


# ── Sarvam AI — audio transcription ─────────────────────────────────────────

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


@app.post("/api/transcribe-audio", response_model=JobResponse, status_code=202)
async def transcribe_audio(
    file: UploadFile,
    agent_name: str = Form(...),
    agent_id: str = Form(...),
    caller_id: str = Form(...),
    caller_name: str = Form(...),
    language_code: str = Form("unknown"),
):
    """Accept an audio file, transcribe it via Sarvam AI, then queue the result for compliance analysis."""
    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="SARVAM_API_KEY is not configured")

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                SARVAM_STT_URL,
                headers={"api-subscription-key": SARVAM_API_KEY},
                files={"file": (file.filename or "audio", audio_bytes, file.content_type or "audio/wav")},
                data={"model": "saarika:v2.5", "language_code": language_code},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Sarvam STT error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Sarvam STT unreachable: {e}")

    transcript = resp.json().get("transcript", "").strip()
    if not transcript:
        raise HTTPException(status_code=502, detail="Sarvam STT returned an empty transcript")

    # reuse existing job when caller_id already exists
    existing = get_job_by_caller_id(caller_id)
    if existing:
        update_job(
            existing["id"],
            transcription=transcript,
            caller_name=caller_name,
            agent_name=agent_name,
            agent_id=agent_id,
            status="pending",
            error=None,
        )
        return JobResponse(job_id=existing["id"], status="pending")

    job_id = str(uuid.uuid4())
    create_job(
        job_id=job_id,
        transcription=transcript,
        caller_id=caller_id,
        caller_name=caller_name,
        agent_name=agent_name,
        agent_id=agent_id,
    )
    return JobResponse(job_id=job_id, status="pending")


# ── Qdrant report store ───────────────────────────────────────────────────────

class FlaggedEmailRequest(BaseModel):
    email: Optional[str] = None


@app.post("/api/reports/flagged/email")
def send_flagged_email(req: FlaggedEmailRequest = FlaggedEmailRequest()):
    """Fetch all flagged reports from Qdrant and email a CSV summary."""
    try:
        records, _ = list_reports(limit=500)
        flagged = [r for r in records if r.get("violations_found")]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")

    to = (req.email or "").strip() or VIOLATION_EMAIL_TO

    # Build CSV
    columns = [
        "Caller Name", "Caller ID", "Agent Name", "Agent ID", "Category",
        "Overall Score", "SOP Compliance", "Objection Handling",
        "Call Checkpoints", "Wait Compliance", "Agent Sentiment",
        "Customer Sentiment", "Call Outcome", "Knowledge Accuracy",
        "Summary", "Recommendation", "Timestamp",
    ]

    def csv_val(v):
        s = str(v) if v is not None else ""
        return '"' + s.replace('"', '""') + '"'

    lines = [",".join(csv_val(c) for c in columns)]
    for r in flagged:
        sc = r.get("scores") or {}
        lines.append(",".join(csv_val(v) for v in [
            r.get("caller_name", ""),
            r.get("caller_id", ""),
            r.get("agent_name", ""),
            r.get("agent_id", ""),
            r.get("category", ""),
            r.get("compliance_score", ""),
            sc.get("script_compliance", ""),
            sc.get("objection_handling", ""),
            sc.get("call_checkpoints", ""),
            sc.get("wait_compliance", ""),
            sc.get("agent_sentiment", ""),
            sc.get("customer_sentiment", ""),
            sc.get("call_outcome", ""),
            sc.get("knowledge_accuracy", ""),
            r.get("compliance_summary", ""),
            r.get("recommendation", ""),
            r.get("created_at", ""),
        ]))

    csv_body = "\n".join(lines)

    try:
        send_email(
            to=to,
            subject="VelocityAI — Flagged Calls Report",
            body=csv_body,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Email send failed: {e}")

    return {"sent": True, "count": len(flagged), "to": to}


@app.get("/api/reports")
def list_stored_reports(
    limit: int = 20,
    offset: str | None = None,
    caller_id: str | None = None,
    caller_name: str | None = None,
    agent_name: str | None = None,
):
    """Return stored compliance reports from Qdrant.

    Filter by caller_id, caller_name, agent_name (all partial/exact matches, AND).
    Without filters returns all reports paginated newest-first.
    """
    try:
        if caller_id or caller_name or agent_name:
            records = get_reports_by_filter(caller_id=caller_id, caller_name=caller_name, agent_name=agent_name)
            return {"reports": records, "next_offset": None, "total": len(records)}
        records, next_offset = list_reports(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    return {"reports": records, "next_offset": next_offset}


@app.get("/api/reports/{job_id}")
def get_stored_report(job_id: str):
    """Fetch all compliance analyses for a job_id from Qdrant (oldest first)."""
    try:
        analyses = get_report(job_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    if not analyses:
        raise HTTPException(status_code=404, detail="No reports found for this job in Qdrant")
    return {"job_id": job_id, "analyses": analyses}


@app.delete("/api/reports/{job_id}", status_code=204)
def delete_stored_report(job_id: str):
    """Delete a compliance report from Qdrant by job_id."""
    try:
        delete_report(job_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")


# ── Agent scores dashboard ──────────────────────────────────────────────────

@app.get("/api/agents")
def list_agents_summary():
    """Return aggregated scores for all agents — powers the leaderboard."""
    try:
        agents = get_all_agents_summary()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    return {"agents": agents}


@app.get("/api/agents/{agent_id}/scores")
def get_agent_score_card(agent_id: str):
    """Return detailed scores for a single agent — powers the agent scorecard."""
    try:
        data = get_agent_scores(agent_id=agent_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    if data["total_calls"] == 0:
        raise HTTPException(status_code=404, detail="No reports found for this agent")
    return data
