---
name: release-notes
description: Use when the user asks to draft release notes, write release notes, or summarize changes since the last release for the current repository.
---

# Release Notes

Write release notes for all the changes in the current repo's `main` (or `master`) since the last release.

## Rules

- Use ASCII characters ONLY. No smart quotes, em dashes, ellipses, arrows, bullets, accented letters, or any other non-ASCII glyph. Use `-`, `'`, `"`, `...` instead.
- DO NOT mention Linear issues. Do not include `DEV-...` identifiers or links to `linear.app`.
- Do not insert line breaks just to keep line length under some limit. Only break lines between paragraphs to keep natural flow. Each paragraph or bullet should be a single line.
- Keep the tone directed at the general user audience of the repo, not at the maintainers. Focus on what changed for users, not internal refactors or process details.
- DO NOT try to imitate the style of past release notes. Their style may be no longer relevant.
- Keep the notes brief and succinct, especially for minor releases.
- Write the notes into an `.md` file in the root of the repo.

## Steps

1. Identify the default branch (`main` or `master`) and the previous release. Prefer `git describe --tags --abbrev=0` for the last tag; fall back to inspecting `gh release list` if tags are not used.
2. Collect the changes since that release using `git log <last-tag>..HEAD --no-merges` on the default branch. Read commit subjects and bodies; for non-trivial commits, also inspect the diff.
3. Determine the next version number from context (commits, package files, prior tags). If unclear, ask the user.
4. Draft the notes following the rules above. Group related changes; lead with user-visible features and fixes.
5. Write the notes to a new `.md` file in the repo root (e.g. `RELEASE_NOTES_<version>.md`, or append to an existing `CHANGELOG.md` if the repo uses one - check first).
6. Run the validator on the written file:

   ```bash
   python ~/.claude/skills/release-notes/scripts/validate.py <path-to-file>
   ```

   If the validator reports issues, fix them and re-run until it passes. Do not report the task as done until validation passes.

## Validator

The validator checks for:

- non-ASCII characters (with line/column and the offending char)
- links to `linear.app` (any URL containing that host)
- the literal string `DEV-` (the typical Linear workspace prefix used in this org)

Exit code 0 = clean. Non-zero = problems found; details are printed to stdout.
