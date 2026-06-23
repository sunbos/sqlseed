"""Tests for the AISqlseedPlugin class in sqlseed_ai.__init__.

Covers plugin instantiation, lazy analyzer construction, the simple-column
heuristic, and the two sqlseed hook implementations
(``sqlseed_ai_analyze_table`` and ``sqlseed_pre_generate_templates``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

try:
    from sqlseed_ai import AISqlseedPlugin
    from sqlseed_ai.config import AIConfig
except ImportError:
    pytest.skip("sqlseed-ai not installed", allow_module_level=True)


class TestAISqlseedPluginInstantiation:
    def test_plugin_instance_creation(self) -> None:
        """Verify AISqlseedPlugin() creates an instance with no analyzer yet."""
        plugin = AISqlseedPlugin()
        assert plugin is not None
        assert plugin._analyzer is None


class TestGetAnalyzer:
    def test_get_analyzer_lazy_init(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify _get_analyzer() lazily constructs a SchemaAnalyzer.

        Mocks AIConfig.from_env so no real environment/HTTP work happens.
        """
        plugin = AISqlseedPlugin()
        assert plugin._analyzer is None

        mock_config = AIConfig(api_key="test-key", model="test-model")
        monkeypatch.setattr(AIConfig, "from_env", lambda *args, **kwargs: mock_config)

        analyzer = plugin._get_analyzer()
        assert analyzer is not None
        assert plugin._analyzer is analyzer

    def test_get_analyzer_caches_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify _get_analyzer() returns the same instance on second call."""
        plugin = AISqlseedPlugin()

        mock_config = AIConfig(api_key="test-key", model="test-model")
        monkeypatch.setattr(AIConfig, "from_env", lambda *args, **kwargs: mock_config)

        first = plugin._get_analyzer()
        second = plugin._get_analyzer()
        assert first is second


class TestIsSimpleColumn:
    def test_is_simple_column_matches_basic_types(self) -> None:
        """Verify _is_simple_column() returns True for id, name, email, created_at."""
        plugin = AISqlseedPlugin()
        assert plugin._is_simple_column("id", "INTEGER") is True
        assert plugin._is_simple_column("name", "TEXT") is True
        assert plugin._is_simple_column("email", "TEXT") is True
        # "created_at" matches via the TIMESTAMP column type
        assert plugin._is_simple_column("created_at", "TIMESTAMP") is True

    def test_is_simple_column_skips_complex_types(self) -> None:
        """Verify _is_simple_column() returns False for json_data, array_field."""
        plugin = AISqlseedPlugin()
        assert plugin._is_simple_column("json_data", "JSON") is False
        assert plugin._is_simple_column("array_field", "ARRAY") is False


class TestAnalyzeTableHook:
    def test_analyze_table_hook_returns_none_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify sqlseed_ai_analyze_table returns None when no API key is set.

        The analyzer's analyze_table_from_ctx short-circuits to None when the
        config has no API key, so the hook should propagate that None.
        """
        plugin = AISqlseedPlugin()
        mock_config = AIConfig(api_key=None, model="test-model")
        monkeypatch.setattr(AIConfig, "from_env", lambda *args, **kwargs: mock_config)

        result = plugin.sqlseed_ai_analyze_table(
            table_name="users",
            columns=[],
            indexes=[],
            sample_data=[],
            foreign_keys=[],
            all_table_names=["users"],
        )
        assert result is None

    def test_analyze_table_hook_calls_analyzer(self) -> None:
        """Verify sqlseed_ai_analyze_table delegates to analyzer.analyze_table_from_ctx."""
        plugin = AISqlseedPlugin()
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_table_from_ctx.return_value = {"name": "users", "columns": []}
        plugin._analyzer = mock_analyzer

        kwargs: dict[str, Any] = {
            "table_name": "users",
            "columns": [],
            "indexes": [],
            "sample_data": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
        }
        result = plugin.sqlseed_ai_analyze_table(**kwargs)

        mock_analyzer.analyze_table_from_ctx.assert_called_once_with(**kwargs)
        assert result == {"name": "users", "columns": []}


class TestPreGenerateTemplatesHook:
    def test_pre_generate_templates_hook_returns_none_on_error(self) -> None:
        """Verify sqlseed_pre_generate_templates returns None on exception.

        Uses a non-simple column so the hook reaches the analyzer, then the
        analyzer raises ValueError which the hook swallows and returns None.
        """
        plugin = AISqlseedPlugin()
        mock_analyzer = MagicMock()
        mock_analyzer.generate_template_values.side_effect = ValueError("boom")
        plugin._analyzer = mock_analyzer

        # "json_data" is not a simple column, so the hook will call the analyzer
        result = plugin.sqlseed_pre_generate_templates(
            table_name="users",
            column_name="json_data",
            column_type="JSON",
            count=10,
            sample_data=[],
        )
        assert result is None
        mock_analyzer.generate_template_values.assert_called_once()
