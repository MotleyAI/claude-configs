#!/usr/bin/env python3
# ~/.claude/hooks/guard_writes.py
#
# Guards dangerous operations in two layers:
#
# 1. Sandbox bypass: any command with dangerouslyDisableSandbox=true
#    is prompted UNLESS it's a known-safe command (gh reads, git fetch/pull).
#    Network git/gh inside the sandbox gets the same allow/ask verdict.
#
# 2. Dangerous commands: force/delete pushes, gh writes, docker — always
#    prompt regardless of sandbox state.
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

# Safe I/O redirections to strip before checking for shell metacharacters.
# Replaced by a space, never across a newline — gluing `push 2>&1 --force` into
# `push--force`, or two lines into one, would hide what follows.
SAFE_REDIRECTS = re.compile(r'[ \t]*\d*>&\d+[ \t]*|[ \t]*\d*>/dev/null[ \t]*')

# Shell metacharacters that can't be safely decomposed by splitting:
# command substitution and grouping ( $(...), backticks, (), {} ), redirects
# ( <, > ), and newlines. Statement separators (&&, ||, ;) and pipes (|) are
# deliberately NOT here — they're decomposed below and each part is vetted
# individually, so a `;`-chain is approved iff every one of its parts would be
# approved on its own (the same treatment && already gets).
UNSAFE_META = re.compile(r'[`$(){}\n<>]')

# Safe pipe targets — read-only consumers that can't cause side effects
SAFE_PIPE_TARGETS = {"head", "tail", "grep", "wc", "sort"}

# tee is allowed as a pipe target when its destinations are all under /tmp/
# or $TMPDIR — see is_safe_pipe_target.
SAFE_TEE_FLAGS = {"-a", "--append", "-i", "--ignore-interrupts", "--"}

# Patterns for commands that are always dangerous
ASK_ALWAYS_PATTERNS = [
    # git push --force / --force-with-lease / --force-with-includes / --force-if-includes
    # (any token starting with --force after `push` — \b after `force` matches the
    # transition into `-with-…` since `-` is non-word).
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s--force\b",
    # git push -f (short form of --force), including bundled short-option
    # forms like `-fu`, `-uf`, `-vfn` — `f` appears anywhere in a single
    # `-[letters]+` token. `--` (long-flag prefix) is rejected because
    # the inner `-` is not a letter and breaks the `[A-Za-z]*f[A-Za-z]*`
    # match.
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s-[A-Za-z]*f[A-Za-z]*\b",
    # git push --delete / -d (incl. bundled short-option forms like `-du`)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s(?:--delete|-[A-Za-z]*d[A-Za-z]*)\b",
    # git push --mirror (force-updates all refs and deletes remote refs not
    # present locally — same blast radius as --force + --delete combined)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s--mirror\b",
    # git push --prune (deletes remote refs without a local counterpart)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b.*\s--prune\b",
    # git push <remote> [<ref> ...] :branch  (deletion via empty-source
    # refspec — token must START with `:`, so this doesn't catch the normal
    # `src:dst` refspec form where the colon is mid-token)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b(?:\s+\S+)*\s+:\S",
    # git push <remote> [<ref> ...] +branch  (force-push refspec — same
    # multi-arg shape as the deletion form)
    r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+push\b(?:\s+\S+)*\s+\+\S",
    # docker — always ask
    r"^docker\b",
]

# Read-only gh patterns — safe even unsandboxed
GH_READ_PATTERNS = [
    r"^gh\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(pr|issue|run|repo)\s+(list|view)\b",
    # gh pr checks: the PR's status-check rollup — read-only.
    r"^gh\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+pr\s+checks\b",
    # gh api: GET by default, safe unless --method/-X specifies non-GET or -f/--field present (implies POST)
    # Catches space-separated (--method POST, -X POST), equals-sign (--method=POST), and no-space (-XPOST) forms.
    # Method match is case-insensitive — `gh api -X post` / `--method=patch` reach GitHub as writes too.
    r"^gh\s+api\b(?!.*(\s+(-X|--method)\s+|-X|--method=)(?i:POST|PUT|PATCH|DELETE))(?!.*(\s+(-f|--field|-F|--raw-field|--input)\b|-[fF]\S|--field=|--raw-field=|--input=))",
    r"^gh\s+auth\s+status\b",
]

# Commands that legitimately need unsandboxed access but are safe
SAFE_UNSANDBOXED_PATTERNS = [
    *GH_READ_PATTERNS,
    # git fetch needs keyring for auth but doesn't mutate local or remote
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+fetch\b",
    # git ls-remote: read-only network — lists remote refs, mutates nothing
    # (same risk class as fetch, strictly less powerful). Like every git entry
    # here, it is only safe without code-running overrides — see git_runs_code.
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+ls-remote\b",
    # git push (plain — dangerous variants are caught earlier by
    # ASK_ALWAYS_PATTERNS, so anything reaching here is non-force, non-delete).
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    # git pull (fetch + merge): needs keyring, mutations are local-only and reversible
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+pull\b",
    # git merge: local-only, can trigger signing/hooks that need keyring access
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+merge\b",
    # Read-only git introspection — needed inside worktrees because the
    # worktree's `.git` file is in the sandbox's denyWithinAllow list, so
    # commands that touch it (even sandboxed) fail and must retry bypassed.
    # All of these only read git's object DB / index / refs; none push or
    # mutate anything remote.
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(?:status|diff|log|show|merge-base|rev-parse|ls-files|branch)\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+config\s+--get\b",
    # git add / rm — local staging only, no remote, fully reversible
    # (the .git index lives in the worktree's gitdir which the sandbox denies).
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+(?:add|rm)\b",
    # Read-only `git remote` subcommands: just reads .git/config, no network.
    # Safe even unsandboxed.
    # Allowed: `remote` (list), `remote -v`, `remote get-url <name>`
    # Not auto-allowed: `remote show <name>` — DOES network (uses git ls-remote
    # under the hood); falls through to ask-on-bypass so Claude has to opt in.
    # Not allowed at all: `remote add|remove|rename|set-url|prune` — mutating.
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\b\s*$",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\s+-v\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+remote\s+get-url\b",
    # wc only emits counts, not file contents — safe even on sensitive paths
    r"^wc\b",
    # echo: harmless producer. Surviving content has no shell metachars
    # (UNSAFE_META check earlier would have asked first).
    r"^echo\b",
    # Bare `cat` (no file operands) — a pure stdin passthrough, used as the
    # producer of a quoted-heredoc pipe (`cat <<'EOF' | grep x`). The
    # heredoc body is stripped upstream, leaving just `cat`. A `cat <file>` form
    # keeps its operand and does NOT match (so it still asks), and the pipe
    # TARGET must independently be a safe consumer (strip_safe_pipes).
    r"^cat\s*$",
]

# Network git/gh commands. The sandbox reaches GitHub, so inside it they get
# the same verdict as unsandboxed: SAFE_UNSANDBOXED → allow, anything else → ask.
NETWORK_PATTERNS = [
    r"^gh\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+fetch\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+ls-remote\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+push\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+pull\b",
    r"^git\b(\s+(-\w+|--\w[\w-]*)(\s+\S+)?)*\s+merge\b",
]

# Env vars that make git/gh run another program or read another config
# (GIT_SSH_COMMAND, GIT_CONFIG_*, PATH, HOME → a different ~/.gitconfig, ...).
_CODE_RUNNING_ENV = re.compile(
    r"^(?:GIT_\w*|GH_\w*|SSH_\w*|LD_\w*|PATH|HOME|XDG_\w*|PAGER|EDITOR|VISUAL"
    r"|BROWSER|BASH_ENV|ENV)$"
)
# git global options that take a separate value token.
_GIT_VALUE_GLOBALS = {"-C", "--git-dir", "--work-tree", "--namespace"}

# Wrappers that run their arguments as a command (`timeout 60 git push`).
_EXEC_WRAPPERS = {
    "bash", "sh", "zsh", "dash", "eval", "exec", "xargs", "timeout", "nohup",
    "nice", "time", "watch", "sudo", "stdbuf", "flock", "parallel", "find",
}
# A git/gh invocation anywhere inside a statement, and where it ends.
_NESTED_CMD_RE = re.compile(r"(?<![\w.-])(?:/\S*/)?(?:git|gh)\s")
_NESTED_END_RE = re.compile(r"[)`'\";&|\n]")

# Patterns that are denied with a custom message. Used for variants where the
# right answer is "run a SAFER form of the same command". Checked BEFORE
# ASK_ALWAYS, SAFE_UNSANDBOXED, and NETWORK_PATTERNS — match wins regardless of
# sandbox state.
DENY_WITH_ADVICE_PATTERNS = [
    (
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+pull\b.*\s(?:--rebase|-r)\b",
        "Use plain `git pull` instead — `--rebase` rewrites local history and can lose in-progress work on conflicts.",
    ),
    (
        # `-X theirs|ours` and `--strategy-option=theirs|ours` and `-Xtheirs|-Xours`,
        # for both `merge` and `pull` (pull forwards -X to merge).
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+(?:merge|pull)\b.*\s(?:-X\s+(?:theirs|ours)|--strategy-option=(?:theirs|ours)|-X(?:theirs|ours))\b",
        "Use plain `git merge` / `git pull` — `theirs/ours` strategy silently overrides one side on every conflict (resolve manually).",
    ),
    (
        # `-s ours|theirs` / `--strategy=ours|theirs` on merge or pull.
        # The `ours` strategy discards the other side's tree entirely (not
        # just per-conflict — the WHOLE merge takes "our" tree); `theirs`
        # via -s isn't a real git strategy but custom drivers and aliases
        # can implement it, so deny symmetrically.
        r"^git\b(?:\s+(?:-\w+|--\w[\w-]*)(?:\s+\S+)?)*\s+(?:merge|pull)\b.*\s(?:-s\s+(?:ours|theirs)|--strategy=(?:ours|theirs))\b",
        "Use plain `git merge` / `git pull` — `-s ours/theirs` discards one side's tree entirely (not just per-conflict).",
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


_SAFE_BIN_PREFIXES = (
    "/usr/bin/",
    "/bin/",
    "/usr/local/bin/",
    "/sbin/",
    "/usr/sbin/",
)


# `retry.sh [-n N] [-d S] [--] cmd...` re-runs cmd verbatim, so the wrapper is
# stripped and cmd judged exactly as if run bare. Home-rooted paths only (a
# PATH-resolved or /tmp `retry.sh` could be anything), optionally via `bash`.
_RETRY_PREFIX = re.compile(
    r'^(?:bash\s+)?(?:~|/home/[^/\s]+|/root)/\.claude/scripts/retry\.sh'
    r'(?:\s+-[nd]\s+\S+)*(?:\s+--)?\s+'
)


# A leading `VAR=value` prefix; the value may be quoted (`A='x y' git push`).
_ASSIGNMENT = re.compile(r'''^(\w+)=(?:'[^']*'|"(?:[^"\\]|\\.)*"|[^\s'"])*\s+''')


def normalize_cmd(raw):
    """Strip leading env var assignments, command/env prefixes and a trusted
    retry.sh wrapper, resolve absolute paths under standard system bin dirs to
    basenames.

    Paths outside the standard bin dirs (e.g. `/tmp/foo`, `/home/u/bin/foo`)
    keep their full prefix — otherwise an attacker placing a same-named
    script at `/tmp/<allowed-script>.sh` would match the bare-name allowlist
    and bypass the sandbox.
    """
    s = raw.strip()
    # Iteratively strip env var assignments and command/env prefixes
    changed = True
    while changed:
        changed = False
        while _ASSIGNMENT.match(s):
            s = _ASSIGNMENT.sub('', s, count=1)
            changed = True
        if re.match(r'^(command|env)\s+', s):
            s = re.sub(r'^(command|env)\s+', '', s)
            changed = True
        if _RETRY_PREFIX.match(s):
            s = _RETRY_PREFIX.sub('', s, count=1)
            changed = True
    # Resolve absolute paths under standard bin dirs: /usr/bin/git → git.
    # Other absolute paths (e.g. /tmp/foo) are left untouched.
    parts = s.split(None, 1)
    if parts and parts[0].startswith(_SAFE_BIN_PREFIXES):
        parts[0] = os.path.basename(parts[0])
        s = ' '.join(parts)
    return s


def split_statements(cmd):
    """Split a command into statements on `&&`, `||`, `;` and newlines outside
    of quotes, dropping `#` comments and joining `\\`-newline continuations.
    Returns the list of statement parts, or None if the command can't be
    safely split — a single `&` (background execution) or unbalanced quotes.

    Each part is vetted independently by evaluate_single_cmd, so the chain is
    approved iff every part would be approved on its own (`A || B` runs B when
    A fails, so B must be allowed too). A single `|` (pipe) is left intact
    inside each part — handled downstream by strip_safe_pipes."""
    parts = []
    current = []
    in_single = False
    in_double = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "\\" and not in_single:
            if cmd[i + 1:i + 2] != "\n":
                current.append(cmd[i:i + 2])
            i += 2  # escaped char kept verbatim; `\`-newline is a continuation
            continue
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
        elif c == '|' and not in_single and not in_double:
            if i + 1 < len(cmd) and cmd[i + 1] == '|':
                # `||` (or-else) — statement separator; each part vetted
                # independently, same as `&&`/`;`.
                parts.append(''.join(current).strip())
                current = []
                i += 2
                continue
            else:
                # Single `|` (pipe) — left intact; strip_safe_pipes handles it.
                current.append(c)
        elif c in ';\n' and not in_single and not in_double:
            parts.append(''.join(current).strip())
            current = []
        elif (c == '#' and not in_single and not in_double
              and (i == 0 or cmd[i - 1] in ' \t\n;&|()')):
            # Comment: skip to the newline, which still ends the statement.
            # (A trailing `\` inside a comment does NOT continue the line.)
            nl = cmd.find('\n', i)
            i = len(cmd) if nl == -1 else nl
            continue
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
    r'[ \t]*(?:&>>|&>|2>>|2>|>>|>)[ \t]*(/tmp/[^\s;|&<>]+|\$TMPDIR(?:/[^\s;|&<>]+)?)'
)


def strip_safe_tmp_redirects(s):
    """Remove file redirects whose destination satisfies is_safe_tee_path."""
    def repl(m):
        return '' if is_safe_tee_path(m.group(1)) else m.group(0)
    return SAFE_TMP_REDIRECT.sub(repl, s)


# Quoted-delimiter heredoc marker: <<'EOF', <<"EOF", <<-'EOF'. The quoted
# delimiter means the body undergoes NO shell expansion, so the body is inert
# stdin data. An UNQUOTED heredoc (<<EOF) expands $(...) / $var in its body and
# is deliberately NOT matched here — it keeps tripping the compound-command guard.
_QUOTED_HEREDOC_RE = re.compile(r"<<-?\s*(['\"])(\w+)\1")


def _heredoc_close(delim, pos, cmd):
    """Match the line closing a heredoc body that starts at newline `pos`.
    The newline after the delimiter is not consumed, so the next line stays
    its own statement."""
    return re.compile(
        r"\n[ \t]*" + re.escape(delim) + r"(?=\n|$)"
    ).search(cmd, pos)


def strip_quoted_heredocs(cmd):
    """Remove quoted-delimiter heredoc markers AND their bodies from a command.

    ``cat <<'EOF' | la-reply URL\\n<body>\\nEOF`` becomes ``cat  | la-reply URL``:
    the inert stdin data goes, the real command stays to be vetted. Markers
    count only in shell code — not inside quotes, comments or `<<<` here-strings
    — since bash runs the lines after such a fake marker. Anything malformed
    (unclosed quote or `$(`, missing delimiter) returns the command unchanged,
    so the guard still sees every line.
    """
    out = []
    stack = []  # open contexts: "'", '"', "$(", "(", "`"
    pending = []  # delimiters whose bodies start at the next code newline
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        ctx = stack[-1] if stack else None
        if ctx == "'":
            if c == "'":
                stack.pop()
            out.append(c)
            i += 1
            continue
        if c == "\\":
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if cmd.startswith("$(", i):
            stack.append("$(")
            out.append("$(")
            i += 2
            continue
        if c == "`":
            if ctx == "`":
                stack.pop()
            else:
                stack.append("`")
            out.append(c)
            i += 1
            continue
        if ctx == '"':
            if c == '"':
                stack.pop()
            out.append(c)
            i += 1
            continue
        # Shell code: top level, or inside $( ) / ( ) / backticks.
        if c in "'\"(":
            stack.append(c)
        elif c == ")":
            if ctx in ("$(", "("):
                stack.pop()
            elif ctx is not None:
                return cmd  # `)` that closes nothing we track — ambiguous
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|()"):
            nl = cmd.find("\n", i)
            nl = n if nl == -1 else nl
            out.append(cmd[i:nl])
            i = nl
            continue
        elif cmd.startswith("<<<", i):
            out.append("<<<")
            i += 3
            continue
        elif c == "\n" and pending:
            pos = i
            for delim in pending:
                close = _heredoc_close(delim, pos, cmd)
                if not close:
                    return cmd
                pos = close.end()
            pending = []
            i = pos
            continue
        else:
            m = _QUOTED_HEREDOC_RE.match(cmd, i)
            if m:
                pending.append(m.group(2))
                out.append(" ")
                i = m.end()
                continue
        out.append(c)
        i += 1
    if stack or pending:
        return cmd
    return "".join(out)


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

# Flags that turn a "safe stdin consumer" into something dangerous:
# writes to a file, reads sensitive files, or executes external programs.
# Each entry maps a command name → a set of exact flag tokens and a set of
# `--flag=` prefixes to reject. Short attached forms (e.g. `-oFILE`) are
# handled inline in the rejection loop.
#
# Examples that must be rejected:
#   sort -o FILE                — writes FILE
#   sort --output=FILE          — writes FILE
#   sort --files0-from=FILE     — reads FILE (newline/null-separated paths)
#   sort --compress-program=X   — executes external program X
_FORBIDDEN_FLAGS = {
    "sort": {
        "exact": {"-o", "--output", "--files0-from", "--compress-program"},
        "prefix": ("--output=", "--files0-from=", "--compress-program="),
    },
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
            # Reject forbidden flags up front: writes (sort -o FILE),
            # sensitive reads (sort --files0-from=FILE), program execution
            # (sort --compress-program=X). Catches both space-separated
            # and `=`-separated forms, plus short attached `-oFILE`.
            forbidden = _FORBIDDEN_FLAGS.get(name)
            if forbidden:
                for a in args:
                    if a in forbidden["exact"]:
                        return False
                    if any(a.startswith(p) for p in forbidden["prefix"]):
                        return False
                    # Short attached form: `-oFILE` (sort writes to FILE).
                    if a.startswith("-o") and len(a) > 2 and not a.startswith("--"):
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
            # reads FILE. Reject `-f FILE` / `--file=FILE` outright — those
            # read patterns from FILE, which is a sensitive-file-read bypass
            # disguised as a pattern source. `-e PATTERN` / `--regexp=PATTERN`
            # supply the pattern through a flag — once seen, any subsequent
            # positional token is unambiguously a FILE operand and must be
            # rejected. Without -e/--regexp, allow exactly one positional
            # (the pattern).
            i = 0
            non_flag_count = 0
            pattern_via_flag = False
            while i < len(args):
                a = args[i]
                if a == "-":
                    i += 1
                    continue
                if a == "-f" or a == "--file" or a.startswith("--file="):
                    return False
                if a == "--regexp" or a.startswith("--regexp="):
                    pattern_via_flag = True
                    if a == "--regexp" and i + 1 < len(args):
                        i += 2
                        continue
                    i += 1
                    continue
                if a == "-e":
                    pattern_via_flag = True
                    i += 2  # consume the pattern value
                    continue
                if a.startswith("-"):
                    i += 1
                    continue
                # Positional token. If -e/--regexp already supplied the
                # pattern, this can only be a FILE operand → reject.
                if pattern_via_flag:
                    return False
                non_flag_count += 1
                if non_flag_count > 1:
                    return False
                i += 1
            return True
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


def _leading_assignments(raw):
    """Names of the `VAR=value` assignments prefixed to a command."""
    names = []
    s = raw.strip()
    while True:
        s = _RETRY_PREFIX.sub('', s, count=1)
        m = _ASSIGNMENT.match(s) or re.match(r'^(?:command|env)\s+()', s)
        if not m:
            return names
        if m.group(1):
            names.append(m.group(1))
        s = s[m.end():]


def git_runs_code(cleaned, normalized):
    """True if a git/gh command carries overrides that make it run arbitrary
    programs: `-c`/`--config-env` (core.sshCommand, protocol.ext.allow, ...),
    `--upload-pack`/`--receive-pack`/`--exec`, `ext::`/`fd::` remotes, or
    env vars such as GIT_SSH_COMMAND."""
    try:
        argv = shlex.split(normalized)
    except ValueError:
        return True
    if not argv or argv[0] not in ("git", "gh"):
        return False
    if any(_CODE_RUNNING_ENV.match(n) for n in _leading_assignments(cleaned)):
        return True
    if argv[0] == "gh":
        return False
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        opt = argv[i]
        if opt.startswith(("-c", "--config-env", "--exec-path")):
            return True
        i += 2 if opt in _GIT_VALUE_GLOBALS else 1
    sub = argv[i] if i < len(argv) else ""
    for tok in argv[i + 1:]:
        if tok.startswith(("--upload-pack", "--receive-pack", "--exec", "fd::")):
            return True
        if "ext::" in tok or (sub == "ls-remote" and tok.startswith("-u")):
            return True
    return False


def nested_command_verdict(stmt, unsandboxed):
    """Vet git/gh commands hidden inside a statement — in `$(...)`, backticks,
    a subshell/brace group, a pipe, or an exec wrapper (`bash -c`, `xargs`,
    `timeout`). Returns ("ask", reason) if one would not be allowed, else None."""
    normalized = normalize_cmd(stmt)
    words = normalized.split(None, 1)
    head = os.path.basename(words[0]) if words else ""
    if head in _EXEC_WRAPPERS or "$(" in stmt or "`" in stmt:
        text = normalized
    else:
        text = strip_quoted_strings(normalized)
        if not re.search(r"[(){}|]", text):
            return None
    for m in _NESTED_CMD_RE.finditer(text):
        if m.start() == 0:
            continue  # the statement's own command — vetted by the caller
        end = _NESTED_END_RE.search(text, m.start())
        inner = text[m.start():end.start() if end else len(text)]
        if evaluate_single_cmd(inner, unsandboxed)[0] != "allow":
            return ("ask", f"Nested command: {inner.strip()[:120]}")
    return None


def evaluate_single_cmd(cmd_str, unsandboxed):
    """Evaluate a single (non-compound) command. Returns
    ("allow", None), ("ask", reason), or ("deny", reason)."""
    stripped = cmd_str.strip()
    # Strip safe redirections
    cleaned = SAFE_REDIRECTS.sub(' ', stripped).strip()

    # The sandbox reaches GitHub, so a git/gh write must not hide behind a
    # substitution, pipe or wrapper in either mode.
    nested = nested_command_verdict(cleaned, unsandboxed)
    if nested:
        return nested

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
            return ("ask", f"Dangerous operation: {stripped[:120]}")

    runs_code = git_runs_code(cleaned, normalized)
    # The git regexes can't parse a quoted `-c k='a b'` value, so a networked
    # git with such overrides asks outright, sandboxed or not.
    if runs_code and re.search(r"\b(?:push|fetch|pull|ls-remote|remote|clone|submodule)\b",
                               normalized):
        return ("ask", f"git with code-running overrides: {stripped[:120]}")
    safe = any(re.match(p, normalized) for p in SAFE_UNSANDBOXED_PATTERNS) and not runs_code

    # If bypassing sandbox, only allow known-safe commands
    if unsandboxed:
        if safe:
            return ("allow", None)
        return ("ask", f"Sandbox bypass: {stripped[:120]}")

    # Network git/gh inside the sandbox: same gate as unsandboxed (gh writes ask)
    if any(re.match(p, normalized) for p in NETWORK_PATTERNS) and not safe:
        return ("ask", f"Network operation: {stripped[:120]}")

    # Everything else is contained by the sandbox
    return ("allow", None)


# Only Bash commands need guarding — everything else is sandboxed
if tool != "Bash":
    allow()

# Strip safe redirections and quoted strings for metacharacter check
cmd_for_meta_check = SAFE_REDIRECTS.sub(' ', cmd)
cmd_for_meta_check = strip_safe_tmp_redirects(cmd_for_meta_check)
# Drop quoted-delimiter heredoc bodies (inert stdin data) so `<<` and the body
# newlines don't read as a compound command; the producer + pipe target remain.
cmd_for_meta_check = strip_quoted_heredocs(cmd_for_meta_check)
cmd_unquoted = strip_quoted_strings(cmd_for_meta_check)

# Check for truly unsafe metacharacters (not && or |, those are handled below).
# Only block when unsandboxed — inside the sandbox, containment handles the risk,
# and patterns like git commit -m "$(cat <<'EOF' ...)" are safe and common.
# Use unquoted version so metacharacters inside quotes don't trigger false positives.
if unsandboxed and UNSAFE_META.search(cmd_unquoted):
    ask(f"Compound command: {cmd[:120]}")

# Decompose into statements on &&, ||, ; and newlines (redirect-stripped so 2>&1
# isn't read as a single &). None => a single `&` background op or unbalanced quotes.
stmt_parts = split_statements(cmd_for_meta_check)
if stmt_parts is None:
    if unsandboxed:
        ask(f"Compound command: {cmd[:120]}")
    # Sandboxed but unparseable: split on every separator, quotes ignored, so
    # `echo x & git push --force` can't pass as one `echo` statement.
    stmt_parts = [p for p in re.split(r"[;&|\n]+", cmd_for_meta_check) if p.strip()]

# Evaluate each statement (each part of the chain, or the single command)
for part in stmt_parts:
    decision, reason = evaluate_single_cmd(part, unsandboxed)
    if decision == "deny":
        deny(reason)
    if decision == "ask":
        ask(reason)

# All parts approved
allow()
