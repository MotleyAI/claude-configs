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


def offending(cmd: str) -> str | None:
    for sub in SPLIT.split(cmd):
        s = sub.strip()
        if any(p.match(s) for p in EXTERNAL):
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
