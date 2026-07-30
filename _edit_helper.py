"""Precise string-replacement helper mirroring the Edit tool semantics.

Usage from a batch script:
    from _edit_helper import edit
    edit("/abs/path.md", "old", "new")                # must be unique
    edit("/abs/path.md", "old", "new", replace_all=True)
"""
from __future__ import annotations

import sys


def edit(path: str, old: str, new: str, *, replace_all: bool = False) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    occurrences = content.count(old)
    if occurrences == 0:
        print(f"FAIL: old_string not found in {path}:\n---\n{old[:400]}\n---")
        sys.exit(1)
    if occurrences > 1 and not replace_all:
        print(f"FAIL: old_string occurs {occurrences}x in {path} (not unique):\n---\n{old[:400]}\n---")
        sys.exit(1)
    if replace_all:
        content = content.replace(old, new)
        print(f"OK: {path} ({occurrences} replacements)")
    else:
        content = content.replace(old, new, 1)
        print(f"OK: {path} (1 replacement)")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
