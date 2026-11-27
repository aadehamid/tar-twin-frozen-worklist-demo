#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1

python3 "$REPO_ROOT/scripts/tree_guard.py" --repo "$REPO_ROOT" -- bash -euo pipefail -c '
  repo="$1"
  echo "==> Checking markdown docs (dashes and links)"
  python3 "$repo/scripts/check_docs.py" --repo "$repo"

  echo "==> Checking repository fact consistency"
  python3 "$repo/scripts/repo_facts.py" --repo "$repo" check

  echo "==> Running repository pytest suite"
  uv run --no-project --with pytest python -m pytest -p no:cacheprovider -q "$repo/tests"
' _ "$REPO_ROOT"

echo "All checks passed."
