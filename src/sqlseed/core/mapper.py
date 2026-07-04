"""Column mapper: infers column generators via a 9-level strategy chain.

Infers an appropriate generator spec (GeneratorSpec) for each column based on a
multi-level strategy chain considering column name, type, default value, user config, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from sqlseed.config.models import CustomColumnMappings
    from sqlseed.database._protocol import ColumnInfo


@dataclass
class GeneratorSpec:
    """Generator spec: describes which data generator and parameters a column should use.

    Encapsulates generator name, parameters, null ratio, and native provider method info:
    serves as the unified contract between the column mapper and data generators.
    """

    generator_name: str
    params: dict[str, Any] = field(default_factory=dict)
    null_ratio: float = 0.0
    provider: str | None = None
    native_faker_method: str | None = None
    native_mimesis_method: str | None = None
    native_params: dict[str, Any] | None = None


class ColumnMapper:
    """Column mapper: infers column generator specs based on a 9-level strategy chain.

    Strategy chain order (priority from high to low):
      1. Primary key autoincrement columns are skipped directly;
      2. User explicit config (user_config);
      3. Column name exact match (including custom rules);
      4. Column default value / nullability handling;
      5. Column name regex pattern match (including custom rules);
      6. CamelCase to snake_case conversion then exact match again;
      7. Pattern match again after snake_case conversion;
      8. Fallback default value / nullability handling (include_nullable=True);
      9. Type-faithful fallback (inferred by SQL type).
    """

    EXACT_MATCH_RULES: ClassVar[dict[str, str]] = {
        "email": "email",
        "phone": "phone",
        "telephone": "phone",
        "mobile": "phone",
        "address": "address",
        "name": "name",
        "username": "username",
        "user_name": "username",
        "nickname": "username",
        "first_name": "first_name",
        "last_name": "last_name",
        "full_name": "name",
        "company": "company",
        "organization": "company",
        "ip": "ipv4",
        "ip_address": "ipv4",
        "url": "url",
        "website": "url",
        "homepage": "url",
        "avatar": "url",
        "avatar_url": "url",
        "uuid": "uuid",
        "guid": "uuid",
        "token": "uuid",
        "password": "password",
        "passwd": "password",
        "secret": "password",
        "status": "choice",
        "state": "state",
        "gender": "choice",
        "sex": "choice",
        "type": "choice",
        "level": "choice",
        "priority": "choice",
        "role": "choice",
        "age": "integer",
        "count": "integer",
        "quantity": "integer",
        "amount": "float",
        "price": "float",
        "cost": "float",
        "salary": "float",
        "balance": "float",
        "score": "float",
        "rating": "float",
        "weight": "float",
        "height": "float",
        "title": "sentence",
        "subject": "sentence",
        "headline": "sentence",
        "bio": "text",
        "biography": "text",
        "description": "text",
        "summary": "text",
        "content": "text",
        "body": "text",
        "comment": "text",
        "note": "text",
        "remark": "text",
        "latitude": "float",
        "longitude": "float",
        "lat": "float",
        "lng": "float",
        "city": "city",
        "country": "country",
        "zip_code": "zip_code",
        "postal_code": "zip_code",
        "postcode": "zip_code",
        "province": "state",
        "region": "state",
        "job_title": "job_title",
        "occupation": "job_title",
        "position": "job_title",
        "country_code": "country_code",
    }

    EXACT_MATCH_PARAMS: ClassVar[dict[str, dict[str, Any]]] = {
        "age": {"min_value": 18, "max_value": 65},
        "count": {"min_value": 0, "max_value": 10000},
        "quantity": {"min_value": 1, "max_value": 100},
        "amount": {"min_value": 0.01, "max_value": 99999.99, "precision": 2},
        "price": {"min_value": 0.01, "max_value": 9999.99, "precision": 2},
        "cost": {"min_value": 0.01, "max_value": 9999.99, "precision": 2},
        "salary": {"min_value": 3000.0, "max_value": 100000.0, "precision": 2},
        "balance": {"min_value": 0.0, "max_value": 999999.99, "precision": 2},
        "score": {"min_value": 0.0, "max_value": 100.0, "precision": 1},
        "rating": {"min_value": 1.0, "max_value": 5.0, "precision": 1},
        "weight": {"min_value": 0.1, "max_value": 500.0, "precision": 1},
        "height": {"min_value": 50.0, "max_value": 250.0, "precision": 1},
        "latitude": {"min_value": -90.0, "max_value": 90.0, "precision": 6},
        "longitude": {"min_value": -180.0, "max_value": 180.0, "precision": 6},
        "lat": {"min_value": -90.0, "max_value": 90.0, "precision": 6},
        "lng": {"min_value": -180.0, "max_value": 180.0, "precision": 6},
        "status": {"choices": [0, 1]},
        "gender": {"choices": ["male", "female", "other"]},
        "sex": {"choices": ["male", "female"]},
        "type": {"choices": [1, 2, 3]},
        "level": {"choices": [1, 2, 3, 4, 5]},
        "priority": {"choices": ["low", "medium", "high"]},
        "role": {"choices": ["admin", "user", "guest"]},
        "bio": {"min_length": 50, "max_length": 200},
        "description": {"min_length": 100, "max_length": 500},
        "content": {"min_length": 200, "max_length": 1000},
        "comment": {"min_length": 10, "max_length": 200},
    }

    PATTERN_MATCH_RULES: ClassVar[tuple[tuple[str, str, dict[str, Any]], ...]] = (
        (r"^id$", "autoincrement", {}),
        (r".*_id$", "foreign_key_or_integer", {}),
        (
            r".*(?:user|card|identity)(?:_no|_number|_nbr)$",
            "string",
            {"min_length": 8, "max_length": 20, "charset": "alphanumeric"},
        ),
        (r".*_no$|.*_nbr$", "foreign_key_or_integer", {}),
        (r".*_ids$", "json", {}),
        (r".*_at$", "datetime", {}),
        (r".*_date$", "date", {}),
        (r".*_time$", "datetime", {}),
        (r".*_timestamp$", "timestamp", {}),
        (r"^created$", "datetime", {}),
        (r"^updated$", "datetime", {}),
        (r"^deleted$", "datetime", {}),
        (
            r"^quantity$|.*_quantity$|.*_sold$|.*_count$|.*_num$|.*_number$",
            "integer",
            {"min_value": 1, "max_value": 50},
        ),
        (r".*_amount$|.*_price$|.*_cost$|.*_fee$", "float", {"min_value": 0.1, "max_value": 999.99, "precision": 2}),
        (r".*_rate$|.*_ratio$|.*_percent$", "float", {"min_value": 0.0, "max_value": 1.0, "precision": 4}),
        (r"^is_.*|^has_.*|^can_.*|^should_.*|^enable.*|^disable.*", "boolean", {}),
        (r".*_code$", "string", {"min_length": 6, "max_length": 12, "charset": "alphanumeric"}),
        # Person-name contexts: explicit human-related prefixes → real person names.
        (
            r".*(?:user|customer|employee|member|author|student|teacher|patient|person|contact|owner|admin|guest|subscriber)_name$",
            "name",
            {},
        ),
        # High-confidence domain contexts: strong semantic match → specialized generator.
        (r".*(?:company|org|organization|department|unit|vendor|supplier|brand)_name$", "company", {}),
        # General *_name fallback: real word (not person name) — semantically neutral
        # for animal_name, medicine_name, plant_name, color_name, course_name, etc.
        # AI (sqlseed-ai) can override with more specific generators when enabled.
        (r".*_name$", "word", {}),
        (r".*_email$", "email", {}),
        (r".*_phone$|.*_tel$|.*_mobile$", "phone", {}),
        (r".*_url$|.*_link$|.*_href$", "url", {}),
        (r".*_path$|.*_file$", "string", {"min_length": 10, "max_length": 100}),
        (r".*_key$|.*_token$|.*_hash$", "uuid", {}),
        (r".*_password$|.*_passwd$|.*_secret$", "password", {}),
        (r".*_address$", "address", {}),
        (r".*_description$|.*_desc$|.*_text$|.*_content$|.*_body$", "text", {"min_length": 50, "max_length": 300}),
        (r".*_title$|.*_subject$|.*_headline$", "sentence", {}),
    )

    TYPE_FALLBACK_RULES: ClassVar[dict[str, tuple[str, dict[str, Any]]]] = {
        "INTEGER": ("integer", {"min_value": 0, "max_value": 999999}),
        "INT8": ("integer", {"min_value": 0, "max_value": 255}),
        "INT16": ("integer", {"min_value": 0, "max_value": 65535}),
        "INT32": ("integer", {"min_value": 0, "max_value": 2147483647}),
        "INT64": ("integer", {"min_value": 0, "max_value": 999999999}),
        "INT": ("integer", {"min_value": 0, "max_value": 999999}),
        "TINYINT": ("integer", {"min_value": 0, "max_value": 255}),
        "SMALLINT": ("integer", {"min_value": 0, "max_value": 32767}),
        "BIGINT": ("integer", {"min_value": 0, "max_value": 999999999}),
        "REAL": ("float", {"min_value": 0.0, "max_value": 999999.0, "precision": 2}),
        "FLOAT": ("float", {"min_value": 0.0, "max_value": 999999.0, "precision": 2}),
        "DOUBLE": ("float", {"min_value": 0.0, "max_value": 999999.0, "precision": 2}),
        "DECIMAL": ("float", {"min_value": 0.0, "max_value": 999999.0, "precision": 2}),
        "NUMERIC": ("float", {"min_value": 0.0, "max_value": 999999.0}),
        "TEXT": ("string", {"min_length": 5, "max_length": 50}),
        "BLOB": ("bytes", {"length": 32}),
        "BOOLEAN": ("boolean", {}),
        "DATE": ("date", {}),
        "DATETIME": ("datetime", {}),
        "TIMESTAMP": ("timestamp", {}),
        "VARCHAR": ("string", {}),
        "CHAR": ("string", {}),
    }

    def __init__(self) -> None:
        """Initialize the column mapper: prepare custom exact match and pattern match rule containers."""
        self._custom_exact_rules: dict[str, tuple[str, dict[str, Any]]] = {}
        self._custom_pattern_rules: list[tuple[str, str, dict[str, Any]]] = []

    def register_exact_rule(self, column_name: str, generator: str, params: dict[str, Any] | None = None) -> None:
        """Register a custom column name exact match rule: priority is higher than built-in rules."""
        self._custom_exact_rules[column_name.lower()] = (generator, params or {})

    def register_pattern_rule(self, pattern: str, generator: str, params: dict[str, Any] | None = None) -> None:
        """Register a custom column name regex pattern match rule: priority is higher than built-in rules."""
        self._custom_pattern_rules.append((pattern, generator, params or {}))

    def load_custom_mappings(self, mappings: CustomColumnMappings) -> None:
        """Load custom column mappings from a YAML config (``CustomColumnMappings``).

        Both exact-match and pattern-match rules are registered with higher
        priority than the built-in rules, allowing users to override incorrect
        mappings without modifying core code or writing a plugin.
        """
        for col_name, exact_rule in mappings.exact.items():
            self.register_exact_rule(col_name, exact_rule.generator, exact_rule.params)
        for pattern_rule in mappings.pattern:
            self.register_pattern_rule(pattern_rule.pattern, pattern_rule.generator, pattern_rule.params)

    def _match_exact(self, column_name: str) -> GeneratorSpec | None:
        """Perform column name exact match against custom rules then built-in rules: returns generator spec or None."""
        if column_name in self._custom_exact_rules:
            gen, params = self._custom_exact_rules[column_name]
            return GeneratorSpec(generator_name=gen, params=params)

        if column_name in self.EXACT_MATCH_RULES:
            gen = self.EXACT_MATCH_RULES[column_name]
            params = self.EXACT_MATCH_PARAMS.get(column_name, {})
            return GeneratorSpec(generator_name=gen, params=params)

        return None

    def _match_pattern(self, column_name: str) -> GeneratorSpec | None:
        """Perform column name regex pattern match against custom rules then built-in rules.

        Returns the generator spec or None.
        """
        for pattern, gen, params in self._custom_pattern_rules:
            if re.match(pattern, column_name):
                return GeneratorSpec(generator_name=gen, params=params)

        for pattern, gen, params in self.PATTERN_MATCH_RULES:
            if re.match(pattern, column_name):
                return GeneratorSpec(generator_name=gen, params=params)

        return None

    def _map_from_user_config(self, user_config: Any) -> GeneratorSpec | None:
        """Build a generator spec from explicit user config; returns None if no generator is provided."""
        if user_config and hasattr(user_config, "generator") and user_config.generator:
            provider_val = (
                user_config.provider.value if hasattr(user_config, "provider") and user_config.provider else None
            )
            return GeneratorSpec(
                generator_name=user_config.generator,
                params=user_config.params if hasattr(user_config, "params") else {},
                null_ratio=user_config.null_ratio if hasattr(user_config, "null_ratio") else 0.0,
                provider=provider_val,
                native_faker_method=getattr(user_config, "faker_method", None),
                native_mimesis_method=getattr(user_config, "mimesis_method", None),
                native_params=getattr(user_config, "native_params", None) or None,
            )
        return None

    def _map_from_default(
        self,
        column_info: ColumnInfo,
        column_type: str,
        enrich: bool,
        force_type_infer: bool,
        *,
        include_nullable: bool = False,
    ) -> GeneratorSpec | None:
        """Generate a spec based on the column default value or nullability.

        When the column has a default value (or is nullable and include_nullable=True):
        - If force_type_infer is True, falls back to type-faithful inference;
        - If enrich is True, returns an __enrich__ spec preserving the original default value;
        - Otherwise returns skip to skip generation for this column.
        """
        if column_info.default is not None or (include_nullable and column_info.nullable):
            if force_type_infer:
                return self._type_faithful_fallback(column_type)
            if enrich:
                return GeneratorSpec(
                    generator_name="__enrich__",
                    params={"_default": column_info.default, "_nullable": column_info.nullable},
                )
            return GeneratorSpec(generator_name="skip")
        return None

    _CAMELCASE_RE: ClassVar[re.Pattern[str]] = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

    @classmethod
    def _to_snake_case(cls, name: str) -> str:
        """Convert CamelCase naming to snake_case: to facilitate subsequent matching."""
        return cls._CAMELCASE_RE.sub("_", name).lower()

    def map_column(
        self,
        column_info: ColumnInfo,
        user_config: Any = None,
        *,
        enrich: bool = False,
        force_type_infer: bool = False,
    ) -> GeneratorSpec:
        """Infer a generator spec for a single column via the 9-level strategy chain.

        When enrich is True, returns an __enrich__ spec (instead of skip) for columns
        with default values; when force_type_infer is True, forces fallback by SQL type,
        ignoring the default-value skip logic.

        Strategy levels L1-L5 are evaluated inline (PK skip, user config, exact
        match, default value, pattern match). Levels L6-L9 (snake_case retry,
        nullable fallback, type-faithful fallback) are delegated to
        :meth:`_match_snake_retry_or_fallback` to keep the return-statement
        count within pylint's threshold while preserving the documented
        strategy order.
        """
        column_name = column_info.name.lower()
        column_type = column_info.type.upper() if column_info.type else "TEXT"

        if getattr(column_info, "is_computed", False):
            return GeneratorSpec(generator_name="skip")

        if column_info.is_primary_key and (
            column_info.is_autoincrement or "INTEGER" in column_type or "INT" in column_type
        ):
            return GeneratorSpec(generator_name="skip")

        user_spec = self._map_from_user_config(user_config)
        if user_spec:
            exact_match = self._match_exact(column_name) or self._match_pattern(column_name)
            if exact_match:
                # Group Merge Compatibility: allow parameter merging across string-like generators
                same_group = False
                if exact_match.generator_name == user_spec.generator_name:
                    same_group = True
                else:
                    string_generators = {"string", "text", "sentence"}
                    if (
                        exact_match.generator_name in string_generators
                        and user_spec.generator_name in string_generators
                    ):
                        same_group = True

                if same_group:
                    merged_params = dict(exact_match.params)
                    merged_params.update(user_spec.params)
                    # Resolve min_length/max_length conflicts that would crash
                    # string/text generators (rng.randint raises ValueError
                    # when min > max). This happens when the user supplies a
                    # min_length larger than the rule's max_length.
                    min_len = merged_params.get("min_length")
                    max_len = merged_params.get("max_length")
                    if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
                        merged_params.pop("max_length", None)
                    user_spec.params = merged_params
            return user_spec

        exact_match = self._match_exact(column_name)
        if exact_match:
            return exact_match

        default_spec = self._map_from_default(column_info, column_type, enrich, force_type_infer)
        if default_spec:
            return default_spec

        pattern_match = self._match_pattern(column_name)
        if pattern_match:
            return pattern_match

        return self._match_snake_retry_or_fallback(column_info, column_name, column_type, enrich, force_type_infer)

    def _match_snake_retry_or_fallback(
        self,
        column_info: ColumnInfo,
        column_name: str,
        column_type: str,
        enrich: bool,
        force_type_infer: bool,
    ) -> GeneratorSpec:
        """Levels L6-L9 of the 9-level strategy chain.

        - L6: CamelCase -> snake_case exact retry
        - L7: snake_case pattern retry
        - L8: nullable fallback (default value with include_nullable=True)
        - L9: type-faithful fallback by SQL type

        Extracted from :meth:`map_column` to keep the parent method within
        pylint's too-many-return-statements threshold. The strategy order is
        preserved exactly as documented in CLAUDE.md.
        """
        snake_name = self._to_snake_case(column_info.name)
        if snake_name != column_name:
            snake_exact = self._match_exact(snake_name)
            if snake_exact:
                return snake_exact
            snake_pattern = self._match_pattern(snake_name)
            if snake_pattern:
                return snake_pattern

        fallback_spec = self._map_from_default(
            column_info,
            column_type,
            enrich,
            force_type_infer,
            include_nullable=True,
        )
        if fallback_spec:
            return fallback_spec

        return self._type_faithful_fallback(column_type)

    def _type_faithful_fallback(self, column_type: str) -> GeneratorSpec:
        """Infer a generator spec via type-faithful fallback by SQL type: preserving length info where possible."""
        length_match = re.search(r"\((\d+)\)", column_type)
        max_length = int(length_match.group(1)) if length_match else None

        base_type = re.sub(r"\(.*\)", "", column_type).strip()

        for type_prefix, (gen, default_params) in self.TYPE_FALLBACK_RULES.items():
            if base_type.startswith(type_prefix):
                params = dict(default_params)
                if max_length is not None:
                    if gen == "string":
                        params["min_length"] = 1
                        params["max_length"] = max_length
                    elif gen == "bytes":
                        params["length"] = max_length
                return GeneratorSpec(generator_name=gen, params=params)

        return GeneratorSpec(generator_name="string", params={"min_length": 5, "max_length": 50})

    def map_columns(
        self,
        columns: list[ColumnInfo],
        user_configs: dict[str, Any] | None = None,
        *,
        enrich: bool = False,
    ) -> dict[str, GeneratorSpec]:
        """Batch-map multiple columns into a generator spec dict.

        Optionally accepts user configs indexed by column name.
        """
        user_configs = user_configs or {}
        result: dict[str, GeneratorSpec] = {}
        for col in columns:
            col_config = user_configs.get(col.name)
            result[col.name] = self.map_column(col, col_config, enrich=enrich)
        return result
