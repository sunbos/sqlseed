from __future__ import annotations

import sqlite3

from sqlseed.core.orchestrator import DataOrchestrator


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

    def test_enum_detection_by_name_pattern_by_prefix(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("byCardType", "INT8")
            assert orch._is_enumeration_column("byCardType", col_info, 3, 100, False) is True

    def test_enum_detection_by_name_pattern_status(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("order_status", "INTEGER")
            assert orch._is_enumeration_column("order_status", col_info, 5, 500, False) is True

    def test_enum_detection_by_name_pattern_type(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("user_type", "INTEGER")
            assert orch._is_enumeration_column("user_type", col_info, 3, 200, False) is True

    def test_enum_detection_by_small_int_type(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("priority", "INT8")
            assert orch._is_enumeration_column("priority", col_info, 3, 200, False) is True

    def test_enum_detection_by_cardinality_ratio(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("gender", "VARCHAR(10)")
            assert orch._is_enumeration_column("gender", col_info, 2, 1000, False) is True

    def test_enum_rejection_unique_column(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("sCardNo", "VARCHAR(32)")
            assert orch._is_enumeration_column("sCardNo", col_info, 3, 100, True) is False

    def test_enum_rejection_high_cardinality(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("sUserNo", "VARCHAR(32)")
            assert orch._is_enumeration_column("sUserNo", col_info, 80, 100, False) is False

    def test_enum_rejection_varchar_medium_cardinality(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("department", "VARCHAR(50)")
            assert orch._is_enumeration_column("department", col_info, 18, 1000, False) is False

    def test_enum_rejection_empty_data(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("status", "INT8")
            assert orch._is_enumeration_column("status", col_info, 0, 0, False) is False

    def test_enum_detection_is_active(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("is_active", "INTEGER")
            assert orch._is_enumeration_column("is_active", col_info, 2, 500, False) is True

    def test_enum_detection_has_permission(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("has_permission", "INTEGER")
            assert orch._is_enumeration_column("has_permission", col_info, 2, 500, False) is True

    def test_enum_detection_int16_type(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("level", "INT16")
            assert orch._is_enumeration_column("level", col_info, 5, 200, False) is True

    def test_enum_rejection_high_ratio_even_with_name(self) -> None:
        with DataOrchestrator(":memory:", provider_name="base") as orch:
            orch._ensure_connected()
            col_info = self._make_col_info("user_type", "INTEGER")
            assert orch._is_enumeration_column("user_type", col_info, 50, 100, False) is False


class TestEnumDetectionIntegration:
    def test_enrich_bystatus_uses_choice(self, tmp_path) -> None:
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

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["bystatus"].generator_name == "choice"
            assert set(specs["bystatus"].params["choices"]) == {1, 2, 3}

    def test_enrich_unique_column_uses_type_infer(self, tmp_path) -> None:
        db_path = str(tmp_path / "enum_unique.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, sCardNo VARCHAR(32) DEFAULT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_cardno ON items(sCardNo)")
        for v in ["AAA", "BBB", "CCC"]:
            conn.execute("INSERT INTO items (sCardNo) VALUES (?)", [v])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["sCardNo"].generator_name != "choice"

    def test_enrich_gender_uses_choice(self, tmp_path) -> None:
        db_path = str(tmp_path / "enum_gender.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, gender VARCHAR(10) DEFAULT 'male')")
        for v in ["male", "female", "male", "male", "female"]:
            conn.execute("INSERT INTO users (gender) VALUES (?)", [v])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("users")
            unique_cols = orch._detect_unique_columns("users")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("users", specs, column_infos, unique_cols)
            assert specs["gender"].generator_name == "choice"

    def test_enrich_high_cardinality_varchar_uses_type_infer(self, tmp_path) -> None:
        db_path = str(tmp_path / "enum_highcard.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, department VARCHAR(50) DEFAULT 'eng')")
        departments = [f"dept_{i}" for i in range(18)]
        for d in departments:
            conn.execute("INSERT INTO items (department) VALUES (?)", [d])
        conn.commit()
        conn.close()

        with DataOrchestrator(db_path, provider_name="base") as orch:
            orch._ensure_connected()
            column_infos = orch._schema.get_column_info("items")
            unique_cols = orch._detect_unique_columns("items")
            specs = orch._mapper.map_columns(column_infos, enrich=True)
            specs = orch._apply_enrich("items", specs, column_infos, unique_cols)
            assert specs["department"].generator_name != "choice"

    def test_fill_card_info_with_enrich_full_e2e(self, tmp_path) -> None:
        db_path = str(tmp_path / "card_info_e2e.db")
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

        for i in range(100):
            conn.execute(
                "INSERT INTO card_info "
                "(cardId, sCardNo, byCardType, byFirstCardEnable, sUserNo, CutCard4byte, CutCard3byte) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [i + 1, f"CARD{i:04d}", (i % 3) + 1, i % 2, f"U{i:04d}", f"C4_{i:04d}", f"C3_{i:04d}"],
            )
        conn.commit()
        conn.close()

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
