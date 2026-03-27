#!/bin/bash
set -eu

echo "Enabling and starting claude-cowork service..."
systemctl --user enable claude-cowork
systemctl --user start claude-cowork

# Verify it's running
if systemctl --user is-active --quiet claude-cowork; then
    echo "claude-cowork service is running."
else
    echo "ERROR: claude-cowork service failed to start." >&2
    systemctl --user status claude-cowork >&2
    exit 1
fi

echo "Launching Claude Desktop..."
nohup claude-desktop &>/dev/null &
echo "Claude Desktop launched (PID: $!)."
