import os
from config import VIOLATION_EMAIL_TO, PROJECT_DIR


def build_prompt(job_id: str, transcription: str, sops: list[dict]) -> str:
    email_script = os.path.join(PROJECT_DIR, "email_helper.py")
    venv_python = os.path.join(PROJECT_DIR, ".venv", "bin", "python3")

    # Top hit — full content + rules for violation checking
    top = sops[0]
    rules_text = "\n".join(f"  {j}. {r}" for j, r in enumerate(top["rules"], 1))
    sops_block = f"""### MATCHED SOP: {top['title']}
Category: {top['category']}  |  Relevance score: {top['score']}

{top['content']}

Rules to check:
{rules_text}"""

    # Runner-up SOPs — category label only, so Claude can confirm it picked the right one
    if len(sops) > 1:
        others = ", ".join(f"{s['category']} (score {s['score']})" for s in sops[1:])
        sops_block += f"\n\n### Other candidate categories (not selected): {others}"

    return f"""You are a compliance analyst for IndiaMart sales operations.
Your task: analyse the call transcription below against the retrieved SOPs, identify any violations, and produce a structured report.

=== JOB ID ===
{job_id}

=== CALL TRANSCRIPTION ===
{transcription}

=== RETRIEVED SOPs ===
{sops_block}

=== INSTRUCTIONS ===
1. Determine the single best-matching SOP category for this call.
2. Check each rule in that SOP against the transcription.
3. For every violation, note:
   - The exact rule broken
   - What the agent did wrong
   - A direct quote from the transcription as evidence
4. Compute a compliance_score (0–100):  100 = full compliance, deduct proportionally per violation.
5. Write a short compliance_summary and recommendation.

=== EMAIL (run this ONLY if violations_found is true) ===
If there are violations, send an alert email using the Bash tool:

```bash
{venv_python} {email_script} \\
  --to "{VIOLATION_EMAIL_TO}" \\
  --subject "SOP Violation Alert — Job {job_id}" \\
  --body "Job ID: {job_id}\\nCategory: <CATEGORY>\\n\\nViolations:\\n<LIST_VIOLATIONS_HERE>\\n\\nCompliance Score: <SCORE>/100"
```

Replace the placeholders with actual values before running.

=== OUTPUT FORMAT ===
After all analysis (and after sending the email if applicable), output the final report
EXACTLY between these two markers on their own lines — no other text after the end marker:

COMPLIANCE_REPORT_START
{{
  "job_id": "{job_id}",
  "category": "<category>",
  "violations_found": <true|false>,
  "violations": [
    {{
      "rule": "<rule text>",
      "description": "<what went wrong>",
      "evidence": "<verbatim quote from transcription>"
    }}
  ],
  "compliance_score": <0-100>,
  "compliance_summary": "<1-2 sentence summary>",
  "recommendation": "<actionable fix>"
}}
COMPLIANCE_REPORT_END
"""
