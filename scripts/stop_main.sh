#!/usr/bin/env bash
# stop_main.sh - Stop the supervised backend and its supervisor.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPERVISOR_PID_FILE="${PROJECT_DIR}/logs/supervisor.pid"
SERVER_PID_FILE="${PROJECT_DIR}/logs/server.pid"

# Stop the server child first (so the supervisor's wait() returns)
if [ -f "$SERVER_PID_FILE" ]; then
    PID=$(cat "$SERVER_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        echo "Stopped server (pid $PID)"
    fi
fi
sleep 1

# Then stop the supervisor
if [ -f "$SUPERVISOR_PID_FILE" ]; then
    PID=$(cat "$SUPERVISOR_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        echo "Stopped supervisor (pid $PID)"
    fi
fi

echo "Backend stopped."
