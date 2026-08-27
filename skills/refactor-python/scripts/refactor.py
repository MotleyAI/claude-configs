#!/usr/bin/env python3
"""IDE-grade Python refactors via rope: rename, move-symbol, move-module.

Rewrites every import and reference across the project. Dry-run by default;
pass --apply to write. Symbol location comes from --offset, --line/--col
(1-based, as an editor/LSP reports), or --name (first def/class/use).
"""
# rope resolves at runtime from the skill's own .venv, not the checker's env.
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import re
from pathlib import Path

from rope.base import libutils
from rope.base.project import Project
from rope.refactor.move import create_move
from rope.refactor.rename import Rename


def _offset_from_line_col(text: str, line: int, col: int) -> int:
    lines = text.splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise SystemExit(f"line {line} out of range (file has {len(lines)} lines)")
    return sum(len(lines[i]) for i in range(line - 1)) + (col - 1)


def _find_symbol_offset(text: str, name: str) -> int:
    escaped = re.escape(name)
    m = re.search(rf"^\s*(?:async\s+def|def|class)\s+({escaped})\b", text, re.M)
    if m:
        return m.start(1)
    m = re.search(rf"\b{escaped}\b", text)
    if not m:
        raise SystemExit(f"symbol {name!r} not found in file")
    return m.start()


def _resolve_offset(args, text: str) -> int:
    if args.offset is not None:
        return args.offset
    if args.line is not None:
        return _offset_from_line_col(text, args.line, args.col or 1)
    if args.name is not None:
        return _find_symbol_offset(text, args.name)
    raise SystemExit("provide one of --offset, --line [--col], or --name")


def _resource(project: Project, path: str):
    return libutils.path_to_resource(project, str(Path(path).resolve()))


def _emit(project: Project, changes, apply: bool) -> None:
    print(changes.get_description())
    touched = [c.resource.path for c in changes.changes]
    if apply:
        project.do(changes)
        print(f"\nAPPLIED. {len(touched)} file(s) changed:")
        for p in touched:
            print(f"  {p}")
    else:
        print(f"\nDRY-RUN. {len(touched)} file(s) would change. Re-run with --apply.")


def cmd_rename(args, project):
    text = Path(args.file).read_text()
    offset = _resolve_offset(args, text)
    renamer = Rename(project, _resource(project, args.file), offset)
    unsure = (lambda *_: True) if args.unsure == "include" else None
    if unsure:
        print("WARNING: --unsure=include also renames occurrences rope cannot "
              "resolve; it may rewrite unrelated attributes of the same name.")
    changes = renamer.get_changes(
        args.new_name, in_hierarchy=args.in_hierarchy, unsure=unsure
    )
    _emit(project, changes, args.apply)


def cmd_move_symbol(args, project):
    text = Path(args.file).read_text()
    offset = _resolve_offset(args, text)
    mover = create_move(project, _resource(project, args.file), offset)
    changes = mover.get_changes(_resource(project, args.dest))
    _emit(project, changes, args.apply)


def cmd_move_module(args, project):
    mover = create_move(project, _resource(project, args.module))  # offset None -> MoveModule
    changes = mover.get_changes(_resource(project, args.dest))
    _emit(project, changes, args.apply)


def _add_locator(sp) -> None:
    sp.add_argument("--file", required=True)
    sp.add_argument("--offset", type=int)
    sp.add_argument("--line", type=int)
    sp.add_argument("--col", type=int)
    sp.add_argument("--name")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=".", help="Project root (default: cwd)")
    p.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("rename", help="Rename the symbol at a location")
    _add_locator(sp)
    sp.add_argument("--new-name", required=True)
    sp.add_argument("--no-in-hierarchy", dest="in_hierarchy", action="store_false",
                    help="Disable hierarchy rename (ON by default: also renames overrides in sub/superclasses)")
    sp.add_argument("--unsure", choices=["skip", "include"], default="skip",
                    help="Occurrences rope cannot resolve: skip (default) or include (risky)")
    sp.set_defaults(func=cmd_rename, in_hierarchy=True)

    sp = sub.add_parser("move-symbol", help="Move a top-level function/class/global to another module")
    _add_locator(sp)
    sp.add_argument("--dest", required=True, help="Destination module .py (must exist)")
    sp.set_defaults(func=cmd_move_symbol)

    sp = sub.add_parser("move-module", help="Move a module file into a package/dir")
    sp.add_argument("--module", required=True, help="Source module .py")
    sp.add_argument("--dest", required=True, help="Destination package directory (must exist)")
    sp.set_defaults(func=cmd_move_module)

    args = p.parse_args(argv)
    project = Project(str(Path(args.project).resolve()))
    try:
        args.func(args, project)
    finally:
        project.close()


if __name__ == "__main__":
    main()
