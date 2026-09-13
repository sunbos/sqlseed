"""Create demo database with 3 tables for quickstart script."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _validate_db_path(path: Path) -> Path:
    """Validate database path to prevent path traversal attacks.

    Rejects relative paths that escape to parent directories via ../.
    """
    if not path.is_absolute():
        rel_input = str(path).replace("\\", "/")
        if rel_input.startswith("../") or "/../" in rel_input:
            raise ValueError(f"Path traversal not allowed: {path}")
    return path.resolve()


def main() -> None:
    default_db = str(Path(__file__).resolve().parent.parent / "quickstart_demo.db")
    db_path_str = sys.argv[1] if len(sys.argv) > 1 else default_db
    db_path = _validate_db_path(Path(db_path_str))
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(str(db_path)) as conn:
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
    print(f"  Database created: {db_path} (3 tables: users, projects, orders)")


if __name__ == "__main__":
    main()
