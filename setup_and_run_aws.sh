#!/usr/bin/env bash
# Ubuntu / Debian / EC2: install python3-venv via apt if needed, venv + pip, then —
#   Default: Telegram webhook server (uvicorn, bind 0.0.0.0 for nginx / ALB / Telegram).
#   CLI one-shot: ./setup_and_run_aws.sh cli  →  python run.py
# Optional env: WEBHOOK_HOST (default 0.0.0.0), WEBHOOK_PORT (default 8000).
# chmod +x setup_and_run_aws.sh && ./setup_and_run_aws.sh
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and add your keys first." >&2
  exit 1
fi

PY="${PYTHON:-python3}"

ensure_ubuntu_debian_venv_packages() {
  [[ -f /etc/os-release ]] || return 0
  # shellcheck source=/dev/null
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]] || return 0

  if dpkg-query -W -f='${Status}' python3-venv 2>/dev/null | grep -q "install ok installed"; then
    return 0
  fi

  echo "Installing python3-venv and python3-pip (apt, requires sudo once)..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip
}

ensure_ubuntu_debian_venv_packages

if [[ ! -f .venv/bin/activate ]]; then
  if ! "$PY" -m venv .venv; then
    rm -rf .venv
    if [[ -f /etc/os-release ]]; then
      # shellcheck source=/dev/null
      . /etc/os-release
      if [[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]]; then
        V="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        echo "Installing python${V}-venv (apt)..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "python${V}-venv" || true
      fi
    fi
    "$PY" -m venv .venv
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [[ "${1:-}" == "cli" ]]; then
  exec python run.py
fi

WH="${WEBHOOK_HOST:-0.0.0.0}"
WP="${WEBHOOK_PORT:-8000}"
echo "Starting Telegram webhook: http://${WH}:${WP}/telegramwebhook (setWebhook must use your public HTTPS URL → this path)" >&2
exec python -m uvicorn webhook_app:app --host "$WH" --port "$WP"
