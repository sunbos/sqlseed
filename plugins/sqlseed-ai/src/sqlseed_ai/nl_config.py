from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed_ai._client import get_openai_client

logger = get_logger(__name__)


class NLConfigGenerator:

    def __init__(self, config: Any | None = None) -> None:
        self._config = config

    def generate(self, description: str, db_path: str | None = None) -> dict[str, Any]:
        try:
            client = get_openai_client(self._config)
            model = "gpt-4o-mini"
            if self._config is not None:
                model = self._config.model

            schema_info = ""
            if db_path:
                schema_info = self._read_schema(db_path)

            prompt = (
                f"Generate a sqlseed YAML configuration based on this description:\n"
                f'"{description}"\n\n'
            )
            if schema_info:
                prompt += f"Database schema:\n{schema_info}\n\n"

            prompt += (
                "The YAML should follow this structure:\n"
                "db_path: path to database\n"
                "provider: mimesis|faker\n"
                "locale: en_US\n"
                "tables:\n"
                "  - name: table_name\n"
                "    count: number_of_rows\n"
                "    columns:\n"
                "      - name: column_name\n"
                "        generator: generator_name\n"
                "        params: {}\n\n"
                "Respond with valid YAML only."
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                temperature=0.5,
            )

            content = response.choices[0].message.content
            if content is None:
                return {}

            import yaml

            result = yaml.safe_load(content)
            return result if isinstance(result, dict) else {}

        except Exception as e:
            logger.warning("NL config generation failed", error=e)
            return {}

    def _read_schema(self, db_path: str) -> str:
        try:
            from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

            adapter = RawSQLiteAdapter()
            adapter.connect(db_path)
            tables = adapter.get_table_names()
            lines: list[str] = []
            for table in tables:
                columns = adapter.get_column_info(table)
                col_desc = ", ".join(
                    f"{c.name}({c.type})" for c in columns
                )
                lines.append(f"  {table}: {col_desc}")
            adapter.close()
            return "\n".join(lines)
        except Exception:
            return ""
