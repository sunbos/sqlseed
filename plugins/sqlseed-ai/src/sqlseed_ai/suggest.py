from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed_ai._client import get_openai_client

logger = get_logger(__name__)


class ColumnSuggester:

    def __init__(self, config: Any | None = None) -> None:
        self._config = config

    def suggest(
        self,
        column_name: str,
        column_type: str,
        table_name: str,
        all_column_names: list[str],
    ) -> dict[str, Any] | None:
        try:
            client = get_openai_client(self._config)
            model = "gpt-4o-mini"
            if self._config is not None:
                model = self._config.model

            prompt = (
                f"Given a SQLite table '{table_name}' with columns {all_column_names}, "
                f"the column '{column_name}' has type '{column_type}'. "
                f"Suggest the best data generator name and params for this column. "
                f"Available generators: string, integer, float, boolean, bytes, "
                f"name, first_name, last_name, email, phone, address, company, "
                f"url, ipv4, uuid, date, datetime, timestamp, text, sentence, "
                f"password, choice, json, foreign_key. "
                f'Respond in JSON format: {{"generator": "...", "params": {{}}}}'
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.3,
            )

            content = response.choices[0].message.content
            if content is None:
                return None

            import json

            result = json.loads(content)
            if isinstance(result, dict) and "generator" in result:
                return result

        except Exception as e:
            logger.warning("AI suggestion failed", column_name=column_name, error=e)

        return None
