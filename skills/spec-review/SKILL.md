---
name: spec-review
description: Stage 4 of 4 of the /spec flow — run /process-reviews in a loop until every source is green, then (OpenSpec repos only) archive the change and push so the PR can merge. Normally dispatched by /spec; if the /spec context (BRANCH, CHANGE_ID, OPENSPEC, Linear issue) is not already loaded in this session, invoke the spec skill instead.
---

**Stage 4 of 4 of the `/spec` flow.** Prerequisite: `/spec` has run in this
session and established `BRANCH`, `CHANGE_ID`, `OPENSPEC`, and the full Linear
issue (body + comments), and the PR for `BRANCH` exists. If any of that is
missing, invoke the `spec` skill instead — it rehydrates and dispatches back
here. The `/spec` stopping policy applies throughout this stage.

## Step 1 — Review loop (batch local fixes; push only once per batch)

Do NOT re-run every gate after every micro-fix. Re-triggering the slow and
quota-limited flows (CI, CodeRabbit, the SonarCloud PR gate) costs a full push
each time. Batch fixes and verify them locally, then push once per batch.

**Run this loop autonomously — fix findings and push fix batches without asking.
The ONLY pauses are (a) a nontrivial design choice — a real fork with more than
one reasonable option, raised with PROS/CONS + a recommendation per the
symptom-vs-structural rule below — and (b) the Step 2 archive gate. A flagged
gate item is NEVER dismissed as "pre-existing": if a gate (Sonar, CI,
conventions, the type baseline, …) flags something on this PR — even on an old
line, an untouched file, or an issue with a months-old creation date — it is in
scope. Fix it, or, only for a genuine false positive, suppress it through that
gate's sanctioned channel with a written reason. "It predates my change" / "the
gate is still green overall" is NEVER a reason to skip a flagged item.**

Split the gates into two tiers:

- **Local gates** — fast, deterministic, need no push and no network trigger;
  run against the working tree / local diff:
  - full non-integration test suite (`poetry run pytest -m "not integration"`
    or the repo's equivalent) and the linter (ruff etc.);
  - conventions gate
    (`bash ~/.claude/skills/process-reviews/scripts/check-conventions.sh <PR>`).
    It checks the WHOLE of every touched file ON PURPOSE, to force each file you
    touch fully compliant. Fix every flagged line; never dodge it (moving code to
    another file, splitting tests out, …) and never offer a dodge as an option.
    Mechanical, assertion-preserving test fixes (hoisting imports or setup out of
    `pytest.raises`, splitting asserts, …) need no separate OK;
  - Codex on the local diff (`mcp__codex__codex`, read-only) — it analyses the
    working tree, so it needs no push;
  - local Sonar pre-check: `mcp__sonarqube__analyze_code_snippet` on each
    changed source file (single-file only — no cross-file, coverage, or
    duplication analysis, and deprecated; a fast pre-filter, NOT a substitute
    for the pushed SonarCloud gate);
  - `openspec validate <CHANGE_ID> --strict` (OpenSpec repos);
  - **living-architecture repos** (an `architecture/` directory at the repo
    root): the arc42 reads and normative-harness rules in the `spec` skill
    apply to every fix in this loop. Then the enforcement
    bundle — `tools/arch_check.py` (the one import law,
    model-truth at every declared granularity), LikeC4 model validation, and the
    type checker at its recorded baseline (see the `living-architecture` skill).
    The baseline is a RATCHET: NEVER re-record it (`--writebaseline`) to absorb
    errors the gate surfaces — ROOT-FIX them instead. A per-line
    `pyright: ignore[rule] — <reason>` counts as a solve ONLY when the checker
    is actually wrong (false positive) or the wrongness is deliberate (e.g. an
    invalid-input rejection test); otherwise fix the types. When a file you are
    touching carries pre-existing baselined errors that root-fix without much
    churn, fix those too — the baseline auto-shrinks on the next run; commit
    the shrink (only ever downward).
- **Remote gates** — slow and/or quota-limited; only a push produces them:
  CI (GitHub Actions), CodeRabbit, and the SonarCloud PR-decorated quality gate
  + new-issues count.

The loop:

1. **Initial full sweep.** Run `/process-reviews` to wait for and fetch the
   remote gates on the current pushed HEAD, and run every local gate. This is
   the complete failing set.
2. **Local fix sub-loop — NO push.** Fix the failures, then re-run (a) the
   specific gates that failed AND (b) every local gate above — INCLUDING a
   fresh full-PR Codex pass over the fixed working tree (Codex is a local
   gate: it reads the working tree, so a pre-push run costs no CI cycle;
   include uncommitted changes via `git diff origin/<base>`). Do NOT push and
   do NOT re-trigger CI / CodeRabbit / SonarCloud in this sub-loop. Repeat
   until ALL local gates converge on the same tree state — tests, linter,
   conventions, Sonar pre-check, openspec/enforcement bundle green AND Codex
   returning no new valid findings. NEVER push a fix Codex has not reviewed —
   a gap in the fix itself otherwise ships and costs a full extra CI round.
3. **Push once.** Only after step 2 has fully converged (Codex included),
   commit and push — this re-triggers the remote gates a single time for the
   whole batch. Never push while a question to me is pending (or about to be
   asked) — ask first, push after I answer, even if the batch excludes the
   disputed change.
4. **Full remote sweep.** Run `/process-reviews` again to wait for + fetch every
   remote gate on the new HEAD (it also re-runs Codex). Any new failure sends
   you back to step 2, then step 3. Repeat until one full push cycle returns
   every source green with nothing left to fix.

**"Green" for CI means an actually-COMPLETE, PASSING run — every check finished
with a pass conclusion.** "No *failed* checks" is NOT green while any check is
still QUEUED / IN_PROGRESS, and `wait-for-reviews` printing "gate clear" only
means the checks it saw were terminal at that poll — it can fire before slow
jobs (the full test matrix, integration/example jobs) even start or finish.
Before treating CI as green, confirm EVERY check shows `pass` (e.g.
`gh pr checks <PR>`). NEVER declare convergence on an incomplete or
still-running CI run.

Use `/process-reviews` for the remote sweeps (steps 1 and 4) — it owns the
wait-for-settle + fetch of CI/CodeRabbit/Sonar and the Codex pass. Run the local
sub-loop (step 2) directly against the working tree; do not invoke
`/process-reviews` there (its gate-poll is about remote state you have not
re-triggered yet).

**Symptom vs. structural cause — decide before you patch.** For EACH valid
finding, before writing the fix, ask whether it is merely a *symptom* of a
deeper structural issue and whether a *structural* fix would be more correct
than a local band-aid — judged against the principles/axioms in the
`architecture/**/*.arc42.md` files (a band-aid that leaves an axiom-violating
shape standing, a bug that recurs because two code paths must agree by hand, a
missed-normalization that a single canonical representation would obviate, etc.
are all tells). When a structural fix appears warranted, STOP and present the
case to me — the symptom, the structural cause, the band-aid vs. structural
options with PROS/CONS, the arc42 grounding, and your RECOMMENDATION — then wait
for my call (this is the design-decision pause permitted by the `/spec` stopping
policy). If the finding is genuinely local with no structural cause, just fix
it. Never silently ship a band-aid over a structural problem, and never
undertake a large structural refactor without my go-ahead.

**Convergence also requires zero dangling CodeRabbit threads.** Before the loop
counts as done, every unresolved CR thread — including ones opened *before* the
latest commit that are still open — must have a reply: either why-won't-fix, or
a pointer to the commit that already fixed it. Use the `reply-to-pr-thread` /
`reply-invalid-coderabbit` channel; never resolve the thread yourself. A
fixed-but-unreplied thread reads as unaddressed to the human reviewer and keeps
CodeRabbit from re-evaluating, so "all sources green" alone is not enough.

**Hard rule — reply to every CR thread CodeRabbit has not resolved after the next
commit's CI.** At EVERY remote sweep, list ALL CodeRabbit threads on the PR,
including outdated ones and ones from reviews several commits back. Any thread that
CodeRabbit has still not marked resolved once CI has completed on a commit pushed
AFTER the thread was opened MUST get a reply in that sweep. Say which later commit(s)
fixed it (SHA plus a one-line how and the test that pins it), or why no fix was or
will be made. Start every such reply with `@coderabbitai` so CodeRabbit re-evaluates
the thread. A thread you already replied to that CodeRabbit left unresolved after a
later CI run needs a new reply that answers its latest comment. Never skip a thread
because it is outdated, old, or was "already addressed" in a commit message; the
reply on the thread is the only record that counts. Review-summary nitpicks are
exempt: never reply to them.

## Step 2 — Archive the OpenSpec change, then I merge (OpenSpec repos only)

Skip unless `OPENSPEC=1`. **Archiving is the ONE action that ALWAYS needs my
fresh, explicit say-so. It is NEVER covered by any "keep going until clean" /
"don't ask unless there's a design choice" autonomy I grant — that autonomy is
for the fix loop (fixing findings, pushing fix batches) and STOPS at the archive.
Do NOT archive on your own judgment, ever, even when every gate is green.** Once
the Step 1 loop has CONVERGED — every source ACTUALLY green (CI a complete
passing run per the definition above, Sonar, CodeRabbit, Codex, conventions) — do
NOT archive: STOP, tell me the loop is clean, and ASK my permission to archive.

**Before offering to archive, the branch MUST include the PR's base.** If
`git merge-base --is-ancestor origin/<base> HEAD` is false, merge it in
(`git merge origin/<base>`, never rebase), re-run the Step 1 loop on the merged
tree, and push. This is autonomous — do it without asking. Archiving a stale
branch bakes an out-of-date corpus into the merge.

**Before you offer to archive, verify `openspec/changes/<CHANGE_ID>/tasks.md`
has no unchecked `- [ ]` items.** `openspec archive` only *warns* on incomplete
tasks and continues under `--yes`, so a silent gap would ship. For each
unchecked task: tick it if the work is already done (a gate/verification task
you ran during the loop but never ticked is a common cross-session miss — tick
it), do it if it is real remaining work, or — if it was deliberately deferred —
strike it with a one-line pointer to the issue it moved to. Do NOT offer to
archive while a genuinely-incomplete task remains: surface the list to me and
resolve it first, and when you do offer, report which unchecked tasks you ticked
as already-done.

Only on my explicit go-ahead run:

```
openspec archive <CHANGE_ID> --yes
```

and commit + push the result as the final commit on the PR branch; I merge the PR
immediately after. Archiving pre-merge (NOT post-merge) lands the corpus update
atomically with the code in the same PR — the archive commit re-triggers CI, but
it is docs-only (`openspec/**`) so it settles fast.

This merges the delta into `openspec/specs/` (ADDED appended, MODIFIED replaced,
REMOVED deleted) and moves the change to
`openspec/changes/archive/YYYY-MM-DD-<CHANGE_ID>/`. Commit the result with
specific `git add` of the changed `openspec/specs/**` and the moved folder. This
is the one step that keeps the behaviour corpus current — everything upstream is
best-effort authoring; `validate` (in `spec-plan`) and `archive` here are
the deterministic guarantees.
