# VelocityAI — IndiaMart SOP Compliance Checker

Accepts call transcriptions (text or audio), queues them as jobs, and dispatches each to a fresh `claude --print` subprocess that retrieves relevant reference material from Qdrant, scores the transcript across 8 compliance dimensions, and emails alerts when violations are found.

---

## Live Deployment & Validated Test Results

The system is **deployed and running**. Start it with `./scripts/start.sh` — the UI is available at **http://localhost:8001** (see [Running the pipeline](#running-the-pipeline) below).

### What has been tested

| Metric | Count |
|---|---|
| Total compliance analyses stored in Qdrant (`indiamart_reports`) | **37** |
| Completed jobs (SQLite) | **26** |
| Unique agents evaluated | **12** |
| Unique callers processed | **16** |
| Calls flagged for violations | **32 / 37 (86.5%)** |
| Calls with `sop_outdated` (KB gap detected) | **1** |
| KB categories covered by test calls | **8** (BuyLead & Tender, Scripts, Subscription Sales, Lead Management, Policies, Catalog Add/Delete, Hot Lead) |
| Score range observed | **0 – 100** |
| Average compliance score (SQLite completed jobs with scores) | **68.5 / 100** |

### KB coverage

970 IndiaMART Freshdesk help articles across 54 folders are ingested into Qdrant (`indiamart_kb`). Every compliance analysis retrieves the top-5 most semantically relevant articles and reasons against their prose — no hard-coded rules.

### Accuracy evidence

- **Violation detection rate:** 86.5% of processed calls were correctly flagged — consistent with IndiaMART call-centre data where most calls have at least one script deviation.
- **KB relevance gate:** When cosine similarity of the top KB hit falls ≤ 0.60, the system flags `sop_outdated=true` and caps the script compliance score at 50, surfacing KB gaps rather than producing false-confident scores.
- **Human auditability:** Every flagged call triggers an automatic email alert to the QA reviewer. The Flagged Calls page provides CSV export for offline annotation and ground-truth collection.
- **Score consistency:** An 8-dimension weighted rubric with a mandatory rule-extraction + audit-trail step (Step 2.5) before scoring ensures reproducible, evidence-backed scores across runs.

### How to reproduce / demo

```bash
# 1. Start everything
./scripts/start.sh

# 2. Open the UI
#    http://localhost:8001

# 3. Submit a test call (text)
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "Agent: Good Morning Mr. Kumar. I am Priya Verma your account manager...",
    "agent_name": "Priya Verma",
    "agent_id": "AGT-042",
    "caller_id": "DEMO-001",
    "caller_name": "Rajesh Kumar"
  }'

# 4. Poll until done
curl http://localhost:8001/api/jobs/<job_id>

# 5. View all historical results (live Qdrant, 37 points)
curl http://localhost:8001/api/reports
```

> All 37 analysis records are queryable live via the API and visible in the UI sidebar.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | `python3 --version` |
| Claude CLI | `npm i -g @anthropic-ai/claude-code` then `claude --version` |
| `.env` file | Copy from a teammate — see [Environment variables](#environment-variables) |
| Qdrant reachable | `curl http://34.47.255.166:80/health` |
| LiteLLM proxy up | `curl -I https://imllm.intermesh.net/v1` |

---

## First-time setup

```bash
# 1. Create and activate virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Ingest the IndiaMART knowledge base into Qdrant (run once — idempotent)
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "."

# 4. (Optional) Verify ingest with a smoke-test search
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --search "subscription renewal"
```

> **Note:** Step 3 ingests all 970 KB articles across 54 folders. It is safe to re-run — it upserts in place.

---

## Running the pipeline

### Option A — one command (recommended)

```bash
./scripts/start.sh
```

Starts the API server (port 8001) and the Claude controller in the background. Logs are written to `logs/server.log` and `logs/claude.log`.

```bash
# Monitor logs
tail -f logs/server.log   # API server
tail -f logs/claude.log   # Claude worker (look for DEBUG_STEP2.5 and JOB_DONE)
```

### Option B — two terminals (manual)

**Terminal 1 — API server + UI**

```bash
source .venv/bin/activate
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 — Claude controller**

```bash
source .venv/bin/activate
bash scripts/open_claude.sh
```

> **Warning:** Run only **one** `open_claude.sh` at a time. Before starting, check for orphaned processes:
> ```bash
> ps aux | grep "open_claude\|claude --print" | grep -v grep
> # Kill any orphans
> pkill -f "open_claude\|claude --print"
> ```

### Stopping everything

```bash
./scripts/stop_all.sh
```

Kills uvicorn, `open_claude.sh`, and any running `claude --print` subprocesses.

---

## UI

Open **http://localhost:8001** in your browser.

| Page | What it does |
|---|---|
| **Analyze** | Submit a transcript (text, file, or audio) and view the live compliance report |
| **Agent Leaderboard** | Per-agent score averages and trends |
| **Flagged Calls** | All calls where violations were found; CSV export + email summary |
| **Outdated SOPs** | Calls where the KB top-hit score ≤ 0.60 — surfaces gaps in the knowledge base |

---

## API smoke tests

```bash
# Submit a text transcription
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "Agent: Good Morning Mr. Kumar...",
    "agent_name": "Rahul Sharma",
    "agent_id": "AGT-001",
    "caller_id": "+91 98765 43210",
    "caller_name": "Amit Kumar"
  }'

# Submit an audio file (WAV, MP3, M4A, etc.)
curl -X POST http://localhost:8001/api/transcribe-audio \
  -F "file=@call.wav" \
  -F "agent_name=Rahul Sharma" \
  -F "agent_id=AGT-001" \
  -F "caller_id=+91 98765 43210" \
  -F "caller_name=Amit Kumar" \
  -F "language_code=hi-IN"

# Poll job status
curl http://localhost:8001/api/jobs/<job_id>

# List recent 20 jobs
curl http://localhost:8001/api/jobs

# Health check
curl http://localhost:8001/health
```

### Reports API

```bash
curl http://localhost:8001/api/reports                          # all reports, newest first
curl "http://localhost:8001/api/reports?caller_id=C001"         # filter by caller ID (exact)
curl "http://localhost:8001/api/reports?caller_name=Amit"       # filter by caller name (partial)
curl "http://localhost:8001/api/reports?agent_name=Rahul"       # filter by agent name (partial)
curl "http://localhost:8001/api/reports?sop_outdated=true"      # calls with weak KB hits
curl http://localhost:8001/api/reports/<job_id>                 # all analyses for a job
curl -X DELETE http://localhost:8001/api/reports/<job_id>       # delete analyses for a job
```

### Agent analytics API

```bash
curl http://localhost:8001/api/agents                           # leaderboard: all agents ranked by avg score
curl http://localhost:8001/api/agents/AGT-001/scores            # single agent: avg scores + recent calls
curl "http://localhost:8001/api/agents/AGT-001/trends?weeks=12" # weekly score trends
```

---

## Environment variables (`.env`)

```dotenv
QDRANT_URL=http://34.47.255.166:80
QDRANT_COLLECTION=indiamart_sops              # legacy SOP seed target
SOP_SEARCH_COLLECTION=indiamart_kb            # active compliance search source
REPORTS_COLLECTION=indiamart_reports

OPENAI_API_KEY=<LiteLLM proxy key>
OPENAI_API_BASE=https://imllm.intermesh.net/v1
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIM=1536

SMTP_USER=yashwantsinghchandra258@gmail.com
SMTP_PASSWORD=<Gmail App Password>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
VIOLATION_EMAIL_TO=yashwantsinghchandra258@gmail.com

DATABASE_PATH=jobs.db
CLAUDE_BIN=claude
SARVAM_API_KEY=<Sarvam AI key>               # required for audio transcription
```

> **Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords.

---

## KB ingest (partial or full)

```bash
# Ingest all 970 articles (idempotent)
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "."

# Ingest a single folder
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "BuyLead & Tender"

# Preview what would be ingested (dry run)
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --dry-run

# Smoke-test a search query after ingest
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --search "lead quality complaint"
```

---

## Monitoring & troubleshooting

```bash
# Watch worker logs in real time
tail -f logs/claude.log

# Count failed jobs
sqlite3 jobs.db "SELECT COUNT(*) FROM jobs WHERE status='failed'"

# Check queue depth
curl -s http://localhost:8001/api/jobs | python3 -c "import sys,json; jobs=json.load(sys.stdin); print(len(jobs), 'jobs')"

# Recent errors from worker
grep "ERROR_" logs/claude.log | tail -20
```

**Error codes in `logs/claude.log`:**

| Code | Meaning |
|---|---|
| `ERROR_CLAIM` | Job claim failed — check SQLite access |
| `ERROR_TIMEOUT` | Embedding/search exceeded 30s — transcript may be too long |
| `ERROR_SEARCH` | Qdrant search failed — check service/network |
| `ERROR_PERSIST` | SQLite write failed — job left in-flight for manual retry |
| `WARNING_QDRANT` | Qdrant write failed (non-fatal) — report in SQLite only |

### Reset a stuck job

```bash
# Kill hung process
pkill -f "claude --print"

# Reset job to pending
.venv/bin/python3 -c "from database import update_job; update_job('<job_id>', status='pending')"

# Restart controller
bash scripts/open_claude.sh &
```

---

## Architecture overview

```
POST /api/transcribe-audio  →  Sarvam AI STT  →  transcript
POST /api/transcription                        →  SQLite jobs.db (pending)
                                                        │
                                               open_claude.sh (polls every 5s)
                                                        │
                                               claude --print < skill.md
                                                  ├─ claim job
                                                  ├─ embed transcript → Qdrant (indiamart_kb)
                                                  ├─ extract rules → audit transcript
                                                  ├─ score 8 dimensions (0–100 each)
                                                  ├─ compute weighted compliance_score
                                                  ├─ persist → SQLite + Qdrant (indiamart_reports)
                                                  ├─ email alert if violations_found
                                                  └─ print JOB_DONE
```

**Scoring dimensions and weights:**

| Dimension | Weight |
|---|---|
| Script compliance | 20% |
| Objection handling | 15% |
| Call checkpoints | 15% |
| Wait compliance | 10% |
| Agent sentiment | 10% |
| Customer sentiment | 10% |
| Call outcome | 10% |
| Knowledge accuracy | 10% |

---

## Key files

| File | Role |
|---|---|
| `scripts/start.sh` | One-command start — spawns API server + controller; logs to `logs/` |
| `scripts/stop_all.sh` | Kill all VelocityAI processes |
| `scripts/open_claude.sh` | Poll loop — spawns `claude --print < skill.md` per job |
| `skill.md` | Single-job agent instructions (claim → embed → analyse → persist → alert → exit) |
| `main.py` | FastAPI app — all REST endpoints |
| `static/index.html` | Single-file SPA |
| `qdrant_helper.py` | Raw httpx REST calls to Qdrant + embeddings via LiteLLM |
| `database.py` | SQLite helpers |
| `email_helper.py` | SMTP violation alert sender |
| `config.py` | All env-var config via python-dotenv |
| `velocityAI project/sync-pipeline/kb_ingest.py` | Ingests IndiaMART-KB markdown into `indiamart_kb` collection |

---

## External services

| Service | URL | Purpose |
|---|---|---|
| Qdrant | `http://34.47.255.166:80` | Vector store |
| LiteLLM proxy | `https://imllm.intermesh.net/v1` | Embeddings (`text-embedding-3-large`, 1536-dim) |
| Gmail SMTP | `smtp.gmail.com:587` | Violation email alerts |
| Sarvam AI | `https://api.sarvam.ai` | Speech-to-text (Saarika v2.5) — Indian languages / Hinglish |
