from __future__ import annotations

from typing import Any

from sqlseed.generators.faker_provider import FakerProvider

from ._mixin import (
    IdentityProviderTestMixin,
    JsonSchemaTestMixin,
    NativePhoneProviderTestMixin,
    TemporalProviderTestMixin,
)


class TestFakerProvider(
    IdentityProviderTestMixin,
    JsonSchemaTestMixin,
    TemporalProviderTestMixin,
):
    def setup_method(self) -> None:
        self.provider = FakerProvider()

    def test_name(self) -> None:
        assert self.provider.name == "faker"


class TestLocaleFallback(NativePhoneProviderTestMixin):
    """使用当前 locale 的等价方法；确实缺失时才降级为 Base placeholder。"""

    def setup_method(self) -> None:
        self.provider = FakerProvider()

    def test_zh_cn_state_uses_province(self) -> None:
        """zh_CN 的 province() 是真实省份来源，不应被误判为缺少能力。"""
        self.provider.set_locale("zh_CN")
        value = self.provider.generate("state")
        assert isinstance(value, str)
        assert not value.startswith("state_")
        assert any("\u4e00" <= char <= "\u9fff" for char in value)

    def test_zh_cn_zip_code_uses_postcode(self) -> None:
        """zh_CN 的 postcode() 生成六位数字邮政编码。"""
        self.provider.set_locale("zh_CN")
        value = self.provider.generate("zip_code")
        assert isinstance(value, str)
        assert len(value) == 6 and value.isdigit()

    def test_en_us_state_uses_real_data(self) -> None:
        """en_US 支持 state → 不触发降级，返回真实州名（非占位格式）。"""
        self.provider.set_locale("en_US")
        value = self.provider.generate("state")
        assert isinstance(value, str)
        assert not value.startswith("state_")

    def test_locale_switch_back_clears_fallback(self) -> None:
        """真实缺失地区方法的 zh_TW 切回 en_US，必须清除旧遮蔽。"""
        self.provider.set_locale("zh_TW")
        assert self.provider.generate("state").startswith("state_")
        self.provider.set_locale("en_US")
        assert not self.provider.generate("state").startswith("state_")

    def test_fallback_preserves_seed_determinism(self) -> None:
        """降级路径走 base 的 _rng + 计数器（均随实例初始化）→ 同 seed 同结果。

        与实际用法一致：每次 fill 新建 provider 实例并播种一次。
        """

        def _gen_with_seed() -> Any:
            p = FakerProvider()
            p.set_locale("zh_TW")
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

    def test_phone_custom_mask(self) -> None:
        """显式传 mask 参数时按 mask 生成（统一格式的可控覆盖）。"""
        phone = self.provider.generate("phone", mask="###.###.####")
        assert isinstance(phone, str)
        assert len(phone) == 12
        assert phone[3] == "." and phone[7] == "."
        assert phone.replace(".", "").isdigit()
