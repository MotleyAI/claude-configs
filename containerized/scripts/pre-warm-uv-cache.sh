#!/usr/bin/env bash
# pre-warm-uv-cache.sh — run `uv sync` on the host in each given repo so the
# wheel cache (~/.cache/uv) is populated. The cache is bind-mounted into every
# agent container; warm cache = ~2s instead of ~60s for in-container `uv sync`.

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: pre-warm-uv-cache.sh <repo-dir> [<repo-dir> ...]" >&2
  exit 2
fi

for repo in "$@"; do
  if [[ ! -f "$repo/pyproject.toml" ]]; then
    echo "skip: $repo (no pyproject.toml)" >&2
    continue
  fi
  echo "→ uv sync in $repo"
  ( cd "$repo" && uv sync )
done
