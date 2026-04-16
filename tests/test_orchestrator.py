from __future__ import annotations

import sqlite3
from typing import Any

from sqlseed.config.models import ColumnConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl


class TestDataOrchestrator:
    def test_fill_basic(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=100)
            assert result.count == 100
            assert result.elapsed > 0

    def test_fill_with_seed(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result1 = orch.preview_table("users", count=5, seed=42)
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result2 = orch.preview_table("users", count=5, seed=42)
        assert result1 == result2

    def test_fill_with_clear(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=50)
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=30, clear_before=True)
            assert result.count == 30

    def test_fill_with_columns(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table(
                "users",
                count=10,
                columns={
                    "name": "name",
                    "email": "email",
                    "age": {"type": "integer", "min_value": 18, "max_value": 65},
                },
            )
            assert result.count == 10

    def test_preview(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            rows = orch.preview_table("users", count=3)
            assert len(rows) == 3
            assert "name" in rows[0]

    def test_report(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            report = orch.report()
            assert "users" in report

    def test_fill_with_foreign_key(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=10)
            result = orch.fill_table("orders", count=50)
            assert result.count == 50

    def test_report_not_connected(self) -> None:
        orch = DataOrchestrator("/tmp/nonexistent.db", provider_name="base")
        report = orch.report()
        assert "Not connected" in report

    def test_fill_with_column_configs(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            col_configs = [
                ColumnConfig(name="name", generator="name"),
                ColumnConfig(name="email", generator="email"),
            ]
            result = orch.fill_table("users", count=5, column_configs=col_configs)
            assert result.count == 5

    def test_fill_with_foreign_key_config(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=10)
            result = orch.fill_table(
                "orders",
                count=20,
                columns={
                    "user_id": {
                        "type": "foreign_key",
                        "ref_table": "users",
                        "ref_column": "id",
                        "strategy": "random",
                    },
                },
            )
            assert result.count == 20

    def test_fill_nonexistent_table(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("nonexistent_table", count=10)
            assert len(result.errors) > 0

    def test_fill_with_mimesis_provider(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="mimesis") as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_with_faker_provider(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="faker") as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_no_optimize_pragma(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base", optimize_pragma=False) as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_with_transform_batch_plugin(self, tmp_db) -> None:
        transform_log: list[str] = []

        class UpperCasePlugin:
            @hookimpl
            def sqlseed_transform_batch(self, table_name: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
                transform_log.append(table_name)
                for row in batch:
                    if "name" in row and isinstance(row["name"], str):
                        row["name"] = row["name"].upper()
                return batch

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(UpperCasePlugin())
            result = orch.fill_table("users", count=5)
            assert result.count == 5
            assert "users" in transform_log

    def test_preview_with_transform_batch_plugin(self, tmp_db) -> None:
        class TagPlugin:
            @hookimpl
            def sqlseed_transform_batch(self, table_name: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
                for row in batch:
                    row["_source"] = "plugin"
                return batch

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(TagPlugin())
            rows = orch.preview_table("users", count=3)
            assert len(rows) == 3
            assert all("_source" in r for r in rows)

    def test_preview_with_column_configs(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            col_configs = [
                ColumnConfig(name="name", generator="name"),
                ColumnConfig(name="email", generator="email"),
            ]
            rows = orch.preview_table("users", count=5, column_configs=col_configs)
            assert len(rows) == 5
            assert "name" in rows[0]

    def test_get_schema_context(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            ctx = orch.get_schema_context("users")
            assert ctx["table_name"] == "users"
            assert len(ctx["columns"]) > 0
            assert isinstance(ctx["foreign_keys"], list)
            assert isinstance(ctx["indexes"], list)
            assert isinstance(ctx["sample_data"], list)
            assert "users" in ctx["all_table_names"]
            assert isinstance(ctx["distribution"], list)

    def test_fill_with_template_pool_plugin(self, tmp_db) -> None:
        class TemplatePlugin:
            @hookimpl
            def sqlseed_pre_generate_templates(
                self,
                table_name: str,
                column_name: str,
                column_type: str,
                count: int,
                sample_data: list[Any],
            ) -> list[Any] | None:
                if column_name == "bio":
                    return ["template_bio_1", "template_bio_2", "template_bio_3"]
                return None

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(TemplatePlugin())
            result = orch.fill_table("users", count=5)
            assert result.count == 5

    def test_detect_unique_columns(self, bank_cards_db) -> None:
        with DataOrchestrator(bank_cards_db, provider_name="base") as orch:
            orch._ensure_connected()
            unique_cols = orch._detect_unique_columns("bank_cards")
            assert "card_number" in unique_cols
            assert "account_id" in unique_cols

    def test_fill_unique_index_no_error(self, bank_cards_db) -> None:
        with DataOrchestrator(bank_cards_db, provider_name="base") as orch:
            result = orch.fill_table("bank_cards", count=100)
            assert result.count == 100
            assert not result.errors

    def test_fill_unique_index_large_count(self, bank_cards_db) -> None:
        with DataOrchestrator(bank_cards_db, provider_name="base") as orch:
            result = orch.fill_table("bank_cards", count=1000)
            assert result.count == 1000
            assert not result.errors

    def test_unique_values_actually_unique(self, bank_cards_db) -> None:
        with DataOrchestrator(bank_cards_db, provider_name="base") as orch:
            orch.fill_table("bank_cards", count=200)
            conn = sqlite3.connect(bank_cards_db)
            rows = conn.execute("SELECT card_number FROM bank_cards").fetchall()
            conn.close()
            values = [r[0] for r in rows]
            assert len(values) == len(set(values))

    def test_adjust_specs_for_unique_string(self, bank_cards_db) -> None:
        with DataOrchestrator(bank_cards_db, provider_name="base") as orch:
            orch._ensure_connected()
            from sqlseed.core.mapper import GeneratorSpec

            specs = {
                "card_number": GeneratorSpec(
                    generator_name="string",
                    params={"min_length": 1, "max_length": 20},
                ),
            }
            adjusted = orch._adjust_specs_for_unique(specs, {"card_number"}, 10000)
            assert adjusted["card_number"].params["min_length"] > 1
            assert adjusted["card_number"].params["min_length"] <= 20

    def test_adjust_specs_for_unique_integer(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, code INTEGER NOT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_code ON items(code)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            from sqlseed.core.mapper import GeneratorSpec

            specs = {
                "code": GeneratorSpec(
                    generator_name="integer",
                    params={"min_value": 0, "max_value": 255},
                ),
            }
            adjusted = orch._adjust_specs_for_unique(specs, {"code"}, 10000)
            assert adjusted["code"].params["max_value"] >= 100000

    def test_fill_card_info_schema(self, tmp_path) -> None:
        db_path = str(tmp_path / "card_info.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE card_info(
                cardId INTEGER PRIMARY KEY,
                sCardNo VARCHAR(32) NOT NULL,
                byCardType INT8 DEFAULT 1,
                byFirstCardEnable INT8 DEFAULT 0,
                sUserNo VARCHAR(32) NOT NULL,
                CutCard4byte VARCHAR(20) DEFAULT NULL,
                CutCard3byte VARCHAR(20) DEFAULT NULL
            )
        """)
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_1 ON card_info(sCardNo)")
        conn.execute("CREATE INDEX cardindex_card_info_2 ON card_info(sUserNo)")
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_3 ON card_info(CutCard4byte)")
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_4 ON card_info(CutCard3byte)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("card_info", count=1000)
            assert result.count == 1000
            assert not result.errors

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT sCardNo FROM card_info").fetchall()
        conn.close()
        card_nos = [r[0] for r in rows]
        assert len(card_nos) == len(set(card_nos))

    def test_enrich_empty_table_uses_defaults(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_empty.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, bystatus INT8 DEFAULT 1)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("items", count=10, enrich=True)
            assert result.count == 10
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT bystatus FROM items").fetchall()
            conn2.close()
            assert all(r[0] == 1 for r in rows)

    def test_enrich_with_existing_data_uses_choice(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_choice.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, bystatus INT8 DEFAULT 1)")
        for _ in range(30):
            conn.execute("INSERT INTO items (bystatus) VALUES (1)")
        for _ in range(10):
            conn.execute("INSERT INTO items (bystatus) VALUES (2)")
        for _ in range(10):
            conn.execute("INSERT INTO items (bystatus) VALUES (3)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("items", count=50, enrich=True, clear_before=False)
            assert result.count == 50
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT DISTINCT bystatus FROM items").fetchall()
            conn2.close()
            distinct_statuses = {r[0] for r in rows}
            assert distinct_statuses == {1, 2, 3}

    def test_enrich_nullable_column_gets_null_ratio(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_null.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, sremark VARCHAR(20) DEFAULT NULL)")
        for v in ["hello", None, "world", None, None]:
            conn.execute("INSERT INTO items (sremark) VALUES (?)", [v])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("items", count=100, enrich=True, clear_before=False)
            assert result.count == 100
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT sremark FROM items").fetchall()
            conn2.close()
            null_count = sum(1 for r in rows if r[0] is None)
            non_null_count = len(rows) - null_count
            assert null_count > 0
            assert non_null_count > 0

    def test_enrich_all_null_column_stays_skip(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_allnull.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(32) NOT NULL,
                sremark VARCHAR(20) DEFAULT NULL
            )
            """
        )
        for n in ["a", "b", "c", "d", "e"]:
            conn.execute("INSERT INTO items (name, sremark) VALUES (?, NULL)", [n])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("items", count=10, enrich=True, clear_before=False)
            assert result.count == 10
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT sremark FROM items").fetchall()
            conn2.close()
            new_rows = rows[5:]
            assert all(r[0] is None for r in new_rows)

    def test_enrich_high_cardinality_uses_type_fallback(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_hcard.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, score REAL DEFAULT 0.0)")
        for i in range(50):
            conn.execute("INSERT INTO items (score) VALUES (?)", [float(i) * 1.1])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("items", count=20, enrich=True, clear_before=False)
            assert result.count == 20
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT score FROM items").fetchall()
            conn2.close()
            new_scores = [r[0] for r in rows[50:]]
            assert all(isinstance(s, float) for s in new_scores)

    def test_fill_card_info_with_enrich(self, tmp_path) -> None:
        db_path = str(tmp_path / "card_enrich.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE card_info(
                cardId INTEGER PRIMARY KEY,
                sCardNo VARCHAR(32) NOT NULL,
                byCardType INT8 DEFAULT 1,
                byFirstCardEnable INT8 DEFAULT 0,
                sUserNo VARCHAR(32) NOT NULL,
                CutCard4byte VARCHAR(20) DEFAULT NULL,
                CutCard3byte VARCHAR(20) DEFAULT NULL
            )
        """)
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_1 ON card_info(sCardNo)")
        conn.execute("CREATE INDEX cardindex_card_info_2 ON card_info(sUserNo)")
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_3 ON card_info(CutCard4byte)")
        conn.execute("CREATE UNIQUE INDEX cardindex_card_info_4 ON card_info(CutCard3byte)")

        for i in range(50):
            conn.execute(
                "INSERT INTO card_info "
                "(cardId, sCardNo, byCardType, byFirstCardEnable, sUserNo, CutCard4byte, CutCard3byte) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [i + 1, f"EXIST{i:04d}", (i % 2) + 1, i % 2, f"U{i:04d}", f"C4_{i:04d}", f"C3_{i:04d}"],
            )
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("card_info", count=100, enrich=True, clear_before=False)
            assert result.count == 100
            assert not result.errors

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT byCardType FROM card_info").fetchall()
        card_types = {r[0] for r in rows}
        assert card_types.issubset({1, 2})
        conn.close()

    def test_enrich_unique_column_uses_type_infer_not_choice(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_unique.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, code VARCHAR(20) DEFAULT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_code ON items(code)")
        for v in ["A", "B"]:
            conn.execute("INSERT INTO items (code) VALUES (?)", [v])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["code"].generator_name == "string"
            assert specs["code"].null_ratio == 0.0

    def test_enrich_not_null_column_null_ratio_is_zero(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_notnull.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, bystatus INT8 DEFAULT 1 NOT NULL)")
        conn.execute("INSERT INTO items (bystatus) VALUES (1)")
        conn.execute("INSERT INTO items (bystatus) VALUES (2)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["bystatus"].null_ratio == 0.0

    def test_enrich_unique_nullable_column_no_null(self, tmp_path) -> None:
        db_path = str(tmp_path / "enrich_uniq_null.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, sremark VARCHAR(20) DEFAULT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_sremark ON items(sremark)")
        for v in ["hello", None, "world"]:
            conn.execute("INSERT INTO items (sremark) VALUES (?)", [v])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["sremark"].null_ratio == 0.0

    def test_adjust_specs_for_unique_varchar_min_exceeds_max(self, tmp_path) -> None:
        db_path = str(tmp_path / "varchar_unique.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, code VARCHAR(5) NOT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_code ON items(code)")
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            from sqlseed.core.mapper import GeneratorSpec

            specs = {
                "code": GeneratorSpec(
                    generator_name="string",
                    params={"min_length": 1, "max_length": 5},
                ),
            }
            adjusted = orch._adjust_specs_for_unique(specs, {"code"}, 10000, orch._schema.get_column_info("items"))
            assert adjusted["code"].params["min_length"] >= 1
            assert adjusted["code"].params["charset"] == "alphanumeric"
