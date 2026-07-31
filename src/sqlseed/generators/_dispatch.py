"""Generator dispatch mixin. Maps 35 generator types to methods and dispatches calls."""

from __future__ import annotations

import warnings
from typing import Any, ClassVar

from sqlseed.generators._protocol import UnknownGeneratorError

# Maximum number of internal retries when ``exclude_values`` is non-empty.
# After this many attempts the last generated value is returned and the
# caller's ConstraintSolver.try_register detects the duplicate and triggers
# backtracking. 50 is chosen to be generous for small value spaces (e.g.
# boolean columns) while bounding the worst-case cost per row.
MAX_GENERATE_RETRIES = 50


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
        "word": "_gen_word",
        "catch_phrase": "_gen_catch_phrase",
        "template": "_gen_template",
        "weighted_choice": "_gen_weighted_choice",
    }

    def generate(
        self,
        type_name: str,
        *,
        exclude_values: set[Any] | None = None,
        **params: Any,
    ) -> Any:
        """Look up the method name for ``type_name`` in ``GENERATOR_MAP`` and call it.

        Raises ``UnknownGeneratorError`` if the type is not registered.

        Args:
            type_name: Generator type name (e.g. ``"email"``).
            exclude_values: Optional set of values the generator should avoid
                producing. When non-empty, retries internally (up to
                :data:`MAX_GENERATE_RETRIES` attempts) to return a value not
                in the set. This is the root-cause fix for the "UNIQUE +
                semantic generators" failure pattern: ``DataStream`` passes
                ``ConstraintSolver.get_seen(col)`` as ``exclude_values`` so
                semantic generators (email/phone/name etc.) can avoid
                producing duplicates on large row counts. ``None`` or an empty
                set means no exclusion (backward compatible, no retry overhead).
                Unhashable values (dict/list) are handled gracefully via a
                linear-scan fallback.
            **params: Generator-specific parameters.

        Returns:
            The generated value. When ``exclude_values`` is non-empty and
            the value space is exhausted after 50 retries, returns the last
            generated value — the caller's ``ConstraintSolver.try_register``
            will detect the duplicate and trigger backtracking.
        """
        method_name = self.GENERATOR_MAP.get(type_name)
        if method_name is None:
            raise UnknownGeneratorError(type_name)
        method = getattr(self, method_name)

        # Fast path: no exclusion (backward compatible, no retry overhead)
        if not exclude_values:
            return method(**params) if params else method()

        # Retry-with-exclude path: avoid producing values already in use.
        # Used by UNIQUE-constrained columns to let semantic generators
        # (email/phone/name etc.) skip duplicates without modifying each
        # individual ``_gen_*`` method.
        last_val: Any = None
        # Some generators may produce unhashable values (dict/list). Try set
        # membership first (O(1)); on TypeError fall back to a list view so
        # the ``in`` check uses linear comparison instead of crashing.
        exclude_seq: set[Any] | list[Any]
        try:
            exclude_seq = set(exclude_values) if not isinstance(exclude_values, set) else exclude_values
        except TypeError:
            exclude_seq = list(exclude_values)
        for _ in range(MAX_GENERATE_RETRIES):
            val = method(**params) if params else method()
            last_val = val
            try:
                excluded = val in exclude_seq
            except TypeError:
                # val is unhashable and exclude_seq is a set — fall back to
                # linear list comparison (slower but correct for any type).
                excluded = val in list(exclude_values)
            if not excluded:
                return val
        # Value space exhausted — return last value and let the caller's
        # ConstraintSolver.try_register detect the duplicate and trigger
        # backtracking. This is the correct signal that the value space is
        # genuinely too small for the requested row count.
        return last_val


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
