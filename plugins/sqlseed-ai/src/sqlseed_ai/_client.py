from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


def get_openai_client(config: Any | None = None) -> Any:
    try:
        from openai import OpenAI

        api_key = None
        base_url = None
        if config is not None:
            api_key = config.api_key
            base_url = config.base_url

        return OpenAI(api_key=api_key, base_url=base_url)
    except ImportError:
        raise ImportError(
            "openai is not installed. Install it with: pip install sqlseed-ai"
        ) from None
