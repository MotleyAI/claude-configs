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

# bash invocations safe enough to receive piped stdin. The script's basename
# (argv[1] of the bash call) is matched against this set. Used for
# `echo body | bash <known-safe-script> URL` patterns where the script is
# already audited and trusted.
SAFE_PIPE_BASH_SCRIPTS = {
    # reply-to-pr-thread.sh: posts a single PR review-thread reply via
    # `gh api .../pulls/N/comments/<id>/replies`. The skill description
    # marks it as "auto-approved globally"; the pipe form would otherwise
    # trip the unsafe-pipe branch.
    "reply-to-pr-thread.sh",
}

# tee is allowed as a pipe target when its destinations are all under /tmp/
# or $TMPDIR — see is_safe_pipe_target.
SAFE_TEE_FLAGS = {"-a", "--append", "-i", "--ignore-interrupts", "--"}

# Patterns for commands that are always dangerous
ASK_ALWAYS_PATTERNS = [
    # git push --force / --force-with-lease / --force-with-includes / --force-if-includes
    # (any token starting with --force after `push` — \b after `force` matches the
    # transition into `-with-…` since `-` is non-word).
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s--force\b",
    # git push -f (short form of --force)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s-f\b",
    # git push --delete / -d  (deletes a remote ref)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s(?:--delete|-d)\b",
    # git push origin :branch  (deletion via empty-source refspec)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b\s+\S+\s+:\S",
    # git push origin +branch  (force-push refspec)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b\s+\S+\s+\+\S",
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
    # git push (plain — dangerous variants are caught earlier by
    # ASK_ALWAYS_PATTERNS, so anything reaching here is non-force, non-delete).
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    # git pull (fetch + merge): needs keyring, mutations are local-only and reversible
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+pull\b",
    # git merge: local-only, can trigger signing/hooks that need keyring access
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+merge\b",
    # git remote -v (and other read-only `git remote` subcommands): just
    # reads .git/config, no network. Safe even unsandboxed.
    # Allowed: `remote` (list), `remote -v`, `remote show <name>`, `remote get-url <name>`
    # Not allowed: `remote add`, `remote remove`, `remote rename`, `remote set-url`, `remote prune`
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\b\s*$",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\s+-v\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\s+(show|get-url)\b",
    # wc only emits counts, not file contents — safe even on sensitive paths
    r"^wc\b",
    # fetch-coderabbit-threads.sh: wraps a single `gh api graphql` GET query
    # over PR review threads — read-only, no mutations. Same risk profile as
    # GH_READ_PATTERNS. Two forms: `bash <path>/fetch-coderabbit-threads.sh ...`
    # and direct invocation (after normalize_cmd basenames the path).
    r"^bash\s+\S*\.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads\.sh\b",
    r"^fetch-coderabbit-threads\.sh\b",
    # fetch-failed-pr-checks.sh: wraps `gh pr view --json statusCheckRollup` +
    # `gh run view --log-failed`. Read-only, no mutations.
    r"^bash\s+\S*\.claude/skills/fetch-failed-pr-checks/scripts/fetch-failed-pr-checks\.sh\b",
    r"^fetch-failed-pr-checks\.sh\b",
    # reply-to-pr-thread.sh: POSTs a single review-thread reply via
    # `gh api -X POST .../pulls/N/comments/<id>/replies`. Auto-approved per
    # the user's "always allowed" request — mutates GitHub but the blast radius
    # is one comment, easily deleted via `gh`.
    r"^bash\s+\S*\.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread\.sh\b",
    r"^reply-to-pr-thread\.sh\b",
    # echo: harmless producer used to feed stdin into reply-to-pr-thread.sh
    # (and similar safe-pipe-bash patterns). Surviving content has no shell
    # metachars (UNSAFE_META check earlier would have asked first).
    r"^echo\b",
]

# Commands that genuinely need network + keyring — must run with bypass.
# Inside the sandbox these are denied with a clear message instead of being
# allowed and then failing opaquely at runtime.
NEEDS_UNSANDBOXED_PATTERNS = [
    r"^gh\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+fetch\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+pull\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+merge\b",
]

# Patterns that are denied with a custom message rather than the generic
# NEEDS_UNSANDBOXED bypass advice. Used for variants where the right answer
# is "run a SAFER form of the same command". Checked BEFORE ASK_ALWAYS,
# SAFE_UNSANDBOXED, and NEEDS_UNSANDBOXED — match wins regardless of
# sandbox state.
DENY_WITH_ADVICE_PATTERNS = [
    (
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+pull\b.*\s(?:--rebase|-r)\b",
        "Use plain `git pull` instead — `--rebase` rewrites local history and can lose in-progress work on conflicts.",
    ),
    (
        # `-X theirs|ours` and `--strategy-option=theirs|ours` and `-Xtheirs|-Xours`
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+merge\b.*\s(?:-X\s+(?:theirs|ours)|--strategy-option=(?:theirs|ours)|-X(?:theirs|ours))\b",
        "Use plain `git merge` instead — `theirs/ours` strategy silently overrides one side on every conflict (resolve manually).",
    ),
    (
        # --squash collapses history without producing a merge commit
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+merge\b.*\s--squash\b",
        "Use plain `git merge` instead — `--squash` discards the merge commit and the per-commit history of the incoming branch.",
    ),
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
    or $TMPDIR (where $TMPDIR resolves to a path under /tmp/) — no path
    traversal, no command substitution, no ~/$HOME."""
    if ".." in p or "`" in p or "~" in p:
        return False
    if p.startswith("/tmp/") and "$" not in p:
        return True
    if p == "$TMPDIR" or p.startswith("$TMPDIR/"):
        if p.count("$") != 1:
            return False
        # $TMPDIR is only safe when it actually resolves under /tmp/.
        # Without this check, an attacker who controls TMPDIR (e.g. exporting
        # TMPDIR=/etc) could direct a tee write outside /tmp.
        tmpdir = os.environ.get("TMPDIR", "")
        if not tmpdir:
            return False
        # Normalize trailing slash so /tmp and /tmp/ both count as under /tmp.
        return tmpdir == "/tmp" or tmpdir.startswith("/tmp/")
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


# Flags that consume the next argv token as a value (not a file operand).
# Per-command list — keeps us from mis-parsing `tail -f file` (where -f
# doesn't take a value) as if `-f` were value-taking.
_VALUE_TAKING_FLAGS = {
    "head": {"-n", "-c", "--lines", "--bytes"},
    "tail": {"-n", "-c", "--lines", "--bytes", "--pid", "--max-unchanged-stats"},
    "sort": {"-k", "-t", "-T", "-S", "--key", "--field-separator",
             "--temporary-directory", "--buffer-size", "--parallel",
             "--compress-program", "--files0-from", "--batch-size"},
    "wc": set(),
}

# Flags on these commands that perform a WRITE — must reject even if the
# operand looks like a value. `sort -o FILE` writes to FILE.
_WRITE_FLAGS = {
    "sort": ("-o", "--output", "-o", "--output="),  # short forms `-oFILE` handled below
}


def is_safe_pipe_target(part):
    """A pipe segment is a safe target if it's a pure read-only consumer
    (head/tail/grep/wc/sort) **with no file operands**, or a tee invocation
    whose destinations are all safe paths.

    Without the no-file-operand check, a name-only allowlist would pass
    `cmd | head /etc/passwd` — `head` matches by name, the pipe gets
    stripped, and the producer auto-allows. The `head` invocation then
    reads /etc/passwd unsandboxed.
    """
    try:
        argv = shlex.split(part)
    except ValueError:
        return False
    if not argv:
        return False
    name = os.path.basename(argv[0])
    if name in SAFE_PIPE_TARGETS:
        args = argv[1:]
        if name in {"head", "tail", "sort", "wc"}:
            # Reject explicit write flags up front (e.g. `sort -o FILE`).
            for a in args:
                if name in _WRITE_FLAGS:
                    if a in {"-o", "--output"} or a.startswith("--output=") or (a.startswith("-o") and len(a) > 2):
                        return False
            # Walk argv: each token must be either a flag, the stdin marker
            # `-`, or the value consumed by the *previous* value-taking flag.
            value_taking = _VALUE_TAKING_FLAGS.get(name, set())
            i = 0
            while i < len(args):
                a = args[i]
                if a == "-":
                    i += 1
                    continue
                if a.startswith("-"):
                    # `--flag=value` carries its value attached, no consumption needed.
                    if a in value_taking and "=" not in a and i + 1 < len(args):
                        i += 2  # skip the consumed value
                    else:
                        i += 1
                    continue
                # Non-flag, non-stdin, non-value token = file operand → reject.
                return False
            return True
        if name == "grep":
            # `grep [flags] PATTERN` reads stdin; `grep [flags] PATTERN FILE`
            # reads FILE. Allow at most one non-flag arg (the PATTERN).
            # grep's value-taking flags (-e, -f, --regexp=, --file=) make
            # the pattern explicit, but the conservative count-non-flags
            # rule is good enough — file operands push the count >1.
            non_flags = [a for a in args if not a.startswith("-") and a != "-"]
            return len(non_flags) <= 1
        # Should not reach here — every name in SAFE_PIPE_TARGETS is handled
        # above. Defensive return.
        return False
    if name == "tee":
        for tok in argv[1:]:
            if tok.startswith("-"):
                if tok not in SAFE_TEE_FLAGS:
                    return False
            else:
                if not is_safe_tee_path(tok):
                    return False
        return True
    # bash invoking a known-safe script (script basename in
    # SAFE_PIPE_BASH_SCRIPTS) — used for `echo body | bash <safe-script>` flows.
    if name == "bash" and len(argv) >= 2:
        if os.path.basename(argv[1]) in SAFE_PIPE_BASH_SCRIPTS:
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

    # Check deny-with-advice patterns first (e.g. `git pull --rebase` →
    # use plain `git pull` instead). Match wins regardless of sandbox state.
    for pattern, advice in DENY_WITH_ADVICE_PATTERNS:
        if re.match(pattern, normalized):
            return ("deny", advice)

    # Check always-dangerous patterns (git push --force, docker)
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

    # Network/keyring commands inside sandbox: deny with clear bypass instruction
    for pattern in NEEDS_UNSANDBOXED_PATTERNS:
        if re.match(pattern, normalized):
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
