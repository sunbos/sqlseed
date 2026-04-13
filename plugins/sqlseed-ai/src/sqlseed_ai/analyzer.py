from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed_ai._client import get_openai_client
from sqlseed_ai.config import AIConfig

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert database test data engineer. You analyze SQLite table schemas and recommend data generation configurations for the sqlseed toolkit.

## sqlseed Configuration Syntax

### Source Column (generator-based):
```yaml
- name: column_name
  generator: generator_name
  params:
    key: value
  constraints:
    unique: true
```

### Derived Column (expression-based):
```yaml
- name: derived_column
  derive_from: source_column
  expression: "value[-8:]"
  constraints:
    unique: true
```

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
9. Respond with VALID YAML only, no markdown fences, no explanation

## Output Format
Return a YAML object with this structure:
```yaml
name: table_name
count: 1000
columns:
  - name: column_name
    generator: generator_name
    params:
      key: value
    constraints:
      unique: true
```"""


class SchemaAnalyzer:
    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config

    def analyze_table(
        self,
        table_name: str,
        columns: list[Any],
        indexes: list[dict[str, Any]],
        sample_data: list[dict[str, Any]],
        foreign_keys: list[Any],
        all_table_names: list[str],
    ) -> dict[str, Any] | None:
        if self._config is None:
            self._config = AIConfig.from_env()

        if not self._config.api_key:
            logger.warning("AI API key not configured, skipping analysis")
            return None

        context = self._build_context(
            table_name=table_name,
            columns=columns,
            indexes=indexes,
            sample_data=sample_data,
            foreign_keys=foreign_keys,
            all_table_names=all_table_names,
        )

        try:
            client = get_openai_client(self._config)
            response = client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
            )

            content = response.choices[0].message.content
            if content is None:
                return None

            return self._parse_yaml_response(content)

        except Exception as e:
            logger.warning("AI analysis failed", table_name=table_name, error=str(e))
            return None

    def _build_context(
        self,
        table_name: str,
        columns: list[Any],
        indexes: list[dict[str, Any]],
        sample_data: list[dict[str, Any]],
        foreign_keys: list[Any],
        all_table_names: list[str],
    ) -> str:
        lines: list[str] = []
        lines.append(f"# Table: {table_name}")
        lines.append("")

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

        if indexes:
            lines.append("")
            lines.append("## Indexes")
            for idx in indexes:
                unique_str = "UNIQUE " if idx.get("unique") else ""
                cols_str = ", ".join(idx.get("columns", []))
                lines.append(f"- {unique_str}INDEX ({cols_str})")

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

        lines.append("")
        lines.append("Please analyze this table schema and recommend a complete sqlseed YAML configuration for generating test data.")

        return "\n".join(lines)

    def _parse_yaml_response(self, content: str) -> dict[str, Any]:
        import yaml

        cleaned = content.strip()
        if cleaned.startswith("```yaml"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        result = yaml.safe_load(cleaned)
        if not isinstance(result, dict):
            return {}
        return result
