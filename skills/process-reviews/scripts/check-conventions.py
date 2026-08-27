#!/usr/bin/env python3
"""Deterministic imports-at-top gate for /process-reviews.

Checks, on the .py files a PR changed (whole file):

  [import-not-top]  Imports must be at the top of the module: no imports inside
                    functions/classes, no module-level imports after the first
                    non-import statement. Module-level ``if``/``try`` blocks
                    that only wrap imports (TYPE_CHECKING, optional deps) count
                    as part of the import prologue.

Waiver (reason required), as a trailing comment on the flagged line — per the
user's CLAUDE.md this is reserved for genuine circular imports and needs their
confirmation first:

    import x.y  # ALLOW(import-not-top): breaks an import cycle with <mod>

Usage:
    check-conventions.py --base origin/main [--repo-root DIR] [FILE ...]

With no FILE args, checks ``git diff --name-only BASE...HEAD`` plus
working-tree edits (exactly the PR's changed files). Output: one
``file:line: [rule] message`` per violation. Exit 0 = clean, 1 = violations,
2 = usage/git error.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

_WAIVER_RE = re.compile(r"#\s*ALLOW\((?P<rule>[a-z-]+)\)\s*:\s*\S")

IMPORT_NOT_TOP = "import-not-top"


class Violation:
    def __init__(self, *, path: str, line: int, rule: str, message: str) -> None:
        self.path = path
        self.line = line
        self.rule = rule
        self.message = message

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _contains_def(node: ast.stmt) -> bool:
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for n in ast.walk(node)
    )


def _imports_in(node: ast.stmt) -> List[ast.stmt]:
    return [
        n for n in ast.walk(node)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]


def _is_import_wrapper(stmt: ast.stmt) -> bool:
    """A module-level ``if``/``try`` that exists to wrap imports
    (TYPE_CHECKING blocks, optional-dependency try/except)."""
    if not isinstance(stmt, (ast.If, ast.Try)):
        return False
    return bool(_imports_in(stmt)) and not _contains_def(stmt)


def _check_imports_at_top(*, tree: ast.Module) -> Iterator[Tuple[int, str]]:
    """Yield (line, message) for import placement violations."""
    prologue_over = False
    for idx, stmt in enumerate(tree.body):
        if _is_docstring(stmt) and idx == 0:
            continue
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if prologue_over:
                yield (
                    stmt.lineno,
                    "module-level import after non-import code; move it to "
                    "the top of the file",
                )
            continue
        if _is_import_wrapper(stmt):
            if prologue_over:
                for imp in _imports_in(stmt):
                    yield (
                        imp.lineno,
                        "module-level import after non-import code; move it "
                        "to the top of the file",
                    )
            continue
        prologue_over = True

    # Imports nested inside any function (or method) body.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for imp in _imports_in_function(node):
                yield (
                    imp.lineno,
                    f"import inside function {node.name!r}; move it to the "
                    f"top of the file",
                )


def _imports_in_function(
    fn: ast.stmt,
) -> List[ast.stmt]:
    """Imports directly inside ``fn``, not double-counting nested defs
    (each nested def is visited on its own by the caller's walk)."""
    out: List[ast.stmt] = []
    stack: List[ast.stmt] = list(
        getattr(fn, "body", []),
    )
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(node)
            continue
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                stack.append(child)
    return out


def _waived(*, source_lines: List[str], line: int, rule: str) -> bool:
    if not (1 <= line <= len(source_lines)):
        return False
    m = _WAIVER_RE.search(source_lines[line - 1])
    return bool(m and m.group("rule") == rule)


def check_file(path: Path, *, rel: str) -> List[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(
            path=rel, line=1, rule="unreadable", message=str(exc),
        )]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Violation(
            path=rel, line=exc.lineno or 1, rule="syntax-error",
            message=exc.msg or "syntax error",
        )]
    source_lines = source.splitlines()
    out: List[Violation] = []
    for line, message in _check_imports_at_top(tree=tree):
        if not _waived(source_lines=source_lines, line=line, rule=IMPORT_NOT_TOP):
            out.append(Violation(
                path=rel, line=line, rule=IMPORT_NOT_TOP, message=message,
            ))
    out.sort(key=lambda v: (v.line, v.rule))
    return out


def _changed_py_files(*, base: str, repo_root: Path) -> List[str]:
    """PR-modified .py files: merge-base committed diff ∪ working-tree edits."""
    out: set = set()
    for target in (f"{base}...HEAD", "HEAD"):
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", target],
            cwd=repo_root, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            sys.exit(2)
        out.update(p for p in proc.stdout.splitlines() if p.endswith(".py"))
    return sorted(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True,
                        help="PR base ref (e.g. origin/main)")
    parser.add_argument("--repo-root", default=".",
                        help="repository root (default: cwd)")
    parser.add_argument("files", nargs="*",
                        help="explicit files (default: the PR's changed .py files)")
    ns = parser.parse_args(argv)

    repo_root = Path(ns.repo_root).resolve()
    rels = ns.files or _changed_py_files(base=ns.base, repo_root=repo_root)
    violations: List[Violation] = []
    for rel in rels:
        path = repo_root / rel
        if not path.exists():
            continue
        violations.extend(check_file(path, rel=rel))

    for v in violations:
        print(v.render())
    n_files = len(rels)
    sys.stderr.write(
        f"check-conventions: {len(violations)} violation(s) across "
        f"{n_files} changed .py file(s)\n"
    )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
