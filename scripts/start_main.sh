#!/usr/bin/env bash
# start_main.sh - Start the supervised backend (main.py) in the background.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPERVISOR_LOG="${PROJECT_DIR}/logs/supervisor.log"
SUPERVISOR_PID_FILE="${PROJECT_DIR}/logs/supervisor.pid"

mkdir -p "${PROJECT_DIR}/logs"

# Stop any existing supervisor first
if [ -f "$SUPERVISOR_PID_FILE" ]; then
    OLD_PID=$(cat "$SUPERVISOR_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing supervisor (pid $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null
        sleep 2
    fi
fi

# Start the supervisor fully detached (own session, survives shell exit)
setsid nohup "${PROJECT_DIR}/scripts/supervise_main.sh" >> "$SUPERVISOR_LOG" 2>&1 < /dev/null &
SUPERVISOR_PID=$!
echo "$SUPERVISOR_PID" > "$SUPERVISOR_PID_FILE"

echo "Supervisor started (pid $SUPERVISOR_PID)"
echo "Logs: ${PROJECT_DIR}/logs/server.log"
