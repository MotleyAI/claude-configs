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
import sys
import json
import re
import os
import shlex

try:
    data = json.loads(sys.stdin.read())
except (json.JSONDecodeError, ValueError):
    # Fail closed: if we can't parse input, require approval
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Failed to parse hook input",
        }
    }))
    sys.exit(0)

tool = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
cmd = tool_input.get("command", "").strip()
unsandboxed = tool_input.get("dangerouslyDisableSandbox", False)

# Safe I/O redirections to strip before checking for shell metacharacters
SAFE_REDIRECTS = re.compile(r'\s*\d*>&\d+\s*|\s*\d*>/dev/null\s*')

# Shell metacharacters that can't be safely decomposed
# Note: && and | are handled separately with smarter logic
UNSAFE_META = re.compile(r'[;`$(){}\n<>]')

# Safe pipe targets — read-only consumers that can't cause side effects
SAFE_PIPE_TARGETS = {"head", "tail", "grep", "wc", "sort"}

# tee is allowed as a pipe target when its destinations are all under /tmp/
# or $TMPDIR — see is_safe_pipe_target.
SAFE_TEE_FLAGS = {"-a", "--append", "-i", "--ignore-interrupts", "--"}

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
    # Catches space-separated (--method POST, -X POST), equals-sign (--method=POST), and no-space (-XPOST) forms
    r"^gh\s+api\b(?!.*(\s+(-X|--method)\s+|-X|--method=)(POST|PUT|PATCH|DELETE))(?!.*(\s+(-f|--field|-F|--raw-field|--input)\b|-[fF]\S|--field=|--raw-field=|--input=))",
    r"^gh\s+auth\s+status\b",
]

# Commands that legitimately need unsandboxed access but are safe
SAFE_UNSANDBOXED_PATTERNS = [
    *GH_READ_PATTERNS,
    # git fetch needs keyring for auth but doesn't mutate local or remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+fetch\b",
    # wc only emits counts, not file contents — safe even on sensitive paths
    r"^wc\b",
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


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def strip_quoted_strings(cmd):
    """Replace quoted strings with placeholder to avoid false metachar matches.
    E.g. gh api --jq '[.[] | select(...)]' → gh api --jq ___"""
    result = []
    in_single = False
    in_double = False
    for c in cmd:
        if c == "'" and not in_double:
            in_single = not in_single
            if not in_single:
                result.append("___")
        elif c == '"' and not in_single:
            in_double = not in_double
            if not in_double:
                result.append("___")
        elif not in_single and not in_double:
            result.append(c)
    return ''.join(result)


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


def split_on_and(cmd):
    """Split command on && outside of quotes. Returns list of parts,
    or None if the command can't be safely split (unbalanced quotes)."""
    parts = []
    current = []
    in_single = False
    in_double = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
        elif c == '&' and not in_single and not in_double:
            if i + 1 < len(cmd) and cmd[i + 1] == '&':
                parts.append(''.join(current).strip())
                current = []
                i += 2
                continue
            else:
                # Single & (background) — not safe to decompose
                return None
        else:
            current.append(c)
        i += 1
    if in_single or in_double:
        return None  # Unbalanced quotes
    parts.append(''.join(current).strip())
    return [p for p in parts if p]


def split_on_pipe(cmd):
    """Split command on | outside of quotes. Returns list of parts,
    or None if the command can't be safely split."""
    parts = []
    current = []
    in_single = False
    in_double = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
        elif c == '|' and not in_single and not in_double:
            if i + 1 < len(cmd) and cmd[i + 1] == '|':
                # || operator — not safe to decompose
                return None
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if in_single or in_double:
        return None
    parts.append(''.join(current).strip())
    return [p for p in parts if p]


def is_safe_tee_path(p):
    """A tee destination is safe if it's an unambiguous path under /tmp/
    or $TMPDIR — no path traversal, no command substitution, no ~/$HOME."""
    if ".." in p or "`" in p or "~" in p:
        return False
    if p.startswith("/tmp/") and "$" not in p:
        return True
    if p == "$TMPDIR" or p.startswith("$TMPDIR/"):
        return p.count("$") == 1
    return False


# File redirects to /tmp/... or $TMPDIR/... — same destination rules as tee.
# Covers >, >>, 2>, 2>>, &>, &>>.
SAFE_TMP_REDIRECT = re.compile(
    r'\s*(?:&>>|&>|2>>|2>|>>|>)\s*(/tmp/[^\s;|&<>]+|\$TMPDIR(?:/[^\s;|&<>]+)?)'
)


def strip_safe_tmp_redirects(s):
    """Remove file redirects whose destination satisfies is_safe_tee_path."""
    def repl(m):
        return '' if is_safe_tee_path(m.group(1)) else m.group(0)
    return SAFE_TMP_REDIRECT.sub(repl, s)


def is_safe_pipe_target(part):
    """A pipe segment is a safe target if it's a pure read-only consumer
    (head/tail/grep/wc/sort), or a tee invocation whose destinations are
    all safe paths."""
    try:
        argv = shlex.split(part)
    except ValueError:
        return False
    if not argv:
        return False
    name = os.path.basename(argv[0])
    if name in SAFE_PIPE_TARGETS:
        return True
    if name == "tee":
        for tok in argv[1:]:
            if tok.startswith("-"):
                if tok not in SAFE_TEE_FLAGS:
                    return False
            else:
                if not is_safe_tee_path(tok):
                    return False
        return True
    return False


def strip_safe_pipes(cmd):
    """If a command ends with pipes to safe consumers (head, tail, grep,
    tee /tmp/..., etc.), strip those and return just the producer command.
    Returns None if any pipe target is unsafe."""
    pipe_parts = split_on_pipe(cmd)
    if pipe_parts is None:
        return None
    if len(pipe_parts) == 1:
        return cmd  # No pipes
    for part in pipe_parts[1:]:
        if not is_safe_pipe_target(part):
            return None
    return pipe_parts[0]


NEEDS_UNSANDBOXED = "This command needs unsandboxed access. Use dangerouslyDisableSandbox: true"


def evaluate_single_cmd(cmd_str, unsandboxed):
    """Evaluate a single (non-compound) command. Returns
    ("allow", None), ("ask", reason), or ("deny", reason)."""
    stripped = cmd_str.strip()
    # Strip safe redirections
    cleaned = SAFE_REDIRECTS.sub('', stripped)

    # Try to strip safe pipes
    producer = strip_safe_pipes(cleaned)
    if producer is None:
        if unsandboxed:
            return ("ask", f"Unsafe pipe: {stripped[:120]}")
        # Inside sandbox — containment covers the risk, allow.
        return ("allow", None)
    cleaned = producer

    normalized = normalize_cmd(cleaned)

    # Check always-dangerous patterns (git push, docker)
    for pattern in ASK_ALWAYS_PATTERNS:
        if re.match(pattern, normalized):
            if unsandboxed:
                return ("ask", f"Dangerous operation: {stripped[:120]}")
            return ("deny", NEEDS_UNSANDBOXED)

    # If bypassing sandbox, only allow known-safe commands
    if unsandboxed:
        for pattern in SAFE_UNSANDBOXED_PATTERNS:
            if re.match(pattern, normalized):
                return ("allow", None)
        return ("ask", f"Sandbox bypass: {stripped[:120]}")

    # gh commands inside sandbox: allow known reads, deny writes (need keyring)
    if re.match(r"^gh\b", normalized):
        for pattern in GH_READ_PATTERNS:
            if re.match(pattern, normalized):
                return ("allow", None)
        return ("deny", NEEDS_UNSANDBOXED)

    # Everything else is contained by the sandbox
    return ("allow", None)


# Only Bash commands need guarding — everything else is sandboxed
if tool != "Bash":
    allow()

# Strip safe redirections and quoted strings for metacharacter check
cmd_for_meta_check = SAFE_REDIRECTS.sub('', cmd)
cmd_for_meta_check = strip_safe_tmp_redirects(cmd_for_meta_check)
cmd_unquoted = strip_quoted_strings(cmd_for_meta_check)

# Check for truly unsafe metacharacters (not && or |, those are handled below).
# Only block when unsandboxed — inside the sandbox, containment handles the risk,
# and patterns like git commit -m "$(cat <<'EOF' ...)" are safe and common.
# Use unquoted version so metacharacters inside quotes don't trigger false positives.
if unsandboxed and UNSAFE_META.search(cmd_unquoted):
    ask(f"Compound command: {cmd[:120]}")

# Check if this is a && chain (use redirect-stripped version so 2>&1 doesn't look like single &)
and_parts = split_on_and(cmd_for_meta_check)
if and_parts is None:
    if unsandboxed:
        ask(f"Compound command: {cmd[:120]}")
    # Inside sandbox with unparseable command — sandbox contains it, allow
    and_parts = [cmd_for_meta_check]

# Evaluate each part of the && chain (or just the single command)
for part in and_parts:
    decision, reason = evaluate_single_cmd(part, unsandboxed)
    if decision == "deny":
        deny(reason)
    if decision == "ask":
        ask(reason)

# All parts approved
allow()
