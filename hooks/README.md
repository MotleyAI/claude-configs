# PreToolUse hook: guard_writes.py

Two-layer permission system: sandbox for containment, hook for guarding operations that escape it.

## Non-Bash tools (Edit, Write, Read, Glob, Grep, Agent, etc.)

Auto-approved. Sandbox contains filesystem access.

## Bash inside sandbox

Everything auto-approves — the sandbox contains it — except what reaches GitHub, since the sandbox has network and keyring access:
- Network `git`/`gh` (`fetch`, `ls-remote`, `push`, `pull`, `merge`, `gh *`) get the same verdict as unsandboxed: reads, PR/issue comments and plain push allow, other writes ask.
- Force/delete pushes and `docker` → **ask**.
- A git/gh command nested in `$()`, backticks, `( )`, `{ }`, a pipe or an exec wrapper (`bash -c`, `xargs`, `timeout`, …) is vetted the same way.
- git with code-running overrides (`-c`, `--upload-pack`, `ext::` remotes, `GIT_SSH_COMMAND=`, …) plus a network subcommand → **ask**.

Inside the sandbox this is a guardrail against accidental writes, not a boundary: a deliberately disguised command (`g\it push --force`, `f=git; $f push`, a script calling git) is not recognised. Outside the sandbox anything unrecognised asks.

Statements are split on `&&`, `||`, `;` and newlines; `#` comments are dropped and `\`-newline continuations joined, as bash does. Quoted heredoc bodies (`<<'EOF'`) are dropped as inert data, but only for markers in shell code — not in quotes, comments or `<<<` here-strings.

## Bash outside sandbox (`dangerouslyDisableSandbox: true`)

| Command | Decision | Why |
|---------|----------|-----|
| Unsafe metacharacters (`` ` ``, `$()`, `()`, `{}`, `<`, `>`, newline), incl. `$()`/backticks inside double quotes | **ask** | Can't safely parse |
| `cmd1 && cmd2`, `;`, `\|\|` | **evaluate each** | Each part checked independently |
| git with code-running overrides (`-c`, `--config-env`, `--upload-pack`, `--receive-pack`, `<helper>::` remotes, `GIT_*`/`PATH`/`HOME` env prefixes) | **ask** | Runs an arbitrary program |
| `cmd \| safe_filter` | **evaluate cmd** | Safe pipe targets: head, tail, grep, wc, sort |
| `git push`, `docker` | **ask** | Dangerous — mutate remote/state |
| `git fetch`, `git ls-remote` | **allow** | Read-only, just needs keyring |
| `gh` reads (`pr/issue/run/repo list/view`, `pr checks`, `api` without POST flags, `auth status`) | **allow** | Read-only, just needs keyring |
| `gh pr comment`, `gh issue comment` (not `--delete-last`) | **allow** | One easily-deleted comment; attribution still blocked |
| All other `gh` commands | **ask** | Unknown = assume write |
| `wc` (standalone) | **allow** | Counts only, no content exposure |
| Everything else | **ask** | No reason to bypass sandbox |

## Safe I/O redirections

These are stripped before metacharacter/pipe analysis and don't trigger compound command detection:

- `2>&1`, `>/dev/null`, `2>/dev/null` — fd dup and `/dev/null` sinks.
- `>`, `>>`, `2>`, `2>>`, `&>`, `&>>` to a literal `/tmp/...` or `$TMPDIR/...` path (same destination rules as `tee` — no `..`, no command substitution, no `~`/`$HOME`). Other paths still trip the metacheck under bypass.

## Command normalization

Commands are normalized before matching: env var prefixes (`VAR=x`, `VAR='a b'`), `command`/`env` wrappers, a trusted `~/.claude/scripts/retry.sh` wrapper, and absolute paths (`/usr/bin/git` → `git`) are stripped. So `env GIT_SSH=x /usr/bin/git push` still catches `git push`.

Safe redirects are replaced by a space, never across a newline, so `git push 2>&1 --force` still reads as a force push.

## block_claude_attribution.py

Second PreToolUse hook: denies `gh` commands that publish PR/issue/comment/release text containing Claude attribution ("Generated with Claude Code", "Co-Authored-By: Claude", claude.com/claude-code links), inline or via a body file (`--body-file`, `-F`, `--input`, `--notes-file`, `-f k=@file`). Commit messages are covered by `git-hooks/commit-msg`.
