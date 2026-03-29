#!/usr/bin/env bash
# Backward compatibility: same as local setup (macOS / dev laptop).
# For EC2 / Ubuntu, use: ./setup_and_run_aws.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/setup_and_run_local.sh"
