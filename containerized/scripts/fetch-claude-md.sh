#!/usr/bin/env bash
# fetch-claude-md.sh — populate claude-config/container-use-rules.md from
# the upstream Container Use agent rules. Re-run whenever upstream changes.
# CLAUDE.md is hand-edited and pulls these rules in via `@container-use-rules.md`,
# so refreshing upstream never clobbers your own instructions.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/claude-config/container-use-rules.md"
URL="https://raw.githubusercontent.com/dagger/container-use/main/rules/agent.md"

echo "→ Fetching $URL"
curl -fsSL "$URL" -o "$DEST"
echo "✓ Wrote $DEST ($(wc -c < "$DEST") bytes)"
