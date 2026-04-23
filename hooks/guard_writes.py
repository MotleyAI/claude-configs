#!/usr/bin/env python3
# ~/.claude/hooks/guard_writes.py
#
# Guards dangerous operations in two layers:
#
# 1. Sandbox bypass: any command with dangerouslyDisableSandbox=true
#    is prompted UNLESS it's a known-safe command that legitimately
#    needs unsandboxed access (gh reads, git fetch/pull).
#
# 2. Dangerous commands: git push, gh writes, docker — always prompt
#    regardless of sandbox state.
import sys, json, re

data = json.loads(sys.stdin.read())
tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
cmd = tool_input.get("command", "").strip()
unsandboxed = tool_input.get("dangerouslyDisableSandbox", False)

# Patterns for commands that are always dangerous
ASK_ALWAYS_PATTERNS = [
    # git push (with any flags/args) — mutates remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    # docker — always ask
    r"^docker\b",
]

# Read-only gh patterns — safe even unsandboxed
GH_READ_PATTERNS = [
    r"^gh\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(pr|issue|run|repo)\s+(list|view)\b",
    r"^gh\s+api\s+GET\b",
    r"^gh\s+auth\s+status\b",
]

# Commands that legitimately need unsandboxed access but are safe
SAFE_UNSANDBOXED_PATTERNS = [
    *GH_READ_PATTERNS,
    # git fetch/pull need keyring for auth but don't mutate remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(fetch|pull)\b",
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

# Check if it matches an always-dangerous pattern
for pattern in ASK_ALWAYS_PATTERNS:
    if re.match(pattern, cmd):
        ask(f"Dangerous operation: {cmd[:120]}")

# If bypassing sandbox, only allow known-safe commands through
if unsandboxed:
    for pattern in SAFE_UNSANDBOXED_PATTERNS:
        if re.match(pattern, cmd):
            allow()
    ask(f"Sandbox bypass: {cmd[:120]}")

# gh commands inside sandbox: allow known reads, prompt for writes
if re.match(r"^gh\b", cmd):
    for pattern in GH_READ_PATTERNS:
        if re.match(pattern, cmd):
            allow()
    ask(f"gh write operation: {cmd[:120]}")

# Everything else is contained by the sandbox
allow()
