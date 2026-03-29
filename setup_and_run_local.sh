#!/usr/bin/env bash
# Local / macOS / laptop: venv + pip + run.py (no apt / no sudo).
# chmod +x setup_and_run_local.sh && ./setup_and_run_local.sh
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and add your keys first." >&2
  exit 1
fi

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python not found ($PY). Install Python 3 and retry (e.g. brew install python on macOS)." >&2
  exit 1
fi

if [[ ! -f .venv/bin/activate ]]; then
  if ! "$PY" -m venv .venv; then
    echo "Failed to create .venv. On macOS you may need: xcode-select --install" >&2
    echo "Or use a specific Python: PYTHON=/usr/local/bin/python3 ./setup_and_run_local.sh" >&2
    exit 1
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
