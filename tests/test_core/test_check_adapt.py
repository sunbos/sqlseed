"""Tests for core/check_adapt.py: CHECK-constraint adaptation of user YAML configs."""

from __future__ import annotations

from typing import Any

import pytest

from sqlseed.config.models import ColumnConfig
from sqlseed.core.check_adapt import CheckAdapter, _is_chinese_locale
from sqlseed.generators._protocol import ConfigurationError


def _range_checks() -> list[str]:
    return ["age >= 18 AND age <= 120"]


class TestIsChineseLocale:
    def test_zh_variants(self) -> None:
        assert _is_chinese_locale("zh_CN") is True
        assert _is_chinese_locale("zh") is True
        assert _is_chinese_locale("zh-CN") is True
        assert _is_chinese_locale("ZH_tw") is True

    def test_non_zh(self) -> None:
        assert _is_chinese_locale("en_US") is False
        assert _is_chinese_locale("en") is False
        assert _is_chinese_locale("ja_JP") is False


class TestClampRange:
    def test_overlap_upper_clamped(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 18, "max_value": 200})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params["min_value"] == 18
        assert cc.params["max_value"] == 120

    def test_overlap_lower_clamped(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 100})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params["min_value"] == 18
        assert cc.params["max_value"] == 100

    def test_check_subset_clamps_both(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 200})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params["min_value"] == 18
        assert cc.params["max_value"] == 120

    def test_no_overlap_raises(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 10})
        with pytest.raises(ConfigurationError):
            CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())

    def test_unset_bound_adopts_check(self) -> None:
        """用户未设的边界采用 CHECK 边界并写回 params（静默补全，不视为修正）。"""
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 50})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params["min_value"] == 50  # 用户设的不动
        assert cc.params["max_value"] == 120  # 未设的采用 CHECK 上界

    def test_bare_generator_adopts_both_bounds(self) -> None:
        """裸 integer（无 params）必须采用 CHECK 双边界——否则生成越界触发 IntegrityError。"""
        cc = ColumnConfig(name="age", generator="integer", params={})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params["min_value"] == 18
        assert cc.params["max_value"] == 120

    def test_float_exclusive_bound_nudged_by_precision(self) -> None:
        """price > 0.5（浮点严格）：round(uniform(0.5,…),2) 可能产出 0.5，
        必须向域内收一个完整精度单位 → min_value = 0.51。"""
        cc = ColumnConfig(name="price", generator="float", params={"min_value": 0.3, "max_value": 10.0})
        CheckAdapter().adapt_user_configs({"price": cc}, ["price > 0.5"])
        assert cc.params["min_value"] == pytest.approx(0.51)
        assert cc.params["max_value"] == 10.0

    def test_integer_generator_float_bounds_rounded_inward(self) -> None:
        """integer 生成器遇浮点边界：x > 0.5 → 1；x < 5.0 → 4；0.5<=x<=9.5 → [1,9]。"""
        cc = ColumnConfig(name="score", generator="integer", params={})
        CheckAdapter().adapt_user_configs({"score": cc}, ["score > 0.5 AND score < 5.0"])
        assert cc.params["min_value"] == 1
        assert cc.params["max_value"] == 4

        cc2 = ColumnConfig(name="score", generator="integer", params={})
        CheckAdapter().adapt_user_configs({"score": cc2}, ["score >= 0.5 AND score <= 9.5"])
        assert cc2.params["min_value"] == 1
        assert cc2.params["max_value"] == 9

    def test_non_gated_generator_untouched(self) -> None:
        """pattern 等非门控生成器无法机械映射 range CHECK → 保持原样。"""
        cc = ColumnConfig(name="age", generator="pattern", params={"regex": "\\d{2}"})
        CheckAdapter().adapt_user_configs({"age": cc}, _range_checks())
        assert cc.params == {"regex": "\\d{2}"}


class TestClampWeightedChoices:
    """weighted_choice 两种参数形态都必须按 CHECK 枚举钳制（修复漏钳导致的 IntegrityError）。"""

    def test_weighted_choices_dict_clamped(self) -> None:
        cc = ColumnConfig(
            name="status",
            generator="weighted_choice",
            params={"weighted_choices": {"active": 80, "banned": 20}},
        )
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["weighted_choices"] == {"active": 80}

    def test_weighted_choices_dict_no_intersection_raises(self) -> None:
        cc = ColumnConfig(
            name="status",
            generator="weighted_choice",
            params={"weighted_choices": {"banned": 100}},
        )
        with pytest.raises(ConfigurationError):
            CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])

    def test_choices_dict_list_clamped(self) -> None:
        cc = ColumnConfig(
            name="status",
            generator="weighted_choice",
            params={"choices": [{"value": "active", "weight": 80}, {"value": "banned", "weight": 20}]},
        )
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["choices"] == [{"value": "active", "weight": 80}]

    def test_bare_weighted_choice_adopts_uniform(self) -> None:
        cc = ColumnConfig(name="status", generator="weighted_choice", params={})
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["weighted_choices"] == {"active": 1, "inactive": 1}

    def test_scalar_list_untouched(self) -> None:
        """标量列表是 weighted_choice 的未文档化形态 → 保持原样，不硬猜。"""
        cc = ColumnConfig(name="status", generator="weighted_choice", params={"choices": ["active", "banned"]})
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["choices"] == ["active", "banned"]


class TestClampChoices:
    def test_intersection_kept(self) -> None:
        cc = ColumnConfig(name="status", generator="choice", params={"choices": ["active", "x", "y"]})
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["choices"] == ["active"]

    def test_no_intersection_raises(self) -> None:
        cc = ColumnConfig(name="status", generator="choice", params={"choices": ["x", "y"]})
        with pytest.raises(ConfigurationError):
            CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])

    def test_all_valid_unchanged(self) -> None:
        cc = ColumnConfig(name="status", generator="choice", params={"choices": ["active", "inactive"]})
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["choices"] == ["active", "inactive"]

    def test_bare_choice_adopts_check_choices(self) -> None:
        """裸 choice 缺 choices 会在生成时 ValueError；CHECK 枚举既是钳制也是补全。"""
        cc = ColumnConfig(name="status", generator="choice", params={})
        CheckAdapter().adapt_user_configs({"status": cc}, ["status IN ('active', 'inactive')"])
        assert cc.params["choices"] == ["active", "inactive"]


class TestClampLength:
    def test_length_clamped(self) -> None:
        cc = ColumnConfig(name="code", generator="string", params={"min_length": 1, "max_length": 20})
        CheckAdapter().adapt_user_configs({"code": cc}, ["length(code) >= 3 AND length(code) <= 10"])
        assert cc.params["min_length"] == 3
        assert cc.params["max_length"] == 10

    def test_bare_string_adopts_length_bounds(self) -> None:
        cc = ColumnConfig(name="code", generator="string", params={})
        CheckAdapter().adapt_user_configs({"code": cc}, ["length(code) >= 3 AND length(code) <= 10"])
        assert cc.params["min_length"] == 3
        assert cc.params["max_length"] == 10


class TestSkippedCases:
    def test_derived_column_skipped(self) -> None:
        """derive_from 派生列无独立生成值域，不动。"""
        cc = ColumnConfig(name="total", derive_from="subtotal", expression="value * 2")
        CheckAdapter().adapt_user_configs({"total": cc}, ["total >= 0"])
        assert cc.params == {}

    def test_unresolvable_check_skipped(self) -> None:
        """跨列 CHECK（check_parser 降级）保持原样，交 AI/人工。"""
        cc = ColumnConfig(name="discount", generator="integer", params={"min_value": 0, "max_value": 999})
        CheckAdapter().adapt_user_configs({"discount": cc}, ["discount <= subtotal"])
        assert cc.params["max_value"] == 999  # 未被改动

    def test_empty_checks_noop(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 10})
        CheckAdapter().adapt_user_configs({"age": cc}, [])
        assert cc.params["max_value"] == 10


class TestBilingualMessages:
    def test_chinese_no_intersection_message(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 10})
        with pytest.raises(ConfigurationError, match="完全无交集"):
            CheckAdapter(locale="zh_CN").adapt_user_configs({"age": cc}, _range_checks())

    def test_english_no_intersection_message(self) -> None:
        cc = ColumnConfig(name="age", generator="integer", params={"min_value": 0, "max_value": 10})
        with pytest.raises(ConfigurationError, match="no overlap"):
            CheckAdapter(locale="en_US").adapt_user_configs({"age": cc}, _range_checks())


class TestOrchestratorIntegration:
    """端到端：_resolve_specs 中的 CHECK 适配 + 零配置声明。"""

    @staticmethod
    def _make_db(db_path: str) -> None:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE t ("
            "id INTEGER PRIMARY KEY, "
            "age INTEGER CHECK(age >= 18 AND age <= 120), "
            "status TEXT CHECK(status IN ('active', 'inactive')))"
        )
        conn.commit()
        conn.close()

    def test_config_path_adaptation_produces_compliant_data(self, tmp_path: Any) -> None:
        """yml 配置 [18,200] 被钳制为 [18,120]，生成数据全部合规。"""
        import sqlseed

        db = str(tmp_path / "c.db")
        self._make_db(db)
        result = sqlseed.fill(
            db,
            table="t",
            count=200,
            columns={"age": {"generator": "integer", "params": {"min_value": 18, "max_value": 200}}},
            provider="faker",
            seed=7,
        )
        assert result.count == 200
        import sqlite3

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT age FROM t").fetchall()
        conn.close()
        assert all(18 <= r[0] <= 120 for r in rows), "钳制后所有 age 必须在 [18,120]"

    def test_config_path_no_overlap_raises(self, tmp_path: Any) -> None:
        import sqlseed

        db = str(tmp_path / "n.db")
        self._make_db(db)
        with pytest.raises(ConfigurationError):
            sqlseed.fill(
                db,
                table="t",
                count=10,
                columns={"age": {"generator": "integer", "params": {"min_value": 0, "max_value": 10}}},
                provider="faker",
            )

    def test_bare_generator_config_produces_compliant_data(self, tmp_path: Any) -> None:
        """回归：裸 integer（无 params）必须采用 CHECK 边界——此前未写回导致 IntegrityError。"""
        import sqlite3

        import sqlseed

        db = str(tmp_path / "bare.db")
        conn = sqlite3.connect(db)
        # 中性列名（不命中 mapper 名称规则），确保合规性来自 CHECK 采用而非列名推断
        conn.execute("CREATE TABLE bare (id INTEGER PRIMARY KEY, zqxw INTEGER CHECK(zqxw >= 18 AND zqxw <= 120))")
        conn.commit()
        conn.close()
        result = sqlseed.fill(
            db, table="bare", count=200, columns={"zqxw": {"generator": "integer"}}, provider="faker", seed=3
        )
        assert result.count == 200
        conn = sqlite3.connect(db)
        vals = [r[0] for r in conn.execute("SELECT zqxw FROM bare").fetchall()]
        conn.close()
        assert len(vals) == 200
        assert all(18 <= v <= 120 for v in vals)

    def test_weighted_choice_config_produces_compliant_data(self, tmp_path: Any) -> None:
        """回归：weighted_choice 含非法枚举必须被钳制——此前漏钳触发 IntegrityError。"""
        import sqlite3

        import sqlseed

        db = str(tmp_path / "w.db")
        self._make_db(db)
        result = sqlseed.fill(
            db,
            table="t",
            count=200,
            columns={
                "status": {"generator": "weighted_choice", "params": {"weighted_choices": {"active": 80, "banned": 20}}}
            },
            provider="faker",
            seed=3,
        )
        assert result.count == 200
        conn = sqlite3.connect(db)
        vals = [r[0] for r in conn.execute("SELECT status FROM t").fetchall()]
        conn.close()
        assert len(vals) == 200
        assert all(v in ("active", "inactive") for v in vals)

    def test_zero_config_emits_boundary_notice(self, tmp_path: Any) -> None:
        """零配置 + 有 CHECK → _resolve_specs 触发能力边界声明（zh/en 文案正确）。"""
        import sqlseed.core.orchestrator._specs as specs_mod
        from sqlseed.core.orchestrator import DataOrchestrator

        db = str(tmp_path / "z.db")
        self._make_db(db)
        for locale, needle in (("zh_CN", "零配置"), ("en_US", "Zero-config")):
            with DataOrchestrator(db, provider_name="faker", locale=locale) as orch:
                checks = orch._db.get_check_constraints("t")
                captured: list[str] = []

                def _capture(msg: str, *a: Any, _c: list[str] = captured, **k: Any) -> None:
                    _c.append(msg)

                orig = specs_mod.logger.warning
                specs_mod.logger.warning = _capture  # type: ignore[assignment]
                try:
                    orch._declare_zero_config_check_boundary("t", checks)
                finally:
                    specs_mod.logger.warning = orig  # type: ignore[assignment]
                assert captured, f"locale={locale} 应产生声明"
                assert needle in captured[0]
                assert "age" in captured[0] and "status" in captured[0]

    def test_zero_config_no_notice_without_check(self, tmp_path: Any) -> None:
        """零配置 + 无 CHECK → 不产生声明（无噪音）。"""
        import sqlite3

        from sqlseed.core.orchestrator import DataOrchestrator

        db = str(tmp_path / "plain.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE plain (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()
        with DataOrchestrator(db, provider_name="faker", locale="en_US") as orch:
            checks = orch._db.get_check_constraints("plain")
            assert checks == []  # 无 CHECK 时 _resolve_specs 的 elif 分支不触发
