"""End-to-end order example checks real generated SQLite data and replay."""

from __future__ import annotations

import importlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed import fill_from_config, load_config
from sqlseed.generators import ConfigurationError

if TYPE_CHECKING:
    from types import ModuleType


def runner() -> ModuleType:
    entry = Path(__file__).parents[1] / "examples" / "order_workflow" / "run.py"
    assert entry.is_file(), "The runnable order workflow entry is not implemented yet"
    return importlib.import_module("examples.order_workflow.run")


def completed(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    output = tmp_path / "order-demo"
    return output, runner().run_workflow(output)


def rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with closing(sqlite3.connect(path)) as db:
        return {
            table: db.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
            for table in ("users", "products", "orders", "order_items")
        }


def test_real_order_data_obeys_relationships_and_matches_report(tmp_path: Path) -> None:
    output, report = completed(tmp_path)
    actual = rows(output / "orders.db")
    assert {table: len(records) for table, records in actual.items()} == {
        "users": 12,
        "products": 8,
        "orders": 24,
        "order_items": 48,
    }
    assert report["validation"]["row_counts"] == {table: len(records) for table, records in actual.items()}
    assert report["validation"]["ok"] is True
    assert json.loads((output / "report.json").read_text(encoding="utf-8")) == report
    with closing(sqlite3.connect(output / "orders.db")) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert (
            db.execute(
                "SELECT COUNT(*) FROM order_items i JOIN products p ON p.id=i.product_id "
                "JOIN orders o ON o.id=i.order_id WHERE i.unit_price_cents=p.price_cents "
                "AND i.line_total_cents=i.quantity*i.unit_price_cents AND i.placed_at=o.created_at"
            ).fetchone()[0]
            == 48
        )
        assert db.execute("SELECT COUNT(DISTINCT order_id) FROM order_items").fetchone()[0] == 24
        assert db.execute("SELECT DISTINCT status FROM orders ORDER BY status").fetchall() == [
            ("paid",),
            ("pending",),
            ("shipped",),
        ]
        assert (
            db.execute(
                "SELECT COUNT(*) FROM orders WHERE created_at >= '2026-01-02' AND created_at < '2026-01-09' "
                "AND (paid_at IS NULL OR paid_at>=created_at) AND (shipped_at IS NULL OR shipped_at>=paid_at)"
            ).fetchone()[0]
            == 24
        )


def test_two_new_databases_are_logically_identical(tmp_path: Path) -> None:
    output, report = completed(tmp_path)
    assert rows(output / "orders.db") == rows(output / "verification" / "second.db")
    assert report["reproducibility"]["logical_data_equal"] is True
    assert report["reproducibility"]["first_sha256"] == report["reproducibility"]["second_sha256"]


def test_bad_rule_really_fails_and_saved_correction_replays(tmp_path: Path) -> None:
    output, report = completed(tmp_path)
    failed = report["failed_rule"]
    assert failed["expected_failure"] is True
    assert "price_cents" in failed["diagnostic"]
    assert "CHECK" in failed["diagnostic"] or "range" in failed["diagnostic"]
    assert all(not records for records in rows(output / "verification" / "bad.db").values())
    with pytest.raises(ConfigurationError, match="price_cents") as caught:
        fill_from_config(str(output / "verification" / "bad-rule.yaml"), skip_ai=True)
    assert "[-100, -1] has no overlap with CHECK constraint [100, 100000]" in str(caught.value)
    config_path = output / "replay.yaml"
    assert load_config(str(config_path)).connection_target == str(output / "replay.db")
    assert all(not records for records in rows(output / "replay.db").values())
    results = fill_from_config(str(config_path), skip_ai=True)
    assert all(not result.errors for result in results)
    assert sum(result.count for result in results) == 92
    assert rows(output / "replay.db") == rows(output / "orders.db")


def test_saved_rules_replay_from_cli(tmp_path: Path) -> None:
    cli = pytest.importorskip("sqlseed_cli.main").cli
    cli_runner = pytest.importorskip("click.testing").CliRunner()
    output = tmp_path / "CLI output"
    runner().run_workflow(output)
    result = cli_runner.invoke(cli, ["fill", "--config", str(output / "replay.yaml"), "--no-ai"])
    assert result.exit_code == 0, result.output
    assert rows(output / "replay.db") == rows(output / "orders.db")


def test_database_itself_rejects_invalid_business_data(tmp_path: Path) -> None:
    output, _ = completed(tmp_path)
    with closing(sqlite3.connect(output / "orders.db")) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for statement in (
            "UPDATE orders SET user_id=99999 WHERE id=1",
            "UPDATE products SET price_cents=-1 WHERE id=1",
            "UPDATE orders SET shipped_at='2020-01-01' WHERE status='shipped'",
            "UPDATE users SET email=(SELECT email FROM users WHERE id=1) WHERE id=2",
            "UPDATE order_items SET line_total_cents=0 WHERE id=1",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(statement)
            db.rollback()


def test_existing_output_is_never_modified(tmp_path: Path) -> None:
    output = tmp_path / "already-exists"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_bytes(b"user-owned content")
    workflow = runner()
    with pytest.raises(FileExistsError):
        workflow.run_workflow(output)
    assert sentinel.read_bytes() == b"user-owned content"
    assert list(output.iterdir()) == [sentinel]
