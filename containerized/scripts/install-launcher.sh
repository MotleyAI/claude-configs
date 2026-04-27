#!/usr/bin/env bash
# install-launcher.sh — symlink user-facing scripts into ~/bin so they run
# from any directory, and ensure ~/bin is on PATH. Idempotent.
#
# Symlinks:
#   ~/bin/agent-task    → containerized/scripts/agent-task.sh
#   ~/bin/setup-project → containerized/scripts/setup-project.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/bin"
ln -sf "$HERE/agent-task.sh"    "$HOME/bin/agent-task"
ln -sf "$HERE/setup-project.sh" "$HOME/bin/setup-project"

if ! grep -q 'export PATH="$HOME/bin:$PATH"' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.bashrc"
fi
if ! grep -q "alias at='agent-task'" "$HOME/.bashrc" 2>/dev/null; then
  printf "alias at='agent-task'\n" >> "$HOME/.bashrc"
fi

echo "✓ Linked $HOME/bin/agent-task    -> $HERE/agent-task.sh"
echo "✓ Linked $HOME/bin/setup-project -> $HERE/setup-project.sh"
echo "  Open a new shell or run: source ~/.bashrc"
