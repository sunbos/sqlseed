"""Tests for FK dependency resolver."""
from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.dependency_resolver import DependencyResolver

from sqlseed.database._protocol import ForeignKeyInfo


def _make_fk(column: str, ref_table: str, ref_column: str) -> ForeignKeyInfo:
    return ForeignKeyInfo(column=column, ref_table=ref_table, ref_column=ref_column)


class TestDependencyResolver:
    """Test FK dependency resolution with recursion."""

    def test_single_table_no_fk(self) -> None:
        db = MagicMock()
        db.get_foreign_keys.return_value = []
        resolver = DependencyResolver(db)
        result = resolver.resolve(["users"])
        assert result.target_tables == ["users"]
        assert result.context_tables == []

    def test_single_table_with_one_parent(self) -> None:
        db = MagicMock()
        db.get_foreign_keys.side_effect = lambda t: {
            "orders": [_make_fk("user_id", "users", "id")],
            "users": [],
        }.get(t, [])
        resolver = DependencyResolver(db)
        result = resolver.resolve(["orders"])
        assert result.target_tables == ["orders"]
        assert "users" in result.context_tables

    def test_multi_level_recursion(self) -> None:
        """order_items -> orders -> users (3-level chain)."""
        db = MagicMock()
        db.get_foreign_keys.side_effect = lambda t: {
            "order_items": [_make_fk("order_id", "orders", "id")],
            "orders": [_make_fk("user_id", "users", "id")],
            "users": [],
        }.get(t, [])
        resolver = DependencyResolver(db)
        result = resolver.resolve(["order_items"])
        assert result.target_tables == ["order_items"]
        assert "orders" in result.context_tables
        assert "users" in result.context_tables

    def test_cycle_detection_self_reference(self) -> None:
        """users.referrer_id -> users.id (self-reference)."""
        db = MagicMock()
        db.get_foreign_keys.side_effect = lambda t: {
            "users": [_make_fk("referrer_id", "users", "id")],
        }.get(t, [])
        resolver = DependencyResolver(db)
        result = resolver.resolve(["users"])
        assert result.target_tables == ["users"]
        assert "users" not in result.context_tables

    def test_max_depth_limit(self) -> None:
        """5-level chain with max_depth=3 stops at depth 3."""
        db = MagicMock()
        db.get_foreign_keys.side_effect = lambda t: {
            "t1": [_make_fk("t2_id", "t2", "id")],
            "t2": [_make_fk("t3_id", "t3", "id")],
            "t3": [_make_fk("t4_id", "t4", "id")],
            "t4": [_make_fk("t5_id", "t5", "id")],
            "t5": [],
        }.get(t, [])
        resolver = DependencyResolver(db, max_depth=3)
        result = resolver.resolve(["t1"])
        assert result.target_tables == ["t1"]
        assert "t2" in result.context_tables
        assert "t3" in result.context_tables
        assert "t4" in result.context_tables  # depth 3
        assert "t5" not in result.context_tables  # depth 4 > max_depth

    def test_multi_target_no_context_overlap(self) -> None:
        """Multiple targets: target tables are not in context_tables."""
        db = MagicMock()
        db.get_foreign_keys.side_effect = lambda t: {
            "orders": [_make_fk("user_id", "users", "id")],
            "items": [_make_fk("category_id", "categories", "id")],
            "users": [],
            "categories": [],
        }.get(t, [])
        resolver = DependencyResolver(db)
        result = resolver.resolve(["orders", "items"])
        assert set(result.target_tables) == {"orders", "items"}
        assert "users" in result.context_tables
        assert "categories" in result.context_tables
        assert "orders" not in result.context_tables
        assert "items" not in result.context_tables

    def test_no_dependencies_flag(self) -> None:
        """include_dependencies=False skips FK resolution."""
        db = MagicMock()
        db.get_foreign_keys.return_value = [_make_fk("user_id", "users", "id")]
        resolver = DependencyResolver(db)
        result = resolver.resolve(["orders"], include_dependencies=False)
        assert result.target_tables == ["orders"]
        assert result.context_tables == []
        db.get_foreign_keys.assert_not_called()
