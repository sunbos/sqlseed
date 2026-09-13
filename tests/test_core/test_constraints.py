from __future__ import annotations

from sqlseed.core.constraints import ConstraintSolver, RegisterResult


class TestConstraintSolver:
    def test_check_and_register_non_unique(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, is_unique=False) is True
        assert solver.check_and_register("col", 1, is_unique=False) is True

    def test_check_and_register_unique_first_time(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, is_unique=True) is True

    def test_check_and_register_unique_duplicate(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, is_unique=True)
        assert solver.check_and_register("col", 1, is_unique=True) is False

    def test_try_register_returns_backtrack(self) -> None:
        solver = ConstraintSolver()
        solver.try_register("col", 1, is_unique=True)
        result = solver.try_register("col", 1, is_unique=True, source_columns=["src"])
        assert isinstance(result, RegisterResult)
        assert result.is_registered is False
        assert result.should_backtrack is True
        assert "src" in result.backtrack_targets

    def test_try_register_none_value_allowed(self) -> None:
        solver = ConstraintSolver()
        solver.try_register("col", None, is_unique=True)
        result = solver.try_register("col", None, is_unique=True)
        assert result.is_registered is True

    def test_unregister_then_reregister(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, is_unique=True)
        solver.unregister("col", 1)
        assert solver.check_and_register("col", 1, is_unique=True) is True

    def test_check_composite_unique(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register_composite("idx", (1, "a")) is True
        assert solver.check_and_register_composite("idx", (1, "b")) is True
        assert solver.check_and_register_composite("idx", (1, "a")) is False

    def test_check_composite_with_null(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register_composite("idx", (1, None)) is True
        assert solver.check_and_register_composite("idx", (1, None)) is True

    def test_reset_clears_all(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col1", 1, is_unique=True)
        solver.check_and_register("col2", 2, is_unique=True)
        solver.reset()
        assert solver.check_and_register("col1", 1, is_unique=True) is True
        assert solver.check_and_register("col2", 2, is_unique=True) is True

    def test_reset_column(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col1", 1, is_unique=True)
        solver.check_and_register("col2", 2, is_unique=True)
        solver.reset_column("col1")
        assert solver.check_and_register("col1", 1, is_unique=True) is True
        assert solver.check_and_register("col2", 2, is_unique=True) is False

    def test_probabilistic_mode_deterministic_hash(self) -> None:
        solver = ConstraintSolver(probabilistic=True)
        assert solver.check_and_register("col", 42, is_unique=True) is True
        assert solver.check_and_register("col", 42, is_unique=True) is False
        assert solver.check_and_register("col", 43, is_unique=True) is True

    def test_probabilistic_reset_column(self) -> None:
        solver = ConstraintSolver(probabilistic=True)
        solver.check_and_register("col", 1, is_unique=True)
        solver.reset_column("col")
        assert solver.check_and_register("col", 1, is_unique=True) is True

    def test_unregister_composite(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register_composite("idx", (1, "a"))
        solver.unregister_composite("idx", (1, "a"))
        assert solver.check_and_register_composite("idx", (1, "a")) is True


class TestGetSeen:
    """Tests for the ``get_seen`` method (UNIQUE retry-with-exclude support).

    ``get_seen`` exposes a per-column view of the registered unique values so
    that ``DataStream`` can pass them to the generator as ``exclude_values``,
    letting the generator avoid producing values already known to be in use.
    This is the root-cause fix for the "UNIQUE + semantic generators" failure
    pattern where ``faker.email()`` etc. produce duplicates on large row counts.
    """

    def test_get_seen_returns_empty_set_for_unknown_column(self) -> None:
        solver = ConstraintSolver()
        seen = solver.get_seen("col")
        assert isinstance(seen, set)
        assert len(seen) == 0

    def test_get_seen_returns_registered_values(self) -> None:
        solver = ConstraintSolver()
        solver._register("col", 1)
        solver._register("col", 2)
        solver._register("col", 3)
        seen = solver.get_seen("col")
        assert seen == {1, 2, 3}

    def test_get_seen_isolates_columns(self) -> None:
        """get_seen returns only values for the requested column."""
        solver = ConstraintSolver()
        solver._register("col_a", 1)
        solver._register("col_b", 100)
        assert solver.get_seen("col_a") == {1}
        assert solver.get_seen("col_b") == {100}

    def test_get_seen_returns_independent_copy(self) -> None:
        """get_seen must return a copy — mutating it must not affect the solver's state.

        Without this guarantee, a generator that accidentally mutates
        ``exclude_values`` could corrupt the solver's seen set.
        """
        solver = ConstraintSolver()
        solver._register("col", 1)
        seen = solver.get_seen("col")
        seen.add(999)  # Mutate the returned set
        # Internal state must be unaffected
        assert solver._is_seen("col", 1)
        assert not solver._is_seen("col", 999)

    def test_get_seen_reflects_unregistration(self) -> None:
        """get_seen reflects values removed via unregister()."""
        solver = ConstraintSolver()
        solver._register("col", 1)
        solver._register("col", 2)
        solver.unregister("col", 1)
        assert solver.get_seen("col") == {2}

    def test_get_seen_returns_empty_after_reset(self) -> None:
        solver = ConstraintSolver()
        solver._register("col", 1)
        solver._register("col", 2)
        solver.reset()
        assert solver.get_seen("col") == set()

    def test_get_seen_returns_empty_after_reset_column(self) -> None:
        solver = ConstraintSolver()
        solver._register("col", 1)
        solver.reset_column("col")
        assert solver.get_seen("col") == set()

    def test_get_seen_probabilistic_mode(self) -> None:
        """Probabilistic mode returns an empty set (not the hash set).

        Previously this returned the SHA256 hash set, but downstream
        ``_dispatch.generate`` compares generated raw values against
        ``exclude_values`` — comparing a raw value to a hash always
        mismatches, so the exclude fast-path was a silent no-op while
        appearing to work. Returning an empty set forces dispatch to
        skip the (broken) exclude check and rely solely on
        ``try_register`` hash-collision detection to trigger backtracking.
        """
        solver = ConstraintSolver(probabilistic=True)
        solver._register("col", 42)
        seen = solver.get_seen("col")
        assert isinstance(seen, set)
        assert len(seen) == 0  # Empty: probabilistic mode cannot do value-based exclude
