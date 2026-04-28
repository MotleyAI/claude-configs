#!/usr/bin/env bash
set -euo pipefail

echo "Stopping Cowork service if present..."
systemctl --user stop claude-cowork-service 2>/dev/null || true
systemctl --user disable claude-cowork-service 2>/dev/null || true

echo "Removing Claude Desktop / Cowork state (but keeping Claude Code state)..."
# This line is needed if you worked around the self-referential symlink bug of Claude Cowork
# by making the relevant files immutable.
if [ -d ~/.config/Claude/local-agent-mode-sessions/ ]; then
  sudo chattr -R -i ~/.config/Claude/local-agent-mode-sessions/ 2>/dev/null || true
fi

rm -rf ~/.config/Claude
rm -rf ~/.local/share/claude
rm -f ~/.local/bin/claude
rm -f ~/.config/systemd/user/claude-cowork-service.service
rm -rf ~/.config/systemd/user/default.target.wants/*claude-cowork-service* 2>/dev/null || true
systemctl --user daemon-reload || true

echo "Ensuring Claude Desktop APT repo is present..."
curl -fsSL https://patrickjaja.github.io/claude-desktop-bin/install.sh | sudo bash
sudo apt update
sudo apt install -y --reinstall claude-desktop-bin

echo "Ensuring Cowork APT repo is present..."
curl -fsSL https://patrickjaja.github.io/claude-cowork-service/install.sh | sudo bash
sudo apt update
sudo apt install -y --reinstall claude-cowork-service

echo "Done. You can now start Claude Desktop normally."