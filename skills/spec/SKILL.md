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

## Step 2 — Combine and interview

Treat the Linear issue body + comments AND whatever I typed in this turn as
the combined brief. In case of conflict, what I typed has higher priority but ask to be sure. 

Interview me in detail.
Cover implementation approach, edge cases, gotchas, design choices, tradeoffs, and constraints.
Skip obvious questions.
Ask one at a time and build on my answers.
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

## Step 4 — Write the tests first

Following the TDD-style memory (`feedback_tdd_style.md`): land the **full**
test suite for the agreed plan before writing any implementation. Tests
should fail for the right reason (feature missing), not for setup reasons.

## Step 5 — Codex review of the tests against the plan

Hand both the plan (from Step 3, post-discussion) and the new tests to
`mcp__codex__codex` and ask it to verify that the tests faithfully cover the
plan: every behavior in the plan has at least one test, edge cases discussed
in Step 3 are exercised, and no test asserts behavior that contradicts the
plan. Codex should not modify files.

Bring the findings back to me. Adjust the tests (add, remove, or fix) based
on what we agree on before writing implementation.

## Step 6 — Implement until tests pass

Implement the plan. Run the full non-integration test suite (per
`feedback_unit_tests_only.md`) after changes and fix any failures. Do not
declare done until every test from Step 4/5 passes.

## Step 7 — Ask me to commit, push, and PR

Once all tests pass, stop and ask me whether to commit, push, and open a PR.
Do not do any of these on your own — wait for my go-ahead, then follow the
standard commit/PR workflow (specific `git add` for each new file, never
`git add -A`).

After you've done executing the plan, call /process-reviews in a loop until there are no more issues to fix.