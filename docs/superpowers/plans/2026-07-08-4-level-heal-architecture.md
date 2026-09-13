# 4-Level Heal Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `sqlseed-ai` LLM heal architecture from 2-level (subgraph→degrader) to 4-level (subgraph→column→compact→degrader) with failure-type-aware routing.

**Architecture:** Delete `Layer4Coordinator` + `LLMHealer`; replace with `HealOrchestrator` coordinating 3 independent healers (`Level1SubgraphHealer`, `Level2ColumnHealer`, `Level3CompactHealer`) + `FailureClassifier` + `ContextWindowDetector`. `ProgressiveDegrader`, `SubgraphSplitter`, `OscillationDetector`, `DiffLearner` remain unchanged.

**Tech Stack:** Python 3.10+, openai SDK (LLM client), pytest, structlog, pydantic (AIConfig).

**Spec:** [docs/superpowers/specs/2026-07-08-4-level-heal-architecture-design.md](../specs/2026-07-08-4-level-heal-architecture-design.md)

**Branch:** `feat/contract-driven-self-healing` (backup checkpoint `87750f5` is the rollback point)

---

## File Structure

### New files (create)
| File | Responsibility |
|------|---------------|
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/_client.py` | Shared `LLMClient` protocol + `_OpenAICompatAdapter` (moved out of `llm_healer.py`) |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/context_detector.py` | `ContextWindowDetector` — dynamic model context window detection |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/failure_classifier.py` | `FailureClassifier` + `FailureType` enum — classify LLM failures |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py` | `Level1SubgraphHealer` — subgraph-level LLM call (refactored from `LLMHealer`) |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py` | `Level2ColumnHealer` — column-level LLM call with minimal dependency set |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py` | `Level3CompactHealer` — compact/ultra-compact prompt + JSON repair |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py` | `HealOrchestrator` — coordinates 4-level degradation with failure-type routing |
| `plugins/sqlseed-ai/tests/healer/test_context_detector.py` | Pure-logic tests for `ContextWindowDetector` |
| `plugins/sqlseed-ai/tests/healer/test_failure_classifier.py` | Pure-logic tests for `FailureClassifier` |
| `plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py` | Pure-logic tests for `Level2ColumnHealer._build_column_context()` |

### Modified files
| File | Change |
|------|--------|
| `plugins/sqlseed-ai/src/sqlseed_ai/config.py` | Add `max_context_tokens: int \| None = None` field to `AIConfig` |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/models.py` | Extend with `FailureType`, `HealAttempt`, `Level1Result`, `Level2Result`, `Level3Result`, `ColumnContext`, `FKInfo`; extend `HealResult` with `success`, `level_used`, `failure_type`, `attempts` |
| `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` | `_heal_subgraph()` calls `HealOrchestrator.heal()` instead of `Layer4Coordinator.reconcile()`; `__init__` takes `heal_orchestrator` instead of `healer` |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | Construct `HealOrchestrator` (with all sub-components) instead of `LLMHealer`; update `_OpenAICompatAdapter` import path |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/__init__.py` | Export new public components |
| `CLAUDE.md` | Update v4 Layer 4 description to 4-level architecture |
| `plugins/sqlseed-ai/README.md` | Update heal architecture description |

### Deleted files
| File | Reason |
|------|--------|
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py` | Split into `Level1SubgraphHealer` + `Level3CompactHealer`; `_OpenAICompatAdapter` moved to `_client.py` |
| `plugins/sqlseed-ai/src/sqlseed_ai/healer/coordinator.py` | Replaced by `HealOrchestrator` |
| `plugins/sqlseed-ai/tests/test_healer_llm_healer.py` | Component deleted; used mocks (self-proving trap) |
| `plugins/sqlseed-ai/tests/test_healer_coordinator.py` | Component deleted; used mocks (self-proving trap) |

---

## Task 1: Add `max_context_tokens` field to `AIConfig`

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/config.py` (in `class AIConfig`, after `timeout` field ~line 176)
- Test: `plugins/sqlseed-ai/tests/test_ai_config.py`

- [ ] **Step 1: Write the failing test**

Add to `plugins/sqlseed-ai/tests/test_ai_config.py`:

```python
def test_max_context_tokens_default_none():
    """max_context_tokens defaults to None (auto-detect)."""
    cfg = AIConfig()
    assert cfg.max_context_tokens is None


def test_max_context_tokens_explicit():
    """max_context_tokens can be set explicitly."""
    cfg = AIConfig(max_context_tokens=8192)
    assert cfg.max_context_tokens == 8192
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_config.py::test_max_context_tokens_default_none -v`
Expected: FAIL with `AttributeError: 'AIConfig' object has no attribute 'max_context_tokens'`

- [ ] **Step 3: Add the field to `AIConfig`**

In `plugins/sqlseed-ai/src/sqlseed_ai/config.py`, after the `timeout` field (around line 176), add:

```python
    # Model context window size in tokens (None = auto-detect via
    # ContextWindowDetector). Set explicitly to override detection.
    max_context_tokens: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_config.py::test_max_context_tokens_default_none plugins/sqlseed-ai/tests/test_ai_config.py::test_max_context_tokens_explicit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/config.py plugins/sqlseed-ai/tests/test_ai_config.py
git commit -m "feat(ai/config): add max_context_tokens field to AIConfig"
```

---

## Task 2: Move `LLMClient` + `_OpenAICompatAdapter` to shared `_client.py`

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/_client.py`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py` (remove moved code, re-import)
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` (update import path, line 465)

- [ ] **Step 1: Create `healer/_client.py`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/_client.py`:

```python
"""Shared LLM client protocol + OpenAI-compatible adapter.

Extracted from ``llm_healer.py`` so all healers (Level1/2/3) can share
the same client abstraction without importing the soon-to-be-deleted
``llm_healer`` module.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Minimal protocol for chat-completion clients (openai-compatible)."""

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Create a chat completion (openai-compatible)."""
        ...


class OpenAICompatAdapter:
    """Adapter wrapping ``openai.OpenAI`` to satisfy the ``LLMClient`` protocol.

    The real OpenAI Python SDK exposes ``client.chat.completions.create(...)``
    (attribute chain), but healers call ``client.chat_completions_create(...)``
    (flat method). Without this adapter, every heal() call raises
    ``AttributeError: 'OpenAI' object has no attribute 'chat_completions_create'``.
    """

    def __init__(self, openai_client: Any) -> None:
        self._client = openai_client

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Forward to ``client.chat.completions.create``."""
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
```

- [ ] **Step 2: Update `llm_healer.py` to import from `_client.py`**

In `plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py`:
- Delete the `LLMClient` class (lines 32-44) and `_OpenAICompatAdapter` class (lines 47-78).
- Add import at the top (after `from sqlseed._utils.logger import get_logger`):

```python
from sqlseed_ai.healer._client import LLMClient, OpenAICompatAdapter
```

- Keep `_OpenAICompatAdapter` as a backward-compatible alias at module level (temporary, until Task 13 deletes `llm_healer.py`):

```python
# Backward-compatible alias — will be removed when this module is deleted.
_OpenAICompatAdapter = OpenAICompatAdapter
```

- [ ] **Step 3: Update `ai_commands.py` import**

In `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` line 465, change:

```python
    from sqlseed_ai.healer.llm_healer import _OpenAICompatAdapter
```

to:

```python
    from sqlseed_ai.healer._client import OpenAICompatAdapter as _OpenAICompatAdapter
```

- [ ] **Step 4: Run existing healer tests to verify no breakage**

Run: `pytest plugins/sqlseed-ai/tests/test_healer_llm_healer.py plugins/sqlseed-ai/tests/test_healer_coordinator.py -v`
Expected: PASS (existing mock-based tests still work until Task 14 deletes them)

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/_client.py plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py
git commit -m "refactor(ai/healer): extract LLMClient + OpenAICompatAdapter to shared _client.py"
```

---

## Task 3: Extend `healer/models.py` with new data structures

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/healer/models.py`

- [ ] **Step 1: Add new dataclasses and enums**

Replace the entire contents of `plugins/sqlseed-ai/src/sqlseed_ai/healer/models.py` with:

```python
"""Layer 4: Healer data structures.

Spec reference: Section 6.2 + 4-Level Heal Architecture (2026-07-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractViolation
    from sqlseed_ai.repair.models import AppliedFix


class DegradeReason(Enum):
    """Reasons why a column was degraded to the Core 9-level mapper."""

    LLM_TIMEOUT = "llm_timeout"
    LLM_OSCILLATION = "llm_oscillation"
    LLM_FAILURE = "llm_failure"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    CASCADE = "cascade"  # set by ProgressiveDegrader for downstream columns


class FailureType(Enum):
    """Classification of LLM failures for routing decisions."""

    CONTEXT_OVERFLOW = "context_overflow"    # Context window exceeded
    EMPTY_RESPONSE = "empty_response"        # LLM returned empty string
    JSON_FORMAT = "json_format"              # JSON parsing failed
    SEMANTIC = "semantic"                    # Validator rejected config
    NETWORK = "network"                      # API timeout/connection/rate limit
    UNKNOWN = "unknown"                      # Unclassified (treated as SEMANTIC)


@dataclass
class SubgraphTask:
    """A healing subgraph: tables to be healed together (SCC or single-table)."""

    task_id: str
    tables: list[str]
    is_scc: bool = False
    parent_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealAttempt:
    """Record of a single LLM healer attempt.

    Spec reference: Section 4.3 — tracks which level was tried, the
    failure type (if any), latency, token estimate, and error message.
    """

    level: int                                   # 1, 2, or 3 (which healer was tried)
    failure_type: FailureType | None = None      # None if success
    latency_ms: int = 0                          # elapsed time in milliseconds
    token_estimate: int = 0                      # prompt token estimate
    error_message: str | None = None
    applied_fixes: list[AppliedFix] = field(default_factory=list)


@dataclass
class FKInfo:
    """Foreign key reference info for Level 2 column context."""

    ref_table: str
    ref_column: str


@dataclass
class ColumnContext:
    """Minimal dependency info for Level 2 column-level healing."""

    table_name: str
    column_name: str
    column_type: str
    nullable: bool
    default: Any
    is_unique: bool
    check_constraints: list[dict[str, Any]]     # all CHECKs this column participates in
    derive_from_sources: list[tuple[str, str]]  # (column_name, column_type) pairs
    derive_from_downstream: list[str]            # downstream column names
    cross_column_refs: list[tuple[str, str]]     # (column_name, column_type) pairs
    fk_info: FKInfo | None


@dataclass
class Level1Result:
    """Result of Level1SubgraphHealer.heal()."""

    success: bool
    config_patch: dict[str, Any] | None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0


@dataclass
class Level2Result:
    """Result of Level2ColumnHealer.heal_column() for a single column."""

    success: bool
    column: str
    config_patch: dict[str, Any] | None = None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0


@dataclass
class Level3Result:
    """Result of Level3CompactHealer.heal_compact()."""

    success: bool
    mode: Literal["compact", "ultra_compact"]
    config_patch: dict[str, Any] | None = None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0
    json_repaired: bool = False


@dataclass
class HealResult:
    """Final result of HealOrchestrator.heal().

    Extended from the original 2-level HealResult to carry 4-level
    diagnostics (level_used, failure_type, attempts) while preserving
    ``config`` and ``degraded_columns`` for AutoHealOrchestrator consumers.
    """

    config: dict[str, Any]
    success: bool = False
    level_used: int = 0                          # 1, 2, 3, or 4
    failure_type: FailureType | None = None      # set when success=False
    degraded_columns: list[str] = field(default_factory=list)
    degrade_reasons: dict[str, DegradeReason] = field(default_factory=dict)
    applied_fixes: list[AppliedFix] = field(default_factory=list)
    learned_contracts: list[ContractViolation] = field(default_factory=list)
    attempts: list[HealAttempt] = field(default_factory=list)
    total_attempts: int = 0
    total_elapsed: float = 0.0
```

- [ ] **Step 2: Run existing tests to verify import compatibility**

Run: `pytest plugins/sqlseed-ai/tests/test_healer_models.py -v`
Expected: PASS (existing `HealResult` tests still work — `config`, `degraded_columns`, `degrade_reasons` fields preserved)

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/models.py
git commit -m "feat(ai/healer): extend models.py with 4-level data structures"
```

---

## Task 4: Create `ContextWindowDetector`

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/context_detector.py`
- Test: `plugins/sqlseed-ai/tests/healer/test_context_detector.py`

- [ ] **Step 1: Write the failing tests**

Create `plugins/sqlseed-ai/tests/healer/__init__.py` (empty file).

Create `plugins/sqlseed-ai/tests/healer/test_context_detector.py`:

```python
"""Pure-logic tests for ContextWindowDetector (no LLM calls)."""

from __future__ import annotations

from sqlseed_ai.config import AIConfig
from sqlseed_ai.healer.context_detector import ContextWindowDetector


def test_get_context_window_from_config():
    """AIConfig.max_context_tokens takes priority."""
    cfg = AIConfig(max_context_tokens=16384)
    det = ContextWindowDetector(cfg, model="gemma-4-e2b")
    assert det.get_context_window() == 16384


def test_get_context_window_from_model_map():
    """Model mapping table is used when max_context_tokens is None."""
    cfg = AIConfig(max_context_tokens=None)
    det = ContextWindowDetector(cfg, model="gemma-4-e2b")
    assert det.get_context_window() == 8192


def test_get_context_window_default_fallback():
    """Conservative default 4096 for unknown models."""
    cfg = AIConfig(max_context_tokens=None)
    det = ContextWindowDetector(cfg, model="unknown-model-xyz")
    assert det.get_context_window() == 4096


def test_estimate_tokens_rough():
    """Token estimate is roughly chars / 4."""
    cfg = AIConfig()
    det = ContextWindowDetector(cfg, model="any")
    assert det.estimate_tokens("abcd") == 1
    assert det.estimate_tokens("abcdefgh") == 2


def test_should_skip_level1_above_threshold():
    """token > 60% of context window → skip Level 1."""
    cfg = AIConfig(max_context_tokens=1000)
    det = ContextWindowDetector(cfg, model="any")
    # 700 tokens > 60% of 1000 (600) → True
    assert det.should_skip_level1(prompt="x" * 2800) is True  # 2800 chars / 4 = 700 tokens


def test_should_skip_level1_below_threshold():
    """token ≤ 60% of context window → do not skip Level 1."""
    cfg = AIConfig(max_context_tokens=1000)
    det = ContextWindowDetector(cfg, model="any")
    # 500 tokens ≤ 60% of 1000 (600) → False
    assert det.should_skip_level1(prompt="x" * 2000) is False  # 2000 chars / 4 = 500 tokens
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_context_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sqlseed_ai.healer.context_detector'`

- [ ] **Step 3: Implement `ContextWindowDetector`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/context_detector.py`:

```python
"""ContextWindowDetector — dynamic model context window detection.

Spec reference: Section 3.2.

Detection priority:
  1. ``AIConfig.max_context_tokens`` (user explicit configuration)
  2. Model mapping table (common models)
  3. Conservative default (4096)
"""

from __future__ import annotations

from sqlseed_ai.config import AIConfig

# Known model context window sizes (in tokens).
# Used when AIConfig.max_context_tokens is None.
_MODEL_CONTEXT_MAP: dict[str, int] = {
    "gemma-4-e2b": 8192,
    "gemma-4-e4b": 8192,
    "gemma-2b": 8192,
    "gemma-7b": 8192,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-3.5-turbo": 4096,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "deepseek-chat": 32768,
    "deepseek-r1": 65536,
    "llama-3-8b": 8192,
    "llama-3-70b": 8192,
    "qwen2-7b": 32768,
    "qwen2-72b": 32768,
    "mistral-7b": 32768,
    "mixtral-8x7b": 32768,
}

# Conservative default when model is unknown.
_DEFAULT_CONTEXT_WINDOW = 4096

# Pre-judgment threshold: skip Level 1 if token estimate exceeds this
# fraction of the context window.
_SKIP_LEVEL1_THRESHOLD = 0.60


class ContextWindowDetector:
    """Detect model context window size and estimate prompt token counts."""

    def __init__(self, ai_config: AIConfig, *, model: str = "") -> None:
        self._config = ai_config
        self._model = (model or "").lower()

    def get_context_window(self) -> int:
        """Get model context window size (tokens).

        Priority: AIConfig.max_context_tokens → model map → default 4096.
        """
        if self._config.max_context_tokens is not None:
            return self._config.max_context_tokens
        for key, size in _MODEL_CONTEXT_MAP.items():
            if key in self._model:
                return size
        return _DEFAULT_CONTEXT_WINDOW

    def estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt (rough: chars / 4)."""
        return max(1, len(prompt) // 4)

    def should_skip_level1(self, prompt: str) -> bool:
        """Pre-judge: return True if tokens > 60% of context window."""
        tokens = self.estimate_tokens(prompt)
        threshold = self.get_context_window() * _SKIP_LEVEL1_THRESHOLD
        return tokens > threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_context_detector.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/context_detector.py plugins/sqlseed-ai/tests/healer/__init__.py plugins/sqlseed-ai/tests/healer/test_context_detector.py
git commit -m "feat(ai/healer): add ContextWindowDetector for dynamic context window detection"
```

---

## Task 5: Create `FailureClassifier`

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/failure_classifier.py`
- Test: `plugins/sqlseed-ai/tests/healer/test_failure_classifier.py`

- [ ] **Step 1: Write the failing tests**

Create `plugins/sqlseed-ai/tests/healer/test_failure_classifier.py`:

```python
"""Pure-logic tests for FailureClassifier (no LLM calls)."""

from __future__ import annotations

import json

import pytest
from sqlseed_ai.healer.failure_classifier import FailureClassifier, FailureType


@pytest.fixture
def classifier():
    return FailureClassifier()


def test_classify_context_overflow_from_message(classifier):
    """Error message containing 'context length' → CONTEXT_OVERFLOW."""
    err = RuntimeError("This model's maximum context length is 8192 tokens")
    assert classifier.classify(err, response=None) == FailureType.CONTEXT_OVERFLOW


def test_classify_context_overflow_from_too_long(classifier):
    """Error message containing 'too long' → CONTEXT_OVERFLOW."""
    err = RuntimeError("Input is too long for this model")
    assert classifier.classify(err, response=None) == FailureType.CONTEXT_OVERFLOW


def test_classify_empty_response(classifier):
    """Empty or whitespace-only response → EMPTY_RESPONSE."""
    assert classifier.classify(None, response="") == FailureType.EMPTY_RESPONSE
    assert classifier.classify(None, response="   \n  ") == FailureType.EMPTY_RESPONSE


def test_classify_json_format(classifier):
    """JSONDecodeError → JSON_FORMAT."""
    err = json.JSONDecodeError("Expecting value", "", 0)
    assert classifier.classify(err, response="{invalid json") == FailureType.JSON_FORMAT


def test_classify_semantic_from_message(classifier):
    """Error message containing 'validation' → SEMANTIC."""
    err = RuntimeError("Validation failed: CHECK constraint violated")
    assert classifier.classify(err, response='{"tables": []}') == FailureType.SEMANTIC


def test_classify_network_timeout(classifier):
    """Timeout-related error → NETWORK."""
    err = TimeoutError("Request timed out after 60s")
    assert classifier.classify(err, response=None) == FailureType.NETWORK


def test_classify_network_connection(classifier):
    """Connection-related error → NETWORK."""
    err = ConnectionError("Failed to connect to localhost:1234")
    assert classifier.classify(err, response=None) == FailureType.NETWORK


def test_classify_unknown(classifier):
    """Unclassified error → UNKNOWN."""
    err = RuntimeError("Something unexpected happened")
    assert classifier.classify(err, response=None) == FailureType.UNKNOWN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_failure_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `FailureClassifier`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/failure_classifier.py`:

```python
"""FailureClassifier — classify LLM failures for routing decisions.

Spec reference: Section 3.3 + Section 5.1.

Classification rules (checked in order):
  1. Error message contains "context length" / "too long" → CONTEXT_OVERFLOW
  2. Response is empty/whitespace → EMPTY_RESPONSE
  3. JSONDecodeError → JSON_FORMAT
  4. Error message contains "validation" / "constraint" → SEMANTIC
  5. Timeout/Connection errors → NETWORK
  6. Other → UNKNOWN (treated as SEMANTIC by HealOrchestrator)
"""

from __future__ import annotations

import json

from sqlseed_ai.healer.models import FailureType


class FailureClassifier:
    """Classify LLM failure types based on error and response."""

    def classify(self, error: Exception | None, response: str | None) -> FailureType:
        """Classify an LLM failure.

        Args:
            error: The exception raised (if any). None if the call succeeded
                but the response was invalid.
            response: The raw LLM response string (if any).

        Returns:
            The classified FailureType.
        """
        # 1. Check error message for context overflow keywords.
        if error is not None:
            err_msg = str(error).lower()
            if "context length" in err_msg or "too long" in err_msg:
                return FailureType.CONTEXT_OVERFLOW

        # 2. Check for empty response.
        if response is not None and not response.strip():
            return FailureType.EMPTY_RESPONSE
        if error is None and response is None:
            return FailureType.EMPTY_RESPONSE

        # 3. Check for JSON format errors.
        if isinstance(error, json.JSONDecodeError):
            return FailureType.JSON_FORMAT

        # 4. Check for semantic/validation errors.
        if error is not None:
            err_msg = str(error).lower()
            if "validation" in err_msg or "constraint" in err_msg:
                return FailureType.SEMANTIC

        # 5. Check for network errors.
        if isinstance(error, TimeoutError | ConnectionError | OSError):
            return FailureType.NETWORK
        if error is not None:
            err_msg = str(error).lower()
            if "timeout" in err_msg or "timed out" in err_msg:
                return FailureType.NETWORK
            if "connection" in err_msg or "connect" in err_msg:
                return FailureType.NETWORK
            if "rate limit" in err_msg:
                return FailureType.NETWORK

        # 6. Unknown.
        return FailureType.UNKNOWN
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_failure_classifier.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/failure_classifier.py plugins/sqlseed-ai/tests/healer/test_failure_classifier.py
git commit -m "feat(ai/healer): add FailureClassifier with 6 failure types"
```

---

## Task 6: Create `Level1SubgraphHealer` (refactored from `LLMHealer`)

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py`

This extracts the core LLM call logic from `LLMHealer.heal()` (lines 186-256 of `llm_healer.py`), returning `Level1Result` instead of `HealAttemptResult`. Compact/ultra-compact logic is NOT included (that goes to Level3).

- [ ] **Step 1: Implement `Level1SubgraphHealer`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py`:

```python
"""Level 1: Subgraph-level LLM healer.

Spec reference: Section 3.4.

Refactored from ``LLMHealer`` (deleted in Task 13). Sends the entire
subgraph (all violations + current column configs) to the LLM and
returns a config patch. No compact/ultra-compact logic — that lives in
``Level3CompactHealer``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer._client import LLMClient
from sqlseed_ai.healer.models import Level1Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


_SYSTEM_PROMPT = """You are a SQL test-data generator repair agent.

You will receive:
1. A list of tables that failed validation.
2. The violation reports (constraint type + columns + message).
3. The current column configurations (generator, params, derive_from).

Your task: output a JSON object with the corrected column configurations
for the failed tables only. Do NOT include tables that were not in the
failure list.

Output format:
{"tables": [{"name": "<table>", "columns": [{"name": "<col>",
  "generator": "<gen>", "params": {...}}]}]}

Rules:
- Never use a generator that crashes on the column type (e.g. integer on TIMESTAMP).
- Respect UNIQUE constraints by upgrading choice -> template_pool when needed.
- Respect CHECK constraints by adjusting min/max params.
- Keep the response under 1500 tokens.
"""


@dataclass
class SubgraphPrompt:
    """Built prompt for inspection/logging."""

    system_prompt: str
    user_prompt: str
    estimated_tokens: int


class Level1SubgraphHealer:
    """Subgraph-level LLM healer (Level 1).

    Sends the full subgraph context to the LLM. Use when the subgraph
    fits comfortably within the model's context window (pre-judged by
    ``ContextWindowDetector``).
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 1500,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def build_prompt(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> SubgraphPrompt:
        """Build the subgraph-level healer prompt."""
        relevant = [v for v in violations if v.table in task.tables]

        lines: list[str] = []
        lines.append("Failed tables and violations:")
        for v in relevant:
            cols = ", ".join(v.columns) if v.columns else "(unknown)"
            lines.append(
                f"- Table {v.table}, columns [{cols}], "
                f"constraint={v.constraint_type.value}, severity={v.severity}"
            )
            if v.message:
                lines.append(f"  Message: {v.message}")

        lines.append("\nCurrent column configurations:")
        for table_cfg in parent_config.get("tables", []):
            if table_cfg["name"] not in task.tables:
                continue
            lines.append(f"Table {table_cfg['name']}:")
            for col in table_cfg.get("columns", []):
                gen = col.get("generator", "<none>")
                params = col.get("params", {})
                derive = col.get("derive_from")
                if derive:
                    lines.append(
                        f"  - {col['name']}: derive_from={derive}, "
                        f"expr={col.get('expression')}"
                    )
                else:
                    lines.append(f"  - {col['name']}: generator={gen}, params={params}")

        user_prompt = "\n".join(lines)
        estimated = len(_SYSTEM_PROMPT) // 4 + len(user_prompt) // 4
        return SubgraphPrompt(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            estimated_tokens=estimated,
        )

    def heal(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> Level1Result:
        """Call the LLM with full subgraph context.

        Returns Level1Result. Does NOT raise on LLM errors — the caller
        (HealOrchestrator) classifies the failure via FailureClassifier.
        Network errors are re-raised so the orchestrator can propagate
        them (per Section 5.3).
        """
        prompt = self.build_prompt(task, violations, parent_config)
        start = time.monotonic()

        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            # Network errors propagate (Section 5.3) — do not degrade.
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 1 LLM call failed", error=str(exc))
            return Level1Result(
                success=False,
                config_patch=None,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=prompt.estimated_tokens,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=None,
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        try:
            patch = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Level 1 LLM returned malformed JSON", error=str(exc))
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=exc,
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        if not isinstance(patch, dict) or "tables" not in patch:
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=RuntimeError("json_schema: missing 'tables' key"),
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        return Level1Result(
            success=True,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=prompt.estimated_tokens,
        )
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py
git commit -m "feat(ai/healer): add Level1SubgraphHealer (refactored from LLMHealer)"
```

---

## Task 7: Create `Level2ColumnHealer` (context builder + LLM call)

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py`
- Test: `plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py`

This is the largest new component. We test only `_build_column_context()` (pure logic, no LLM).

- [ ] **Step 1: Write failing tests for `_build_column_context()`**

Create `plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py`:

```python
"""Pure-logic tests for Level2ColumnHealer._build_column_context() (no LLM)."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.healer.models import FKInfo


def _make_snapshot(tables: dict):
    """Build a fake SchemaSnapshot-like object."""
    snap = MagicMock()
    snap.tables = tables
    return snap


def _make_table_meta(name, columns, column_types, constraints=None, foreign_keys=None):
    """Build a fake TableMeta-like object."""
    meta = MagicMock()
    meta.name = name
    meta.columns = columns
    meta.column_types = column_types
    meta.constraints = constraints or []
    meta.foreign_keys = foreign_keys or []
    return meta


def test_build_context_simple_column():
    """Single column with no dependencies → only target column attributes."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "users",
        columns=["id", "name", "email"],
        column_types={"id": "INTEGER", "name": "TEXT", "email": "TEXT"},
    )
    snap = _make_snapshot({"users": table})
    ctx = healer._build_column_context("users", "name", snap)
    assert ctx.table_name == "users"
    assert ctx.column_name == "name"
    assert ctx.column_type == "TEXT"
    assert ctx.check_constraints == []
    assert ctx.derive_from_sources == []
    assert ctx.derive_from_downstream == []
    assert ctx.cross_column_refs == []
    assert ctx.fk_info is None


def test_build_context_with_single_check():
    """Single-column CHECK → context contains the CHECK expression."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "products",
        columns=["price"],
        column_types={"price": "REAL"},
        constraints=[{"type": "check", "expression": "price > 0", "columns": ["price"]}],
    )
    snap = _make_snapshot({"products": table})
    ctx = healer._build_column_context("products", "price", snap)
    assert len(ctx.check_constraints) == 1
    assert ctx.check_constraints[0]["expression"] == "price > 0"


def test_build_context_with_cross_column_check():
    """Cross-column CHECK → related column appears in cross_column_refs."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "products",
        columns=["cost_price", "unit_price"],
        column_types={"cost_price": "REAL", "unit_price": "REAL"},
        constraints=[
            {"type": "check", "expression": "unit_price > cost_price", "columns": ["unit_price", "cost_price"]}
        ],
    )
    snap = _make_snapshot({"products": table})
    ctx = healer._build_column_context("products", "unit_price", snap)
    # cross_column_refs should contain cost_price
    ref_names = [r[0] for r in ctx.cross_column_refs]
    assert "cost_price" in ref_names
    # The cross-column CHECK should also appear in check_constraints
    assert len(ctx.check_constraints) == 1


def test_build_context_with_fk():
    """FK column → fk_info is populated."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "user_id"],
        column_types={"id": "INTEGER", "user_id": "INTEGER"},
        foreign_keys=[
            {"columns": ["user_id"], "ref_table": "users", "ref_columns": ["id"]}
        ],
    )
    snap = _make_snapshot({"orders": table})
    ctx = healer._build_column_context("orders", "user_id", snap)
    assert ctx.fk_info is not None
    assert ctx.fk_info.ref_table == "users"
    assert ctx.fk_info.ref_column == "id"


def test_build_context_with_unique():
    """UNIQUE constraint → is_unique is True."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "users",
        columns=["email"],
        column_types={"email": "TEXT"},
        constraints=[{"type": "unique", "columns": ["email"]}],
    )
    snap = _make_snapshot({"users": table})
    ctx = healer._build_column_context("users", "email", snap)
    assert ctx.is_unique is True


def test_build_context_with_derive_from_source():
    """derive_from source columns are detected from config (_enrich_with_config)."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "subtotal", "tax", "total"],
        column_types={"id": "INTEGER", "subtotal": "REAL", "tax": "REAL", "total": "REAL"},
    )
    snap = _make_snapshot({"orders": table})
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "subtotal", "generator": "random_float"},
                    {"name": "tax", "generator": "random_float"},
                    {"name": "total", "derive_from": ["subtotal", "tax"], "expression": "subtotal + tax"},
                ],
            }
        ]
    }
    ctx = healer._build_column_context("orders", "total", snap)
    ctx = healer._enrich_with_config(ctx, config)
    src_names = [s[0] for s in ctx.derive_from_sources]
    assert "subtotal" in src_names
    assert "tax" in src_names


def test_build_context_with_downstream():
    """derive_from downstream columns are detected from config (_enrich_with_config)."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "subtotal", "tax", "total"],
        column_types={"id": "INTEGER", "subtotal": "REAL", "tax": "REAL", "total": "REAL"},
    )
    snap = _make_snapshot({"orders": table})
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "subtotal", "generator": "random_float"},
                    {"name": "tax", "generator": "random_float"},
                    {"name": "total", "derive_from": ["subtotal", "tax"], "expression": "subtotal + tax"},
                ],
            }
        ]
    }
    # subtotal is a source for total → total should appear in downstream.
    ctx = healer._build_column_context("orders", "subtotal", snap)
    ctx = healer._enrich_with_config(ctx, config)
    assert "total" in ctx.derive_from_downstream
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `Level2ColumnHealer`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py`:

```python
"""Level 2: Column-level LLM healer with minimal dependency set.

Spec reference: Section 3.5 + 4.2.

Sends only the target column + its complete dependency set (CHECK
constraints, derive_from sources, cross-column refs, FK info) to the
LLM. This minimizes per-column prompt size and maximizes success rate
when the subgraph-level prompt (Level 1) overflows the context window.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer._client import LLMClient
from sqlseed_ai.healer.models import ColumnContext, FKInfo, Level2Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


_SYSTEM_PROMPT = """You are a SQL test-data generator repair agent.

You will receive:
1. A single column that failed validation.
2. The violation report for that column.
3. The column's complete dependency set (CHECK constraints, derive_from
   sources, cross-column references, FK info).

Your task: output a JSON object with the corrected configuration for
ONLY this column.

Output format:
{"name": "<col>", "generator": "<gen>", "params": {...}}

Rules:
- Never use a generator that crashes on the column type.
- Respect UNIQUE constraints by upgrading choice -> template when needed.
- Respect CHECK constraints by adjusting min/max params.
- If the column has a derive_from source, use derive_from + expression.
- Keep the response under 500 tokens.
"""


class Level2ColumnHealer:
    """Column-level LLM healer (Level 2).

    Processes violation columns individually with minimal dependency
    context. Used when Level 1 fails due to context overflow or empty
    response, or when pre-judgment detects the subgraph prompt is too
    large for the model's context window.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 500,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def _build_column_context(
        self,
        table_name: str,
        column_name: str,
        snapshot: SchemaSnapshot,
    ) -> ColumnContext:
        """Extract minimal dependency info for a column.

        Spec reference: Section 3.5 (information boundary).

        Returns a ColumnContext with:
        - Target column attributes (name, type, nullable, default, UNIQUE)
        - All CHECK constraints this column participates in
        - derive_from source columns (if any)
        - derive_from downstream columns (if any)
        - Cross-column CHECK related columns
        - FK info (if column is a FK)
        """
        meta = snapshot.tables.get(table_name)
        if meta is None:
            return ColumnContext(
                table_name=table_name,
                column_name=column_name,
                column_type="TEXT",
                nullable=True,
                default=None,
                is_unique=False,
                check_constraints=[],
                derive_from_sources=[],
                derive_from_downstream=[],
                cross_column_refs=[],
                fk_info=None,
            )

        col_type = meta.column_types.get(column_name, "TEXT")
        all_columns = meta.columns

        # Collect CHECK constraints this column participates in.
        col_checks: list[dict[str, Any]] = []
        cross_column_refs: list[tuple[str, str]] = []
        for c in meta.constraints:
            if c.get("type") != "check":
                continue
            expr = c.get("expression", "")
            if not expr:
                continue
            if not re.search(rf"\b{re.escape(column_name)}\b", expr, re.IGNORECASE):
                continue
            col_checks.append(c)
            # Find cross-column references (other columns in the same expr).
            for other in all_columns:
                if other == column_name:
                    continue
                if re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE):
                    other_type = meta.column_types.get(other, "TEXT")
                    cross_column_refs.append((other, other_type))

        # Detect UNIQUE.
        is_unique = False
        for c in meta.constraints:
            if c.get("type") == "unique" and column_name in (c.get("columns") or []):
                is_unique = True
                break

        # Detect FK info.
        fk_info: FKInfo | None = None
        for fk in meta.foreign_keys:
            fk_cols = fk.get("columns") or []
            if column_name in fk_cols:
                ref_table = fk.get("ref_table", "")
                ref_cols = fk.get("ref_columns") or []
                fk_info = FKInfo(
                    ref_table=ref_table,
                    ref_column=ref_cols[0] if ref_cols else "",
                )
                break

        # derive_from sources/downstream are not available from schema
        # alone — they come from the current config. The HealOrchestrator
        # passes the config so heal_column() can enrich the context.
        # _build_column_context returns empty lists here; heal_column()
        # fills them in from the config.
        return ColumnContext(
            table_name=table_name,
            column_name=column_name,
            column_type=col_type,
            nullable=True,  # schema reflection doesn't expose this cleanly; safe default
            default=None,
            is_unique=is_unique,
            check_constraints=col_checks,
            derive_from_sources=[],
            derive_from_downstream=[],
            cross_column_refs=cross_column_refs,
            fk_info=fk_info,
        )

    def _enrich_with_config(
        self,
        context: ColumnContext,
        config: dict[str, Any],
    ) -> ColumnContext:
        """Enrich context with derive_from info from the current config."""
        for table_cfg in config.get("tables", []):
            if table_cfg.get("name") != context.table_name:
                continue
            for col in table_cfg.get("columns", []):
                col_name = col.get("name", "")
                # If this column derives from others, record sources.
                if col_name == context.column_name and col.get("derive_from"):
                    sources = col.get("derive_from")
                    if isinstance(sources, str):
                        sources = [sources]
                    for src in sources:
                        src_type = "TEXT"
                        # Look up source column type in the same table.
                        for c2 in table_cfg.get("columns", []):
                            if c2.get("name") == src:
                                # We don't have column_types in config; use
                                # the snapshot type if available (set by caller).
                                pass
                        context.derive_from_sources.append((src, src_type))
                # If another column derives from THIS column, record downstream.
                if col.get("derive_from"):
                    sources = col.get("derive_from")
                    if isinstance(sources, str):
                        sources = [sources]
                    if context.column_name in sources and col_name != context.column_name:
                        context.derive_from_downstream.append(col_name)
        return context

    def _build_prompt(
        self,
        context: ColumnContext,
        violation: ViolationReport,
    ) -> tuple[str, int]:
        """Build the column-level prompt. Returns (user_prompt, estimated_tokens)."""
        lines: list[str] = []
        lines.append(f"Table: {context.table_name}")
        lines.append(f"Column: {context.column_name}")
        lines.append(f"Type: {context.column_type}")
        lines.append(f"Nullable: {context.nullable}")
        lines.append(f"Unique: {context.is_unique}")
        if context.fk_info:
            lines.append(
                f"FK: references {context.fk_info.ref_table}({context.fk_info.ref_column})"
            )
        if context.check_constraints:
            lines.append("CHECK constraints:")
            for c in context.check_constraints:
                lines.append(f"  - {c.get('expression', '')}")
        if context.cross_column_refs:
            lines.append("Cross-column references:")
            for ref_name, ref_type in context.cross_column_refs:
                lines.append(f"  - {ref_name} ({ref_type})")
        if context.derive_from_sources:
            lines.append("derive_from sources:")
            for src_name, src_type in context.derive_from_sources:
                lines.append(f"  - {src_name} ({src_type})")
        if context.derive_from_downstream:
            lines.append(f"derive_from downstream: {context.derive_from_downstream}")
        lines.append(f"\nViolation: {violation.constraint_type.value} on {violation.columns}")
        if violation.message:
            lines.append(f"Message: {violation.message}")

        user_prompt = "\n".join(lines)
        estimated = len(_SYSTEM_PROMPT) // 4 + len(user_prompt) // 4
        return user_prompt, estimated

    def heal_column(
        self,
        table_name: str,
        column_name: str,
        violation: ViolationReport,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> Level2Result:
        """Call LLM with column-level minimal dependency context.

        Returns Level2Result. Network errors are re-raised (Section 5.3).
        """
        context = self._build_column_context(table_name, column_name, snapshot)
        context = self._enrich_with_config(context, config)
        user_prompt, estimated = self._build_prompt(context, violation)
        start = time.monotonic()

        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 2 LLM call failed", column=column_name, error=str(exc))
            return Level2Result(
                success=False,
                column=column_name,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=estimated,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level2Result(
                success=False,
                column=column_name,
                raw_response=content,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        try:
            patch = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Level 2 LLM returned malformed JSON", column=column_name, error=str(exc))
            return Level2Result(
                success=False,
                column=column_name,
                raw_response=content,
                error=exc,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        return Level2Result(
            success=True,
            column=column_name,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=estimated,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py plugins/sqlseed-ai/tests/healer/test_level2_context_builder.py
git commit -m "feat(ai/healer): add Level2ColumnHealer with minimal dependency context"
```

---

## Task 8: Create `Level3CompactHealer`

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py`

- [ ] **Step 1: Implement `Level3CompactHealer`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py`:

```python
"""Level 3: Compact/ultra-compact prompt LLM healer + JSON repair.

Spec reference: Section 3.6.

Uses progressively shorter prompts (compact → ultra_compact) to handle
context overflow and JSON format errors. Attempts JSON repair (strip
markdown fences, trailing commas) before declaring failure.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any, Literal

from sqlseed_ai.healer._client import LLMClient
from sqlseed_ai.healer.models import Level3Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


_COMPACT_SYSTEM_PROMPT = """You are a SQL test-data repair agent. Output JSON only.
Format: {"tables":[{"name":"<t>","columns":[{"name":"<c>","generator":"<g>","params":{}}]}]}
Fix the violations. No explanation."""

_ULTRA_COMPACT_SYSTEM_PROMPT = """Output JSON only: {"tables":[{"name":"<t>","columns":[{"name":"<c>","generator":"<g>","params":{}}]}]}"""


def _repair_json(text: str) -> str:
    """Attempt to repair minor JSON format errors.

    Strips markdown code fences (```json ... ```), trailing commas, and
    leading/trailing whitespace. Does not use external libraries.
    """
    text = text.strip()
    # Strip markdown code fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    # Remove trailing commas before } or ].
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


class Level3CompactHealer:
    """Compact/ultra-compact prompt LLM healer (Level 3).

    Two modes:
    - ``compact``: Reduced system prompt, no few-shot examples.
    - ``ultra_compact``: Minimal system prompt (JSON format only).
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 1000,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def _build_user_prompt(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
        mode: Literal["compact", "ultra_compact"],
    ) -> str:
        """Build a compact user prompt."""
        relevant = [v for v in violations if v.table in task.tables]
        lines: list[str] = []
        for v in relevant:
            cols = ",".join(v.columns) if v.columns else "?"
            lines.append(f"{v.table}.{cols}:{v.constraint_type.value}")
        lines.append("")
        for table_cfg in parent_config.get("tables", []):
            if table_cfg["name"] not in task.tables:
                continue
            for col in table_cfg.get("columns", []):
                gen = col.get("generator", "?")
                params = col.get("params", {})
                lines.append(f"{table_cfg['name']}.{col['name']}={gen}:{params}")
        return "\n".join(lines)

    def heal_compact(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
        mode: Literal["compact", "ultra_compact"],
    ) -> Level3Result:
        """Call LLM with compact or ultra_compact prompt.

        Returns Level3Result. Network errors are re-raised (Section 5.3).
        """
        system_prompt = (
            _COMPACT_SYSTEM_PROMPT if mode == "compact" else _ULTRA_COMPACT_SYSTEM_PROMPT
        )
        user_prompt = self._build_user_prompt(task, violations, parent_config, mode)
        estimated = len(system_prompt) // 4 + len(user_prompt) // 4
        start = time.monotonic()

        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 3 LLM call failed", mode=mode, error=str(exc))
            return Level3Result(
                success=False,
                mode=mode,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=estimated,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level3Result(
                success=False,
                mode=mode,
                raw_response=content,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        # Try direct JSON parse first.
        patch: dict[str, Any] | None = None
        json_repaired = False
        try:
            patch = json.loads(content)
        except json.JSONDecodeError:
            # Attempt JSON repair.
            repaired = _repair_json(content)
            try:
                patch = json.loads(repaired)
                json_repaired = True
            except json.JSONDecodeError as exc:
                logger.warning("Level 3 JSON repair failed", mode=mode, error=str(exc))
                return Level3Result(
                    success=False,
                    mode=mode,
                    raw_response=content,
                    error=exc,
                    elapsed_seconds=elapsed,
                    prompt_tokens=estimated,
                    json_repaired=False,
                )

        if not isinstance(patch, dict) or "tables" not in patch:
            return Level3Result(
                success=False,
                mode=mode,
                raw_response=content,
                error=RuntimeError("json_schema: missing 'tables' key"),
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
                json_repaired=json_repaired,
            )

        return Level3Result(
            success=True,
            mode=mode,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=estimated,
            json_repaired=json_repaired,
        )
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py
git commit -m "feat(ai/healer): add Level3CompactHealer with compact/ultra_compact + JSON repair"
```

---

## Task 9: Create `HealOrchestrator`

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py`

This is the central coordinator. It implements the 4-level degradation logic with failure-type-aware routing per Section 2.2 of the spec.

- [ ] **Step 1: Implement `HealOrchestrator`**

Create `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py`:

```python
"""HealOrchestrator — coordinates 4-level LLM heal degradation.

Spec reference: Section 3.1 + 2.2 + 4.1.

Replaces ``Layer4Coordinator``. Routes LLM failures by type:
  CONTEXT_OVERFLOW / EMPTY_RESPONSE → Level 2 (column-level)
  JSON_FORMAT → Level 3 (compact, skip Level 2)
  SEMANTIC → Level 4 (deterministic degrade, skip Level 2/3)
  NETWORK → raise exception (not in degradation chain)

Pre-judgment: if token estimate > 60% of context window, skip Level 1.
"""

from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer.context_detector import ContextWindowDetector
from sqlseed_ai.healer.degrader import ProgressiveDegrader
from sqlseed_ai.healer.failure_classifier import FailureClassifier
from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
from sqlseed_ai.healer.models import (
    DegradeReason,
    FailureType,
    HealAttempt,
    HealResult,
    SubgraphTask,
)
from sqlseed_ai.healer.oscillation import OscillationDetector

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class HealOrchestrator:
    """Coordinate 4-level LLM heal degradation with failure-type routing."""

    def __init__(
        self,
        *,
        snapshot: SchemaSnapshot,
        context_detector: ContextWindowDetector,
        failure_classifier: FailureClassifier,
        level1: Level1SubgraphHealer,
        level2: Level2ColumnHealer,
        level3: Level3CompactHealer,
        degrader: ProgressiveDegrader,
        validator: Any,  # FastValidator
        schema_hash: str = "",
        max_rounds: int = 3,
        time_budget_seconds: float = 60.0,
    ) -> None:
        self._snapshot = snapshot
        self._context_detector = context_detector
        self._failure_classifier = failure_classifier
        self._level1 = level1
        self._level2 = level2
        self._level3 = level3
        self._degrader = degrader
        self._validator = validator
        self._schema_hash = schema_hash
        self._max_rounds = max_rounds
        self._time_budget = time_budget_seconds
        self._oscillation = OscillationDetector()

    def heal(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
    ) -> HealResult:
        """Main entry: orchestrate 4-level degradation.

        Returns HealResult with the final config (repaired or degraded).
        Network errors propagate as RuntimeError (Section 5.3).
        """
        start = time.monotonic()
        attempts: list[HealAttempt] = []
        current_config = copy.deepcopy(config)
        current_violations = list(violations)

        for round_num in range(1, self._max_rounds + 1):
            if time.monotonic() - start > self._time_budget:
                logger.warning("HealOrchestrator time budget exhausted", budget=self._time_budget)
                return self._degrade_and_return(
                    current_config, current_violations, DegradeReason.TIME_BUDGET_EXHAUSTED,
                    attempts, round_num, start,
                )

            result = self._try_one_round(task, current_violations, current_config, attempts, round_num)

            if result.success:
                # Re-validate the patched config.
                current_config = self._merge_patch(current_config, result.config_patch)
                val_result = self._validator.validate(current_config, self._snapshot)
                new_violations = self._extract_violations(val_result)

                if not new_violations:
                    return HealResult(
                        config=current_config,
                        success=True,
                        level_used=result.level,
                        attempts=attempts,
                        total_attempts=round_num,
                        total_elapsed=time.monotonic() - start,
                    )

                # New violations — feed back into the loop.
                current_violations = new_violations
                if self._oscillation.check_and_record(current_violations):
                    logger.warning("Oscillation detected, degrading", round=round_num)
                    return self._degrade_and_return(
                        current_config, current_violations, DegradeReason.LLM_OSCILLATION,
                        attempts, round_num, start,
                    )
                continue

            # Failure — classify and route.
            ftype = result.failure_type
            if ftype == FailureType.NETWORK:
                raise RuntimeError(f"LLM network error: {result.error}")

            # For non-network failures, the routing is handled inside
            # _try_one_round. If we reach here, all levels failed.
            return self._degrade_and_return(
                current_config, current_violations, DegradeReason.LLM_FAILURE,
                attempts, round_num, start,
            )

        return self._degrade_and_return(
            current_config, current_violations, DegradeReason.MAX_RETRIES_EXCEEDED,
            attempts, self._max_rounds, start,
        )

    def _try_one_round(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Try Level 1 → (Level 2 | Level 3) → degrade for one round.

        Returns _RoundResult with success/failure + failure_type + level.
        """
        # Pre-judgment: skip Level 1 if prompt too large.
        l1_prompt = self._level1.build_prompt(task, violations, config)
        skip_l1 = self._context_detector.should_skip_level1(
            l1_prompt.system_prompt + l1_prompt.user_prompt
        )

        if not skip_l1:
            # Level 1: subgraph-level.
            l1_result = self._level1.heal(task, violations, config)
            l1_ftype = None if l1_result.success else self._failure_classifier.classify(
                l1_result.error, l1_result.raw_response
            )
            attempts.append(HealAttempt(
                level=1,
                failure_type=l1_ftype,
                latency_ms=int(l1_result.elapsed_seconds * 1000),
                token_estimate=l1_result.prompt_tokens,
                error_message=str(l1_result.error) if l1_result.error else None,
            ))
            if l1_result.success:
                return _RoundResult(success=True, level=1, config_patch=l1_result.config_patch or {})

            # Classify failure.
            return self._route_after_l1_failure(
                task, violations, config, l1_ftype or FailureType.UNKNOWN, attempts, round_num
            )

        # Pre-judgment skipped Level 1 → go to Level 2.
        logger.info("Skipping Level 1 (pre-judgment: prompt too large)")
        return self._try_level2(task, violations, config, attempts, round_num)

    def _route_after_l1_failure(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        ftype: FailureType,
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Route to next level based on Level 1 failure type (Section 2.2)."""
        if ftype in (FailureType.CONTEXT_OVERFLOW, FailureType.EMPTY_RESPONSE):
            return self._try_level2(task, violations, config, attempts, round_num)
        if ftype == FailureType.JSON_FORMAT:
            return self._try_level3(task, violations, config, attempts, round_num, mode="compact")
        if ftype == FailureType.NETWORK:
            return _RoundResult(success=False, level=1, failure_type=FailureType.NETWORK)
        # SEMANTIC or UNKNOWN → degrade.
        return _RoundResult(success=False, level=1, failure_type=ftype)

    def _try_level2(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Try Level 2: column-level healing for each violation column."""
        merged_patch: dict[str, Any] = {"tables": []}
        all_success = True
        any_success = False

        for v in violations:
            for col in v.columns:
                l2_result = self._level2.heal_column(
                    v.table, col, v, config, self._snapshot
                )
                l2_ftype = None if l2_result.success else self._failure_classifier.classify(
                    l2_result.error, l2_result.raw_response
                )
                attempts.append(HealAttempt(
                    level=2,
                    failure_type=l2_ftype,
                    latency_ms=int(l2_result.elapsed_seconds * 1000),
                    token_estimate=l2_result.prompt_tokens,
                    error_message=str(l2_result.error) if l2_result.error else None,
                ))
                if l2_result.success and l2_result.config_patch:
                    # Merge single-column patch into merged_patch.
                    self._merge_column_patch(merged_patch, v.table, l2_result.config_patch)
                    any_success = True
                else:
                    all_success = False
                    # Classify failure for routing.
                    if l2_ftype == FailureType.CONTEXT_OVERFLOW:
                        # Single-column prompt overflow → Level 3.
                        return self._try_level3(
                            task, violations, config, attempts, round_num, mode="compact"
                        )

        if all_success and any_success:
            return _RoundResult(success=True, level=2, config_patch=merged_patch)
        if any_success:
            # Partial success — return what we have; remaining columns
            # will be caught by re-validation and degraded.
            return _RoundResult(success=True, level=2, config_patch=merged_patch)
        return _RoundResult(success=False, level=2, failure_type=FailureType.UNKNOWN)

    def _try_level3(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
        mode: str,
    ) -> _RoundResult:
        """Try Level 3: compact then ultra_compact."""
        l3_result = self._level3.heal_compact(task, violations, config, mode=mode)  # type: ignore[arg-type]
        l3_ftype = None if l3_result.success else self._failure_classifier.classify(
            l3_result.error, l3_result.raw_response
        )
        attempts.append(HealAttempt(
            level=3,
            failure_type=l3_ftype,
            latency_ms=int(l3_result.elapsed_seconds * 1000),
            token_estimate=l3_result.prompt_tokens,
            error_message=str(l3_result.error) if l3_result.error else None,
        ))
        if l3_result.success:
            return _RoundResult(success=True, level=3, config_patch=l3_result.config_patch or {})

        # If compact failed, try ultra_compact.
        if mode == "compact":
            return self._try_level3(task, violations, config, attempts, round_num, mode="ultra_compact")

        # ultra_compact also failed → degrade.
        return _RoundResult(success=False, level=3, failure_type=l3_ftype or FailureType.UNKNOWN)

    def _degrade_and_return(
        self,
        config: dict[str, Any],
        violations: list[ViolationReport],
        reason: DegradeReason,
        attempts: list[HealAttempt],
        round_num: int,
        start: float,
    ) -> HealResult:
        """Invoke ProgressiveDegrader and build the final HealResult."""
        failed_cols = self._collect_failed_columns(violations)
        if not failed_cols:
            return HealResult(
                config=config,
                success=False,
                level_used=4,
                attempts=attempts,
                total_attempts=round_num,
                total_elapsed=time.monotonic() - start,
            )
        failed_map = {c: reason for c in failed_cols}
        new_config, _ = self._degrader.degrade(config, failed_map, column_groups=[])
        return HealResult(
            config=new_config,
            success=False,
            level_used=4,
            degraded_columns=failed_cols,
            degrade_reasons=failed_map,
            attempts=attempts,
            total_attempts=round_num,
            total_elapsed=time.monotonic() - start,
        )

    @staticmethod
    def _extract_violations(val_result: Any) -> list[ViolationReport]:
        """Extract violations list from a ValidationResult or list."""
        if hasattr(val_result, "violations"):
            return list(val_result.violations)
        return list(val_result or [])

    @staticmethod
    def _merge_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Merge a healer-produced patch into the current config."""
        new_config = copy.deepcopy(config)
        patch_tables = {t["name"]: t for t in patch.get("tables", [])}
        for table_cfg in new_config.get("tables", []):
            name = table_cfg["name"]
            if name not in patch_tables:
                continue
            patch_cols = {c["name"]: c for c in patch_tables[name].get("columns", [])}
            new_columns = []
            for col in table_cfg.get("columns", []):
                if col["name"] in patch_cols:
                    degraded = col.get("_degraded", False)
                    new_col = copy.deepcopy(patch_cols[col["name"]])
                    if degraded:
                        new_col["_degraded"] = True
                    new_columns.append(new_col)
                else:
                    new_columns.append(col)
            table_cfg["columns"] = new_columns
        return new_config

    @staticmethod
    def _merge_column_patch(
        merged: dict[str, Any], table_name: str, col_patch: dict[str, Any]
    ) -> None:
        """Merge a single-column patch into the merged patch dict."""
        # Find or create the table entry.
        for t in merged.get("tables", []):
            if t["name"] == table_name:
                t["columns"].append(col_patch)
                return
        merged["tables"].append({"name": table_name, "columns": [col_patch]})

    @staticmethod
    def _collect_failed_columns(violations: list[ViolationReport]) -> list[str]:
        """Flatten columns from all violations (deduped, table-prefixed)."""
        seen: list[str] = []
        for v in violations:
            table = getattr(v, "table", "") or ""
            for c in v.columns:
                if not c:
                    continue
                key = f"{table}:{c}" if table else c
                if key not in seen:
                    seen.append(key)
        return seen


class _RoundResult:
    """Internal result of one round attempt (not exported)."""

    __slots__ = ("success", "level", "config_patch", "failure_type", "error")

    def __init__(
        self,
        *,
        success: bool,
        level: int,
        config_patch: dict[str, Any] | None = None,
        failure_type: FailureType | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.level = level
        self.config_patch = config_patch
        self.failure_type = failure_type
        self.error = error
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from sqlseed_ai.healer.orchestrator import HealOrchestrator; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py
git commit -m "feat(ai/healer): add HealOrchestrator with 4-level failure-type routing"
```

---

## Task 10: Update `AutoHealOrchestrator._heal_subgraph()`

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py`

- [ ] **Step 1: Update `__init__` to accept `heal_orchestrator` instead of `healer`**

In `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py`, modify the `__init__` method (lines 59-78). Change the `healer: Any` parameter to `heal_orchestrator: Any` and update the assignment:

```python
    def __init__(
        self,
        *,
        db_path: str | None = None,
        url: str | None = None,
        heal_orchestrator: Any,  # HealOrchestrator (replaces healer: LLMHealer)
        validator: Any,  # FastValidator
        total_budget_seconds: float = 300.0,
        max_scc_size: int = 3,
        max_retries: int = 3,
        verbose: bool = False,
    ) -> None:
        self._db_path = db_path
        self._url = url
        self._heal_orchestrator = heal_orchestrator
        self._validator = validator
        self._total_budget = total_budget_seconds
        self._max_scc_size = max_scc_size
        self._max_retries = max_retries
        self._verbose = verbose
```

- [ ] **Step 2: Update `_heal_subgraph()` to use `HealOrchestrator`**

Replace the Layer 4 section of `_heal_subgraph()` (lines 367-393). Replace:

```python
        # Layer 4: LLM healing (expensive)
        from sqlseed_ai.healer.coordinator import Layer4Coordinator
        from sqlseed_ai.healer.models import SubgraphTask

        if self._verbose:
            _debug(f"[ai-analyze]     Layer 4: calling LLM healer (max_attempts={self._max_retries}) ...")
        task = SubgraphTask(
            task_id=f"sg_{sg_tables[0] if sg_tables else 'empty'}",
            tables=sg_tables,
            is_scc=len(sg_tables) > 1,
        )
        coord: Layer4Coordinator = Layer4Coordinator(
            healer=self._healer,
            validator=self._validator,
            snapshot=snapshot,
            max_attempts=self._max_retries,
            schema_hash=schema_hash,
            time_budget_seconds=budget.per_table_budget(),
        )
        # Layer4Coordinator.reconcile returns HealResult with .config
        result = coord.reconcile(task, sg_config, violations)
        if self._verbose:
            # Surface LLM healer outcome (success/failure/degraded)
            attempts = getattr(result, "attempts", 0)
            success = getattr(result, "success", None)
            _debug(f"[ai-analyze]     Layer 4 done: attempts={attempts} success={success}")
        return result.config
```

with:

```python
        # Layer 4: 4-level LLM healing (subgraph → column → compact → degrade)
        from sqlseed_ai.healer.models import SubgraphTask

        if self._verbose:
            _debug(
                f"[ai-analyze]     Layer 4: calling HealOrchestrator "
                f"(max_rounds={self._max_retries}) ..."
            )
        task = SubgraphTask(
            task_id=f"sg_{sg_tables[0] if sg_tables else 'empty'}",
            tables=sg_tables,
            is_scc=len(sg_tables) > 1,
        )
        # HealOrchestrator.heal returns HealResult with .config
        result = self._heal_orchestrator.heal(task, violations, sg_config)
        if self._verbose:
            level = getattr(result, "level_used", 0)
            success = getattr(result, "success", False)
            degraded = getattr(result, "degraded_columns", [])
            _debug(
                f"[ai-analyze]     Layer 4 done: level={level} "
                f"success={success} degraded={len(degraded)}"
            )
        return result.config
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `python -c "from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py
git commit -m "refactor(ai/auto_heal): wire AutoHealOrchestrator to HealOrchestrator"
```

---

## Task 11: Update `ai_commands.py` to construct `HealOrchestrator`

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` (lines ~640-660 and ~780-795)

- [ ] **Step 1: Add a `_build_heal_orchestrator` helper function**

In `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py`, add a new helper function after `_build_llm_client` (around line 468):

```python
def _build_heal_orchestrator(
    ai_config: AIConfig,
    client: Any,
    snapshot: Any,
    validator: Any,
    schema_hash: str,
    *,
    max_retries: int = 3,
) -> Any:
    """Build a HealOrchestrator with all 4-level components.

    Constructs the ContextWindowDetector, FailureClassifier, 3 healers
    (Level1/2/3), and ProgressiveDegrader, then wraps them in a
    HealOrchestrator.
    """
    from sqlseed_ai.healer.context_detector import ContextWindowDetector
    from sqlseed_ai.healer.degrader import ProgressiveDegrader
    from sqlseed_ai.healer.failure_classifier import FailureClassifier
    from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
    from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
    from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
    from sqlseed_ai.healer.orchestrator import HealOrchestrator

    resolved_model = ai_config.resolve_model()
    context_detector = ContextWindowDetector(ai_config, model=resolved_model)
    failure_classifier = FailureClassifier()
    level1 = Level1SubgraphHealer(client=client, model=resolved_model)
    level2 = Level2ColumnHealer(client=client, model=resolved_model)
    level3 = Level3CompactHealer(client=client, model=resolved_model)
    degrader = ProgressiveDegrader(snapshot)

    return HealOrchestrator(
        snapshot=snapshot,
        context_detector=context_detector,
        failure_classifier=failure_classifier,
        level1=level1,
        level2=level2,
        level3=level3,
        degrader=degrader,
        validator=validator,
        schema_hash=schema_hash,
        max_rounds=max_retries,
    )
```

- [ ] **Step 2: Update `ai_analyze` command (around line 648)**

Replace:

```python
    healer = LLMHealer(client=client, model=resolved_model)

    orch = AutoHealOrchestrator(
        db_path=db_path,
        url=db_url,
        healer=healer,
        validator=validator,
        total_budget_seconds=300.0,
        max_retries=max_retries,
        verbose=True,
    )
```

with:

```python
    # Build HealOrchestrator (4-level: subgraph → column → compact → degrade).
    # The snapshot is captured inside AutoHealOrchestrator.run(), but
    # HealOrchestrator needs it for Level 2 context building. We create a
    # preliminary snapshot here for construction; AutoHealOrchestrator.run()
    # will create its own for the optimistic-lock check (Defense 8).
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    prelim_snapshot = SchemaSnapshot(db_path=db_path, url=db_url)
    heal_orch = _build_heal_orchestrator(
        ai_config, client, prelim_snapshot, validator,
        schema_hash=prelim_snapshot.schema_hash, max_retries=max_retries,
    )

    orch = AutoHealOrchestrator(
        db_path=db_path,
        url=db_url,
        heal_orchestrator=heal_orch,
        validator=validator,
        total_budget_seconds=300.0,
        max_retries=max_retries,
        verbose=True,
    )
```

- [ ] **Step 3: Update `auto_heal` command (around line 784)**

Apply the same replacement pattern to the `auto_heal` command's `LLMHealer` + `AutoHealOrchestrator` construction (around line 784).

- [ ] **Step 4: Remove the `LLMHealer` import**

Find and remove the `from sqlseed_ai.healer.llm_healer import LLMHealer` import (if it exists at the top of `ai_commands.py`). The `LLMHealer` is no longer used directly — `_build_heal_orchestrator` handles construction.

- [ ] **Step 5: Verify CLI imports work**

Run: `python -c "from sqlseed_ai.cli.ai_commands import ai_analyze, auto_heal; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py
git commit -m "refactor(ai/cli): construct HealOrchestrator instead of LLMHealer"
```

---

## Task 12: Delete old components + old tests

**Files:**
- Delete: `plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py`
- Delete: `plugins/sqlseed-ai/src/sqlseed_ai/healer/coordinator.py`
- Delete: `plugins/sqlseed-ai/tests/test_healer_llm_healer.py`
- Delete: `plugins/sqlseed-ai/tests/test_healer_coordinator.py`

- [ ] **Step 1: Verify no remaining imports of deleted modules**

Run these searches to confirm no other code imports `llm_healer` or `coordinator`:

```
Grep pattern: "from sqlseed_ai.healer.llm_healer import|from sqlseed_ai.healer.coordinator import"
path: plugins/sqlseed-ai/src/
```

Expected: No matches (Task 2 and Task 11 already updated all imports).

- [ ] **Step 2: Delete the files**

Delete:
- `plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/healer/coordinator.py`
- `plugins/sqlseed-ai/tests/test_healer_llm_healer.py`
- `plugins/sqlseed-ai/tests/test_healer_coordinator.py`

- [ ] **Step 3: Verify test suite still collects**

Run: `pytest plugins/sqlseed-ai/tests/ --collect-only -q 2>&1 | head -50`
Expected: No collection errors. Remaining healer tests (`test_healer_models.py`, `test_healer_degrader.py`, `test_healer_oscillation.py`, `test_healer_subgraph.py`, `test_healer_post_repair.py`, `test_healer_diff_learner.py`) should still collect.

- [ ] **Step 4: Commit**

```bash
git add -A plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py plugins/sqlseed-ai/src/sqlseed_ai/healer/coordinator.py plugins/sqlseed-ai/tests/test_healer_llm_healer.py plugins/sqlseed-ai/tests/test_healer_coordinator.py
git commit -m "refactor(ai/healer): delete LLMHealer + Layer4Coordinator (replaced by 4-level architecture)"
```

---

## Task 13: Update `healer/__init__.py` exports

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/healer/__init__.py`

- [ ] **Step 1: Update exports**

Replace the contents of `plugins/sqlseed-ai/src/sqlseed_ai/healer/__init__.py` with:

```python
"""Layer 4: 4-Level Heal Architecture (subgraph → column → compact → degrade)."""

from sqlseed_ai.healer.context_detector import ContextWindowDetector
from sqlseed_ai.healer.failure_classifier import FailureClassifier, FailureType
from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
from sqlseed_ai.healer.orchestrator import HealOrchestrator

__all__ = [
    "ContextWindowDetector",
    "FailureClassifier",
    "FailureType",
    "HealOrchestrator",
    "Level1SubgraphHealer",
    "Level2ColumnHealer",
    "Level3CompactHealer",
]
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from sqlseed_ai.healer import HealOrchestrator, FailureType; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/healer/__init__.py
git commit -m "feat(ai/healer): update __init__.py exports for 4-level architecture"
```

---

## Task 14: Run lint + type check + existing tests

**Files:** None (verification only)

- [ ] **Step 1: Run ruff lint**

Run: `ruff check src/ tests/ plugins/`
Expected: No errors. Fix any issues found.

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check src/ tests/ plugins/`
Expected: No errors. Run `ruff format src/ tests/ plugins/` if needed.

- [ ] **Step 3: Run mypy**

Run: `mypy`
Expected: No errors. Fix any type issues in the new files.

- [ ] **Step 4: Run existing test suite (excluding deleted tests)**

Run: `pytest plugins/sqlseed-ai/tests/ -v --tb=short -q`
Expected: All non-LLM tests pass. LLM-dependent tests skip gracefully if no LM Studio.

- [ ] **Step 5: Run new pure-logic tests**

Run: `pytest plugins/sqlseed-ai/tests/healer/ -v`
Expected: All pass (ContextWindowDetector: 6, FailureClassifier: 8, Level2 context builder: 7).

- [ ] **Step 6: Run core tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: All pass.

- [ ] **Step 7: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore: lint + format fixes for 4-level heal architecture"
```

(Skip if no fixes needed.)

---

## Task 15: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `plugins/sqlseed-ai/README.md`

- [ ] **Step 1: Update CLAUDE.md v4 Layer 4 section**

In `CLAUDE.md`, find the "v4 Contract-Driven Self-Healing (sqlseed-ai)" section, Layer 4 description. Update the `healer/` description to reflect the 4-level architecture:

Replace references to `Layer4Coordinator` and `LLMHealer` with the new components. Specifically, update the Layer 4 bullet to describe:
- `HealOrchestrator` (coordinates 4-level degradation)
- `ContextWindowDetector` (dynamic context window detection)
- `FailureClassifier` (6 failure types: CONTEXT_OVERFLOW, EMPTY_RESPONSE, JSON_FORMAT, SEMANTIC, NETWORK, UNKNOWN)
- `Level1SubgraphHealer` (subgraph-level, default)
- `Level2ColumnHealer` (column-level + complete dependency set, info boundary optimization)
- `Level3CompactHealer` (compact/ultra-compact prompt + JSON repair)
- `ProgressiveDegrader` (deterministic fallback, unchanged)

Mention that `Layer4Coordinator` and `LLMHealer` were deleted (replaced by the 4-level architecture).

- [ ] **Step 2: Update plugins/sqlseed-ai/README.md**

Update any references to the heal architecture in the AI plugin README.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md plugins/sqlseed-ai/README.md
git commit -m "docs: update CLAUDE.md + README for 4-level heal architecture"
```

---

## Task 16: CI-equivalent validation

**Files:** None (verification only)

Run the full CI-equivalent validation per `ci.yml`:

- [ ] **Step 1: Lint**

Run: `ruff check src/ tests/ plugins/`
Expected: PASS

- [ ] **Step 2: Format check**

Run: `ruff format --check src/ tests/ plugins/`
Expected: PASS

- [ ] **Step 3: Type check**

Run: `mypy`
Expected: PASS

- [ ] **Step 4: Core tests with coverage**

Run: `pytest --cov=sqlseed --cov=sqlseed_ai --cov-report=term-missing --tb=short -q`
Expected: All pass (3 skipped for unconfigured API keys is OK)

- [ ] **Step 5: Property tests**

Run: `pytest plugins/sqlseed-ai/tests/property/ -v --maxfail=1 --tb=short`
Expected: PASS

- [ ] **Step 6: Integration tests (if Docker available)**

Run: `pytest tests/integration/ -v --tb=short`
Expected: PASS (or skip if no Docker)

If all pass, proceed to Loop Engineering. If any fail, fix before continuing.

---

## Task 17: Loop Engineering Phase 1 — Single Database Convergence

**Goal:** Select 1 complex database, run ai-analyze → fill → verify loop until 0 issues.

- [ ] **Step 1: Generate a complex database**

Create a new SQLite database with meaningful business logic and constraint complexity. The database must cover the complexity checklist:
- Self-referencing FK
- Composite PK
- Cross-column CHECK
- Arithmetic equality CHECK
- Single-column CHECK (BETWEEN/IN/LENGTH)
- UNIQUE (including text column)
- DEFAULT values
- AUTOINCREMENT PK
- NOT NULL
- Multi-table FK chain

Verify the database schema is self-consistent (no conflicting constraints).

- [ ] **Step 2: Run ai-analyze with local LM Studio (small model)**

```bash
sqlseed ai-analyze --db <db_path> --model <local_model>
```

Observe the verbose logging (Step 1-6, per-subgraph violations, Layer 3/4 results, degraded columns).

- [ ] **Step 3: Run fill**

```bash
sqlseed fill --config <generated_yaml>
```

- [ ] **Step 4: Verify constraints**

Check:
- FK integrity (no orphaned rows)
- CHECK constraints (all pass)
- UNIQUE constraints (no duplicates)
- Composite PK uniqueness
- Row counts match expected

- [ ] **Step 5: If issues found, fix CODE (not YAML)**

Per Loop Engineering methodology: observe logs/YAML → diagnose root cause in code → fix code → re-run. Do NOT manually patch YAML.

- [ ] **Step 6: Clean up temporary files**

Delete the database, YAML, logs after each round.

- [ ] **Step 7: Repeat until 0 issues**

Continue rounds until ai-analyze → fill → verify produces 0 violations. Then proceed to Phase 2.

- [ ] **Step 8: Run pytest after code fixes**

Run: `pytest plugins/sqlseed-ai/tests/ tests/ -v --tb=short -q`
Expected: All pass

- [ ] **Step 9: Commit code fixes (if any)**

```bash
git add <fixed source files>
git commit -m "fix(ai/healer): <root cause description>"
```

---

## Task 18: Loop Engineering Phase 2 — Stability Validation (same DB, 2 retries)

**Goal:** Same database runs 2 more times without issues.

- [ ] **Step 1: Retry 1**

Recreate the same database → ai-analyze → fill → verify.
Expected: 0 issues.

- [ ] **Step 2: Retry 2**

Recreate the same database → ai-analyze → fill → verify.
Expected: 0 issues.

- [ ] **Step 3: If any failure, return to Phase 1**

If either retry fails, return to Task 17 to continue fixing code.

- [ ] **Step 4: Proceed to Phase 3**

If both retries pass, proceed to Task 19.

---

## Task 19: Loop Engineering Phase 3 — New Database Validation (2 different DBs)

**Goal:** Generate 2 new databases with different business scenarios, each completing Phase 1 + Phase 2.

- [ ] **Step 1: Generate new database A (different business scenario)**

Choose a different domain (e.g., hospital, library, HR). Verify schema self-consistency and complexity checklist coverage.

- [ ] **Step 2: Database A — Phase 1 (convergence)**

Run ai-analyze → fill → verify loop until 0 issues. Fix code as needed.

- [ ] **Step 3: Database A — Phase 2 (stability, 2 retries)**

Run 2 more times. Both must pass.

- [ ] **Step 4: Generate new database B (another different scenario)**

Choose yet another domain. Verify schema.

- [ ] **Step 5: Database B — Phase 1 (convergence)**

Run ai-analyze → fill → verify loop until 0 issues. Fix code as needed.

- [ ] **Step 6: Database B — Phase 2 (stability, 2 retries)**

Run 2 more times. Both must pass.

- [ ] **Step 7: Final CI validation**

Run: `ruff check src/ tests/ plugins/ && ruff format --check src/ tests/ plugins/ && mypy && pytest --cov=sqlseed --cov=sqlseed_ai --tb=short -q`
Expected: All pass

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat(ai/healer): 4-level heal architecture complete (Loop Engineering 3-phase converged)"
```

---

## Task 20: Dual-model validation (OpenRouter large model)

**Goal:** Validate the 4-level architecture with a large model (OpenRouter free tier) in addition to the local small model (LM Studio) used in Tasks 17-19.

- [ ] **Step 1: Configure OpenRouter**

Set environment variables for OpenRouter:
```bash
set SQLSEED_AI_API_KEY=<openrouter_key>
set SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1
set SQLSEED_AI_MODEL=<free_large_model>
```

- [ ] **Step 2: Run ai-analyze → fill → verify on one database**

Use one of the databases from Tasks 17-19. The large model should handle Level 1 (subgraph-level) more easily due to larger context window.

- [ ] **Step 3: Verify constraints**

Check FK/CHECK/UNIQUE integrity.

- [ ] **Step 4: If issues found, fix CODE**

Per Loop Engineering: observe → diagnose → fix code → re-run.

- [ ] **Step 5: Commit fixes (if any)**

```bash
git add <fixed files>
git commit -m "fix(ai/healer): <root cause> (found via large-model validation)"
```

---

## Task 21: Deterministic Fallback Semantic Gap Fix (Post-Implementation Blind Spot)

**Goal:** Fix a design blind spot discovered during data quality validation: `_build_subgraph_config()` Step 4 used `_placeholder_generator()` (type-only lookup) instead of the Core `ColumnMapper` (9-level strategy chain with 76 exact match rules + 29 pattern rules), causing all TEXT columns without CHECK constraints to receive `generator: string` (random gibberish) regardless of column name semantics.

### Background

The spec (Section 3.8) states `_build_subgraph_config` retains its "CHECK inference logic". However, the spec did not specify the fallback behavior for columns WITHOUT CHECK/UNIQUE constraints. The implementation used `_placeholder_generator(col_type)` which only checks column TYPE:

```python
def _placeholder_generator(col_type: str) -> str:
    t = col_type.upper()
    if any(k in t for k in ("INT", ...)): return "integer"
    if any(k in t for k in ("REAL", ...)): return "float"
    if any(k in t for k in ("DATETIME", ...)): return "datetime"
    if "BOOLEAN" in t: return "boolean"
    return "string"  # ALL TEXT columns → string, ignoring name semantics
```

This meant columns like `email`, `username`, `avatar_url`, `title`, `description`, `content`, `bio`, `phone`, `name` all received `generator: string` (random alphanumeric gibberish), even though the Core `ColumnMapper` has exact match rules mapping these names to semantic generators (`email`→email, `username`→username, `avatar_url`→url, `title`→sentence, etc.).

### Why the LLM Didn't Fix It

The `ProgressiveDegrader` (Layer 4) is designed to "fall back to Core 9-level mapper when LLM fails". However, this only triggers on LLM failure. For 11/12 tables in the R5 education database, the deterministic inference produced 0 violations → "accepted as-is" → **no LLM call** → Core `ColumnMapper` never ran. The LLM was never consulted for these columns, so it never had a chance to correct the generator choice.

### Root Cause

The architectural gap is in the data flow:

```
_build_subgraph_config()
  ├─ Step 1: _infer_cross_column_config()  → cross-column CHECK (derive_from)
  ├─ Step 2: _infer_from_check_constraints() → single-column CHECK (enum/range)
  ├─ Step 3: _infer_unique_column_config() → UNIQUE columns (template/email)
  └─ Step 4: _placeholder_generator(col_type) → ❌ type-only, ignores name
                                            → Core ColumnMapper bypassed

→ validator: 0 violations (string doesn't violate CHECK)
→ "accepted as-is" → LLM never called
→ fill uses string → random gibberish for email/url/username/etc.
```

### Fix

Step 4 now delegates to the Core `ColumnMapper.map_column()` instead of `_placeholder_generator()`:

```python
from sqlseed.core.mapper import ColumnMapper
from sqlseed.database._protocol import ColumnInfo

@lru_cache(maxsize=1)
def _get_column_mapper() -> ColumnMapper:
    return ColumnMapper()

# Step 4: Delegate to Core ColumnMapper for semantic name matching.
col_info = ColumnInfo(
    name=col_name, type=col_type,
    nullable=True, default=None,
    is_primary_key=False, is_autoincrement=False,
)
spec = _get_column_mapper().map_column(col_info)
gen_name = spec.generator_name
gen_params = dict(spec.params)
if gen_name == "skip":
    gen_name = _placeholder_generator(col_type)
    gen_params = {}
if gen_name == "string" and _is_date_column(col_name):
    gen_name = "datetime"
```

This reuses the Core's 76 exact match rules (L3) + 29 pattern rules (L5) for semantic column name matching, correctly mapping `email`→email, `avatar_url`→url, `title`→sentence, `content`→text, etc.

### Files

- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — Step 4 delegation
- Modify: `plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py` — 13 new tests

### Steps

- [x] **Step 1: Add ColumnMapper import + _get_column_mapper() lazy singleton**
- [x] **Step 2: Replace Step 4 fallback with ColumnMapper.map_column() delegation**
- [x] **Step 3: Handle "skip" return (PK autoincrement) → fall back to _placeholder_generator**
- [x] **Step 4: Preserve _is_date_column() as additional fallback**
- [x] **Step 5: Add 13 unit tests (email/username/avatar_url/phone/name/bio/title/description/content/website/created_at + 2 string fallbacks)**
- [x] **Step 6: Run ruff + mypy + full test suite (51 orchestrator tests + 14 architecture + 17 doc_sync = 82 pass)**
- [ ] **Step 7: Re-run R5 education DB to verify end-to-end data quality improvement**
- [ ] **Step 8: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py \
      plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py
git commit -m "fix(ai/auto_heal): Step 4 delegates to Core ColumnMapper for semantic name matching

Design blind spot: _build_subgraph_config Step 4 used _placeholder_generator
(type-only lookup) for columns without CHECK/UNIQUE constraints, returning
'string' for ALL TEXT columns. This bypassed the Core ColumnMapper's 76 exact
match rules + 29 pattern rules, producing random gibberish for email, username,
avatar_url, title, description, content, bio, phone, name columns.

The LLM was never consulted for these columns because 11/12 tables had 0
violations and were 'accepted as-is' (no LLM call). The ProgressiveDegrader
(which uses Core ColumnMapper) only triggers on LLM failure, not on
'accepted as-is' configs.

Fix: Step 4 now constructs a ColumnInfo and calls ColumnMapper.map_column()
to get a GeneratorSpec with semantic generator + params. Handles 'skip'
return (PK autoincrement) and preserves _is_date_column() fallback.

13 new unit tests verify email/username/avatar_url/phone/name/bio/title/
description/content/website/created_at columns get correct semantic
generators instead of 'string'."
```

### Spec Update

This fix supplements the spec (Section 3.8) as follows:

| Component | Spec Before | Spec After |
|-----------|-------------|------------|
| `_build_subgraph_config` Step 4 | "type-based placeholder fallback" | "delegates to Core `ColumnMapper.map_column()` for semantic column name matching (76 exact rules + 29 pattern rules); falls back to `_placeholder_generator()` only for 'skip' returns" |

---

## Task 22: Deterministic Fallback Semantic Gap — Comprehensive Blind Spot Audit

**Goal:** Audit ALL deterministic fallback paths in `auto_heal/orchestrator.py` that use `_placeholder_generator()` and ensure they delegate to Core `ColumnMapper` for semantic name matching. Task 21 fixed Step 4 in `_build_subgraph_config()`; this task fixes the remaining instances and documents known limitations.

### Background

The spec (Section 3.8) states `_build_subgraph_config` retains its "CHECK inference logic". Task 21 discovered that Step 4's fallback used `_placeholder_generator()` (type-only), bypassing Core `ColumnMapper`. A comprehensive audit of ALL `_placeholder_generator()` call sites revealed **3 categories** of blind spots:

### Blind Spot Inventory

| # | Location | Code | Status | Severity |
|---|----------|------|--------|----------|
| 1 | `_build_subgraph_config` Step 4 (line ~465) | `gen = _placeholder_generator(col_type)` | **Fixed** (Task 21) | High — affects ALL unconstrained columns when LLM not called |
| 2 | Step 5.5 post-LLM safety net (line ~259) | `gen = _placeholder_generator(col_type)` | **Fixed** (Task 22) | Medium — affects columns where LLM stripped the generator field |
| 3 | `_infer_cross_column_config` Pattern 4 (line ~1211) | `"generator": _placeholder_generator(col_type)` + `null_ratio: 1.0` | **Known limitation** (documented) | Low — `null_ratio: 1.0` means always NULL, generator is moot |
| 4 | `_infer_cross_column_config` Pattern 5 (line ~1225) | `"generator": _placeholder_generator(col_type)` + `null_ratio: 1.0` | **Known limitation** (documented) | Low — `null_ratio: 1.0` means always NULL, generator is moot |

### Root Cause Analysis

**Blind Spot 1 (Step 4) + Blind Spot 2 (Step 5.5) — Same root cause:**

Both paths use `_placeholder_generator(col_type)` which only checks column TYPE:
```python
def _placeholder_generator(col_type: str) -> str:
    t = col_type.upper()
    if any(k in t for k in ("INT", ...)): return "integer"
    if any(k in t for k in ("REAL", ...)): return "float"
    ...
    return "string"  # ALL TEXT columns → string, ignoring name semantics
```

This bypasses the Core `ColumnMapper`'s 9-level strategy chain (76 exact match rules + 29 pattern rules), producing `generator: string` (random gibberish) for semantically-named TEXT columns like `email`, `username`, `avatar_url`, `title`, `description`, `content`, `bio`, `phone`, `name`.

**Blind Spot 1 (Step 4) is higher severity** because it triggers when the LLM is never consulted (0 violations → "accepted as-is" → no LLM call). The user observed this from generation speed: "if it had gone through LLM analysis it wouldn't be that fast".

**Blind Spot 2 (Step 5.5) is medium severity** because it triggers after the LLM WAS called but stripped the generator field. The LLM had a chance to set the correct generator but failed to do so. The safety net then falls back to `_placeholder_generator()` — same dumb type-only lookup.

**Blind Spots 3 + 4 (Pattern 4/5) are known limitations** because `null_ratio: 1.0` means the column is always NULL. The generator choice is moot — no data is ever generated using it. These patterns handle `col IS NULL OR col = expr` (computed column with NULL escape) and `col IS NULL OR other_col = 'value'` (conditional NULL). A future enhancement could parse the RHS expression for Pattern 4 (computed columns) to produce real values instead of always-NULL, but that is a separate feature, not a semantic-matching blind spot.

### Fix for Blind Spot 2

Step 5.5's missing-generator inference now delegates to `ColumnMapper.map_column()` (same fix as Task 21 Step 4):

```python
# Before (blind spot):
elif meta and col_name in meta.columns:
    col_type = meta.column_types.get(col_name, "TEXT")
    gen = _placeholder_generator(col_type)
    if gen == "string" and _is_date_column(col_name):
        gen = "datetime"

# After (fixed):
elif meta and col_name in meta.columns:
    col_type = meta.column_types.get(col_name, "TEXT")
    col_info = ColumnInfo(
        name=col_name, type=col_type,
        nullable=True, default=None,
        is_primary_key=False, is_autoincrement=False,
    )
    spec = _get_column_mapper().map_column(col_info)
    gen = spec.generator_name
    if gen == "skip":
        gen = _placeholder_generator(col_type)
    if gen == "string" and _is_date_column(col_name):
        gen = "datetime"
```

### Files

- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — Step 5.5 delegation (line ~257-282)
- Modify: `plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py` — 7 new Step 5.5 tests

### Steps

- [x] **Step 1: Audit all `_placeholder_generator()` call sites in orchestrator.py**
- [x] **Step 2: Fix Blind Spot 2 (Step 5.5 post-LLM safety net) — delegate to ColumnMapper**
- [x] **Step 3: Add 7 unit tests for Step 5.5 (email/username/avatar_url/title/content/created_at/unknown_text)**
- [x] **Step 4: Document Blind Spots 3+4 as known limitations (null_ratio: 1.0 makes generator moot)**
- [x] **Step 5: Run ruff + mypy + full test suite (58 orchestrator + 31 arch/doc_sync = 89 pass)**
- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py \
      plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py
git commit -m "fix(ai/auto_heal): Step 5.5 safety net also delegates to Core ColumnMapper

Comprehensive audit of all _placeholder_generator() call sites revealed
the same semantic-matching blind spot existed in TWO places, not one:

  1. Step 4 in _build_subgraph_config (fixed in Task 21)
  2. Step 5.5 post-LLM safety net (fixed in this commit)

Both used _placeholder_generator(col_type) which returns 'string' for ALL
TEXT columns, ignoring column name semantics. Step 5.5 triggers when the
LLM strips the generator field — the safety net then fell back to the
same dumb type-only lookup, producing random gibberish for email,
username, avatar_url, title, content even after the LLM was called.

Fix: Step 5.5 now constructs a ColumnInfo and calls
ColumnMapper.map_column() to get a GeneratorSpec with semantic generator
+ params (same pattern as Task 21 Step 4).

Also documents Blind Spots 3+4 (_infer_cross_column_config Pattern 4/5)
as known limitations: these use _placeholder_generator with
null_ratio=1.0 (always NULL), so the generator choice is moot.

7 new unit tests verify Step 5.5 fills in correct semantic generators
(email/username/url/sentence/text/datetime) when the LLM strips them."
```

### Spec Update

This fix supplements the spec (Section 3.8 + Section 4.1 data flow) as follows:

| Component | Spec Before | Spec After |
|-----------|-------------|------------|
| `_build_subgraph_config` Step 4 | "type-based placeholder fallback" | "delegates to Core `ColumnMapper.map_column()` for semantic column name matching (76 exact rules + 29 pattern rules); falls back to `_placeholder_generator()` only for 'skip' returns" |
| Step 5.5 missing-generator inference | "fall back to type-based placeholder" | "delegates to Core `ColumnMapper.map_column()` for semantic name matching (same as Step 4); falls back to `_placeholder_generator()` only for 'skip' returns" |
| `_infer_cross_column_config` Pattern 4/5 | (not documented) | "returns `_placeholder_generator(col_type)` with `null_ratio: 1.0` — generator is moot because column is always NULL; future enhancement could parse the RHS expression for Pattern 4 to produce real computed values" |

---

## Task 23: Round 5 Education Domain — Three Blind Spots Fixed (Pattern 8 + Step 5.5 template + Self-ref FK)

**Goal:** Fix three blind spots discovered during Round 5 (online education platform, 12 tables) convergence testing. All three were found via the Loop Engineering methodology (observe → diagnose → fix CODE → re-validate).

### Background

Round 5 used a 12-table education database (users, categories, courses, lessons, enrollments, lesson_progress, orders, coupons, payments, reviews, certificates, instructor_profiles) with complex CHECK constraints (conditional equality, date ordering, cross-column arithmetic, self-referencing FK). The first ai-analyze + fill run produced 10/12 tables (users + coupons failed), and after fixing those, a third table (categories) had 999 FK violations from a self-referencing FK.

### Blind Spot 1: Pattern 8 INTEGER expression producing negative values

**Root cause:** Pattern 8 (`col <= other_col`) for INTEGER columns used the expression `value - random_int(0, 100)`. When `value` (the derived-from column) was less than 100, this produced negative results, violating companion CHECK constraints like `col >= 0`.

**Example:** `coupons.used_count <= total_count` with `total_count = 7` produced `used_count = 7 - random_int(0, 100) = -93`, violating `CHECK (used_count >= 0)`.

**Fix:** Changed the expression to `random_int(0, value)` which guarantees `0 <= result <= value`, satisfying both `col <= other_col` AND `col >= 0`.

**Location:** `_infer_cross_column_config()` Pattern 8, line ~1411

### Blind Spot 2: Step 5.5 missing template param

**Root cause:** The LLM sometimes returns `generator: template` with `params: {}` (missing the `template` string field). Without a template string, the template generator raises `KeyError` at fill time, causing the entire table to fail (0 rows generated).

**Example:** `users.user_code` had `generator: template, params: {}` → KeyError → 0 rows for users table.

**Fix:** Step 5.5 now detects `generator: template` with missing `template` param and fills in a default template using the column name prefix: `{PREFIX}-{sequence:04d}` (e.g., `USER_COD-{sequence:04d}` for `user_code`).

**Location:** Step 5.5 safety net, line ~244-254

### Blind Spot 3: Self-referencing FK not detected

**Root cause:** `_build_subgraph_config()` did not detect self-referencing FK columns (where `fk.ref_table == current_table`). The `foreign_key_or_integer` generator tried to sample from the parent table's SharedPool, but since the parent table IS the current table (being filled for the first time), the SharedPool was empty — the generator fell back to random integers that don't match any existing PK, causing FK violations.

**Example:** `categories.parent_id → categories.id` produced `parent_id = 665178` (random integer), but valid category IDs are 1-1000 → 999 FK violations.

**Fix:** Added Step 0 in `_build_subgraph_config()`: detect self-referencing FK columns (where `fk.get("ref_table") == table_name`) and set `null_ratio: 1.0` to ensure all values are NULL. This is the only safe option during initial bulk fill because the parent table has no rows at fill time.

**Location:** `_build_subgraph_config()` Step 0, line ~409-439

### Files

- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — Pattern 8 fix + Step 5.5 template fix + Step 0 self-ref FK detection
- Modify: `plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py` — 8 new tests (3 Pattern 8 + 3 Step 5.5 template + 2 Step 0 self-ref FK)

### Steps

- [x] **Step 1: Fix Pattern 8 INTEGER expression** (`value - random_int(0, 100)` → `random_int(0, value)`)
- [x] **Step 2: Fix Step 5.5 missing template param** (auto-fill default template from column name prefix)
- [x] **Step 3: Add Step 0 self-referencing FK detection** (`null_ratio: 1.0` for self-ref FK columns)
- [x] **Step 4: Add 8 unit tests** (3 Pattern 8 + 3 Step 5.5 template + 2 Step 0 self-ref FK)
- [x] **Step 5: Run ruff + mypy + full test suite** (97 tests pass: 66 orchestrator + 31 arch/doc_sync)
- [x] **Step 6: Re-run R5 ai-analyze + fill** (12/12 tables, 12000 rows, 0 violations)
- [x] **Step 7: Auto-check data quality** (FK/CHECK/UNIQUE all pass, semantic generators verified)
- [ ] **Step 8: Commit**

### Convergence Curve

| Run | Tables | Rows | FK Violations | CHECK Violations | Issue |
|-----|--------|------|---------------|------------------|-------|
| v3 | 10/12 | 10000 | 0 | 0 | users (missing template) + coupons (negative used_count) |
| v4 | 12/12 | 12000 | 999 | 0 | categories self-ref FK |
| v5 | 12/12 | 12000 | 0 | 0 | ALL PASSED ✓ |

### Spec Update

| Component | Spec Before | Spec After |
|-----------|-------------|------------|
| Pattern 8 INTEGER | `value - random_int(0, 100)` | `random_int(0, value)` — guarantees `0 <= result <= value` |
| Step 5.5 template | (not documented) | Detects `generator: template` with missing `template` param, fills default `{PREFIX}-{sequence:04d}` from column name |
| `_build_subgraph_config` Step 0 | (did not exist) | Detects self-referencing FK columns (`fk.ref_table == table_name`), sets `null_ratio: 1.0` to avoid FK violations during initial bulk fill |

---

## Task 24: Phone+LENGTH CHECK Architecture Audit — Three Systemic Blind Spots Fixed

**Goal:** Fix three systemic blind spots in the 4-Level Heal architecture that caused `users.phone` (with `CHECK (phone IS NULL OR LENGTH(phone) = 11)`) to generate alphanumeric gibberish instead of phone-like digits. The audit confirmed the architecture design is sound — the issues were in the implementation layer (contract matrix rules, repair strategies, and degrader logic).

### Background

During Round 5 data quality review, `users.phone` was found to generate `string` (alphanumeric gibberish) with `_degraded: true, degrade_reason: llm_oscillation`. The LLM was called but oscillated between two conflicting goals: satisfying `LENGTH(phone) = 11` (needs `string` + length params) vs. semantic quality (needs `phone` or `pattern` generator). The architecture audit traced the complete data flow:

1. Step 2 (`_infer_from_check_constraints`) detected `LENGTH(phone) = 11` → returned `string` + `min_length=11, max_length=11` (structurally correct, semantically poor)
2. Validator contract matrix matched TWO rules: `semantic_upgrade` (specificity=2) won over `upgrade_phone_to_pattern` (specificity=3)
3. Layer 3 `_semantic_upgrade` changed `string` → `phone`, **dropped all params** (broke LENGTH CHECK)
4. Layer 3 `_upgrade_phone_to_pattern` SKIPPED (correctly detected LENGTH CHECK)
5. Layer 4 LLM oscillated between `string+length` and `phone` (unresolvable conflict)
6. ProgressiveDegrader kept the oscillated LLM output (did not restore original deterministic config)

### Blind Spot 1: `_semantic_upgrade` unconditionally drops params

**Root cause:** `_semantic_upgrade` in `strategies.py` called `new_col.pop("params", None)` unconditionally, dropping ALL params including `min_length`/`max_length` from CHECK constraint inference. When upgrading `string` → `phone` for a column with `LENGTH(phone) = 11`, the `phone` generator produces variable-length output (NANP format is 14 chars), violating the LENGTH CHECK.

**Fix:** When upgrading `string` → `phone` and the column has a `LENGTH(col) = N` CHECK constraint, upgrade to `pattern` with `[0-9]{N}` instead of `phone`. This satisfies both the semantic requirement (digits-only, phone-like) and the LENGTH CHECK (exact N). Added `_extract_length_check()` helper to detect LENGTH constraints (including `col IS NULL OR` prefix stripping).

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py` — `_semantic_upgrade()` + new `_extract_length_check()` helper

### Blind Spot 2: Step 2 source — phone-like + LENGTH → string (triggers contract matrix conflict)

**Root cause:** Step 2 (`_infer_from_check_constraints`) detected `LENGTH(phone) = 11` and returned `string` + `min_length=11, max_length=11`. This triggered the contract matrix's `string` on `phone` → `semantic_upgrade` rule (specificity=2), which then dropped the length params and caused the LLM oscillation chain.

**Fix:** In `_build_subgraph_config`, after Step 2 returns `string` + `min_length=N, max_length=N` for a phone-like column, override to `pattern` with `[0-9]{N}` regex. This prevents the `string` config from being generated at the source, avoiding the contract matrix conflict entirely. The existing UNIQUE + LENGTH override (line 472-487) served as the template for this fix.

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — `_build_subgraph_config()` Step 2, after UNIQUE+LENGTH check

### Blind Spot 3: ProgressiveDegrader keeps oscillated LLM output

**Root cause:** `HealOrchestrator._degrade_and_return()` passed `current_config` (which may contain oscillated LLM output) to `ProgressiveDegrader.degrade()`. The degrader's comment said "Keep generator/params from `_build_subgraph_config`", but the actual config was the LLM's last oscillated output, not the original deterministic inference. This meant the degraded config could have lost CHECK-constraint params.

**Fix:** Added `original_config` parameter to `_degrade_and_return()`. Before calling `ProgressiveDegrader.degrade()`, the new `_restore_failed_columns()` static method restores failed columns' `generator`/`params`/`derive_from`/`expression` from the original deterministic config. Non-failed columns are left unchanged (preserving any successful LLM patches).

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py` — `heal()` + `_degrade_and_return()` + new `_restore_failed_columns()` static method

### Architecture Conclusion

**The 4-Level Heal architecture design itself is sound** — the spec Section 4.1 data flow (deterministic inference → validate → rule repair → LLM 4-level degradation) is correct. The three blind spots were implementation-layer issues:

1. `_semantic_upgrade` had a blanket `pop("params")` that didn't account for CHECK constraints
2. Step 2 didn't detect phone-like columns, producing `string` configs that triggered contract matrix conflicts
3. ProgressiveDegrader trusted the `current_config` without verifying it was the original deterministic output

### Files

- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py` — `_semantic_upgrade` phone+LENGTH fix + `_extract_length_check` helper
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — Step 2 phone-like+LENGTH override + `_is_phone_like` import
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py` — `heal()` original_config + `_degrade_and_return` signature + `_restore_failed_columns` static method
- Modify: `plugins/sqlseed-ai/tests/test_repair_strategies.py` — 3 new tests (phone+LENGTH→pattern, phone without LENGTH→phone, email still drops params)
- Modify: `plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py` — 6 new tests (3 Step 2 phone+LENGTH + 3 _restore_failed_columns)

### Steps

- [x] **Step 1: Architecture audit** — traced complete data flow for `users.phone`, confirmed 3 systemic blind spots
- [x] **Step 2: Fix Blind Spot 1** — `_semantic_upgrade` phone+LENGTH → pattern with `[0-9]{N}`
- [x] **Step 3: Fix Blind Spot 2** — Step 2 source fix, phone-like + LENGTH → pattern (avoids contract matrix conflict)
- [x] **Step 4: Fix Blind Spot 3** — ProgressiveDegrader restores original deterministic config for failed columns
- [x] **Step 5: Add 9 unit tests** (3 repair strategies + 3 Step 2 phone+LENGTH + 3 _restore_failed_columns)
- [x] **Step 6: Run ruff + mypy + full AI plugin test suite** (598 passed, 3 skipped, 0 failed)

### Validation Results

- **ruff check**: All checks passed
- **mypy strict**: Success, no issues found in 3 source files
- **pytest**: 598 passed, 3 skipped (MCP API key tests), 0 failed
- **New tests**: 9 new tests all pass (3 `_semantic_upgrade` + 3 Step 2 phone+LENGTH + 3 `_restore_failed_columns`)

---

## Success Criteria

- [ ] All pure-logic unit tests pass (ContextWindowDetector, FailureClassifier, Level2 context builder)
- [ ] LLM-dependent tests pass or skip gracefully
- [ ] `ruff check` + `ruff format --check` + `mypy` all pass
- [ ] `pytest --cov=sqlseed --cov=sqlseed_ai` passes
- [ ] Property tests pass
- [ ] Integration tests pass (or skip if no Docker)
- [ ] Loop Engineering 3-phase convergence complete:
  - Phase 1: Single database 0 issues
  - Phase 2: Same database 2 retries stable
  - Phase 3: 2 new databases each complete Phase 1 + Phase 2
- [ ] Dual-model validation (OpenRouter large + LM Studio small) both work
- [ ] Documentation updated (CLAUDE.md, README.md)
- [ ] No dead code (`llm_healer.py`, `coordinator.py` fully removed)
- [ ] No mock LLM tests (self-proving trap avoided)
