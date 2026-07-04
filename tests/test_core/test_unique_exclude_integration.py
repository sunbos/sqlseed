"""End-to-end integration tests for the ``exclude_values`` root-cause fix.

These tests verify that the root-cause fix for the "UNIQUE + semantic
generators" failure pattern works end-to-end:

  Before the fix:
    - ``faker.email()`` produces duplicates around row ~300-500
    - ``ConstraintSolver.try_register`` detects the duplicate
    - ``DataStream`` retries blindly (generator has no exclude info)
    - After 1000 retries, ``RuntimeError`` is raised → entire table fails

  After the fix:
    - ``DataStream`` passes ``ConstraintSolver.get_seen(col)`` as
      ``exclude_values`` to ``provider.generate()``
    - The dispatch layer retries internally (up to 50 attempts) to avoid
      producing values in the exclude set
    - 1000 rows of UNIQUE ``faker.email()`` succeed without ``RuntimeError``

This is the regression test that proves the fix is not a self-proving test:
without the ``exclude_values`` propagation, this test fails with
``RuntimeError``.
"""

from __future__ import annotations

import pytest

from sqlseed.core.column_dag import ColumnConstraints, ColumnDAG, ColumnNode
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.generators.faker_provider import FakerProvider

from .conftest import make_stream


class TestUniqueSemanticGenerators:
    """End-to-end tests for UNIQUE + semantic generators (the failure pattern)."""

    def test_faker_email_unique_1000_rows_succeeds(self) -> None:
        """1000 UNIQUE ``faker.email()`` rows succeed without ``RuntimeError``.

        This is the canonical regression test for the root-cause fix. Before
        the ``exclude_values`` fix, this test would fail with
        ``RuntimeError: Failed to generate row satisfying all constraints
        after 1000 retries`` because ``faker.email()`` produces duplicates
        on large row counts.
        """
        specs = {"email": GeneratorSpec(generator_name="email")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = [
            ColumnNode(
                name=n.name,
                generator_spec=n.generator_spec,
                constraints=ColumnConstraints(is_unique=True, max_retries=100),
            )
            for n in nodes
        ]

        provider = FakerProvider()
        provider.set_seed(42)
        stream = make_stream(unique_nodes, provider, seed=42)

        batches = list(stream.generate(1000, batch_size=500))
        emails = [row["email"] for batch in batches for row in batch]

        assert len(emails) == 1000, f"Expected 1000 rows, got {len(emails)}"
        unique_count = len(set(emails))
        assert unique_count == 1000, f"Duplicate emails found: {len(emails) - unique_count} duplicates in 1000 rows"

    def test_faker_name_unique_500_rows_succeeds(self) -> None:
        """500 UNIQUE ``faker.name()`` rows succeed (semantic generator + UNIQUE).

        Same root-cause pattern as email: ``faker.name()`` produces
        duplicates on large row counts. The ``exclude_values`` fix applies
        uniformly to all generators via the dispatch layer.
        """
        specs = {"name": GeneratorSpec(generator_name="name")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = [
            ColumnNode(
                name=n.name,
                generator_spec=n.generator_spec,
                constraints=ColumnConstraints(is_unique=True, max_retries=100),
            )
            for n in nodes
        ]

        provider = FakerProvider()
        provider.set_seed(42)
        stream = make_stream(unique_nodes, provider, seed=42)

        batches = list(stream.generate(500, batch_size=500))
        names = [row["name"] for batch in batches for row in batch]

        assert len(names) == 500
        unique_count = len(set(names))
        assert unique_count == 500, f"Duplicate names found: {len(names) - unique_count} duplicates in 500 rows"

    def test_faker_phone_unique_300_rows_succeeds(self) -> None:
        """300 UNIQUE ``faker.phone_number()`` rows succeed.

        Phone numbers have a smaller value space than emails (fewer
        format permutations), so this test exercises the dispatch-layer
        retry loop more aggressively.
        """
        specs = {"phone": GeneratorSpec(generator_name="phone")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = [
            ColumnNode(
                name=n.name,
                generator_spec=n.generator_spec,
                constraints=ColumnConstraints(is_unique=True, max_retries=100),
            )
            for n in nodes
        ]

        provider = FakerProvider()
        provider.set_seed(42)
        stream = make_stream(unique_nodes, provider, seed=42)

        batches = list(stream.generate(300, batch_size=300))
        phones = [row["phone"] for batch in batches for row in batch]

        assert len(phones) == 300
        unique_count = len(set(phones))
        assert unique_count == 300, f"Duplicate phones found: {len(phones) - unique_count} duplicates in 300 rows"

    def test_base_provider_email_unique_1000_rows_succeeds(self) -> None:
        """1000 UNIQUE ``BaseProvider._gen_email()`` rows succeed.

        ``BaseProvider`` already uses a counter to guarantee uniqueness, so
        this test verifies that the ``exclude_values`` fix does not break
        the existing behavior. The dispatch-layer retry loop should be a
        no-op when the generator never produces duplicates.
        """
        from sqlseed.generators.base_provider import BaseProvider

        specs = {"email": GeneratorSpec(generator_name="email")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = [
            ColumnNode(
                name=n.name,
                generator_spec=n.generator_spec,
                constraints=ColumnConstraints(is_unique=True, max_retries=100),
            )
            for n in nodes
        ]

        provider = BaseProvider()
        provider.set_seed(42)
        stream = make_stream(unique_nodes, provider, seed=42)

        batches = list(stream.generate(1000, batch_size=500))
        emails = [row["email"] for batch in batches for row in batch]

        assert len(emails) == 1000
        unique_count = len(set(emails))
        assert unique_count == 1000

    def test_value_space_exhaustion_raises_runtime_error(self) -> None:
        """When the value space is genuinely exhausted, ``RuntimeError`` is raised.

        This is the "value space too small" case: a UNIQUE boolean column
        can only hold 2 distinct values (True/False). Generating 3 rows
        must fail with ``RuntimeError`` after exhausting retries.

        This test ensures the ``exclude_values`` fix does not mask genuine
        value-space exhaustion — it only helps when the value space is
        sufficient but the generator happens to produce duplicates.
        """
        specs = {"flag": GeneratorSpec(generator_name="boolean")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = [
            ColumnNode(
                name=n.name,
                generator_spec=n.generator_spec,
                constraints=ColumnConstraints(is_unique=True, max_retries=5),
            )
            for n in nodes
        ]

        provider = FakerProvider()
        provider.set_seed(42)
        stream = make_stream(unique_nodes, provider, seed=42)

        with pytest.raises(RuntimeError, match="Failed to generate row satisfying all constraints"):
            list(stream.generate(3, batch_size=3))
