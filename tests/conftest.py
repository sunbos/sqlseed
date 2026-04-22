from __future__ import annotations

import gc
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _gc_between_tests():
    gc.collect()
    yield
    gc.collect()


def make_col(
    name: str,
    col_type: str = "TEXT",
    nullable: bool = False,
    default=None,
    is_pk: bool = False,
    is_auto: bool = False,
):
    return type(
        "Col",
        (),
        {
            "name": name,
            "type": col_type,
            "nullable": nullable,
            "default": default,
            "is_primary_key": is_pk,
            "is_autoincrement": is_auto,
        },
    )()


@pytest.fixture(name="tmp_db")
def create_tmp_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            age INTEGER,
            phone TEXT,
            address TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1,
            balance REAL,
            bio TEXT,
            status INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            amount REAL,
            quantity INTEGER,
            status TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(name="tmp_db_with_data")
def create_tmp_db_with_data(tmp_db: str) -> str:
    conn = sqlite3.connect(tmp_db)
    for i in range(10):
        conn.execute(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            [f"user_{i}", f"user_{i}@test.com", 20 + i],
        )
    conn.commit()
    conn.close()
    return tmp_db


@pytest.fixture(name="bank_cards_db")
def create_bank_cards_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "bank_cards.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE bank_cards (
            cardId INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number VARCHAR(20) NOT NULL,
            account_id VARCHAR(32) NOT NULL,
            last_eight VARCHAR(8),
            last_six VARCHAR(6),
            byCardType INTEGER DEFAULT 1,
            byFirstCardEnable INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE UNIQUE INDEX idx_cardno ON bank_cards(card_number)")
    conn.execute("CREATE UNIQUE INDEX idx_userno ON bank_cards(account_id)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(name="raw_adapter")
def create_raw_adapter(tmp_db: str) -> Generator[RawSQLiteAdapter, None, None]:
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture(name="raw_adapter_with_data")
def create_raw_adapter_with_data(tmp_db_with_data: str) -> Generator[RawSQLiteAdapter, None, None]:
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db_with_data)
    yield adapter
    adapter.close()


CARD_INFO_DDL = """
    CREATE TABLE card_info(
        cardId INTEGER PRIMARY KEY,
        sCardNo VARCHAR(32) NOT NULL,
        byCardType INT8 DEFAULT 1,
        byFirstCardEnable INT8 DEFAULT 0,
        sUserNo VARCHAR(32) NOT NULL,
        CutCard4byte VARCHAR(20) DEFAULT NULL,
        CutCard3byte VARCHAR(20) DEFAULT NULL
    )
"""

CARD_INFO_INDEXES = [
    "CREATE UNIQUE INDEX cardindex_card_info_1 ON card_info(sCardNo)",
    "CREATE INDEX cardindex_card_info_2 ON card_info(sUserNo)",
    "CREATE UNIQUE INDEX cardindex_card_info_3 ON card_info(CutCard4byte)",
    "CREATE UNIQUE INDEX cardindex_card_info_4 ON card_info(CutCard3byte)",
]


def create_simple_db(
    db_path: str,
    table_ddl: str = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(table_ddl)
    conn.commit()
    conn.close()


def apply_enrichment(db_path: str, table_name: str, provider_name: str = "base"):
    with DataOrchestrator(db_path, provider_name=provider_name) as orch:
        orch._ensure_connected()
        column_infos = orch._schema.get_column_info(table_name)
        unique_cols = orch._schema.detect_unique_columns(table_name)
        specs = orch._mapper.map_columns(column_infos, enrich=True)
        specs = orch._enrichment.apply(table_name, specs, column_infos, unique_cols)
        return orch, specs


def create_card_info_db(
    db_path: str,
    with_data: bool = False,
    data_count: int = 50,
    card_type_mod: int = 2,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(CARD_INFO_DDL)
    for idx_sql in CARD_INFO_INDEXES:
        conn.execute(idx_sql)
    if with_data:
        for i in range(data_count):
            conn.execute(
                "INSERT INTO card_info "
                "(cardId, sCardNo, byCardType, byFirstCardEnable, sUserNo, CutCard4byte, CutCard3byte) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [i + 1, f"CARD{i:04d}", (i % card_type_mod) + 1, i % 2, f"U{i:04d}", f"C4_{i:04d}", f"C3_{i:04d}"],
            )
    conn.commit()
    conn.close()
