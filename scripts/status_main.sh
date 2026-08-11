#!/usr/bin/env bash
# status_main.sh - Show status of the supervised backend.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPERVISOR_PID_FILE="${PROJECT_DIR}/logs/supervisor.pid"
SERVER_PID_FILE="${PROJECT_DIR}/logs/server.pid"

echo "== Supervisor =="
if [ -f "$SUPERVISOR_PID_FILE" ] && kill -0 "$(cat "$SUPERVISOR_PID_FILE")" 2>/dev/null; then
    echo "RUNNING (pid $(cat "$SUPERVISOR_PID_FILE"))"
else
    echo "NOT RUNNING"
fi

echo "== Server (main.py) =="
if [ -f "$SERVER_PID_FILE" ] && kill -0 "$(cat "$SERVER_PID_FILE")" 2>/dev/null; then
    echo "RUNNING (pid $(cat "$SERVER_PID_FILE"))"
else
    echo "NOT RUNNING"
fi

echo "== Health =="
curl -s -o /dev/null -w 'HTTP %{http_code}\n' --max-time 10 http://localhost:8000/health
