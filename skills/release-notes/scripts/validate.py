#!/usr/bin/env python3
"""Validate a release-notes markdown file.

Checks:
  - non-ASCII characters (reports line, column, char, codepoint)
  - links to linear.app
  - the literal substring 'DEV-' (typical Linear workspace prefix)

Exit code is 0 if the file is clean, 1 otherwise.
"""

import argparse
import re
import sys
from pathlib import Path

LINEAR_HOST_RE = re.compile(r"\blinear\.app\b", re.IGNORECASE)
DEV_PREFIX_RE = re.compile(r"DEV-")


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [f"file is not valid UTF-8: {e}"]

    for lineno, line in enumerate(text.splitlines(), start=1):
        for col, ch in enumerate(line, start=1):
            if ord(ch) > 0x7F:
                problems.append(
                    f"non-ASCII char at line {lineno}, col {col}: "
                    f"{ch!r} (U+{ord(ch):04X})"
                )
        for m in LINEAR_HOST_RE.finditer(line):
            problems.append(
                f"linear.app reference at line {lineno}, col {m.start() + 1}: "
                f"{line.strip()!r}"
            )
        for m in DEV_PREFIX_RE.finditer(line):
            problems.append(
                f"'DEV-' (Linear workspace prefix) at line {lineno}, "
                f"col {m.start() + 1}: {line.strip()!r}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Path to the release-notes .md file")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"error: not a file: {args.file}", file=sys.stderr)
        return 2

    problems = check_file(args.file)
    if not problems:
        print(f"OK: {args.file} is clean")
        return 0

    print(f"FAIL: {args.file} has {len(problems)} issue(s):")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
