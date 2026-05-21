#!/usr/bin/env bash
# install.sh — top-level orchestrator for the containerized parallel-agent
# workflow. Drives the per-step scripts in scripts/ and gates on prerequisites
# that need a human action between steps (docker group membership, OAuth login).
#
# Idempotent: safe to re-run after each gate. Each step is skipped if it has
# already been done (the underlying scripts handle their own idempotency).
#
# All flags are passed through to install-prereqs.sh, e.g.:
#   bash containerized/install.sh --with-gitkraken
#   bash containerized/install.sh --skip-node

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/scripts"

say()   { printf "\n══ %s\n" "$*"; }
gate()  { printf "\n!! %s\n" "$*" >&2; }

# 1. Host prerequisites
say "Step 1/5 — host prerequisites"
bash "$SCRIPTS/install-prereqs.sh" "$@"

# 2. Docker group gate
if ! id -nG "$USER" | grep -qw docker; then
  gate "Your user is not yet in the 'docker' group in this session."
  gate "Log out and back in (or run 'newgrp docker'), then re-run this script."
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  gate "Docker daemon is not reachable. Start it (e.g. 'sudo systemctl start docker')"
  gate "and re-run this script."
  exit 0
fi

# 3. Claude Code OAuth gate
if [[ ! -f "$HOME/.claude/.credentials.json" ]]; then
  gate "Claude Code is not authenticated on the host."
  gate "Run 'claude' once to log in, then quit and re-run this script."
  exit 0
fi

# 4. Fetch upstream container-use rules + build base image
say "Step 2/5 — fetching upstream container-use rules"
bash "$SCRIPTS/fetch-claude-md.sh"

say "Step 3/5 — building agent-base:latest"
bash "$SCRIPTS/build-base-image.sh"

# 5. Install ~/bin launchers (agent-task, setup-project)
say "Step 4/5 — installing ~/bin launchers"
bash "$SCRIPTS/install-launcher.sh"

say "Step 5/5 — done"
cat <<'EOF'

Next:
  1. Open a new shell (or `source ~/.bashrc`) so ~/bin is on PATH.
  2. Export GITHUB_TOKEN (and OPENAI_API_KEY / OPENCODE_API_KEY if you'll use Codex / opencode).
  3. cd to your workspace folder (must be a git repo, or contain git sub-folders).
  4. Run: setup-project
  5. Spawn a task: at <task-name> "<message>"
EOF
