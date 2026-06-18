from __future__ import annotations

from typing import Any, ClassVar

from sqlseed.generators._protocol import UnknownGeneratorError


class GeneratorDispatchMixin:
    _GENERATOR_MAP: ClassVar[dict[str, str]] = {
        "string": "_gen_string",
        "integer": "_gen_integer",
        "float": "_gen_float",
        "boolean": "_gen_boolean",
        "bytes": "_gen_bytes",
        "name": "_gen_name",
        "first_name": "_gen_first_name",
        "last_name": "_gen_last_name",
        "email": "_gen_email",
        "phone": "_gen_phone",
        "address": "_gen_address",
        "company": "_gen_company",
        "url": "_gen_url",
        "ipv4": "_gen_ipv4",
        "uuid": "_gen_uuid",
        "date": "_gen_date",
        "datetime": "_gen_datetime",
        "timestamp": "_gen_timestamp",
        "text": "_gen_text",
        "sentence": "_gen_sentence",
        "password": "_gen_password",
        "choice": "_gen_choice",
        "json": "_gen_json",
        "pattern": "_gen_pattern",
        "username": "_gen_username",
        "city": "_gen_city",
        "country": "_gen_country",
        "state": "_gen_state",
        "zip_code": "_gen_zip_code",
        "job_title": "_gen_job_title",
        "country_code": "_gen_country_code",
    }

    def generate(self, type_name: str, **params: Any) -> Any:
        method_name = self._GENERATOR_MAP.get(type_name)
        if method_name is None:
            raise UnknownGeneratorError(type_name)
        method = getattr(self, method_name)
        return method(**params) if params else method()


def verify_dispatch_sync() -> None:
    """Verify that GENERATOR_MAP entries match actual methods on BaseProvider."""
    # Imports inside function to avoid circular dependency at module load time.
    # pylint: disable=import-outside-toplevel
    from sqlseed.generators.base_provider import BaseProvider  # noqa: PLC0415

    for gen_name, method_name in GeneratorDispatchMixin._GENERATOR_MAP.items():
        if not hasattr(BaseProvider, method_name):
            import warnings  # noqa: PLC0415

            warnings.warn(
                f"GENERATOR_MAP['{gen_name}'] references '{method_name}' which does not exist on BaseProvider",
                stacklevel=1,
            )
