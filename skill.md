# Controller — VelocityAI Compliance Worker (single-job run)

You are a one-shot compliance analysis agent. Process exactly one job, then exit. Do not loop.

## Step 1 — Claim the next pending job

```bash
.venv/bin/python3 -c "
from database import claim_next_pending
import json
import sys
try:
    job = claim_next_pending()
    print(json.dumps(job) if job else 'NO_JOBS')
except Exception as e:
    print(f'ERROR_CLAIM: {str(e)}', file=sys.stderr)
    sys.exit(1)
"
```

If the output is `NO_JOBS`, print `NO_JOBS` and stop immediately. Do nothing else.

**Error handling:** If output contains `ERROR_CLAIM`, log the error and exit with status 1. The job remains in `pending` status for retry.

**Concurrency:** IMPORTANT — Only one `open_claude.sh` controller should run at a time. Before starting a new controller, check: `ps aux | grep "open_claude\|claude --print" | grep -v grep`. Kill any orphaned `claude --print` processes before restarting.

## Step 2 — Embed and search the knowledge base

Using the `transcription` field from the claimed job (max ~50,000 tokens; very long transcripts >30 min may timeout):

```bash
.venv/bin/python3 -c "
from qdrant_helper import search_sops
import json
import sys
transcription = '''<transcription>'''  # Transcription must be passed as a Python string literal
try:
    sops = search_sops(transcription, top_k=5)
    print(json.dumps(sops))
except TimeoutError:
    print('ERROR_TIMEOUT: Embedding or search exceeded 30s timeout', file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f'ERROR_SEARCH: {str(e)}', file=sys.stderr)
    sys.exit(1)
"
```

This searches the `indiamart_kb` collection. Each hit has `category`,
`folder`, `title`, `content`, and `score`. The `content` field holds the
full IndiaMART help/policy article — that is the compliance reference text.

**String escaping:** The transcription is passed as a Python triple-quoted string. Triple quotes protect most special characters, but newlines and single quotes within the transcript are preserved as-is. If the transcription contains `'''`, replace with escaped form or use JSON.dumps() in the calling script.

### KB relevance check

After receiving the search results, check the top hit's `score`:

- **score > 0.60** — sufficient match; proceed with normal scoring. Set `sop_outdated: false`.
- **score ≤ 0.60** — no matching SOP found. Set `sop_outdated: true`. For `script_compliance`,
  `objection_handling`, and `knowledge_accuracy` score_reasons, begin with:
  "No matching SOP was found for this call topic — the knowledge base
  appears to be outdated or incomplete for this category and needs to be
  updated." Then continue with the normal per-dimension reasoning based on
  what was observable in the transcript. Cap `script_compliance` at 50.

**Note:** Exact boundary (score = 0.60) is treated as outdated. If search fails (no hits), treat as score = 0 and mark `sop_outdated: true`.

## Step 2.5 — Extract checkable rules from KB hits (CRITICAL)

**For observability:** Before analysis, print to stderr: `DEBUG_STEP2.5: Analyzing transcript length N chars, top KB hit: "<title>" (score: X.XX)`. This helps monitor controller progress.

Before scoring anything, you MUST extract an explicit numbered checklist
from the KB content. This is the step that makes scoring consistent.

Read the top KB hit's `content` carefully. Extract every **checkable
behaviour** the script prescribes. Group them under the relevant scoring
dimension. Output the checklist as a fenced block so it is visible in
your reasoning. Example:

```
EXTRACTED RULES from "Upsell Script" (score: 0.87):

SCRIPT_COMPLIANCE:
  R1. Agent must greet with "Good Morning/Afternoon Mr./Ms. <Name>"
  R2. Agent must state "I am <Name> your account manager from IndiaMART"
  R3. Agent must ask "Is this the right time to talk to you?" and WAIT
  R4. Agent must state "This call is being recorded for training and quality purpose"
  R5. Agent must ask about overall experience on platform and WAIT
  R6. If positive: agent should introduce upsell value proposition
  R7. If objection: agent should use prescribed rebuttal from KB

WAIT_COMPLIANCE:
  W1. Wait after greeting before continuing
  W2. Wait after "Is this the right time" before continuing
  W3. Wait after recording disclosure before continuing
  W4. Wait after feedback question before continuing
  W5. Wait after any objection-handling response

KNOWLEDGE_ACCURACY (claims to verify against KB):
  K1. Product names / package names mentioned
  K2. Pricing figures quoted
  K3. BuyLead allocation numbers
  K4. Feature descriptions
  K5. Process or policy claims
```

Then, for EACH extracted rule, scan the transcript and record:

```
RULE AUDIT:
  R1. PASS — Agent said "Good Morning Mr. Patel"
  R2. PASS — Agent said "I am Rahul Sharma, your account manager from IndiaMART"
  R3. PASS — Agent asked "Is this the right time to talk to you?" → Customer replied "Yes"
  R4. PASS — Agent stated recording disclosure
  R5. PASS — Agent asked "How has your overall experience been?"
  R6. PASS — Agent introduced Gold package upsell
  R7. PARTIAL — Customer raised pricing objection; agent gave data-backed response but did not use the exact prescribed rebuttal from KB
  W1. PASS — Customer responded after greeting
  W2. PASS — Customer responded after permission ask
  W3. PASS — Customer responded after recording disclosure
  W4. PASS — Customer responded after experience question
  W5. N/A — No objection-handling wait point reached
  K1. VERIFY — Agent mentioned "Silver package" and "Gold package" — consistent with KB
  K2. FLAG — Agent quoted "Rs. 45,000 per year" — must verify against KB pricing
  K3. PASS — Agent said "3x more BuyLeads" — consistent with KB
```

This audit trail is your evidence base. Scores MUST derive from it — not from vibes.

## Step 3 — Analyse the transcript and compute ALL scores using the audit trail

**Timeout guideline:** The full analysis (extraction + scoring + report generation) should complete within 5 minutes for typical ~500-line transcripts. If analysis takes >5 min, the calling controller may timeout. Very long transcripts (>1000 lines) may require optimization or chunking.

### 3.1 Script compliance (`script_compliance`: 0–100)

Start at 100. For each extracted rule under SCRIPT_COMPLIANCE:
- Rule completely followed: 0 deduction
- Rule partially followed: −5 to −10
- Rule skipped entirely: −10 to −15
- Wrong script type used for the situation: −30

The score = 100 minus total deductions (floor at 0).

### 3.2 Objection handling quality (`objection_handling`: 0–100)

Identify each customer objection in the transcript. For each:
1. Name the objection type (fund issue, irrelevancy, maturity, business closing, pricing, etc.)
2. Find the matching KB objection handling article from the search results
3. Compare agent's actual response to the prescribed rebuttal

Scoring:
- No objections raised → 100 (N/A)
- Each objection handled with prescribed rebuttal → no deduction
- Each objection handled but with wrong/weak rebuttal → −20
- Each objection ignored entirely → −30

### 3.3 Call checkpoints hit (`call_checkpoints`: 0–100)

Seven mandatory checkpoints. Each = ~14 points. Mark each true/false:

| # | Checkpoint | What to look for |
|---|-----------|-----------------|
| 1 | `greeting` | "Good Morning/Afternoon" + polite opener |
| 2 | `self_introduction` | Agent stated name + "from IndiaMART" |
| 3 | `purpose_statement` | Stated call purpose (feedback/service/renewal) |
| 4 | `recording_disclosure` | "This call is being recorded for training and quality purpose" |
| 5 | `permission_to_proceed` | "Is this the right time to talk to you?" |
| 6 | `feedback_collection` | Asked for customer's experience/feedback |
| 7 | `proper_closing` | Professional sign-off, next steps stated |

Score = (count of true checkpoints / 7) × 100, rounded to integer.

### 3.4 Wait-for-response compliance (`wait_compliance`: 0–100)

Use the W-rules from your audit. Start at 100.
- Each point where agent should have waited but continued without customer turn: −15
- Each point where agent waited properly: no deduction
- Floor at 0.

### 3.5 Agent sentiment & empathy (`agent_sentiment`: 0–100)

Start at 70 (neutral professional baseline).

Add points for (each +5, max 30 bonus):
- Empathetic phrases: "I understand", "I completely understand your concern"
- Patient language when customer is frustrated
- Positive framing / offering solutions proactively
- Using customer's name

Deduct points for (each −10 to −20):
- Dismissive language / ignoring stated concerns
- Interrupting / steamrolling
- Aggressive hard-sell after customer declined
- Rude or impatient tone

Cap at 0–100.

### 3.6 Customer sentiment trajectory (`customer_sentiment`: 0–100)

Track the customer's mood at three points: opening, middle, closing.

| Trajectory | Score |
|-----------|-------|
| negative/neutral → positive/satisfied | 90–100 |
| neutral throughout | 65–75 |
| positive → neutral (no resolution) | 40–55 |
| positive → frustrated/angry | 20–40 |
| hostile throughout, no resolution | 0–20 |

REQUIRED: set `customer_sentiment_trajectory` to a short arrow string,
e.g. "neutral → concerned → reassured" or "frustrated → angry → unresolved".

### 3.7 Call outcome classification (`call_outcome`: 0–100)

| Outcome | Score | `call_outcome_type` value |
|---------|-------|--------------------------|
| Renewed / Upsold / Issue fully resolved | 90–100 | `renewed` / `upsold` |
| Customer retained, commitment made | 80–90 | `retained` |
| Callback scheduled with positive intent | 70–80 | `callback_scheduled` |
| Partial resolution, follow-up needed | 50–65 | `partial_resolution` |
| Customer undecided, no commitment | 30–45 | `unresolved` |
| Customer declined but not churned | 15–30 | `unresolved` |
| Customer churned / escalated | 0–15 | `churned` / `escalated` |

### 3.8 Knowledge accuracy (`knowledge_accuracy`: 0–100)

Use the K-rules from your audit. Start at 100.
- Each verified-correct claim: no deduction
- Each factual error (wrong product info, wrong process): −15
- Each false promise (guaranteed results, unauthorized discounts): −25
- No factual claims made → 100

## Step 4 — Compute overall compliance score

Weighted average:

| Dimension | Weight |
|-----------|--------|
| script_compliance | 20% |
| objection_handling | 15% |
| call_checkpoints | 15% |
| wait_compliance | 10% |
| agent_sentiment | 10% |
| customer_sentiment | 10% |
| call_outcome | 10% |
| knowledge_accuracy | 10% |

Formula: `compliance_score = round(sum(score × weight for each dimension))`

## Step 5 — Build the report

### 5.1 Structured coaching recommendations

The `recommendation` field MUST be specific, warm, and actionable coaching written
directly to the agent — as a supportive coach, NOT an auditor.

**Tone rules (non-negotiable):**
- Address the agent as **"you"** — never "the agent"
- Never use "failed", "failure", "incorrect", "wrong", "falsely" — instead: "missed", "next time try", "worth practising"
- Give exactly **ONE** priority action — not a list, not bullet points
- Include at least one **copy-paste phrase** the agent can say verbatim next call (wrap in quotes)
- Keep the entire recommendation under **150 words**
- Be specific to THIS transcript — zero generic advice
- **End on a high note** — the last line must be something the agent did genuinely well

Structure:
1. **What went well** — one specific positive with a quote from the transcript
2. **One thing to try next time** — name the gap, show what to say instead (copy-paste phrase), cite the KB article
3. **Priority focus** — exactly one sentence, the single most impactful habit to build
4. **Closing encouragement** — one sentence that ends warmly and references something real from the call

Example recommendation:
```
WHAT WENT WELL:
You nailed the opening — "Good Morning Mr. Patel, I am Rahul Sharma, your account manager from IndiaMART" was word-perfect.

ONE THING TO TRY NEXT TIME:
When the customer raises a pricing concern, next time try the structured cost-comparison script: "Sir, think of it this way — IndiaMART gives you access to thousands of active buyers at just Rs. 2,500/month. A single shop in a commercial market costs 60–80K/month, and you still wait for walk-ins." This is more persuasive than a general statistic. Review: "Fund Issue (Retention Script - Objection Handling)"

PRIORITY FOCUS: Practise the fund-issue rebuttal until it feels natural — it's the one phrase that turns pricing hesitations into callbacks.

The empathy you showed when you said "I completely understand" kept Mr. Patel engaged — that's a real skill.
```

### 5.2 Report JSON

```json
{
  "job_id": "<uuid>",
  "category": "<category from top KB hit>",
  "violations_found": true,
  "violations": [
    {
      "rule": "<the extracted rule ID and text, e.g. R4: Recording disclosure>",
      "description": "<what went wrong>",
      "evidence": "<verbatim quote from transcript>",
      "kb_article": "<title of the KB article that defines this rule>"
    }
  ],
  "scores": {
    "script_compliance": 75,
    "objection_handling": 80,
    "call_checkpoints": 86,
    "wait_compliance": 85,
    "agent_sentiment": 90,
    "customer_sentiment": 60,
    "call_outcome": 80,
    "knowledge_accuracy": 85
  },
  "score_reasons": {
    "script_compliance": {
      "baseline": 100,
      "positives": [
        {"detail": "Followed prescribed greeting format"},
        {"detail": "Correctly sequenced upsell pitch after addressing concern"}
      ],
      "deductions": [
        {"detail": "Recording disclosure skipped entirely", "points": -10},
        {"detail": "Deviated from prescribed upsell flow — jumped to price before value", "points": -15}
      ],
      "summary": "Agent followed most of the script but missed 2 key mandatory steps."
    },
    "objection_handling": {
      "baseline": 100,
      "positives": [],
      "deductions": [],
      "summary": "No objections were raised during the call — dimension not applicable, scored 100."
    },
    "call_checkpoints": {
      "baseline": 100,
      "positives": [
        {"detail": "Greeting ✓"},
        {"detail": "Self introduction ✓"},
        {"detail": "Recording disclosure ✓"},
        {"detail": "Permission to proceed ✓"},
        {"detail": "Proper closing ✓"}
      ],
      "deductions": [
        {"detail": "Purpose statement not stated", "points": -14},
        {"detail": "Feedback collection skipped", "points": -14}
      ],
      "summary": "5 of 7 mandatory checkpoints hit; purpose statement and feedback collection missed."
    },
    "wait_compliance": {
      "baseline": 100,
      "positives": [
        {"detail": "Waited after greeting"},
        {"detail": "Waited after permission ask"}
      ],
      "deductions": [
        {"detail": "Continued speaking without waiting after feedback question", "points": -15},
        {"detail": "Continued speaking without waiting after objection response", "points": -15}
      ],
      "summary": "Agent paused correctly at 2 of 4 required wait points."
    },
    "agent_sentiment": {
      "baseline": 70,
      "positives": [
        {"detail": "Used empathetic phrase 'I completely understand'", "points": 5},
        {"detail": "Patient language when customer raised pricing concern", "points": 5},
        {"detail": "Positive reframing — offered cost-per-lead perspective", "points": 5},
        {"detail": "Used customer's name (Mr. Kumar) throughout", "points": 5}
      ],
      "deductions": [],
      "summary": "Professional and empathetic throughout; +20 bonus above baseline."
    },
    "customer_sentiment": {
      "baseline": 100,
      "positives": [],
      "deductions": [
        {"detail": "Customer started neutral but expressed irrelevancy concern mid-call", "points": -15},
        {"detail": "Customer raised pricing objection — ended open but not committed", "points": -13}
      ],
      "summary": "Customer moved from neutral to concerned to cautiously open; no firm commitment."
    },
    "call_outcome": {
      "baseline": 100,
      "positives": [
        {"detail": "Clear next step set — Wednesday callback agreed by customer"}
      ],
      "deductions": [
        {"detail": "No immediate commitment secured — customer needs partner discussion", "points": -25}
      ],
      "summary": "Callback scheduled with positive intent; no renewal or upsell confirmed."
    },
    "knowledge_accuracy": {
      "baseline": 100,
      "positives": [
        {"detail": "BuyLead filter explanation accurate per KB"},
        {"detail": "Platform reach framing (Rs. 2,500/month) consistent with KB"}
      ],
      "deductions": [
        {"detail": "Gold package quoted at Rs. 35,000/year — unverified against current KB pricing", "points": -15}
      ],
      "summary": "One unverified pricing claim; all other factual statements were accurate."
    }
  },
  "checkpoints": {
    "greeting": true,
    "self_introduction": true,
    "purpose_statement": true,
    "recording_disclosure": true,
    "permission_to_proceed": true,
    "feedback_collection": true,
    "proper_closing": true
  },
  "call_outcome_type": "callback_scheduled",
  "customer_sentiment_trajectory": "neutral → concerned → reassured",
  "compliance_score": 80,
  "human_review_required": false,
  "sop_outdated": false,
  "compliance_summary": "...",
  "recommendation": "WHAT WENT WELL:\n- ...\n\nWHAT TO IMPROVE:\n1. ...\n\nPRIORITY ACTION: ..."
}
```

### 5.3 Violation threshold

Set `violations_found: true` if ANY of these conditions are met:
- `compliance_score` < 70
- Any checkpoint is `false`
- `script_compliance` < 60
- `knowledge_accuracy` < 70 (factual errors are always flagged)

Each missed checkpoint or failed rule becomes a violation entry.

### 5.4 Human review flag

Set `human_review_required: true` if `compliance_score` < 70, otherwise `false`.
This flag is independent of `violations_found` and must always be present in the report JSON.

## Step 6 — Persist the report

Append the new report to the existing list (same caller may have prior analyses under this job_id).

```bash
.venv/bin/python3 -c "
import json
import sys
from database import get_job, update_job
from qdrant_helper import store_report

report = <report_json>  # Already a Python dict from Step 5
job_id = '<job_id>'
job = {'id': job_id, 'agent_name': '<agent_name>', 'agent_id': '<agent_id>', 'caller_id': '<caller_id>', 'caller_name': '<caller_name>'}

try:
    # append to history
    existing = get_job(job_id)
    prev = existing.get('report') if existing else None
    if prev:
        try:
            parsed = json.loads(prev)
            history = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
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
except Exception as e:
    print(f'ERROR_PERSIST: SQLite write failed: {str(e)}', file=sys.stderr)
    sys.exit(1)

try:
    store_report(job, report)
except Exception as e:
    print(f'WARNING_QDRANT: Qdrant write failed (non-fatal): {str(e)}', file=sys.stderr)
"
```

**Important:** SQLite write (update_job) must succeed. Qdrant failure is non-fatal and should not block completion. If update_job fails, exit with code 1 and the job stays in-flight for manual retry.

## Step 7 — Send alert if violations found

Only run this if `violations_found` is true:

```bash
.venv/bin/python3 email_helper.py \
  --to yashwantsinghchandra258@gmail.com \
  --subject "Compliance Violation — <agent_name>" \
  --body "<compliance_summary>\n\nScores: script_compliance=<score>, objection_handling=<score>, call_checkpoints=<score>, wait_compliance=<score>, agent_sentiment=<score>, customer_sentiment=<score>, call_outcome=<score>, knowledge_accuracy=<score>\nOverall: <compliance_score>/100\n\nPRIORITY ACTION: <priority_action_from_recommendation>"
```

## Step 8 — Exit

Print `JOB_DONE` (to stdout) and stop. Do not poll for another job.

**For observability:** Print `JOB_DONE` only after Step 6 succeeds (SQLite write confirmed). This signal tells `open_claude.sh` that the job is complete and it can claim the next one.

**Stuck jobs:** If a `claude --print` process hangs (no output for >5 min), the calling `open_claude.sh` loop will eventually timeout and try again. To manually unstick a job, set its SQLite status back to `pending`:
```bash
.venv/bin/python3 -c "from database import update_job; update_job('<job_id>', status='pending')"
```
Then restart the controller.

## On any error

```bash
.venv/bin/python3 -c "
from database import update_job
update_job('<job_id>', status='failed', error='<error_message>')
"
```

Then exit.

---

## Calibration Example

Below is a fully scored example. Use it to calibrate your scoring —
your output for similar transcripts should produce similar scores.

### Example transcript

```
Agent: Good Morning Mr. Kumar. I am Priya Verma, your account manager from IndiaMART. How are you doing?
Customer: I am good, thanks.
Agent: Is this the right time to talk to you?
Customer: Yes, please go ahead.
Agent: Thank you Sir. This call is being made to take your feedback on the service and will be recorded for training and quality purpose.
Customer: Okay.
Agent: Sir, you have been associated with IndiaMART since 2021. How has your overall experience been on our platform?
Customer: Honestly, it has been mixed. I get leads but many of them are not relevant to my business.
Agent: I understand your concern, Sir. Irrelevant leads can be frustrating. Let me check your account... Sir, I can see that your product catalog has 12 items listed. Sometimes when the catalog is broader, the system matches more diverse buyer queries. Have you tried using the BuyLead filter to focus on the most relevant categories?
Customer: No, I didn't know about that.
Agent: No problem, Sir. I can help you set that up. Also, I wanted to let you know that your service renewal is coming up next month. Given your experience, I would recommend upgrading to our Gold package which includes priority lead matching — that specifically helps with relevance. The Gold package is Rs. 35,000 per year.
Customer: That's quite expensive. I'm not sure the current service is worth renewing, let alone upgrading.
Agent: I completely understand, Sir. Let me share this perspective — you currently have an online presence reaching thousands of buyers at roughly Rs. 2,500 per month. If you compare that to maintaining a physical showroom or running print ads, the reach-per-rupee is significantly better. And with Gold, the priority matching means the leads you receive are pre-filtered for relevance.
Customer: Hmm, that makes sense. But I need to discuss with my business partner first.
Agent: Absolutely, Sir. Take your time. I will follow up with you next Wednesday. Would that work?
Customer: Yes, Wednesday is fine.
Agent: Thank you for your time, Mr. Kumar. If you have any questions before then, feel free to reach out. Have a great day!
Customer: Thank you, bye.
```

### Expected output

```
EXTRACTED RULES from "Renewal script" + "Upsell Script" (top hits):

SCRIPT_COMPLIANCE:
  R1. Greet with "Good Morning/Afternoon Mr./Ms. <Name>" — PASS
  R2. State "I am <Name>, your account manager from IndiaMART" — PASS
  R3. Ask "Is this the right time to talk to you?" and WAIT — PASS
  R4. State recording disclosure and WAIT — PASS
  R5. Ask about overall experience and WAIT — PASS
  R6. Address customer concern before pitching — PASS (addressed irrelevancy first)
  R7. Introduce upsell value proposition — PASS (Gold package)
  R8. Handle objection with prescribed rebuttal — PARTIAL (used cost comparison but not exact KB wording)
  R9. Set follow-up / next steps — PASS (Wednesday callback)

WAIT_COMPLIANCE:
  W1. Wait after greeting — PASS
  W2. Wait after permission ask — PASS
  W3. Wait after recording disclosure — PASS
  W4. Wait after experience question — PASS
  W5. Wait after objection response — PASS

KNOWLEDGE_ACCURACY:
  K1. "product catalog has 12 items" — assumed from account, PASS
  K2. "Gold package is Rs. 35,000 per year" — VERIFY (KB may differ)
  K3. "priority lead matching" — PASS (consistent with Gold features)
  K4. "Rs. 2,500 per month" — PASS (consistent with KB pricing comparison)
```

### Expected scores

```json
{
  "job_id": "example-001",
  "category": "Scripts",
  "violations_found": false,
  "violations": [],
  "scores": {
    "script_compliance": 88,
    "objection_handling": 75,
    "call_checkpoints": 100,
    "wait_compliance": 100,
    "agent_sentiment": 92,
    "customer_sentiment": 72,
    "call_outcome": 75,
    "knowledge_accuracy": 85
  },
  "score_reasons": {
    "script_compliance": "Agent followed 8/9 script rules fully. Partial deduction (−12) for objection rebuttal: used a cost-comparison approach rather than the KB-prescribed fund-issue rebuttal with exact service breakdowns.",
    "objection_handling": "One pricing objection raised ('That's quite expensive'). Agent responded with a cost-comparison argument — broadly consistent with KB but not the exact prescribed rebuttal listing specific included services (−25). Partial credit awarded.",
    "call_checkpoints": "All 7 mandatory checkpoints completed in correct order: greeting, self-introduction, purpose statement, recording disclosure, permission, feedback collection, and professional closing.",
    "wait_compliance": "Agent paused at all 5 prescribed wait points: after greeting, permission ask, recording disclosure, experience question, and objection response. No violations.",
    "agent_sentiment": "Highly empathetic tone. Used 'I understand your concern, Sir' and 'I completely understand, Sir'. Addressed customer's irrelevancy pain point before pitching. Used customer's name twice. Positive framing throughout (+22 from baseline 70).",
    "customer_sentiment": "Started neutral, moved to concerned about lead relevancy, then reassured after the agent explained BuyLead filters and cost comparison. Ended open/considering — not fully committed.",
    "call_outcome": "Callback successfully scheduled for next Wednesday with customer agreement. Positive intent confirmed but no commitment to renew or upgrade yet.",
    "knowledge_accuracy": "Agent quoted Rs. 35,000/year for Gold package — could not be verified against KB pricing (−15 for unverified claim). All other product information (priority lead matching, BuyLead filters, Rs. 2,500/month cost comparison) was consistent with KB."
  },
  "checkpoints": {
    "greeting": true,
    "self_introduction": true,
    "purpose_statement": true,
    "recording_disclosure": true,
    "permission_to_proceed": true,
    "feedback_collection": true,
    "proper_closing": true
  },
  "call_outcome_type": "callback_scheduled",
  "customer_sentiment_trajectory": "neutral → concerned → reassured → open",
  "score_reasons": {
    "script_compliance": {
      "baseline": 100,
      "positives": [
        {"detail": "Correct greeting: 'Good Morning Mr. Kumar. I am Priya Verma, your account manager from IndiaMART'"},
        {"detail": "Asked permission to proceed and waited for response"},
        {"detail": "Gave recording disclosure before feedback question"},
        {"detail": "Addressed irrelevancy concern before pitching upsell"},
        {"detail": "Introduced Gold package with value proposition"},
        {"detail": "Set clear follow-up — Wednesday callback"}
      ],
      "deductions": [
        {"detail": "Objection rebuttal deviated from KB prescribed wording — used general cost comparison instead of structured fund-issue script", "points": -12}
      ],
      "summary": "Followed 8 of 9 script rules fully; 1 partial on objection rebuttal wording."
    },
    "objection_handling": {
      "baseline": 100,
      "positives": [
        {"detail": "Acknowledged pricing objection empathetically: 'I completely understand, Sir'"},
        {"detail": "Offered cost-per-reach comparison (Rs. 2,500/month vs offline alternatives)"}
      ],
      "deductions": [
        {"detail": "Did not use prescribed KB rebuttal — missed listing specific included services (PNS, 7 FREE BuyLeads/week, Catalog support)", "points": -25}
      ],
      "summary": "Pricing objection handled but not with the exact KB-prescribed rebuttal structure."
    },
    "call_checkpoints": {
      "baseline": 100,
      "positives": [
        {"detail": "Greeting ✓ — 'Good Morning Mr. Kumar'"},
        {"detail": "Self introduction ✓ — 'I am Priya Verma, your account manager from IndiaMART'"},
        {"detail": "Purpose statement ✓ — 'to take your feedback on the service'"},
        {"detail": "Recording disclosure ✓ — 'will be recorded for training and quality purpose'"},
        {"detail": "Permission to proceed ✓ — 'Is this the right time to talk to you?'"},
        {"detail": "Feedback collection ✓ — 'How has your overall experience been on our platform?'"},
        {"detail": "Proper closing ✓ — 'Thank you for your time... Have a great day!'"}
      ],
      "deductions": [],
      "summary": "All 7 of 7 mandatory checkpoints completed in correct order."
    },
    "wait_compliance": {
      "baseline": 100,
      "positives": [
        {"detail": "Waited after greeting — customer responded 'I am good, thanks'"},
        {"detail": "Waited after permission ask — customer responded 'Yes, please go ahead'"},
        {"detail": "Waited after recording disclosure — customer responded 'Okay'"},
        {"detail": "Waited after experience question — customer gave detailed feedback"},
        {"detail": "Waited after objection response — customer responded 'Hmm, that makes sense'"}
      ],
      "deductions": [],
      "summary": "Agent waited at every mandatory pause point; full compliance."
    },
    "agent_sentiment": {
      "baseline": 70,
      "positives": [
        {"detail": "Empathetic phrasing: 'I completely understand, Sir'", "points": 5},
        {"detail": "Patient when customer raised irrelevancy and pricing concerns", "points": 5},
        {"detail": "Positive reframing — reach-per-rupee perspective", "points": 5},
        {"detail": "Used customer's name 'Mr. Kumar' throughout the call", "points": 5},
        {"detail": "Proactively offered to help set up BuyLead filter", "points": 7}
      ],
      "deductions": [],
      "summary": "Consistently empathetic, patient, and constructive throughout; +22 above baseline."
    },
    "customer_sentiment": {
      "baseline": 100,
      "positives": [
        {"detail": "Customer became more open after cost-comparison reframe"}
      ],
      "deductions": [
        {"detail": "Customer expressed frustration about irrelevant leads mid-call", "points": -15},
        {"detail": "Customer raised pricing concern and ended call without committing", "points": -13}
      ],
      "summary": "Customer moved from neutral → concerned → cautiously open; no firm commitment reached."
    },
    "call_outcome": {
      "baseline": 100,
      "positives": [
        {"detail": "Clear next step agreed — Wednesday callback confirmed"}
      ],
      "deductions": [
        {"detail": "No immediate renewal or upsell commitment — needs partner discussion", "points": -25}
      ],
      "summary": "Callback scheduled with positive intent; outcome pending partner discussion."
    },
    "knowledge_accuracy": {
      "baseline": 100,
      "positives": [
        {"detail": "BuyLead filter explanation accurate per KB"},
        {"detail": "Platform reach framing (Rs. 2,500/month) consistent with KB pricing comparison"},
        {"detail": "Priority lead matching feature description accurate for Gold package"}
      ],
      "deductions": [
        {"detail": "Gold package quoted at Rs. 35,000/year — not verified against current KB pricing", "points": -15}
      ],
      "summary": "One unverified pricing claim; all other product and feature claims were accurate."
    }
  },
  "compliance_score": 87,
  "human_review_required": false,
  "sop_outdated": false,
  "compliance_summary": "Agent followed the combined renewal/upsell script effectively. All 7 checkpoints hit. Strong empathy and professional tone throughout. Addressed irrelevancy concern before pitching upsell. Objection handling used a cost-comparison approach consistent with KB but not the exact prescribed rebuttal wording. Customer moved from concern to openness with a callback scheduled.",
  "recommendation": "WHAT WENT WELL:\nYou hit every single checkpoint in the right order — that's a perfect 7/7 and sets the call up for success from the first word.\n\nONE THING TO TRY NEXT TIME:\nWhen Mr. Kumar said \"That's quite expensive\", next time try: \"Sir, think of it this way — IndiaMART costs you about Rs. 2,500 a month. A shop in a commercial market costs 60–80K a month, and you still wait for walk-ins. With Gold, those buyers come to you, pre-filtered for relevance.\" This lands much harder than a general statistic. Review: \"Fund Issue (Retention Script - Objection Handling)\"\n\nPRIORITY FOCUS: Practise that cost-comparison rebuttal until it flows naturally — it's the one script line that most often converts a hesitant customer into a callback.\n\nThe way you proactively offered to set up the BuyLead filter mid-call was genuinely helpful — Mr. Kumar appreciated it and it built real trust."
}
```

### Why these scores?

- `script_compliance: 88` — followed 8/9 rules fully, 1 partial (objection rebuttal wording)
- `objection_handling: 75` — one objection (pricing), handled but not with exact KB rebuttal
- `call_checkpoints: 100` — all 7/7 checkpoints hit
- `wait_compliance: 100` — agent waited at every prescribed point
- `agent_sentiment: 92` — empathetic, patient, used customer's name, positive framing (+22 from baseline 70)
- `customer_sentiment: 72` — started neutral, went concerned, ended open/reassured but not committed
- `call_outcome: 75` — callback scheduled with positive intent
- `knowledge_accuracy: 85` — one unverified pricing claim (−15)

Use this calibration to anchor your scoring. A call with all checkpoints hit but one weak objection response scores ~87. A call missing 2 checkpoints and ignoring an objection would score ~55–65.

---

---

## Production Operations & Monitoring

**Controller health checks:**
- Controller logs are in `logs/claude.log`. Watch for `ERROR_` or `WARNING_` prefixes.
- Each job should print debug output like `DEBUG_STEP2.5: ...` to stderr before returning `JOB_DONE`.
- If no `JOB_DONE` appears for >5 min, the `claude --print` process may be hung — kill it and reset the job to `pending`.

**Metrics to monitor:**
- Job queue depth: `curl http://localhost:8001/api/jobs | wc -l`
- Failed jobs: `SELECT COUNT(*) FROM jobs WHERE status='failed'` in `jobs.db`
- Qdrant write success rate: grep `WARNING_QDRANT` in logs

**Recovery:**
- To reset a stuck job: `python3 -c "from database import update_job; update_job('<job_id>', status='pending')"`
- To view job details: `curl http://localhost:8001/api/jobs/<job_id>`
- To check for orphaned processes: `ps aux | grep "claude --print" | grep -v grep`

---

## Rules

- Handle exactly one job per run.
- All commands run from the project root: `/home/yashwant-singh/office/hackathon_15May/velocityAI`
- Use `.venv/bin/python3` for all Python calls.
- Qdrant write failures are non-fatal — log and continue.
- Never skip Step 8 — always exit cleanly.
- ALL eight scores MUST be computed for every transcript, even if some
  dimensions are not applicable (score them 100 with a note).
- The `scores` object, `checkpoints` object, `call_outcome_type`,
  `customer_sentiment_trajectory`, `score_reasons`, `human_review_required`,
  and `sop_outdated` are REQUIRED fields in every report.
- `human_review_required` MUST be a boolean: `true` if `compliance_score` < 70,
  `false` otherwise. Set this AFTER computing `compliance_score`.
- `sop_outdated` MUST be a boolean: `true` if the top KB hit score < 0.60,
  `false` otherwise. Set this during the KB relevance check in Step 2.
- `score_reasons` MUST contain one structured object per dimension key. Each object MUST have:
  - `baseline` (integer): starting score before any adjustments (100 for most dims; 70 for agent_sentiment)
  - `positives` (array): things the agent did correctly — each item is `{"detail": "..."}`.
    For agent_sentiment where bonuses are explicitly added, include `"points": <positive integer>`.
    Use an empty array `[]` if nothing positive was observed.
  - `deductions` (array): specific things that reduced the score — each item is `{"detail": "...", "points": <negative integer>}`.
    Points MUST be the actual numeric deduction (e.g. -10, -15, -25). Use an empty array `[]` if no deductions.
  - `summary` (string): one sentence overall assessment for this dimension.
  For N/A dimensions (e.g. no objections raised), set positives/deductions to `[]` and explain in summary.
- For `script_compliance`, `objection_handling`, and `knowledge_accuracy`
  score_reasons: if top KB hit score < 0.60, set `summary` to begin with "No matching
  SOP was found for this call topic — the knowledge base appears to be
  outdated or incomplete for this category and needs to be updated." Then
  still populate positives/deductions based on what was observable in the transcript.
  If score ≥ 0.60, proceed with normal structured output (no caveat needed).
- The `scores` object, `checkpoints` object, `call_outcome_type`, and
  `customer_sentiment_trajectory` are REQUIRED fields in every report.
- Step 2.5 (rule extraction + audit trail) is MANDATORY. Do not skip it.
  The audit trail is what makes scoring explainable and consistent.
- Violations must include `kb_article` field referencing which KB article
  defines the rule that was broken.
- The `recommendation` field MUST follow the structured format:
  WHAT WENT WELL / ONE THING TO TRY NEXT TIME / PRIORITY FOCUS / closing encouragement.
- The `recommendation` field MUST use supportive coaching tone: address the agent as "you",
  never use "failed"/"incorrect"/"wrong" (use "missed"/"next time try" instead), include
  exactly one copy-paste phrase the agent can say verbatim, keep total under 150 words,
  and end on a positive note referencing something specific from the call.
