# Parallel AI Coding Agents on Ubuntu: Containerized Setup

A reference for running multiple isolated AI coding agents (Claude Code, Codex CLI,
opencode) in parallel on Ubuntu, with per-task containerised environments, multi-repo
support, git branch isolation, and a human-in-the-loop review workflow.

Everything specific to the containerized setup lives inside this `containerized/`
directory and is bind-mounted into agent containers as needed. The host's
`~/.claude/` is **not** read or written — host (no-CU) Claude Code sessions are
configured separately and stay completely independent.

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────┐
│  jmux (tmux overlay)                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ task-A 🟠 │  │ task-B ✅ │  │ task-C 🔄 │  ← sidebar │
│  └──────────┘  └──────────┘  └──────────┘             │
│       │               │             │                   │
│  Container Use — one Docker container per task          │
│  (custom base image, all repos cloned, isolated env)    │
│       │               │             │                   │
│  Claude Code / Codex CLI / opencode running inside      │
│  each container (pick one per task with --agent)        │
└─────────────────────────────────────────────────────────┘
              ↓  agent done
         GitKraken — visual diff review + merge
```

**Layers:**
- **Custom base image** — Ubuntu 24.04 + uv + Python 3.12 + Node + gh + Claude
  Code + Codex CLI + opencode, built once
- **jmux** — session dashboard, attention flags, cost visibility
- **Container Use** — Docker container + git branch per task (multi-repo isolation)
- **Coding agent CLI** — Claude Code, Codex, or opencode, picked per task
- **GitKraken** — diff review and merge UI once an agent finishes
- **`containerized/claude-config/`** — settings.json, CLAUDE.md, hooks, agents.
  Bind-mounted read-only into each container at `/root/.claude/...`. Host's
  `~/.claude/` is untouched.

---

## One-Time Setup

```bash
cd /path/to/claude-configs

# 1. Host prerequisites (Docker, jmux, Container Use, fnm+Node, gh, etc.)
bash containerized/scripts/install-prereqs.sh
# Optional flags:
#   --with-host-sandbox   install bubblewrap+socat (for host-level Claude Code sessions)
#   --with-gitkraken      install GitKraken .deb
#   --skip-node           leave existing Node setup alone
# After this you must log out and back in (or `newgrp docker`) for docker group membership.

# 2. Fetch the dagger container-use agent rules into claude-config/container-use-rules.md
bash containerized/scripts/fetch-claude-md.sh

# 3. Build the base image (~3–5 min the first time)
bash containerized/scripts/build-base-image.sh
# Sanity: prints versions of claude, codex, opencode, uv, python, gh

# 4. Install the agent-task launcher and `agt` alias
bash containerized/scripts/install-launcher.sh
source ~/.bashrc
```


---

## Base Image (`Dockerfile.agent-base`)

Ubuntu 24.04 with everything pre-installed so per-task containers start in seconds:

| Layer | Contents |
|---|---|
| apt | git, curl, ca-certificates, build-essential, python3.12 (+dev/lib), nodejs/npm, gh, unzip |
| copied from `ghcr.io/astral-sh/uv:latest` | uv binary at `/usr/local/bin/uv` |
| `npm i -g` | `@anthropic-ai/claude-code`, `@openai/codex` |
| upstream installer | opencode at `/usr/local/bin/opencode` |
| pre-created dirs | `/root/.claude/{hooks,agents}` (bind-mount targets) |

uv environment baked in: `UV_PYTHON_DOWNLOADS=never` (use system 3.12),
`UV_LINK_MODE=copy` (cache and `.venv` on different filesystems),
`UV_COMPILE_BYTECODE=1`, `UV_CACHE_DIR=/uv-cache`.

### Container startup time

| Step | Naive setup commands | Custom base image |
|---|---|---|
| Toolchain installation | ~2–3 min (apt + curl + npm) | 0 (baked in) |
| `uv sync` cold (no cache) | ~60s | ~60s |
| `uv sync` warm (cache hit) | ~60s | ~2s |
| Total time to agent running | 3–4 min | ~10s |

---

## Containerized Claude Code Configuration

Lives entirely in `containerized/claude-config/`. Bind-mounted read-only into each
container. Host `~/.claude/` is **not** read.

### Permission model

The container is the security boundary, so the policy is:

| Operation | Decision |
|---|---|
| Read-only `git`, `gh`, file-listing, viewing | **Auto-approve** via `permissions.allow` |
| Anything else inside the container (file edits, `npm install`, `uv sync`, running tests, building) | Normal Claude Code flow — typically auto-approved by default rules; nothing is gated |
| Operations that escape the container (`git push`, `gh pr create/merge/close`, `gh api POST/DELETE/PUT/PATCH`, `gh release create`, etc.) | **Ask** — `guard_writes.py` PreToolUse hook prompts |

### `claude-config/settings.json`

No `sandbox` block — Docker provides isolation. The `permissions.allow` list is
the broad read-only allowlist; the PreToolUse hook is the explicit gate for
external mutations.

### `claude-config/hooks/guard_writes.py`

Denylist style. Splits the bash command on `&&`, `||`, `;`, `|`, `&` and inspects
every sub-command. If any sub-command matches an external-mutation pattern, the
hook exits 1 with an explanation on stderr; otherwise exits 0.

This catches chains like `git status && git push` — the prefix `git status` is on
the auto-approve list, but the hook still flags the push.

Patterns matched (prompt the user):
- `git push …` and remote-mutating `git remote …`
- `gh pr create|merge|close|comment|review|edit|lock|unlock|ready|reopen`
- `gh issue create|close|comment|edit|lock|unlock|reopen|transfer|pin|unpin|delete`
- `gh release create|edit|delete|upload`
- `gh repo create|delete|edit|fork|sync|archive|unarchive|rename`
- `gh api -X POST|DELETE|PUT|PATCH`
- `gh secret|variable|workflow|ssh-key|gpg-key …`
- `gh auth login|logout|refresh`

### `claude-config/CLAUDE.md` and `claude-config/container-use-rules.md`

`container-use-rules.md` is populated by `scripts/fetch-claude-md.sh` from
`raw.githubusercontent.com/dagger/container-use/main/rules/agent.md`. Re-fetch
when upstream changes — the script overwrites only that file.

`CLAUDE.md` is hand-edited. Its first line is `@container-use-rules.md`, which
imports the upstream rules; everything below that is your own project-wide
instructions. Both files are bind-mounted into the container so the `@`-import
resolves at runtime.

### `claude-config/agents/`

Drop subagent definitions here. The directory is bind-mounted at
`/root/.claude/agents:ro` so agents can read but not modify them.

---

## Per-Project Container Use Configuration

Run once inside each project root. Container Use stores config in
`.container-use/environment.json` — commit this file so all worktrees share the
same baseline.

```bash
cd ~/projects/my-project
bash containerized/scripts/setup-project.sh
```

The script is **cwd-driven** with no positional args. It reads the current
directory: if cwd is itself a git repo it uses that as the primary; otherwise
it prompts to pick one of the cwd's git sub-folders, and registers the rest
as extra-repo setup commands (clone + `uv sync` if `uv.lock` is present).

What the script does:

1. `claude mcp add container-use -- container-use stdio` — register the MCP server.
2. `container-use config base-image set agent-base:latest`.
3. Bind-mounts:
   - **Config (read-only)** — from `containerized/claude-config/`:
     - `settings.json` → `/root/.claude/settings.json:ro`
     - `CLAUDE.md` → `/root/.claude/CLAUDE.md:ro`
     - `container-use-rules.md` → `/root/.claude/container-use-rules.md:ro`
     - `hooks/` → `/root/.claude/hooks:ro`
     - `agents/` → `/root/.claude/agents:ro`
   - **Claude subscription credentials (read-write)** — from `~/.claude/`:
     - `.credentials.json` → `/root/.claude/.credentials.json` (OAuth tokens, refresh)
     - `.claude.json` → `/root/.claude/.claude.json` (account state)
   - **uv wheel cache (read-write)** — `~/.cache/uv` → `/uv-cache` (uv's file lock makes concurrent use safe).
4. For each extra repo passed: setup commands `git clone --local /host-repos/<name>
   /workspace/<name>` and `cd … && uv sync`.
5. HTTPS git auth via `GITHUB_TOKEN` (credential helper).
6. Registers three secrets: `GITHUB_TOKEN`, `OPENAI_API_KEY`, `OPENCODE_API_KEY`
   (you'll be prompted if not in env). **`ANTHROPIC_API_KEY` is deliberately not
   set** — see Authentication below.

### What lives where in the container

```text
/root/.claude/
  settings.json            ← bind-mount from containerized/claude-config/        (ro)
  CLAUDE.md                ← bind-mount from containerized/claude-config/        (ro — hand-edited; @-imports rules below)
  container-use-rules.md   ← bind-mount from containerized/claude-config/        (ro — fetched from upstream)
  hooks/                   ← bind-mount from containerized/claude-config/hooks   (ro)
  agents/                  ← bind-mount from containerized/claude-config/agents  (ro)
  .credentials.json        ← bind-mount from ~/.claude/                          (rw — OAuth subscription)
  .claude.json             ← bind-mount from ~/.claude/                          (rw — account state)
  projects/, todos/, shell-snapshots/   ← ephemeral; discarded with `cu remove`

/workspace/
  repo-b/
    .venv/            ← created by uv sync, isolated per container
    pyproject.toml
    uv.lock
  repo-c/
    .venv/
    ...

/uv-cache/            ← bind-mount from ~/.cache/uv on host
```

### Authentication

- **Claude Code → host's Max/Pro/Team plan via OAuth.** `~/.claude/.credentials.json`
  and `~/.claude/.claude.json` are bind-mounted into every container, so all
  in-container Claude usage runs on your subscription rather than a metered API
  key. `ANTHROPIC_API_KEY` is deliberately **not** registered as a secret —
  Claude Code would auto-detect it and prefer it over the OAuth token, billing
  to the API key instead of the subscription.
  - The mounts are read-write because the OAuth access token refreshes
    periodically. Concurrent containers all bind-mount the same host file, so
    a refresh in one is visible to the others; the worst case is one container
    doing a redundant refresh, not a stuck session.
  - To run before any session: log in once on the host with `claude` so the
    credential file exists. `setup-project.sh` warns if it doesn't.
  - If you want metered API-key billing instead, comment out the two
    credential mounts in `setup-project.sh` and add
    `container-use config secret set ANTHROPIC_API_KEY`.
- **Codex CLI** uses `OPENAI_API_KEY` (registered as a Container Use secret).
- **opencode** uses `OPENCODE_API_KEY` for opencode-managed providers; if you
  configure it to call a different provider directly, that provider's key
  applies — see opencode docs.
- **`git push` / `gh`** operations use `GITHUB_TOKEN` via the credential helper.
  The PreToolUse hook still prompts before any external-mutation command
  regardless of token scope.

### GitHub fine-grained token

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Repository access: only the specific repos involved
3. Grant: **Contents** (read/write), **Pull requests** (read/write), **Issues** (read)
4. Do **not** grant: Administration, Secrets, Actions write, or org-level permissions

---

## Daily Workflow

### Pre-warm the uv cache (once, or after dependency changes)

```bash
bash containerized/scripts/pre-warm-uv-cache.sh ~/projects/repo-b ~/projects/repo-c
```

Populates `~/.cache/uv` on the host. Every new agent container's `uv sync`
reads from that bind-mounted cache and finishes in ~2s.

### Starting tasks

```bash
# Default agent: claude
agt add-unit-tests "Write unit tests for the auth module, targeting 80% coverage"

# Pick a specific agent per task
agt --agent codex    refactor-api "Refactor the API client in repo-b to use the retry logic from repo-c"
agt --agent opencode write-migration "Write the database migration for the users table"
```

### Monitoring

```bash
cu list                 # all active environments
cu watch <env-id>       # stream live output
cu log <env-id>         # full command history inside the container
```

### Reviewing and merging

1. Quick diff: `cu diff <env-id>`
2. Visual review in GitKraken — the branch shows up in the commit graph automatically
3. Merge:
   ```bash
   cu checkout <env-id>
   git merge feature/my-task --no-ff
   git push
   ```
4. Cleanup: `cu remove <env-id>` (destroys container, keeps branch)

### Absorbing agent improvements

If an agent installed something useful during its session:

```bash
container-use config show <env-id>    # inspect changes
container-use config import <env-id>  # promote to new project baseline
```

If the change belongs permanently in the base image, add it to
`Dockerfile.agent-base` and rebuild via `bash containerized/scripts/build-base-image.sh`.

---

## Orchestrating Agents with a Separate Claude Code Instance

### Option A — Agent Teams (built-in, experimental)

```bash
claude --enable-agent-teams -m "You are the team lead. Spawn 3 teammates:
  - one to add tests to repo-b
  - one to update the API client in repo-c
  - one to write the migration in repo-d
Coordinate via the shared task list and report when all three are done."
```

Teammates communicate via a shared mailbox and self-assign from a task list.
**Trade-off:** high token cost — each teammate is a full Claude instance.

### Option B — Shared coordination file + `cu` commands (lower cost)

Maintain a `coordination.md` in the project root:

```markdown
## Active Tasks
| task | env-id | status | branch | notes |
|------|--------|--------|--------|-------|
| add-tests | cu-abc123 | running | feature/add-tests | |
| refactor-api | cu-def456 | waiting-review | feature/refactor-api | |
```

The orchestrator reads `cu list` and `cu log <env-id>`, writes instructions to
`messages/<env-id>.md`, and calls `cu diff` to decide whether to merge. Lower
cost because the orchestrator uses tool calls rather than full conversation
contexts.

### Option C — `tmux send-keys` (zero overhead, any agent)

```bash
tmux send-keys -t "task-name" "Also add integration tests for the edge cases" Enter
```

---

## Isolation Summary

| Layer | Tool | What it isolates |
|---|---|---|
| Full environment isolation | Container Use (Docker) | Own filesystem, network namespace, all repos |
| Read-only auto-approve | `permissions.allow` in `claude-config/settings.json` | No prompt for `git status`/`git diff`/`gh ... view`/etc. — single commands and pipelines |
| External-mutation gate | `guard_writes.py` PreToolUse hook | Prompts before any `git push`, `gh pr create/merge`, `gh api POST/DELETE/PUT/PATCH`, … even when chained after an allowlisted prefix |
| Config tamper protection | `:ro` bind-mounts on `settings.json`, `CLAUDE.md`, `hooks/`, `agents/` | Agent cannot modify its own rules |
| Host/container config separation | `containerized/claude-config/` is the only **config** source | Settings, hooks, CLAUDE.md, agents are container-specific; host `~/.claude/` settings never apply inside the container |
| Subscription auth sharing | Host `~/.claude/.credentials.json` and `.claude.json` mounted (rw) | Claude Code in the container uses the host's Max/Pro/Team subscription; no API key is set |
| GitHub API scope | Fine-grained PAT | Token scoped to specific repos and operations |

---

## Tool Comparison

| Feature | GitKraken | Superset | Emdash | jmux | OpenCode |
|---|---|---|---|---|---|
| Worktree auto-creation | ✅ | ✅ | ✅ | ✅ | ❌ |
| Diff/review UI | ✅ best-in-class | ✅ built-in | ✅ side-by-side | ❌ delegates out | ❌ |
| Agent agnostic | ✅ | ✅ 10+ | ✅ 22+ | ✅ any CLI | ✅ |
| Best-of-N mode | ❌ | ❌ | ✅ | ❌ | ❌ |
| Issue tracker integration | ✅ GitHub/GitLab/Jira | ❌ | ✅ Linear/GitHub/Jira | ❌ | ❌ |
| Multi-repo support | ❌ | ❌ | ❌ | ❌ (--dir workaround) | ❌ |
| Linux/Ubuntu | ✅ | ✅ (from source) | ✅ | ✅ | ✅ |
| Built-in sandbox | ❌ | ❌ | ❌ | ❌ | ✅ gVisor |
| Overhead | Heavy (Electron) | Medium (Electron) | Medium (Electron) | Minimal (tmux) | Minimal (TUI) |

---

## Performance Notes

On Ubuntu (native Linux Docker — no hypervisor):

| Metric | Value |
|---|---|
| Container CPU overhead | ~0.3–0.6% |
| Container memory overhead | ~0.5–0.7% |
| Disk I/O with bind mounts | ~1–2% |
| Agent container ready time | ~10s (custom base image + warm uv cache) |

The agent spends the vast majority of its time waiting on LLM API responses.
Container and uv overhead are not bottlenecks.
