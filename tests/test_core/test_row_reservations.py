"""A row attempt releases only the UNIQUE reservations that it owns."""

from __future__ import annotations

import pytest

from sqlseed.core import stream
from sqlseed.core.constraints import ConstraintSolver


def test_rollback_releases_current_row_and_keeps_prior_rows_reserved() -> None:
    if not hasattr(stream, "_RowReservations"):
        pytest.fail("Row reservation ownership has not been implemented")
    solver = ConstraintSolver()
    assert solver.check_and_register("code", 1, is_unique=True)
    assert solver.check_and_register("code", 2, is_unique=True)
    assert solver.check_and_register_composite("pair", (1, "old"))
    assert solver.check_and_register_composite("pair", (2, "current"))
    row = {"code": 2, "label": "current"}
    generated = dict(row)
    reservations = stream._RowReservations(row, generated)
    reservations.composites.append(("pair", (2, "current")))

    reservations.rollback(solver)

    assert not row
    assert not generated
    assert not reservations.composites
    assert not solver.check_and_register("code", 1, is_unique=True)
    assert not solver.check_and_register_composite("pair", (1, "old"))
    assert solver.check_and_register("code", 2, is_unique=True)
    assert solver.check_and_register_composite("pair", (2, "current"))
    reservations.rollback(solver)
    assert not solver.check_and_register("code", 2, is_unique=True)
    assert not solver.check_and_register_composite("pair", (2, "current"))
