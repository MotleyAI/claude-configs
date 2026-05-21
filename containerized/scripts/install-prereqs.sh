#!/usr/bin/env bash
# install-prereqs.sh — install host-side prerequisites for the containerized
# parallel-agent workflow.
#
# Idempotent: skips steps where the required binary is already on PATH.
# sudo lines are clearly labelled. Re-run any time.
#
# Flags:
#   --with-host-sandbox   also install bubblewrap + socat (only needed if you
#                         intend to run host-level Claude Code sessions outside
#                         Container Use; not required for the container workflow)
#   --with-gitkraken      install GitKraken .deb for visual diff/merge review
#   --skip-node           don't install fnm + Node LTS (use existing Node setup)

set -euo pipefail

WITH_HOST_SANDBOX=0
WITH_GITKRAKEN=0
SKIP_NODE=0
for arg in "$@"; do
  case "$arg" in
    --with-host-sandbox) WITH_HOST_SANDBOX=1 ;;
    --with-gitkraken)    WITH_GITKRAKEN=1 ;;
    --skip-node)         SKIP_NODE=1 ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say() { printf "\n→ %s\n" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; } # NOSONAR(S7679) — short one-line helper; assigning $1 to a local var adds noise without clarity

if ! have docker; then
  say "Installing Docker (sudo)"
  sudo apt update
  sudo apt install -y docker.io
  sudo usermod -aG docker "$USER"
  echo "  Note: log out and back in (or run 'newgrp docker') so the group takes effect."
else
  say "Docker already installed — skipping"
fi

if [[ $WITH_HOST_SANDBOX -eq 1 ]]; then
  if ! have bwrap; then
    say "Installing bubblewrap + socat for host-level Claude Code sandbox (sudo)"
    sudo apt install -y bubblewrap socat
  else
    say "bubblewrap already installed — skipping"
  fi
fi

if [[ $SKIP_NODE -eq 0 ]] && ! have node; then
  say "Installing fnm + Node LTS"
  curl -fsSL https://fnm.vercel.app/install | bash
  # shellcheck disable=SC1090
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$(fnm env --shell bash 2>/dev/null || true)"
  fnm install --lts
elif [[ $SKIP_NODE -eq 1 ]]; then
  say "Skipping Node install (--skip-node)"
else
  say "Node already installed — skipping"
fi

if ! have claude; then
  if ! have npm; then
    echo "error: npm not found — install Node (omit --skip-node) or install claude manually" >&2
    exit 2
  fi
  say "Installing Claude Code (host)"
  npm install -g @anthropic-ai/claude-code
else
  say "Claude Code already installed — skipping"
fi

if ! have codex; then
  if ! have npm; then
    echo "error: npm not found — install Node (omit --skip-node) or install codex manually" >&2
    exit 2
  fi
  say "Installing Codex CLI (host)"
  npm install -g @openai/codex
else
  say "Codex CLI already installed — skipping"
fi

if ! have gh; then
  say "Installing GitHub CLI from official apt source (sudo)"
  sudo mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt update
  sudo apt install -y gh
else
  say "gh already installed — skipping"
fi

if ! have container-use; then
  say "Installing Container Use"
  curl -fsSL https://raw.githubusercontent.com/dagger/container-use/main/install.sh | bash
else
  say "Container Use already installed — skipping"
fi

if ! have tmux; then
  say "Installing tmux (sudo, required by jmux)"
  sudo apt install -y tmux
else
  say "tmux already installed — skipping"
fi

if ! have bun; then
  say "Installing Bun (required by jmux)"
  curl -fsSL https://bun.sh/install | bash
  # shellcheck disable=SC1091
  export BUN_INSTALL="$HOME/.bun"
  export PATH="$BUN_INSTALL/bin:$PATH"
else
  say "Bun already installed — skipping"
fi

if ! have jmux; then
  say "Installing jmux via Bun"
  bun install -g @jx0/jmux
else
  say "jmux already installed — skipping"
fi

if [[ $WITH_GITKRAKEN -eq 1 ]] && ! have gitkraken; then
  say "Installing GitKraken (sudo)"
  TMP="$(mktemp -d)"
  ( cd "$TMP" && wget -q https://release.gitkraken.com/linux/gitkraken-amd64.deb )
  sudo dpkg -i "$TMP/gitkraken-amd64.deb" || sudo apt -f install -y
  rm -rf "$TMP"
fi

say "Done."
