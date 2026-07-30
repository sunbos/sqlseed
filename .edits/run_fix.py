"""Fault-tolerant runner for fix_all_remaining.py."""
from __future__ import annotations

import runpy
import sys

sys.path.insert(0, "/workspace")
import _edit_helper  # noqa: E402

failures: list[tuple[str, str]] = []
applied: list[str] = []
already: list[str] = []


def edit_recording(path: str, old: str, new: str, *, replace_all: bool = False) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    n_old = content.count(old)
    if n_old == 0:
        if new in content or (new == "" and old not in content):
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

runpy.run_path("/workspace/.edits/fix_all_remaining.py", run_name="__main__")

print("\n================ SUMMARY ================")
print(f"applied:  {len(applied)}")
print(f"already:  {len(already)}")
print(f"failures: {len(failures)}")
for p, o in failures:
    print(f"  - {p}\n      {o}")
