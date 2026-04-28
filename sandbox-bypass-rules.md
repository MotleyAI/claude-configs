# Sandbox bypass rules

The Bash sandbox is on by default. The `guard_writes.py` PreToolUse hook
prompts `Sandbox bypass: ...` whenever a Bash call sets
`dangerouslyDisableSandbox: true` for a command that isn't on the
known-safe-unsandboxed allowlist. Bypass is meant to be rare and explicit.

## When to set `dangerouslyDisableSandbox: true`

Only these commands need keyring/network access outside the sandbox:

- `gh ...` — all `gh` invocations (reads and writes). The hook still
  separately denies gh writes inside sandbox and asks on bypass for
  non-allowlisted gh writes.
- `git fetch` — needs the credential keyring.
- `git push` — needs the credential keyring; the hook will additionally
  ask before each push regardless of sandbox state.

Never use `WebFetch` for GitHub API calls — use `gh api` with bypass.

## When NOT to set `dangerouslyDisableSandbox`

Read-only git operations are local and don't need keyring or network.
Run them inside the sandbox without the bypass flag:

- `git log`
- `git diff` (including `git diff --stat`, `git diff origin/master..HEAD`)
- `git show`
- `git status`
- `git branch`
- `git rev-parse`
- `git ls-files`
- `git check-ignore`
- `git remote -v`
- `git config --get` (read-only config queries)

Setting bypass for any of these will trip the hook with
`Sandbox bypass: ...` because they aren't on `SAFE_UNSANDBOXED_PATTERNS` —
and they don't belong on it, since they don't need bypass in the first
place.

## Quick mental model

- Touches the network or credentials? → bypass.
- Reads local repo state only? → no bypass.
