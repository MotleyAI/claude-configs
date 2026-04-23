#!/usr/bin/env python3
# ~/.claude/hooks/guard_writes.py
import sys, json, re

data = json.loads(sys.stdin.read())
tool = data.get("tool_name", "")
cmd = data.get("tool_input", {}).get("command", "")

READ_ONLY_BASH = [
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(status|diff|log|show|branch|fetch|stash)\b",
    r"^gh\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(pr|issue|run|repo)\s+(list|view)\b",
    r"^gh api GET ",
    r"^(cat|ls|find|grep|head|tail|wc|stat) ",
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


# Auto-approve Read tool entirely
if tool == "Read":
    allow()

# Auto-approve known read-only bash commands
if tool == "Bash":
    for pattern in READ_ONLY_BASH:
        if re.match(pattern, cmd.strip()):
            allow()
    # Anything else: ask for approval
    ask(f"Write/unknown operation: {cmd[:120]}")

# All other tools (Write, Edit, etc.): ask
ask(f"Non-read tool: {tool}")
