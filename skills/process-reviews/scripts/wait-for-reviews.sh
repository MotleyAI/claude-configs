#!/usr/bin/env bash
# Wait for a PR's reviews + CI to be ready for the /process-reviews triage.
#
#   Stage 0a — status-check rollup gate: poll ``gh pr view --json statusCheckRollup``
#     until no check is still PENDING / EXPECTED / QUEUED / IN_PROGRESS /
#     WAITING / REQUESTED. Cap at 30 minutes; non-zero exit on timeout.
#   Stage 0b — CodeRabbit settle: if a coderabbit ``StatusContext`` exists in
#     the rollup, poll ``repos/<repo>/issues/<PR>/comments`` until any
#     ``coderabbitai[bot]`` summary comment's ``updated_at`` advances past
#     the HEAD commit's ``committedDate``. Cap at 10 minutes (best-effort —
#     after that we proceed without a fresh review).
#
# Stdout reports progress; the script exits 0 on success (both stages clear or
# CodeRabbit not installed), 1 on Stage 0a timeout (Stage 0b is best-effort
# only).
#
# Usage:
#   wait-for-reviews.sh <PR_NUMBER> [--repo OWNER/REPO]
#
# Defaults the repo to the current git working directory via ``gh repo view``.

set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <PR_NUMBER> [--repo OWNER/REPO]

  <PR_NUMBER>           required, the PR number
  --repo OWNER/REPO     optional, defaults to the repo of the current git directory
EOF
    exit 64
}

PR=""
REPO=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        --*)
            echo "unknown flag: $1" >&2
            usage
            ;;
        *)
            if [[ -z "$PR" ]]; then
                PR="$1"
                shift
            else
                echo "extra positional arg: $1" >&2
                usage
            fi
            ;;
    esac
done

if [[ -z "$PR" ]]; then
    usage
fi

if [[ -z "$REPO" ]]; then
    REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null \
        || { echo "could not resolve --repo from gh repo view" >&2; exit 2; })
fi

# ---------------------------------------------------------------------------
# Stage 0a — status-check rollup gate (cap 30 minutes)
# ---------------------------------------------------------------------------

GATE_TIMEOUT=$((30 * 60))
GATE_START=$(date +%s)

while :; do
    pending=$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup --jq '
        [.statusCheckRollup[]
         | select(
             (.__typename == "StatusContext"
                and (.state == "PENDING" or .state == "EXPECTED"))
             or ((.__typename == "CheckRun" or .__typename == "WorkflowRun")
                and (.status == "QUEUED" or .status == "IN_PROGRESS"
                  or .status == "WAITING" or .status == "REQUESTED"
                  or .status == "PENDING"))
           )
         | (.name // .context)] | join(", ")' 2>/dev/null || echo "")

    if [[ -z "$pending" ]]; then
        echo "Stage 0a: gate clear."
        break
    fi

    elapsed=$(( $(date +%s) - GATE_START ))
    echo "Stage 0a: pending — $pending (elapsed $((elapsed / 60))m). Sleeping 1m."

    if (( elapsed >= GATE_TIMEOUT )); then
        echo "Stage 0a: gate timed out after 30 min. Still pending: $pending." >&2
        exit 1
    fi

    sleep 60
done

# ---------------------------------------------------------------------------
# Stage 0b — CodeRabbit summary-comment settle (cap 10 minutes; best-effort)
# ---------------------------------------------------------------------------

has_coderabbit=$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup --jq '
    any(.statusCheckRollup[];
        (.__typename == "StatusContext")
        and ((.context // .name // "") | ascii_downcase | test("coderabbit")))')

if [[ "$has_coderabbit" != "true" ]]; then
    echo "Stage 0b: no CodeRabbit StatusContext on this PR — skipping settle."
    exit 0
fi

head_oid=$(gh pr view "$PR" --repo "$REPO" --json headRefOid --jq '.headRefOid')
head_committed=$(gh api "repos/$REPO/commits/$head_oid" \
    --jq '.commit.committer.date')

CR_SETTLE=$((10 * 60))
CR_START=$(date +%s)

while :; do
    cr_updated=$(gh api "repos/$REPO/issues/$PR/comments" --jq '
        [.[] | select(.user.login | test("coderabbitai"; "i")) | .updated_at]
        | sort | last // ""')

    if [[ -n "$cr_updated" && "$cr_updated" > "$head_committed" ]]; then
        echo "Stage 0b: CodeRabbit summary updated ($cr_updated > $head_committed)."
        exit 0
    fi

    elapsed=$(( $(date +%s) - CR_START ))
    if (( elapsed >= CR_SETTLE )); then
        echo "Stage 0b: hit 10m cap without a fresh CodeRabbit summary — proceeding anyway." >&2
        exit 0
    fi

    echo "Stage 0b: waiting for CR summary > $head_committed (current: ${cr_updated:-none}, elapsed $((elapsed / 60))m). Sleeping 30s."
    sleep 30
done
