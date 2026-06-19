"""批量写入性能优化器协议。

抽象各数据库的批量写入优化策略：
- SQLite: PRAGMA synchronous = OFF, journal_mode = MEMORY
- PostgreSQL: SET synchronous_commit = OFF
- MySQL: SET unique_checks = 0, foreign_key_checks = 0

阶段 1 仅定义协议和 SQLiteBulkOptimizer（委托给现有 PragmaOptimizer），
PostgresBulkOptimizer/MySQLBulkOptimizer 留待后续阶段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.database.optimizer import PragmaOptimizer


@runtime_checkable
class BulkWriteOptimizer(Protocol):
    """批量写入性能优化器协议。

    生命周期：
        preserve()  → 保存当前数据库配置
        optimize()  → 应用批量写入优化
        ... 批量写入操作 ...
        restore()   → 恢复原配置
    """

    def preserve(self) -> None:
        """保存当前数据库配置（在优化前调用）。"""
        ...

    def optimize(self, expected_rows: int | None = None) -> None:
        """应用批量写入优化。

        Args:
            expected_rows: 预期写入行数，用于选择优化级别
                          None 时使用默认值（通常 10000）
        """
        ...

    def restore(self) -> None:
        """恢复原配置（在写入完成后调用）。"""
        ...


class SQLiteBulkOptimizer:
    """SQLite 批量写入优化器。

    委托给现有的 ``PragmaOptimizer``，保持现有 SQLite 性能优化行为不变。
    """

    def __init__(
        self,
        execute_fn: Callable[..., Any],
        fetch_pragma_fn: Callable[[str], Any],
    ) -> None:
        """初始化 SQLite 批量写入优化器。

        Args:
            execute_fn: 执行 PRAGMA SQL 的可调用对象
            fetch_pragma_fn: 获取 PRAGMA 当前值的可调用对象
        """
        # 延迟导入避免循环依赖
        from sqlseed.database.optimizer import PragmaOptimizer  # noqa: PLC0415

        self._optimizer: PragmaOptimizer = PragmaOptimizer(
            execute_fn=execute_fn,
            fetch_pragma_fn=fetch_pragma_fn,
        )

    def preserve(self) -> None:
        """保存当前 PRAGMA 配置。"""
        self._optimizer.preserve()

    def optimize(self, expected_rows: int | None = None) -> None:
        """应用 PRAGMA 批量写入优化。

        根据 expected_rows 选择优化级别：
        - >100000: aggressive (synchronous=OFF, journal_mode=OFF)
        - >10000: moderate (synchronous=OFF, journal_mode=MEMORY)
        - 其他: light (synchronous=NORMAL, temp_store=MEMORY)
        """
        self._optimizer.optimize(expected_rows)

    def restore(self) -> None:
        """恢复原 PRAGMA 配置。"""
        self._optimizer.restore()


__all__ = ["BulkWriteOptimizer", "SQLiteBulkOptimizer"]
