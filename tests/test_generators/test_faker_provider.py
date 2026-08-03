from __future__ import annotations

from typing import Any

from sqlseed.generators.faker_provider import FakerProvider

from ._mixin import (
    CoreProviderTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
)


class TestFakerProvider(
    CoreProviderTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
):
    def setup_method(self) -> None:
        self.provider = FakerProvider()

    def test_name(self) -> None:
        assert self.provider.name == "faker"


class TestLocaleFallback:
    """faker 部分方法仅特定 locale 实现（实证：zh_CN 缺 state/zipcode，ja_JP 缺 state）。

    缺失时必须按 mimesis → faker → base 的兜底链降级为 base 的类型路由实现，
    而不是让生成在 AttributeError 中崩溃（可靠性：生成中途崩溃=整批失败）。
    """

    def setup_method(self) -> None:
        self.provider = FakerProvider()

    def test_zh_cn_state_falls_back_to_base(self) -> None:
        """zh_CN 无 state() → 降级为 base 占位（state_NNN_xxxx 格式），不崩溃。"""
        self.provider.set_locale("zh_CN")
        value = self.provider.generate("state")
        assert isinstance(value, str)
        assert value.startswith("state_")

    def test_zh_cn_zip_code_falls_back_to_base(self) -> None:
        """zh_CN 无 zipcode() → 降级为 base 的 5 位数字占位。"""
        self.provider.set_locale("zh_CN")
        value = self.provider.generate("zip_code")
        assert isinstance(value, str)
        assert len(value) == 5 and value.isdigit()

    def test_en_us_state_uses_real_data(self) -> None:
        """en_US 支持 state → 不触发降级，返回真实州名（非占位格式）。"""
        self.provider.set_locale("en_US")
        value = self.provider.generate("state")
        assert isinstance(value, str)
        assert not value.startswith("state_")

    def test_locale_switch_back_clears_fallback(self) -> None:
        """zh_CN 降级后切回 en_US：实例级遮蔽必须清除，恢复真实数据。"""
        self.provider.set_locale("zh_CN")
        assert self.provider.generate("state").startswith("state_")
        self.provider.set_locale("en_US")
        assert not self.provider.generate("state").startswith("state_")

    def test_fallback_preserves_seed_determinism(self) -> None:
        """降级路径走 base 的 _rng + 计数器（均随实例初始化）→ 同 seed 同结果。

        与实际用法一致：每次 fill 新建 provider 实例并播种一次。
        """

        def _gen_with_seed() -> Any:
            p = FakerProvider()
            p.set_locale("zh_CN")
            p.set_seed(7)
            return p.generate("state")

        assert _gen_with_seed() == _gen_with_seed()

    def test_supported_generator_unaffected(self) -> None:
        """zh_CN 支持的方法（name）保持真实数据，不被降级波及。"""
        self.provider.set_locale("zh_CN")
        value = self.provider.generate("name")
        assert isinstance(value, str) and value
        assert not value.startswith("first_")

    def test_generate_word_returns_real_word(self) -> None:
        """Faker's word() returns a real English word (non-empty alphabetic string)."""
        result = self.provider.generate("word")
        assert isinstance(result, str)
        assert len(result) > 0
        assert result.isalpha()

    def test_phone_default_follows_locale(self) -> None:
        """默认 phone 按 locale 生成真实号码（非空字符串，含数字）。

        默认 mask=None 走 faker 原生 phone_number()，按 locale 输出真实
        国家格式，不强制统一（如 en_US 可能带分机号），保证业务真实性。
        """
        for _ in range(20):
            phone = self.provider.generate("phone")
            assert isinstance(phone, str)
            assert len(phone) > 0
            assert any(c.isdigit() for c in phone)

    def test_phone_custom_mask(self) -> None:
        """显式传 mask 参数时按 mask 生成（统一格式的可控覆盖）。"""
        phone = self.provider.generate("phone", mask="###.###.####")
        assert isinstance(phone, str)
        assert len(phone) == 12
        assert phone[3] == "." and phone[7] == "."
        assert phone.replace(".", "").isdigit()
