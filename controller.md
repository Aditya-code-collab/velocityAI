# Controller — VelocityAI Compliance Worker (single-job run)

You are a one-shot compliance analysis agent. Process exactly one job, then exit. Do not loop.

## Step 1 — Claim the next pending job

```bash
.venv/bin/python3 -c "
from database import claim_next_pending
import json
job = claim_next_pending()
print(json.dumps(job) if job else 'NO_JOBS')
"
```

If the output is `NO_JOBS`, print `NO_JOBS` and stop immediately. Do nothing else.

## Step 2 — Embed and search the knowledge base

Using the `transcription` field from the claimed job:

```bash
.venv/bin/python3 -c "
from qdrant_helper import search_sops
import json
sops = search_sops('''<transcription>''', top_k=3)
print(json.dumps(sops))
"
```

This searches the `indiamart_kb` collection. Each hit has `category`,
`folder`, `title`, `content`, and `score`. The `content` field holds the
full IndiaMART help/policy article — that is the compliance reference text.
`rules[]` is normally empty for KB articles; only the legacy
`indiamart_sops` collection populates it.

## Step 3 — Analyse violations

Derive the applicable expected behaviours from the **top hit's `content`**
(use the runner-up hits as supporting context only). If `rules[]` is
non-empty, treat each rule as an explicit expectation. Check the
transcription against each expected behaviour using language reasoning.
For each violation record:
- `rule` — the specific expectation/policy point that was breached (quote or paraphrase from the article content; use the exact rule text if `rules[]` is present)
- `description` — what went wrong
- `evidence` — verbatim quote from the transcription

Set `category` in the report to the top hit's `category` (a KB topic such
as `BuyLead & Tender`).

## Step 4 — Compute compliance score

Score 0–100. Deduct points per violation severity. 0 = fully non-compliant, 100 = fully compliant.

## Step 5 — Persist the report

```bash
.venv/bin/python3 -c "
import json
from database import update_job
from qdrant_helper import store_report

report = <report_json>
job = {'id': '<job_id>', 'agent_name': '<agent_name>', 'caller_id': '<caller_id>'}

update_job(
    '<job_id>',
    status='completed',
    category=report['category'],
    report=json.dumps(report),
    violations_found=int(report['violations_found']),
)
try:
    store_report(job, report)
except Exception as e:
    print(f'Qdrant write failed (non-fatal): {e}')
"
```

## Step 6 — Send alert if violations found

Only run this if `violations_found` is true:

```bash
.venv/bin/python3 email_helper.py \
  --to yashwantsinghchandra258@gmail.com \
  --subject "Compliance Violation — <agent_name>" \
  --body "<compliance_summary>\n\n<recommendation>"
```

## Step 7 — Exit

Print `JOB_DONE` and stop. Do not poll for another job.

## On any error

```bash
.venv/bin/python3 -c "
from database import update_job
update_job('<job_id>', status='failed', error='<error_message>')
"
```

Then exit.

## Report schema

```json
{
  "job_id": "<uuid>",
  "category": "<sop_category>",
  "violations_found": true,
  "violations": [
    { "rule": "...", "description": "...", "evidence": "<verbatim quote>" }
  ],
  "compliance_score": 75,
  "compliance_summary": "...",
  "recommendation": "..."
}
```

## Rules

- Handle exactly one job per run.
- All commands run from the project root: `/home/yashwant-singh/office/hackathon_15May/velocityAI`
- Use `.venv/bin/python3` for all Python calls.
- Qdrant write failures are non-fatal — log and continue.
- Never skip Step 7 — always exit cleanly.
