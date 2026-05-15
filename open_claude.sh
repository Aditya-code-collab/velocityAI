#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[claude-controller] Poller started."

while true; do
  OUTPUT=$(claude --print \
    --allowedTools Bash \
    --dangerously-skip-permissions \
    < controller.md 2>&1)

  if echo "$OUTPUT" | grep -q "NO_JOBS"; then
    sleep 5
  else
    echo "[claude-controller] Job processed."
    echo "$OUTPUT"
    # immediately re-check for more pending jobs
  fi
done
