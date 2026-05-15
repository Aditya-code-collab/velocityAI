# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VelocityAI** — IndiaMart SOP Compliance Checker. Accepts call transcriptions via REST API, queues them as jobs, and dispatches each job to a fresh `claude --print` subprocess that retrieves relevant SOPs from Qdrant, checks the transcription for violations, generates a structured report, and emails alerts when violations are found.

## Commands

```bash
# Create and activate virtualenv
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Seed Qdrant with IndiaMart SOPs (run once, or after editing setup_sops.py)
.venv/bin/python3 setup_sops.py

# Start API server (port 8001)
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Start worker (separate terminal)
.venv/bin/python3 worker.py

# Quick smoke test
curl -X POST http://localhost:8001/api/transcription \
  -H "Content-Type: application/json" \
  -d '{"transcription": "your call text here", "agent_name": "Test Agent"}'

curl http://localhost:8001/api/jobs/<job_id>
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
  claude --print subprocess  (new shell per job)
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

## Qdrant — Store and Fetch

### What is stored per SOP point

Each SOP is stored as one Qdrant point with a **vector** and a **payload**:

```
vector  = embed(description)          ← 1536-dim float array (never fetched back)

payload fields stored:
  category     string   slug: catalog_addition | catalog_deletion |
                              subscription_sales | lead_management | payment_collection
  title        string   human-readable SOP name
  content      string   2–3 sentence overview of the SOP's purpose
  description  string   full embedding text: title + overview + rules (numbered) +
                        representative call phrases — this is what was embedded
  rules        string[] individual enforceable rule strings (7–9 per SOP)
  keywords     string[] trigger word hints (stored, not used in search)
```

### Why rules appear in two places

The same rule text is stored twice, serving different purposes:

| Location | Format | Used for |
|----------|--------|----------|
| Inside `description` | Plain numbered text | Baked into the embedding vector → helps match transcriptions that mention rule-related phrases |
| `rules` list | Structured string[] | Fetched after search → passed line-by-line to the Claude agent for violation checking |

### Write path (`setup_sops.py` → `upsert_sop`)

```
description field (title + overview + rules as text + call phrases)
        │
        ▼
embed(description)  →  1536-dim vector  →  stored in Qdrant
payload (category, title, content, description, rules, keywords)  →  stored in Qdrant
```

### Read path (`worker.py` → `search_sops`)

```
transcription text
        │
        ▼
embed(transcription)  →  1536-dim vector
        │
        ▼
POST /collections/indiamart_sops/points/search
  { vector: [...], limit: 3,
    with_payload: { include: [category, title, content, rules] } }
        │         ↑ description and keywords excluded — not needed after indexing
        ▼
cosine similarity against all 5 stored SOP vectors
        │
        ▼
top-3 hits returned:
  hit #1  category + title + content + rules[]   ← full rules for violation check
  hit #2  category + title + content + rules[]   ← rules stripped in Python (not used)
  hit #3  category + title + content + rules[]   ← rules stripped in Python (not used)
```

Runner-up rules are fetched from Qdrant but immediately discarded in `search_sops` — only the top hit's rules are passed to the agent.

### Two-stage matching

| Stage | Input compared | Method |
|-------|---------------|--------|
| **Category selection** | `embed(transcription)` vs `embed(description)` for each SOP | Cosine similarity in Qdrant |
| **Rule violation check** | Each rule string vs full transcription text | Claude language reasoning inside `claude --print` subprocess |

Vector search only answers *"which SOP category does this call belong to?"* Rule-by-rule checking is done entirely by Claude after the category is selected.

## What the Claude agent receives in its prompt

```
=== CALL TRANSCRIPTION ===
<raw transcription text>

=== RETRIEVED SOPs ===
### MATCHED SOP: <title>
Category: <category>  |  Relevance score: <score>
<content — 2-sentence overview>
Rules to check:
  1. <rule>
  2. <rule>
  ...

### Other candidate categories (not selected): <cat2> (score X), <cat3> (score Y)

=== INSTRUCTIONS ===
1. Confirm the best-matching category
2. Check each rule against the transcription
3. For every violation: rule broken + what went wrong + direct quote as evidence
4. Compute compliance_score (0-100)
5. Write summary and recommendation

=== EMAIL ===
<pre-filled bash command — agent runs it via Bash tool if violations found>

=== OUTPUT FORMAT ===
COMPLIANCE_REPORT_START
{ ...JSON report... }
COMPLIANCE_REPORT_END
```

## Key files

| File | Role |
|------|------|
| `main.py` | FastAPI app — `/api/transcription`, `/api/jobs/{id}`, `/api/jobs` |
| `worker.py` | Polls SQLite, spawns `claude --print` subprocess per job |
| `agent_prompt.py` | Builds the compliance analysis prompt for the Claude agent |
| `qdrant_helper.py` | Raw `httpx` REST calls to Qdrant + OpenAI embeddings via LiteLLM proxy |
| `database.py` | SQLite helpers (`init_db`, `create_job`, `update_job`, etc.) |
| `email_helper.py` | CLI-callable SMTP sender (`python3 email_helper.py --to --subject --body`) |
| `setup_sops.py` | One-time seed script — upserts 5 IndiaMart SOPs into Qdrant |
| `config.py` | All env-var config loaded via `python-dotenv` |

## External services

| Service | URL | Purpose |
|---------|-----|---------|
| Qdrant | `http://34.47.255.166:80` | Vector store for SOPs (collection: `indiamart_sops`) |
| LiteLLM proxy | `https://imllm.intermesh.net/v1` | Embeddings (`openai/text-embedding-3-large`, 1536-dim) |
| Gmail SMTP | `smtp.gmail.com:587` | Violation email alerts |

## SOP categories

`catalog_addition` · `catalog_deletion` · `subscription_sales` · `lead_management` · `payment_collection`

## Report schema (output from Claude agent)

```json
{
  "job_id": "...",
  "category": "subscription_sales",
  "violations_found": true,
  "violations": [
    { "rule": "...", "description": "...", "evidence": "<verbatim quote from transcript>" }
  ],
  "compliance_score": 0-100,
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
VIOLATION_EMAIL_TO=yashwantsinghchandra258@gmail.com
WORKER_POLL_INTERVAL=5
```

## Notes

- The `claude --print` subprocess reads auth from the system keychain — do **not** use `--bare`.
- Qdrant client v1.18 is incompatible with server v1.9.2; `qdrant_helper.py` uses raw `httpx` calls to avoid this — do not switch back to the `qdrant-client` library.
- Qdrant must be addressed as `http://34.47.255.166:80` (explicit port 80) — omitting the port causes the client to append `:6333` by default.
- Email requires a Gmail **App Password** (not the account password). Enable: Google Account → Security → 2-Step Verification → App passwords.
- To re-seed SOPs: delete the collection first (`curl -X DELETE http://34.47.255.166/collections/indiamart_sops`) then run `setup_sops.py`.
