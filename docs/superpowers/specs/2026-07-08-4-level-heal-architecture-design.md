# 4-Level Heal Architecture Design

**Date:** 2026-07-08
**Status:** Design
**Branch:** `feat/contract-driven-self-healing`
**Supersedes:** Current `Layer4Coordinator` + `LLMHealer` architecture

## 1. Overview

### 1.1 Problem Statement

The current LLM heal architecture in `sqlseed-ai` has two critical issues:

1. **Missing intermediate layer**: The current degradation path jumps from subgraph-level LLM calls directly to `ProgressiveDegrader` (deterministic fallback), skipping a column-level retry layer that could rescue LLM failures with minimal dependency context.

2. **Mixed concerns**: The current `LLMHealer` conflates internal algorithm (information boundary optimization) with external fault tolerance (prompt compression). When LLM fails, there is no failure-type-aware routing — all failures are retried identically or degraded.

### 1.2 Design Goals

1. **Internal algorithm vs external fault tolerance separation**: Level 1/2 optimize information boundaries (internal), Level 3 compresses prompts (external), Level 4 provides deterministic fallback.
2. **Failure-type-aware routing**: Different LLM failure types (context overflow, empty response, JSON format error, semantic error, network error) trigger different degradation paths.
3. **Pre-judgment + post-failure hybrid triggering**: Dynamically detect model context window size and pre-judge whether to skip Level 1.
4. **Aggressive refactoring**: Delete `Layer4Coordinator` and `LLMHealer`, rebuild as 4 independent healers + failure classifier + context detector. No backward compatibility constraints.
5. **Low maintenance cost**: Each component has a single responsibility, clear interfaces, independent testing.

### 1.3 Core Principle

> **Internal factors (code responsibility)**: Information boundary optimization, algorithm performance, degradation mechanism, validation mechanism.
> **External factors (caller responsibility)**: Network retry, model selection, empty response diagnosis.
>
> Large vs small model differences: only the sharding granularity differs, the internal algorithm is identical.

## 2. Architecture

### 2.1 4-Level Degradation Architecture

```
AutoHealOrchestrator._heal_subgraph()
  │
  ├─ Layer 3 Repair (deterministic rule repair, unchanged)
  │   ↓ still has violations
  │
  ├─ HealOrchestrator (new, replaces Layer4Coordinator)
  │   │
  │   ├─ ContextWindowDetector (new)
  │   │   └─ Dynamically detect model context window size
  │   │
  │   ├─ FailureClassifier (new)
  │   │   └─ Classify LLM failures: CONTEXT_OVERFLOW / EMPTY_RESPONSE / JSON_FORMAT / SEMANTIC / NETWORK
  │   │
  │   ├─ Level1SubgraphHealer (refactored from LLMHealer)
  │   │   └─ Subgraph-level LLM call, sends entire subgraph info
  │   │
  │   ├─ Level2ColumnHealer (new)
  │   │   └─ Column-level LLM call, sends only target column + complete dependency set
  │   │
  │   ├─ Level3CompactHealer (new)
  │   │   └─ compact/ultra-compact prompt LLM call, reduces redundancy + JSON repair
  │   │
  │   └─ ProgressiveDegrader (unchanged)
  │       └─ Deterministic degradation, CHECK inference + Core mapper
  │
  └─ Output repaired config
```

### 2.2 Degradation Paths

**Pre-judgment (before Level 1):**
```
token_estimate > 60% context_window → skip Level 1, go directly to Level 2
token_estimate ≤ 60% context_window → Level 1
```

**Post-failure routing (after Level 1 failure):**
```
CONTEXT_OVERFLOW / EMPTY_RESPONSE → Level 2 → Level 3 → Level 4
JSON_FORMAT → Level 3 → Level 4 (skip Level 2)
SEMANTIC → Level 4 (skip Level 2/3)
NETWORK → raise exception (not in degradation chain)
```

**Post-failure routing (after Level 2 failure):**
```
CONTEXT_OVERFLOW → Level 3
Other failures → Level 4
```

**Post-failure routing (after Level 3 failure):**
```
Any failure → Level 4
```

### 2.3 Relationship with Existing Architecture

| Existing Component | Treatment |
|-------------------|-----------|
| `Layer4Coordinator` | **Delete**, replace with `HealOrchestrator` |
| `LLMHealer` | **Refactor**, split into `Level1SubgraphHealer` + `Level3CompactHealer` |
| `ProgressiveDegrader` | **Unchanged**, already best practice |
| `SubgraphSplitter` | **Unchanged**, Tarjan SCC algorithm optimal |
| `OscillationDetector` | **Migrate** to `HealOrchestrator` |
| `DiffLearner` | **Unchanged**, learning mechanism retained |

## 3. Component Design

### 3.1 HealOrchestrator (new)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py`

**Responsibility:** Coordinate 4-level degradation, route by failure type.

**Core interface:**
```python
class HealOrchestrator:
    def __init__(
        self,
        snapshot: SchemaSnapshot,
        context_detector: ContextWindowDetector,
        failure_classifier: FailureClassifier,
        level1: Level1SubgraphHealer,
        level2: Level2ColumnHealer,
        level3: Level3CompactHealer,
        degrader: ProgressiveDegrader,
    ) -> None: ...

    def heal(
        self,
        table_name: str,
        violations: list[ViolationReport],
        config: dict[str, Any],
    ) -> HealResult:
        """Main entry: orchestrate 4-level degradation based on failure type."""
```

**Core logic:**
1. Pre-judge: call `ContextWindowDetector.estimate_tokens()`, skip Level 1 if > 60% context window.
2. Call Level 1 → on failure → `FailureClassifier.classify()` → route by type.
3. Each level failure decides next level (per Section 2.2 degradation paths).
4. Return `HealResult` (including per-level attempt records).

### 3.2 ContextWindowDetector (new)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/context_detector.py`

**Responsibility:** Dynamically detect model context window size, estimate prompt token count.

**Detection priority:**
1. `AIConfig.max_context_tokens` (user explicit configuration)
2. Model mapping table (common models: gemma-4-e2b=8192, gpt-4=8192, claude-3=200000, etc.)
3. Conservative default (4096)

**Core interface:**
```python
class ContextWindowDetector:
    def __init__(self, ai_config: AIConfig) -> None: ...

    def get_context_window(self) -> int:
        """Get model context window size (tokens)."""

    def estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt (rough: chars / 4)."""

    def should_skip_level1(self, subgraph_prompt: str) -> bool:
        """Pre-judge: return True if tokens > 60% of context window."""
```

### 3.3 FailureClassifier (new)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/failure_classifier.py`

**Responsibility:** Classify LLM failure types.

**Failure type enum:**
```python
class FailureType(Enum):
    CONTEXT_OVERFLOW = "context_overflow"    # Context overflow
    EMPTY_RESPONSE = "empty_response"        # Empty response
    JSON_FORMAT = "json_format"              # JSON format error
    SEMANTIC = "semantic"                    # Semantic error (validator rejected)
    NETWORK = "network"                      # Network/API error
    UNKNOWN = "unknown"                      # Unknown error
```

**Core interface:**
```python
class FailureClassifier:
    def classify(self, error: Exception, response: str | None) -> FailureType:
        """Classify LLM failure based on error type and response."""
```

**Classification rules:**
- `ContextOverflowError` / error message contains "context length" / "too long" → `CONTEXT_OVERFLOW`
- Response is empty or whitespace only → `EMPTY_RESPONSE`
- `JSONDecodeError` → `JSON_FORMAT`
- validator rejected (`ValidationResult.ok == False`) → `SEMANTIC`
- `APITimeoutError` / `APIConnectionError` / `RateLimitError` → `NETWORK`
- Other → `UNKNOWN` (treated as `SEMANTIC`)

### 3.4 Level1SubgraphHealer (refactored from LLMHealer)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py`

**Responsibility:** Subgraph-level LLM call, sends entire subgraph violations + config.

**Relationship with existing `LLMHealer`:** Extract core logic from `LLMHealer.heal()`, remove compact/ultra-compact related code.

**Core interface:**
```python
class Level1SubgraphHealer:
    def __init__(self, ai_config: AIConfig, client: APIClient) -> None: ...

    def heal(
        self,
        table_name: str,
        violations: list[ViolationReport],
        config: dict[str, Any],
    ) -> Level1Result:
        """Call LLM with full subgraph context. Raises on failure."""
```

### 3.5 Level2ColumnHealer (new)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py`

**Responsibility:** Column-level LLM call, sends only target column + complete dependency set.

**Information boundary (complete dependency set):**
1. Target column attributes: `name`, `type`, `nullable`, `default`, `UNIQUE`
2. All CHECK constraints the column participates in (including cross-column, full expressions)
3. `derive_from` source columns (if any): source column `name` + `type`
4. Downstream columns that `derive_from` this column (if any): downstream column `name` (prevent overwriting dependencies)
5. Cross-column CHECK related columns: e.g., `col_b` in `col_a > col_b` — `name` + `type`
6. FK relationship (if column is FK): referenced table + referenced column

**Core interface:**
```python
class Level2ColumnHealer:
    def __init__(self, ai_config: AIConfig, client: APIClient) -> None: ...

    def heal_column(
        self,
        table_name: str,
        column_name: str,
        violation: ViolationReport,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> Level2Result:
        """Call LLM with column-level minimal dependency info."""

    def _build_column_context(
        self,
        table_name: str,
        column_name: str,
        snapshot: SchemaSnapshot,
    ) -> ColumnContext:
        """Extract minimal dependency info for a column."""
```

### 3.6 Level3CompactHealer (new)

**Location:** `plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py`

**Responsibility:** compact/ultra-compact prompt LLM call, reduces redundancy + JSON repair.

**Two-tier compression:**
- `compact`: Reduce few-shot examples (from 3 to 1), simplify format instructions
- `ultra_compact`: Remove all few-shot, keep only JSON Schema, strengthen format requirements

**JSON repair:** Attempt `json-repair` library to fix minor format errors before failing.

**Core interface:**
```python
class Level3CompactHealer:
    def __init__(self, ai_config: AIConfig, client: APIClient) -> None: ...

    def heal_compact(
        self,
        table_name: str,
        violations: list[ViolationReport],
        config: dict[str, Any],
        mode: Literal["compact", "ultra_compact"],
    ) -> Level3Result:
        """Call LLM with compact prompt + JSON repair."""
```

### 3.7 Deleted Components

| Component | Reason |
|-----------|--------|
| `Layer4Coordinator` | Replaced by `HealOrchestrator` |
| `LLMHealer` | Split into `Level1SubgraphHealer` + `Level3CompactHealer` |
| `LLMHealer.build_prompt()` compact logic | Migrated to `Level3CompactHealer` |

### 3.8 Unchanged Components

| Component | Reason |
|-----------|--------|
| `ProgressiveDegrader` | Already best practice |
| `SubgraphSplitter` | Tarjan SCC algorithm optimal |
| `OscillationDetector` | Migrated to `HealOrchestrator`, logic unchanged |
| `DiffLearner` | Learning mechanism retained |
| `_build_subgraph_config` | CHECK inference logic retained |

### 3.9 File Structure

```
plugins/sqlseed-ai/src/sqlseed_ai/healer/
├── __init__.py
├── orchestrator.py            # New: HealOrchestrator
├── context_detector.py        # New: ContextWindowDetector
├── failure_classifier.py      # New: FailureClassifier
├── level1_subgraph_healer.py  # New (refactored from llm_healer.py)
├── level2_column_healer.py    # New
├── level3_compact_healer.py   # New
├── degrader.py                # Unchanged
├── subgraph.py                # Unchanged
├── oscillation.py             # Unchanged (called by orchestrator)
├── post_repair.py             # Unchanged
├── diff_learner.py            # Unchanged
├── models.py                  # Extended: new HealResult, Level1Result, etc.
└── llm_healer.py              # Deleted
```

## 4. Data Flow

### 4.1 Complete Data Flow (Happy Path)

```
AutoHealOrchestrator.run()
  │
  ├─ SchemaSnapshot creation
  ├─ SubgraphSplitter splitting (unchanged)
  │
  └─ For each subgraph, call _heal_subgraph()
      │
      ├─ Step 1: Layer 3 Repair (deterministic rule repair, unchanged)
      │   ↓ still has violations
      │
      ├─ Step 2: HealOrchestrator.heal()
      │   │
      │   ├─ 2a. ContextWindowDetector.should_skip_level1()
      │   │   ├─ True (token > 60%) → jump to 2c (Level 2)
      │   │   └─ False (token ≤ 60%) → continue 2b (Level 1)
      │   │
      │   ├─ 2b. Level1SubgraphHealer.heal()
      │   │   ├─ Success → validator validation
      │   │   │   ├─ Pass → return HealResult(success)
      │   │   │   └─ Reject → FailureClassifier.classify() = SEMANTIC → jump to 2e
      │   │   └─ Failure → FailureClassifier.classify()
      │   │       ├─ CONTEXT_OVERFLOW / EMPTY_RESPONSE → continue 2c (Level 2)
      │   │       ├─ JSON_FORMAT → jump to 2d (Level 3)
      │   │       ├─ SEMANTIC → jump to 2e (Level 4)
      │   │       └─ NETWORK → raise exception
      │   │
      │   ├─ 2c. Level2ColumnHealer.heal_column() (per-column processing)
      │   │   ├─ Success → validator validation
      │   │   │   ├─ Pass → merge into config → return HealResult(success)
      │   │   │   └─ Reject → continue Level 2 next column or jump to 2d
      │   │   └─ Failure → FailureClassifier.classify()
      │   │       ├─ CONTEXT_OVERFLOW → jump to 2d (Level 3)
      │   │       └─ Other → jump to 2e (Level 4)
      │   │
      │   ├─ 2d. Level3CompactHealer.heal_compact()
      │   │   ├─ mode="compact" → success → validator validation → pass/reject
      │   │   ├─ mode="compact" → failure → mode="ultra_compact"
      │   │   ├─ mode="ultra_compact" → success → validator validation → pass/reject
      │   │   └─ mode="ultra_compact" → failure → jump to 2e (Level 4)
      │   │
      │   └─ 2e. ProgressiveDegrader.degrade() (unchanged)
      │       └─ return HealResult(degraded, _degraded_columns)
      │
      ├─ Step 3: BrokenEdgeAligner (unchanged)
      └─ Step 4: schema_hash optimistic lock validation (unchanged)
```

### 4.2 Level 2 Column-Level Processing Detail

```
Level2ColumnHealer.heal_column(table, col, violation, config, snapshot)
  │
  ├─ _build_column_context(table, col, snapshot)
  │   │
  │   ├─ Extract target column attributes: name, type, nullable, default, UNIQUE
  │   ├─ Extract CHECK constraints this column participates in (including cross-column)
  │   ├─ Extract derive_from source columns (if any): name + type
  │   ├─ Extract derive_from downstream columns (if any): name list
  │   ├─ Extract cross-column CHECK related keys: name + type
  │   └─ Extract FK info (if FK column): referenced table + referenced column
  │
  ├─ Build column-level prompt (only above info + violation description)
  │
  ├─ Call LLM
  │   ├─ Success → parse JSON → return Level2Result(success, config_patch)
  │   └─ Failure → raise exception (caught by HealOrchestrator for classification)
  │
  └─ Return Level2Result
```

### 4.3 Data Structures

```python
@dataclass
class HealResult:
    """Result of HealOrchestrator.heal()."""
    success: bool
    config: dict[str, Any]          # Repaired config
    level_used: int                  # 1, 2, 3, or 4
    failure_type: FailureType | None # If success=False
    degraded_columns: list[str]      # Level 4 degraded columns
    attempts: list[HealAttempt]      # Per-level attempt records (for diagnostics)

@dataclass
class HealAttempt:
    """Record of a single heal attempt."""
    level: int                       # 1, 2, 3
    failure_type: FailureType | None # None if success
    latency_ms: int
    token_estimate: int              # prompt token estimate
    error_message: str | None

@dataclass
class Level1Result:
    success: bool
    config_patch: dict[str, Any] | None
    raw_response: str | None         # for FailureClassifier
    error: Exception | None

@dataclass
class Level2Result:
    success: bool
    column: str
    config_patch: dict[str, Any] | None
    raw_response: str | None
    error: Exception | None

@dataclass
class Level3Result:
    success: bool
    mode: Literal["compact", "ultra_compact"]
    config_patch: dict[str, Any] | None
    raw_response: str | None
    error: Exception | None
    json_repaired: bool              # whether json-repair was used

@dataclass
class ColumnContext:
    """Minimal dependency info for Level 2."""
    target_column: ColumnInfo
    check_constraints: list[Constraint]  # all CHECKs this column participates in
    derive_from_sources: list[ColumnInfo]  # derive_from source columns
    derive_from_downstream: list[str]  # downstream column names
    cross_column_refs: list[ColumnInfo]  # cross-column CHECK related keys
    fk_info: FKInfo | None
```

### 4.4 Key Design Decisions

1. **Level 2 processes columns individually**: Not sending all violation columns at once, but each violation column gets a separate LLM call. This minimizes per-column prompt size and maximizes success rate.

2. **Level 2 merges configs on success**: After each column is repaired, merge into subgraph config, validate uniformly at the end.

3. **Level 3 has two modes**: `compact` first (keep 1 few-shot), then `ultra_compact` (remove all few-shot) on failure.

4. **`HealAttempt` records for diagnostics**: Every attempt records level, failure_type, latency, token_estimate for post-hoc analysis.

5. **NETWORK errors do not enter degradation chain**: Raise exception directly, let caller decide whether to retry.

## 5. Error Handling

### 5.1 Error Classification and Handling Matrix

| Error Type | Trigger Scenario | Handling | User-Visible Message |
|-----------|-----------------|----------|---------------------|
| `CONTEXT_OVERFLOW` | LLM returns context overflow error | Level 1→2 or Level 2→3 | "Context overflow, retrying with reduced context" |
| `EMPTY_RESPONSE` | LLM returns empty string | Level 1→2 | "Empty response, retrying with column-level context" |
| `JSON_FORMAT` | JSON parsing fails | Level 1→3 (skip Level 2) | "Invalid JSON, retrying with compact prompt + json-repair" |
| `SEMANTIC` | validator rejects config | Direct Level 4 | "Semantic error, falling back to deterministic config" |
| `NETWORK` | API timeout/connection/rate limit | **Raise exception, no degradation** | "Network error: {detail}. Please check connection/API quota." |
| `UNKNOWN` | Unclassified error | Treat as `SEMANTIC` | "Unknown error: {detail}, falling back to deterministic config" |

### 5.2 Level 2 Partial Success Strategy

Level 2 supports partial success — some columns repaired successfully, some failed:

```python
results: dict[str, Level2Result] = {}
for col_name, violation in column_violations.items():
    try:
        context = self._build_column_context(table, col_name, snapshot)
        prompt = self._build_column_prompt(context, violation)
        response = client.call(prompt)
        if not response or not response.strip():
            results[col_name] = Level2Result(success=False, ...)
            continue
        config_patch = parse_json(response)
        results[col_name] = Level2Result(success=True, ...)
    except ContextOverflowError:
        # Single-column prompt overflow → go to Level 3
        return Level2Result(success=False, error=ContextOverflowError())
    except JSONDecodeError as e:
        results[col_name] = Level2Result(success=False, error=JSONFormatError(str(e)))
        continue
    # NETWORK errors not caught, propagate up

# Merge successful column configs
merged = merge_successful_patches(results)
if all(r.success for r in results.values()):
    return Level2Result(success=True, ...)
elif any(r.success for r in results.values()):
    # Partial success → successful columns use LLM config, failed columns continue to Level 3/4
    return Level2Result(success=partial, merged=merged, failed_columns=[...])
```

### 5.3 Network/API Error Propagation

Network errors do not enter the degradation chain, raise directly:

```python
class HealOrchestrator:
    def heal(self, ...):
        try:
            return self._do_heal(...)
        except NetworkError as e:
            raise HealNetworkError(
                f"LLM API call failed: {e}. "
                f"Please check network connection, API key, and rate limits."
            ) from e
```

**Rationale:** Network errors are external factors. Degrading to deterministic config would mask the real API problem. Users should know "the API had a problem", not "the config was degraded".

### 5.4 Oscillation Detection

`OscillationDetector` logic unchanged, but call site migrates to `HealOrchestrator`:

```python
class HealOrchestrator:
    def heal(self, ...):
        oscillator = OscillationDetector()
        for attempt in range(max_rounds):
            result = self._try_heal_one_round(...)
            if result.success:
                return result
            if oscillator.is_oscillating(result.failure_type):
                # Oscillation detected → direct degradation
                return self._degrade(...)
```

### 5.5 Logging and Observability

Each level attempt records structured logs:

```python
logger.info(
    "heal_attempt",
    table=table_name,
    level=2,
    column=col_name,
    failure_type="context_overflow",
    latency_ms=1500,
    token_estimate=8500,
    next_level=3,
)
```

Final result logging:

```python
logger.info(
    "heal_complete",
    table=table_name,
    success=True,
    level_used=2,
    attempts=[
        {"level": 1, "failure_type": "context_overflow", "latency_ms": 2000},
        {"level": 2, "failure_type": None, "latency_ms": 800},
    ],
    degraded_columns=[],
)
```

## 6. Testing Strategy

### 6.1 Core Principles

1. **No mock LLM calls** — Avoid "self-proving trap" (mock correct but actual call fails).
2. **Use real test environments** — Skip if no real environment available (`@pytest.mark.skipif`).
3. **Delete tests for removed components** — Do not keep tests for deleted components.
4. **Loop Engineering strict convergence** — 3-phase multi-round validation.

### 6.2 Test Layers

```
Test pyramid:
  ├─ Pure logic unit tests (no LLM) — test with real data
  ├─ LLM-dependent tests (need real LLM) — run only if LLM environment available, else skip
  └─ Loop Engineering E2E — strict 3-phase convergence
```

### 6.3 Pure Logic Unit Tests (No LLM)

These components do not involve LLM calls, test with real input data:

#### `TestContextWindowDetector`

| Test Case | Verification Point |
|-----------|-------------------|
| `test_get_context_window_from_config` | AIConfig.max_context_tokens priority |
| `test_get_context_window_from_model_map` | Model mapping table (gemma-4-e2b → 8192) |
| `test_get_context_window_default` | Conservative default 4096 |
| `test_estimate_tokens_rough` | chars/4 estimation |
| `test_should_skip_level1_above_threshold` | token > 60% → True |
| `test_should_skip_level1_below_threshold` | token ≤ 60% → False |

#### `TestFailureClassifier`

| Test Case | Verification Point |
|-----------|-------------------|
| `test_classify_context_overflow` | Real ContextOverflowError → CONTEXT_OVERFLOW |
| `test_classify_empty_response` | Empty string → EMPTY_RESPONSE |
| `test_classify_json_format` | Real JSONDecodeError → JSON_FORMAT |
| `test_classify_semantic` | Real ValidationResult(ok=False) → SEMANTIC |
| `test_classify_network_timeout` | Real APITimeoutError → NETWORK |
| `test_classify_network_connection` | Real APIConnectionError → NETWORK |
| `test_classify_unknown` | Unknown exception → UNKNOWN |

#### `TestLevel2ColumnHealer._build_column_context()`

Only test context building logic (pure logic, no LLM):

| Test Case | Verification Point |
|-----------|-------------------|
| `test_build_context_simple_column` | Single column no dependencies → only target column attributes |
| `test_build_context_with_check` | Single column CHECK → contains CHECK expression |
| `test_build_context_with_derive_from_source` | derive_from source column → contains source column attributes |
| `test_build_context_with_downstream` | Downstream dependency → contains downstream column names |
| `test_build_context_with_cross_column_check` | Cross-column CHECK → contains related columns |
| `test_build_context_with_fk` | FK column → contains reference info |

### 6.4 LLM-Dependent Tests (Real LLM or Skip)

These tests require real LLM environments, controlled by `@pytest.mark.skipif`:

```python
@pytest.fixture(scope="session")
def llm_available():
    """Check if local LM Studio is available."""
    try:
        import httpx
        resp = httpx.get("http://localhost:1234/v1/models", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False

@pytest.mark.skipif("not llm_available", reason="LM Studio not available")
class TestLevel1SubgraphHealerReal:
    """Real LLM tests — skipped if no LM Studio."""
    ...
```

| Component | Test Content | Skip Condition |
|-----------|-------------|----------------|
| `Level1SubgraphHealer` | Real LLM call + response parsing | No LM Studio |
| `Level2ColumnHealer.heal_column()` | Real column-level LLM call | No LM Studio |
| `Level3CompactHealer` | Real compact/ultra_compact | No LM Studio |
| `HealOrchestrator` | Real 4-level degradation flow | No LM Studio |

### 6.5 Deleted Tests

| Deleted Test | Reason |
|-------------|--------|
| Existing `test_llm_healer.py` mock tests | Component deleted |
| Existing `test_layer4_coordinator.py` mock tests | Component deleted |
| Any test mocking `APIClient` | Violates "no mock" principle |

### 6.6 Loop Engineering E2E (Strict 3-Phase Convergence)

#### Phase 1: Single Database Problem Convergence

```
Select 1 complex database (meaningful logic/business structure, high complexity)
  ↓
Loop Engineering loop:
  Round 1: ai-analyze → fill → verify → find issues → fix code → cleanup
  Round 2: ai-analyze → fill → verify → find issues → fix code → cleanup
  ...
  Round N: ai-analyze → fill → verify → 0 issues → enter Phase 2
  ↓
Convergence criteria: 0 FK/CHECK/UNIQUE violations + test suite all pass
```

#### Phase 2: Stability Validation (Same Database Retry 2 Times)

```
Same database runs 2 more times:
  Round N+1: ai-analyze → fill → verify → must pass
  Round N+2: ai-analyze → fill → verify → must pass
  ↓
If any failure → return to Phase 1 to continue fixing code
If both pass → enter Phase 3
```

#### Phase 3: New Database Validation (2 Different Databases)

```
Generate new database A (different business scenario, meaningful complexity):
  ├─ First verify database itself is correct (schema constraints self-consistent)
  └─ Complete Phase 1 + Phase 2 (problem convergence + stability validation)

Generate new database B (another different business scenario, meaningful complexity):
  ├─ First verify database itself is correct (schema constraints self-consistent)
  └─ Complete Phase 1 + Phase 2 (problem convergence + stability validation)
  ↓
Both databases pass → Loop Engineering ends
```

### 6.7 Database Requirements

| Requirement | Description |
|-------------|-------------|
| **Database itself correct** | Schema constraints self-consistent, verify database usability before fill |
| **Meaningful logic/business structure** | Simulate real business scenarios (e-commerce, hospital, logistics, etc.) |
| **Meaningful complexity** | Not about table count, but constraint complexity (self-referencing FK, composite PK, cross-column CHECK, UNIQUE chains, etc.) |
| **Each generation different** | Generate new database each round, check code from different angles |

#### Database Complexity Checklist

Each generated database must cover:

```
□ Self-referencing foreign key (e.g., categories.parent_id)
□ Composite primary key (e.g., order_items(order_id, product_id))
□ Cross-column CHECK constraint (e.g., unit_price > cost_price)
□ Arithmetic equality CHECK (e.g., subtotal = quantity * unit_price)
□ Single-column CHECK (BETWEEN, IN, LENGTH)
□ UNIQUE constraint (including text column UNIQUE)
□ DEFAULT values
□ AUTOINCREMENT primary key
□ Implicit rowid PK
□ NOT NULL constraint
□ Multi-table FK relationship chain
```

### 6.8 Per-Round Validation Checklist

```
1. Database itself validation (schema self-consistent, constraints not conflicting)
2. ai-analyze generates YAML (observe logging observability)
3. sqlseed fill data generation
4. FK integrity validation
5. CHECK constraint validation (including cross-column)
6. UNIQUE constraint validation
7. Composite primary key uniqueness validation
8. pytest test suite all pass
9. ruff check + ruff format + mypy pass
10. Temporary file cleanup
```

### 6.9 Dual-Model Validation

Model validation flow supports two model types:

| Model Type | Backend | Use Case |
|-----------|---------|----------|
| Large model | OpenRouter (free) | High-capability scenario validation |
| Small model | Local LM Studio | Low-capability scenario validation |

Both model types must complete the Loop Engineering 3-phase convergence.

### 6.10 Assistant Role Boundary

During Loop Engineering, the assistant:
- **Only observes** logs and YAML output
- **Fixes code** based on observed issues (not YAML output)
- **Does not participate** in the actual LLM analysis flow
- **Does not manually patch** YAML output

### 6.11 CI Integration Validation

Ensure `ci.yml` executes without issues:

```bash
# Local CI-equivalent validation
ruff check src/ tests/ plugins/                    # lint
ruff format --check src/ tests/ plugins/           # format check
mypy                                                # type check
pytest --cov=sqlseed --cov=sqlseed_ai \
  --cov-report=term-missing --tb=short -q          # core tests
pytest plugins/sqlseed-ai/tests/property/ -v        # property tests
pytest tests/integration/ -v                        # integration tests
```

### 6.12 Test File Structure

```
plugins/sqlseed-ai/tests/
├── healer/
│   ├── test_context_detector.py              # New (pure logic)
│   ├── test_failure_classifier.py            # New (pure logic)
│   ├── test_level2_context_builder.py        # New (pure logic, only test _build_column_context)
│   ├── test_heal_orchestrator_real.py        # New (real LLM, skipif controlled)
│   ├── test_level1_subgraph_healer_real.py   # New (real LLM, skipif controlled)
│   ├── test_level2_column_healer_real.py     # New (real LLM, skipif controlled)
│   ├── test_level3_compact_healer_real.py    # New (real LLM, skipif controlled)
│   ├── test_degrader.py                      # Existing, unchanged
│   └── test_oscillation.py                   # Existing, unchanged
├── test_llm_healer.py                        # Deleted (component deleted)
├── test_layer4_coordinator.py                # Deleted (component deleted)
└── property/
    └── test_contract_matrix.py               # Existing, unchanged
```

## 7. Documentation Update Requirements

Per user requirement, the following documentation must be updated in the same commit as code changes:

| Source File | Docs to Update | What to Check |
|------------|---------------|---------------|
| `healer/orchestrator.py` (new) | CLAUDE.md, README.md | LLM heal architecture description |
| `healer/context_detector.py` (new) | CLAUDE.md | Component description |
| `healer/failure_classifier.py` (new) | CLAUDE.md | Failure type enum |
| `healer/level1_subgraph_healer.py` (new) | CLAUDE.md | Component description |
| `healer/level2_column_healer.py` (new) | CLAUDE.md | Component description |
| `healer/level3_compact_healer.py` (new) | CLAUDE.md | Component description |
| `healer/llm_healer.py` (deleted) | CLAUDE.md | Remove old component description |
| `healer/coordinator.py` (deleted) | CLAUDE.md | Remove old component description |
| `CLAUDE.md` v4 architecture section | CLAUDE.md | Update Layer 4 description to 4-level architecture |

## 8. Pre-Implementation Requirements

### 8.1 Backup Commit

Before any code changes, commit the current state as a backup checkpoint:

```bash
git add -A
git commit -m "backup: pre-4-level-heal-architecture-refactor checkpoint"
```

This allows rollback if issues arise during refactoring.

### 8.2 Branch Strategy

- All changes on `feat/contract-driven-self-healing` branch
- Do not merge to `main` until all Loop Engineering phases pass
- Merge must be manually confirmed by user

## 9. Implementation Order

1. **Backup commit** (Section 8.1)
2. **Create new components** (pure logic first):
   - `ContextWindowDetector`
   - `FailureClassifier`
   - `Level2ColumnHealer._build_column_context()` (context building only)
3. **Refactor existing components**:
   - Extract `Level1SubgraphHealer` from `LLMHealer`
   - Create `Level3CompactHealer` from `LLMHealer` compact logic
4. **Create `HealOrchestrator`** (coordinates all levels)
5. **Update `AutoHealOrchestrator._heal_subgraph()`** to use `HealOrchestrator`
6. **Delete old components** (`Layer4Coordinator`, `LLMHealer`)
7. **Update/delete tests** (per Section 6.12)
8. **Update documentation** (per Section 7)
9. **Run CI-equivalent validation** (per Section 6.11)
10. **Loop Engineering 3-phase convergence** (per Section 6.6)

## 10. Success Criteria

1. All pure logic unit tests pass
2. LLM-dependent tests pass (or skip gracefully if no LLM)
3. CI (`ci.yml`) all green
4. Loop Engineering 3-phase convergence complete:
   - Phase 1: Single database 0 issues
   - Phase 2: Same database 2 retries stable
   - Phase 3: 2 new databases each complete Phase 1 + Phase 2
5. Documentation updated and consistent
6. No dead code (deleted components fully removed)
