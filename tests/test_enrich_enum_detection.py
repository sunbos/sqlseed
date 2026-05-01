from __future__ import annotations

import sqlite3
from typing import Any

from sqlseed.core.orchestrator import DataOrchestrator
from tests.conftest import apply_enrichment, create_card_info_db


class TestEnumDetection:
    def _make_col_info(self, name: str, col_type: str = "INT8", nullable: bool = False) -> object:
        class FakeColumnInfo:
            def __init__(self, n: str, t: str, nl: bool) -> None:
                self.name = n
                self.type = t
                self.nullable = nl
                self.default = None
                self.is_primary_key = False
                self.is_autoincrement = False

        return FakeColumnInfo(name, col_type, nullable)

    def _assert_enum(
        self, col_name: str, col_type: str, distinct: int, total: int, is_unique: bool, expected: bool
    ) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info(col_name, col_type)
            assert (
                orch._enrichment is not None
                and orch._enrichment.is_enumeration_column(col_name, col_info, distinct, total, is_unique) is expected
            )

    def test_enum_detection_by_name_pattern_by_prefix(self) -> None:
        self._assert_enum("byCardType", "INT8", 3, 100, False, True)

    def test_enum_detection_by_name_pattern_status(self) -> None:
        self._assert_enum("order_status", "INTEGER", 5, 500, False, True)

    def test_enum_detection_by_name_pattern_type(self) -> None:
        self._assert_enum("user_type", "INTEGER", 3, 200, False, True)

    def test_enum_detection_by_small_int_type(self) -> None:
        self._assert_enum("priority", "INT8", 3, 200, False, True)

    def test_enum_detection_by_cardinality_ratio(self) -> None:
        self._assert_enum("gender", "VARCHAR(10)", 2, 1000, False, True)

    def test_enum_rejection_unique_column(self) -> None:
        self._assert_enum("sCardNo", "VARCHAR(32)", 3, 100, True, False)

    def test_enum_rejection_high_cardinality(self) -> None:
        self._assert_enum("sUserNo", "VARCHAR(32)", 80, 100, False, False)

    def test_enum_rejection_varchar_medium_cardinality(self) -> None:
        self._assert_enum("department", "VARCHAR(50)", 18, 1000, False, False)

    def test_enum_rejection_empty_data(self) -> None:
        self._assert_enum("status", "INT8", 0, 0, False, False)

    def test_enum_detection_is_active(self) -> None:
        self._assert_enum("is_active", "INTEGER", 2, 500, False, True)

    def test_enum_detection_has_permission(self) -> None:
        self._assert_enum("has_permission", "INTEGER", 2, 500, False, True)

    def test_enum_detection_int16_type(self) -> None:
        self._assert_enum("level", "INT16", 5, 200, False, True)

    def test_enum_rejection_high_ratio_even_with_name(self) -> None:
        self._assert_enum("user_type", "INTEGER", 50, 100, False, False)


class TestEnumDetectionIntegration:
    def test_enrich_bystatus_uses_choice(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "enum_by.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, bystatus INT8 DEFAULT 1)")
        for _ in range(30):
            conn.execute("INSERT INTO items (bystatus) VALUES (1)")
        for _ in range(15):
            conn.execute("INSERT INTO items (bystatus) VALUES (2)")
        for _ in range(5):
            conn.execute("INSERT INTO items (bystatus) VALUES (3)")
        conn.commit()
        conn.close()

        _, specs = apply_enrichment(db_path, "items")
        assert specs["bystatus"].generator_name == "choice"
        assert set(specs["bystatus"].params["choices"]) == {1, 2, 3}

    def test_enrich_unique_column_uses_type_infer(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "enum_unique.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, sCardNo VARCHAR(32) DEFAULT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_cardno ON items(sCardNo)")
        for v in ("AAA", "BBB", "CCC"):
            conn.execute("INSERT INTO items (sCardNo) VALUES (?)", [v])
        conn.commit()
        conn.close()

        _, specs = apply_enrichment(db_path, "items")
        assert specs["sCardNo"].generator_name != "choice"

    def test_enrich_gender_uses_choice(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "enum_gender.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, gender VARCHAR(10) DEFAULT 'male')")
        for v in ("male", "female", "male", "male", "female"):
            conn.execute("INSERT INTO users (gender) VALUES (?)", [v])
        conn.commit()
        conn.close()

        _, specs = apply_enrichment(db_path, "users")
        assert specs["gender"].generator_name == "choice"

    def test_enrich_high_cardinality_varchar_uses_type_infer(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "enum_highcard.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, department VARCHAR(50) DEFAULT 'eng')")
        departments = [f"dept_{i}" for i in range(18)]
        for d in departments:
            conn.execute("INSERT INTO items (department) VALUES (?)", [d])
        conn.commit()
        conn.close()

        _, specs = apply_enrichment(db_path, "items")
        assert specs["department"].generator_name != "choice"

    def test_fill_card_info_with_enrich_full_e2e(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "card_info_e2e.db")
        create_card_info_db(db_path, with_data=True, data_count=100, card_type_mod=3)

        with DataOrchestrator(db_path, provider_name="base") as orch:
            result = orch.fill_table("card_info", count=500, enrich=True, clear_before=False)
            assert result.count == 500
            assert not result.errors

        conn = sqlite3.connect(db_path)
        card_types = {r[0] for r in conn.execute("SELECT DISTINCT byCardType FROM card_info").fetchall()}
        assert card_types == {1, 2, 3}

        card_nos = [r[0] for r in conn.execute("SELECT sCardNo FROM card_info").fetchall()]
        assert len(card_nos) == len(set(card_nos))

        cut4 = [
            r[0] for r in conn.execute("SELECT CutCard4byte FROM card_info WHERE CutCard4byte IS NOT NULL").fetchall()
        ]
        assert len(cut4) == len(set(cut4))

        conn.close()
