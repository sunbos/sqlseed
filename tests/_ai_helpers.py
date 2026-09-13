"""Shared test helpers for sqlseed-ai plugin tests.

This module imports ``sqlseed_ai`` at the top level. It is only imported by
test files inside their ``try/except ImportError`` blocks, so an ImportError
from a missing sqlseed-ai plugin is caught by the caller's skip logic.

Extracted to eliminate duplicate-code between
``test_ai_analyzer_streaming.py::TestFindLocalFallbackModel`` and
``test_ai_caller.py::TestFindLocalFallbackModelWalksChain``: the
config+analyzer+patch setup block was repeated across 6 tests in the two
modules.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIBackend, AIConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _lm_studio_analyzer_with_models(loaded_models: list[str]) -> Iterator[SchemaAnalyzer]:
    """Build an LM Studio SchemaAnalyzer with detect_all_local_models patched.

    Constructs the standard test config (LM Studio backend, 26B-a4b model) and
    patches ``AIConfig.detect_all_local_models`` to return the supplied list,
    yielding a ready-to-use analyzer inside the patch context.

    Args:
        loaded_models: Return value for the ``detect_all_local_models`` patch.

    Yields:
        The configured SchemaAnalyzer instance.
    """
    config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
    analyzer = SchemaAnalyzer(config=config)
    with patch.object(AIConfig, "detect_all_local_models", return_value=loaded_models):
        yield analyzer
