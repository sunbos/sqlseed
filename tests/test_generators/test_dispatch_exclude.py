"""Tests for ``exclude_values`` support in ``GeneratorDispatchMixin.generate``.

The ``exclude_values`` parameter is the core mechanism for the root-cause fix
of the "UNIQUE + semantic generators" failure pattern. When a column has a
UNIQUE constraint, ``DataStream`` passes the constraint solver's seen set as
``exclude_values`` so the generator can avoid producing values already in use.

These tests verify:
  1. Backward compatibility — ``generate()`` without ``exclude_values`` works.
  2. ``exclude_values`` avoidance — generator retries until producing a value
     not in the exclude set.
  3. End-to-end uniqueness — 100 unique integers from a 1000-value space.
"""

from __future__ import annotations

from sqlseed.generators.base_provider import BaseProvider


class TestGenerateExcludeValues:
    """Tests for ``exclude_values`` parameter on ``generate()``."""

    def test_generate_without_exclude_values_works(self) -> None:
        """Backward compatibility: ``generate()`` without ``exclude_values`` works as before."""
        provider = BaseProvider()
        provider.set_seed(42)
        val = provider.generate("integer", min_value=1, max_value=10)
        assert 1 <= val <= 10

    def test_generate_with_none_exclude_values_works(self) -> None:
        """``exclude_values=None`` is equivalent to not passing it."""
        provider = BaseProvider()
        provider.set_seed(42)
        val = provider.generate("integer", min_value=1, max_value=10, exclude_values=None)
        assert 1 <= val <= 10

    def test_generate_with_empty_exclude_values_works(self) -> None:
        """Empty ``exclude_values`` set is equivalent to no exclusion."""
        provider = BaseProvider()
        provider.set_seed(42)
        val = provider.generate("integer", min_value=1, max_value=10, exclude_values=set())
        assert 1 <= val <= 10

    def test_generate_exclude_values_avoids_duplicates(self) -> None:
        """``exclude_values``: generator retries until producing a value not in the exclude set.

        Uses a tightly constrained value space (1-2) with one value excluded,
        forcing the generator to eventually return the only allowed value.
        """
        provider = BaseProvider()
        provider.set_seed(42)
        # Exclude value 1; only value 2 is allowed
        val = provider.generate("integer", min_value=1, max_value=2, exclude_values={1})
        assert val == 2

    def test_generate_exclude_values_produces_unique_sequence(self) -> None:
        """Integration: 100 unique integers from a 1000-value space, using ``exclude_values``.

        This is a stable regression test for the dispatch-layer retry loop:
        without ``exclude_values`` support, generating 100 unique integers
        from 1-1000 would still pass (integer space is large), but this test
        exercises the full retry-with-exclude code path.
        """
        provider = BaseProvider()
        provider.set_seed(42)
        seen: set[int] = set()
        for _ in range(100):
            val = provider.generate("integer", min_value=1, max_value=1000, exclude_values=seen)
            assert val not in seen, f"Generator produced duplicate value {val} despite exclude_values"
            seen.add(val)
        assert len(seen) == 100

    def test_generate_exclude_values_with_string_generator(self) -> None:
        """``exclude_values`` works with string generators (semantic generators benefit)."""
        provider = BaseProvider()
        provider.set_seed(42)
        # Generate 50 unique strings
        seen: set[str] = set()
        for _ in range(50):
            val = provider.generate("string", min_length=8, max_length=8, exclude_values=seen)
            assert val not in seen
            seen.add(val)
        assert len(seen) == 50

    def test_generate_exclude_values_falls_back_when_value_space_exhausted(self) -> None:
        """When the exclude set covers the entire value space, generator returns a value anyway.

        The dispatch layer retries up to a fixed maximum (50 attempts); if no
        unique value can be produced, it returns the last generated value.
        This is intentional — the caller (``ConstraintSolver.try_register``)
        will detect the duplicate and trigger backtracking, which is the
        correct signal that the value space is genuinely exhausted.
        """
        provider = BaseProvider()
        provider.set_seed(42)
        # Value space is {1, 2}, exclude both
        val = provider.generate("integer", min_value=1, max_value=2, exclude_values={1, 2})
        # Generator should still return a value (either 1 or 2)
        assert val in (1, 2)
