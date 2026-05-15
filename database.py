import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            transcription TEXT NOT NULL,
            caller_id   TEXT,
            caller_name TEXT,
            agent_name  TEXT,
            agent_id    TEXT,
            status      TEXT DEFAULT 'pending',
            category    TEXT,
            report      TEXT,
            violations_found INTEGER DEFAULT 0,
            error       TEXT,
            created_at  TEXT,
            updated_at  TEXT
        )
    """)
    # migrate existing DBs that predate these columns
    for col in ("agent_id TEXT", "caller_name TEXT"):
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def create_job(job_id: str, transcription: str, caller_id: str = None, caller_name: str = None, agent_name: str = None, agent_id: str = None):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO jobs (id,transcription,caller_id,caller_name,agent_name,agent_id,status,category,report,violations_found,error,created_at,updated_at) VALUES (?,?,?,?,?,?,'pending',NULL,NULL,0,NULL,?,?)",
        (job_id, transcription, caller_id, caller_name, agent_name, agent_id, now, now),
    )
    conn.commit()
    conn.close()


def get_job(job_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def list_jobs(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(job_id: str, **kwargs):
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    conn = get_conn()
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_job_by_caller_id(caller_id: str) -> dict | None:
    """Return the most recent job for a given caller_id, or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE caller_id=? ORDER BY created_at DESC LIMIT 1",
        (caller_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def claim_next_pending() -> dict | None:
    """Atomically mark the oldest pending job as processing and return it."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE jobs SET status='processing', updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), row["id"]),
        )
        conn.commit()
    conn.close()
    return dict(row) if row else None
