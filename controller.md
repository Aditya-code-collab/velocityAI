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
sops = search_sops('''<transcription>''', top_k=5)
print(json.dumps(sops))
"
```

This searches the `indiamart_kb` collection. Each hit has `category`,
`folder`, `title`, `content`, and `score`. The `content` field holds the
full IndiaMART help/policy article — that is the compliance reference text.
`rules[]` is normally empty for KB articles; only the legacy
`indiamart_sops` collection populates it.

### KB relevance check

After receiving the search results, check the top hit's `score`:

- **score ≥ 0.60** — sufficient match; proceed with normal scoring.
- **score < 0.60** — no matching SOP found. For `script_compliance`,
  `objection_handling`, and `knowledge_accuracy` score_reasons, begin with:
  "No matching SOP was found for this call topic — the knowledge base
  appears to be outdated or incomplete for this category and needs to be
  updated." Then continue with the normal per-dimension reasoning based on
  what was observable in the transcript. Cap `script_compliance` at 50.

## Step 3 — Analyse the transcript and compute ALL scores

Analyse the transcription against the retrieved KB articles across **eight
scoring dimensions**. Each score is an integer 0–100. Use the KB scripts
(engagement, upsell, renewal, objection handling) as the ground truth for
what the agent _should_ have said/done.

### 3.1 Script compliance (`script_compliance`: 0–100)

Compare the transcript flow against the applicable KB script (engagement,
upsell, renewal, or objection handling). Check whether the agent followed
the prescribed sequence:

- Did the agent use the correct script type for the situation?
- Did the agent follow the script steps in order?
- Were key phrases and talking points from the script used?

Deduct points for: wrong script used (−30), skipped steps (−10 each),
deviated from script flow (−5 each).

### 3.2 Objection handling quality (`objection_handling`: 0–100)

When the customer raised objections (fund issue, irrelevancy, maturity,
business closing, etc.), did the agent respond with the correct rebuttal
from the KB objection handling scripts?

- Identify each objection the customer raised
- Match it to the correct KB objection handling article
- Check if the agent's response aligned with the prescribed rebuttal

Score 100 if no objections were raised (not applicable). Deduct −20 per
poorly handled objection, −30 for ignored objections.

### 3.3 Call checkpoints hit (`call_checkpoints`: 0–100)

Check whether the agent completed these mandatory checkpoints:

1. **Greeting** — "Good Morning/Afternoon" + polite opener
2. **Self-introduction** — Agent stated their name and "from IndiaMART"
3. **Purpose statement** — Clearly stated the call purpose (feedback/service/renewal)
4. **Recording disclosure** — "This call is being recorded for training and quality purpose"
5. **Permission to proceed** — "Is this the right time to talk to you?"
6. **Feedback collection** — Asked for customer's experience/feedback
7. **Proper closing** — Professional sign-off, next steps if any

Each checkpoint = ~14 points. Mark each as hit (true) or missed (false).

### 3.4 Wait-for-response compliance (`wait_compliance`: 0–100)

The KB scripts explicitly say "Wait for the customer response" at key
moments. Detect whether the agent paused and let the customer speak, or
steamrolled through without listening.

- Check for customer turn-taking after greeting
- Check for customer turn-taking after permission ask
- Check for customer turn-taking after feedback questions
- Check for customer turn-taking after objection responses

Deduct −15 per instance where the agent continued without waiting.

### 3.5 Sentiment & empathy score (`agent_sentiment`: 0–100)

Analyse the agent's language:

- **Positive indicators** (+points): empathetic phrases ("I understand"),
  professional tone, patient language, positive framing, offering solutions
- **Negative indicators** (−points): dismissive language, interrupting,
  aggressive pushing, rude or impatient tone, ignoring customer concerns

Start at 70 (neutral professional), add/deduct based on indicators.

### 3.6 Customer sentiment trajectory (`customer_sentiment`: 0–100)

Track how the customer's mood changed during the call:

- 100 = customer started neutral/negative and ended positive/satisfied
- 70 = customer sentiment remained stable/neutral throughout
- 40 = customer started positive but ended frustrated
- 0 = customer was hostile/angry throughout with no resolution

Provide a brief trajectory description (e.g., "frustrated → reassured → satisfied").

### 3.7 Call outcome classification (`call_outcome`: 0–100)

Classify and score the business outcome:

- 100 = Renewed / Upsold / Issue fully resolved
- 80 = Callback scheduled with positive intent
- 60 = Partial resolution, follow-up needed
- 40 = Customer undecided, no commitment
- 20 = Customer declined but not churned
- 0 = Customer churned / complained / escalated

Also classify the outcome type as one of: `renewed`, `upsold`, `retained`,
`callback_scheduled`, `partial_resolution`, `unresolved`, `churned`, `escalated`.

### 3.8 Knowledge accuracy (`knowledge_accuracy`: 0–100)

Cross-reference factual claims the agent made against the KB articles:

- Did the agent give correct product/process information?
- Were BuyLead limits, allocation rules, pricing, or procedures stated correctly?
- Did the agent make any false promises or give outdated information?

Score 100 if all statements were accurate or no factual claims were made.
Deduct −15 per factual error, −25 per false promise.

## Step 4 — Compute overall compliance score

The overall `compliance_score` is a weighted average:

| Dimension             | Weight |
|----------------------|--------|
| script_compliance     | 20%    |
| objection_handling    | 15%    |
| call_checkpoints      | 15%    |
| wait_compliance       | 10%    |
| agent_sentiment       | 10%    |
| customer_sentiment    | 10%    |
| call_outcome          | 10%    |
| knowledge_accuracy    | 10%    |

Formula: `compliance_score = round(sum(score × weight for each dimension))`

## Step 5 — Build the report

Construct the full report JSON. Note the new `scores` object and
`checkpoints` array:

```json
{
  "job_id": "<uuid>",
  "category": "<sop_category from top KB hit>",
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
    "script_compliance": "Agent used the engagement script but skipped the recording disclosure step (−10) and deviated from the prescribed upsell flow (−15).",
    "objection_handling": "No objections were raised during the call; dimension not applicable — scored 100.",
    "call_checkpoints": "Greeting, self-introduction, permission, recording disclosure, and closing were completed. Purpose statement and feedback collection were missed (−14 each).",
    "wait_compliance": "Agent paused after greeting and permission ask but continued speaking without waiting after the feedback question (−15) and after the objection response (−15).",
    "agent_sentiment": "Professional and empathetic tone throughout. Used 'I understand' and positive reframing twice. No dismissive or impatient language detected.",
    "customer_sentiment": "Customer started frustrated about lead quality but gradually became more receptive after the agent explained the BuyLead allocation policy. Ended with neutral-positive sentiment.",
    "call_outcome": "Agent successfully scheduled a follow-up callback with a clear next step; customer agreed to review the proposal.",
    "knowledge_accuracy": "All product information was accurate. Agent correctly stated BuyLead limits and allocation rules per KB article. No false promises detected."
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

## Step 6 — Persist the report

Append the new report to the existing list (same caller may have prior analyses under this job_id).

```bash
.venv/bin/python3 -c "
import json
from database import get_job, update_job
from qdrant_helper import store_report

report = <report_json>
job_id = '<job_id>'
job = {'id': job_id, 'agent_name': '<agent_name>', 'agent_id': '<agent_id>', 'caller_id': '<caller_id>', 'caller_name': '<caller_name>'}

# append to history
existing = get_job(job_id)
prev = existing.get('report')
if prev:
    try:
        parsed = json.loads(prev)
        history = parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        history = []
else:
    history = []
history.append(report)

update_job(
    job_id,
    status='completed',
    category=report['category'],
    report=json.dumps(history),
    violations_found=int(report['violations_found']),
    compliance_score=report['compliance_score'],
)
try:
    store_report(job, report)
except Exception as e:
    print(f'Qdrant write failed (non-fatal): {e}')
"
```

## Step 7 — Send alert if violations found

Only run this if `violations_found` is true:

```bash
.venv/bin/python3 email_helper.py \
  --to yashwantsinghchandra258@gmail.com \
  --subject "Compliance Violation — <agent_name>" \
  --body "<compliance_summary>\n\nScores: script_compliance=<score>, objection_handling=<score>, call_checkpoints=<score>, wait_compliance=<score>, agent_sentiment=<score>, customer_sentiment=<score>, call_outcome=<score>, knowledge_accuracy=<score>\nOverall: <compliance_score>/100\n\n<recommendation>"
```

## Step 8 — Exit

Print `JOB_DONE` and stop. Do not poll for another job.

## On any error

```bash
.venv/bin/python3 -c "
from database import update_job
update_job('<job_id>', status='failed', error='<error_message>')
"
```

Then exit.

## Rules

- Handle exactly one job per run.
- All commands run from the project root: `/home/yashwant-singh/office/hackathon_15May/velocityAI`
- Use `.venv/bin/python3` for all Python calls.
- Qdrant write failures are non-fatal — log and continue.
- Never skip Step 8 — always exit cleanly.
- ALL eight scores MUST be computed for every transcript, even if some
  dimensions are not applicable (score them 100 with a note).
- The `scores` object, `checkpoints` object, `call_outcome_type`,
  `customer_sentiment_trajectory`, and `score_reasons` are REQUIRED fields
  in every report.
- `score_reasons` MUST contain one entry per dimension key. Each reason
  must be 1–3 sentences explaining what evidence led to that score: what
  the agent did right, what they missed, and how the deductions were
  applied. For N/A dimensions write why the dimension does not apply.
- For `script_compliance`, `objection_handling`, and `knowledge_accuracy`
  reasons: if top KB hit score < 0.60, begin the reason with "No matching
  SOP was found for this call topic — the knowledge base appears to be
  outdated or incomplete for this category and needs to be updated." Then
  still provide the full per-dimension analysis based on the transcript.
  If score ≥ 0.60, proceed directly with the analysis (no caveat needed).
