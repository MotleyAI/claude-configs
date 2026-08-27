---
name: refactor-python
description: Use when James asks to move or rename a Python module, class, function, or symbol and have all imports/references updated automatically (IDE-style refactor). Wraps `rope`; dry-run by default. Runs under the skill's own venv.
---

# IDE-grade Python refactoring (rope)

Move/rename Python code and rewrite every import and reference project-wide,
instead of hand-editing import strings. The engine is `rope`; this skill adds a
stable CLI plus the surrounding procedure.

Entrypoint: `~/.claude/skills/refactor-python/scripts/refactor.sh`
It runs `scripts/refactor.py` under `.venv/` (rope only — never system Python).

## Procedure (follow every time)

1. **Locate the symbol with the LSP tool, not grep** (per James's global rule).
   Use `documentSymbol` (in-file) or `workspaceSymbol` (find it) to get the
   exact `file`, `line`, `col`.
2. **Dry-run first** (default — no `--apply`). Show James the printed diff.
3. **Apply** only after James is happy: re-run the same command with `--apply`.
4. **Verify completeness:**
   - LSP `findReferences` on the symbol at its new location → confirm nothing
     dangles.
   - Grep for what rope CANNOT see (dynamic references): dotted-path strings,
     `importlib.import_module(`, `getattr(`, `__all__` entries, entry points,
     and config/Django-style string references to the old path. Fix by hand.
5. **Run the project's full non-integration test suite** and fix failures (per
   James's rules). rope is safe for static refs only; tests are the backstop.
6. **Review `git diff`.** James commits — never commit or `git add -A` here.

## Commands

Dry-run is the default; add `--apply` to write. `--project` defaults to cwd.

```bash
# Rename a symbol (function/class/variable/method) everywhere
~/.claude/skills/refactor-python/scripts/refactor.sh --project <root> rename \
    --file src/pkg/mod.py --line 42 --col 5 --new-name NewName

# Move a top-level function/class/global to another (existing) module
~/.claude/skills/refactor-python/scripts/refactor.sh --project <root> move-symbol \
    --file src/pkg/a.py --name Thing --dest src/pkg/b.py

# Move a whole module file into an (existing) package directory
~/.claude/skills/refactor-python/scripts/refactor.sh --project <root> move-module \
    --module src/pkg/mod.py --dest src/pkg/subpkg
```

Symbol locator for `rename`/`move-symbol` is one of: `--line [--col]`,
`--offset N` (0-based char offset), or `--name NAME` (first def/class/use).
Prefer `--line/--col` sourced from the LSP tool.

## Notes / limits

- **Destinations must already exist** (`move-symbol` dest module; `move-module`
  dest package dir). Create them first if needed.
- **First-party refactors** work regardless of interpreter. If a refactor needs
  rope to resolve the project's own installed third-party packages, run against
  the project's venv Python instead of `.venv/` (point at
  `scripts/refactor.py` with that interpreter).
- Run a formatter (ruff/black) after applying — rope may reflow touched imports.
- rope builds an analysis cache under the project; large trees are slower.
