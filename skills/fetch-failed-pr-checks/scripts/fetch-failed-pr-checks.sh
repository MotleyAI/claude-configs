#!/usr/bin/env bash
# Fetch failed CI checks on a GitHub PR and (for GitHub Actions) the failed-step logs.
# Always emits Markdown to stdout AND writes the full filtered JSON to a tempfile.
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <PR_NUMBER> [--repo OWNER/REPO] [--max-log-lines N]

  <PR_NUMBER>          required, the PR number
  --repo OWNER/REPO    optional, defaults to the current repo via gh repo view
  --max-log-lines N    cap each failed job's log excerpt at N lines (default: 200)

Output: Markdown to stdout, full JSON to \${TMPDIR:-/tmp}/failed-pr-checks-<pr>-<ts>.json.
EOF
    exit 2
}

PR=""
REPO=""
MAX_LOG=200

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)
            [ $# -ge 2 ] || usage
            REPO="$2"; shift 2 ;;
        --repo=*)
            REPO="${1#--repo=}"; shift ;;
        --max-log-lines)
            [ $# -ge 2 ] || usage
            MAX_LOG="$2"; shift 2 ;;
        --max-log-lines=*)
            MAX_LOG="${1#--max-log-lines=}"; shift ;;
        -h|--help)
            usage ;;
        --)
            shift; break ;;
        -*)
            echo "error: unknown flag: $1" >&2
            usage ;;
        *)
            if [ -z "$PR" ]; then
                PR="$1"; shift
            else
                echo "error: unexpected positional arg: $1" >&2
                usage
            fi
            ;;
    esac
done

[ -n "$PR" ] || usage
[[ "$PR"     =~ ^[0-9]+$ ]] || { echo "error: PR_NUMBER must be a positive integer, got: $PR" >&2; exit 2; }
[[ "$MAX_LOG" =~ ^[0-9]+$ ]] || { echo "error: --max-log-lines must be a non-negative integer, got: $MAX_LOG" >&2; exit 2; }

if [ -z "$REPO" ]; then
    REPO="$(gh repo view --json owner,name -q '.owner.login + "/" + .name' 2>/dev/null || true)"
    [ -n "$REPO" ] || { echo "error: --repo not given and could not auto-detect (cwd is not a gh-recognised repo)" >&2; exit 2; }
fi

command -v gh >/dev/null 2>&1 || { echo "error: gh is required" >&2; exit 127; }
command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 127; }

# Pull the full statusCheckRollup. Three node typenames appear here:
# - CheckRun       (GitHub Actions): .conclusion, .name, .detailsUrl, .workflowName
# - StatusContext  (legacy / external CI): .state, .context, .targetUrl
# - WorkflowRun    (rare): treated like CheckRun via fallback fields
all_checks="$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup -q '.statusCheckRollup // []')"

# Normalise + filter to non-passing terminal states.
failed="$(echo "$all_checks" | jq '[
    .[]
    | (.conclusion // .state // "") as $c
    | select(($c | ascii_upcase) | IN("FAILURE","TIMED_OUT","CANCELLED","ACTION_REQUIRED","STARTUP_FAILURE","ERROR"))
    | {
        typename:      .__typename,
        name:          (.name // .context // null),
        workflow_name: (.workflowName // null),
        conclusion:    (.conclusion // .state // null),
        status:        (.status // null),
        details_url:   (.detailsUrl // .targetUrl // null),
        completed_at:  (.completedAt // null)
    }
]')"

# Enrich each failed check with run_id / job_id / failed-step log excerpt
# (only resolvable when the details URL is a GitHub Actions URL we recognise).
enriched_file="$(mktemp)"
trap 'rm -f "$enriched_file"' EXIT
echo '[]' > "$enriched_file"

n=$(echo "$failed" | jq 'length')
i=0
while [ "$i" -lt "$n" ]; do
    check="$(echo "$failed" | jq -c ".[$i]")"
    url="$(echo "$check" | jq -r '.details_url // ""')"
    run_id=""
    job_id=""
    log_file="$(mktemp)"

    if [[ "$url" =~ /actions/runs/([0-9]+) ]]; then
        run_id="${BASH_REMATCH[1]}"
    fi
    if [[ "$url" =~ /job/([0-9]+) ]]; then
        job_id="${BASH_REMATCH[1]}"
    fi

    if [ "$MAX_LOG" -gt 0 ]; then
        if [ -n "$job_id" ]; then
            gh run view --job "$job_id" --repo "$REPO" --log-failed 2>/dev/null \
                | tail -n "$MAX_LOG" > "$log_file" || true
        elif [ -n "$run_id" ]; then
            gh run view "$run_id" --repo "$REPO" --log-failed 2>/dev/null \
                | tail -n "$MAX_LOG" > "$log_file" || true
        fi
    fi

    jq -n \
        --slurpfile cur "$enriched_file" \
        --argjson check "$check" \
        --arg run_id "$run_id" \
        --arg job_id "$job_id" \
        --rawfile log "$log_file" \
        '$cur[0] + [$check + {run_id: $run_id, job_id: $job_id, log_excerpt: $log}]' \
        > "$enriched_file.tmp"
    mv "$enriched_file.tmp" "$enriched_file"
    rm -f "$log_file"

    i=$((i + 1))
done

enriched="$(cat "$enriched_file")"

ts="$(date -u +%Y%m%d-%H%M%S)"
json_out="${TMPDIR:-/tmp}/failed-pr-checks-${PR}-${ts}.json"
jq -n \
    --argjson pr "$PR" \
    --arg repo "$REPO" \
    --argjson failed "$enriched" \
    '{pr: $pr, repo: $repo, failed_checks: $failed}' \
    > "$json_out"

# Markdown
echo "# Failed CI checks on $REPO PR #$PR"
echo
fail_count=$(echo "$enriched" | jq 'length')
if [ "$fail_count" = "0" ]; then
    echo "_No failed checks._"
    echo
else
    echo "$enriched" | jq -r --argjson max "$MAX_LOG" '
        to_entries[]
        | (.key + 1) as $i
        | .value as $c
        | (
            "## Check \($i) — \(($c.workflow_name // "") + (if ($c.workflow_name // "") != "" and ($c.name // "") != "" then " / " else "" end) + ($c.name // "?"))",
            "Conclusion: \($c.conclusion)   Status: \($c.status // "n/a")   Type: \($c.typename // "?")",
            "Details: \($c.details_url // "n/a")",
            (if ($c.run_id // "") != "" then "Run: \($c.run_id)\(if ($c.job_id // "") != "" then "  Job: \($c.job_id)" else "" end)" else empty end),
            "",
            (if ($c.log_excerpt // "") != "" then
                "<details><summary>Failed-step log (last \($max) lines)</summary>",
                "",
                "```",
                $c.log_excerpt,
                "```",
                "",
                "</details>"
             else
                "_No log excerpt available — likely an external CI; follow Details URL._"
             end),
            "",
            "---",
            ""
          )
    '
fi

echo "JSON: $json_out"
