#!/usr/bin/env bash
# Stops all VelocityAI processes: uvicorn API server, open_claude.sh poll loop,
# and any in-flight `claude --print` subprocesses.

echo "Stopping VelocityAI..."

pkill -f "uvicorn main:app" 2>/dev/null && echo "  killed: uvicorn" || echo "  not running: uvicorn"
pkill -f "open_claude.sh"   2>/dev/null && echo "  killed: open_claude.sh" || echo "  not running: open_claude.sh"
pkill -f "claude --print"   2>/dev/null && echo "  killed: claude --print" || echo "  not running: claude --print"

echo "Done."
