#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Load env file if present
if [ -f "$DIR/env" ]; then
    set -a
    . "$DIR/env"
    set +a
fi

cleanup() {
    echo "[run-tunnel] Cleaning up child processes..."
    kill -TERM "$FWD_PID" "$SB_PID" 2>/dev/null || true
    wait "$FWD_PID" 2>/dev/null || true
    wait "$SB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 1. Start Python forwarder
python3 forwarder.py &
FWD_PID=$!
echo "[run-tunnel] Started forwarder (PID $FWD_PID)"

# Wait for forwarder on port 1180
for i in {1..50}; do
    if ss -tln | grep -q ":1180 "; then
        echo "[run-tunnel] Forwarder listening on 1180"
        break
    fi
    sleep 0.1
done

# 2. Start sing-box
SB_BIN="./sing-box"
if [ ! -x "$SB_BIN" ] && command -v sing-box >/dev/null 2>&1; then
    SB_BIN="sing-box"
fi

"$SB_BIN" run -c config.json &
SB_PID=$!
echo "[run-tunnel] Started sing-box (PID $SB_PID)"

# Wait for either process to exit
wait -n "$FWD_PID" "$SB_PID"
