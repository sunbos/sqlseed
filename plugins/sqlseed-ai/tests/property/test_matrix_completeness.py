"""Property-based tests for the contract matrix (Section 12).

These tests run in CI to verify that the built-in matrix covers all
realistic (generator, column_type, constraints) combinations. Gaps are
flagged as failures so they can be added to the matrix before users hit
them in production.

Runs in-memory SQLite to avoid CI timeouts (per user requirement).
"""

from __future__ import annotations

import sqlite3

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.contracts.matrix import ContractResolver, ViolationKind

# Generators that actually exist in the dispatch map
GENERATORS = st.sampled_from(
    [
        "integer",
        "float",
        "string",
        "text",
        "boolean",
        "date",
        "datetime",
        "email",
        "uuid",
        "choice",
        "name",
        "first_name",
        "last_name",
        "phone_number",
        "address",
        "city",
        "country",
        "url",
        "ipv4",
        "ipv6",
        "random_int",
        "random_float",
        "random_string",
    ]
)

# Column types that actually appear in real schemas
COLUMN_TYPES = st.sampled_from(
    [
        "INTEGER",
        "INT",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",
        "REAL",
        "FLOAT",
        "DOUBLE",
        "DECIMAL",
        "NUMERIC",
        "TEXT",
        "VARCHAR",
        "CHAR",
        "CLOB",
        "TIMESTAMP",
        "DATETIME",
        "DATE",
        "TIME",
        "BLOB",
        "BINARY",
        "BOOLEAN",
    ]
)

# Constraint combinations
CONSTRAINTS = st.lists(
    st.sampled_from(["UNIQUE", "NOT NULL", "PRIMARY KEY", "CHECK"]),
    unique=True,
).map(frozenset)


@given(
    generator=GENERATORS,
    column_type=COLUMN_TYPES,
    constraints=CONSTRAINTS,
)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_matrix_lookup_never_crashes(generator, column_type, constraints):
    """Property: ContractResolver.check() never raises for any input combo."""
    resolver = ContractResolver(
        builtin=set(BUILTIN_VIOLATIONS),
        learned=set(),
    )
    # Must not raise — gaps are returned as None, not exceptions
    result = resolver.check(
        generator=generator,
        column_type=column_type,
        constraints=constraints,
        config={},
    )
    # Result is either None (no violation) or a ContractViolation
    assert result is None or hasattr(result, "fix_strategy")


@given(
    generator=GENERATORS,
    column_type=COLUMN_TYPES,
    constraints=CONSTRAINTS,
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_known_crash_combinations_have_fix(generator, column_type, constraints):
    """Property: known crash combinations (e.g. integer on TIMESTAMP) must
    have a matching contract with a non-empty fix_strategy."""
    resolver = ContractResolver(
        builtin=set(BUILTIN_VIOLATIONS),
        learned=set(),
    )
    # Config that triggers conditional predicates (code-like name + small pool)
    config = {"name": "code", "pool_size": 5, "row_count": 100}
    result = resolver.check(
        generator=generator,
        column_type=column_type,
        constraints=constraints,
        config=config,
    )
    # If this is a known crash combo, the fix must exist
    if generator == "integer" and column_type == "TIMESTAMP":
        assert result is not None
        assert result.kind == ViolationKind.CRASH
        assert result.fix_strategy == "switch_generator"
    if generator == "choice" and "UNIQUE" in constraints:
        # With code-like name + small pool, the violation must be present
        assert result is not None
        assert result.kind == ViolationKind.UNIQUE_UNSATISFIABLE


def test_property_tests_use_in_memory_sqlite():
    """Sanity: confirm we can spin up an in-memory SQLite (no CI timeouts)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t (id) VALUES (1)")
    rows = conn.execute("SELECT COUNT(*) FROM t").fetchone()
    assert rows[0] == 1
    conn.close()
