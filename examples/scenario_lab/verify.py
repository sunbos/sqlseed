"""在临时副本上运行真实 core；--web 加测正式 Web 结构、预览与压力边界。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing, redirect_stdout
from pathlib import Path
from typing import Any

import yaml

from sqlseed import fill_from_config

if __package__:
    from .build import HERE, build_database
    from .validate import validate_database
else:
    from build import HERE, build_database
    from validate import validate_database


def verify(*, source: Path | None = None, web: bool = False) -> dict[str, Any]:
    """所有生成仅发生在自动清理的临时副本。"""
    with tempfile.TemporaryDirectory(prefix="sqlseed-scenario-check-") as directory:
        target = Path(directory) / "working-copy.db"
        if source is None:
            build_database(target)
        else:
            resolved = source.expanduser().resolve(strict=True)
            with (
                closing(sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)) as original,
                closing(sqlite3.connect(target)) as copy,
            ):
                original.backup(copy)
        before = validate_database(target)
        if not before["ok"]:
            raise ValueError(f"输入夹具未通过验证：{before}")
        document = yaml.safe_load((HERE / "baseline.yaml").read_text(encoding="utf-8"))
        report: dict[str, Any] = {"before": before, "temporary_copy_only": True}
        if web:
            from sqlseed_web.state import UIState
            from sqlseed_web.workbench_runtime import check_document
            from sqlseed_web.workbench_schema import inspect_connection

            registry = UIState()
            conn = registry.add_connection(str(target), provider="base")
            try:
                with registry.connection_operation(conn.conn_id):
                    schema = inspect_connection(conn)
                    preview = check_document(conn, document, schema["schema_hash"], preview=True, count=10)
                    pressure = yaml.safe_load((HERE / "stress.yaml").read_text(encoding="utf-8"))
                    blocked = check_document(conn, pressure, schema["schema_hash"])
                report["web"] = {
                    "tables": len(schema["tables"]),
                    "relations": len(schema["edges"]),
                    "baseline_ok": preview["ok"],
                    "baseline_issues": preview["issues"],
                    "baseline_order": preview["order"],
                    "sample_counts": {name: len(rows) for name, rows in preview["samples"].items()},
                    "stress_ok": blocked["ok"],
                    "stress_issues": blocked["issues"],
                }
                if not preview["ok"]:
                    raise ValueError(f"Web baseline 检查失败：{preview['issues']}")
                codes = {issue["code"] for issue in blocked["issues"]}
                if blocked["ok"] or not {"composite_fk_width", "cross_table_cycle"} <= codes:
                    raise ValueError(f"压力边界与预期不符：{blocked['issues']}")
            finally:
                registry.close_connection(conn.conn_id)
        bound = Path(directory) / "bound-baseline.yaml"
        bound.write_text(yaml.safe_dump({**document, "db_path": str(target)}, allow_unicode=True), encoding="utf-8")
        results = fill_from_config(str(bound), skip_ai=True)
        report["core_results"] = [
            {
                "table": result.table_name,
                "count": result.count,
                "errors": result.errors,
                "batch_count": result.batch_count,
            }
            for result in results
        ]
        after = validate_database(target)
        report["after"] = after
        expected = {table["name"]: table["count"] for table in document["tables"]}
        changes = {name: after["row_counts"][name] - before["row_counts"][name] for name in before["row_counts"]}
        report["rows_added"] = changes
        report["ok"] = (
            after["ok"]
            and all(not result.errors for result in results)
            and all(count == expected.get(name, 0) for name, count in changes.items())
        )
        if not report["ok"]:
            raise ValueError(f"baseline 执行或约束验证失败：{report}")
        return report


def main() -> None:
    """运行副本验收并输出 JSON 报告。"""
    from sqlseed._utils.logger import configure_logging

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="只读打开此库，所有生成发生在临时副本")
    parser.add_argument("--web", action="store_true", help="同时调用已安装 sqlseed-web 的真实 schema/check 实现")
    args = parser.parse_args()
    configure_logging("ERROR")
    # Core's progress renderer writes to stdout; keep it separate from the
    # machine-readable report without changing the library's progress code.
    with redirect_stdout(sys.stderr):
        report = verify(source=args.source, web=args.web)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
