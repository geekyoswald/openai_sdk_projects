#!/usr/bin/env bash
# chmod +x setup_and_run.sh && ./setup_and_run.sh
# On Ubuntu/Debian, installs python3-venv via apt (sudo) when needed — no separate server steps.
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
    # e.g. Ubuntu may need python3.12-venv explicitly
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
python run.py
