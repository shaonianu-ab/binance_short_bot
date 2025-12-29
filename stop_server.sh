#!/usr/bin/env bash
set -e

PROJECT_DIR="/opt/binance_short_bot"
PID_FILE="$PROJECT_DIR/server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[stop] server not running (pid file not found)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! kill -0 "$PID" 2>/dev/null; then
    echo "[stop] process $PID not exists, cleaning pidfile"
    rm -f "$PID_FILE"
    exit 0
fi

echo "[stop] stopping server pid=$PID"
kill "$PID"

# 等待优雅退出
for i in {1..10}; do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "[stop] stopped"
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 0.5
done

echo "[stop] force killing $PID"
kill -9 "$PID" || true
rm -f "$PID_FILE"
echo "[stop] killed"
