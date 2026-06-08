from __future__ import annotations

import json
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError
from sqlseed_ai._client import get_openai_client
from sqlseed_ai._json_utils import parse_json_response
from sqlseed_ai._model_selector import select_next_gemma_model
from sqlseed_ai.config import AIBackend, AIConfig
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
- username — realistic usernames like "jsmith42", "john.doe", "john_smith"
- email, phone, address, company
- city, country, state, zip_code, country_code — real geographic data
- job_title — real job titles like "Software Engineer"
- url, ipv4, uuid
- date (params: start_year, end_year)
- datetime (params: start_year, end_year)
- timestamp
- text (params: min_length, max_length)
- sentence, password
- choice (params: choices)
- json (params: schema)
- pattern (params: regex) — generates strings matching a regex pattern

## Native Method Selection
For columns that would default to "string" type, you can also recommend
native Faker/Mimesis methods:
- faker_method: A Faker method name
  (e.g., "license_plate", "color_name", "iban", "credit_card_number")
- mimesis_method: A Mimesis method path
  (e.g., "transport.vehicle_registration_code", "text.color",
  "hardware.cpu", "payment.credit_card_number")
- native_params: Parameters for the native method if needed

Only recommend methods you are confident exist. When uncertain, omit these
fields and the system will fall back to the generator type.

## Key Rules
1. INTEGER PRIMARY KEY AUTOINCREMENT columns → do NOT include (auto-skip)
2. Columns with DEFAULT values → do NOT include (auto-skip)
3. Nullable columns → do NOT include unless they have semantic meaning
4. Prefer specific generators over generic "string":
   use username, city, country, state, zip_code, job_title,
   country_code when column names match
5. For "age" columns, use min_value: 18, max_value: 65 (working age range)
6. Use `pattern` generator with regex for codes, IDs, serial numbers with specific formats
7. Use `derive_from` + `expression` when one column is computed from another
8. Use `constraints.unique: true` for columns that must be unique
9. Detect cross-column dependencies: if short_code = last 6 chars of project_no, use derive_from
10. Detect implicit business associations: if member_no appears in multiple tables, note it

## Output Format
You MUST respond with ONLY a valid JSON object (NOT YAML, NOT markdown fences, no explanations before or after).
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
      "name": "license_plate",
      "generator": "string",
      "params": {"min_length": 5, "max_length": 10},
      "faker_method": "license_plate",
      "mimesis_method": "transport.vehicle_registration_code"
    },
    {
      "name": "derived_column",
      "derive_from": "source_column",
      "expression": "value[-8:]",
      "constraints": {"unique": true}
    }
  ]
}

IMPORTANT: Do NOT include columns that are PRIMARY KEY AUTOINCREMENT or have DEFAULT values.
IMPORTANT: Output ONLY the JSON object, nothing else."""

_MAX_FALLBACK_ATTEMPTS = 3

# ── Gemma 4 Native Function Calling Tool Definitions ─────────────────
# These tools leverage Gemma 4's native function calling capability,
# allowing the model to invoke sqlseed operations directly.

GEMMA_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_schema",
            "description": (
                "Analyze a database table schema and recommend data generation configuration. "
                "Use this tool to examine table structure, column types, constraints, and foreign keys, "
                "then produce a complete sqlseed JSON configuration for generating realistic test data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table to analyze",
                    },
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Column name"},
                                "type": {"type": "string", "description": "Column SQL type"},
                                "is_primary_key": {"type": "boolean", "description": "Whether column is primary key"},
                                "is_autoincrement": {
                                    "type": "boolean",
                                    "description": "Whether column auto-increments",
                                },
                                "nullable": {"type": "boolean", "description": "Whether column is nullable"},
                                "default": {"type": "string", "description": "Default value if any"},
                            },
                            "required": ["name", "type"],
                        },
                        "description": "List of column definitions in the table",
                    },
                    "foreign_keys": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "ref_table": {"type": "string"},
                                "ref_column": {"type": "string"},
                            },
                        },
                        "description": "Foreign key relationships",
                    },
                    "indexes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "columns": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "unique": {"type": "boolean"},
                            },
                        },
                        "description": "Table indexes",
                    },
                },
                "required": ["table_name", "columns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_column_values",
            "description": (
                "Generate realistic sample values for a specific database column. "
                "Use this tool when you need to produce template values for columns "
                "that require custom or domain-specific data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "column_name": {
                        "type": "string",
                        "description": "Name of the column",
                    },
                    "column_type": {
                        "type": "string",
                        "description": "SQL type of the column",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of values to generate",
                    },
                    "table_name": {
                        "type": "string",
                        "description": "Table name for context",
                    },
                    "sample_data": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Existing sample values for reference",
                    },
                },
                "required": ["column_name", "column_type", "count"],
            },
        },
    },
]


class SchemaAnalyzer:
    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config
        if self._config is not None:
            self._config.resolve_model()

    def analyze_table_from_ctx(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self._config is None:
            self._config = AIConfig.from_env()

        self._config.resolve_model()

        if not self._config.resolve_api_key():
            logger.warning(
                "AI API key not configured. "
                "Set GOOGLE_API_KEY, SQLSEED_AI_API_KEY, or OPENAI_API_KEY environment variable. "
                "For Ollama, set SQLSEED_AI_BACKEND=ollama."
            )
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

        # Use fewer examples for local models (4B) to reduce inference time
        max_examples = len(FEW_SHOT_EXAMPLES)
        if self._config and self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            max_examples = 1  # Only 1 example for local inference speed

        for example in FEW_SHOT_EXAMPLES[:max_examples]:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})

        messages.append({"role": "user", "content": context})

        return messages

    def call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self._config is None:
            self._config = AIConfig.from_env()
        self._config.resolve_model()
        if not self._config.resolve_api_key():
            raise ValueError("AI API key not configured")

        for attempt in range(_MAX_FALLBACK_ATTEMPTS):
            try:
                return self._call_llm_once(messages)
            except (APITimeoutError, APIConnectionError) as e:
                current_model = self._config.model
                logger.warning(
                    "LLM API call timed out or connection failed",
                    model=current_model,
                    error=str(e)[:200],
                    attempt=attempt + 1,
                )

                next_model = select_next_gemma_model(current_model or "")
                if next_model is None:
                    raise RuntimeError(
                        f"LLM API call failed after trying {attempt + 1} model(s). "
                        f"Last error (model={current_model}): {e}"
                    ) from e

                logger.warning(
                    "Falling back to next Gemma 4 model",
                    from_model=current_model,
                    to_model=next_model,
                )
                self._config.model = next_model

        raise RuntimeError(f"LLM API call failed after {_MAX_FALLBACK_ATTEMPTS} fallback attempts")

    def _call_llm_once(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        assert self._config is not None, "AIConfig must be initialized before calling LLM"
        client = get_openai_client(self._config)
        _openai_exceptions = (APIError, ValueError, RuntimeError, OSError)

        try:
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "max_tokens": self._config.max_tokens,
                "temperature": self._config.temperature,
            }

            # Try Gemma 4 native function calling first
            # Only for cloud backends (Google AI Studio) that support tools parameter.
            # Local backends (LM Studio, Ollama) may not support it and would waste time.
            if self._config.backend == AIBackend.GOOGLE_AI_STUDIO:
                result = self._try_tool_calling(client, kwargs)
                if result is not None:
                    return result

            # Fallback: try JSON mode
            try:
                kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**kwargs)
            except (APIError, ValueError, RuntimeError) as fmt_err:
                err_msg = str(fmt_err).lower()
                if "json" in err_msg or "response_format" in err_msg or "400" in err_msg:
                    logger.debug("JSON mode not supported, falling back to text mode", model=self._config.model)
                    del kwargs["response_format"]
                    response = client.chat.completions.create(**kwargs)
                else:
                    raise
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

    def _extract_tool_call_result(self, choice: Any) -> dict[str, Any] | None:
        """Extract the analyze_schema result from a tool call choice."""
        if not choice.message.tool_calls:
            return None
        for tool_call in choice.message.tool_calls:
            if tool_call.function.name == "analyze_schema":
                args_str = tool_call.function.arguments
                if args_str:
                    try:
                        result: dict[str, Any] | None = json.loads(args_str)
                        logger.info(
                            "Gemma 4 native function calling succeeded",
                            tool="analyze_schema",
                            model=self._config.model if self._config else "unknown",
                        )
                        return result
                    except json.JSONDecodeError:
                        logger.debug("Failed to parse tool call arguments", args=args_str[:200])
        return None

    def _try_tool_calling(self, client: Any, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        """Attempt Gemma 4 native function calling.

        If the model supports tool use, it will invoke the `analyze_schema`
        function with structured parameters. We then extract the result
        from the tool call response.

        Returns None if tool calling is not available or fails, so we can
        fall back to JSON mode.
        """
        try:
            tool_kwargs = {**kwargs, "tools": GEMMA_TOOLS, "tool_choice": "auto"}
            # Remove response_format if present (incompatible with tools)
            tool_kwargs.pop("response_format", None)

            response = client.chat.completions.create(**tool_kwargs)

            if not response.choices:
                return None

            choice = response.choices[0]

            result = self._extract_tool_call_result(choice)
            if result is not None:
                return result

            # If no tool call was made but we have text content, parse it
            if choice.message.content:
                return self._parse_json_response(choice.message.content)

            return None

        except (APIError, ValueError, RuntimeError) as e:
            err_msg = str(e).lower()
            if "tool" in err_msg or "function" in err_msg or "400" in err_msg:
                logger.debug(
                    "Gemma 4 tool calling not supported by this endpoint, falling back to JSON mode",
                    model=self._config.model if self._config else "unknown",
                )
                return None
            raise

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
