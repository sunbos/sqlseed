"""构建和管理 sqlseed 教程的演示 SQLite 数据库。

本模块具有双重用途：
  1. **可导入库** — notebook 调用 ``ensure_db()`` 获取就绪的数据库
  2. **CLI 脚本** — ``python build_demo_db.py`` 独立使用

公开 API：
  - ``ensure_db()`` — 幂等操作：缺失时创建 schema，存在时直接返回路径
  - ``build()``     — 始终创建全新数据库（破坏性）
  - ``SCHEMA_SQL``  — schema DDL，唯一真实来源

设计决策：**仅 schema，无种子数据**。所有数据由 sqlseed 在 notebook 中生成——
这确保了随机性，并更好地展示库的功能。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema — 所有 notebook 的唯一真实来源
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
-- Schema 版本: 2

-- 1. organizations — VARCHAR 主键, 自引用外键, _code/_count/_at/is_ 列
CREATE TABLE IF NOT EXISTS organizations (
    org_code VARCHAR(16) PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    parent_code VARCHAR(16),
    description TEXT,
    is_active INTEGER DEFAULT 1,
    member_count INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (parent_code) REFERENCES organizations(org_code)
);

-- 2. members — UNIQUE email, _no 列, is_ 布尔值, BLOB, _at, REAL, 显式外键
CREATE TABLE IF NOT EXISTS members (
    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_no VARCHAR(16) NOT NULL UNIQUE,
    name VARCHAR(64) NOT NULL,
    email VARCHAR(128) NOT NULL UNIQUE,
    phone VARCHAR(20),
    org_code VARCHAR(16) NOT NULL,
    is_active INTEGER DEFAULT 1,
    balance REAL DEFAULT 0.0,
    avatar BLOB,
    registered_at TEXT,
    address TEXT,
    FOREIGN KEY (org_code) REFERENCES organizations(org_code)
);

-- 3. projects — _no 列, UNIQUE, derive_from 目标, _count/_at/is_, REAL, 显式外键
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_no VARCHAR(20) NOT NULL UNIQUE,
    short_code VARCHAR(6),
    name VARCHAR(128) NOT NULL,
    org_code VARCHAR(16) NOT NULL,
    budget REAL DEFAULT 0.0,
    task_count INTEGER DEFAULT 0,
    is_public INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0,
    created_at TEXT,
    description TEXT,
    FOREIGN KEY (org_code) REFERENCES organizations(org_code)
);

-- 4. tasks — 显式外键（双重）, _at/is_/_count, REAL
CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    assignee_id INTEGER NOT NULL,
    title VARCHAR(256) NOT NULL,
    priority INTEGER DEFAULT 1,
    status INTEGER DEFAULT 0,
    is_completed INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    estimated_hours REAL,
    due_at TEXT,
    completed_at TEXT,
    created_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (assignee_id) REFERENCES members(member_id)
);

-- 5. reviews — 显式外键 (task_id) + 隐式外键 (member_id 同名), _at
CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    rating INTEGER DEFAULT 0,
    content TEXT,
    created_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- 6. tags — 简单查找表, UNIQUE name, _count
CREATE TABLE IF NOT EXISTS tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) NOT NULL UNIQUE,
    color VARCHAR(7),
    usage_count INTEGER DEFAULT 0
);

-- 7. task_tags — 多列 UNIQUE, 显式外键（双重）
CREATE TABLE IF NOT EXISTS task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    UNIQUE(task_id, tag_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id),
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
);

-- 8. attachments — BLOB, 显式外键, _at
CREATE TABLE IF NOT EXISTS attachments (
    attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    file_name VARCHAR(128) NOT NULL,
    file_data BLOB,
    file_size INTEGER DEFAULT 0,
    uploaded_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- 索引（IF NOT EXISTS 确保幂等性）
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_short_code ON projects(short_code);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id);
CREATE INDEX IF NOT EXISTS idx_members_active ON members(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(org_code);
"""

# 演示数据库中预期的表
_EXPECTED_TABLES = frozenset(
    {
        "organizations",
        "members",
        "projects",
        "tasks",
        "reviews",
        "tags",
        "task_tags",
        "attachments",
    }
)

# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = _SCRIPT_DIR / "sqlseed_demo.db"


def _validate_db_path(path: Path) -> Path:
    """Validate database path to prevent path traversal and unsafe locations.

    Ensures the resolved path stays within the script's parent directory tree
    or is an absolute path explicitly provided by the caller (not relative ../).
    """
    resolved = path.resolve()
    # Reject paths that escape to parent directories via relative ../ traversal
    # when the input was a relative path
    if not path.is_absolute():
        rel_input = str(path).replace("\\", "/")
        if rel_input.startswith("../") or "/../" in rel_input:
            raise ValueError(f"Path traversal not allowed: {path}")
    return resolved


def ensure_db(db_path: str | Path | None = None) -> Path:
    """确保演示数据库存在且 schema 正确。

    幂等操作 — 可安全多次调用：
      - 数据库存在且包含所有表 → 立即返回路径（无数据丢失）
      - 数据库缺失或 schema 不完整 → 创建/修复 schema

    不插入数据 — notebook 使用 sqlseed 本身来填充表，
    确保每次运行产生全新的随机数据。

    Args:
        db_path: 数据库路径。默认为 ``examples/sqlseed_demo.db``。

    Returns:
        数据库文件的绝对路径。
    """
    path = _validate_db_path(Path(db_path) if db_path else _DEFAULT_DB_PATH)

    if path.exists():
        conn = sqlite3.connect(str(path))
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if _EXPECTED_TABLES.issubset(existing):
            conn.close()
            return path
        # Schema 不完整 — 修复
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()
        return path

    # 数据库不存在 — 仅创建 schema
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


def build(db_path: str | Path | None = None) -> Path:
    """创建全新的演示数据库（破坏性 — 删除已有数据库）。

    如需非破坏性替代方案，请使用 ``ensure_db()``。

    Args:
        db_path: 输出路径。默认为 ``examples/sqlseed_demo.db``。

    Returns:
        创建的数据库文件路径。
    """
    path = _validate_db_path(Path(db_path) if db_path else _DEFAULT_DB_PATH)
    if path.exists():
        path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="构建 sqlseed_demo.db")
    parser.add_argument("--fresh", action="store_true", help="强制重建（删除已有数据库）")
    parser.add_argument("--output", default=None, help="输出路径（默认: examples/sqlseed_demo.db）")
    args = parser.parse_args()

    if args.fresh:
        p = build(args.output)
        print(f"已重建（全新）: {p}")
    else:
        p = ensure_db(args.output)
        print(f"已确保存在: {p}")
