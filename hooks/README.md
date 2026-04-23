# PreToolUse hook: guard_writes.py

Two-layer permission system: sandbox for containment, hook for guarding operations that escape it.

## Non-Bash tools (Edit, Write, Read, Glob, Grep, Agent, etc.)

Auto-approved. Sandbox contains filesystem access.

## Bash inside sandbox

Everything auto-approves — the sandbox contains it. Includes compound commands (`$()`, backticks, subshells, heredocs, `&&` chains, safe pipes).

Exceptions (would fail inside sandbox anyway due to no keyring/socket):
- `git push`, `docker` → **deny** with "use dangerouslyDisableSandbox: true"
- `gh` write commands → **deny** with "use dangerouslyDisableSandbox: true"
- Unsafe pipe targets (`cmd | bash`) → **ask**

## Bash outside sandbox (`dangerouslyDisableSandbox: true`)

| Command | Decision | Why |
|---------|----------|-----|
| Unsafe metacharacters (`;`, `` ` ``, `$()`, `()`, `{}`) | **ask** | Can't safely parse |
| `cmd1 && cmd2` | **evaluate each** | Each part checked independently |
| `cmd \| safe_filter` | **evaluate cmd** | Safe pipe targets: head, tail, grep, wc, sort |
| `git push`, `docker` | **ask** | Dangerous — mutate remote/state |
| `git fetch` | **allow** | Read-only, just needs keyring |
| `gh` reads (`pr/issue/run/repo list/view`, `api` without POST flags, `auth status`) | **allow** | Read-only, just needs keyring |
| All other `gh` commands | **ask** | Unknown = assume write |
| Everything else | **ask** | No reason to bypass sandbox |

## Safe I/O redirections

`2>&1`, `>/dev/null`, `2>/dev/null` are stripped before metacharacter/pipe analysis and don't trigger compound command detection.

## Command normalization

Commands are normalized before matching: env var prefixes (`VAR=x`), `command`/`env` wrappers, and absolute paths (`/usr/bin/git` → `git`) are stripped. So `env GIT_SSH=x /usr/bin/git push` still catches `git push`.
