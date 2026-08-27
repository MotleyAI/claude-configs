---
name: spec
description: Guide for creating better specs for tasks I give to an agent. Always pulls in the Linear issue whose `gitBranchName` matches the current git branch exactly, and combines it with whatever I type when invoking the skill.
---

I want a detailed spec. The brief is the union of:
1. The Linear issue tied to the current branch (see Step 1), AND
2. Whatever I just typed when invoking this skill.

## Step 1 — Pull in the Linear issue for the current branch

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
   - When `OPENSPEC=0`, skip every step below marked *"OpenSpec repos only."*

## Step 2 — Combine and interview

Treat the Linear issue body + comments AND whatever I typed in this turn as
the combined brief. In case of conflict, what I typed has higher priority but ask to be sure. 

Interview me in detail.
Cover implementation approach, edge cases, gotchas, design choices, tradeoffs, and constraints.
Skip obvious questions.
Ask one at a time and build on my answers.

**IMPORTANT — WHENEVER you ask me to make a choice, you MUST give, for the
decision, explicit PROS and CONS of each option AND a clear RECOMMENDATION of
which one you'd pick and why. This is non-negotiable. Never present options as
a bare menu. If you use a structured/multiple-choice prompt, spell out the
pros, the cons, and the recommendation inside it — do not rely on a one-line
description to carry them.**

When you think you have enough information, return a detailed, complete spec.
In the spec you write, NEVER take shortcuts or make simplifications or
extensions to the original requirements without asking me about each one first.

## Step 3 — Codex review of the plan

Once I've approved the spec/plan, hand the plan text to the codex MCP server
(`mcp__codex__codex`) and ask it to review the plan itself — not a diff —
focusing on correctness of approach, missed edge cases, risky design choices,
test coverage gaps, and anything that contradicts the Linear issue. Codex
should not modify files; it should return actionable findings.

Bring Codex's findings back to me and discuss them. For each finding, decide
together whether to fold it into the plan, defer it, or reject it. Update the
written spec to reflect the resolved decisions before moving on.

## Step 3b — Emit the OpenSpec change (OpenSpec repos only)

Skip this whole step unless `OPENSPEC=1` (Step 1). Turn the approved,
Codex-resolved plan into an OpenSpec change — but do NOT hand-author the files
from memory. OpenSpec ships authoritative, version-correct, per-artifact
instructions; follow them so the output passes `validate --strict`.

1. **Scaffold:** `openspec new change <CHANGE_ID>` (creates
   `openspec/changes/<CHANGE_ID>/.openspec.yaml`; artifacts are added next).
2. **Author each artifact in dependency order** — proposal → specs → design →
   tasks. For each, run `openspec instructions <artifact> --change <CHANGE_ID>`
   and obey the emitted `<instruction>` + `<template>`, writing to the `<output>`
   path it names. `openspec status --change <CHANGE_ID>` shows what's done/blocked.
   Most of this is a reformat of the plan — don't re-derive it:
   - **proposal.md** — `## Why` + `## What Changes` (from the Linear issue +
     plan), plus `## Capabilities` (New/Modified — this list decides which delta
     files must exist) and `## Impact`.
   - **specs/<capability-path>/spec.md** (the delta — the crux) — one file per
     capability from the proposal, using `## ADDED` / `## MODIFIED` / `## REMOVED`
     / `## RENAMED Requirements`. Each requirement is `### Requirement: <name>` in
     SHALL/MUST language with **≥1** `#### Scenario:` in WHEN/THEN form. Validator
     gotchas: scenarios need **exactly four** `#` (three or bullets fail
     silently); MODIFIED must contain the FULL updated requirement; REMOVED needs
     **Reason** + **Migration**; RENAMED uses FROM:/TO:. These scenarios ARE the
     Step 4 acceptance criteria.
   - **design.md** — only for non-obvious design (the Codex-resolved decisions);
     skip if there's nothing to say.
   - **tasks.md** — the `- [ ]` checklist that also drives Steps 4/6; maintain it
     here, not twice.
3. **No spec-level behaviour change?** (pure refactor, tooling, docs, or a fix
   that doesn't alter specified behaviour) — do NOT invent a requirement; set
   `skip_specs: true` in `openspec/changes/<CHANGE_ID>/.openspec.yaml`. Specs
   describe behaviour, so if behaviour doesn't change, no spec should.
4. **Gate before writing any tests:**

   ```
   openspec validate <CHANGE_ID> --strict
   ```

   Fix until green. This catches a malformed plan and — crucially — any MODIFIED
   requirement that no longer lines up with the current corpus (spec drift), at
   plan time, for free.

## Step 4 — Write the tests first

Following the TDD-style memory (`feedback_tdd_style.md`): land the **full**
test suite for the agreed plan before writing any implementation. Tests
should fail for the right reason (feature missing), not for setup reasons.

If `OPENSPEC=1`, derive the test cases from the delta scenarios in
`openspec/changes/<CHANGE_ID>/specs/<capability>/spec.md` (Step 3b): every
`#### Scenario:` needs at least one covering test.

## Step 5 — Codex review of the tests against the plan

Hand both the plan (from Step 3, post-discussion) and the new tests to
`mcp__codex__codex` and ask it to verify that the tests faithfully cover the
plan: every behavior in the plan has at least one test, edge cases discussed
in Step 3 are exercised, and no test asserts behavior that contradicts the
plan. Codex should not modify files.

Bring the findings back to me. Adjust the tests (add, remove, or fix) based
on what we agree on before writing implementation.

If `OPENSPEC=1`, "the plan" includes the delta specs: verify every ADDED/MODIFIED
requirement and each of its scenarios has a covering test.

## Step 6 — Implement until tests pass

Implement the plan. Run the full non-integration test suite (per
`feedback_unit_tests_only.md`) after changes and fix any failures. Do not
declare done until every test from Step 4/5 passes.

If `OPENSPEC=1`, tick off `openspec/changes/<CHANGE_ID>/tasks.md` as you complete
each task (the same checklist from Step 3b — this is the `apply` phase, driven by
TDD here instead of `/opsx:apply`).

When writing code AND tests (Steps 4 and 6), follow the `concise-comments`
skill: no design essays, ticket-ID-on-every-line, or code-restating comments;
docstrings to a line. Rationale belongs in the spec / PR description / this
issue — not in code — so verbose comments never get written in the first place.

## Step 7 — Ask me to commit, push, and PR

Once all tests pass, stop and ask me whether to commit, push, and open a PR.
Do not do any of these on your own — wait for my go-ahead, then follow the
standard commit/PR workflow (specific `git add` for each new file, never
`git add -A`).

If `OPENSPEC=1`, the whole `openspec/changes/<CHANGE_ID>/` folder is part of the
change — `git add` it explicitly alongside the code (proposal, design, tasks,
delta specs). Put `openspec diff <CHANGE_ID>` in the PR description so reviewers
see the spec surface change. Do NOT archive yet — that happens post-merge
(Step 8).

After you've done executing the plan, call /process-reviews in a loop until there are no more issues to fix.

## Step 8 — Archive the OpenSpec change (OpenSpec repos only, AFTER the PR merges)

Skip unless `OPENSPEC=1`. Archiving folds the delta into the living spec corpus,
so it must run only once the change is merged/deployed — never at spec time. When
the PR is merged (i.e. after the Step 7 `/process-reviews` loop settles and I've
merged), run:

```
openspec archive <CHANGE_ID>
```

This merges the delta into `openspec/specs/` (ADDED appended, MODIFIED replaced,
REMOVED deleted) and moves the change to
`openspec/changes/archive/YYYY-MM-DD-<CHANGE_ID>/`. Commit the result with
specific `git add` of the changed `openspec/specs/**` and the moved folder. This
is the one step that keeps the behaviour corpus current — everything upstream is
best-effort authoring; `validate` (Step 3b) and `archive` here are the
deterministic guarantees.