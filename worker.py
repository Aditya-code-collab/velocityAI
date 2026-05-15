"""
Worker process — polls SQLite for pending jobs and dispatches each one
to a fresh `claude --print` subprocess for compliance analysis.
"""
import json
import logging
import os
import re
import subprocess
import sys
import time

from agent_prompt import build_prompt
from config import PROJECT_DIR, WORKER_POLL_INTERVAL
from database import claim_next_pending, init_db, update_job
from qdrant_helper import ensure_reports_collection, search_sops, store_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
VENV_PYTHON = os.path.join(PROJECT_DIR, ".venv", "bin", "python3")

_REPORT_RE = re.compile(
    r"COMPLIANCE_REPORT_START\s*(\{.*?\})\s*COMPLIANCE_REPORT_END",
    re.DOTALL,
)


def extract_report(output: str) -> dict:
    m = _REPORT_RE.search(output)
    if m:
        return json.loads(m.group(1))
    # Fallback: grab the last {...} block that looks like our schema
    candidates = re.findall(r'\{[^{}]*"category"[^{}]*\}', output, re.DOTALL)
    if candidates:
        return json.loads(candidates[-1])
    raise ValueError("Could not find compliance report in agent output")


def run_claude_agent(prompt: str) -> tuple[str, str, int]:
    """Spawn a new claude --print session and return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [
            CLAUDE_BIN,
            "--print",
            "--allowedTools", "Bash",
            "--dangerously-skip-permissions",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        cwd=PROJECT_DIR,
        env={**os.environ},
    )
    return proc.stdout, proc.stderr, proc.returncode


def process_job(job: dict):
    job_id = job["id"]
    transcription = job["transcription"]
    log.info("Processing job %s", job_id)

    try:
        # Retrieve relevant SOPs from Qdrant
        sops = search_sops(transcription, top_k=3)
        if not sops:
            raise RuntimeError("No SOPs found in Qdrant — run setup_sops.py first")

        log.info("Found %d SOP(s) — top category: %s (score %.3f)",
                 len(sops), sops[0]["category"], sops[0]["score"])

        prompt = build_prompt(job_id, transcription, sops)

        log.info("Spawning claude agent for job %s ...", job_id)
        stdout, stderr, rc = run_claude_agent(prompt)

        if rc != 0:
            log.warning("claude exited %d\nstderr: %s", rc, stderr[:500])

        report = extract_report(stdout)
        violations_found = bool(report.get("violations_found", False))

        update_job(
            job_id,
            status="completed",
            category=report.get("category"),
            report=json.dumps(report),
            violations_found=int(violations_found),
        )

        try:
            store_report(job, report)
            log.info("Report %s stored in Qdrant", job_id)
        except Exception as qdrant_exc:
            log.warning("Could not store report in Qdrant: %s", qdrant_exc)

        log.info(
            "Job %s done — category=%s violations=%s score=%s",
            job_id,
            report.get("category"),
            violations_found,
            report.get("compliance_score"),
        )

    except Exception as exc:
        log.error("Job %s failed: %s", job_id, exc, exc_info=True)
        update_job(job_id, status="failed", error=str(exc))


def main():
    init_db()
    ensure_reports_collection()
    log.info("Worker started (poll interval: %ds)", WORKER_POLL_INTERVAL)
    while True:
        job = claim_next_pending()
        if job:
            process_job(job)
        else:
            time.sleep(WORKER_POLL_INTERVAL)


if __name__ == "__main__":
    main()
