"""Generate, diagnose and replay a SQLite order workflow through public APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import sqlite3
from contextlib import closing
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

from sqlseed import connect, fill_from_config
from sqlseed.generators import ConfigurationError

HERE = Path(__file__).resolve().parent
TABLES = ("users", "products", "orders", "order_items")


def create_database(path: Path, schema: str) -> None:
    """Create only schema in a new file, using the production public connection."""
    path.touch(exist_ok=False)
    with connect(str(path), provider="base", optimize_pragma=False) as database:
        for statement in schema.split(";"):
            if statement.strip():
                database.execute(statement).close()


def write_config(path: Path, database: Path, rules: dict[str, Any]) -> None:
    """Bind a copy of the saved rules to a specific newly created database."""
    document = {**deepcopy(rules), "db_path": str(database)}
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")


def logical_data(path: Path) -> dict[str, list[list[Any]]]:
    """Read ordered rows without SQLite physical layout or timing metadata."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        return {
            table: [list(row) for row in database.execute(f'SELECT * FROM "{table}" ORDER BY id')] for table in TABLES
        }


def digest(value: Any) -> str:
    """Hash stable JSON values used to compare logical outputs."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_database(path: Path, expected: dict[str, int]) -> dict[str, Any]:
    """Verify actual counts, SQLite constraints and the stated business rules."""
    checks = {
        "item_price_matches_product": (
            "SELECT COUNT(*) FROM order_items i JOIN products p ON p.id=i.product_id "
            "WHERE i.unit_price_cents != p.price_cents"
        ),
        "line_total_matches_quantity": (
            "SELECT COUNT(*) FROM order_items WHERE line_total_cents != quantity*unit_price_cents"
        ),
        "item_time_matches_order": (
            "SELECT COUNT(*) FROM order_items i JOIN orders o ON o.id=i.order_id WHERE i.placed_at != o.created_at"
        ),
        "every_order_has_items": (
            "SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id)"
        ),
        "order_after_user_creation": (
            "SELECT COUNT(*) FROM orders o JOIN users u ON u.id=o.user_id WHERE o.created_at<u.created_at"
        ),
        "order_time_ordering": ("SELECT COUNT(*) FROM orders WHERE paid_at<created_at OR shipped_at<paid_at"),
    }
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        counts = {table: database.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}
        integrity = [row[0] for row in database.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in database.execute("PRAGMA foreign_key_check")]
        violations = {name: database.execute(query).fetchone()[0] for name, query in checks.items()}
        totals = [
            {"order_no": row[0], "line_count": row[1], "total_cents": row[2]}
            for row in database.execute(
                "SELECT o.order_no,COUNT(i.id),SUM(i.line_total_cents) FROM orders o "
                "JOIN order_items i ON i.order_id=o.id GROUP BY o.id ORDER BY o.id"
            )
        ]
    return {
        "ok": counts == expected and integrity == ["ok"] and not foreign_keys and not any(violations.values()),
        "row_counts": counts,
        "expected_row_counts": expected,
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "business_violations": violations,
        "order_totals_query": totals,
    }


def generate(config_path: Path) -> list[dict[str, Any]]:
    """Generate every record through sqlseed; retain actual committed counts."""
    results = fill_from_config(str(config_path), skip_ai=True)
    summaries = [
        {"table": result.table_name, "count": result.count, "batches": result.batch_count, "errors": result.errors}
        for result in results
    ]
    errors = [f"{result.table_name}: {error}" for result in results for error in result.errors]
    if errors:
        raise RuntimeError("; ".join(errors))
    return summaries


def demonstrate_rejected_rule(verification: Path, schema: str, rules: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Record a rejected rule and verify that it leaves the database empty."""
    bad_database = verification / "bad.db"
    create_database(bad_database, schema)
    bad_rules = deepcopy(rules)
    bad_rules["tables"] = [table for table in bad_rules["tables"] if table["name"] == "products"]
    price_rule = next(column for column in bad_rules["tables"][0]["columns"] if column["name"] == "price_cents")
    price_rule["params"] = {"min_value": -100, "max_value": -1}
    bad_config = verification / "bad-rule.yaml"
    write_config(bad_config, bad_database, bad_rules)
    before_row_counts = {table: len(rows) for table, rows in logical_data(bad_database).items()}
    try:
        generate(bad_config)
    except ConfigurationError as error:
        diagnostic = str(error)
        if "price_cents" not in diagnostic or ("CHECK" not in diagnostic and "range" not in diagnostic):
            raise
        after_row_counts = {table: len(rows) for table, rows in logical_data(bad_database).items()}
        failed_rule = {
            "expected_failure": True,
            "table": "products",
            "column": "price_cents",
            "exception_type": type(error).__name__,
            "diagnostic": diagnostic,
            "before_row_counts": before_row_counts,
            "after_row_counts": after_row_counts,
            "correction": {"min_value": 500, "max_value": 5000},
        }
        if any(after_row_counts.values()):
            raise RuntimeError("The rejected rule unexpectedly committed data") from error
        return bad_config, failed_rule
    raise RuntimeError("The deliberately invalid price rule unexpectedly succeeded")


def run_workflow(output_dir: Path) -> dict[str, Any]:
    """Run the demonstration in a new directory, refusing any existing target."""
    output = output_dir.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=False)
    verification = output / "verification"
    verification.mkdir()
    schema = (HERE / "schema.sql").read_text(encoding="utf-8")
    rules = yaml.safe_load((HERE / "rules.yaml").read_text(encoding="utf-8"))
    expected = {table["name"]: table["count"] for table in rules["tables"]}
    (output / "schema.sql").write_text(schema, encoding="utf-8")

    bad_config, failed_rule = demonstrate_rejected_rule(verification, schema, rules)

    main_database = output / "orders.db"
    main_config = output / "rules.yaml"
    create_database(main_database, schema)
    write_config(main_config, main_database, rules)
    generated = generate(main_config)
    validation = validate_database(main_database, expected)
    if not validation["ok"]:
        raise RuntimeError(f"Generated order data failed validation: {validation}")

    second_database = verification / "second.db"
    second_config = verification / "second.yaml"
    create_database(second_database, schema)
    write_config(second_config, second_database, rules)
    second_generated = generate(second_config)
    second_validation = validate_database(second_database, expected)
    first_data, second_data = logical_data(main_database), logical_data(second_database)
    if not second_validation["ok"] or first_data != second_data:
        raise RuntimeError("Same rules and seeds did not reproduce identical logical data")

    # Leave a fresh schema ready for the user's first CLI or Web replay.
    replay_database = output / "replay.db"
    create_database(replay_database, schema)
    write_config(output / "replay.yaml", replay_database, rules)
    report = {
        "scenario": "SQLite 订单生成、诊断与离线重放",
        "conditions": {
            "provider": "base",
            "locale": "en_US",
            "table_seeds": {table["name"]: table["seed"] for table in rules["tables"]},
            "order_date_range": ["2026-01-02", "2026-01-08"],
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "sqlseed_version": version("sqlseed"),
            "dependency_versions": {name: version(name) for name in ("SQLAlchemy", "pydantic", "PyYAML")},
            "schema_sha256": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
            "rules_sha256": digest(rules),
            "ai_called": False,
        },
        "artifacts": {
            "database": str(main_database),
            "rules": str(main_config),
            "replay_database": str(replay_database),
            "replay_rules": str(output / "replay.yaml"),
            "bad_rule": str(bad_config),
        },
        "generated": generated,
        "failed_rule": failed_rule,
        "validation": validation,
        "reproducibility": {
            "logical_data_equal": first_data == second_data,
            "first_sha256": digest(first_data),
            "second_sha256": digest(second_data),
            "second_generated": second_generated,
        },
        "limitations": [
            "仅验收 SQLite。未运行 PostgreSQL。",
            "固定 seed 的复现条件是相同软件环境、schema、规则和新的空数据库。",
            "订单总额通过只读 SUM 查询展示，不是生成引擎维护的跨表聚合字段。",
            "本示例不包含库存扣减、退款、税费、跨表状态机或真实 AI 分析。",
            "replay.db 为尚未写入的重放目标。同一目标重复追加不保证 UNIQUE 成功。",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """Run the example from any working directory using an installed sqlseed."""
    parser = argparse.ArgumentParser(description="生成可复验的 SQLite 四表订单示例。已有目录绝不覆盖。")
    parser.add_argument("--output-dir", type=Path, required=True, help="必须是尚不存在的新目录")
    args = parser.parse_args()
    try:
        report = run_workflow(args.output_dir)
    except Exception as error:
        parser.exit(1, f"订单示例失败：{type(error).__name__}: {error}\n")
    print(f"生成并验证 {sum(report['validation']['row_counts'].values())} 行，两个新库逻辑数据一致。")
    print(f"数据库：{report['artifacts']['database']}")
    print(f"验收报告：{args.output_dir.absolute() / 'report.json'}")
    print(f"离线重放：sqlseed fill --config {shlex.quote(report['artifacts']['replay_rules'])} --no-ai")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
