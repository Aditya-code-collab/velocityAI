#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[claude-controller] Poller started."

# skill.md is imported into CLAUDE.md via `@skill.md`, so piping it
# on stdin makes claude treat it as passive context and reply conversationally
# instead of running the steps. Pass it as an explicit imperative prompt.
PREAMBLE="Execute the following compliance-worker instructions NOW as a one-shot task. Do exactly the steps in order, run the bash commands, and end by printing JOB_DONE or NO_JOBS. Do not ask questions."

# Hard timeout per job (seconds). Kill the subprocess if it hangs beyond this.
JOB_TIMEOUT=360

while true; do
  # Run claude with a hard timeout. stderr goes to claude.log, stdout captured.
  OUTPUT=$(timeout "$JOB_TIMEOUT" claude --print \
    --allowedTools Bash \
    --dangerously-skip-permissions \
    "$PREAMBLE"$'\n\n'"$(cat skill.md)" 2>&1) || EXIT_CODE=$?

  # timeout exits 124 when it kills the process
  if [[ "${EXIT_CODE:-0}" -eq 124 ]]; then
    echo "[claude-controller] ERROR: job timed out after ${JOB_TIMEOUT}s — process killed. Check logs and reset stuck jobs." >&2
    sleep 5
    continue
  fi

  if echo "$OUTPUT" | grep -qF "NO_JOBS"; then
    sleep 5
  elif echo "$OUTPUT" | grep -qF "JOB_DONE"; then
    echo "[claude-controller] Job processed."
    echo "$OUTPUT"
    # immediately re-check for more pending jobs
  else
    # Neither sentinel printed — claude likely didn't run the steps.
    # Sleep to avoid a hot loop burning API calls (the old failure mode).
    echo "[claude-controller] WARNING: no JOB_DONE/NO_JOBS sentinel — backing off 15s." >&2
    echo "$OUTPUT"
    sleep 15
  fi
done
