#!/usr/bin/env bash
# One click for Mac and Linux: starts the ATLAS backend and the Signal app in your browser.
#   ./start-signal.sh          practice mode (synthetic data, every number labelled DEMO)
#   ./start-signal.sh --real   real data (Coinbase, Yahoo, FRED and the other free public sources)
# On a Mac you can also double-click start-signal.command. Press Ctrl+C to stop both.
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
MODE="demo"; [ "$1" = "--real" ] && MODE="real"

command -v python3 >/dev/null || { echo "Python 3.11+ is needed (python3 not found)."; exit 1; }
command -v node >/dev/null || { echo "Node 20+ is needed (node not found)."; exit 1; }

if [ ! -d "$ROOT/.signal-venv" ]; then
  echo "First run: setting up the backend (a few minutes)..."
  python3 -m venv "$ROOT/.signal-venv"
  "$ROOT/.signal-venv/bin/pip" install -q -e "$ROOT/atlas/backend"
fi
if [ ! -d "$ROOT/atlas/mobile/node_modules" ]; then
  echo "First run: installing the app (a few minutes)..."
  (cd "$ROOT/atlas/mobile" && npm install --no-audit --no-fund)
fi

export ATLAS_CORS_ORIGINS="http://localhost:8081"
[ "$MODE" = "demo" ] && export ATLAS_DEMO=1
"$ROOT/.signal-venv/bin/python" -m atlas_api &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT INT TERM

for i in $(seq 1 60); do
  curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 1
done
echo
echo "Backend is up ($MODE mode). Opening Signal at http://localhost:8081 ."
echo "When Signal asks for a server, enter:  http://127.0.0.1:8000"
cd "$ROOT/atlas/mobile" && npx expo start --web --port 8081
