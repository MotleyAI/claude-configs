# Sandbox bypass rules

The Bash sandbox is on by default. The `guard_writes.py` PreToolUse hook
prompts `Sandbox bypass: ...` whenever a Bash call sets
`dangerouslyDisableSandbox: true` for a command that isn't on the
known-safe-unsandboxed allowlist. Bypass is meant to be rare and explicit.

## When to set `dangerouslyDisableSandbox: true`

Only these commands need keyring/network access outside the sandbox:

- `gh ...` (any subcommand) — always needs bypass. The hook denies *every*
  sandboxed `gh` call with a "needs unsandboxed" message (the keyring lives
  outside the sandbox), so trying `gh pr view` inside the sandbox just
  costs a round-trip. Once bypassed, `gh` reads matching `GH_READ_PATTERNS`
  (e.g. `gh pr view`, `gh issue list`, `gh api` GETs, `gh auth status`)
  auto-allow; writes (`gh pr create`, `gh api -X POST`, etc.) prompt.
- `git fetch` / `git pull` — need the credential keyring.
- `git push` — needs the credential keyring. Plain `git push` auto-approves
  unsandboxed (also allowlisted in `settings.json`). The dangerous variants
  — `--force` / `-f` / `--force-with-lease` / `--delete` / `-d` / `--mirror`
  / `--prune` and the `:branch` (deletion) / `+branch` (force) refspec
  forms — always ask, regardless of sandbox state.

Never use `WebFetch` for GitHub API calls — use `gh api` with bypass.

## When NOT to set `dangerouslyDisableSandbox`

Local git operations — both reads AND writes to the local repo — don't
need keyring or network. Run them inside the sandbox without the bypass
flag:

Reads:
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

Local writes (touch the working tree / local refs only — no remote, no keyring):
- `git add`
- `git commit` (including with `-m`/HEREDOC; signing only needs bypass if
  GPG keyring is involved — current setup commits unsigned)
- `git checkout` / `git switch` (local branch ops)
- `git reset` (local)
- `git stash`
- `git tag` (local; `git push --tags` is the network part)
- `git rm`, `git mv`

Setting bypass for any of these will trip the hook with
`Sandbox bypass: ...` because they aren't on `SAFE_UNSANDBOXED_PATTERNS` —
and they don't belong on it, since they don't need bypass in the first
place.

## Quick mental model

- Touches the network or credentials? → bypass.
- Reads local repo state only? → no bypass.
