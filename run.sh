#!/usr/bin/env bash
# Start AI Stock Radar. First run installs dependencies into .venv.
#   ./run.sh               start server and open the app window
#   ./run.sh --no-browser  server only
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import fastapi, yfinance, anthropic" 2>/dev/null; then
  ./scripts/setup.sh
fi

exec .venv/bin/python -m backend "$@"
