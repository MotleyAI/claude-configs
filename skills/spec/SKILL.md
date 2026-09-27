---
name: spec
description: Guide for creating better specs for tasks I give to an agent. Always pulls in the Linear issue whose `gitBranchName` matches the current git branch exactly, and combines it with whatever I type when invoking the skill. Rehydrates context, detects the current stage, and dispatches to the stage skills spec-plan → spec-tests → spec-implement → spec-review.
---

I want a detailed spec-driven flow. The brief is the union of:
1. The Linear issue tied to the current branch (see "Rehydrate" below), AND
2. Whatever I just typed when invoking this skill.

## The four stages

The flow runs as four stage skills in this fixed order, and I reset the
session (`/clear`) between stages. Each stage ends at a hard stop; everything
a fresh session needs is on disk or in Linear, so any stage can resume from
just the branch name:

1. **`spec-plan`** — interview me, Codex-review the plan, emit the
   OpenSpec change (OpenSpec repos only), make the plan durable.
   Ends at 🛑 reset point 1 (before tests).
2. **`spec-tests`** — write the full failing test suite for the plan,
   Codex-review the tests against the plan.
   Ends at 🛑 reset point 2 (before implementation).
3. **`spec-implement`** — implement until every test passes, then (with my
   go-ahead) commit, push, and open the PR.
   Ends at 🛑 reset point 3 (just after the PR is created).
4. **`spec-review`** — run `/process-reviews` until converged, then
   archive the OpenSpec change (OpenSpec repos only) so I can merge.

This skill does NO stage work itself. It only: rehydrates context (below),
detects which stage we're at, and invokes that stage's skill via the Skill
tool. Run exactly ONE stage per session — when its hard stop is reached, STOP;
never chain into the next stage, even if it looks quick.

## Stopping policy

Each stage skill ends with its own **hard stop** so I can reset your context.
At a hard stop: say which reset point we're at, then STOP and wait — do not
start the next stage. I'll `/clear` and re-invoke `/spec` (possibly with
"continue on branch `<BRANCH>`"); rehydration + stage detection below take it
from there.

**Within a stage, run autonomously — do NOT stop or ask permission to
proceed.** The only other permitted pauses are:
- the **`spec-plan` interview** (its whole point is questioning me);
- a **nontrivial design decision** — a real fork with more than one reasonable
  option — raised with explicit PROS/CONS + RECOMMENDATION (per the interview
  rule in `spec-plan`). A choice with an obvious default is NOT this:
  take the default and move on;
- the standing **go-ahead gate before push/PR** (`spec-implement`), per my
  global rules;
- a **suspected unrelated gap** — a failure, restriction, or missing capability
  that looks pre-existing or outside this change's scope (a bind-level refusal, an
  allowlist, a fixture that cannot express a scenario, …). Whether it is unrelated
  and what to do about it is MY call, never yours: STOP and ask, presenting what
  you found, the existing Linear issues you searched for (search first, cite ids
  and titles), and the options (treat as in-scope / xfail against an EXISTING issue
  / narrow the scenario) with a recommendation. NEVER create a Linear issue, mark a
  scenario xfail, or narrow a scenario on your own to route around it — even when a
  tasks.md line or an earlier plan says "file its own issue".

Never stop just to report progress, to confirm an obvious next step, or to ask
something you can determine yourself.

## The plan is frozen once spec-plan ends

The plan — the OpenSpec change folder (proposal, design, tasks, delta specs) or,
without OpenSpec, the finalized-plan comment on the Linear issue — is MINE once
`spec-plan` reaches its hard stop. In EVERY later stage, NEVER change it without
my explicit confirmation of the exact edit: no added or amended decisions, no
rewritten or added scenarios, no "corrections" after a probe, no re-scoping, no
notes folded into tasks. If a stage finds the plan wrong, incomplete, or
contradicted by an axiom or a probe, STOP, present the exact proposed diff with
the reason, and wait. The one self-serve edit is flipping a task's `[ ]` to `[x]`
when it was completed exactly as written.

## Nothing the next stage needs lives in chat

Sessions `/clear` between stages, so the stop message reaches no future stage.
Anything the next stage must know therefore has to be **persisted where that
stage will discover it naturally** during its own rehydration and work — NEVER a
turn-final "heads-up", "note for next time", "FYI for spec-implement", or a
caveat tacked onto the stop message. Such text is gone the instant I `/clear`, so
it only masquerades as a hand-off. If you catch yourself about to write one,
STOP and put it in one of these instead:

- **tasks.md** — an open sub-task, a gotcha, or a calibration note on a step
  (the next stage works through this file);
- **design.md / proposal.md / the spec delta** — a decision, rationale, or a
  constraint on how something must be built;
- **the Linear issue** — the spec in the body, resume state and probe outcomes
  in a handoff comment;
- **the code itself** — a test's assertions plus a terse comment, or a
  forward-pointer issue (per my global rules) — for anything about how the code
  must behave.

A hard stop then states only which reset point we're at: everything the next
stage needs is already on disk or in Linear, by construction.

## Commit at the end of every stage

At each stage's hard stop — after the stage's work is done, just before you
STOP — commit the files that stage created or changed, **without asking**. This
is a `/spec`-flow override of my global "don't commit, I'll commit" / "ask me
each time" rules, and it supersedes any "do NOT commit" wording in the stage
skills. What still holds:

- Stage with **specific named paths** (`git add <path>`, one at a time) — NEVER
  `git add -A`, `git add .`, or a whole directory.
- **Commit only** — pushing and opening the PR still need my explicit go-ahead
  (`spec-implement` Step 3 / the stopping policy above); the end-of-stage
  commit does not.

## Normative harnesses (living-architecture repos)

In a repo with an `architecture/` directory at its root,
`architecture/**/*.arc42.md` and `architecture/**/*.c4` files are normative
harnesses, exactly like tests. This applies at EVERY stage of the flow —
planning, writing tests, implementing, and fixing review findings:

- **Read them first.** Before doing the stage's work, read
  `architecture/index.yaml` plus **every** `*.arc42.md` file relevant to the
  modules the change touches — the node file of each touched node AND
  `system.arc42.md` (cross-cutting principles) — plus the LikeC4 view of every
  touched node (see the `living-architecture` skill).
- **Obey them.** Every plan, test, implementation, and review fix MUST obey the
  node principles and the model's import law — or explicitly include the
  model + arc42 update as part of the change.
- **Flag, never deviate.** If anything in an arc42 file seems wrong,
  contradictory, or makes the task impossible or substantially harder, FLAG IT
  TO ME EXPLICITLY and wait for my call — NEVER silently deviate from,
  reinterpret, or ignore a principle, and never produce work that quietly
  conflicts with one.
- **Keep them normative and minimal.** When work strains a principle, first make
  the code comply; propose an edit only when the principle genuinely forbids
  something needed, in the smallest general wording — never descriptive text or
  implementation detail (function names, mechanisms).
- **Never edit without per-change approval.** NEVER create, modify, or delete
  one without my explicit approval for each specific change — present the
  exact edit and wait for my OK. A broader approved plan that mentions the
  edit does NOT count; the concrete edit itself needs the OK.

## Rehydrate — pull in the Linear issue for the current branch

Look up the Linear issue whose `gitBranchName` equals the current git branch
**exactly**. I create branches by clicking "Copy git branch name" in the
Linear issue UI and `git checkout -b`-ing them, so the local branch name is
byte-equal to the issue's `gitBranchName`. That equality is the join key.

1. Capture `BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
2. Try the cheap path first: Linear's auto-generated branch name is
   `<user>/<lowercased-key>-<title-slug>` (e.g.
   `egor/dev-1330-slayer-storage-...`). Pull out the `<key>` chunk
   (`dev-1330`), uppercase it (`DEV-1330`), and call
   `mcp__linear__get_issue(id="DEV-1330")`.
3. If that returns an issue **and** the returned issue's `gitBranchName`
   equals `BRANCH` exactly, use it. Otherwise fall back to
   `mcp__linear__list_issues(team="DEV", query="<key-or-slug>",
   includeArchived=false)` and walk the results, comparing each issue's
   `gitBranchName` to `BRANCH`. Pick the unique exact match.
4. If 0 exact matches: tell me no DEV issue maps to this branch and ask
   whether to proceed with only my typed input as the brief. If >1 exact
   matches: list them and ask which one.
5. Once a match is confirmed, read the issue body in full
   (`mcp__linear__get_issue` already returns it) plus any comments via
   `mcp__linear__list_comments`.
6. **Set the change-id and resolve OpenSpec.** `CHANGE_ID` = `$BRANCH` with any
   leading `<user>/` segment stripped (Linear's copied branch names look like
   `egor/dev-1330-slayer-storage`, so `CHANGE_ID=dev-1330-slayer-storage`). This
   keeps Linear issue ↔ git branch ↔ OpenSpec change 1:1:1. Then resolve OpenSpec:
   - If an `openspec/` directory exists at the repo root and it's healthy, set
     `OPENSPEC=1`.
   - If `openspec/` is **absent or invalid**, ask me whether to initialize this
     repo for OpenSpec now (one-time) or run this change without it. If yes,
     invoke the **`openspec-init`** skill (it resolves the CLI and scaffolds the
     corpus), then set `OPENSPEC=1`. If no, set `OPENSPEC=0`.
   - When `OPENSPEC=0`, skip everything marked *"OpenSpec repos only"* in the
     stage skills.

## Detect the stage

Work out which stage this session should run — first match wins:

1. **Open PR for `BRANCH`?** Check with `gh pr view --json state,url`
   (`gh` runs sandboxed like everything else). If an open PR
   exists → **`spec-review`**.
2. **No durable plan yet?** The plan is durable iff:
   - `OPENSPEC=1`: `openspec/changes/<CHANGE_ID>/` exists and
     `openspec validate <CHANGE_ID> --strict` passes; or
   - `OPENSPEC=0`: the Linear issue has a comment containing the finalized
     plan.
   If not durable → **`spec-plan`**.
3. **No tests for this change yet?** Look for test files added/changed for
   this change: the working tree (`git status`) plus commits since the
   merge-base with the default branch
   (`git diff --name-only $(git merge-base HEAD <default-branch>)..HEAD`).
   If none → **`spec-tests`**.
4. **Otherwise** → **`spec-implement`** (plan and tests exist, no PR yet;
   this stage also covers the "all tests already pass, awaiting my
   commit/push/PR go-ahead" case).

If the evidence is ambiguous (e.g. test files changed but they don't obviously
belong to this change), say what you found and ask me which stage to run.

## Dispatch

Tell me in one line which stage was detected and why, then invoke that stage's
skill via the Skill tool and follow it to its hard stop. If I explicitly named
a stage when invoking `/spec`, that overrides detection.
