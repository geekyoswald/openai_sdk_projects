#!/usr/bin/env bash
# chmod +x setup_and_run.sh && ./setup_and_run.sh
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and add your keys first." >&2
  exit 1
fi

PY="${PYTHON:-python3}"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
