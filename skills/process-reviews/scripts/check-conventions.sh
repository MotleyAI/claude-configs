#!/usr/bin/env bash
# Deterministic convention gate driver for /process-reviews: resolves the PR's
# base branch, then runs check-conventions.py (imports-at-top) on the PR's
# modified .py files (whole file, committed ∪ working tree).
#
# EXIT CODES:  0 gate clear · 1 gate RED (violations on stdout) · 2 usage/git error
#
# Usage:
#   check-conventions.sh <PR_NUMBER> [--repo OWNER/REPO] [--base BRANCH]
#
# Needs network (gh + git fetch) — invoke with dangerouslyDisableSandbox: true.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <PR_NUMBER> [--repo OWNER/REPO] [--base BRANCH]

  <PR_NUMBER>          required unless --base is given (resolves the base branch)
  --repo OWNER/REPO    optional, defaults to the repo of the current git directory
  --base BRANCH        optional, skip the PR lookup and diff against this base
EOF
    exit 2
}

PR=""
REPO=""
BASE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --base) BASE="$2"; shift 2 ;;
        -h|--help) usage ;;
        --*) echo "unknown flag: $1" >&2; usage ;;
        *)
            if [[ -z "$PR" ]]; then PR="$1"; shift
            else echo "extra positional arg: $1" >&2; usage; fi
            ;;
    esac
done

if [[ -z "$PR" && -z "$BASE" ]]; then
    usage
fi

if [[ -z "$BASE" ]]; then
    if [[ -z "$REPO" ]]; then
        REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null \
            || { echo "could not resolve --repo from gh repo view" >&2; exit 2; })
    fi
    BASE=$(gh pr view "$PR" --repo "$REPO" --json baseRefName --jq '.baseRefName' 2>/dev/null \
        || { echo "could not resolve base branch for PR $PR" >&2; exit 2; })
fi

# Best-effort fetch so origin/<base> is current; a stale ref still diffs.
git fetch origin "$BASE" --quiet 2>/dev/null || true

if ! git rev-parse --verify --quiet "origin/$BASE" >/dev/null; then
    echo "error: origin/$BASE not found locally — fetch failed and no cached ref." >&2
    exit 2
fi

status=0
python3 "$SCRIPT_DIR/check-conventions.py" --base "origin/$BASE" || status=$?
if [[ $status -eq 0 ]]; then
    echo "gate: CLEAR — conventions hold on the PR's modified .py files."
    exit 0
fi
if [[ $status -eq 1 ]]; then
    echo
    echo "gate: RED — hoist each flagged import to module top. Only a genuine"
    echo "circular import may be waived with '# ALLOW(import-not-top): <reason>'"
    echo "on the line — and per the user's CLAUDE.md, confirm with the user"
    echo "BEFORE landing a waiver."
fi
exit "$status"
