from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import sqlalchemy
import yaml

import sqlseed

if TYPE_CHECKING:
    import pytest


def assert_fk_integrity(db_path: str, fk_query: str, ref_query: str) -> None:
    conn = sqlite3.connect(db_path)
    fk_values = {r[0] for r in conn.execute(fk_query).fetchall() if r[0] is not None}
    ref_values = {r[0] for r in conn.execute(ref_query).fetchall()}
    conn.close()
    assert fk_values.issubset(ref_values)


def fill_from_config_and_verify_fk(
    db_path: str,
    config_data: dict[str, Any],
    config_dir: str,
    fk_query: str,
    ref_query: str,
) -> list[Any]:
    config_path = str(Path(config_dir) / "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    results = sqlseed.fill_from_config(config_path)
    assert_fk_integrity(db_path, fk_query, ref_query)
    return results


# ---------------------------------------------------------------------------
# LLM test helpers (shared across sqlseed-ai plugin tests)
# ---------------------------------------------------------------------------

# All LLM-related environment variables that influence ``AIConfig.from_env()``.
# Kept as a tuple so callers cannot mutate it accidentally.
_LLM_ENV_VARS: tuple[str, ...] = (
    "SQLSEED_AI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "SQLSEED_AI_BASE_URL",
    "OPENAI_BASE_URL",
    "SQLSEED_AI_MODEL",
    "SQLSEED_AI_BACKEND",
    "SQLSEED_AI_TIMEOUT",
)


def clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete every LLM-related env var so ``AIConfig.from_env()`` sees a clean slate.

    Use this at the start of tests that need to assert ``from_env()`` returns
    empty defaults, before re-setting only the specific vars the test cares about.
    """
    for var in _LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def configure_llm_backend_env(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    model: str,
) -> None:
    """Set backend-specific env vars + ``SQLSEED_AI_MODEL`` for the given backend.

    Mirrors the backend-conditional setup used by the real-LLM integration tests.
    For ``google_ai_studio`` the caller is expected to have ``GOOGLE_API_KEY``
    already set (typically via the ``available_llm_backend`` session fixture).

    Args:
        monkeypatch: pytest's ``MonkeyPatch`` fixture (auto-restored on teardown).
        backend: One of ``"ollama"``, ``"lm_studio"``, ``"google_ai_studio"``.
        model: The model id to set as ``SQLSEED_AI_MODEL``.
    """
    if backend == "ollama":
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
    elif backend == "lm_studio":
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
    elif backend == "google_ai_studio":
        # GOOGLE_API_KEY is provided by the available_llm_backend session fixture.
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "google_ai_studio")
    else:
        raise ValueError(f"Unsupported backend for configure_llm_backend_env: {backend!r}")

    monkeypatch.setenv("SQLSEED_AI_MODEL", model)


def ensure_pg_users_table(pg_url: str) -> None:
    """Create the ``users`` table on the given PostgreSQL URL if it does not exist.

    The schema matches what the real-LLM PG integration tests expect:
    ``id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT``. Idempotent so
    multiple tests can share the same session-scoped ``pg_url``.
    """
    engine = sqlalchemy.create_engine(pg_url)
    try:
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT)"
                )
            )
            conn.commit()
    finally:
        engine.dispose()


def make_streaming_chunk(content: str | None, reasoning: str | None = None) -> Any:
    """Build a mock OpenAI streaming chunk with the given delta content.

    Args:
        content: The ``delta.content`` value. Pass ``None`` for reasoning-only chunks.
        reasoning: The ``delta.reasoning_content`` value. Defaults to ``None`` for
            content-only chunks.

    Returns:
        A ``MagicMock`` shaped like an OpenAI ``ChatCompletionChunk`` with
        ``choices[0].delta.content`` and ``choices[0].delta.reasoning_content``
        attributes set.
    """
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.reasoning_content = reasoning
    return chunk


def make_reasoning_chunk(text: str) -> Any:
    """Build a mock streaming chunk that carries only reasoning content.

    Convenience wrapper around :func:`make_streaming_chunk` for the common
    case of a reasoning-only chunk (``content=None``).
    """
    return make_streaming_chunk(content=None, reasoning=text)


def make_empty_streaming_chunk() -> Any:
    """Build a mock streaming chunk with no choices (early-termination shape).

    Used to verify ``_collect_stream_chunks`` skips chunks with empty
    ``choices`` lists without raising.
    """
    chunk = MagicMock()
    chunk.choices = []
    return chunk


def create_simple_users_db(db_path: str) -> None:
    """Create a test DB with a single ``users`` table (id, name, email, age).

    Extracted to avoid CodeDuplication: the 7-line ``sqlite3.connect`` +
    ``CREATE TABLE users (...)`` + ``commit`` + ``close`` block was repeated
    verbatim in ``plugins/mcp-server-sqlseed/tests/test_server.py`` and
    ``plugins/sqlseed-ai/tests/test_mcp.py``. The schema is intentionally
    minimal so it can be reused by both MCP server test suites.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, age INTEGER)"
    )
    conn.commit()
    conn.close()
