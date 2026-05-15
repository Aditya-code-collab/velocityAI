#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[claude-controller] Poller started."

# controller.md is imported into CLAUDE.md via `@controller.md`, so piping it
# on stdin makes claude treat it as passive context and reply conversationally
# instead of running the steps. Pass it as an explicit imperative prompt.
PREAMBLE="Execute the following compliance-worker instructions NOW as a one-shot task. Do exactly the steps in order, run the bash commands, and end by printing JOB_DONE or NO_JOBS. Do not ask questions."

while true; do
  OUTPUT=$(claude --print \
    --allowedTools Bash \
    --dangerously-skip-permissions \
    "$PREAMBLE"$'\n\n'"$(cat controller.md)" 2>&1)

  if echo "$OUTPUT" | grep -q "NO_JOBS"; then
    sleep 5
  elif echo "$OUTPUT" | grep -q "JOB_DONE"; then
    echo "[claude-controller] Job processed."
    echo "$OUTPUT"
    # immediately re-check for more pending jobs
  else
    # Neither sentinel printed — claude likely didn't run the steps.
    # Sleep to avoid a hot loop burning API calls (the old failure mode).
    echo "[claude-controller] WARNING: no JOB_DONE/NO_JOBS sentinel — backing off 15s."
    echo "$OUTPUT"
    sleep 15
  fi
done
