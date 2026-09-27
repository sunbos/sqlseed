"""Malformed type declarations remain cheap and preserve their raw fallback."""

from __future__ import annotations

import subprocess
import sys

import pytest

from sqlseed.database import _type_normalizer
from sqlseed.database._type_normalizer import TypeNormalizer


def test_long_unclosed_type_parameters_finish_within_bounded_time() -> None:
    # Bound the parser, not importing SQLAlchemy and the entire public API on
    # a busy Windows host. Other tests import the public TypeNormalizer export.
    program = """
import runpy, sys
TypeNormalizer = runpy.run_path(sys.argv[1])['TypeNormalizer']
raw = "VARCHAR" + " " * 100_000 + "("
result = TypeNormalizer().normalize(raw, "postgresql")
if result.base != raw.upper() or result.params != () or result.raw != raw:
    raise RuntimeError("Malformed type fallback changed")
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, _type_normalizer.__file__],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("raw", "base", "params"),
    [
        (" character varying ( 12 ) ", "VARCHAR", (12,)),
        ("numeric(10,,2,word)", "NUMERIC", (10, 2)),
        ("a((1)", "A", ()),
        ("a)", "A)", ()),
        (" a() ", " A() ", ()),
        ("(1)", "(1)", ()),
        (" a(1) extra ", " A(1) EXTRA ", ()),
        (" \t ", "TEXT", ()),
    ],
)
def test_parameter_syntax_and_malformed_fallback(raw: str, base: str, params: tuple[int, ...]) -> None:
    normalized = TypeNormalizer().normalize(raw, "postgresql")
    assert normalized.base == base
    assert normalized.params == params
    assert normalized.raw == raw
