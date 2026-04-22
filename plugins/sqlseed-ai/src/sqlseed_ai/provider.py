from __future__ import annotations

from typing import Any

from sqlseed.generators._dispatch import GeneratorDispatchMixin

_NO_PARAM_DEFAULTS: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "float": 0.0,
    "boolean": False,
    "bytes": b"",
    "name": "",
    "first_name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "address": "",
    "company": "",
    "url": "",
    "ipv4": "",
    "uuid": "",
    "date": "",
    "datetime": "",
    "timestamp": 0,
    "text": "",
    "sentence": "",
    "password": "",
    "json": "{}",
    "pattern": "",
}


class AIProvider(GeneratorDispatchMixin):
    _RETURN_DEFAULTS: dict[str, Any] = _NO_PARAM_DEFAULTS

    @property
    def name(self) -> str:
        return "ai"

    def set_locale(self, _locale: str) -> None:
        # AI provider does not use locale-specific generation
        pass

    def set_seed(self, _seed: int) -> None:
        # AI provider does not rely on local random seeds
        pass

    def _gen_choice(self, choices: list[Any]) -> Any:
        return choices[0] if choices else None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_gen_"):
            type_key = name[5:]
            if type_key in self._RETURN_DEFAULTS:
                default = self._RETURN_DEFAULTS[type_key]

                def _stub(**_kwargs: Any) -> Any:
                    return default

                _stub.__name__ = name
                return _stub
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
