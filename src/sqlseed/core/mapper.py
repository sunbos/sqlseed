from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo


@dataclass
class GeneratorSpec:
    generator_name: str
    params: dict[str, Any] = field(default_factory=dict)
    null_ratio: float = 0.0
    provider: str | None = None


class ColumnMapper:
    EXACT_MATCH_RULES: ClassVar[dict[str, str]] = {
        "email": "email",
        "phone": "phone",
        "telephone": "phone",
        "mobile": "phone",
        "address": "address",
        "name": "name",
        "username": "name",
        "user_name": "name",
        "nickname": "name",
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
        "state": "choice",
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
        "city": "sentence",
        "country": "sentence",
        "zip_code": "string",
        "postal_code": "string",
    }

    EXACT_MATCH_PARAMS: ClassVar[dict[str, dict[str, Any]]] = {
        "age": {"min_value": 18, "max_value": 100},
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
        "state": {"choices": [0, 1, 2]},
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

    PATTERN_MATCH_RULES: ClassVar[list[tuple[str, str, dict[str, Any]]]] = [
        (r"^id$", "autoincrement", {}),
        (r".*_id$", "foreign_key_or_integer", {}),
        (r".*_ids$", "json", {}),
        (r".*_at$", "datetime", {}),
        (r".*_date$", "date", {}),
        (r".*_time$", "datetime", {}),
        (r".*_timestamp$", "timestamp", {}),
        (r"^created$", "datetime", {}),
        (r"^updated$", "datetime", {}),
        (r"^deleted$", "datetime", {}),
        (r".*_count$|.*_num$|.*_number$", "integer", {"min_value": 0, "max_value": 10000}),
        (r".*_amount$|.*_price$|.*_cost$|.*_fee$", "float", {"min_value": 0.01, "max_value": 99999.99, "precision": 2}),
        (r".*_rate$|.*_ratio$|.*_percent$", "float", {"min_value": 0.0, "max_value": 1.0, "precision": 4}),
        (r"^is_.*|^has_.*|^can_.*|^should_.*|^enable.*|^disable.*", "boolean", {}),
        (r".*_code$", "string", {"min_length": 6, "max_length": 12, "charset": "alphanumeric"}),
        (r".*_name$", "name", {}),
        (r".*_email$", "email", {}),
        (r".*_phone$|.*_tel$|.*_mobile$", "phone", {}),
        (r".*_url$|.*_link$|.*_href$", "url", {}),
        (r".*_path$|.*_file$", "string", {"min_length": 10, "max_length": 100}),
        (r".*_key$|.*_token$|.*_hash$", "uuid", {}),
        (r".*_password$|.*_passwd$|.*_secret$", "password", {}),
        (r".*_address$", "address", {}),
        (r".*_description$|.*_desc$|.*_text$|.*_content$|.*_body$", "text", {"min_length": 50, "max_length": 300}),
        (r".*_title$|.*_subject$|.*_headline$", "sentence", {}),
    ]

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
        self._custom_exact_rules: dict[str, tuple[str, dict[str, Any]]] = {}
        self._custom_pattern_rules: list[tuple[str, str, dict[str, Any]]] = []

    def register_exact_rule(self, column_name: str, generator: str, params: dict[str, Any] | None = None) -> None:
        self._custom_exact_rules[column_name.lower()] = (generator, params or {})

    def register_pattern_rule(self, pattern: str, generator: str, params: dict[str, Any] | None = None) -> None:
        self._custom_pattern_rules.append((pattern, generator, params or {}))

    def map_column(self, column_info: ColumnInfo, user_config: Any = None) -> GeneratorSpec:
        column_name = column_info.name.lower()
        column_type = column_info.type.upper() if column_info.type else "TEXT"

        if column_info.is_primary_key and (
            column_info.is_autoincrement or "INTEGER" in column_type or "INT" in column_type
        ):
            return GeneratorSpec(generator_name="skip")

        if user_config and hasattr(user_config, "generator") and user_config.generator:
            provider_val = (
                user_config.provider.value if hasattr(user_config, "provider") and user_config.provider else None
            )
            return GeneratorSpec(
                generator_name=user_config.generator,
                params=user_config.params if hasattr(user_config, "params") else {},
                null_ratio=user_config.null_ratio if hasattr(user_config, "null_ratio") else 0.0,
                provider=provider_val,
            )

        if column_name in self._custom_exact_rules:
            gen, params = self._custom_exact_rules[column_name]
            return GeneratorSpec(generator_name=gen, params=params)

        if column_name in self.EXACT_MATCH_RULES:
            gen = self.EXACT_MATCH_RULES[column_name]
            params = self.EXACT_MATCH_PARAMS.get(column_name, {})
            return GeneratorSpec(generator_name=gen, params=params)

        for pattern, gen, params in self._custom_pattern_rules:
            if re.match(pattern, column_name):
                return GeneratorSpec(generator_name=gen, params=params)

        for pattern, gen, params in self.PATTERN_MATCH_RULES:
            if re.match(pattern, column_name):
                return GeneratorSpec(generator_name=gen, params=params)

        if column_info.default is not None or column_info.nullable:
            return GeneratorSpec(generator_name="skip")

        return self._type_faithful_fallback(column_type)

    def _type_faithful_fallback(self, column_type: str) -> GeneratorSpec:
        import re as _re

        length_match = _re.search(r"\((\d+)\)", column_type)
        max_length = int(length_match.group(1)) if length_match else None

        base_type = _re.sub(r"\(.*\)", "", column_type).strip()

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
    ) -> dict[str, GeneratorSpec]:
        user_configs = user_configs or {}
        result: dict[str, GeneratorSpec] = {}
        for col in columns:
            col_config = user_configs.get(col.name)
            result[col.name] = self.map_column(col, col_config)
        return result
