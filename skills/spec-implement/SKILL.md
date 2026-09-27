---
name: spec-implement
description: Stage 3 of 4 of the /spec flow — implement until every test from the spec-tests stage passes, then with my explicit go-ahead commit, push, and open the PR. Normally dispatched by /spec; if the /spec context (BRANCH, CHANGE_ID, OPENSPEC, Linear issue) is not already loaded in this session, invoke the spec skill instead.
---

**Stage 3 of 4 of the `/spec` flow.** Prerequisite: `/spec` has run in this
session and established `BRANCH`, `CHANGE_ID`, `OPENSPEC`, and the full Linear
issue (body + comments). If any of that is missing, invoke the `spec` skill
instead — it rehydrates and dispatches back here. The `/spec` stopping policy
applies throughout this stage.

Before writing anything, recover the durable plan (the
`openspec/changes/<CHANGE_ID>/` folder when `OPENSPEC=1`, else the plan
comment on the Linear issue) and the failing tests already on disk from
`spec-tests`.

## Step 1 — Implement until tests pass

Implement the plan. Run the full non-integration test suite (per
`feedback_unit_tests_only.md`) after changes and fix any failures. Do not
declare done until every test from the `spec-tests` stage passes.

**Symptom vs. structural cause — decide before you patch.** The plan already
chose between a band-aid and a structural fix; implement the structural shape
it chose, and do not quietly degrade it into instance patches to get tests
green faster. If, while implementing, a test failure or the code itself
reveals that the planned fix is a band-aid after all — the same change must be
repeated in N places, two code paths have to agree by hand, a missed
normalization that a single canonical representation would obviate, an
axiom-violating shape left standing (judged against the principles/axioms in
the `architecture/**/*.arc42.md` files) — STOP and present the case to me: the
symptom, the structural cause, the band-aid vs. structural options with
PROS/CONS, the arc42 grounding, and your RECOMMENDATION (leaning structural —
a bigger diff is an acceptable cost). Wait for my call (this is the
design-decision pause permitted by the `/spec` stopping policy). If the
failure is genuinely local with no structural cause, just fix it. Never
silently ship a band-aid over a structural problem, and never undertake a
large structural refactor the plan did not include without my go-ahead.

Intermediate local commits during implementation are fine within reason — e.g.
to merge origin/main before editing, or to checkpoint a coherent working state.
Keep them tidy (specific `git add`, never `git add -A`); they can be reorganized
before the push. The go-ahead gate in Step 3 governs **pushing** and **opening
the PR**, not every local commit.

If `OPENSPEC=1`, tick off `openspec/changes/<CHANGE_ID>/tasks.md` as you complete
each task (the same checklist authored in `spec-plan` — this is the
`apply` phase, driven by TDD here instead of `/opsx:apply`).

When writing code, follow the `concise-comments` skill: no design essays,
ticket-ID-on-every-line, or code-restating comments; docstrings to a line.
Rationale belongs in the spec / PR description / the Linear issue — not in
code — so verbose comments never get written in the first place.

## Step 2 — Conventions gate (before commit)

Once the suite is green, run the SAME deterministic conventions gate
`/spec-review` uses, so CodeRabbit/Sonar don't have to redo it and the first
push is already clean. There is no PR yet at this stage, so diff against the
default branch with `--base`:

```
bash ~/.claude/skills/process-reviews/scripts/check-conventions.sh --base <default-branch>
```

(call it BARE — the script is in `sandbox.excludedCommands`, so it gets network
automatically; passing `dangerouslyDisableSandbox: true` is what forces a
permission prompt, and the base fetch is a no-op when the default branch is
already current locally). It
AST-checks every `.py` file this change touches (whole file, committed ∪
working tree) for `[import-not-top]` (no imports inside functions/classes; a
`TYPE_CHECKING` / optional-dep `try:` wrapper is fine) and `[text-ratio]`
(docstring/comment-only lines ≤15% of total, aggregated separately over the
change's test files and its source files). Exit 0 = clear, 1 = RED.

This is a HARD GATE: do not proceed to Step 3 while it is RED. Fix every
finding — hoist the flagged imports, and trim comments/docstrings in the
flagged file group per `concise-comments` (internal engine/sql/core files
carry the bulk; leave outward-facing MCP/CLI/OpenAPI docstrings alone) until
the ratio fits. Per the global CLAUDE.md rule, an `import-not-top` waiver
(`# ALLOW(import-not-top): <reason>`) is only for a genuine circular/optional
import and must be confirmed with me BEFORE landing it. Re-run until green.

## Step 3 — Ask me to push and open the PR

Once all tests pass AND the conventions gate is green, stop and ask me whether
to push and open a PR (folding in any final commit of the implementation).
Intermediate local commits along the way were fine (Step 1), but **pushing** and
**opening the PR** need my explicit go-ahead — do not do either on your own.
Then follow the standard commit/PR workflow (specific `git add` for each new
file, never `git add -A`).

If `OPENSPEC=1`, the whole `openspec/changes/<CHANGE_ID>/` folder is part of the
change — `git add` it explicitly alongside the code (proposal, design, tasks,
delta specs). Do NOT archive yet — that happens once the review loop has
converged, just before I merge (`spec-review`).

**Always merge the PR's destination branch before creating the PR.** After
committing and before the push, bring the PR's envisioned base branch (the branch
the PR will target — usually `main`) into `BRANCH`, so the PR opens against, and
CI runs on, the current destination rather than a stale base: `git fetch origin
<base>` then `git merge origin/<base>`. Commit any local changes first, then
merge — NEVER stash, NEVER rebase (per my global rules); the merge message's
first line must name the merged ref in single quotes, e.g. `Merge branch
'origin/main' into <BRANCH>`. Resolve any conflicts, re-run the local gates
(full non-integration suite + conventions) on the merged tree, and only then
push and `gh pr create`. If the base has not advanced since your last merge the
merge is a no-op — proceed straight to the push.

**Write the PR description for a human reader**, not as a spec dump. Concise but
complete prose: what the change does and why, the user-facing behaviour it adds
or changes, and — where it makes the change concrete — a short runnable example
or two (a query plus what it now returns, or a before/after). Cover anything a
reviewer needs to understand and evaluate the change; skip what they don't.
Do NOT paste `openspec show --diff`, the raw delta specs, or the tasks
checklist — the change folder is committed in this PR, so whoever wants the full
spec surface reads it there. Link the Linear issue.

## Step 4 — Hard stop

> **🛑 HARD STOP (reset point 3 of 3) — just after the PR is created.** Code,
> tests (green, conventions gate clean), and the change folder are committed and
> the PR exists. Say we're at reset point 3 and STOP — do not start the review
> loop. I'll `/clear` and re-invoke `/spec`, which will detect and run
> `spec-review`.
