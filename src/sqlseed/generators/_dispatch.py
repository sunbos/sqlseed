"""Generator dispatch mixin. Maps 31 generator types to methods and dispatches calls."""

from __future__ import annotations

import warnings
from typing import Any, ClassVar

from sqlseed.generators._protocol import UnknownGeneratorError


class GeneratorDispatchMixin:
    """Generator dispatch mixin.

    Maps generator type names to ``_gen_*`` methods via ``GENERATOR_MAP`` and
    dispatches calls through ``generate``.
    """

    GENERATOR_MAP: ClassVar[dict[str, str]] = {
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
        """Look up the method name for ``type_name`` in ``GENERATOR_MAP`` and call it.

        Raises ``UnknownGeneratorError`` if the type is not registered.
        """
        method_name = self.GENERATOR_MAP.get(type_name)
        if method_name is None:
            raise UnknownGeneratorError(type_name)
        method = getattr(self, method_name)
        return method(**params) if params else method()


def verify_dispatch_sync(provider_class: type) -> None:
    """Verify that the method names in ``GENERATOR_MAP`` actually exist on ``provider_class``.

    Args:
        provider_class: The provider class to verify against (e.g., ``BaseProvider``).

    Emits a warning for any missing methods.
    """
    for gen_name, method_name in GeneratorDispatchMixin.GENERATOR_MAP.items():
        if not hasattr(provider_class, method_name):
            warnings.warn(
                f"GENERATOR_MAP['{gen_name}'] references '{method_name}' which does not exist on "
                f"{provider_class.__name__}",
                stacklevel=1,
            )
