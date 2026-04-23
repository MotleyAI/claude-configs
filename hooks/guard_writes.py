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
import sys, json, re, os

data = json.loads(sys.stdin.read())
tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
cmd = tool_input.get("command", "").strip()
unsandboxed = tool_input.get("dangerouslyDisableSandbox", False)

# Shell metacharacters that indicate compound/piped commands
SHELL_META = re.compile(r'[;&|`$]|<<|>>')

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
    # gh api: GET by default, safe unless --method/-X specifies non-GET or -f/--field present (implies POST)
    r"^gh\s+api\b(?!.*\s+(-X|--method)\s+(POST|PUT|PATCH|DELETE))(?!.*\s+(-f|--field|-F|--raw-field|--input)\b)",
    r"^gh\s+auth\s+status\b",
]

# Commands that legitimately need unsandboxed access but are safe
SAFE_UNSANDBOXED_PATTERNS = [
    *GH_READ_PATTERNS,
    # git fetch needs keyring for auth but doesn't mutate local or remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+fetch\b",
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


def normalize_cmd(raw):
    """Strip leading env var assignments and command/env prefixes,
    resolve absolute paths to basenames."""
    s = raw.strip()
    # Iteratively strip env var assignments and command/env prefixes
    changed = True
    while changed:
        changed = False
        while re.match(r'^\w+=\S*\s+', s):
            s = re.sub(r'^\w+=\S*\s+', '', s)
            changed = True
        if re.match(r'^(command|env)\s+', s):
            s = re.sub(r'^(command|env)\s+', '', s)
            changed = True
    # Resolve absolute paths: /usr/bin/git → git
    parts = s.split(None, 1)
    if parts:
        parts[0] = os.path.basename(parts[0])
        s = ' '.join(parts)
    return s


# Only Bash commands need guarding — everything else is sandboxed
if tool != "Bash":
    allow()

# Compound commands can't be safely parsed — prompt
if SHELL_META.search(cmd):
    ask(f"Compound command: {cmd[:120]}")

# Normalize the command for pattern matching
normalized = normalize_cmd(cmd)

# Check if it matches an always-dangerous pattern
for pattern in ASK_ALWAYS_PATTERNS:
    if re.match(pattern, normalized):
        ask(f"Dangerous operation: {cmd[:120]}")

# If bypassing sandbox, only allow known-safe commands through
if unsandboxed:
    for pattern in SAFE_UNSANDBOXED_PATTERNS:
        if re.match(pattern, normalized):
            allow()
    ask(f"Sandbox bypass: {cmd[:120]}")

# gh commands inside sandbox: allow known reads, prompt for writes
if re.match(r"^gh\b", normalized):
    for pattern in GH_READ_PATTERNS:
        if re.match(pattern, normalized):
            allow()
    ask(f"gh write operation: {cmd[:120]}")

# Everything else is contained by the sandbox
allow()
