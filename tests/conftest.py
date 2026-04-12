from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def tmp_db(tmp_path):
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


@pytest.fixture
def tmp_db_with_data(tmp_db):
    conn = sqlite3.connect(tmp_db)
    for i in range(10):
        conn.execute(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            [f"user_{i}", f"user_{i}@test.com", 20 + i],
        )
    conn.commit()
    conn.close()
    return tmp_db
