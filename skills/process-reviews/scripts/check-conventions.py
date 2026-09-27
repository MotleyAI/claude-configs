#!/usr/bin/env python3
"""Deterministic imports-at-top gate for /process-reviews.

Checks, on the .py files a PR changed (whole file):

  [import-not-top]  Imports must be at the top of the module: no imports inside
                    functions/classes, no module-level imports after the first
                    non-import statement. Module-level ``if``/``try`` blocks
                    that only wrap imports (TYPE_CHECKING, optional deps) count
                    as part of the import prologue.

  [text-ratio]      Text-only lines (docstring / standalone-string lines plus
                    comment-only lines) must be <= 15% of total physical lines,
                    aggregated separately over the PR's test files and source
                    files (cap adjustable via --text-ratio-cap). No per-line
                    waiver — the fix is trimming comments/docstrings.

  [composite-assert]   (test files only) ``assert a and b`` — split into
                    separate assert statements so a failure names the broken
                    conjunct (mirrors Sonar python:S9073 locally).

  [raises-single-throw] (test files only) a ``with pytest.raises(...):`` /
                    ``assertRaises`` block that makes more than one call which
                    can throw — build inputs outside the block so the assertion
                    pins the call under test (mirrors Sonar python:S5778).

Waiver (reason required) as a trailing comment on the flagged line, e.g.
``# ALLOW(raises-single-throw): <reason>``; for import-not-top this is reserved
for genuine circular imports and needs the user's confirmation first:

    import x.y  # ALLOW(import-not-top): breaks an import cycle with <mod>

Usage:
    check-conventions.py --base origin/main [--repo-root DIR]
                         [--exclude GLOB ...] [FILE ...]

With no FILE args, checks ``git diff --name-only BASE...HEAD`` plus
working-tree edits (exactly the PR's changed files). Files matching a built-in
or ``--exclude`` glob are exempt from every check (product-surface docstrings
that are maintained deliberately, not trimmable prose). Output: one
``file:line: [rule] message`` per violation. Exit 0 = clean, 1 = violations,
2 = usage/git error.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

_WAIVER_RE = re.compile(r"#\s*ALLOW\((?P<rule>[a-z-]+)\)\s*:\s*\S")

IMPORT_NOT_TOP = "import-not-top"
TEXT_RATIO = "text-ratio"
COMPOSITE_ASSERT = "composite-assert"
RAISES_SINGLE_THROW = "raises-single-throw"

# ``pytest.raises`` / ``raises`` / ``self.assertRaises[Regex]`` context managers.
_RAISES_CALLEES: Tuple[str, ...] = (
    "raises", "assertRaises", "assertRaisesRegex", "assertRaisesRegexp",
)

# Files exempt from ALL checks: their docstrings are the deliberately-maintained
# agent-facing / user-facing product surface (MCP tool schemas, etc.), not
# trimmable prose — so the text-ratio cap does not apply. Repo-relative POSIX
# paths; fnmatch globs allowed. Extend with --exclude on the CLI.
DEFAULT_EXCLUDES: Tuple[str, ...] = (
    "slayer/mcp/server.py",
)


def _is_excluded(rel: str, *, patterns: List[str]) -> bool:
    """True when ``rel`` (repo-relative) matches any exclude glob."""
    rel_posix = Path(rel).as_posix()
    return any(fnmatch.fnmatch(rel_posix, pat) for pat in patterns)


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


def _check_composite_asserts(*, tree: ast.Module) -> Iterator[Tuple[int, str]]:
    """S9073: ``assert a and b`` should be split into separate assert statements
    (a failure otherwise can't say which conjunct broke)."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assert)
                and isinstance(node.test, ast.BoolOp)
                and isinstance(node.test.op, ast.And)):
            yield (
                node.lineno,
                "composite `assert ... and ...`; split into separate assert "
                "statements (Sonar S9073)",
            )


def _is_raises_cm(expr: ast.expr) -> bool:
    """True for a ``pytest.raises(...)`` / ``raises(...)`` / ``assertRaises(...)`` call."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Attribute):
        return func.attr in _RAISES_CALLEES
    return isinstance(func, ast.Name) and func.id in _RAISES_CALLEES


def _check_raises_single_throw(*, tree: ast.Module) -> Iterator[Tuple[int, str]]:
    """S5778: a ``with pytest.raises(...):`` block should hold exactly one
    invocation that can throw — build inputs (helper/constructor calls) outside
    the block so the assertion pins the call actually under test."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(_is_raises_cm(item.context_expr) for item in node.items):
            continue
        calls = sum(
            isinstance(sub, ast.Call)
            for stmt in node.body
            for sub in ast.walk(stmt)
        )
        if calls > 1:
            yield (
                node.lineno,
                f"`pytest.raises` block makes {calls} calls that can throw; move "
                "all but the call under test outside the block (Sonar S5778)",
            )


def _waived(*, source_lines: List[str], line: int, rule: str) -> bool:
    if not (1 <= line <= len(source_lines)):
        return False
    m = _WAIVER_RE.search(source_lines[line - 1])
    return bool(m and m.group("rule") == rule)


def _is_test_file(rel: str) -> bool:
    parts = Path(rel).parts
    name = parts[-1]
    return (
        any(p in ("tests", "test") for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _text_line_numbers(*, source: str, tree: ast.Module) -> Set[int]:
    """Lines holding only text: docstring/standalone-string statement spans
    plus comment-only lines (``#`` inside string literals doesn't count)."""
    text: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and _is_docstring(node):
            text.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if (tok.type == tokenize.COMMENT
                    and not tok.line[: tok.start[1]].strip()):
                text.add(tok.start[0])
    except tokenize.TokenError:
        pass
    return text


def check_file(
    path: Path, *, rel: str,
) -> Tuple[List[Violation], Optional[Tuple[int, int]]]:
    """Violations plus ``(text_only_lines, total_lines)``; the counts are
    ``None`` when the file is unreadable or unparsable."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(
            path=rel, line=1, rule="unreadable", message=str(exc),
        )], None
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Violation(
            path=rel, line=exc.lineno or 1, rule="syntax-error",
            message=exc.msg or "syntax error",
        )], None
    source_lines = source.splitlines()
    out: List[Violation] = []
    for line, message in _check_imports_at_top(tree=tree):
        if not _waived(source_lines=source_lines, line=line, rule=IMPORT_NOT_TOP):
            out.append(Violation(
                path=rel, line=line, rule=IMPORT_NOT_TOP, message=message,
            ))
    # Pytest assertion smells (Sonar S9073 / S5778) apply to test files only.
    if _is_test_file(rel):
        for rule, check in (
            (COMPOSITE_ASSERT, _check_composite_asserts),
            (RAISES_SINGLE_THROW, _check_raises_single_throw),
        ):
            for line, message in check(tree=tree):
                if not _waived(source_lines=source_lines, line=line, rule=rule):
                    out.append(Violation(
                        path=rel, line=line, rule=rule, message=message,
                    ))
    out.sort(key=lambda v: (v.line, v.rule))
    counts = (len(_text_line_numbers(source=source, tree=tree)), len(source_lines))
    return out, counts


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
    parser.add_argument("--text-ratio-cap", type=float, default=15.0,
                        help="max %% of text-only lines per file group "
                             "(default: 15)")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="GLOB",
                        help="repo-relative path glob to exempt from all checks "
                             "(repeatable); merged with the built-in "
                             "product-surface exempt list")
    parser.add_argument("files", nargs="*",
                        help="explicit files (default: the PR's changed .py files)")
    ns = parser.parse_args(argv)

    repo_root = Path(ns.repo_root).resolve()
    excludes = list(DEFAULT_EXCLUDES) + list(ns.exclude)
    rels = ns.files or _changed_py_files(base=ns.base, repo_root=repo_root)
    excluded = [r for r in rels if _is_excluded(r, patterns=excludes)]
    rels = [r for r in rels if not _is_excluded(r, patterns=excludes)]
    if excluded:
        sys.stderr.write(
            "check-conventions: exempt (product surface, skipped): "
            + ", ".join(excluded) + "\n"
        )
    violations: List[Violation] = []
    groups: Dict[str, List[Tuple[str, int, int]]] = {"source": [], "tests": []}
    for rel in rels:
        path = repo_root / rel
        if not path.exists():
            continue
        file_violations, counts = check_file(path, rel=rel)
        violations.extend(file_violations)
        if counts is not None:
            group = "tests" if _is_test_file(rel) else "source"
            groups[group].append((rel, *counts))

    for v in violations:
        print(v.render())

    ratio_red = False
    for group, files in groups.items():
        text = sum(t for _, t, _ in files)
        total = sum(n for _, _, n in files)
        if not total:
            continue
        pct = 100.0 * text / total
        sys.stderr.write(
            f"check-conventions: {group} text-only ratio {pct:.1f}% "
            f"({text}/{total}, cap {ns.text_ratio_cap:.1f}%)\n"
        )
        if pct <= ns.text_ratio_cap:
            continue
        ratio_red = True
        print(
            f"[{TEXT_RATIO}] {group}: text-only lines are {pct:.1f}% of the "
            f"changed {group} files ({text}/{total}), cap {ns.text_ratio_cap:.1f}%"
        )
        by_ratio = sorted(
            (f for f in files if f[2]),
            key=lambda f: f[1] / f[2], reverse=True,
        )
        for rel, t, n in by_ratio:
            print(f"    {rel}: {100.0 * t / n:.1f}% ({t}/{n})")

    n_files = len(rels)
    sys.stderr.write(
        f"check-conventions: {len(violations)} violation(s) across "
        f"{n_files} changed .py file(s)\n"
    )
    return 1 if violations or ratio_red else 0


if __name__ == "__main__":
    sys.exit(main())
