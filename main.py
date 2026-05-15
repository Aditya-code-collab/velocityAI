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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import create_job, get_job, get_job_by_caller_id, init_db, list_jobs, update_job
from qdrant_helper import delete_report, get_report, get_reports_by_caller, list_reports

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
    caller_id: Optional[str] = None
    agent_name: Optional[str] = None


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

    # reuse existing job_id when caller_id matches a previous job
    if req.caller_id:
        existing = get_job_by_caller_id(req.caller_id)
        if existing:
            update_job(
                existing["id"],
                transcription=req.transcription,
                agent_name=req.agent_name or existing.get("agent_name"),
                status="pending",
                error=None,
            )
            return JobResponse(job_id=existing["id"], status="pending")

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


# ── Qdrant report store ───────────────────────────────────────────────────────

@app.get("/api/reports")
def list_stored_reports(limit: int = 20, offset: str | None = None):
    """Return stored compliance reports from Qdrant (paginated)."""
    try:
        records, next_offset = list_reports(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    return {"reports": records, "next_offset": next_offset}


@app.get("/api/caller/{caller_id}")
def get_caller_history(caller_id: str):
    """Fetch all compliance analyses for a caller_id across all jobs (oldest first)."""
    try:
        analyses = get_reports_by_caller(caller_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant error: {e}")
    if not analyses:
        raise HTTPException(status_code=404, detail="No reports found for this caller")
    return {"caller_id": caller_id, "total": len(analyses), "analyses": analyses}


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
