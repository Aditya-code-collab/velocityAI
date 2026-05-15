# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VelocityAI** — IndiaMart SOP Compliance Checker. Accepts call transcriptions via REST API, queues them as jobs, and dispatches each job to a fresh `claude --print` subprocess that retrieves relevant SOPs from Qdrant, checks the transcription for violations, generates a structured report, and emails alerts when violations are found.

## Commands

> For a full step-by-step guide see [`run.md`](run.md).

```bash
# Start everything with one command (recommended)
./start.sh

# --- or manually ---

# Create and activate virtualenv
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Seed Qdrant with IndiaMart SOPs (run once, or after editing setup_sops.py)
.venv/bin/python3 setup_sops.py

# Start API server (port 8001) — UI served at http://localhost:8001
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Start worker (separate terminal — run only one at a time)
.venv/bin/python3 worker.py

# Smoke test
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{"transcription": "your call text here", "agent_name": "Test Agent", "caller_id": "optional"}'

curl http://localhost:8001/api/jobs/<job_id>
curl http://localhost:8001/api/jobs          # list recent 20 jobs
curl http://localhost:8001/health            # liveness probe
```

## Architecture

```
POST /api/transcription
        │
        ▼
    SQLite jobs.db          ← status: pending → processing → completed/failed
        │
        ▼
  worker.py (poll every 5s)
        │
        ├─ 1. embed transcription  → LiteLLM proxy (openai/text-embedding-3-large, 1536-dim)
        ├─ 2. search Qdrant REST   → top-3 SOPs by cosine similarity
        ├─ 3. build prompt         → agent_prompt.py
        │
        ▼
  claude --print subprocess  (new process per job, 300s timeout)
        │   flags: --allowedTools Bash --dangerously-skip-permissions
        │
        ├─ picks best-matching SOP category
        ├─ checks each rule against transcription (language reasoning, not vector search)
        ├─ optionally: Bash tool → python3 email_helper.py (SMTP alert)
        └─ outputs JSON between COMPLIANCE_REPORT_START / COMPLIANCE_REPORT_END markers
        │
        ▼
  worker.py parses report → saves to SQLite
        │
        ▼
GET /api/jobs/{job_id}  → report + violations + compliance_score
```

**Important:** Only run one worker at a time. `claim_next_pending()` in `database.py` uses a read-then-update pattern that is not safe for concurrent workers under SQLite.

## Qdrant — Store and Fetch

Each SOP is one Qdrant point:

```
vector  = embed(description)          ← 1536-dim float array

payload fields:
  category     string   catalog_addition | catalog_deletion |
                        subscription_sales | lead_management | payment_collection
  title        string   human-readable SOP name
  content      string   2–3 sentence overview
  description  string   full embedding text (title + overview + rules + call phrases)
  rules        string[] enforceable rule strings (7–9 per SOP)
  keywords     string[] stored but not used in search
```

### Two-stage matching

| Stage | Method |
|-------|--------|
| **Category selection** | Cosine similarity: `embed(transcription)` vs `embed(description)` in Qdrant |
| **Rule violation check** | Claude language reasoning on each rule string vs full transcription |

`search_sops` returns top-3 hits but only passes `rules[]` from the top hit to the agent — runner-up rules are discarded immediately.

## What the Claude agent receives

```
=== JOB ID ===  /  === CALL TRANSCRIPTION ===  /  === RETRIEVED SOPs ===
  → top SOP: title, category, score, content, numbered rules
  → runner-up categories (label + score only, for category confirmation)

=== INSTRUCTIONS ===
  1. Confirm best-matching category
  2. Check each rule against transcription
  3. For violations: rule + what went wrong + verbatim quote as evidence
  4. Compute compliance_score (0–100)
  5. Write summary and recommendation

=== EMAIL === (pre-filled bash command — agent runs only if violations found)

=== OUTPUT FORMAT ===
COMPLIANCE_REPORT_START
{ ...JSON report... }
COMPLIANCE_REPORT_END
```

Worker parses the report using `COMPLIANCE_REPORT_START/END` markers, with a fallback regex that grabs the last `{..."category"...}` block if markers are absent.

## Frontend

`static/index.html` is a single-file vanilla JS SPA served at `GET /` by FastAPI (`StaticFiles` mount + `FileResponse`). No build step.

**Layout — two-column:**
- **Left panel:** submit form (file upload drop zone + manual textarea + Agent Name / Caller ID) and a recent-jobs sidebar (last 30, color-coded dots, click to load)
- **Right panel:** live compliance report — score ring, violations with evidence quotes, summary, recommendation

**Key JS behaviours:**
- On submit → `POST /api/transcription` → starts a `setInterval` polling `GET /api/jobs/{id}` every 2s until `completed` or `failed`
- File drop zone (`#dropZone`) accepts `.txt`, `.log`, `.csv` via click-browse or drag-and-drop; reads with `FileReader` and populates the textarea
- Recent jobs list auto-refreshes every 10s
- Score ring colour: green ≥ 80, amber ≥ 50, red < 50

To add a new section to the report, update both `agent_prompt.py` (add the field to the JSON output format) and the `renderReport()` function in `index.html`.

## Key files

| File | Role |
|------|------|
| `run.md` | Step-by-step guide for setting up and running the app |
| `start.sh` | One-command script to start the API server and worker together |
| `main.py` | FastAPI app — `POST /api/transcription`, `GET /api/jobs/{id}`, `GET /api/jobs`, `GET /health`, `GET /` (serves UI) |
| `static/index.html` | Single-file SPA — submit form, live polling, report renderer |
| `worker.py` | Polls SQLite every 5s, spawns `claude --print` subprocess per job |
| `agent_prompt.py` | Builds the full compliance analysis prompt |
| `qdrant_helper.py` | Raw `httpx` REST calls to Qdrant + OpenAI embeddings via LiteLLM proxy |
| `database.py` | SQLite helpers — `init_db`, `create_job`, `claim_next_pending`, `update_job`, `get_job`, `list_jobs` |
| `email_helper.py` | CLI-callable SMTP sender: `python3 email_helper.py --to --subject --body` |
| `setup_sops.py` | One-time seed — upserts 5 IndiaMart SOPs into Qdrant |
| `config.py` | All env-var config via `python-dotenv`; exposes `PROJECT_DIR` |

## External services

| Service | URL | Purpose |
|---------|-----|---------|
| Qdrant | `http://34.47.255.166:80` | Vector store (collection: `indiamart_sops`) |
| LiteLLM proxy | `https://imllm.intermesh.net/v1` | Embeddings (`openai/text-embedding-3-large`, 1536-dim) |
| Gmail SMTP | `smtp.gmail.com:587` | Violation email alerts |

## Report schema

```json
{
  "job_id": "...",
  "category": "subscription_sales",
  "violations_found": true,
  "violations": [
    { "rule": "...", "description": "...", "evidence": "<verbatim quote>" }
  ],
  "compliance_score": 0,
  "compliance_summary": "...",
  "recommendation": "..."
}
```

## Environment variables (`.env`)

```
QDRANT_URL=http://34.47.255.166:80
QDRANT_COLLECTION=indiamart_sops
OPENAI_API_KEY=<LiteLLM key>
OPENAI_API_BASE=https://imllm.intermesh.net/v1
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIM=1536
SMTP_USER=yashwantsinghchandra258@gmail.com
SMTP_PASSWORD=<Gmail app password>
SMTP_HOST=smtp.gmail.com         # optional, default shown
SMTP_PORT=587                    # optional, default shown
VIOLATION_EMAIL_TO=yashwantsinghchandra258@gmail.com
DATABASE_PATH=jobs.db            # optional, default shown
WORKER_POLL_INTERVAL=5           # optional, seconds
CLAUDE_BIN=claude                # optional, path to claude binary
```

## Notes

- `claude --print` reads auth from the system keychain — do **not** use `--bare`.
- `qdrant_helper.py` uses raw `httpx` calls — do not switch to the `qdrant-client` library (v1.18 is incompatible with server v1.9.2).
- Qdrant must be addressed as `http://34.47.255.166:80` (explicit port 80) — omitting it causes the client to append `:6333`.
- Email requires a Gmail **App Password**: Google Account → Security → 2-Step Verification → App passwords.
- To re-seed SOPs: `curl -X DELETE http://34.47.255.166:80/collections/indiamart_sops` then `python3 setup_sops.py`.
