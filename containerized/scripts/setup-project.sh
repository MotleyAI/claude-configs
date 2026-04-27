#!/usr/bin/env bash
# setup-project.sh — configure Container Use for a workspace so it uses the
# agent-base image and bind-mounts the containerized/ Claude config.
#
# Usage:
#   cd <workspace>
#   setup-project.sh
#
# Operates on the current working directory. No args. Container Use needs the
# workspace root to be a git repo, so:
#   - if cwd is itself a git repo → use it as primary
#   - if cwd is not, but contains git sub-folders → numbered prompt picks
#     which sub-folder hosts .container-use/; the rest become extra-repo
#     setup commands (clone + uv sync if uv.lock present)
#   - otherwise → error and exit. Never auto-init.
#
# Required env: GITHUB_TOKEN
# Optional env: OPENAI_API_KEY (Codex), OPENCODE_API_KEY (opencode)
#
# Idempotent-ish: re-running adds duplicate volume/setup entries because
# `container-use config volume add` is additive. Inspect with
# `container-use config show` and clean up if you need to.

set -euo pipefail

# Resolve own location through symlinks so this script works when invoked
# via the ~/bin symlink that install.sh creates.
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(cd "$(dirname "$SELF")/.." && pwd)"
CONFIG_DIR="$HERE/claude-config"

if [[ ! -f "$CONFIG_DIR/container-use-rules.md" ]] || [[ ! -s "$CONFIG_DIR/container-use-rules.md" ]]; then
  echo "warning: $CONFIG_DIR/container-use-rules.md is missing or empty." >&2
  echo "         Run: bash $HERE/scripts/fetch-claude-md.sh" >&2
fi

# ── env-var preflight ────────────────────────────────────────────────────────
missing=()
[[ -z "${GITHUB_TOKEN:-}" ]] && missing+=("GITHUB_TOKEN")
if (( ${#missing[@]} )); then
  echo "error: required env vars not set: ${missing[*]}" >&2
  echo "       export them and re-run." >&2
  exit 1
fi

[[ -z "${OPENAI_API_KEY:-}"   ]] && echo "warning: OPENAI_API_KEY not set — Codex agent unavailable in containers." >&2
[[ -z "${OPENCODE_API_KEY:-}" ]] && echo "warning: OPENCODE_API_KEY not set — opencode agent unavailable in containers." >&2

# ── pick primary repo ───────────────────────────────────────────────────────
WORKSPACE="$(pwd)"
EXTRA_REPOS=()

is_git_repo() { [[ -d "$1/.git" ]] || git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }

if is_git_repo "$WORKSPACE"; then
  PRIMARY="$WORKSPACE"
  echo "→ Primary repo: $PRIMARY (cwd is a git repo)"
else
  shopt -s nullglob
  SUBS=()
  for d in "$WORKSPACE"/*/; do
    d="${d%/}"
    is_git_repo "$d" && SUBS+=("$d")
  done
  shopt -u nullglob
  if (( ${#SUBS[@]} == 0 )); then
    echo "error: cwd is not a git repo, and no direct sub-folders are git repos." >&2
    echo "       Container Use requires a git repo at the workspace root." >&2
    echo "       Either cd into a git repo, or add one as a sub-folder." >&2
    exit 1
  fi

  echo "cwd is not a git repo. Pick which sub-repo hosts .container-use/:"
  i=1
  for d in "${SUBS[@]}"; do
    printf "  %d) %s\n" "$i" "$(basename "$d")"
    ((i++))
  done
  read -r -p "Number: " n
  if ! [[ "$n" =~ ^[0-9]+$ ]] || (( n < 1 )) || (( n > ${#SUBS[@]} )); then
    echo "error: invalid selection: $n" >&2
    exit 1
  fi
  PRIMARY="${SUBS[$((n-1))]}"
  echo "→ Primary repo: $PRIMARY"

  for d in "${SUBS[@]}"; do
    [[ "$d" == "$PRIMARY" ]] && continue
    EXTRA_REPOS+=("$d")
  done
fi

cd "$PRIMARY"

# ── core CU config ──────────────────────────────────────────────────────────
echo "→ Registering container-use as MCP server for this repo"
claude mcp add container-use -- container-use stdio || true

echo "→ Setting base image to agent-base:latest"
container-use config base-image set agent-base:latest

echo "→ Adding bind-mounts (Claude config: ro)"
container-use config volume add "$CONFIG_DIR/settings.json:/root/.claude/settings.json:ro"
container-use config volume add "$CONFIG_DIR/CLAUDE.md:/root/.claude/CLAUDE.md:ro"
container-use config volume add "$CONFIG_DIR/container-use-rules.md:/root/.claude/container-use-rules.md:ro"
container-use config volume add "$CONFIG_DIR/hooks:/root/.claude/hooks:ro"
container-use config volume add "$CONFIG_DIR/agents:/root/.claude/agents:ro"

echo "→ Adding bind-mounts (Claude subscription credentials: rw)"
# Claude Code uses OAuth for Max/Pro/Team subscriptions; tokens are stored in
# ~/.claude/.credentials.json on the host and refresh periodically, so the
# mount must be read-write. .claude.json holds account state.
if [[ ! -f "$HOME/.claude/.credentials.json" ]]; then
  echo "  warning: $HOME/.claude/.credentials.json not found." >&2
  echo "           Run 'claude' on the host once to authenticate, then re-run this script." >&2
fi
container-use config volume add "$HOME/.claude/.credentials.json:/root/.claude/.credentials.json"
container-use config volume add "$HOME/.claude/.claude.json:/root/.claude/.claude.json"

echo "→ Adding bind-mount (uv wheel cache: rw)"
container-use config volume add "$HOME/.cache/uv:/uv-cache"

# ── extra-repo setup commands (Case B) ──────────────────────────────────────
for repo in "${EXTRA_REPOS[@]}"; do
  name="$(basename "$repo")"
  echo "→ Adding setup command: clone $name"
  container-use config setup add "git clone --local /host-repos/$name /workspace/$name"
  if [[ -f "$repo/uv.lock" ]]; then
    echo "→ Adding setup command: uv sync $name (uv.lock present)"
    container-use config setup add "cd /workspace/$name && uv sync"
  else
    echo "  (skipping uv sync for $name — no uv.lock)"
  fi
done

# ── credential helper + secrets ─────────────────────────────────────────────
echo "→ Adding HTTPS credential helper using GITHUB_TOKEN"
container-use config setup add \
  "git config --global credential.helper '!f() { echo username=x-token; echo password=\$GITHUB_TOKEN; }; f'"

echo "→ Registering secrets from environment"
# ANTHROPIC_API_KEY is intentionally NOT registered — Claude Code would prefer
# it over the OAuth subscription token, billing to the API key instead.
container-use config secret set GITHUB_TOKEN
[[ -n "${OPENAI_API_KEY:-}"   ]] && container-use config secret set OPENAI_API_KEY
[[ -n "${OPENCODE_API_KEY:-}" ]] && container-use config secret set OPENCODE_API_KEY

echo
echo "── final config ──"
container-use config show
echo
echo "✓ Done. Commit .container-use/environment.json in $PRIMARY so all worktrees share it."
