#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

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

# --- start server ---
echo "Starting API server on http://localhost:8001 ..."
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 \
  > "$LOG_DIR/server.log" 2>&1 &
echo $! > "$LOG_DIR/server.pid"

# give the server a moment to bind the port
sleep 2

# --- start claude controller ---
echo "Starting Claude compliance controller..."
nohup bash "$SCRIPT_DIR/open_claude.sh" \
  > "$LOG_DIR/claude.log" 2>&1 &
echo $! > "$LOG_DIR/claude.pid"

echo "Pipeline is up (background)."
echo "  API:    http://localhost:8001"
echo "  Logs:   $LOG_DIR/server.log  |  $LOG_DIR/claude.log"
echo "  Stop:   ./scripts/stop_all.sh"
