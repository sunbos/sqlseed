"""Shared counters and output for standalone validation suites."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckRecorder:
    """Accumulate results without rebinding module-level counters."""

    report_passes: bool = True
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            if self.report_passes:
                print(f"  [PASS] {name}")
        else:
            self.failed += 1
            self.failures.append(name)
            print(f"  [FAIL] {name}  {detail}")

    def summarize(self) -> int:
        """Print the common suite summary and return its process exit code."""
        print("\n" + "=" * 70)
        print(f"TOTAL: {self.passed} passed, {self.failed} failed")
        if self.failures:
            print("failed checks:")
            for failure in self.failures:
                print(f"  - {failure}")
        print("=" * 70)
        return 0 if self.failed == 0 else 1
