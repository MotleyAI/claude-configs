# PreToolUse hook: guard_writes.py

Two-layer permission system: sandbox for containment, hook for guarding operations that escape it.

## Non-Bash tools (Edit, Write, Read, Glob, Grep, Agent, etc.)

Auto-approved. Sandbox contains filesystem access.

## Bash inside sandbox

| Command | Decision | Why |
|---------|----------|-----|
| Any command (including `$()`, `` ` ``, subshells, etc.) | **allow** | Sandbox contains everything |

Exception: `git push`, `docker`, `gh` writes would fail inside sandbox anyway (no keyring/socket), but are still caught if they appear as plain commands or inside `&&` chains.

## Bash outside sandbox (`dangerouslyDisableSandbox: true`)

| Command | Decision | Why |
|---------|----------|-----|
| Unsafe metacharacters (`;`, `` ` ``, `$()`, etc.) | **ask** | Can't safely parse |
| `cmd1 && cmd2` | **evaluate each** | Each part checked independently |
| `cmd \| safe_filter` | **evaluate cmd** | Safe pipe targets: head, tail, grep, wc, sort |
| `git push`, `git pull`, `docker *` | **ask** | Mutate remote/local state |
| `git fetch` | **allow** | Read-only, just needs keyring |
| `gh` reads (`pr/issue/run/repo list/view`, `api` without POST flags, `auth status`) | **allow** | Read-only, just needs keyring |
| All other `gh` commands | **ask** | Unknown = assume write |
| Everything else | **ask** | No reason to bypass sandbox |

## Command normalization

Commands are normalized before matching: env var prefixes (`VAR=x`), `command`/`env` wrappers, and absolute paths (`/usr/bin/git` → `git`) are stripped. So `env GIT_SSH=x /usr/bin/git push` still catches `git push`.
