#!/usr/bin/env python3
"""External-mutation gate for containerized Claude Code agents.

Docker is the boundary. This hook does not gate in-container mutations
(file edits, package installs, etc.) — only commands that escape the
container: git push, gh pr create/merge, gh api POST/DELETE/PUT/PATCH, etc.

It splits compound bash commands on shell operators so a chain like
`git status && git push` is gated even though `git status*` is on the
auto-approve allowlist.

Exit 0  -> hook does not object; Claude Code continues with normal
           permission flow (allowlisted commands auto-approve, the rest
           prompt as usual).
Exit 1  -> stderr is shown to the user as a warning; the normal
           permission flow still runs and prompts for approval.
"""
import json
import re
import shlex
import sys

EXTERNAL = [
    re.compile(p)
    for p in [
        r"^git\s+push(\s|$)",
        r"^git\s+remote\s+(add|remove|set-url)(\s|$)",
        r"^gh\s+pr\s+(create|merge|close|comment|review|edit|lock|unlock|ready|reopen)(\s|$)",
        r"^gh\s+issue\s+(create|close|comment|edit|lock|unlock|reopen|transfer|pin|unpin|delete)(\s|$)",
        r"^gh\s+release\s+(create|edit|delete|upload)(\s|$)",
        r"^gh\s+repo\s+(create|delete|edit|fork|sync|archive|unarchive|rename)(\s|$)",
        r"^gh\s+api\s+(-X\s+)?(POST|DELETE|PUT|PATCH)(\s|$)",
        r"^gh\s+(secret|variable|workflow|ssh-key|gpg-key)\s+",
        r"^gh\s+auth\s+(login|logout|refresh)(\s|$)",
    ]
]

SPLIT = re.compile(r"\|\||&&|;|\||&")

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _token_scan(s: str) -> bool:
    """Token-aware fallback for cases the regex list misses because of
    flag reordering: `git -C /p push`, `gh api /repos -X POST`, `gh api ...
    --method=PATCH`, `gh api ... -XPOST`. Case-insensitive on the method.
    """
    try:
        toks = shlex.split(s)
    except ValueError:
        return False
    if not toks:
        return False
    head = toks[0]
    # `git ... push` anywhere in argv (catches `git -C /p push origin`)
    if head == "git" and "push" in toks[1:]:
        return True
    # `gh api ...` with a write method passed via -X / --method in any position
    if head == "gh" and len(toks) >= 2 and toks[1] == "api":
        for i, t in enumerate(toks):
            # `-X POST`, `--method POST`
            if t in {"-X", "-x", "--method"} and i + 1 < len(toks):
                if toks[i + 1].upper() in WRITE_METHODS:
                    return True
            # `--method=POST`, `--METHOD=PATCH`
            if t.lower().startswith("--method=") and t.split("=", 1)[1].upper() in WRITE_METHODS:
                return True
            # `-XPOST`, `-xPOST`
            if t[:2] in {"-X", "-x"} and len(t) > 2 and t[2:].upper() in WRITE_METHODS:
                return True
    return False


def offending(cmd: str) -> str | None:
    for sub in SPLIT.split(cmd):
        s = sub.strip()
        if any(p.match(s) for p in EXTERNAL):
            return s
        if _token_scan(s):
            return s
    return None


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = data.get("tool_input", {}).get("command", "")
    bad = offending(cmd)
    if bad is None:
        sys.exit(0)
    print(f"External-mutation operation: {bad[:160]}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
