#!/usr/bin/env bash
# agent-task.sh — spawn a new Container Use environment + jmux session for
# a task, running the requested AI coding CLI inside the container.
#
# Usage:
#   agent-task [--agent claude|codex|opencode] <task-name> "message"
#
# Examples:
#   agent-task fix-auth "Fix the OAuth token refresh race condition"
#   agent-task --agent codex add-tests "Add unit tests for the auth module"
#   agent-task --agent opencode refactor "Refactor the API client"
#
# Default agent is claude. The `at` alias is installed by install-launcher.sh.

set -euo pipefail

AGENT=claude
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:?--agent requires a value}"; shift 2 ;;
    --help|-h) sed -n '2,15p' "$0"; exit 0 ;;
    --) shift; POSITIONAL+=("$@"); break ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

TASK="${POSITIONAL[0]:-}"
MESSAGE="${POSITIONAL[1]:-}"
if [[ -z "$TASK" || -z "$MESSAGE" ]]; then
  echo "Usage: agent-task [--agent claude|codex|opencode] <task-name> \"message\"" >&2
  exit 2
fi

BRANCH="feature/$TASK"

echo "→ Creating Container Use environment for branch $BRANCH"
ENV_ID="$(cu new --branch "$BRANCH" --output id)"
echo "  environment: $ENV_ID"

CU_TOOLS="mcp__container-use__environment_create,mcp__container-use__environment_run_cmd,mcp__container-use__environment_file_read,mcp__container-use__environment_file_write,mcp__container-use__environment_file_list,mcp__container-use__environment_file_delete,mcp__container-use__environment_checkpoint,mcp__container-use__environment_update,mcp__container-use__environment_open,mcp__container-use__environment_add_service"

case "$AGENT" in
  claude)
    INNER_CMD="claude --allowedTools $CU_TOOLS -m $(printf %q "$MESSAGE")"
    ;;
  codex)
    INNER_CMD="codex --message $(printf %q "$MESSAGE")"
    ;;
  opencode)
    INNER_CMD="opencode run $(printf %q "$MESSAGE")"
    ;;
  *)
    echo "unknown agent: $AGENT (expected claude|codex|opencode)" >&2
    exit 2
    ;;
esac

echo "→ Spawning jmux session: $TASK ($AGENT)"
jmux ctl new-session \
  --name "$TASK" \
  --command "cu shell $ENV_ID -- $INNER_CMD"

cat <<EOF

✓ Agent ($AGENT) running on $ENV_ID — branch $BRANCH
  Watch:  cu watch $ENV_ID
  Diff:   cu diff $ENV_ID
  Merge:  cu checkout $ENV_ID && git merge $BRANCH --no-ff
  Drop:   cu remove $ENV_ID
EOF
