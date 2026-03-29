#!/usr/bin/env bash
# Commit & push changes for this project.
# Works when: (a) complai_sdr_email/ is under a monorepo — only that folder is staged;
#             (b) complai_sdr_email/ is the git root — whole repo is staged.
# Usage: ./push_to_git.sh ["commit message"]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Error: not inside a git repository." >&2
  exit 1
}

# Inside monorepo: e.g. complai_sdr_email/. At project repo root: empty.
SCOPE="$(git rev-parse --show-prefix)"
SCOPE="${SCOPE%/}"

cd "$GIT_ROOT"
if [[ -n "$SCOPE" ]]; then
  git add -A -- "$SCOPE"
  LABEL="$SCOPE"
else
  git add -A
  LABEL="complai_sdr_email (repo root)"
fi

if git diff --cached --quiet; then
  echo "Nothing new to commit ($LABEL)"
  exit 0
fi

MSG="${1:-Update}"
git commit -m "$MSG"
git push -u origin master

echo "Pushed ($LABEL): $MSG"
