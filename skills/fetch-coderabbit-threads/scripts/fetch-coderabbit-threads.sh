#!/usr/bin/env bash
# Fetch unresolved CodeRabbit review threads (and review-summary nitpicks) for a GitHub PR.
# Always emits Markdown to stdout AND writes the full filtered JSON to a tempfile.
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <PR_NUMBER> [--repo OWNER/REPO] [--all-authors]

  <PR_NUMBER>           required, the PR number
  --repo OWNER/REPO     optional, defaults to the repo of the current git directory
  --all-authors         include unresolved threads from any author, not just CodeRabbit

Output: Markdown to stdout, full JSON to \${TMPDIR:-/tmp}/coderabbit-threads-<pr>-<ts>.json.
EOF
    exit 2
}

PR=""
REPO=""
ALL_AUTHORS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)
            [ $# -ge 2 ] || usage
            REPO="$2"; shift 2 ;;
        --repo=*)
            REPO="${1#--repo=}"; shift ;;
        --all-authors)
            ALL_AUTHORS=1; shift ;;
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
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "error: PR_NUMBER must be a positive integer, got: $PR" >&2; exit 2; }

if [ -z "$REPO" ]; then
    REPO="$(gh repo view --json owner,name -q '.owner.login + "/" + .name' 2>/dev/null || true)"
    if [ -z "$REPO" ]; then
        echo "error: --repo not given and could not auto-detect (cwd is not a gh-recognised repo)" >&2
        exit 2
    fi
fi
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"
if [ -z "$OWNER" ] || [ -z "$NAME" ] || [ "$OWNER" = "$REPO" ]; then
    echo "error: --repo must be OWNER/REPO, got: $REPO" >&2
    exit 2
fi

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 127; }
command -v gh >/dev/null 2>&1 || { echo "error: gh is required" >&2; exit 127; }

# jq-safe regex: matches "coderabbitai" or "coderabbitai[bot]". Square brackets
# are character-class metacharacters in regex; using `[[]bot[]]` avoids needing
# a backslash escape, which jq's JSON-string parser would reject as `\[`.
CODERABBIT_LOGIN_RE='^coderabbitai([[]bot[]])?$'

# ---- Fetch review threads via GraphQL (manual cursor loop; --paginate doesn't drive nested cursors) ----
threads_all_json="$(mktemp)"
trap 'rm -f "$threads_all_json"' EXIT
echo '[]' > "$threads_all_json"

cursor=""
while :; do
    if [ -z "$cursor" ]; then
        cursor_arg='null'
    else
        cursor_arg="\"$cursor\""
    fi
    page="$(gh api graphql \
        -F owner="$OWNER" \
        -F repo="$NAME" \
        -F pr="$PR" \
        -f query="query(\$owner: String!, \$repo: String!, \$pr: Int!) {
          repository(owner: \$owner, name: \$repo) {
            pullRequest(number: \$pr) {
              reviewThreads(first: 100, after: $cursor_arg) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  line
                  originalLine
                  comments(first: 50) {
                    nodes {
                      author { login }
                      body
                      url
                      createdAt
                    }
                  }
                }
              }
            }
          }
        }")"
    # Write the page's nodes to a sibling temp file rather than passing them
    # as --argjson — large pages (many comments per thread) exceed ARG_MAX.
    nodes_tmp="$threads_all_json.page.json"
    echo "$page" | jq -c '.data.repository.pullRequest.reviewThreads.nodes' > "$nodes_tmp"
    jq -s '.[0] + .[1]' "$threads_all_json" "$nodes_tmp" > "$threads_all_json.tmp"
    mv "$threads_all_json.tmp" "$threads_all_json"
    rm -f "$nodes_tmp"

    has_next="$(echo "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')"
    if [ "$has_next" = "true" ]; then
        cursor="$(echo "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')"
    else
        break
    fi
done

# Filter: unresolved + (CodeRabbit author unless --all-authors)
filter_jq='[.[] | select(.isResolved == false)]'
if [ "$ALL_AUTHORS" -eq 0 ]; then
    filter_jq='[.[] | select(.isResolved == false) | select(any(.comments.nodes[]?.author.login // ""; test("'"$CODERABBIT_LOGIN_RE"'")))]'
fi
threads_filtered="$(jq "$filter_jq" "$threads_all_json")"

# ---- Fetch nitpicks from review bodies (REST) ----
reviews_raw="$(gh api --paginate "repos/$OWNER/$NAME/pulls/$PR/reviews" 2>/dev/null || echo '[]')"
# --paginate may concatenate JSON arrays; normalise to a single array.
reviews_json="$(echo "$reviews_raw" | jq -s 'if length == 0 then [] elif (.[0] | type) == "array" then add else . end')"

# Keep CodeRabbit reviews with non-empty bodies that mention "Nitpick".
nitpick_reviews="$(echo "$reviews_json" | jq --arg re "$CODERABBIT_LOGIN_RE" '
    [ .[]
      | select(.user.login // "" | test($re))
      | select(.body != null and .body != "")
      | select(.body | test("Nitpick"; "i"))
      | { url: .html_url, submitted_at: .submitted_at, body: .body }
    ]
')"

# Pull the Nitpick block out of each body. CodeRabbit wraps nitpicks in either:
#   <details>...<summary>...Nitpick comments (N)...</summary>BODY</details>
# or a plain `## Nitpick comments (N)` section. Capture from the marker to the
# next `</details>` / end-of-string.
nitpicks="$(echo "$nitpick_reviews" | jq '
    def extract_nitpicks(body):
        ( body
          | capture("(?<block>(<details[^>]*>[^<]*<summary>[^<]*[Nn]itpick[^<]*</summary>(?<inner1>[\\s\\S]*?)</details>)|(##\\s*[Nn]itpick[^\\n]*\\n(?<inner2>[\\s\\S]*?)(?=\\n##\\s|\\Z)))"; "g")
        ) // null;
    [ .[]
      | . as $r
      | (extract_nitpicks($r.body)) as $m
      | if $m == null then empty
        else { url: $r.url, submitted_at: $r.submitted_at, block: ($m.inner1 // $m.inner2 // $m.block) }
        end
    ]
')"

# Fallback: if the regex extraction missed everything, keep the full review body
# so the user still sees something rather than silent loss.
if [ "$(echo "$nitpicks" | jq 'length')" = "0" ] && [ "$(echo "$nitpick_reviews" | jq 'length')" != "0" ]; then
    nitpicks="$(echo "$nitpick_reviews" | jq '[ .[] | { url: .url, submitted_at: .submitted_at, block: .body } ]')"
fi

# ---- Write JSON file ----
ts="$(date -u +%Y%m%d-%H%M%S)"
json_out="${TMPDIR:-/tmp}/coderabbit-threads-${PR}-${ts}.json"
jq -n \
    --argjson pr "$PR" \
    --arg repo "$REPO" \
    --argjson threads "$threads_filtered" \
    --argjson nitpicks "$nitpicks" \
    '{pr: $pr, repo: $repo, threads: $threads, nitpicks: $nitpicks}' \
    > "$json_out"

# ---- Render Markdown ----
echo "# Unresolved CodeRabbit threads on $REPO PR #$PR"
echo

thread_count="$(echo "$threads_filtered" | jq 'length')"
if [ "$thread_count" = "0" ]; then
    echo "_No unresolved threads._"
    echo
else
    echo "$threads_filtered" | jq -r '
        to_entries[]
        | (.key + 1) as $i
        | .value as $t
        | (
            "## Thread \($i) — \($t.path // "?"):\($t.line // $t.originalLine // "file-level")",
            "URL: " + ((($t.comments.nodes // [])[0].url) // "n/a"),
            "Resolved: \($t.isResolved)   Outdated: \($t.isOutdated)",
            "",
            ( ($t.comments.nodes // [])
              | to_entries[]
              | "### Comment \(.key + 1) — \(.value.author.login // "?")  \(.value.createdAt // "")",
                "<\(.value.url)>",
                "",
                ((.value.body // "") | split("\n") | map("> " + .) | join("\n")),
                ""
            ),
            "---",
            ""
          )
    '
fi

echo "## CodeRabbit review-summary nitpicks"
echo
nitpick_count="$(echo "$nitpicks" | jq 'length')"
if [ "$nitpick_count" = "0" ]; then
    echo "_No nitpicks._"
    echo
else
    echo "$nitpicks" | jq -r '
        to_entries[]
        | (.key + 1) as $i
        | .value as $n
        | (
            "### Nitpick \($i)",
            "Review: \($n.url)   Submitted: \($n.submitted_at // "")",
            "",
            (($n.block // "") | split("\n") | map("> " + .) | join("\n")),
            "",
            "---",
            ""
          )
    '
fi

echo "JSON: $json_out"
