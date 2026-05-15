#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- checks ---
if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found. Ask a teammate for the values."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  echo "Installing dependencies..."
  .venv/bin/pip install -q -r requirements.txt
fi

# --- cleanup on exit ---
cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$SERVER_PID" "$WORKER_PID" 2>/dev/null || true
  wait "$SERVER_PID" "$WORKER_PID" 2>/dev/null || true
  echo "Done."
}
trap cleanup SIGINT SIGTERM

# --- start server ---
echo "Starting API server on http://localhost:8001 ..."
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 2>&1 | sed 's/^/[server] /' &
SERVER_PID=$!

# give the server a moment to bind the port
sleep 2

# --- start worker ---
echo "Starting worker..."
.venv/bin/python3 worker.py 2>&1 | sed 's/^/[worker] /' &
WORKER_PID=$!

echo "Pipeline is up. Press Ctrl+C to stop."
echo ""

wait "$SERVER_PID" "$WORKER_PID"
