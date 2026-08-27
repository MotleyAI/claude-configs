#!/usr/bin/env bash
# Stable entrypoint: runs refactor.py under the skill's own venv so rope never
# touches system Python or any project's venv.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/../.venv/bin/python" "$HERE/refactor.py" "$@"
