#!/usr/bin/env bash
# build-base-image.sh — build the agent base Docker image.
#
# Tag: agent-base:latest   (referenced by Container Use's base-image config)
# Build context: containerized/ (siblings of the Dockerfile). The .dockerignore
# excludes scripts/ and *.md so the context stays minimal.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker build \
  -f "$HERE/Dockerfile.agent-base" \
  -t agent-base:latest \
  "$HERE"

echo
echo "✓ Built agent-base:latest"
docker run --rm agent-base:latest sh -c \
  'echo "  claude:   $(claude --version 2>/dev/null || echo MISSING)" \
  && echo "  codex:    $(codex --version 2>/dev/null || echo MISSING)" \
  && echo "  opencode: $(opencode --version 2>/dev/null || echo MISSING)" \
  && echo "  uv:       $(uv --version 2>/dev/null || echo MISSING)" \
  && echo "  python:   $(python3.12 --version 2>/dev/null || echo MISSING)" \
  && echo "  gh:       $(gh --version 2>/dev/null | head -n1 || echo MISSING)"'
