"""Fault-tolerant runner for batch doc edits.

Wraps _edit_helper.edit so that:
- a missing old_string whose NEW string is already present => ALREADY (skip)
- a missing old_string whose new string is also absent      => recorded failure
- non-unique old_string                                       => recorded failure
Never aborts mid-batch; prints a summary at the end.
"""
from __future__ import annotations

import runpy
import sys

sys.path.insert(0, "/workspace")
import _edit_helper  # noqa: E402

failures: list[tuple[str, str]] = []
already: list[str] = []
applied: list[str] = []


def edit_recording(path: str, old: str, new: str, *, replace_all: bool = False) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    n_old = content.count(old)
    if n_old == 0:
        if new in content:
            already.append(f"{path}: {old[:60]!r}")
            return
        failures.append((path, old[:200]))
        print(f"FAIL(not found): {path}: {old[:80]!r}")
        return
    if n_old > 1 and not replace_all:
        failures.append((path, f"NON-UNIQUE({n_old}x): {old[:200]}"))
        print(f"FAIL(non-unique {n_old}x): {path}: {old[:80]!r}")
        return
    content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    applied.append(f"{path}: {old[:60]!r}")


_edit_helper.edit = edit_recording

runpy.run_path("/workspace/.edits/all_edits.py", run_name="__main__")

print("\n================ SUMMARY ================")
print(f"applied:  {len(applied)}")
print(f"already:  {len(already)}")
print(f"failures: {len(failures)}")
for p, o in failures:
    print(f"  - {p}\n      {o}")
