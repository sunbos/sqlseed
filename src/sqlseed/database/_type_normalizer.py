"""类型归一化层。

将不同数据库的类型名归一化为 sqlseed 内部统一类型，
保护 ``mapper.py`` 中 74 条 exact match 规则不失效。

归一化规则：
- 提取基础类型名和参数（长度、精度）
- 按方言映射到 sqlseed 内部类型（大写形式）
- 保留参数信息供生成器使用

示例：
    "character varying(255)" → NormalizedType(base="VARCHAR", params=(255,))
    "numeric(10,2)"          → NormalizedType(base="NUMERIC", params=(10, 2))
    "integer"                → NormalizedType(base="INTEGER", params=())
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 提取基础类型名和参数的正则
# "character varying(255)" → group(1)="character varying", group(2)="255"
# "numeric(10,2)"          → group(1)="numeric", group(2)="10,2"
# "integer"                → group(1)="integer", group(2)=None
_TYPE_PARAMS_RE = re.compile(r"^([^(]+?)\s*(?:\(([^)]+)\))?\s*$")


@dataclass(frozen=True)
class NormalizedType:
    """归一化后的类型信息。

    Attributes:
        base: 归一化后的基础类型名（大写），如 "VARCHAR"、"INTEGER"
        params: 类型参数元组，如 (255,) 或 (10, 2)
        raw: 原始类型字符串
    """

    base: str
    params: tuple[int, ...]
    raw: str

    @property
    def display(self) -> str:
        """显示形式："VARCHAR(255)" 或 "INTEGER"。"""
        if self.params:
            return f"{self.base}({','.join(str(p) for p in self.params)})"
        return self.base


# PostgreSQL 类型映射表
_PG_TYPE_MAP: dict[str, str] = {
    "serial": "INTEGER",
    "bigserial": "INTEGER",
    "smallserial": "INTEGER",
    "character varying": "VARCHAR",
    "character": "CHAR",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMPTZ",
    "double precision": "FLOAT",
    "boolean": "BOOLEAN",
    "smallint": "INTEGER",
    "bigint": "INTEGER",
    "integer": "INTEGER",
    "real": "FLOAT",
    "bytea": "BLOB",
    "jsonb": "JSON",
    "json": "JSON",
    "uuid": "UUID",
    "text": "TEXT",
    "numeric": "NUMERIC",
    "decimal": "NUMERIC",
    "date": "DATE",
    "time without time zone": "TIME",
    "time with time zone": "TIMETZ",
    "interval": "INTERVAL",
    "money": "DECIMAL",
    "inet": "TEXT",
    "cidr": "TEXT",
    "macaddr": "TEXT",
    "bit varying": "BLOB",
    "bit": "BLOB",
}

# MySQL 类型映射表
_MYSQL_TYPE_MAP: dict[str, str] = {
    "int": "INTEGER",
    "integer": "INTEGER",
    "bigint": "INTEGER",
    "smallint": "INTEGER",
    "tinyint": "INTEGER",
    "mediumint": "INTEGER",
    "varchar": "VARCHAR",
    "char": "CHAR",
    "text": "TEXT",
    "tinytext": "TEXT",
    "mediumtext": "TEXT",
    "longtext": "TEXT",
    "datetime": "DATETIME",
    "timestamp": "TIMESTAMP",
    "date": "DATE",
    "time": "TIME",
    "year": "INTEGER",
    "double": "FLOAT",
    "float": "FLOAT",
    "decimal": "NUMERIC",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "blob": "BLOB",
    "tinyblob": "BLOB",
    "mediumblob": "BLOB",
    "longblob": "BLOB",
    "json": "JSON",
    "binary": "BLOB",
    "varbinary": "BLOB",
    "enum": "TEXT",
    "set": "TEXT",
}


class TypeNormalizer:
    """将不同数据库的类型名归一化，让 mapper.py 的规则继续工作。

    使用方式：
        normalizer = TypeNormalizer()
        result = normalizer.normalize("character varying(255)", "postgresql")
        # result.base == "VARCHAR"
        # result.params == (255,)
        # result.display == "VARCHAR(255)"
    """

    def normalize(self, raw_type: str, dialect_name: str) -> NormalizedType:
        """归一化类型名。

        Args:
            raw_type: 数据库返回的原始类型字符串
            dialect_name: 方言名（"sqlite"、"postgresql"、"mysql"）

        Returns:
            NormalizedType 归一化后的类型信息
        """
        if not raw_type or not raw_type.strip():
            return NormalizedType(base="TEXT", params=(), raw=raw_type)

        match = _TYPE_PARAMS_RE.match(raw_type.strip())
        if not match:
            return NormalizedType(base=raw_type.upper(), params=(), raw=raw_type)

        base_raw = match.group(1).strip().lower()
        params_str = match.group(2)

        # 按方言映射基础类型
        base = self._map_base_type(base_raw, dialect_name)

        # 解析参数（长度、精度）
        params = self._parse_params(params_str)

        return NormalizedType(base=base, params=params, raw=raw_type)

    def _map_base_type(self, base_raw: str, dialect_name: str) -> str:
        """按方言映射基础类型名到 sqlseed 内部类型。"""
        if dialect_name == "postgresql":
            return _PG_TYPE_MAP.get(base_raw, base_raw.upper())
        if dialect_name == "mysql":
            return _MYSQL_TYPE_MAP.get(base_raw, base_raw.upper())
        # SQLite 类型已经是规范化的大写形式
        return base_raw.upper()

    def _parse_params(self, params_str: str | None) -> tuple[int, ...]:
        """解析类型参数字符串为整数元组。

        "255"    → (255,)
        "10,2"   → (10, 2)
        None     → ()
        "abc"    → ()  # 非数字参数忽略
        """
        if not params_str:
            return ()

        params: list[int] = []
        for raw_part in params_str.split(","):
            part = raw_part.strip()
            if not part:
                continue
            try:
                params.append(int(part))
            except ValueError:
                # 非数字参数（如 ENUM 值）忽略，只保留数字
                continue
        return tuple(params)


__all__ = ["NormalizedType", "TypeNormalizer"]
