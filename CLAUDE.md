# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@skill.md

## Project Overview

**VelocityAI** — IndiaMart SOP Compliance Checker. Accepts call transcriptions via REST API, queues them as jobs, and dispatches each job to a fresh `claude --print` subprocess (zero context between runs) that retrieves relevant reference material from Qdrant, checks the transcription for violations, generates a structured report, and emails alerts when violations are found.

Compliance search reads from the **`indiamart_kb`** collection by default (the ingested IndiaMART help knowledge base — see `velocityAI project/sync-pipeline/`), not the legacy 5-SOP `indiamart_sops` collection. This is controlled by `SOP_SEARCH_COLLECTION` and is reversible. Because KB articles have no `rules[]`, the controller reasons over each hit's `content` (article prose) instead of discrete rule strings.

## Commands

```bash
# Start everything in the background (recommended)
./start.sh          # spawns uvicorn + claude controller; logs → logs/server.log, logs/claude.log

# Stop everything
./stop_all.sh       # kills uvicorn, open_claude.sh, and any claude --print processes

# --- or manually ---

# Create and activate virtualenv
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Ingest the IndiaMART KB into the indiamart_kb collection (default search source)
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "."        # ingest entire KB (all 970 articles)
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "BuyLead & Tender"  # scope to one folder
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --dry-run          # preview
.venv/bin/python3 "velocityAI project/sync-pipeline/kb_ingest.py" --search "your q"   # smoke test

# (Legacy) seed the 5-SOP indiamart_sops collection — only if SOP_SEARCH_COLLECTION=indiamart_sops
.venv/bin/python3 setup_sops.py

# Start API server (port 8001) — UI served at http://localhost:8001
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Start claude controller (separate terminal)
bash open_claude.sh

# Smoke test — text transcription
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{"transcription": "call text", "agent_name": "Rahul Sharma", "agent_id": "AGT-001", "caller_id": "+91 98765 43210", "caller_name": "Amit Kumar"}'

# Smoke test — audio transcription (Sarvam AI → transcript → compliance pipeline)
curl -X POST http://localhost:8001/api/transcribe-audio \
  -F "file=@call.wav" \
  -F "agent_name=Rahul Sharma" \
  -F "agent_id=AGT-001" \
  -F "caller_id=+91 98765 43210" \
  -F "caller_name=Amit Kumar" \
  -F "language_code=hi-IN"    # optional; default=unknown (auto-detect)

curl http://localhost:8001/api/jobs/<job_id>
curl http://localhost:8001/api/jobs          # list recent 20 jobs (local SQLite)
curl http://localhost:8001/health            # liveness probe

# Qdrant report store
curl http://localhost:8001/api/reports                                        # all reports, newest first
curl "http://localhost:8001/api/reports?caller_id=C001"                       # filter by caller_id (exact)
curl "http://localhost:8001/api/reports?caller_name=Amit"                     # filter by caller name (partial)
curl "http://localhost:8001/api/reports?agent_name=Rahul"                     # filter by agent name (partial)
curl "http://localhost:8001/api/reports?caller_id=C001&agent_name=Rahul"      # combined filter (AND)
curl "http://localhost:8001/api/reports?sop_outdated=true"                    # calls where KB top-hit score < 0.60 (server-side Qdrant filter)
curl http://localhost:8001/api/reports/<job_id>                               # all analyses for a job
curl -X DELETE http://localhost:8001/api/reports/<job_id>                     # delete all analyses for a job

# Agent analytics
curl http://localhost:8001/api/agents                                        # leaderboard: all agents ranked by avg score
curl http://localhost:8001/api/agents/AGT-001/scores                         # single agent: avg scores + recent calls
curl "http://localhost:8001/api/agents/AGT-001/trends?weeks=12"              # weekly score trends for an agent

# Agent notification (extensible to SMS/WhatsApp via webhook_url)
curl -X POST http://localhost:8001/api/notify \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"AGT-001","agent_name":"Rahul","compliance_score":80,"summary":"Good call","priority_action":"Practice rebuttals"}'

# Check for stale claude controller processes
ps aux | grep "open_claude\|claude --print" | grep -v grep
```

## Architecture

```
POST /api/transcribe-audio  (multipart: file + agent_name, agent_id, caller_id, caller_name, [language_code])
        │
        ▼
  Sarvam AI Saarika v2.5    ← STT optimised for Indian languages / Hinglish / telephony
        │   api.sarvam.ai/speech-to-text  · api-subscription-key header
        │   returns transcript string
        │
        ▼  (feeds into same pipeline as ↓)

POST /api/transcription  (requires: transcription, agent_name, agent_id, caller_id, caller_name)
        │
        ├─ If caller_id already exists → reuse same job_id, reset to pending
        │
        ▼
    SQLite jobs.db          ← status: pending → processing → completed/failed
        │                      report field stores a JSON array (one entry per analysis run)
        ▼
  open_claude.sh (bash poll loop, every 5s)
        │
        ▼
  claude --print < skill.md   ← fresh shell per job, zero context between runs
        │   flags: --allowedTools Bash --dangerously-skip-permissions
        │
        ├─ Step 1: claim next pending job from SQLite
        ├─ Step 2: embed transcription → search SOP_SEARCH_COLLECTION → top-5 hits
        │           KB relevance check: top-hit score ≤ 0.60 → mark sop_outdated=true,
        │           cap script_compliance at 50, prepend "No matching SOP found — KB
        │           outdated/incomplete" to affected score_reasons
        ├─ Step 3: analyse transcript across 8 scoring dimensions (0–100 each):
        │           SOP compliance, objection handling, call checkpoints,
        │           wait compliance, agent sentiment, customer sentiment,
        │           call outcome, knowledge accuracy
        ├─ Step 4: compute weighted compliance_score (0–100)
        ├─ Step 5: build report JSON incl. scores, score_reasons, checkpoints,
        │           call_outcome_type, customer_sentiment_trajectory
        ├─ Step 6: append report to history in SQLite + new Qdrant point per analysis
        ├─ Step 7: send email alert if violations found
        └─ Step 8: print JOB_DONE and exit
        │
        ▼
GET /api/jobs/{job_id}        → report array + violations + compliance_score  (from SQLite)
GET /api/reports              → all reports newest-first, filterable           (from Qdrant)
GET /api/reports/{job_id}     → all analyses for a job, oldest-first          (from Qdrant)
DELETE /api/reports/{job_id}  → remove all analyses for a job                 (from Qdrant)
```

**Important:** Only run one `open_claude.sh` at a time. `claim_next_pending()` in `database.py` uses a read-then-update pattern that is not safe under concurrent access. Always check `ps aux | grep "open_claude\|claude --print"` before starting a new controller. Deleting `open_claude.sh` or killing its parent does **not** kill already-running `claude --print` subprocesses — kill them explicitly.

## Controller Operations & Monitoring

**Startup checklist:**
- Ensure virtualenv is active: `. .venv/bin/activate`
- Check for orphaned processes: `ps aux | grep "open_claude\|claude --print" | grep -v grep`
- Kill any orphans before starting: `pkill -f "open_claude\|claude --print"`
- Verify Qdrant is reachable: `curl http://34.47.255.166:80/health`
- Verify LiteLLM proxy is up: `curl -I https://imllm.intermesh.net/v1`

**Runtime monitoring:**
- Controller logs: `tail -f logs/claude.log` — watch for `ERROR_` or `DEBUG_STEP2.5:` lines
- Job queue depth: `curl http://localhost:8001/api/jobs | grep -c "id"` (should stay small)
- Failed jobs: `sqlite3 jobs.db "SELECT COUNT(*) FROM jobs WHERE status='failed'"`
- Recent errors: `grep "ERROR_" logs/claude.log | tail -10`

**Error codes in logs** (from skill.md):
- `ERROR_CLAIM` — job claim failed; check SQLite access
- `ERROR_TIMEOUT` — embedding/search timed out (>30s); transcript may be too long
- `ERROR_SEARCH` — Qdrant search failed; check service/network
- `ERROR_PERSIST` — SQLite write failed; job left in-flight for manual retry
- `WARNING_QDRANT` — Qdrant write failed (non-fatal); report stored in SQLite only

**Recovery procedures:**
- **Stuck job (no output >5 min):** Kill the hung process and reset the job:
  ```bash
  pkill -f "claude --print"
  python3 -c "from database import update_job; update_job('<job_id>', status='pending')"
  bash open_claude.sh &  # restart controller
  ```
- **Full queue backup:** Check for high-volume submissions; may need to increase batch size or add concurrency (carefully — currently single-threaded by design)
- **Qdrant write failures:** Non-fatal, but reports won't appear in `/api/reports` until manually re-run. Monitor `WARNING_QDRANT` frequency; if >1%, check Qdrant health and networking

**Analysis timeout:** Expected max 5 minutes per job for typical ~500-line transcripts. Very long transcripts (>1000 lines) may exceed this; consider splitting or optimizing in future versions.

## Qdrant — Store and Fetch

### Collection: `indiamart_kb` (default compliance search source)

The ingested IndiaMART help knowledge base. One markdown article = one point
(no chunking — articles are short, self-contained answers). Ingested by
`velocityAI project/sync-pipeline/kb_ingest.py`, which mirrors
`qdrant_helper.py` conventions (raw `httpx`, LiteLLM embeddings, 1536-dim).
IDs are `uuid5(relative_path)` so re-ingestion upserts in place.

```
vector  = embed(title + "\n\n" + content)   ← 1536-dim float array

payload fields:
  category       string   top-level KB folder, e.g. "BuyLead & Tender"
  folder         string   subfolder, e.g. "BLNI", "Tenders"
  title          string   article H1 (falls back to filename)
  content        string   full markdown body — the compliance reference text
  relative_path  string   path within IndiaMART-KB (used for the deterministic id)
  source         string   always "freshdesk-kb"
```

KB articles have **no `rules[]`** — the controller reasons over `content`.
Ingest all: `python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "."` (idempotent — safe to re-run).
Ingest a folder: `python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "BuyLead & Tender"`
(`--dry-run` to preview, `--search "q"` to smoke-test). All 970 articles across all 54 KB folders are ingested (as of 2026-05-16).
**Note:** `kb_ingest.py` truncates embed text to 30,000 chars (~7,500 tokens) to stay under the embedding model's 8,192-token limit. One article exceeds this — `Buyer-Supplier Conflict/Buyer supplier Conflict - Others/Chargeback in India.md` (~103K chars) — its embedding is truncated but full content is stored in Qdrant.

### Collection: `indiamart_sops` (legacy — used only if `SOP_SEARCH_COLLECTION=indiamart_sops`)

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

### Collection: `indiamart_reports`

Each compliance analysis run creates a **new Qdrant point** (point ID = fresh UUID). Multiple analyses for the same `caller_id` all live as separate points, enabling full history queries.

```
vector  = embed(compliance_summary + " " + recommendation)   ← 1536-dim float array

payload fields:
  job_id                        string   UUID of the job (shared across re-runs for same caller)
  agent_name                    string   name of the agent who made the call
  agent_id                      string   agent employee ID
  caller_id                     string   caller identifier
  caller_name                   string   caller's full name
  created_at                    string   ISO-8601 timestamp of this analysis run
  category                      string   matched KB topic
  violations_found              bool     true if any violations detected
  compliance_score              int      0–100 weighted overall score
  violations                    object[] list of {rule, description, evidence}
  compliance_summary            string   narrative summary of the compliance result
  recommendation                string   remediation advice
  scores                        object   per-dimension scores {sop_compliance, objection_handling,
                                         call_checkpoints, wait_compliance, agent_sentiment,
                                         customer_sentiment, call_outcome, knowledge_accuracy}
  score_reasons                 object   per-dimension reason strings (same keys as scores);
                                         if KB top-hit score ≤ 0.60, affected reasons are prefixed
                                         with "No matching SOP was found — KB outdated/incomplete"
  checkpoints                   object   boolean flags for 7 mandatory call checkpoints
  call_outcome_type             string   renewed|upsold|retained|callback_scheduled|
                                         partial_resolution|unresolved|churned|escalated
  customer_sentiment_trajectory string   e.g. "frustrated → reassured → satisfied"
```

Qdrant write failure is non-fatal — the SQLite record is always saved first.

Filtering via `GET /api/reports`:
- `?caller_id=X` — exact match (server-side Qdrant filter)
- `?caller_name=X` — partial case-insensitive match (Python post-filter)
- `?agent_name=X` — partial case-insensitive match (Python post-filter)
- `?sop_outdated=true` — calls where KB top-hit cosine similarity was ≤ 0.60 (server-side Qdrant filter; used by the Outdated SOPs page)
- Multiple params → AND filter; `get_reports_by_filter()` in `qdrant_helper.py` handles all

### Two-stage matching

| Stage | Method |
|-------|--------|
| **Topic selection** | Cosine similarity: `embed(transcription)` vs stored vectors in `SOP_SEARCH_COLLECTION` |
| **Violation check** | Claude language reasoning: derive expected behaviour from the top hit's `content` (KB) or `rules[]` (legacy SOPs), check vs full transcription |

`search_sops` (in `qdrant_helper.py`) queries `SOP_SEARCH_COLLECTION` and returns the top-3 hits with `category`, `folder`, `title`, `content`, `score`, and `rules` (empty for KB; only the top hit's rules are kept for legacy SOPs). Retrieval quality depends on which KB folders have been ingested — transcripts about an un-ingested topic will get weak, off-target hits.

## Frontend

`static/index.html` is a single-file vanilla JS SPA served at `GET /` by FastAPI (`StaticFiles` mount + `FileResponse`). No build step.

**Four top-level pages (nav bar):**

| Page | ID | Description |
|------|----|-------------|
| Analyze | `page-analyze` | Two-column: submit form + sidebar on left, live compliance report on right |
| Agent Leaderboard | `page-agents` | Per-agent score averages, trend charts, ranked table |
| Flagged Calls | `page-flagged` | Dense table of all calls where `violations_found=true`; CSV export + email summary |
| Outdated SOPs | `page-outdated` | Card grid of calls where `sop_outdated=true` (KB top-hit score ≤ 0.60); for KB improvers |

**Analyze page — left panel:**
- Submit form: file upload drop zone + manual textarea + Agent Name / Agent ID / Caller ID / Caller Name (all required) and a recent-jobs sidebar (last 30 from Qdrant, shared across all machines)

**Analyze page — right panel:**
- Live compliance report: score ring, violations with evidence quotes, summary, recommendation, previous analyses history

**Sidebar features:**
- Filter tabs: All / Flagged (violations only, with live count badge)
- Three filter inputs: Caller ID (exact), Caller Name (partial), Agent Name (partial) — all work together (AND)
- Clear filters link
- Shows agent name + caller name per row; compliance score (coloured green/amber/red); red dot for flagged, green for compliant

**Outdated SOPs page:**
- Fetches via `GET /api/reports?sop_outdated=true` — server-side Qdrant filter, no client-side filtering
- Cards sorted by category; each card shows: category pill (amber), caller name, agent name, SOP score ring (svg, colour-coded), and the full `score_reasons.script_compliance` text as "Why this SOP needs improvement"
- SOP score is `scores.script_compliance` — capped at 50 by controller when `sop_outdated=true`
- Stats bar counts total calls and unique categories affected
- CSV export: Category, Caller Name, Agent Name, SOP Score, Why SOP Needs Improvement, Timestamp — sorted by category

**Key JS behaviours:**
- **Input mode tabs:** "📄 Text / File" (default) or "🎙️ Audio" — switches between two drop zones
- Text mode: on submit → `POST /api/transcription` (JSON) → polls `GET /api/jobs/{id}` every 2s
- Audio mode: on submit → `POST /api/transcribe-audio` (multipart FormData) → shows "Transcribing audio…" spinner → on success switches to "Analysing transcription…" spinner and polls as normal
- Text drop zone (`#dropZone`) accepts `.txt`, `.log`, `.csv`; reads with `FileReader` and populates the textarea
- Audio drop zone (`#audioDrop`) accepts `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.webm`, `.aac`, `.amr`; holds `File` reference in `selectedAudioFile`
- Sidebar reads from `GET /api/reports` (Qdrant, shared across machines); pending local jobs shown via `pendingJobs` map until they land in Qdrant
- Recent jobs list auto-refreshes every 10s
- Score ring colour: green ≥ 80, amber ≥ 50, red < 50
- Clicking a job loads full analysis history (all runs for that caller)
- **Dimension score cards** are clickable — opens a modal showing the dimension name, score, colour-coded bar, and the `score_reason` text from the report. Cards without a reason (old reports) are non-interactive. Reasons are stored in `currentScoreReasons` (module-level JS variable set on each `renderReport` call) to avoid HTML-attribute escaping issues.
- "Script Compliance" dimension is labelled **"SOP Compliance"** in the UI (`DIM_LABELS` in `index.html`)

To add a new field to the report, update `skill.md` (add the field to the JSON schema section) and the `renderReport()` function in `index.html`.

## Key files

| File | Role |
|------|------|
| `start.sh` | One-command background start — nohup uvicorn + claude controller; logs to `logs/` |
| `stop_all.sh` | Kill uvicorn, open_claude.sh, and claude --print processes |
| `open_claude.sh` | Poll loop: spawns a fresh `claude --print < skill.md` per job |
| `skill.md` | Single-job agent instructions — claim → embed → analyse → persist → alert → exit |
| `main.py` | FastAPI app — all REST endpoints |
| `static/index.html` | Single-file SPA — submit form, live polling, report renderer, filters |
| `qdrant_helper.py` | Raw `httpx` REST calls to Qdrant + OpenAI embeddings via LiteLLM proxy |
| `database.py` | SQLite helpers — `init_db`, `create_job`, `claim_next_pending`, `update_job`, `get_job`, `get_job_by_caller_id`, `list_jobs` |
| `email_helper.py` | CLI-callable SMTP sender: `python3 email_helper.py --to --subject --body` |
| `setup_sops.py` | One-time seed — upserts 5 IndiaMart SOPs into legacy `indiamart_sops` |
| `config.py` | All env-var config via `python-dotenv`; exposes `PROJECT_DIR`, `SOP_SEARCH_COLLECTION` |
| `velocityAI project/sync-pipeline/kb_ingest.py` | Ingests `IndiaMART-KB/<subdir>` markdown into the `indiamart_kb` collection (1 article = 1 point; idempotent) |

## External services

| Service | URL | Purpose |
|---------|-----|---------|
| Qdrant | `http://34.47.255.166:80` | Vector store (collections: `indiamart_kb` ← search source, `indiamart_sops` legacy, `indiamart_reports`) |
| LiteLLM proxy | `https://imllm.intermesh.net/v1` | Embeddings (`openai/text-embedding-3-large`, 1536-dim) |
| Gmail SMTP | `smtp.gmail.com:587` | Violation email alerts |
| Sarvam AI | `https://api.sarvam.ai` | Speech-to-text (Saarika v2.5) — Indian languages, Hinglish, telephony audio |

## Report schema

Each job stores a **list** of analysis objects in SQLite (one per run). The Qdrant collection stores each analysis as a separate point.

```json
{
  "job_id": "...",
  "category": "BuyLead & Tender",
  "violations_found": true,
  "violations": [
    { "rule": "...", "description": "...", "evidence": "<verbatim quote>" }
  ],
  "scores": {
    "script_compliance": 75,
    "objection_handling": 100,
    "call_checkpoints": 86,
    "wait_compliance": 70,
    "agent_sentiment": 80,
    "customer_sentiment": 60,
    "call_outcome": 80,
    "knowledge_accuracy": 90
  },
  "score_reasons": {
    "script_compliance": "No matching SOP was found... (if KB score ≤ 0.60) OR full analysis text",
    "objection_handling": "...",
    "call_checkpoints": "...",
    "wait_compliance": "...",
    "agent_sentiment": "...",
    "customer_sentiment": "...",
    "call_outcome": "...",
    "knowledge_accuracy": "..."
  },
  "checkpoints": {
    "greeting": true,
    "self_introduction": true,
    "purpose_statement": false,
    "recording_disclosure": true,
    "permission_to_proceed": true,
    "feedback_collection": false,
    "proper_closing": true
  },
  "call_outcome_type": "callback_scheduled",
  "customer_sentiment_trajectory": "frustrated → reassured → satisfied",
  "compliance_score": 78,
  "compliance_summary": "...",
  "recommendation": "..."
}
```

**KB relevance rule:** If the top Qdrant hit's cosine similarity score is ≤ 0.60 (or no hits found), the `score_reasons` for `script_compliance`, `objection_handling`, and `knowledge_accuracy` are prefixed with *"No matching SOP was found for this call topic — the knowledge base appears to be outdated or incomplete for this category and needs to be updated."* The per-dimension analysis still follows. `script_compliance` is additionally capped at 50. The `sop_outdated` flag is set to `true` in the report.

## Environment variables (`.env`)

```
QDRANT_URL=http://34.47.255.166:80
QDRANT_COLLECTION=indiamart_sops              # legacy SOP seed/upsert target
SOP_SEARCH_COLLECTION=indiamart_kb            # optional, default shown — what search_sops reads
REPORTS_COLLECTION=indiamart_reports          # optional, default shown
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
CLAUDE_BIN=claude                # optional, path to claude binary
SARVAM_API_KEY=<Sarvam AI API key>   # required for POST /api/transcribe-audio
```

## Notes

- The `claude` CLI must be installed and on PATH for the controller to run: `npm i -g @anthropic-ai/claude-code`. If missing, `open_claude.sh` exits immediately (exit 127, "command not found") and jobs sit in `pending` forever — the API/UI keep working, only analysis stalls.
- `claude --print` reads auth from the system keychain — do **not** use `--bare`.
- Compliance search source is `SOP_SEARCH_COLLECTION` (default `indiamart_kb`). Set it to `indiamart_sops` in `.env` to restore the original rule-based behaviour — no code change needed.
- All 970 KB articles across 54 folders are ingested into `indiamart_kb` (as of 2026-05-16). Re-ingest with `python3 "velocityAI project/sync-pipeline/kb_ingest.py" --subdir "."` — it is idempotent.
- KB upserts must use small batches (≤8 points) — the Qdrant server rejects large request bodies with HTTP 413.
- Each `claude --print` run starts with zero context — no memory of previous jobs. All state is in SQLite and Qdrant.
- `qdrant_helper.py` uses raw `httpx` calls — do not switch to the `qdrant-client` library (v1.18 is incompatible with server v1.9.2).
- Qdrant must be addressed as `http://34.47.255.166:80` (explicit port 80) — omitting it causes the client to append `:6333`.
- Email requires a Gmail **App Password**: Google Account → Security → 2-Step Verification → App passwords.
- Same `caller_id` across submissions → same `job_id` reused; each new analysis appends to the report array in SQLite and creates a new Qdrant point.
- The sidebar reads from Qdrant (`/api/reports`) so reports are visible on all machines. Locally-submitted pending jobs appear via the in-memory `pendingJobs` map until processing completes.
- A stale `claude --print` process (from a previous controller run) will compete for jobs — always run `./stop_all.sh` before starting a new controller.
- `POST /api/transcribe-audio` calls Sarvam AI synchronously before queuing the job — if the audio is very long (>30 min) or the Sarvam API is slow, the HTTP request will block. For very long recordings use Sarvam's Batch API instead (not yet wired up).
- Sarvam AI `language_code=unknown` enables automatic language detection — fine for mixed Hindi/English calls. Pass `hi-IN` or `en-IN` explicitly if the language is known.
- **Analysis timeout:** Expected max 5 minutes per job for typical ~500-line transcripts. Embedding/search is capped at 30s; full analysis (extraction + scoring + report generation) at 5 min. Very long transcripts (>1000 lines) may exceed this — consider chunking in future versions.
- **Error handling:** skill.md defines error codes (ERROR_CLAIM, ERROR_TIMEOUT, ERROR_SEARCH, ERROR_PERSIST, WARNING_QDRANT). All appear in logs/claude.log with stderr output. SQLite writes must succeed; Qdrant failures are non-fatal.
