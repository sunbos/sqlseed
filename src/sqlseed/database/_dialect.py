"""数据库方言抽象层。

封装各数据库的专属行为（类型归一化、自增检测、标识符引用、批量写入器创建），
让上层代码无需感知底层是 SQLite、PostgreSQL 还是 MySQL。

阶段 1 仅实现 SQLiteDialect，PostgresDialect/MySQLDialect 留待后续阶段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class BatchInserter(Protocol):
    """批量写入器接口。

    由各方言通过 ``Dialect.create_batch_inserter`` 创建，
    封装数据库专属的高性能批量写入方式（如 PG 的 COPY 协议）。
    """

    def insert(self, rows: list[dict[str, Any]]) -> int:
        """写入一批数据，返回写入行数。"""
        ...


@runtime_checkable
class Dialect(Protocol):
    """数据库方言抽象。

    封装各数据库的专属行为，让上层代码无需感知底层方言。
    """

    name: str

    def normalize_type(self, raw_type: str) -> str:
        """将数据库原始类型名归一化为 sqlseed 内部类型。

        SQLite: "TEXT" → "TEXT", "INTEGER" → "INTEGER"
        PG: "character varying(255)" → "VARCHAR(255)"
        """
        ...

    def detect_autoincrement(self, column_info: dict[str, Any]) -> bool:
        """检测列是否自增。

        SQLite: 解析 CREATE TABLE 找 AUTOINCREMENT
        PG: 检测 SERIAL / IDENTITY / nextval()
        """
        ...

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """重置自增计数器。

        SQLite: DELETE FROM sqlite_sequence
        PG: TRUNCATE ... RESTART IDENTITY / ALTER SEQUENCE
        MySQL: ALTER TABLE ... AUTO_INCREMENT = 1
        """
        ...

    def quote_identifier(self, name: str) -> str:
        """引用标识符。

        SQLite/PG: "name"
        MySQL: `name`
        """
        ...

    def create_batch_inserter(self, engine: Any, table_name: str) -> BatchInserter:
        """创建批量写入器。

        SQLite: SQLAlchemy bulk_insert_mappings
        PG: psycopg3 COPY 协议（比 INSERT 快 5-10x）
        """
        ...


class SQLiteDialect:
    """SQLite 方言实现。

    autoincrement 检测委托给 ``sqlseed._utils.schema_helpers.detect_autoincrement``，
    该函数解析 ``sqlite_master`` 中的 CREATE TABLE SQL。
    """

    name = "sqlite"

    def normalize_type(self, raw_type: str) -> str:
        """SQLite 类型已经是规范化的大写形式。"""
        return raw_type.upper() if raw_type else "TEXT"

    def detect_autoincrement(self, column_info: dict[str, Any]) -> bool:
        """SQLite 的 autoincrement 检测需要解析 CREATE TABLE SQL。

        阶段 1 不在此处实现，由 SQLAlchemyAdapter/RawSQLiteAdapter
        通过 ``schema_helpers.detect_autoincrement`` 完成。
        此方法保留接口一致性，返回 False 作为占位。
        """
        return False

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """重置 SQLite 自增序列：DELETE FROM sqlite_sequence。"""
        execute_fn("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])

    def quote_identifier(self, name: str) -> str:
        """SQLite 使用双引号引用标识符。"""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def create_batch_inserter(self, engine: Any, table_name: str) -> BatchInserter:
        """创建 SQLite 批量写入器。

        阶段 2 引入 SQLAlchemyAdapter 后实现，阶段 1 抛出 NotImplementedError。
        """
        raise NotImplementedError("SQLiteBatchInserter will be implemented in phase 2")


__all__ = ["BatchInserter", "Dialect", "SQLiteDialect"]
