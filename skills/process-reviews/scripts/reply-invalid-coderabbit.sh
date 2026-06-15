#!/usr/bin/env bash
# Reply to a CodeRabbit review thread classified as INVALID during
# /process-reviews triage. Auto-prepends "@coderabbitai " so the bot
# threads the response, and delegates to the underlying
# reply-to-pr-thread.sh for URL parsing + the POST /replies call.
#
# Body is read from stdin. Print the new reply's html_url on success.
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $(basename "$0") <DISCUSSION_URL>
       $(basename "$0") --comment-id <ID> --pr <PR> [--repo OWNER/REPO]

  <DISCUSSION_URL>   e.g. https://github.com/owner/repo/pull/164#discussion_r3362457742
                     parses owner, repo, PR, and comment ID from the URL.
  --comment-id ID    integer comment ID (the digits after "discussion_r")
  --pr PR            PR number
  --repo OWNER/REPO  defaults to the current repo via gh repo view

Body is **always read from stdin** — pipe the rationale in or use a
heredoc. The script prepends "@coderabbitai " automatically if the
first non-whitespace character is not already an @-mention of the bot.

On success, prints the new reply's html_url to stdout.

Typical use inside /process-reviews:

  cat <<EOF | bash ~/.claude/skills/process-reviews/scripts/reply-invalid-coderabbit.sh \\
    "https://github.com/MotleyAI/slayer/pull/164#discussion_r3362457742"
  this removal is intentional — DEV-1532 collapses the typed-bucket
  EntityHit/MemoryHit pair into a single SearchHit. The new contract is
  pinned by tests/test_search_unified.py:124-128.
  EOF
EOF
    exit 2
}

# Forward every flag/positional unchanged — reply-to-pr-thread.sh owns
# argument parsing, validation, and the gh call.
if [ $# -eq 0 ]; then
    usage
fi
case "${1:-}" in
    -h|--help) usage ;;
esac

# Read stdin body up front so we can re-emit it through reply-to-pr-thread.sh
# with the @-mention prepended.
BODY="$(cat)"
if [ -z "$BODY" ]; then
    echo "error: empty body — pipe the rationale in via stdin." >&2
    exit 2
fi

# Trim leading whitespace for the prefix check (without losing it in BODY).
LEADING_STRIP="$(printf '%s' "$BODY" | sed -n '1,1p' | sed -E 's/^[[:space:]]+//')"
case "$LEADING_STRIP" in
    @coderabbitai*|@CodeRabbitAI*|@coderabbit*)
        # Caller already tagged the bot — pass through.
        ;;
    *)
        BODY="@coderabbitai ${BODY}"
        ;;
esac

REPLY_SCRIPT="${HOME}/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh"
if [ ! -x "$REPLY_SCRIPT" ] && [ ! -r "$REPLY_SCRIPT" ]; then
    echo "error: ${REPLY_SCRIPT} not found — install the reply-to-pr-thread skill." >&2
    exit 1
fi

printf '%s' "$BODY" | bash "$REPLY_SCRIPT" "$@"
