#!/usr/bin/env bash
set -e

PROJECT_DIR="/opt/binance_short_bot"
SERVER_PY="server.py"
PID_FILE="$PROJECT_DIR/server.pid"
PYTHON="python3"

cd "$PROJECT_DIR"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[start] server already running pid=$PID"
        exit 0
    else
        echo "[start] stale pidfile, removing"
        rm -f "$PID_FILE"
    fi
fi

echo "[start] starting server..."

nohup "$PYTHON" "$SERVER_PY" \
    > server.out 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"

sleep 0.5
if kill -0 "$PID" 2>/dev/null; then
    echo "[start] server started pid=$PID"
else
    echo "[start] failed to start server"
    rm -f "$PID_FILE"
    exit 1
fi
