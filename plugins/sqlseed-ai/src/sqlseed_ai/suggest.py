from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed_ai._client import get_openai_client
from sqlseed_ai.config import AIConfig

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
            model = AIConfig.model_fields["model"].default
            if self._config is not None and hasattr(self._config, "model"):
                model = self._config.model

            prompt = (
                f"Given a SQLite table '{table_name}' with columns {all_column_names}, "
                f"the column '{column_name}' has type '{column_type}'. "
                f"Suggest the best data generator name and params for this column. "
                f"Available generators: string, integer, float, boolean, bytes, "
                f"name, first_name, last_name, email, phone, address, company, "
                f"url, ipv4, uuid, date, datetime, timestamp, text, sentence, "
                f"password, choice, json, foreign_key, pattern. "
                f'Respond in JSON format: {{"generator": "...", "params": {{}}}}'
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content if response.choices else None
            if content is None:
                return None

            from sqlseed_ai._json_utils import parse_json_response

            result = parse_json_response(content)
            if "generator" in result:
                return result

        except Exception as e:
            logger.warning("AI suggestion failed", column_name=column_name, error=e)

        return None
