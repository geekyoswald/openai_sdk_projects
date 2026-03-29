#!/usr/bin/env bash
# EC2 / Ubuntu: venv + deps, then webhook in background (terminal returns).
# Foreground: ./setup_and_run_aws.sh foreground   |  Stop: ./stop_webhook_aws.sh
# CLI once: ./setup_and_run_aws.sh cli
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
  echo "Installing python3-venv and python3-pip (apt, requires sudo once)..." >&2
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
        echo "Installing python${V}-venv (apt)..." >&2
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
PIDFILE="$(pwd)/.webhook.pid"
LOGDIR="$(pwd)/logs"
LOGFILE="$LOGDIR/webhook.log"
UVICORN=(python -m uvicorn webhook_app:app --host "$WH" --port "$WP" --timeout-graceful-shutdown 5)

if [[ "${1:-}" == "foreground" || "${1:-}" == "fg" ]]; then
  exec "${UVICORN[@]}"
fi

mkdir -p "$LOGDIR"
if [[ -f "$PIDFILE" ]]; then
  oldpid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ "$oldpid" =~ ^[0-9]+$ ]] && kill -0 "$oldpid" 2>/dev/null; then
    echo "Already running (pid $oldpid). Run: ./stop_webhook_aws.sh" >&2
    exit 1
  fi
  rm -f "$PIDFILE"
fi

nohup "${UVICORN[@]}" >>"$LOGFILE" 2>&1 &
echo $! >"$PIDFILE"
echo "Started pid $(cat "$PIDFILE") — log: $LOGFILE — stop: ./stop_webhook_aws.sh" >&2
