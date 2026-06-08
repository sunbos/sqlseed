"""Create demo database with 3 tables for quickstart script."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    db_path_str = sys.argv[1] if len(sys.argv) > 1 else "quickstart_demo.db"
    db_path = Path(db_path_str)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            age INTEGER,
            city TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'Planning',
            owner_id INTEGER REFERENCES users(id),
            budget REAL,
            deadline DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            project_id INTEGER REFERENCES projects(id),
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            order_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    print(f"  Database created: {db_path} (3 tables: users, projects, orders)")


if __name__ == "__main__":
    main()
