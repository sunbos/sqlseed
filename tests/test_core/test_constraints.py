from __future__ import annotations

from sqlseed.core.constraints import ConstraintSolver, RegisterResult


class TestConstraintSolver:
    def test_check_and_register_non_unique(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, unique=False) is True
        assert solver.check_and_register("col", 1, unique=False) is True

    def test_check_and_register_unique_first_time(self) -> None:
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, unique=True) is True

    def test_check_and_register_unique_duplicate(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, unique=True)
        assert solver.check_and_register("col", 1, unique=True) is False

    def test_try_register_returns_backtrack(self) -> None:
        solver = ConstraintSolver()
        solver.try_register("col", 1, unique=True)
        result = solver.try_register("col", 1, unique=True, source_columns=["src"])
        assert isinstance(result, RegisterResult)
        assert result.registered is False
        assert result.need_backtrack is True
        assert "src" in result.backtrack_targets

    def test_try_register_none_value_allowed(self) -> None:
        solver = ConstraintSolver()
        solver.try_register("col", None, unique=True)
        result = solver.try_register("col", None, unique=True)
        assert result.registered is True

    def test_unregister_then_reregister(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, unique=True)
        solver.unregister("col", 1)
        assert solver.check_and_register("col", 1, unique=True) is True

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
        solver.check_and_register("col1", 1, unique=True)
        solver.check_and_register("col2", 2, unique=True)
        solver.reset()
        assert solver.check_and_register("col1", 1, unique=True) is True
        assert solver.check_and_register("col2", 2, unique=True) is True

    def test_reset_column(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register("col1", 1, unique=True)
        solver.check_and_register("col2", 2, unique=True)
        solver.reset_column("col1")
        assert solver.check_and_register("col1", 1, unique=True) is True
        assert solver.check_and_register("col2", 2, unique=True) is False

    def test_probabilistic_mode_deterministic_hash(self) -> None:
        solver = ConstraintSolver(probabilistic=True)
        assert solver.check_and_register("col", 42, unique=True) is True
        assert solver.check_and_register("col", 42, unique=True) is False
        assert solver.check_and_register("col", 43, unique=True) is True

    def test_probabilistic_reset_column(self) -> None:
        solver = ConstraintSolver(probabilistic=True)
        solver.check_and_register("col", 1, unique=True)
        solver.reset_column("col")
        assert solver.check_and_register("col", 1, unique=True) is True

    def test_unregister_composite(self) -> None:
        solver = ConstraintSolver()
        solver.check_and_register_composite("idx", (1, "a"))
        solver.unregister_composite("idx", (1, "a"))
        assert solver.check_and_register_composite("idx", (1, "a")) is True
