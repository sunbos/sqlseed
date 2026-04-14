from __future__ import annotations

from typing import Any


class AIProvider:

    @property
    def name(self) -> str:
        return "ai"

    def set_locale(self, locale: str) -> None:
        pass

    def set_seed(self, seed: int) -> None:
        pass

    def generate_string(self, **kwargs: Any) -> str:
        return ""

    def generate_integer(self, **kwargs: Any) -> int:
        return 0

    def generate_float(self, **kwargs: Any) -> float:
        return 0.0

    def generate_boolean(self) -> bool:
        return False

    def generate_bytes(self, **kwargs: Any) -> bytes:
        return b""

    def generate_name(self) -> str:
        return ""

    def generate_first_name(self) -> str:
        return ""

    def generate_last_name(self) -> str:
        return ""

    def generate_email(self) -> str:
        return ""

    def generate_phone(self) -> str:
        return ""

    def generate_address(self) -> str:
        return ""

    def generate_company(self) -> str:
        return ""

    def generate_url(self) -> str:
        return ""

    def generate_ipv4(self) -> str:
        return ""

    def generate_uuid(self) -> str:
        return ""

    def generate_date(self, **kwargs: Any) -> str:
        return ""

    def generate_datetime(self, **kwargs: Any) -> str:
        return ""

    def generate_timestamp(self) -> int:
        return 0

    def generate_text(self, **kwargs: Any) -> str:
        return ""

    def generate_sentence(self) -> str:
        return ""

    def generate_password(self, **kwargs: Any) -> str:
        return ""

    def generate_choice(self, choices: list[Any]) -> Any:
        return choices[0] if choices else None

    def generate_json(self, **kwargs: Any) -> str:
        return "{}"

    def generate_pattern(self, *, regex: str, **kwargs: Any) -> str:
        return ""
