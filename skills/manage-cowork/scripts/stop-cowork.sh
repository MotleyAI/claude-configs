#!/bin/bash
set -eu

echo "Stopping claude-cowork service..."
systemctl --user stop claude-cowork 2>/dev/null || true
systemctl --user disable claude-cowork 2>/dev/null || true

if systemctl --user is-active --quiet claude-cowork; then
    echo "ERROR: claude-cowork service is still running." >&2
    systemctl --user status claude-cowork >&2
    exit 1
else
    echo "claude-cowork service stopped."
fi

echo "Killing claude-desktop processes..."
if pkill -f claude-desktop 2>/dev/null; then
    echo "claude-desktop processes killed."
else
    echo "No claude-desktop processes found."
fi

echo "Cowork session stopped."
