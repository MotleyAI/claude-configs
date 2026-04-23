#!/usr/bin/env python3
# ~/.claude/hooks/guard_writes.py
#
# With sandboxing enabled, most operations are safely contained.
# This hook only guards the three excluded-from-sandbox commands
# that can affect shared/remote state:
#   - git push (mutates remote)
#   - gh writes (mutates GitHub)
#   - docker (always prompt)
import sys, json, re

data = json.loads(sys.stdin.read())
tool = data.get("tool_name", "")
cmd = data.get("tool_input", {}).get("command", "").strip()

# Patterns for commands that escape the sandbox and need approval
ASK_PATTERNS = [
    # git push (with any flags/args) — the only git command that mutates remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    # docker — always ask
    r"^docker\b",
]

# Read-only gh patterns — these are safe
GH_READ_PATTERNS = [
    r"^gh\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(pr|issue|run|repo)\s+(list|view)\b",
    r"^gh\s+api\s+GET\b",
]


def allow():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }))
    sys.exit(0)


def ask(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


# Only Bash commands need guarding — everything else is sandboxed
if tool != "Bash":
    allow()

# Check if it matches a dangerous pattern
for pattern in ASK_PATTERNS:
    if re.match(pattern, cmd):
        ask(f"Excluded-from-sandbox operation: {cmd[:120]}")

# gh commands: allow known reads, prompt for everything else
if re.match(r"^gh\b", cmd):
    for pattern in GH_READ_PATTERNS:
        if re.match(pattern, cmd):
            allow()
    ask(f"gh write operation: {cmd[:120]}")

# Everything else is contained by the sandbox
allow()
