"""
VelocityAI — SOP Compliance Checker API
POST /api/transcription  → submit a call transcription as a job
GET  /api/jobs/{job_id}  → poll job status and fetch the report
GET  /api/jobs           → list recent jobs
GET  /health             → liveness probe
"""
import json
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from database import create_job, get_job, init_db, list_jobs

app = FastAPI(
    title="VelocityAI SOP Compliance Checker",
    description="Submit call transcriptions for automated IndiaMart SOP compliance analysis.",
    version="1.0.0",
)


@app.on_event("startup")
def startup():
    init_db()


# ── request / response models ────────────────────────────────────────────────

class TranscriptionRequest(BaseModel):
    transcription: str
    caller_id: Optional[str] = None
    agent_name: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    category: Optional[str] = None
    violations_found: bool = False
    report: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_response(row: dict) -> JobResponse:
    report = None
    if row.get("report"):
        try:
            report = json.loads(row["report"])
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

    job_id = str(uuid.uuid4())
    create_job(
        job_id=job_id,
        transcription=req.transcription,
        caller_id=req.caller_id,
        agent_name=req.agent_name,
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
