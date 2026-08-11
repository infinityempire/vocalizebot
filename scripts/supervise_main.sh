#!/usr/bin/env bash
# ============================================================================
# supervise_main.sh - Persistent supervisor for the primary backend (main.py)
#
# Automatically restarts the service if it crashes or exits unexpectedly.
# Backoff grows exponentially (1s -> 2s -> 4s ... capped at MAX_BACKOFF) to
# avoid restart loops when the environment is broken.
#
# Usage:
#   scripts/start_main.sh   # start supervised backend (detached)
#   scripts/stop_main.sh    # stop backend + supervisor
#   scripts/status_main.sh  # show status
# ============================================================================
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
MAIN_SCRIPT="${PROJECT_DIR}/main.py"
LOG_FILE="${PROJECT_DIR}/logs/server.log"
PID_FILE="${PROJECT_DIR}/logs/server.pid"
MAX_BACKOFF=60
BACKOFF=1

mkdir -p "$(dirname "$LOG_FILE")"

# On SIGTERM/SIGINT: stop the child and exit without restarting.
CHILD_PID=""
on_signal() {
    echo "[supervisor] $(date -Is) received signal, stopping child ${CHILD_PID}" >> "$LOG_FILE"
    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill "$CHILD_PID" 2>/dev/null
    fi
    exit 0
}
trap on_signal TERM INT

echo "[supervisor] $(date -Is) supervisor started (pid $$)" >> "$LOG_FILE"

while true; do
    cd "$PROJECT_DIR"
    echo "[supervisor] $(date -Is) starting main.py" >> "$LOG_FILE"
    "$PYTHON_BIN" "$MAIN_SCRIPT" >> "$LOG_FILE" 2>&1 &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$PID_FILE"

    wait "$CHILD_PID"
    EXIT_CODE=$?
    CHILD_PID=""

    if [ "$EXIT_CODE" -eq 0 ]; then
        echo "[supervisor] $(date -Is) main.py exited cleanly (code 0), supervisor stopping" >> "$LOG_FILE"
        break
    fi

    echo "[supervisor] $(date -Is) main.py exited with code $EXIT_CODE, restarting in ${BACKOFF}s" >> "$LOG_FILE"
    sleep "$BACKOFF"
    BACKOFF=$((BACKOFF * 2))
    if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
        BACKOFF="$MAX_BACKOFF"
    fi
done

exit 0
