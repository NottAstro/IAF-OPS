#!/usr/bin/env bash
# Start the whole stack: wind sidecar (8787), FastAPI (API_PORT, default 8010), Vite (5173). Ctrl-C stops all three.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
API_PORT=$(grep -E '^API_PORT=' .env 2>/dev/null | cut -d= -f2 | cut -d' ' -f1)
API_PORT=${API_PORT:-8010}
mkdir -p data/logs

# Node 24 straight from nvm's install dir. (Sourcing nvm.sh inside a script breaks when another Node is already active.)
NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/v24*/bin 2>/dev/null | tail -1)
if [ -z "$NODE_BIN" ]; then
  echo "Node 24 not found. Install it with:  nvm install 24"
  exit 1
fi
export PATH="$NODE_BIN:$PATH"

busy=()
for p in 8787 "$API_PORT" 5173; do
  lsof -nP -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1 && busy+=("$p")
done
if [ ${#busy[@]} -gt 0 ]; then
  echo "Port(s) already in use: ${busy[*]}"
  echo "iaf-airops is probably already running: open http://localhost:5173"
  echo "To restart it, run:  make stop  then  make dev"
  exit 1
fi

/opt/homebrew/opt/postgresql@17/bin/pg_isready -q || brew services start postgresql@17

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null; }
trap cleanup INT TERM EXIT
(cd wind && node server.mjs > "$ROOT/data/logs/wind.log" 2>&1) & pids+=($!)
(cd backend && ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --workers 1 > "$ROOT/data/logs/api.log" 2>&1) & pids+=($!)
(cd frontend && npx vite > "$ROOT/data/logs/web.log" 2>&1) & pids+=($!)

sleep 6
ok=1
for svc in "wind:8787:wind.log" "api:$API_PORT:api.log" "web:5173:web.log"; do
  IFS=: read -r name port log <<< "$svc"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    printf "  ✓ %-4s http://localhost:%s\n" "$name" "$port"
  else
    ok=0
    printf "  ✗ %-4s did not start. Last lines of data/logs/%s:\n" "$name" "$log"
    tail -5 "$ROOT/data/logs/$log" | sed 's/^/      /'
  fi
done
[ "$ok" = 1 ] || exit 1
echo
echo "Open http://localhost:5173   (logs in data/logs/, Ctrl-C to stop)"
wait
