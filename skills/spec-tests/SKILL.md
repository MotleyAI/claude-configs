---
name: spec-tests
description: Stage 2 of 4 of the /spec flow — write the full failing test suite for the agreed plan (TDD-first), then Codex-review the tests against the plan. Normally dispatched by /spec; if the /spec context (BRANCH, CHANGE_ID, OPENSPEC, Linear issue) is not already loaded in this session, invoke the spec skill instead.
---

**Stage 2 of 4 of the `/spec` flow.** Prerequisite: `/spec` has run in this
session and established `BRANCH`, `CHANGE_ID`, `OPENSPEC`, and the full Linear
issue (body + comments). If any of that is missing, invoke the `spec` skill
instead — it rehydrates and dispatches back here. The `/spec` stopping policy
applies throughout this stage.

Before writing anything, recover the durable plan from `spec-plan`:
- `OPENSPEC=1` — read the whole change folder
  `openspec/changes/<CHANGE_ID>/` (proposal, design, tasks, delta specs).
- `OPENSPEC=0` — the finalized plan is a comment on the Linear issue.

## Step 1 — Write the tests first

Following the TDD-style memory (`feedback_tdd_style.md`): land the **full**
test suite for the agreed plan before writing any implementation. Tests
should fail for the right reason (feature missing), not for setup reasons.

If `OPENSPEC=1`, derive the test cases from the delta scenarios in
`openspec/changes/<CHANGE_ID>/specs/<capability>/spec.md`: every
`#### Scenario:` needs at least one covering test.

When writing tests, follow the `concise-comments` skill: no design essays,
ticket-ID-on-every-line, or code-restating comments; docstrings to a line.
Rationale belongs in the spec / PR description / the Linear issue — not in
code — so verbose comments never get written in the first place.

## Step 2 — Codex review of the tests against the plan

Hand both the plan (from `spec-plan`, post-discussion) and the new tests
to `mcp__codex__codex` and ask it to verify that the tests faithfully cover
the plan: every behavior in the plan has at least one test, edge cases
discussed during the plan review are exercised, and no test asserts behavior
that contradicts the plan. Codex should not modify files.

Bring the findings back to me. Adjust the tests (add, remove, or fix) based
on what we agree on before writing implementation.

If `OPENSPEC=1`, "the plan" includes the delta specs: verify every ADDED/MODIFIED
requirement and each of its scenarios has a covering test.

## Step 3 — Commit the changed files

Once the tests are finalized (Step 2 findings resolved), `git add` every file
this stage created or changed — by specific named path — then commit them. This
is the full set: new test modules and their fixtures/helpers, plus any file this
stage only **modified** (a flipped existing test, a reworded docstring, an
amended golden `ALLOWED_DELTAS`, an approved plan/spec edit). Per the `/spec`
"commit at the end of every stage" rule, do this **without asking**. Rules that
still hold:

- NEVER `git add -A` / `git add .` / `git add tests/` — only specific named
  paths. Listing several named paths in one `git add` command is fine; a bulk
  add (all files, `.`, or a directory) is not.
- Do NOT push — pushing waits for the `spec-implement` go-ahead gate.

## Step 4 — Hard stop

> **🛑 HARD STOP (reset point 2 of 3) — before implementation.** The finalized
> failing tests, and every other file this stage created or changed, are
> committed. Say we're at reset point 2 and STOP — do not start implementing.
> I'll `/clear` and re-invoke `/spec`, which will detect and run `spec-implement`.
