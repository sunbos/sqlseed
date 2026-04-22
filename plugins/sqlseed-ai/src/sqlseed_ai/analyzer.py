from __future__ import annotations

from typing import Any

from openai import APIError
from sqlseed_ai._client import get_openai_client
from sqlseed_ai._json_utils import parse_json_response
from sqlseed_ai.config import AIConfig
from sqlseed_ai.examples import FEW_SHOT_EXAMPLES

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert database test data engineer.
You analyze SQLite table schemas and recommend data generation configurations for the sqlseed toolkit.

## Available Generators
- string (params: min_length, max_length, charset)
- integer (params: min_value, max_value)
- float (params: min_value, max_value, precision)
- boolean
- bytes (params: length)
- name, first_name, last_name
- email, phone, address, company
- url, ipv4, uuid
- date (params: start_year, end_year)
- datetime (params: start_year, end_year)
- timestamp
- text (params: min_length, max_length)
- sentence, password
- choice (params: choices)
- json (params: schema)
- pattern (params: regex) — generates strings matching a regex pattern

## Key Rules
1. INTEGER PRIMARY KEY AUTOINCREMENT columns → do NOT include (auto-skip)
2. Columns with DEFAULT values → do NOT include (auto-skip)
3. Nullable columns → do NOT include unless they have semantic meaning
4. Use `pattern` generator with regex for card numbers, codes, IDs with specific formats
5. Use `derive_from` + `expression` when one column is computed from another
6. Use `constraints.unique: true` for columns that must be unique
7. Detect cross-column dependencies: if last_eight = last 8 chars of card_number, use derive_from
8. Detect implicit business associations: if account_id appears in multiple tables, note it

## Output Format
You MUST respond with a valid JSON object (NOT YAML, NOT markdown fences).
The JSON object must have this exact structure:
{
  "name": "table_name",
  "count": 1000,
  "columns": [
    {
      "name": "column_name",
      "generator": "generator_name",
      "params": {"key": "value"}
    },
    {
      "name": "derived_column",
      "derive_from": "source_column",
      "expression": "value[-8:]",
      "constraints": {"unique": true}
    }
  ]
}

IMPORTANT: Do NOT include columns that are PRIMARY KEY AUTOINCREMENT or have DEFAULT values."""


class SchemaAnalyzer:
    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config

    def analyze_table_from_ctx(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self._config is None:
            self._config = AIConfig.from_env()

        if not self._config.api_key:
            logger.warning("AI API key not configured, skipping analysis")
            return None

        messages = self.build_initial_messages(kwargs)

        try:
            return self.call_llm(messages)
        except (ValueError, RuntimeError) as e:
            logger.warning("AI analysis failed", table_name=kwargs.get("table_name", ""), error=str(e))
            return None

    def build_initial_messages(
        self,
        schema_ctx: dict[str, Any],
    ) -> list[dict[str, str]]:
        context = self._build_context(schema_ctx)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})

        messages.append({"role": "user", "content": context})

        return messages

    def call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self._config is None:
            self._config = AIConfig.from_env()
        if not self._config.api_key:
            raise ValueError("AI API key not configured")

        client = get_openai_client(self._config)
        _openai_exceptions = (APIError, ValueError, RuntimeError, OSError)

        try:
            response = client.chat.completions.create(
                model=self._config.model,
                messages=messages,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                response_format={"type": "json_object"},
            )
        except _openai_exceptions as e:
            raise RuntimeError(f"LLM API call failed (model={self._config.model}): {e}") from e

        if not response.choices:
            raise RuntimeError(
                f"LLM returned no choices (model={self._config.model}). The API key or model may be invalid."
            )
        content = response.choices[0].message.content
        if content is None:
            return {}
        return self._parse_json_response(content)

    TEMPLATE_SYSTEM_PROMPT = (
        "You are a data generation assistant. Generate realistic sample values "
        "for the given database column. Return a JSON object with a 'values' "
        "array containing the requested number of unique, realistic values. "
        "Each value must be valid for the column type. Do NOT include explanations."
    )

    def generate_template_values(
        self,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
        table_name: str = "",
    ) -> list[Any]:
        prompt = (
            f"Generate {count} realistic sample values for a database column "
            f"named '{column_name}' with type '{column_type}'"
        )
        if table_name:
            prompt += f" in table '{table_name}'"
        prompt += "."
        if sample_data:
            prompt += f"\nExisting sample values: {sample_data[:5]}"
        prompt += (
            f'\nRespond with a JSON object: {{"values": [...]}}.\nEach value should be a valid {column_type} value.'
        )

        messages = [
            {"role": "system", "content": self.TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = self.call_llm(messages)
        values = result.get("values", [])
        return values if isinstance(values, list) else []

    def _build_context(
        self,
        schema_ctx: dict[str, Any],
    ) -> str:
        table_name = schema_ctx.get("table_name", "unknown")
        columns = schema_ctx.get("columns", [])
        indexes = schema_ctx.get("indexes", [])
        foreign_keys = schema_ctx.get("foreign_keys", [])
        all_table_names = schema_ctx.get("all_table_names", [])
        sample_data = schema_ctx.get("sample_data", [])
        distribution_profiles = schema_ctx.get("distribution")

        lines: list[str] = []
        lines.append(f"# Table: {table_name}")
        lines.append("")

        self._append_columns_info(lines, columns)

        if indexes:
            self._append_indexes_info(lines, indexes)

        if foreign_keys:
            lines.append("")
            lines.append("## Foreign Keys")
            for fk in foreign_keys:
                lines.append(f"- {fk.column} → {fk.ref_table}.{fk.ref_column}")

        if all_table_names:
            lines.append("")
            lines.append("## All Tables in Database")
            lines.append(", ".join(all_table_names))

        if sample_data:
            lines.append("")
            lines.append("## Sample Data (existing rows)")
            for i, row in enumerate(sample_data[:5]):
                row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                lines.append(f"  Row {i + 1}: {row_str}")

        if distribution_profiles:
            self._append_distribution_info(lines, distribution_profiles)

        lines.append("")
        lines.append(
            "Please analyze this table schema and recommend "
            "a complete sqlseed JSON configuration for generating test data."
        )

        return "\n".join(lines)

    def _append_columns_info(
        self,
        lines: list[str],
        columns: list[Any],
    ) -> None:
        lines.append("## Columns")
        for col in columns:
            parts = [f"- {col.name}: {col.type}"]
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if col.is_autoincrement:
                parts.append("AUTOINCREMENT")
            if col.nullable:
                parts.append("NULLABLE")
            if col.default is not None:
                parts.append(f"DEFAULT={col.default}")
            if not col.nullable and col.default is None and not col.is_primary_key:
                parts.append("NOT NULL")
            lines.append(" ".join(parts))

    def _append_indexes_info(
        self,
        lines: list[str],
        indexes: list[dict[str, Any]],
    ) -> None:
        lines.append("")
        lines.append("## Indexes")
        for idx in indexes:
            unique_str = "UNIQUE " if idx.get("unique") else ""
            cols_str = ", ".join(idx.get("columns", []))
            lines.append(f"- {unique_str}INDEX ({cols_str})")

    def _append_distribution_info(
        self,
        lines: list[str],
        distribution_profiles: list[dict[str, Any]],
    ) -> None:
        lines.append("")
        lines.append("## Column Distribution (from existing data)")
        for profile in distribution_profiles:
            col = profile["column"]
            distinct = profile.get("distinct_count", "?")
            null_ratio = profile.get("null_ratio", 0)
            lines.append(f"- {col}: {distinct} distinct values, {null_ratio:.1%} null")
            top_values = profile.get("top_values", [])
            if top_values:
                top_str = ", ".join(f"{tv['value']}({tv['frequency']:.0%})" for tv in top_values[:3])
                lines.append(f"  Top values: {top_str}")
            vr = profile.get("value_range")
            if vr:
                lines.append(f"  Range: [{vr['min']}, {vr['max']}]")

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        return parse_json_response(content)
