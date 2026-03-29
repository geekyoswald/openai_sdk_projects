#!/usr/bin/env bash
# Stop background uvicorn from setup_and_run_aws.sh
set -euo pipefail

cd "$(dirname "$0")"
PIDFILE=".webhook.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "No $PIDFILE — nothing to stop." >&2
  exit 1
fi

pid="$(cat "$PIDFILE")"
if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
  rm -f "$PIDFILE"
  exit 1
fi

if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$PIDFILE"
  echo "Stale pid; removed $PIDFILE" >&2
  exit 0
fi

kill -TERM "$pid" 2>/dev/null || true
for _ in $(seq 1 20); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PIDFILE"
    echo "Stopped." >&2
    exit 0
  fi
  sleep 0.5
done

kill -KILL "$pid" 2>/dev/null || true
rm -f "$PIDFILE"
echo "Force-stopped." >&2
