# Running VelocityAI

## Prerequisites

- Python 3.10+
- Claude CLI installed and authenticated (`claude --version`)
- `.env` file present in the project root (ask a teammate for values)

## First-time setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Seed Qdrant with IndiaMart SOPs (run once)
.venv/bin/python3 scripts/setup_sops.py
```

## Running the app

### Option A — one command (recommended)

```bash
./scripts/start.sh
```

`scripts/start.sh` handles everything: creates the virtualenv if missing, installs dependencies, and starts both the API server and worker in the same terminal. Logs are prefixed with `[server]` and `[worker]`. Press `Ctrl+C` to stop both.

> **Note:** `scripts/start.sh` does **not** run `scripts/setup_sops.py` — complete first-time setup above before using it.

### Option B — two terminals (manual)

**Terminal 1 — API server + UI**

```bash
source .venv/bin/activate
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 — Worker**

```bash
source .venv/bin/activate
.venv/bin/python3 worker.py
```

The worker polls the SQLite job queue every 5 seconds and spawns a `claude --print` subprocess for each job.

> **Note:** Run only one worker at a time — concurrent workers are not safe with SQLite.

UI is available at: http://localhost:8001

## Smoke test

```bash
# Submit a transcription
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{"transcription": "your call text here", "agent_name": "Test Agent", "caller_id": "optional"}'

# Check job status (replace <job_id> with the ID returned above)
curl http://localhost:8001/api/jobs/<job_id>

# List recent jobs
curl http://localhost:8001/api/jobs

# Health check
curl http://localhost:8001/health
```

## Environment variables

All config is loaded from `.env` in the project root. Key variables:

| Variable | Purpose |
|----------|---------|
| `QDRANT_URL` | Qdrant vector store URL |
| `QDRANT_COLLECTION` | Qdrant collection name |
| `OPENAI_API_KEY` | LiteLLM proxy key (used for embeddings) |
| `OPENAI_API_BASE` | LiteLLM proxy base URL |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail App Password for violation alerts |
| `VIOLATION_EMAIL_TO` | Email address to send alerts to |

## Re-seeding SOPs

If you need to reset and re-seed the Qdrant collection:

```bash
curl -X DELETE http://34.47.255.166:80/collections/indiamart_sops
.venv/bin/python3 scripts/setup_sops.py
```
