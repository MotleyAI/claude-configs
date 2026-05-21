#!/usr/bin/env bash
# Reply to a GitHub PR review thread (CodeRabbit, human reviewer, or any other).
# Body is read from stdin. Calls POST /repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies.
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <DISCUSSION_URL>
       $(basename "$0") --comment-id <ID> --pr <PR> [--repo OWNER/REPO]

  <DISCUSSION_URL>   e.g. https://github.com/owner/repo/pull/70#discussion_r3177795982
                     parses owner, repo, PR, and comment ID from the URL.
  --comment-id ID    integer comment ID (the digits after "discussion_r")
  --pr PR            PR number
  --repo OWNER/REPO  defaults to the current repo via gh repo view

Body is **always read from stdin** — pipe text in or use a heredoc.
On success, prints the new reply's html_url.
EOF
    exit 2
}

URL=""
COMMENT_ID=""
PR=""
REPO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --comment-id)
            [ $# -ge 2 ] || usage
            COMMENT_ID="$2"; shift 2 ;;
        --comment-id=*)
            COMMENT_ID="${1#--comment-id=}"; shift ;;
        --pr)
            [ $# -ge 2 ] || usage
            PR="$2"; shift 2 ;;
        --pr=*)
            PR="${1#--pr=}"; shift ;;
        --repo)
            [ $# -ge 2 ] || usage
            REPO="$2"; shift 2 ;;
        --repo=*)
            REPO="${1#--repo=}"; shift ;;
        -h|--help)
            usage ;;
        --)
            shift; break ;;
        -*)
            echo "error: unknown flag: $1" >&2
            usage ;;
        *)
            if [ -z "$URL" ]; then
                URL="$1"; shift
            else
                echo "error: unexpected positional arg: $1" >&2
                usage
            fi
            ;;
    esac
done

if [ -n "$URL" ]; then
    if [[ "$URL" =~ github\.com/([^/]+)/([^/]+)/pull/([0-9]+)#discussion_r([0-9]+) ]]; then
        : "${REPO:=${BASH_REMATCH[1]}/${BASH_REMATCH[2]}}"
        : "${PR:=${BASH_REMATCH[3]}}"
        : "${COMMENT_ID:=${BASH_REMATCH[4]}}"
    elif [[ "$URL" == *"#pullrequestreview-"* ]]; then
        echo "error: this URL is a review-summary, not a review thread; the replies endpoint only works for #discussion_r... URLs" >&2
        exit 2
    else
        echo "error: URL doesn't match github.com/OWNER/REPO/pull/PR#discussion_rID: $URL" >&2
        exit 2
    fi
fi

[ -n "$COMMENT_ID" ] || { echo "error: --comment-id (or a discussion URL) is required" >&2; usage; }
[ -n "$PR" ]         || { echo "error: --pr (or a discussion URL) is required" >&2; usage; }

if [ -z "$REPO" ]; then
    REPO="$(gh repo view --json owner,name -q '.owner.login + "/" + .name' 2>/dev/null || true)"
    [ -n "$REPO" ] || { echo "error: --repo not given and could not auto-detect (cwd is not a gh-recognised repo)" >&2; exit 2; }
fi

[[ "$COMMENT_ID" =~ ^[0-9]+$ ]] || { echo "error: comment-id must be a positive integer, got: $COMMENT_ID" >&2; exit 2; }
[[ "$PR"         =~ ^[0-9]+$ ]] || { echo "error: pr must be a positive integer, got: $PR" >&2; exit 2; }

case "$REPO" in
    */*/*) echo "error: --repo must be OWNER/REPO, got: $REPO" >&2; exit 2 ;;
    */*) ;;
    *) echo "error: --repo must be OWNER/REPO, got: $REPO" >&2; exit 2 ;;
esac

command -v gh >/dev/null 2>&1 || { echo "error: gh is required" >&2; exit 127; }
command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 127; }

if [ -t 0 ]; then
    echo "error: comment body must be provided on stdin (pipe text in or use a heredoc)" >&2
    exit 2
fi

# Use mktemp so a co-resident process can't pre-create or symlink the
# target before we write — predictable PID-based names are vulnerable to
# clobbering on shared hosts.
BODY_FILE="$(mktemp "${TMPDIR:-/tmp}/pr-reply-body-XXXXXX.md")"
PAYLOAD_FILE="$(mktemp "${TMPDIR:-/tmp}/pr-reply-payload-XXXXXX.json")"
trap 'rm -f "$BODY_FILE" "$PAYLOAD_FILE"' EXIT

cat > "$BODY_FILE"
[ -s "$BODY_FILE" ] || { echo "error: stdin was empty" >&2; exit 2; }

# Build the JSON payload via jq so newlines / special chars are escaped properly.
jq -nR --rawfile body "$BODY_FILE" '{body: $body}' > "$PAYLOAD_FILE"

# POST and surface the new reply's URL.
gh api -X POST \
    "repos/$REPO/pulls/$PR/comments/$COMMENT_ID/replies" \
    --input "$PAYLOAD_FILE" \
  | jq -r '.html_url'
