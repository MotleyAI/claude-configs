#!/usr/bin/env python3
"""PreToolUse guard: deny gh commands that would publish Claude attribution
(PR / issue / comment / release bodies), inline or via a referenced body file."""

import json
import re
import shlex
import sys
from pathlib import Path

PATTERNS = re.compile(
    r"generated\s+with\s+\[?claude\s+code|co-authored-by:\s*claude|claude\.com/claude-code",
    re.IGNORECASE,
)
PUBLISHING = re.compile(
    r"\bgh\s+(pr\s+(create|edit|comment|review)|issue\s+(create|edit|comment)"
    r"|release\s+(create|edit)|api\b)"
)
FILE_FLAGS = {"--body-file", "-F", "--input", "--notes-file"}


def _file_args(tokens):
    """Paths a gh command reads body text from."""
    out = []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok in FILE_FLAGS and nxt:
            out.append(nxt.split("=@", 1)[1] if "=@" in nxt else nxt)
        elif tok in ("-f", "--field", "--raw-field") and "=@" in nxt:
            out.append(nxt.split("=@", 1)[1])
        elif tok.startswith("--body-file="):
            out.append(tok.split("=", 1)[1])
    return out


def _offending(command: str) -> bool:
    if not PUBLISHING.search(command):
        return False
    if PATTERNS.search(command):
        return True
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for path in _file_args(tokens):
        p = Path(path).expanduser()
        try:
            if p.is_file() and PATTERNS.search(p.read_text(errors="ignore")):
                return True
        except OSError:
            continue
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    if payload.get("tool_name") != "Bash":
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    if _offending(command):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Blocked: this gh command would publish Claude attribution "
                "('Generated with Claude Code' / 'Co-Authored-By: Claude' / a "
                "claude.com/claude-code link). Remove it from the body and retry."
            ),
        }}))


if __name__ == "__main__":
    main()
