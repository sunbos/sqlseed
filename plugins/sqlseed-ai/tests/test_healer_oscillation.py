"""Tests for healer.oscillation module."""

from __future__ import annotations

from sqlseed_ai.healer.oscillation import OscillationDetector
from sqlseed_ai.validator.models import ConstraintType, ViolationReport


def _v(cols, severity="crash"):
    return ViolationReport(
        table="t",
        columns=cols,
        constraint_type=ConstraintType.CHECK,
        severity=severity,
    )


def test_no_oscillation_first_call():
    det = OscillationDetector()
    assert det.check_and_record([_v(["a"])]) is False


def test_exact_oscillation_detected():
    det = OscillationDetector()
    det.check_and_record([_v(["a"])])
    det.check_and_record([_v(["b"])])
    assert det.check_and_record([_v(["a"])]) is True


def test_partial_oscillation_80_percent_overlap():
    det = OscillationDetector(partial_threshold=0.8)
    # State 1: {a, b, c, d, e}
    det.check_and_record([_v(["a"]), _v(["b"]), _v(["c"]), _v(["d"]), _v(["e"])])
    # State 2: {b, c, d, e, f} — 4/5 overlap with state 1
    assert det.check_and_record([_v(["b"]), _v(["c"]), _v(["d"]), _v(["e"]), _v(["f"])]) is True


def test_no_oscillation_distinct_states():
    det = OscillationDetector()
    det.check_and_record([_v(["a"])])
    det.check_and_record([_v(["b"])])
    det.check_and_record([_v(["c"])])
    assert det.check_and_record([_v(["d"])]) is False
