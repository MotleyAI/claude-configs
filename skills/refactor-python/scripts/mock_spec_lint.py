#!/usr/bin/env python3
"""Deterministic CI gate: every unittest.mock double must be bound to a spec.

Makes a renamed-away member impossible to reference undetected. Every
Mock/MagicMock must carry spec=/spec_set=; every patch()/patch.object() must
carry autospec=True (or an explicit new=/new_callable=/spec=). create_autospec()
is always allowed. Pure stdlib — run under any interpreter, no deps.

Usage: python mock_spec_lint.py <path> [<path> ...]   # files or dirs
Exit 0 clean, 1 violations (printed file:line: message), 2 usage error.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

MOCK_CTORS = {"Mock", "MagicMock", "NonCallableMock",
              "NonCallableMagicMock", "AsyncMock"}
SPEC_KWARGS = {"spec", "spec_set"}
PATCH_OK_KWARGS = {"autospec", "new", "new_callable", "spec", "spec_set"}
# Positional arg count at/after which `new` is supplied positionally.
PATCH_NEW_POS = {"patch": 2, "object": 3}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _patch_kind(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name) and f.id == "patch":
        return "patch"
    if isinstance(f, ast.Attribute):
        if f.attr == "patch":
            return "patch"
        if f.attr in ("object", "multiple") and _name(f.value) == "patch":
            return f.attr
    return None


def _kwargs(call: ast.Call) -> set[str]:
    return {kw.arg for kw in call.keywords if kw.arg}


def check_file(path: Path) -> list[str]:
    out: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = _patch_kind(node)
        if kind is not None:
            new_pos = kind in PATCH_NEW_POS and len(node.args) >= PATCH_NEW_POS[kind]
            if not (_kwargs(node) & PATCH_OK_KWARGS) and not new_pos:
                shown = "patch" if kind == "patch" else f"patch.{kind}"
                out.append(f"{path}:{node.lineno}: {shown}() without autospec=True/"
                           f"new=/spec= — stale members go undetected")
            continue
        name = _name(node.func)
        if name in MOCK_CTORS and not (_kwargs(node) & SPEC_KWARGS):
            out.append(f"{path}:{node.lineno}: {name}() without spec=/spec_set= "
                       f"— bind it to the real class (or use create_autospec)")
    return out


def _iter_py(paths):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(p.rglob("*.py"))
        else:
            yield p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: mock_spec_lint.py <path> [<path> ...]", file=sys.stderr)
        return 2
    problems = [msg for f in _iter_py(argv) for msg in check_file(f)]
    for msg in problems:
        print(msg)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
