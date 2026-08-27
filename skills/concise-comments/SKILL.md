---
name: concise-comments
description: Rules for concise code comments/docstrings, plus a pass to trim verbose ones. Use when writing or reviewing code, or when asked to reduce comment verbosity / trim over-commented code / cut docstring bloat. Referenced by /spec and /process-reviews.
---

# Concise comments & docstrings

Prevention: follow these when writing. Cleanup: run the pass below when invoked as `/concise-comments`.

## The test
Keep a comment only if a competent reader of THIS codebase couldn't infer it from the code and names. Otherwise delete it, or cut it to the one missing fact in one line.

## For / not for
For: the non-obvious *why* (constraint, invariant, footgun, edge-case gotcha) and a one-line *what* on public APIs.
Not for: design narrative, alternatives-considered, defending the approach, repro steps, byte-count walkthroughs, ticket history, or restating the code. Those go in the PR description, DECISIONS.md, the issue, or a test.

## Limits (defaults; exceed only with a stated reason)
- Inline comment: 1 line. Needing 3+ lines to justify a line of code → rename things or move the rationale out.
- Function/method docstring: 1-line summary; +≤3 lines only for genuinely subtle behaviour.
- Module docstring: ≤8 lines. Test docstring: 1 line, or none if the name says it.
- Section banner: ≤1 label line, no `---` paragraphs.

Say it once at the definition; don't re-explain at every call site.

## Delete on sight
- **Restates the code** (`# strip prefix` above `x.split(...)`).
- **Ticket-ID noise** (`DEV-1234:` on every line/attribute; the value is the fact).
- **Design essay / justification debate** (paragraphs on why this is right and alternatives wrong).
- **Worked examples & repros** (byte counts, sample output) → move to the test.
- **Docstring echoing the name** (`def test_x: """Test x."""`).
- **Emphasis theatre** (ALL-CAPS sentences, "astronomically", "provably", "THE … requirement").

Keep, as ≤1 line: a real cross-dialect/edge gotcha, a non-obvious invariant, a "looks wrong but isn't", an ordering/side-effect warning. When unsure a *why* is inferable, keep it but shorten it.

## The pass (`/concise-comments`)
1. Scope: default to the branch diff (`git diff $(git merge-base <base> HEAD) -- '*.py'`); or the path/file the user names. Only added/modified comments unless told to sweep.
2. Edit comments/docstrings ONLY — never code, string literals, test data, asserts, imports, markers.
3. Verify: run affected tests + linter (green); confirm `git diff` changed no code line; measure before/after with `scripts/count_comments.py --range <mergebase> <paths>`.
4. Report per-file and total lines before → after + ratio, and that tests/lint pass.

Scale to the ask: "trim a bit" = kill the essays; "3x" / "massively" = apply every limit hard.
