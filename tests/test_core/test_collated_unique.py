"""Real SQLite oracles for in-stream and existing collated UNIQUE keys."""

from __future__ import annotations

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests.sqlite_helpers import sqlite_connection


@pytest.mark.parametrize("collation", ["NOCASE", "RTRIM", "BINARY"])
@pytest.mark.parametrize("index_only", [False, True])
def test_collated_preview_and_repeated_append(tmp_path, collation, index_only):
    path = tmp_path / "keys.db"
    suffix = "" if index_only else f" COLLATE {collation} UNIQUE"
    ddl = f"CREATE TABLE items (code TEXT NOT NULL{suffix})"
    if index_only:
        ddl += f"; CREATE UNIQUE INDEX code_key ON items(code COLLATE {collation})"
    values = [v for i in range(24) for v in (f"sku{i:02}", f"SKU{i:02}" if collation != "RTRIM" else f"sku{i:02}  ")]
    columns = {"code": {"generator": "choice", "params": {"choices": values}}}
    with sqlite_connection(path) as db:
        db.executescript(ddl)
        db.executemany("INSERT INTO items VALUES (?)", [("sku00",), ("sku01",)])
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        rows = orch.preview_table("items", count=10, columns=columns, seed=1530)
        # Insertion into a real duplicate schema validates preview, including existing keys.
        with sqlite_connection(tmp_path / "oracle.db") as db:
            db.executescript(ddl)
            db.executemany("INSERT INTO items VALUES (?)", [("sku00",), ("sku01",)])
            db.executemany("INSERT INTO items VALUES (?)", [(row["code"],) for row in rows])
        for _ in range(2):
            result = orch.fill_table("items", count=10, columns=columns, seed=1530, batch_size=4, skip_ai=True)
            assert not result.errors
            assert result.count == 10
        assert orch.get_row_count("items") == 22


@pytest.mark.parametrize(
    "collation,left,right",
    [
        ("NOCASE", "abc", "ABC"),
        ("NOCASE", "Ä", "ä"),
        ("NOCASE", "a\0x", "A\0y"),
        ("NOCASE", "a\0x", "A\0zz"),
        ("NOCASE", "a\0ä", "A\0xy"),
        ("RTRIM", "abc", "abc  "),
        ("RTRIM", "abc", "abc\t"),
        ("RTRIM", "abc", "abc\u00a0"),
        ("BINARY", "abc", "ABC"),
        ("NOCASE", None, None),
        ("RTRIM", None, None),
    ],
)
@pytest.mark.parametrize("probabilistic", [False, True])
def test_sqlite_equality_and_reservation_release(tmp_path, collation, left, right, probabilistic):
    import sqlite3

    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.database._unique_keys import UniqueKey, sqlite_key_normalizer

    with sqlite_connection(tmp_path / "oracle.db") as db:
        db.execute(f"CREATE TABLE items (code TEXT COLLATE {collation} UNIQUE)")
        db.execute("INSERT INTO items VALUES (?)", (left,))
        try:
            db.execute("INSERT INTO items VALUES (?)", (right,))
            accepted = True
        except sqlite3.IntegrityError:
            accepted = False
    normalize = sqlite_key_normalizer(UniqueKey(("code",), (collation,)))
    solver = ConstraintSolver(
        probabilistic=probabilistic, key_normalizers={("code",): [normalize]} if normalize else {}
    )
    assert solver.check_and_register("code", left, True)
    assert solver.check_and_register("code", right, True) is accepted
    if not accepted:
        solver.unregister("code", left)
        assert solver.check_and_register("code", right, True)
    solver.reset_column("code")
    assert solver.check_and_register("code", left, True)
    solver.reset()
    assert solver.check_and_register("code", left, True)


@pytest.mark.parametrize("probabilistic", [False, True])
@pytest.mark.parametrize("replacement", ["abc", "ABC", "abc  "])
def test_reset_column_preserves_other_columns_and_composite_keys(probabilistic, replacement):
    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.database._unique_keys import UniqueKey, sqlite_key_normalizer

    normalizers = {}
    for key in (
        UniqueKey(("code",), ("NOCASE",)),
        UniqueKey(("code",), ("RTRIM",)),
        UniqueKey(("other",), ("NOCASE",)),
        UniqueKey(("code", "other"), ("NOCASE", "RTRIM")),
    ):
        normalize = sqlite_key_normalizer(key)
        assert normalize is not None
        normalizers.setdefault(key.columns, []).append(normalize)
    solver = ConstraintSolver(probabilistic=probabilistic, key_normalizers=normalizers)
    assert solver.check_and_register("code", "abc", True)
    assert solver.check_and_register("other", "hold", True)
    assert solver.check_and_register_composite("pair", ("abc", "pair  "), columns=["code", "other"])
    assert not solver.check_and_register("code", replacement, True)

    solver.reset_column("code")
    solver.reset_column("code")

    assert solver.check_and_register("code", replacement, True)
    assert not solver.check_and_register("other", "HOLD", True)
    assert not solver.check_and_register_composite("pair", ("ABC", "pair"), columns=["code", "other"])


@pytest.mark.parametrize("composite", [False, True])
def test_multiple_index_collations_and_nulls(tmp_path, composite):
    path = tmp_path / "multiple.db"
    ending = ", bucket" if composite else ""
    ddl = (
        "CREATE TABLE items(code TEXT, bucket INTEGER NOT NULL);"
        f"CREATE UNIQUE INDEX k1 ON items(code COLLATE NOCASE{ending});"
        f"CREATE UNIQUE INDEX k2 ON items(code COLLATE RTRIM{ending});"
    )
    values = [v for i in range(40) for v in (f"sku{i:02}", f"SKU{i:02}", f"sku{i:02}  ")]
    columns = {
        "code": {"generator": "choice", "params": {"choices": values}},
        "bucket": {"generator": "choice", "params": {"choices": [1, 2]}},
    }
    with sqlite_connection(path) as db:
        db.executescript(ddl)
        db.execute("INSERT INTO items VALUES ('sku00', 1)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        for _ in range(2):
            result = orch.fill_table("items", count=15, columns=columns, seed=1530, batch_size=5, skip_ai=True)
            assert result.count == 15
            assert not result.errors
        columns["code"] = {"generator": "choice", "params": {"choices": values}, "null_ratio": 1.0}
        result = orch.fill_table("items", count=5, columns=columns, seed=1530, skip_ai=True)
        assert result.count == 5
        assert not result.errors
        assert orch.get_row_count("items") == 36


@pytest.mark.parametrize("composite", [False, True])
def test_rejected_equivalent_does_not_release_owned_key(composite):
    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.database._unique_keys import UniqueKey, sqlite_key_normalizer

    columns = ("code", "bucket") if composite else ("code",)
    normalize = sqlite_key_normalizer(UniqueKey(columns, ("NOCASE", "BINARY") if composite else ("NOCASE",)))
    assert normalize is not None
    solver = ConstraintSolver(key_normalizers={columns: [normalize]})
    if composite:
        assert solver.check_and_register_composite("pair", ("abc", 1), columns=list(columns))
        assert not solver.check_and_register_composite("pair", ("ABC", 1), columns=list(columns))
        solver.unregister_composite("pair", ("ABC", 1))
        assert not solver.check_and_register_composite("pair", ("ABC", 1), columns=list(columns))
        solver.unregister_composite("pair", ("abc", 1))
        assert solver.check_and_register_composite("pair", ("ABC", 1), columns=list(columns))
    else:
        assert solver.check_and_register("code", "abc", True)
        assert not solver.check_and_register("code", "ABC", True)
        solver.unregister("code", "ABC")
        assert not solver.check_and_register("code", "ABC", True)
        assert solver.get_seen("code") == {"abc"}
        solver.unregister("code", "abc")
        assert solver.check_and_register("code", "ABC", True)


@pytest.mark.parametrize("repeated", [False, True])
def test_existing_index_probe_preserves_every_term(tmp_path, repeated):
    from sqlseed.core.orchestrator._specs import SpecResolverMixin
    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    class Resolver(SpecResolverMixin):
        def __init__(self, db):
            self._db = db

    with SQLAlchemyAdapter() as db:
        db.connect(str(tmp_path / "probe.db"))
        db.execute("CREATE TABLE items(code TEXT)").close()
        terms = "code COLLATE NOCASE, code COLLATE RTRIM" if repeated else "code COLLATE NOCASE"
        db.execute(f"CREATE UNIQUE INDEX k ON items({terms})").close()
        db.execute("INSERT INTO items VALUES ('abc')").close()
        check = Resolver(db)._existing_key_checker("items")
        assert check({"code": "abc"})
        assert check({"code": "ABC"}) is (not repeated)
        assert not check({"code": "abc  "})


@pytest.mark.parametrize("collation", ["NOCASE", "RTRIM"])
@pytest.mark.parametrize("index_only", [False, True])
def test_empty_table_collated_preview_and_fill(tmp_path, collation, index_only):
    path = tmp_path / "empty.db"
    suffix = "" if index_only else f" COLLATE {collation} UNIQUE"
    ddl = f"CREATE TABLE items (code TEXT NOT NULL{suffix})"
    if index_only:
        ddl += f"; CREATE UNIQUE INDEX code_key ON items(code COLLATE {collation})"
    values = [
        value for i in range(24) for value in (f"sku{i:02}", f"SKU{i:02}" if collation == "NOCASE" else f"sku{i:02}  ")
    ]
    columns = {"code": {"generator": "choice", "params": {"choices": values}}}
    with sqlite_connection(path) as db:
        db.executescript(ddl)
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        rows = orch.preview_table("items", count=10, columns=columns, seed=1530)
        assert len(rows) == 10
        assert orch.get_row_count("items") == 0
        with sqlite_connection(tmp_path / "empty-oracle.db") as db:
            db.executescript(ddl)
            db.executemany("INSERT INTO items VALUES (?)", [(row["code"],) for row in rows])
        result = orch.fill_table("items", count=10, columns=columns, seed=1530, batch_size=4, skip_ai=True)
        assert not result.errors
        assert result.count == 10
        assert orch.get_row_count("items") == 10
