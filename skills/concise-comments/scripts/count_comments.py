#!/usr/bin/env python3
"""Count comment + docstring lines in Python files.

Comments via tokenize, docstrings via AST (module/class/function first stmt).

  count_comments.py <file>...              # per-file + total counts
  count_comments.py --range <ref> <path>...  # net added vs a git ref (working tree)
"""
from __future__ import annotations

import ast
import io
import subprocess
import sys
import tokenize


def counts(src: str | None) -> tuple[int, int]:
    if src is None:
        return (0, 0)
    try:
        comment = sum(
            1 for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type == tokenize.COMMENT
        )
    except Exception:
        comment = 0
    doc = 0
    try:
        tree = ast.parse(src)
    except Exception:
        return (comment, 0)
    kinds = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if isinstance(node, kinds):
            body = getattr(node, "body", [])
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc += first.end_lineno - first.lineno + 1
    return (comment, doc)


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def read(path: str) -> str | None:
    try:
        return open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return None


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--range":
        ref = argv[1]
        paths = argv[2:]
        tc = td = 0
        for p in paths:
            b = counts(git_show(ref, p))
            h = counts(read(p))
            dc, dd = h[0] - b[0], h[1] - b[1]
            print(f"{dc + dd:+5d}  comment={dc:+4d} doc={dd:+4d}  {p}")
            tc += dc
            td += dd
        print(f"{'=' * 50}\nNET ADDED total={tc + td} (comment {tc}, docstring {td})")
        return 0
    if not argv:
        print(__doc__)
        return 1
    tc = td = 0
    for p in argv:
        c, d = counts(read(p))
        print(f"{c + d:5d}  comment={c:4d} doc={d:4d}  {p}")
        tc += c
        td += d
    print(f"{'=' * 50}\nTOTAL={tc + td} (comment {tc}, docstring {td})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
