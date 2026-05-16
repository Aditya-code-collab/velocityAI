# VelocityAI — Pipeline Flowchart

## Full System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER / CLIENT                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
           ┌─────────────┴──────────────┐
           │                            │
           ▼                            ▼
  ┌─────────────────┐          ┌─────────────────────┐
  │ POST             │          │ POST                 │
  │ /api/transcription│          │ /api/transcribe-audio│
  │ (text / file)    │          │ (WAV, MP3, M4A …)   │
  └────────┬────────┘          └──────────┬──────────┘
           │                              │
           │                              ▼
           │                   ┌─────────────────────┐
           │                   │   Sarvam AI STT      │
           │                   │   Saarika v2.5       │
           │                   │   (Indian languages, │
           │                   │    Hinglish, telephony│
           │                   └──────────┬──────────┘
           │                              │  transcript string
           └──────────────┬───────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  caller_id seen       │
              │  before?              │
              └───────┬───────────────┘
                      │
            ┌─────────┴─────────┐
            │ YES               │ NO
            ▼                   ▼
   reuse same job_id     create new job_id
   reset → pending       status = pending
            │                   │
            └─────────┬─────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │   SQLite  jobs.db     │
          │   status: pending     │
          └───────────┬───────────┘
                      │
                      │  (open_claude.sh polls every 5s)
                      │
                      ▼
          ┌───────────────────────┐
          │   open_claude.sh      │
          │   poll loop           │
          │   (one at a time!)    │
          └───────────┬───────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  claude --print       │
          │  < skill.md           │
          │  fresh process,       │
          │  zero context         │
          └───────────┬───────────┘
                      │
```

---

## Inside claude --print (skill.md steps)

```
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 1 — Claim job                                       │
  │  claim_next_pending() → atomically sets status=processing│
  │  output = NO_JOBS → exit immediately                     │
  │  output = ERROR_CLAIM → log + exit 1                     │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 2 — Embed + search KB                               │
  │  embed(transcription) → search indiamart_kb (top-5 hits) │
  │  each hit: category, folder, title, content, score       │
  │                                                          │
  │  top-hit score > 0.60 ──────────────────► sop_outdated=false
  │  top-hit score ≤ 0.60 ──────────────────► sop_outdated=true
  │                         cap script_compliance at 50      │
  │                         prefix affected score_reasons    │
  │                         with "No matching SOP found …"   │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 2.5 — Extract rules + audit trail (MANDATORY)       │
  │  Read top KB hit's content                               │
  │  Extract numbered checklist per dimension:               │
  │    SCRIPT_COMPLIANCE  → R1, R2, R3 …                    │
  │    WAIT_COMPLIANCE    → W1, W2, W3 …                    │
  │    KNOWLEDGE_ACCURACY → K1, K2, K3 …                    │
  │  For each rule: PASS / FAIL / PARTIAL / N/A             │
  │  Print: DEBUG_STEP2.5: transcript N chars, top hit …    │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 3 — Score 8 dimensions (0–100 each)                 │
  │                                                          │
  │  script_compliance    — rule audit deductions from 100   │
  │  objection_handling   — per-objection KB rebuttal match  │
  │  call_checkpoints     — 7 mandatory checkpoints (×14 pt) │
  │  wait_compliance      — W-rule audit deductions from 100 │
  │  agent_sentiment      — baseline 70 ± empathy/rudeness   │
  │  customer_sentiment   — opening → middle → closing mood  │
  │  call_outcome         — renewal/callback/churn scale     │
  │  knowledge_accuracy   — K-rule audit deductions from 100 │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 4 — Weighted compliance_score                       │
  │                                                          │
  │  script_compliance  × 20%                                │
  │  objection_handling × 15%                                │
  │  call_checkpoints   × 15%                                │
  │  wait_compliance    × 10%                                │
  │  agent_sentiment    × 10%                                │
  │  customer_sentiment × 10%                                │
  │  call_outcome       × 10%                                │
  │  knowledge_accuracy × 10%                                │
  │  ──────────────────────────                              │
  │  compliance_score = round(weighted sum)                  │
  │                                                          │
  │  violations_found = true if:                             │
  │    compliance_score < 70  OR  any checkpoint = false     │
  │    script_compliance < 60 OR  knowledge_accuracy < 70    │
  │                                                          │
  │  human_review_required = compliance_score < 70           │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 5 — Build report JSON                               │
  │  scores, score_reasons (1 per dimension)                 │
  │  checkpoints (7 booleans)                                │
  │  violations[] with kb_article reference                  │
  │  call_outcome_type, customer_sentiment_trajectory        │
  │  compliance_summary, recommendation                      │
  │  (WHAT WENT WELL / WHAT TO IMPROVE / PRIORITY ACTION)   │
  │  sop_outdated, human_review_required                     │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 6 — Persist report                                  │
  │                                                          │
  │  SQLite update_job()  ◄── MUST succeed                   │
  │    append to report[] history                            │
  │    status = completed                                     │
  │    store violations_found, compliance_score              │
  │         │                                                │
  │         │ ERROR_PERSIST → exit 1 (job stays in-flight)   │
  │         │                                                │
  │  Qdrant store_report()  ◄── non-fatal                    │
  │    new point per analysis run                            │
  │    vector = embed(summary + recommendation)              │
  │         │                                                │
  │         │ WARNING_QDRANT → log and continue              │
  └───────────────────────────┬──────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────┐
              │  violations_found?    │
              └───────┬───────────────┘
                      │
            ┌─────────┴─────────┐
            │ YES               │ NO
            ▼                   │
  ┌──────────────────┐          │
  │ STEP 7 — Email   │          │
  │ alert via SMTP   │          │
  │ smtp.gmail.com   │          │
  └────────┬─────────┘          │
           │                   │
           └─────────┬─────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────────────────┐
  │ STEP 8 — Exit                                            │
  │  print JOB_DONE (stdout)                                 │
  │  open_claude.sh sees JOB_DONE → claims next pending job  │
  └──────────────────────────────────────────────────────────┘
```

---

## Data stores

```
  ┌──────────────────────────────────────────────────────────┐
  │                      SQLite  jobs.db                     │
  │                                                          │
  │  id          UUID                                        │
  │  caller_id   string  (same caller → same job_id reused)  │
  │  agent_name, agent_id, caller_name                       │
  │  transcription                                           │
  │  status      pending → processing → completed / failed   │
  │  report      JSON array  (one object per analysis run)   │
  │  violations_found, compliance_score, category            │
  └──────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────┐
  │               Qdrant  (34.47.255.166:80)                 │
  │                                                          │
  │  indiamart_kb          ← compliance search source        │
  │    970 KB articles, 1536-dim, uuid5(relative_path) IDs   │
  │                                                          │
  │  indiamart_sops        ← legacy (5 SOPs, rules[])        │
  │                                                          │
  │  indiamart_reports     ← one point per analysis run      │
  │    vector = embed(summary + recommendation)              │
  │    payload: all report fields + agent/caller metadata    │
  └──────────────────────────────────────────────────────────┘
```

---

## Error paths

```
  open_claude.sh spawns claude --print
          │
          ├─ NO_JOBS output          → sleep 5s, retry
          │
          ├─ ERROR_CLAIM             → log, exit 1 (job stays pending)
          │
          ├─ ERROR_TIMEOUT           → embed/search >30s; exit 1
          │
          ├─ ERROR_SEARCH            → Qdrant unreachable; exit 1
          │
          ├─ ERROR_PERSIST           → SQLite write failed; exit 1
          │                            job stays in-flight → manual reset
          │
          ├─ WARNING_QDRANT          → Qdrant write failed (non-fatal)
          │                            report in SQLite only; continue
          │
          └─ no JOB_DONE after 5min → process hung
                                       kill: pkill -f "claude --print"
                                       reset: update_job(id, status='pending')
                                       restart: bash open_claude.sh &
```
