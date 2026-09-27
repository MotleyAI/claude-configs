#!/usr/bin/env bash
# Detect inline (non-top-level) imports in the files a PR modifies, so
# /process-reviews can enforce them as a HARD GATE: every such import must be
# hoisted to module top (or, only as a last resort, marked for the linter to
# ignore) before the triage is considered done.
#
# SCOPE: only the .py files this PR touches (merge-base diff against the PR
# base, plus any uncommitted working-tree edits). Files the PR does not touch
# are never linted, so the gate never fires on pre-existing inline imports
# elsewhere in the repo — but for a touched file the WHOLE file is in scope,
# not just the added lines.
#
# LINTER: Python is linted with ruff's PLC0415 (import-outside-top-level); if
# ruff is unavailable, pylint's C0415 is used. Both honour an inline
# `# noqa: PLC0415` / `# pylint: disable=import-outside-top-level`, which is the
# escape hatch for a genuine circular-import case. Config is bypassed
# (`ruff --isolated`) so a repo that disables the rule can't hide the gate.
# Non-Python files are reported as "unlinted" — in ESM `import` is already
# forced top-level, and inline `require()`/dynamic `import()` are usually
# deliberate, so there is no reliable cross-language gate to run.
#
# EXIT CODES:
#   0  gate clear — no inline imports in the PR's modified Python files
#   1  gate RED   — at least one inline import found (locations on stdout)
#   2  usage / git error
#   3  no linter available (ruff and pylint both missing) — gate cannot run
#
# Usage:
#   lint-modified-imports.sh <PR_NUMBER> [--repo OWNER/REPO] [--base BRANCH]
#
# In sandbox.excludedCommands — call BARE; passing dangerouslyDisableSandbox causes the permission prompt.

set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <PR_NUMBER> [--repo OWNER/REPO] [--base BRANCH]

  <PR_NUMBER>          required, the PR number (used to resolve the base branch)
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

if [[ -z "$REPO" ]]; then
    REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null \
        || { echo "could not resolve --repo from gh repo view" >&2; exit 2; })
fi

if [[ -z "$BASE" ]]; then
    BASE=$(gh pr view "$PR" --repo "$REPO" --json baseRefName --jq '.baseRefName' 2>/dev/null \
        || { echo "could not resolve base branch for PR $PR" >&2; exit 2; })
fi

# Best-effort fetch so origin/<base> is current; a stale ref still diffs.
git fetch origin "$BASE" --quiet 2>/dev/null || true

if ! git rev-parse --verify --quiet "origin/$BASE" >/dev/null; then
    echo "error: origin/$BASE not found locally — fetch failed and no cached ref." >&2
    exit 2
fi

# PR-modified .py files: merge-base committed diff ∪ working-tree edits.
# --diff-filter=ACMR drops deletions (nothing to lint) and yields the new path
# for renames. Filter to files that still exist on disk.
mapfile -t FILES < <(
    {
        git diff --name-only --diff-filter=ACMR "origin/$BASE...HEAD" -- '*.py'
        git diff --name-only --diff-filter=ACMR HEAD -- '*.py'
    } | sort -u | while IFS= read -r f; do
        [[ -n "$f" && -f "$f" ]] && printf '%s\n' "$f"
    done
)

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "gate: no modified .py files in PR $PR (base $BASE) — nothing to lint."
    exit 0
fi

echo "gate: linting ${#FILES[@]} modified .py file(s) for inline imports (base $BASE):"
printf '  %s\n' "${FILES[@]}"
echo

# --- run the linter ---------------------------------------------------------
findings=""

if command -v ruff >/dev/null 2>&1; then
    echo "gate: using ruff (PLC0415, config-isolated)."
    # ruff exits 1 when violations are found, 0 when clean — don't let set -e abort.
    findings=$(ruff check --isolated --preview --select PLC0415 \
        --output-format concise "${FILES[@]}" 2>/dev/null || true)
    # Keep only PLC0415 lines (concise format: path:row:col: PLC0415 message).
    findings=$(printf '%s\n' "$findings" | grep -E ':[0-9]+:[0-9]+: PLC0415 ' || true)
elif command -v pylint >/dev/null 2>&1; then
    echo "gate: ruff not found — using pylint (C0415)."
    # parseable format: path:line: [C0415(import-outside-top-level), scope] message
    findings=$(pylint --disable=all --enable=C0415 \
        --output-format=parseable "${FILES[@]}" 2>/dev/null || true)
    findings=$(printf '%s\n' "$findings" | grep -E '\[C0415\(' || true)
else
    echo "error: neither ruff nor pylint is installed — cannot run the inline-import gate." >&2
    echo "       install one (e.g. 'pip install ruff') and re-run." >&2
    exit 3
fi

# Strip blank lines that grep -E may leave behind.
findings=$(printf '%s\n' "$findings" | sed '/^[[:space:]]*$/d' || true)

if [[ -z "$findings" ]]; then
    echo "gate: CLEAR — no inline imports in the PR's modified files."
    exit 0
fi

count=$(printf '%s\n' "$findings" | wc -l | tr -d ' ')
echo "gate: RED — $count inline import(s) found in PR-modified files:"
echo
printf '%s\n' "$findings"
echo
echo "Fix each: move the import to module top. Only if that creates a circular"
echo "import (or is otherwise impossible) mark it '# noqa: PLC0415' — and per the"
echo "user's CLAUDE.md rule, confirm with the user BEFORE using that escape hatch."
exit 1
