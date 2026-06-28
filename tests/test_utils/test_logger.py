"""Tests for ``sqlseed._utils.logger`` — structlog configuration and get_logger.

Covers the public ``configure_logging`` and ``get_logger`` functions, log level
filtering behavior, stderr output routing, and the module-level
auto-configuration driven by the ``SQLSEED_LOG_LEVEL`` environment variable.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import structlog

from sqlseed._utils import logger as logger_mod
from sqlseed._utils.logger import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _restore_logging() -> Generator[None, None, None]:
    """Restore a known logging configuration after each test.

    ``cache_logger_on_first_use=True`` means already-used loggers are not
    affected by subsequent ``configure_logging`` calls, so each test must use a
    unique logger name. This fixture just guarantees a sane baseline config
    (INFO) for any later test that does not explicitly configure.
    """
    yield
    configure_logging("INFO")


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    """Tests for the ``get_logger`` function."""

    def test_returns_non_none(self) -> None:
        """get_logger returns a non-None logger object."""
        log = get_logger("test_returns_non_none")
        assert log is not None

    def test_default_name_none(self) -> None:
        """get_logger() works with no name argument (None default)."""
        log = get_logger()
        assert log is not None

    def test_empty_string_name(self) -> None:
        """get_logger('') works with an empty string name."""
        log = get_logger("")
        assert log is not None

    def test_different_names_return_loggers(self) -> None:
        """get_logger returns loggers for different module names."""
        log1 = get_logger("module_a_unique")
        log2 = get_logger("module_b_unique")
        assert log1 is not None
        assert log2 is not None

    def test_logger_emits_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The returned logger can emit INFO records to stderr."""
        configure_logging("INFO")
        log = get_logger("test_logger_emits_info")
        log.info("an info message")
        captured = capsys.readouterr()
        assert "an info message" in captured.err

    def test_logger_emits_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The returned logger can emit WARNING records to stderr."""
        configure_logging("WARNING")
        log = get_logger("test_logger_emits_warning")
        log.warning("a warning message")
        captured = capsys.readouterr()
        assert "a warning message" in captured.err

    def test_logger_emits_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The returned logger can emit ERROR records to stderr."""
        configure_logging("ERROR")
        log = get_logger("test_logger_emits_error")
        log.error("an error message")
        captured = capsys.readouterr()
        assert "an error message" in captured.err

    def test_logger_supports_bind(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The returned logger supports structlog's bind() for context."""
        configure_logging("INFO")
        log = get_logger("test_logger_supports_bind").bind(request_id="abc-123")
        log.info("message with context")
        captured = capsys.readouterr()
        assert "message with context" in captured.err
        assert "abc-123" in captured.err


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Tests for the ``configure_logging`` function."""

    def test_default_level_is_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """configure_logging() with no args defaults to INFO level."""
        configure_logging()
        log = get_logger("test_default_level_is_info")
        log.info("info via default level")
        captured = capsys.readouterr()
        assert "info via default level" in captured.err

    def test_debug_level_emits_debug(self, capsys: pytest.CaptureFixture[str]) -> None:
        """DEBUG level emits debug messages."""
        configure_logging("DEBUG")
        log = get_logger("test_debug_level_emits_debug")
        log.debug("a debug message")
        captured = capsys.readouterr()
        assert "a debug message" in captured.err

    def test_info_level_emits_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """INFO level emits info messages."""
        configure_logging("INFO")
        log = get_logger("test_info_level_emits_info")
        log.info("an info message")
        captured = capsys.readouterr()
        assert "an info message" in captured.err

    def test_warning_level_filters_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """WARNING level filters out INFO messages."""
        configure_logging("WARNING")
        log = get_logger("test_warning_level_filters_info")
        log.info("this info should be filtered")
        captured = capsys.readouterr()
        assert "this info should be filtered" not in captured.err

    def test_warning_level_emits_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """WARNING level emits warning messages."""
        configure_logging("WARNING")
        log = get_logger("test_warning_level_emits_warning")
        log.warning("a warning message")
        captured = capsys.readouterr()
        assert "a warning message" in captured.err

    def test_error_level_filters_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ERROR level filters out WARNING messages."""
        configure_logging("ERROR")
        log = get_logger("test_error_level_filters_warning")
        log.warning("this warning should be filtered")
        captured = capsys.readouterr()
        assert "this warning should be filtered" not in captured.err

    def test_error_level_emits_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ERROR level emits error messages."""
        configure_logging("ERROR")
        log = get_logger("test_error_level_emits_error")
        log.error("an error message")
        captured = capsys.readouterr()
        assert "an error message" in captured.err

    def test_critical_level_emits_critical(self, capsys: pytest.CaptureFixture[str]) -> None:
        """CRITICAL level emits critical messages."""
        configure_logging("CRITICAL")
        log = get_logger("test_critical_level_emits_critical")
        log.critical("a critical message")
        captured = capsys.readouterr()
        assert "a critical message" in captured.err

    def test_critical_level_filters_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """CRITICAL level filters out ERROR messages."""
        configure_logging("CRITICAL")
        log = get_logger("test_critical_level_filters_error")
        log.error("this error should be filtered")
        captured = capsys.readouterr()
        assert "this error should be filtered" not in captured.err

    def test_invalid_level_falls_back_to_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An invalid level name falls back to INFO (via getattr default)."""
        configure_logging("NOT_A_REAL_LEVEL")
        log = get_logger("test_invalid_level_falls_back_to_info")
        log.info("info with invalid level name")
        captured = capsys.readouterr()
        assert "info with invalid level name" in captured.err

    def test_lowercase_level_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Lowercase level names are uppercased internally."""
        configure_logging("debug")
        log = get_logger("test_lowercase_level_name")
        log.debug("debug with lowercase level")
        captured = capsys.readouterr()
        assert "debug with lowercase level" in captured.err

    def test_mixed_case_level_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mixed-case level names are uppercased internally."""
        configure_logging("WaRnInG")
        log = get_logger("test_mixed_case_level_name")
        log.warning("warning with mixed case level")
        captured = capsys.readouterr()
        assert "warning with mixed case level" in captured.err

    def test_output_goes_to_stderr_not_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Log output is written to stderr, not stdout."""
        configure_logging("INFO")
        log = get_logger("test_output_goes_to_stderr_not_stdout")
        log.info("stderr routing message")
        captured = capsys.readouterr()
        assert "stderr routing message" in captured.err
        assert "stderr routing message" not in captured.out

    def test_reconfigure_changes_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Calling configure_logging again changes the active level for new loggers."""
        configure_logging("DEBUG")
        log_debug = get_logger("test_reconfigure_changes_level_debug")
        log_debug.debug("debug before reconfigure")
        captured_debug = capsys.readouterr()
        assert "debug before reconfigure" in captured_debug.err

        configure_logging("WARNING")
        log_warn = get_logger("test_reconfigure_changes_level_warn")
        log_warn.debug("debug after reconfigure should be filtered")
        log_warn.warning("warning after reconfigure should appear")
        captured_warn = capsys.readouterr()
        assert "debug after reconfigure should be filtered" not in captured_warn.err
        assert "warning after reconfigure should appear" in captured_warn.err


# ---------------------------------------------------------------------------
# Log level filtering (parametrized)
# ---------------------------------------------------------------------------


class TestLogLevelFiltering:
    """Parametrized tests covering the full level filtering matrix."""

    @pytest.mark.parametrize(
        ("level", "method", "should_appear"),
        [
            # DEBUG level: everything emits
            ("DEBUG", "debug", True),
            ("DEBUG", "info", True),
            ("DEBUG", "warning", True),
            ("DEBUG", "error", True),
            ("DEBUG", "critical", True),
            # INFO level: debug filtered
            ("INFO", "debug", False),
            ("INFO", "info", True),
            ("INFO", "warning", True),
            ("INFO", "error", True),
            ("INFO", "critical", True),
            # WARNING level: debug, info filtered
            ("WARNING", "debug", False),
            ("WARNING", "info", False),
            ("WARNING", "warning", True),
            ("WARNING", "error", True),
            ("WARNING", "critical", True),
            # ERROR level: debug, info, warning filtered
            ("ERROR", "debug", False),
            ("ERROR", "info", False),
            ("ERROR", "warning", False),
            ("ERROR", "error", True),
            ("ERROR", "critical", True),
            # CRITICAL level: only critical emits
            ("CRITICAL", "debug", False),
            ("CRITICAL", "info", False),
            ("CRITICAL", "warning", False),
            ("CRITICAL", "error", False),
            ("CRITICAL", "critical", True),
        ],
        ids=lambda x: str(x) if isinstance(x, bool) else x,
    )
    def test_level_filtering_matrix(
        self,
        level: str,
        method: str,
        should_appear: bool,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Each level filters log methods below it."""
        configure_logging(level)
        log = get_logger(f"test_filter_{level}_{method}")
        message = f"{level}-{method}-unique-message"
        getattr(log, method)(message)
        captured = capsys.readouterr()
        if should_appear:
            assert message in captured.err, f"{method} at {level} should appear in stderr"
        else:
            assert message not in captured.err, f"{method} at {level} should be filtered"


# ---------------------------------------------------------------------------
# Module auto-configuration (SQLSEED_LOG_LEVEL env var)
# ---------------------------------------------------------------------------


class TestModuleAutoConfiguration:
    """Tests for the module's auto-configuration on import via SQLSEED_LOG_LEVEL."""

    def test_module_exposes_configure_logging(self) -> None:
        """The logger module exposes configure_logging."""
        assert hasattr(logger_mod, "configure_logging")
        assert callable(logger_mod.configure_logging)

    def test_module_exposes_get_logger(self) -> None:
        """The logger module exposes get_logger."""
        assert hasattr(logger_mod, "get_logger")
        assert callable(logger_mod.get_logger)

    def test_default_env_level_is_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without SQLSEED_LOG_LEVEL, the default level is WARNING."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SQLSEED_LOG_LEVEL", None)
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_default_env_level_is_warning")
            log.info("this info should be filtered by default warning level")
            log.warning("this warning should appear by default")
            captured = capsys.readouterr()
            assert "this info should be filtered by default warning level" not in captured.err
            assert "this warning should appear by default" in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_debug_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SQLSEED_LOG_LEVEL=DEBUG sets the initial level to DEBUG."""
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "DEBUG"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_debug_level")
            log.debug("debug via env var")
            captured = capsys.readouterr()
            assert "debug via env var" in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_info_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SQLSEED_LOG_LEVEL=INFO sets the initial level to INFO."""
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "INFO"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_info_level")
            log.info("info via env var")
            log.debug("debug should be filtered by info env var")
            captured = capsys.readouterr()
            assert "info via env var" in captured.err
            assert "debug should be filtered by info env var" not in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_error_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SQLSEED_LOG_LEVEL=ERROR sets the initial level to ERROR."""
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "ERROR"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_error_level")
            log.warning("warning should be filtered by error env var")
            log.error("error via env var")
            captured = capsys.readouterr()
            assert "warning should be filtered by error env var" not in captured.err
            assert "error via env var" in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_lowercase_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SQLSEED_LOG_LEVEL is uppercased before resolution."""
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "debug"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_lowercase_value")
            log.debug("debug via lowercase env var")
            captured = capsys.readouterr()
            assert "debug via lowercase env var" in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_mixed_case_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SQLSEED_LOG_LEVEL with mixed case is uppercased before resolution."""
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "WaRnInG"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_mixed_case_value")
            log.warning("warning via mixed case env var")
            log.info("info should be filtered by mixed case warning")
            captured = capsys.readouterr()
            assert "warning via mixed case env var" in captured.err
            assert "info should be filtered by mixed case warning" not in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_invalid_falls_back_to_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An invalid SQLSEED_LOG_LEVEL falls back to INFO (via getattr default).

        The env var default is WARNING only when the variable is unset. When it
        is set to an invalid value, ``configure_logging`` resolves the level via
        ``getattr(logging, level.upper(), logging.INFO)``, which falls back to
        INFO — so INFO messages are emitted.
        """
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": "NOT_A_LEVEL"}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_invalid_falls_back_to_info")
            log.info("info should appear via info fallback")
            log.debug("debug should be filtered by info fallback")
            captured = capsys.readouterr()
            assert "info should appear via info fallback" in captured.err
            assert "debug should be filtered by info fallback" not in captured.err
        finally:
            configure_logging("INFO")

    def test_env_var_empty_string_falls_back_to_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An empty SQLSEED_LOG_LEVEL falls back to INFO (via getattr default).

        ``"".upper()`` is ``""``, and ``getattr(logging, "", logging.INFO)``
        returns the default ``logging.INFO``.
        """
        with patch.dict(os.environ, {"SQLSEED_LOG_LEVEL": ""}):
            importlib.reload(logger_mod)
        try:
            log = get_logger("test_env_var_empty_string_falls_back_to_info")
            log.info("info should appear via empty env fallback")
            log.debug("debug should be filtered by empty env fallback")
            captured = capsys.readouterr()
            assert "info should appear via empty env fallback" in captured.err
            assert "debug should be filtered by empty env fallback" not in captured.err
        finally:
            configure_logging("INFO")


# ---------------------------------------------------------------------------
# Output format / processor chain
# ---------------------------------------------------------------------------


class TestLoggerOutput:
    """Tests for the output format produced by the processor chain."""

    def test_output_contains_log_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The add_log_level processor adds the level name to the output."""
        configure_logging("INFO")
        log = get_logger("test_output_contains_log_level")
        log.info("level marker message")
        captured = capsys.readouterr()
        assert "level marker message" in captured.err
        # ConsoleRenderer formats the level as [info] or similar.
        assert "info" in captured.err.lower()

    def test_output_contains_iso_timestamp(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The TimeStamper processor adds an ISO-8601 timestamp to the output."""
        configure_logging("INFO")
        log = get_logger("test_output_contains_iso_timestamp")
        log.info("timestamped message")
        captured = capsys.readouterr()
        # ISO-8601 timestamp looks like 2026-06-23T12:34:56.789012
        assert "timestamped message" in captured.err
        # Check for a date-like pattern in the output.
        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        assert re.search(iso_pattern, captured.err), f"Expected ISO timestamp in output, got: {captured.err!r}"

    def test_output_includes_bound_context(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Bound context values appear in the rendered output."""
        configure_logging("INFO")
        log = get_logger("test_output_includes_bound_context").bind(user_id=42, action="login")
        log.info("contextual event")
        captured = capsys.readouterr()
        assert "contextual event" in captured.err
        assert "42" in captured.err
        assert "login" in captured.err

    def test_exception_info_rendered(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The set_exc_info processor includes exception info when exc_info=True."""
        configure_logging("INFO")
        log = get_logger("test_exception_info_rendered")
        try:
            raise ValueError("a test exception")
        except ValueError:
            log.error("error with exception", exc_info=True)
        captured = capsys.readouterr()
        assert "error with exception" in captured.err
        assert "ValueError" in captured.err
        assert "a test exception" in captured.err


# ---------------------------------------------------------------------------
# Structlog configuration sanity
# ---------------------------------------------------------------------------


class TestStructlogConfig:
    """Sanity checks on the structlog global configuration set by configure_logging."""

    def test_configure_does_not_raise(self) -> None:
        """configure_logging completes without raising for standard levels."""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            configure_logging(level)  # should not raise

    def test_configure_with_numeric_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        """configure_logging accepts numeric level names from the logging module."""
        configure_logging("INFO")
        log = get_logger("test_configure_with_numeric_level")
        log.info("numeric level test")
        captured = capsys.readouterr()
        assert "numeric level test" in captured.err

    def test_logging_levels_are_standard(self) -> None:
        """The standard logging module levels are accessible."""
        assert logging.DEBUG == 10
        assert logging.INFO == 20
        assert logging.WARNING == 30
        assert logging.ERROR == 40
        assert logging.CRITICAL == 50

    def test_structlog_get_logger_returns_proxy(self) -> None:
        """structlog.get_logger returns a usable logger proxy."""
        configure_logging("INFO")
        log = structlog.get_logger("test_structlog_get_logger_returns_proxy")
        assert log is not None
        # The proxy should have standard log methods.
        assert hasattr(log, "debug")
        assert hasattr(log, "info")
        assert hasattr(log, "warning")
        assert hasattr(log, "error")
        assert hasattr(log, "critical")
