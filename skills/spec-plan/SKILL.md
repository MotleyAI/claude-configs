---
name: spec-plan
description: Stage 1 of 4 of the /spec flow — interview me to turn the Linear issue + typed brief into a detailed spec, Codex-review the plan, emit the OpenSpec change (OpenSpec repos only), and make the plan durable. Normally dispatched by /spec; if the /spec context (BRANCH, CHANGE_ID, OPENSPEC, Linear issue) is not already loaded in this session, invoke the spec skill instead.
---

**Stage 1 of 4 of the `/spec` flow.** Prerequisite: `/spec` has run in this
session and established `BRANCH`, `CHANGE_ID`, `OPENSPEC`, and the full Linear
issue (body + comments). If any of that is missing, invoke the `spec` skill
instead — it rehydrates and dispatches back here. The `/spec` stopping policy
applies throughout this stage.

## Step 1 — Combine and interview

Treat the Linear issue body + comments AND whatever I typed when invoking
`/spec` as the combined brief. In case of conflict, what I typed has higher
priority but ask to be sure.

**Living-architecture repos**: the arc42 / LikeC4 reads and normative-harness
rules in the `spec` skill apply before drafting. The plan MUST state which node
principles apply, and any arc42 contradiction is raised as its own interview
point. If the change adds a capability, the plan also records where its spec
attaches in `index.yaml` (one node's `specs:`, or `cross_cutting_specs` with a
`touches:` list). When an arc42 axiom edit is needed, keep the clause **concise
and simple** — introduce a named concept (with a one-symbol gloss where it
helps, e.g. `a.b.a ≡ a`) and reference it, rather than spelling the mechanism
out inline. Present the exact wording for approval before it lands, and prefer
the shortest phrasing that stays precise.

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

**Recommendation bias — cleaner end-state over smaller diff.** When a decision
trades a cleaner architectural end result against a smaller or cheaper diff,
ALWAYS lean toward the cleaner end result and recommend it — UNLESS the diff to
get there is *really* huge. Churn, re-blessing goldens, and touching many call
sites are acceptable costs for a genuinely cleaner final structure; only a
truly outsized diff tips the recommendation the other way. This governs how you
form the RECOMMENDATION above, and applies at every stage of the flow, not just
planning.

**Design bias — structural fix over band-aid.** When the brief is a bug, a
gap, or an inconsistency, decide BEFORE designing the fix whether the reported
symptom is one instance of a deeper structural cause — judged against the
principles/axioms in the `architecture/**/*.arc42.md` files (an axiom-violating
shape left standing, two code paths that must agree by hand, a missed
normalization that a single canonical representation would obviate, a check
repeated at every call site, etc. are all tells). Prefer a design that makes
the whole bug CLASS impossible or hard to recur — at the planner / type /
canonical-representation level, one code path instead of N — over patching
the instance in the existing repetitive implementation. Raise this as its own
interview point: state the symptom, the structural cause, the band-aid vs.
structural options with PROS/CONS, the arc42 grounding, and your
RECOMMENDATION (leaning structural — a bigger diff is an acceptable cost, per
the bias above). Only if the problem is genuinely local with no structural
cause is the local fix the right plan; never silently plan a band-aid over a
structural problem, and never plan a large structural refactor without my
go-ahead.

When you think you have enough information, return a detailed, complete spec.
In the spec you write, NEVER take shortcuts or make simplifications or
extensions to the original requirements without asking me about each one first.

## Step 2 — Codex review of the plan

Once I've approved the spec/plan, hand the plan text to the codex MCP server
(`mcp__codex__codex`) and ask it to review the plan itself — not a diff —
focusing on correctness of approach, missed edge cases, risky design choices,
test coverage gaps, and anything that contradicts the Linear issue. Codex
should not modify files; it should return actionable findings.

Bring Codex's findings back to me and discuss them. For each finding, decide
together whether to fold it into the plan, defer it, or reject it. Update the
written spec to reflect the resolved decisions before moving on.

## Step 3 — Emit the OpenSpec change (OpenSpec repos only)

Skip this whole step unless `OPENSPEC=1` (set by `/spec`). Turn the approved,
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
     / `## RENAMED Requirements`. A **new** capability's file also needs a
     `## Purpose` (50+ chars) — omit it for an existing capability, else `archive`
     stamps a `TBD` placeholder into the corpus. Each requirement is
     `### Requirement: <name>` in
     SHALL/MUST language with **≥1** `#### Scenario:` in WHEN/THEN form. Validator
     gotchas: scenarios need **exactly four** `#` (three or bullets fail
     silently); MODIFIED must contain the FULL updated requirement; REMOVED needs
     **Reason** + **Migration**; RENAMED uses FROM:/TO:. These scenarios ARE the
     acceptance criteria for the `spec-tests` stage.
   - **design.md** — only for non-obvious design (the Codex-resolved decisions);
     skip if there's nothing to say.
   - **tasks.md** — the `- [ ]` checklist that also drives the
     `spec-tests` and `spec-implement` stages; maintain it here, not twice.
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

## Step 4 — Make the plan durable, then hard stop

> **🛑 HARD STOP (reset point 1 of 3) — before tests.** First make the plan
> durable: if `OPENSPEC=1` it's the validated change folder; if `OPENSPEC=0`,
> post the finalized plan to the Linear issue (a comment) so a reset recovers
> it. Then say we're at reset point 1 and STOP — do not start writing tests.
> I'll `/clear` and re-invoke `/spec`, which will detect and run
> `spec-tests`.
