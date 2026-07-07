# Contract-Driven Self-Healing Architecture v4

**Status:** Implemented (2026-07-07)
**Date:** 2026-07-05
**Author:** sqlseed team
**Supersedes:** Rule-based engine in `staged_analyzer.py` (gradual migration)
**Implementation:** [2026-07-07-v4-default-migration-and-legacy-removal.md](../plans/2026-07-07-v4-default-migration-and-legacy-removal.md)

---

## 1. Motivation

### 1.1 Problem Statement

The current rule engine in [`staged_analyzer.py`](file:///c:/Users/14435/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py) uses 16 rules (Rule #14–#20, #22–#30; Rule #21 was never implemented) applied in a fixed sequence. While each rule is schema-aware (not hardcoded to specific tables), the **addition of rules is reactive**: a new rule is added only after observing a new failure mode. This leads to:

1. **Patch-style fixes** — Each new LLM mistake requires a new Rule or Case
2. **Implicit ordering dependencies** — Rules must execute in a specific order (maintained via comments)
3. **Open-ended growth** — No definition of "when is the rule set complete?"
4. **No learning** — The same LLM mistake on a new schema requires re-discovery

### 1.2 Goals

| Requirement | How v4 achieves it |
|-------------|-------------------|
| Zero learning cost for users | `sqlseed ai-analyze --auto-heal` (one command) |
| Fast (90%+ failures resolved without LLM) | Layer 2/3 pure Python, millisecond response |
| Long-term stable core code | Sparse matrix is a closed set (~50–100 entries) |
| Self-healing for unknown failures | Layer 4 LLM Healer + Progressive Degrade |
| Learning accumulates across runs | Local JSON registry with schema_hash versioning |
| Root-cause fix, not patches | Property-based testing discovers matrix gaps in CI |

### 1.3 Design Principles

1. **Design by Contract** (Meyer) — Layer 1 defines invariant contracts
2. **Defense in Depth** — 6 layers, each with single responsibility
3. **Controller Pattern** (Kubernetes) — Layer 4 reconcile loop for self-healing
4. **Closed-Set Learning** — Matrix is finite; learning converges
5. **Property-Based Testing** (Hypothesis) — CI verifies completeness
6. **Progressive Enhancement** — Layer 2→3→4→5, each layer is the fallback for the next

---

## 2. Architecture Overview

### 2.1 Six Layers + Eight Defense Lines

```
┌─────────────────────────────────────────────────────────────────┐
│ [Startup Phase]                                                  │
│   [Defense 8] Schema static snapshot (lock schema_hash)         │
│   [Defense 2] Tarjan SCC merge (circular dependency deadlock)   │
│   [Defense 6] Megacluster weak-link breaking (>3 tables)        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Sparse Contract Matrix (dev-time, closed set)          │
│   + Learned Contracts Registry (runtime, local JSON)            │
│   [Defense 1] Safety sandbox: fix whitelist, schema_hash        │
│   [Defense 7] RCE defense: forbid custom_function persistence   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Fast Validator (runtime-fast, pure Python)             │
│   2a: Single-column contract check (sparse matrix, O(N)~O(1))   │
│   2b: Cross-column constraint check (DAG + FK + composite)      │
│   [Defense 3] Dialect-aware error parser (SQLite/PG)            │
│   [Defense 5] Composite FK coordinator                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓ failure
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Stateless Repair Engine (runtime-fast, known modes)    │
│   Existing 16 rules refactored to stateless functions           │
│   Driven by Layer 2 ViolationReports (declarative → imperative) │
└─────────────────────────────────────────────────────────────────┘
                              ↓ still failing
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: LLM Healer + Progressive Degrade (runtime-robust)      │
│   4a: Dependency subgraph splitting (sliding window, 1-2K tok)  │
│   4b: LLM regeneration (with failure reasons + contracts)       │
│   4c: Oscillation detection (error state history comparison)    │
│   4d: Progressive deterministic degrade (Core 9-level mapper)   │
│   [Defense 4] Cascade degrade (incl. derive_from downstream)    │
│   [Defense 5] Composite FK coordinated degrade                  │
│   4e: Diff learning → [Defense 7] intercept → JSON registry     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [Write Phase]                                                    │
│   [Defense 8] Optimistic lock: verify schema_hash unchanged     │
│   Broken-edge post-repair: align nullable FK ranges             │
│   Write YAML                                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 5: CI Property-Based Testing (dev-time, completeness)     │
│   Hypothesis generates random schema × generator × constraint   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ TimeBudgetController (spans all layers, default 300s)           │
│   Per-table dynamic allocation + timeout deterministic fallback │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Eight Defense Lines

| # | Defense | Layer | Solves |
|---|---------|-------|--------|
| 1 | Safety sandbox JSON registry | Layer 1 | Learning non-persistence |
| 2 | Tarjan SCC merge | Startup | Circular dependency deadlock |
| 3 | Dialect-aware error parser | Layer 2 | Multi-DB error differences |
| 4 | Cascade degrade + lock rebuild | Layer 4 | Upstream degrade breaks downstream |
| 5 | Composite FK coordinator | Layer 2+4 | Composite FK single-column conflict |
| 6 | Megacluster weak-link breaking | Startup | Giant SCC overflows small-model context |
| 7 | RCE execution-time interception | Layer 4e | LLM injects malicious code |
| 8 | Schema snapshot + optimistic lock | Startup+Write | Schema drift during analysis |

---

## 3. Layer 1: Sparse Contract Matrix + Learned Registry

### 3.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Contract Matrix                                    │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────────────────┐    │
│  │ Built-in         │  │ Learned Contracts Registry   │    │
│  │ Violations       │  │ (~/.sqlseed/learned.json)    │    │
│  │ (code, closed)   │  │ (runtime, incremental)       │    │
│  └────────┬─────────┘  └────────────┬─────────────────┘    │
│           └──────────┬───────────────┘                       │
│                      ▼                                       │
│           ┌──────────────────────┐                           │
│           │ ContractResolver     │                           │
│           │ (merged query, O(N)~O(1)) │                         │
│           └──────────────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Core Data Structures

```python
# plugins/sqlseed-ai/src/sqlseed_ai/contracts/matrix.py

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class ViolationKind(Enum):
    CRASH = "crash"
    SEMANTIC_ERROR = "semantic_error"
    UNIQUE_UNSATISFIABLE = "unique_unsatisfiable"
    CONDITIONAL = "conditional"


@dataclass
class ContractViolation:
    """Single contract violation definition"""
    generator: str
    column_type: str                     # "ANY" for wildcard
    constraints: frozenset[str]          # empty set for wildcard
    kind: ViolationKind
    fix_strategy: str                    # whitelist function name
    fix_params: dict[str, Any] = field(default_factory=dict)
    predicate: Callable[[dict], bool] | None = None  # None for learned contracts
    source: str = "builtin"              # "builtin" | "auto_learned"
    learned_at: datetime | None = None
    schema_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializable form (predicate excluded, datetime as ISO)"""
        return {
            "generator": self.generator,
            "column_type": self.column_type,
            "constraints": list(self.constraints),
            "kind": self.kind.value,
            "fix_strategy": self.fix_strategy,
            "fix_params": self.fix_params,
            "source": self.source,
            "learned_at": self.learned_at.isoformat() if self.learned_at else None,
            "schema_hash": self.schema_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractViolation:
        """Deserialize (predicate set to None for learned contracts)"""
        return cls(
            generator=data["generator"],
            column_type=data["column_type"],
            constraints=frozenset(data.get("constraints", [])),
            kind=ViolationKind(data["kind"]),
            fix_strategy=data["fix_strategy"],
            fix_params=data.get("fix_params", {}),
            predicate=None,  # Learned contracts are declarative
            source=data.get("source", "auto_learned"),
            learned_at=datetime.fromisoformat(data["learned_at"]) if data.get("learned_at") else None,
            schema_hash=data.get("schema_hash"),
        )

    def __hash__(self) -> int:
        """Identity by core fields only (excludes predicate/learned_at/source)"""
        return hash((self.generator, self.column_type, self.constraints,
                     self.kind, self.fix_strategy))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContractViolation):
            return NotImplemented
        return (self.generator == other.generator and
                self.column_type == other.column_type and
                self.constraints == other.constraints and
                self.kind == other.kind and
                self.fix_strategy == other.fix_strategy)


class ContractResolver:
    """Merged query: builtin + learned.

    Adversarial fix (C2 from cross-agent review): the lookup is O(N) where
    N is the matrix size (~100 entries, <1ms in practice), NOT O(1). True
    O(1) would require a ``dict[(generator, column_type, frozenset[str]),
    list[ContractViolation]]`` index. The current linear scan is fast
    enough at this scale; if matrix grows beyond ~500 entries, consider
    adding the dict index.
    """

    def __init__(self, builtin: set[ContractViolation], learned: set[ContractViolation]):
        self._builtin = builtin
        self._learned = learned

    def check(self, generator: str, column_type: str,
              constraints: frozenset[str], config: dict) -> ContractViolation | None:
        """Check if combination is violated, return definition or None (compatible)"""
        matches = []

        # Collect from both sources
        for source, violations in [("learned", self._learned), ("builtin", self._builtin)]:
            for v in violations:
                if v.generator != generator:
                    continue
                specificity = self._match_specificity(v, column_type, constraints)
                if specificity is None:
                    continue
                # Conditional violations need predicate evaluation
                if v.predicate is not None and not v.predicate(config):
                    continue
                matches.append((source, specificity, v))

        if not matches:
            return None

        # Priority: specificity (1=exact, 2=partial wildcard, 3=full wildcard)
        # Then: learned > builtin (allows LLM/user to override unreasonable defaults)
        matches.sort(key=lambda x: (x[1], 0 if x[0] == "learned" else 1))
        return matches[0][2]

    @staticmethod
    def _match_specificity(v: ContractViolation, col_type: str,
                           constraints: frozenset[str]) -> int | None:
        """Return specificity level (1=exact, 2=partial, 3=full wildcard) or None (no match)"""
        type_match = v.column_type == col_type
        type_wildcard = v.column_type == "ANY"
        cons_match = v.constraints == constraints
        cons_subset = v.constraints.issubset(constraints) and v.constraints
        cons_wildcard = not v.constraints

        if type_match and cons_match:
            return 1
        if type_match and (cons_subset or cons_wildcard):
            return 2
        if type_wildcard and (cons_match or cons_subset or cons_wildcard):
            return 3
        return None
```

### 3.3 Built-in Sparse Matrix (~50–100 entries)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/contracts/builtin_violations.py

BUILTIN_VIOLATIONS: set[ContractViolation] = {
    # === Type compatibility (from Rule #30) ===
    ContractViolation(
        generator="integer", column_type="TIMESTAMP",
        constraints=frozenset(), kind=ViolationKind.CRASH,
        fix_strategy="switch_generator", fix_params={"target": "datetime"},
    ),
    ContractViolation(
        generator="float", column_type="TEXT",
        constraints=frozenset(), kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator", fix_params={"target": "string"},
    ),
    # === UNIQUE cardinality (from Rule #24) ===
    ContractViolation(
        generator="choice", column_type="ANY",
        constraints=frozenset({"UNIQUE"}), kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="upgrade_to_template",
        predicate=lambda cfg: _is_code_like(cfg.get("name", "")),
    ),
    # ... ~50-100 entries total ...
}
```

### 3.4 Learned Registry (Defense 1 + Defense 7)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/contracts/registry.py

SAFE_FIX_STRATEGIES = frozenset({
    "switch_generator", "upgrade_to_template", "expand_pool",
    "adjust_bounds", "add_unique_suffix", "normalize_params",
    "break_derive_from_cycle", "align_fk_max_value",
    "isolate_date_ranges", "semantic_upgrade", "fix_self_reference",
    "coerce_float_to_int", "align_group_generators",
})

FORBIDDEN_PERSIST_KEYS = frozenset({
    "custom_function", "expression", "code", "eval", "exec", "lambda",
})


class LearnedContractsRegistry:
    """Local JSON-persisted learned contracts registry"""

    def __init__(self, path: Path | None = None):
        self._path = path or (get_cache_dir() / "learned_contracts.json")
        self._contracts: set[ContractViolation] = set()
        self._load()

    def add(self, violation: ContractViolation) -> bool:
        """Add a learned contract, return success"""
        # [Defense 7] Refuse to persist dangerous params
        if any(k in violation.fix_params for k in FORBIDDEN_PERSIST_KEYS):
            logger.warning("Refusing to persist unsafe contract",
                          strategy=violation.fix_strategy)
            return False
        # [Defense 1] Must be whitelist strategy
        if violation.fix_strategy not in SAFE_FIX_STRATEGIES:
            return False
        self._contracts.add(violation)
        self._save()
        return True

    def filter_by_schema_hash(self, current_hash: str) -> set[ContractViolation]:
        """[Defense 1] Auto-invalidate stale contracts on schema change"""
        return {v for v in self._contracts if v.schema_hash == current_hash}

    def size(self) -> int:
        return len(self._contracts)

    def _load(self) -> None:
        """Load from JSON, gracefully handle corruption"""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data.get("contracts", []):
                self._contracts.add(ContractViolation.from_dict(item))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Learned contracts registry corrupted, ignoring", error=str(e))

    def _save(self) -> None:
        """Persist to JSON"""
        data = {
            "schema_hash": None,  # Per-contract hash is authoritative
            "contracts": [v.to_dict() for v in self._contracts],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
```

### 3.5 Error Handling

- **JSON parse failure**: Ignore learned_contracts.json, use only builtin contracts (degrade, don't crash)
- **schema_hash mismatch**: Auto-invalidate all learned contracts, log warning
- **Duplicate contracts**: Builtin takes precedence; learned contracts deduplicated by `__hash__`/`__eq__`

### 3.6 Testing

```python
@given(
    generator=st.sampled_from(ALL_GENERATORS),
    col_type=st.sampled_from(ALL_COLUMN_TYPES),
    constraints=st.frozensets(st.sampled_from({"UNIQUE", "NOT_NULL", "CHECK", "FK"})),
)
def test_contract_matrix_completeness(generator, col_type, constraints):
    """Property: each combination is either COMPATIBLE or has explicit matrix entry"""
    violation = resolver.check(generator, col_type, constraints, {})
    if violation is None:
        config = make_test_config(generator, col_type, constraints)
        result = try_fill_in_memory(config, n=100)
        assert result.success, f"Unlisted combination failed: {(generator, col_type, constraints)}"
```

---

## 4. Layer 2: Fast Validator

### 4.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Fast Validator                                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2a: SingleColumnValidator                                │    │
│  │   - ContractResolver.check() O(N)~O(1) lookup             │    │
│  │   - UNIQUE cardinality check                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2b: CrossColumnValidator                                 │    │
│  │   - FK consistency (value domain alignment)              │    │
│  │   - Composite UNIQUE (multi-column cardinality)          │    │
│  │   - Semantic relations (start_date < end_date)           │    │
│  │   - derive_from DAG (no cycles + type compatible)        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ [Defense 3] DialectErrorParser                           │    │
│  │   SQLite/PG error → normalized ViolationReport           │    │
│  │   Uses pre-cached constraint_map from SchemaSnapshot     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ [Defense 5] CompositeFKCoordinator                       │    │
│  │   Identify composite FK → bind ColumnGroup               │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Core Data Structures

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/models.py

class ConstraintType(Enum):
    FK = "fk"
    CHECK = "check"
    UNIQUE = "unique"
    NOT_NULL = "not_null"


@dataclass
class ViolationReport:
    """Normalized violation report (dialect-agnostic)"""
    table: str
    columns: list[str]
    constraint_type: ConstraintType
    severity: Literal["crash", "semantic_error", "unique_unsatisfiable"]
    raw_expression: str | None = None
    constraint_name: str | None = None
    is_composite: bool = False
    fix_hint: str | None = None
    fix_params: dict[str, Any] = field(default_factory=dict)
    source: str = "validation"
    message: str | None = None  # human-readable error text (used by LLMHealer)


@dataclass
class ColumnGroup:
    """Composite FK coordinated generation group (Defense 5)"""
    group_id: str
    columns: list[str]
    parent_table: str
    parent_columns: list[str]
    degrade_together: bool = True


@dataclass
class ValidationResult:
    violations: list[ViolationReport]
    column_groups: list[ColumnGroup]
    is_clean: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_clean = len(self.violations) == 0
```

### 4.3 Single-Column Validator (2a)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/single_column.py

class SingleColumnValidator:
    """2a: Single-column contract check (sparse matrix, O(N)~O(1))"""

    def __init__(self, resolver: ContractResolver):
        self._resolver = resolver

    def validate(self, table_config: dict, table_schema: dict,
                 row_count: int) -> list[ViolationReport]:
        violations = []
        for col in table_config.get("columns", []):
            col_name = col.get("name", "")
            col_type = self._extract_col_type(col_name, table_schema)
            constraints = self._extract_constraints(col_name, table_schema, col)

            # Contract matrix lookup
            violation = self._resolver.check(
                generator=col.get("generator", ""),
                column_type=col_type,
                constraints=constraints,
                config={**col, "row_count": row_count, "name": col_name},
            )
            if violation:
                violations.append(ViolationReport(
                    table=table_config["name"],
                    columns=[col_name],
                    constraint_type=self._map_constraint_type(violation),
                    severity=violation.kind.value,
                    fix_hint=violation.fix_strategy,
                    fix_params=violation.fix_params,
                ))

            # UNIQUE cardinality check (with robust defaults)
            if "UNIQUE" in constraints:
                cardinality = self._compute_cardinality(col, row_count)
                if cardinality < row_count:
                    violations.append(ViolationReport(
                        table=table_config["name"],
                        columns=[col_name],
                        constraint_type=ConstraintType.UNIQUE,
                        severity="unique_unsatisfiable",
                        fix_hint="upgrade_to_template",
                        fix_params={"reason": f"cardinality {cardinality} < row_count {row_count}"},
                    ))
        return violations

    def _compute_cardinality(self, col: dict, row_count: int) -> int:
        """Compute generator cardinality with robust defaults"""
        gen = col.get("generator", "")
        params = col.get("params", {})
        if gen == "choice":
            return len(params.get("choices", []))
        if gen == "template":
            return int(1e9)  # effectively infinite; avoid float inf in comparisons
        if gen == "integer":
            min_val = params.get("min_value") or 0
            max_val = params.get("max_value") or 9999
            return max_val - min_val + 1
        if gen == "string":
            return 62 ** params.get("max_length", 10)
        return row_count  # Optimistic estimate
```

### 4.4 Cross-Column Validator (2b)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/cross_column.py

class CrossColumnValidator:
    """2b: Cross-column constraint check"""

    def validate(self, table_config: dict, table_schema: dict,
                 snapshot: SchemaSnapshot) -> list[ViolationReport]:
        violations = []
        violations.extend(self._check_fk_integrity(table_config, snapshot))
        violations.extend(self._check_composite_unique(table_config, table_schema))
        violations.extend(self._check_semantic_relations(table_config, table_schema))
        violations.extend(self._check_derive_from_dag(table_config))
        return violations
```

### 4.5 Dialect-Aware Error Parser (Defense 3)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/dialect_parser.py

class DialectErrorParser:
    """[Defense 3] Normalize SQLAlchemy/DBAPI exceptions to ViolationReport"""

    @classmethod
    def parse(cls, error: Exception, dialect: str, table: str | None,
              snapshot: SchemaSnapshot | None) -> ViolationReport | None:
        if dialect == "sqlite":
            return cls._parse_sqlite(error, table)
        elif dialect == "postgresql":
            return cls._parse_postgresql(error, table, snapshot)
        return None

    @staticmethod
    def _parse_sqlite(error: Exception, table: str | None) -> ViolationReport | None:
        """SQLite: extract expression from error text"""
        msg = str(error)
        if "CHECK constraint failed" in msg:
            expr = msg.split("CHECK constraint failed:")[-1].strip()
            return ViolationReport(
                table=table or "", columns=[],
                constraint_type=ConstraintType.CHECK,
                severity="crash", raw_expression=expr,
            )
        if "UNIQUE constraint failed" in msg:
            cols_str = msg.split("UNIQUE constraint failed:")[-1].strip()
            cols = [c.strip() for c in cols_str.split(".")[1:]]  # table.col format
            return ViolationReport(
                table=table or "", columns=cols,
                constraint_type=ConstraintType.UNIQUE, severity="crash",
            )
        if "FOREIGN KEY constraint failed" in msg:
            # SQLite FK errors don't include column info;
            # caller should do in-memory shadow FK scan to locate
            return ViolationReport(
                table=table or "", columns=[],
                constraint_type=ConstraintType.FK, severity="crash",
                fix_hint="shadow_fk_scan",
            )
        return None

    @staticmethod
    def _parse_postgresql(error: Exception, table: str | None,
                          snapshot: SchemaSnapshot | None) -> ViolationReport | None:
        """PostgreSQL: use diag.constraint_name + pre-cached constraint_map"""
        diag = getattr(error, "diag", None)
        if diag is None:
            return None
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name is None or snapshot is None:
            return None
        # O(1) lookup in pre-cached constraint_map (no runtime SQL)
        info = snapshot.constraint_map.get(constraint_name)
        if info is None:
            return None
        return ViolationReport(
            table=table or getattr(diag, "table_name", "") or "",
            columns=info.columns,
            constraint_type=info.constraint_type,
            severity="crash",
            constraint_name=constraint_name,
            raw_expression=info.expression,
            is_composite=len(info.columns) > 1,
        )
```

### 4.6 Composite FK Coordinator (Defense 5)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/composite_fk.py

class CompositeFKCoordinator:
    """[Defense 5] Identify composite FK, bind coordinated groups"""

    def identify_groups(self, snapshot: SchemaSnapshot) -> list[ColumnGroup]:
        groups = []
        for table in snapshot.tables.values():
            for fk in table.foreign_keys:
                if len(fk.columns) > 1:
                    group_id = f"{table.name}_{'_'.join(fk.columns)}_fk"
                    groups.append(ColumnGroup(
                        group_id=group_id,
                        columns=fk.columns,
                        parent_table=fk.ref_table,
                        parent_columns=fk.ref_columns,
                        degrade_together=True,
                    ))
        return groups

    def validate_group(self, group: ColumnGroup,
                       table_config: dict) -> ViolationReport | None:
        """Verify group columns use aligned generators"""
        cols = [c for c in table_config.get("columns", [])
                if c.get("name") in group.columns]
        if len(cols) != len(group.columns):
            return None
        generators = {c.get("generator") for c in cols}
        if len(generators) > 1:
            return ViolationReport(
                table=table_config["name"], columns=group.columns,
                constraint_type=ConstraintType.FK,
                severity="semantic_error", is_composite=True,
                fix_hint="align_group_generators",
                fix_params={"group_id": group.group_id},
            )
        return None

    def coordinate_degrade(self, group: ColumnGroup, degraded_col: str) -> list[str]:
        """If any column in group degrades, return all group columns"""
        if group.degrade_together and degraded_col in group.columns:
            return group.columns
        return [degraded_col]
```

### 4.7 Main Validator Orchestration

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/main.py

class FastValidator:
    """Layer 2 main validator: orchestrates 2a + 2b + dialect + composite FK"""

    def __init__(self, resolver: ContractResolver):
        self._single = SingleColumnValidator(resolver)
        self._cross = CrossColumnValidator()
        self._composite_fk = CompositeFKCoordinator()

    def validate(self, config: dict, snapshot: SchemaSnapshot,
                 fill_error: Exception | None = None,
                 dialect: str = "sqlite") -> ValidationResult:
        all_violations = []
        for table_config in config.get("tables", []):
            table_schema = snapshot.tables.get(table_config["name"], {})
            row_count = config.get("default_count", 1000)
            all_violations.extend(self._single.validate(table_config, table_schema, row_count))
            all_violations.extend(self._cross.validate(table_config, table_schema, snapshot))

        if fill_error is not None:
            report = DialectErrorParser.parse(fill_error, dialect, None, snapshot)
            if report:
                all_violations.append(report)

        groups = self._composite_fk.identify_groups(snapshot)
        for group in groups:
            for table_config in config.get("tables", []):
                if table_config["name"] == group.parent_table:
                    continue
                v = self._composite_fk.validate_group(group, table_config)
                if v:
                    all_violations.append(v)

        return ValidationResult(violations=all_violations, column_groups=groups)
```

### 4.8 Testing

```python
def test_unique_choice_low_cardinality():
    """choice generator cardinality < row_count → UNIQUE_UNSATISFIABLE"""
    ...

def test_sqlite_check_violation_parsing():
    error = sqlite3.IntegrityError("CHECK constraint failed: sale_price >= cost_price")
    report = DialectErrorParser.parse(error, "sqlite", table="products")
    assert report.constraint_type == ConstraintType.CHECK
    assert report.raw_expression == "sale_price >= cost_price"

def test_composite_fk_group_identification():
    """Composite FK correctly identified as ColumnGroup"""
    ...
```

---

## 5. Layer 3: Stateless Repair Engine

### 5.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Stateless Repair Engine                                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ RepairStrategyRegistry                                   │    │
│  │   fix_strategy name → stateless repair function          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ RepairExecutor                                           │    │
│  │   Sort by severity, invoke strategies, collect fixes    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ LegacyRuleBridge                                         │    │
│  │   Existing 16 rules → stateless functions                │    │
│  │   Distinguishes table-level vs column-level rules        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Core Data Structures

```python
# plugins/sqlseed-ai/src/sqlseed_ai/repair/models.py

@dataclass
class AppliedFix:
    """Record of a single repair (for Diff learning)"""
    table: str
    columns: list[str]
    fix_strategy: str
    before: dict[str, Any]
    after: dict[str, Any]
    violation_kind: str
    success: bool = True


@dataclass
class RepairResult:
    config: dict
    applied_fixes: list[AppliedFix]
    unfixable: list[ViolationReport]
    fix_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.fix_count = len(self.applied_fixes)
```

### 5.3 Repair Strategy Registry (whitelist + stateless)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py

RepairFn = Callable[[dict, ViolationReport, dict[str, Any]], dict]


REPAIR_STRATEGIES: dict[str, RepairFn] = {
    "switch_generator": _switch_generator,
    "upgrade_to_template": _upgrade_to_template,
    "normalize_params": _normalize_params,
    "break_derive_from_cycle": _break_derive_from_cycle,
    "adjust_bounds": _adjust_bounds,
    "align_fk_max_value": _align_fk_max_value,
    "isolate_date_ranges": _isolate_date_ranges,
    "semantic_upgrade": _semantic_upgrade,
    "fix_self_reference": _fix_self_reference,
    "coerce_float_to_int": _coerce_float_to_int,
    "align_group_generators": _align_group_generators,
    "expand_pool": _expand_pool,
    "add_unique_suffix": _add_unique_suffix,
}


def _switch_generator(col: dict, v: ViolationReport, ctx: dict) -> dict:
    """Stateless: switch generator (from Rule #30)"""
    target = v.fix_params.get("target", "string")
    new_col = {**col, "generator": target}
    if target == "string":
        new_col = _semantic_upgrade(new_col, v, ctx)
    new_col.pop("params", None)
    return new_col


def _upgrade_to_template(col: dict, v: ViolationReport, ctx: dict) -> dict:
    """Stateless: UNIQUE code column → template (from Rule #24 Case 5)"""
    col_name = col.get("name", "row")
    prefix = _infer_template_prefix(col_name)
    return {
        **col,
        "generator": "template",
        "params": {"template": f"{prefix}-{{sequence:04d}}"},
        "derive_from": None,
        "expression": None,
    }


def _normalize_params(col: dict, v: ViolationReport, ctx: dict) -> dict:
    """Stateless: params normalization (from Rule #14 three layers)"""
    params = col.get("params")
    gen = col.get("generator", "")
    new_col = {**col}

    # Layer 1: list → dict wrapping (choice/weighted_choice)
    if gen in {"choice", "weighted_choice"} and isinstance(params, list):
        new_col["params"] = {"choices": params}
        params = new_col["params"]

    # Layer 2: weighted_choice string-list downgrade to choice
    if gen == "weighted_choice" and isinstance(params, dict):
        choices = params.get("choices", [])
        if choices and any(isinstance(c, str) for c in choices):
            new_col["generator"] = "choice"
            gen = "choice"

    # Layer 3: choice→choices typo + whitelist stripping
    if isinstance(params, dict) and "choice" in params and "choices" not in params:
        new_col["params"] = {"choices": params["choice"]}
        params = new_col["params"]

    if gen in {"choice", "weighted_choice"} and isinstance(params, dict):
        new_col["params"] = _strip_invalid_params(params, gen)

    return new_col


# ... other strategy functions similar, all stateless ...
```

### 5.4 Legacy Rule Bridge (table-level vs column-level distinction)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/repair/legacy_bridge.py

class LegacyRuleBridge:
    """Bridge existing 16 rules to stateless functions

    Existing rules are NOT all single-column:
    - Column-level (Rule #14, #15, #18, etc.): (col) or (col, table_schema)
    - Table-level (Rule #16, #19, #22, #29): (table, table_schema)
    """

    TABLE_LEVEL_RULES = frozenset({16, 19, 22, 29})
    RULE_MAPPING = {
        14: "normalize_params",
        15: "bound_regex",
        16: "align_fk_max_value",
        17: "handle_boolean_derive",
        18: "limit_future_year",
        19: "adjust_bounds",
        20: "fix_self_reference",
        22: "isolate_date_ranges",
        23: "upgrade_phone_to_pattern",
        24: "upgrade_to_template",
        25: "downgrade_text_to_string",
        26: "coerce_float_to_int",
        27: "infer_derive_from_check",
        28: "semantic_upgrade",
        29: "break_derive_from_cycle",
        30: "switch_generator",
    }

    @staticmethod
    def extract_logic(rule_num: int, original_method: Callable) -> RepairFn:
        if rule_num in LegacyRuleBridge.TABLE_LEVEL_RULES:
            def table_wrapped(col: dict, v: ViolationReport, ctx: dict) -> dict:
                # ctx must include table_config (passed by Executor for table-level rules)
                table_cfg = ctx.get("table_config", {})
                table_schema = ctx.get("table_schema", {})
                original_method.__wrapped__(table_cfg, table_schema)
                # Return the targeted column's updated config
                return next(
                    (c for c in table_cfg.get("columns", [])
                     if c.get("name") == col.get("name")),
                    col
                )
            return table_wrapped
        else:
            def col_wrapped(col: dict, v: ViolationReport, ctx: dict) -> dict:
                new_col = {**col}
                table_schema = ctx.get("table_schema", {})
                original_method.__wrapped__(new_col, table_schema)
                return new_col
            return col_wrapped
```

### 5.5 Repair Executor

```python
# plugins/sqlseed-ai/src/sqlseed_ai/repair/executor.py

class RepairExecutor:
    """Layer 3 main executor"""

    def __init__(self, strategies: dict[str, RepairFn] | None = None):
        self._strategies = strategies or REPAIR_STRATEGIES

    def repair(self, config: dict, violations: list[ViolationReport],
               snapshot: SchemaSnapshot) -> RepairResult:
        applied_fixes: list[AppliedFix] = []
        unfixable: list[ViolationReport] = []

        sorted_violations = self._sort_by_severity(violations)

        for violation in sorted_violations:
            strategy_name = violation.fix_hint
            if strategy_name not in self._strategies:
                unfixable.append(violation)
                continue

            for table_config in config.get("tables", []):
                if table_config["name"] != violation.table:
                    continue
                cols_to_fix = self._expand_composite_cols(violation, table_config)
                for col in cols_to_fix:
                    before = {**col}
                    ctx = {
                        "table_schema": snapshot.tables.get(violation.table, {}),
                        "table_config": table_config,  # For table-level rules
                        "column_type": self._extract_col_type(col, snapshot, violation.table),
                    }
                    try:
                        after = self._strategies[strategy_name](col, violation, ctx)
                        col.clear()
                        col.update(after)
                        applied_fixes.append(AppliedFix(
                            table=violation.table,
                            columns=[col.get("name", "")],
                            fix_strategy=strategy_name,
                            before=before, after=after,
                            violation_kind=violation.severity,
                        ))
                    except Exception as e:
                        logger.warning("Repair strategy failed",
                                      strategy=strategy_name, error=str(e))
                        unfixable.append(violation)

        return RepairResult(config=config, applied_fixes=applied_fixes, unfixable=unfixable)

    def _expand_composite_cols(self, violation: ViolationReport,
                                table_config: dict) -> list[dict]:
        """[Defense 5] Composite FK coordinated degrade"""
        if not violation.is_composite:
            return [c for c in table_config.get("columns", [])
                    if c.get("name") in violation.columns]
        return [c for c in table_config.get("columns", [])
                if c.get("name") in violation.columns]
```

### 5.6 Repair Pipeline (incremental verification)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/repair/pipeline.py

class RepairPipeline:
    """Layer 2 → Layer 3 bridge with incremental verification"""

    def __init__(self, resolver: ContractResolver):
        self._validator = FastValidator(resolver)
        self._executor = RepairExecutor()

    def run(self, config: dict, snapshot: SchemaSnapshot,
            fill_error: Exception | None = None,
            dialect: str = "sqlite") -> tuple[dict, RepairResult]:
        validation = self._validator.validate(config, snapshot, fill_error, dialect)
        if validation.is_clean:
            return config, RepairResult(config=config, applied_fixes=[], unfixable=[])

        repair_result = self._executor.repair(config, validation.violations, snapshot)

        # Incremental verification: only re-validate if not all fixed
        if repair_result.applied_fixes and len(repair_result.applied_fixes) < len(validation.violations):
            # Only re-validate modified tables
            modified_tables = {f.table for f in repair_result.applied_fixes}
            modified_config = {"tables": [t for t in config.get("tables", [])
                                          if t["name"] in modified_tables]}
            revalidation = self._validator.validate(modified_config, snapshot, None, dialect)
            if not revalidation.is_clean:
                repair_result.unfixable.extend(revalidation.violations)

        return config, repair_result
```

### 5.7 Migration Strategy: Dual-Track + Gradual Switch

```python
# Phase 1 (PR 2): Dual-track parallel
class Stage3Validator:
    def validate(self, config, table_schema):
        self._apply_legacy_rules(config, table_schema)  # Old path
        violations = self._layer2_validator.validate(config, table_schema)
        self._layer3_executor.repair(config, violations)  # New path
        # Assert dual-track consistency (log discrepancies)

# Phase 2 (after PR 3): Switch to new path with legacy fallback
class Stage3Validator:
    def validate(self, config, table_schema):
        violations = self._layer2_validator.validate(config, table_schema)
        result = self._layer3_executor.repair(config, violations)
        if result.unfixable:
            self._apply_legacy_rules(config, table_schema)  # Fallback

# Phase 3 (fully validated): Delete legacy path
```

### 5.8 Testing

```python
def test_switch_generator_float_to_text():
    col = {"name": "product_name", "generator": "float", "params": {"min_value": 0}}
    v = ViolationReport(table="products", columns=["product_name"],
                        constraint_type=ConstraintType.NOT_NULL,
                        severity="semantic_error",
                        fix_hint="switch_generator", fix_params={"target": "string"})
    result = REPAIR_STRATEGIES["switch_generator"](col, v, {})
    assert result["generator"] == "string"

def test_legacy_table_level_rule_bridge():
    """Table-level rules (Rule #16/#19/#22/#29) receive table_config in ctx"""
    ...

def test_repair_introduces_new_violation_incremental():
    """Incremental verification only re-validates modified tables"""
    ...
```

---

## 6. Layer 4: LLM Healer + Progressive Degrade

### 6.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: LLM Healer + Progressive Degrade                       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4a: DependencySubgraphSplitter                           │    │
│  │   [Defense 2] Tarjan SCC merge                           │    │
│  │   [Defense 6] Megacluster weak-link breaking             │    │
│  │   Sliding window: 1-2K tokens/table                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4b: LLMHealer                                            │    │
│  │   prompt = failure reasons + contracts + composite FK    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4c: OscillationDetector                                  │    │
│  │   Error state history, A↔B alternation → terminate       │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4d: ProgressiveDegrader                                  │    │
│  │   Preserve successful + degrade failed to Core 9-level   │    │
│  │   [Defense 4] Cascade degrade (incl. derive_from)        │    │
│  │   [Defense 5] Composite FK coordinated degrade           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4e: DiffLearner                                          │    │
│  │   [Defense 7] Intercept dangerous params                 │    │
│  │   Write to local JSON registry (Defense 1)               │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Core Data Structures

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/models.py

class DegradeReason(Enum):
    LLM_TIMEOUT = "llm_timeout"
    LLM_OSCILLATION = "llm_oscillation"
    LLM_FAILURE = "llm_failure"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    CASCADE = "cascade"  # set by ProgressiveDegrader for downstream columns


@dataclass
class SubgraphTask:
    task_id: str
    tables: list[str]
    is_scc: bool = False
    parent_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealAttempt:
    attempt_num: int
    prompt_tokens: int
    elapsed_seconds: float
    success: bool
    error: str | None = None
    applied_fixes: list[AppliedFix] = field(default_factory=list)


@dataclass
class HealResult:
    config: dict
    applied_fixes: list[AppliedFix]
    degraded_columns: list[str]
    degrade_reasons: dict[str, DegradeReason]
    learned_contracts: list[ContractViolation] = field(default_factory=list)
    total_attempts: int = 0
    total_elapsed: float = 0.0
```

### 6.3 Dependency Subgraph Splitter (4a + Defense 2 + Defense 6)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/subgraph.py

import networkx as nx


class DependencySubgraphSplitter:
    """4a: Dependency subgraph splitting + Tarjan SCC + megacluster breaking"""

    MAX_SCC_SIZE = 3  # Trigger breaking above this size
    MAX_TOKENS_PER_WINDOW = 2000

    def __init__(self):
        self._broken_edges: list[tuple[str, str]] = []  # For post-repair

    def split(self, snapshot: SchemaSnapshot,
              unfixable_tables: list[str]) -> list[SubgraphTask]:
        graph = self._build_dependency_graph(snapshot, unfixable_tables)
        sccs = list(nx.strongly_connected_components(graph))
        sccs = self._break_megaclusters(sccs, graph)
        scc_graph = nx.condensation(graph, sccs)
        topo_order = list(nx.topological_sort(scc_graph))
        return self._create_sliding_window_tasks(sccs, scc_graph, topo_order)

    def _break_megaclusters(self, sccs, graph) -> list[set[str]]:
        """[Defense 6] Break SCCs larger than MAX_SCC_SIZE by removing nullable FK edges"""
        broken_sccs = []
        for scc in sccs:
            if len(scc) <= self.MAX_SCC_SIZE:
                broken_sccs.append(scc)
                continue
            nullable_edges = [(u, v) for u, v, d in graph.subgraph(scc).edges(data=True)
                              if d.get("nullable", False)]
            if not nullable_edges:
                logger.warning("Megacluster cannot be broken", size=len(scc))
                broken_sccs.append(scc)
                continue
            for u, v in nullable_edges:
                graph.remove_edge(u, v)
                self._broken_edges.append((u, v))
                logger.info("Broke megacluster edge", from_table=u, to_table=v)
            new_sccs = list(nx.strongly_connected_components(graph.subgraph(scc)))
            broken_sccs.extend(new_sccs)
        return broken_sccs

    def repair_broken_edges(self, config: dict, snapshot: SchemaSnapshot) -> None:
        """Post-repair: align nullable FK ranges after healing completes"""
        for parent_table, child_table in self._broken_edges:
            # Find FK columns between these tables
            fk_cols = self._find_fk_columns(parent_table, child_table, snapshot)
            parent_pk_range = self._extract_range(config, parent_table, fk_cols.parent_pk)
            if parent_pk_range:
                # Force child FK range to align with parent PK range
                self._force_align_range(config, child_table, fk_cols.child_fk, parent_pk_range)
                logger.info("Post-repair aligned broken edge",
                          parent=parent_table, child=child_table)
```

### 6.4 LLM Healer (4b)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/llm_healer.py

class LLMHealer:
    """4b: LLM regeneration of failing column configs"""

    def __init__(self, config: AIConfig):
        self._config = config
        self._caller = LLMCallerMixin()

    def heal(self, task: SubgraphTask, violations: list[ViolationReport],
             snapshot: SchemaSnapshot, current_config: dict) -> dict | None:
        prompt = self._build_heal_prompt(task, violations, snapshot, current_config)
        try:
            response = self._caller.call_llm(prompt)
            return self._parse_heal_response(response, task)
        except (APITimeoutError, APIConnectionError) as e:
            logger.warning("LLM heal failed", task=task.task_id, error=str(e))
            return None

    def _build_heal_prompt(self, task, violations, snapshot, current_config):
        violations_text = self._format_violations(violations)
        composite_fk_text = self._format_composite_fk(task, snapshot)
        schema_text = self._format_schema(task, snapshot)
        return [
            {"role": "system", "content": (
                "You are a database schema repair specialist. "
                "Fix ONLY the violating columns, keep others unchanged. "
                "Constraints:\n"
                "- Generator output type must match column type\n"
                "- UNIQUE columns need sufficient cardinality (use template for codes)\n"
                "- CHECK constraints must be satisfiable\n"
                "- Foreign keys must align with parent table\n"
                "- Composite foreign keys must use aligned generators\n"
            )},
            {"role": "user", "content": (
                f"Schema:\n{schema_text}\n\n"
                f"Violations to fix:\n{violations_text}\n\n"
                f"Composite FK constraints:\n{composite_fk_text}\n\n"
                "Output the fixed columns as YAML."
            )},
        ]
```

### 6.5 Oscillation Detector (4c)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/oscillation.py

class OscillationDetector:
    """4c: Detect A↔B alternation in error states"""

    def __init__(self, max_history: int = 6, partial_threshold: float = 0.8):
        self._history: list[frozenset[tuple[str, str]]] = []
        self._max_history = max_history
        self._partial_threshold = partial_threshold

    def check_and_record(self, violations: list[ViolationReport]) -> bool:
        current = frozenset(
            (col, v.severity) for v in violations for col in v.columns
        )

        # Exact oscillation
        if current in self._history:
            logger.warning("Oscillation detected", history_len=len(self._history))
            return True

        # Partial oscillation (80% overlap with historical state)
        for hist in self._history:
            overlap = len(current & hist) / max(len(current), 1)
            if overlap > self._partial_threshold:
                logger.warning("Partial oscillation detected", overlap=overlap)
                return True

        self._history.append(current)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        return False
```

### 6.6 Progressive Degrader (4d + Defense 4 + Defense 5)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/degrader.py

from sqlseed.core.mapper import ColumnMapper  # Core 9-level mapper


class ProgressiveDegrader:
    """4d: Progressive deterministic degrade"""

    def __init__(self, snapshot: SchemaSnapshot):
        self._snapshot = snapshot
        self._core_mapper = ColumnMapper()

    def degrade(self, config: dict, failed_columns: dict[str, DegradeReason],
                column_groups: list[ColumnGroup]) -> tuple[dict, list[AppliedFix]]:
        applied_fixes = []
        new_config = {"tables": []}

        for table_config in config.get("tables", []):
            new_table = {"name": table_config["name"], "columns": []}
            for col in table_config.get("columns", []):
                col_name = col.get("name", "")

                # [Defense 5] Composite FK coordinated degrade
                if self._should_degrade_group(col_name, failed_columns, column_groups):
                    group = self._find_group(col_name, column_groups)
                    if group:
                        for group_col_name in group.columns:
                            existing = next((c for c in new_table["columns"]
                                            if c.get("name") == group_col_name), None)
                            if existing:
                                continue
                            original = next((c for c in table_config["columns"]
                                            if c.get("name") == group_col_name), col)
                            degraded = self._degrade_to_core(original, table_config["name"])
                            new_table["columns"].append(degraded)
                            applied_fixes.append(self._make_fix(original, degraded, "progressive_degrade"))
                        continue

                if col_name in failed_columns:
                    degraded = self._degrade_to_core(col, table_config["name"])
                    new_table["columns"].append(degraded)
                    applied_fixes.append(self._make_fix(col, degraded, "progressive_degrade"))
                else:
                    new_table["columns"].append(col)  # Preserve successful config

            new_config["tables"].append(new_table)

        # [Defense 4] Cascade degrade (including derive_from downstream)
        self._cascade_degrade(new_config, failed_columns, applied_fixes)

        return new_config, applied_fixes

    def _degrade_to_core(self, col: dict, table_name: str) -> dict:
        """Degrade to Core 9-level mapper's type-routed generator"""
        col_name = col.get("name", "")
        col_type = self._snapshot.get_column_type(table_name, col_name)
        spec = self._core_mapper.map_column(col_name, col_type, {})
        return {
            **col,
            "generator": spec.generator,
            "params": spec.params,
            "derive_from": None,
            "expression": None,
            "_degraded": True,
        }

    def _cascade_degrade(self, config: dict, failed_columns: dict[str, DegradeReason],
                         applied_fixes: list[AppliedFix]) -> None:
        """[Defense 4] Cascade degrade: upstream degrade clears downstream locks

        Covers both physical FK dependencies AND derive_from logical dependencies.
        """
        for table_config in config.get("tables", []):
            for col in table_config.get("columns", []):
                if not col.get("_degraded"):
                    continue
                # Find downstream: physical FK + derive_from
                downstream = self._find_downstream_inclusive(col["name"], table_config["name"], config)
                for ds_table, ds_col_name in downstream:
                    ds_col = self._find_column(config, ds_table, ds_col_name)
                    if ds_col and not ds_col.get("_degraded"):
                        degraded = self._degrade_to_core(ds_col, ds_table)
                        ds_col.clear()
                        ds_col.update(degraded)
                        applied_fixes.append(self._make_fix(ds_col, degraded, "cascade_degrade"))

    def _find_downstream_inclusive(self, col_name: str, table_name: str,
                                    config: dict) -> list[tuple[str, str]]:
        """Find downstream covering BOTH FK and derive_from dependencies"""
        downstream = []
        # 1. Physical FK downstream
        downstream.extend(self._find_fk_downstream(col_name, table_name))
        # 2. derive_from logical downstream (across all tables)
        for table_config in config.get("tables", []):
            for col in table_config.get("columns", []):
                derive_from = col.get("derive_from") or []
                if isinstance(derive_from, list):
                    # Check if this column derives from the degraded column
                    if (table_config["name"] == table_name and col_name in derive_from):
                        downstream.append((table_config["name"], col.get("name", "")))
        return downstream
```

### 6.7 Diff Learner (4e + Defense 7)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/diff_learner.py

class DiffLearner:
    """4e: Extract new contracts from repair diffs"""

    def __init__(self, registry: LearnedContractsRegistry):
        self._registry = registry

    def learn(self, applied_fixes: list[AppliedFix],
              snapshot: SchemaSnapshot) -> list[ContractViolation]:
        learned = []
        for fix in applied_fixes:
            violation = self._extract_contract(fix, snapshot)
            if violation is None:
                continue
            # [Defense 7] Refuse to persist dangerous params
            if not self._is_safe_to_persist(violation):
                logger.warning("Refusing to learn unsafe contract",
                              strategy=violation.fix_strategy)
                continue
            if self._registry.add(violation):
                learned.append(violation)
                logger.info("Learned new contract",
                           generator=violation.generator,
                           column_type=violation.column_type)
        return learned

    def _extract_contract(self, fix: AppliedFix, snapshot: SchemaSnapshot) -> ContractViolation | None:
        before_gen = fix.before.get("generator", "")
        after_gen = fix.after.get("generator", "")
        if before_gen == after_gen:
            return None
        col_type = snapshot.get_column_type(fix.table, fix.columns[0] if fix.columns else "")
        return ContractViolation(
            generator=before_gen,
            column_type=col_type,
            constraints=frozenset(),
            kind=ViolationKind.SEMANTIC_ERROR,
            fix_strategy="switch_generator",
            fix_params={"target": after_gen},
            source="auto_learned",
            learned_at=datetime.now(),
            schema_hash=snapshot.schema_hash,
        )

    def _is_safe_to_persist(self, violation: ContractViolation) -> bool:
        """[Defense 7] RCE defense"""
        if violation.fix_strategy not in SAFE_FIX_STRATEGIES:
            return False
        return not any(k in violation.fix_params for k in FORBIDDEN_PERSIST_KEYS)
```

### 6.8 Layer 4 Coordinator

```python
# plugins/sqlseed-ai/src/sqlseed_ai/healer/coordinator.py

class Layer4Coordinator:
    """Layer 4 main coordinator: orchestrates 4a-4e"""

    def __init__(self, config: AIConfig, registry: LearnedContractsRegistry,
                 time_budget: float = 300.0):
        self._config = config
        self._registry = registry
        self._time_budget = time_budget
        self._splitter = DependencySubgraphSplitter()
        self._healer = LLMHealer(config)
        self._detector = OscillationDetector()
        self._degrader: ProgressiveDegrader | None = None
        self._learner = DiffLearner(registry)

    def heal(self, config: dict, unfixable: list[ViolationReport],
             snapshot: SchemaSnapshot, column_groups: list[ColumnGroup]) -> HealResult:
        start_time = time.time()
        self._degrader = ProgressiveDegrader(snapshot)
        failed_tables = list({v.table for v in unfixable})
        all_fixes: list[AppliedFix] = []
        all_degraded: list[str] = []
        degrade_reasons: dict[str, DegradeReason] = {}

        tasks = self._splitter.split(snapshot, failed_tables)

        for task in tasks:
            elapsed = time.time() - start_time
            if elapsed >= self._time_budget:
                degraded, fixes = self._degrade_task(config, task, snapshot,
                                                    column_groups,
                                                    DegradeReason.TIME_BUDGET_EXHAUSTED)
                all_degraded.extend(degraded)
                all_fixes.extend(fixes)
                degrade_reasons.update({c: DegradeReason.TIME_BUDGET_EXHAUSTED for c in degraded})
                continue

            task_violations = [v for v in unfixable if v.table in task.tables]
            healed = self._healer.heal(task, task_violations, snapshot, config)

            if healed is None:
                degraded, fixes = self._degrade_task(config, task, snapshot,
                                                    column_groups,
                                                    DegradeReason.LLM_FAILURE)
                all_degraded.extend(degraded)
                all_fixes.extend(fixes)
                degrade_reasons.update({c: DegradeReason.LLM_FAILURE for c in degraded})
                continue

            remaining_violations = self._revalidate(healed, snapshot)
            if self._detector.check_and_record(remaining_violations):
                degraded, fixes = self._degrade_task(config, task, snapshot,
                                                    column_groups,
                                                    DegradeReason.LLM_OSCILLATION)
                all_degraded.extend(degraded)
                all_fixes.extend(fixes)
                degrade_reasons.update({c: DegradeReason.LLM_OSCILLATION for c in degraded})
                continue

            self._merge_healed(config, healed, task)
            all_fixes.extend(self._make_fixes_from_heal(healed, task))

        learned = self._learner.learn(all_fixes, snapshot)

        return HealResult(
            config=config, applied_fixes=all_fixes,
            degraded_columns=all_degraded, degrade_reasons=degrade_reasons,
            learned_contracts=learned,
            total_elapsed=time.time() - start_time,
        )

    def repair_broken_edges(self, config: dict, snapshot: SchemaSnapshot) -> None:
        """Post-repair: align broken nullable FK ranges"""
        self._splitter.repair_broken_edges(config, snapshot)
```

### 6.9 Testing

```python
def test_tarjan_scc_identification():
    """Circular dependencies correctly identified as SCC"""
    ...

def test_megacluster_breaking():
    """SCC > 3 tables broken by removing nullable FK"""
    ...

def test_progressive_degrade_preserves_successful():
    """Degrade preserves successful column configs"""
    ...

def test_cascade_degrade_includes_derive_from():
    """Cascade degrade covers derive_from downstream (not just FK)"""
    ...

def test_composite_fk_coordinated_degrade():
    """Composite FK group degrades together"""
    ...

def test_refuse_to_persist_custom_function():
    """[Defense 7] Refuse to persist custom_function param"""
    ...
```

---

## 7. Layer 5: CI Property-Based Testing + Time Budget + Integration

### 7.1 Property-Based Testing

```python
# tests/property/test_contract_completeness.py

from hypothesis import given, strategies as st, settings
from sqlseed_ai.contracts.matrix import BUILTIN_VIOLATIONS, ContractResolver
from sqlseed_ai.validator import FastValidator


@st.composite
def schema_strategy(draw):
    return {
        "table": draw(st.from_regex(r"[a-z_]+", fullmatch=True)),
        "column": draw(st.from_regex(r"[a-z_]+", fullmatch=True)),
        "generator": draw(st.sampled_from(ALL_GENERATORS)),
        "column_type": draw(st.sampled_from(ALL_COLUMN_TYPES)),
        "constraints": draw(st.frozensets(st.sampled_from(ALL_CONSTRAINTS), min_size=0, max_size=3)),
        "params": draw(st.dictionaries(st.text(min_size=1), st.integers(min_value=0, max_value=1000))),
    }


@given(schema_strategy())
@settings(max_examples=500, deadline=None)
def test_contract_matrix_completeness(case):
    """Property: each combination is either COMPATIBLE or has explicit matrix entry"""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    violation = resolver.check(
        generator=case["generator"],
        column_type=case["column_type"],
        constraints=case["constraints"],
        config={"name": case["column"], "row_count": 100, **case["params"]},
    )
    if violation is None:
        # Default COMPATIBLE must actually work — use in-memory SQLite for speed
        config = make_test_config(case)
        result = try_fill_in_memory(config, n=100)  # sqlite:///:memory:
        assert result.success, (
            f"Unlisted combination failed but not in matrix: "
            f"({case['generator']}, {case['column_type']}, {case['constraints']})"
        )


@given(schema_strategy())
def test_repair_idempotence(case):
    """Property: repair is idempotent (second repair doesn't change)"""
    ...


@given(schema_strategy())
def test_degrade_always_succeeds(case):
    """Property: degrade to Core 9-level mapper always produces valid config"""
    degrader = ProgressiveDegrader(make_test_snapshot(case))
    config = make_test_config(case)
    failed = {case["column"]: DegradeReason.LLM_FAILURE}
    degraded_config, _ = degrader.degrade(config, failed, column_groups=[])
    result = try_fill_in_memory(degraded_config, n=100)
    assert result.success, f"Degrade failed: {result.error}"
```

**In-memory execution**: All `try_fill_in_memory` calls use `sqlite:///:memory:` to keep individual cases under Hypothesis's default 200ms deadline.

### 7.2 CI Integration

```yaml
# .github/workflows/contract-matrix-ci.yml
name: Contract Matrix Completeness
on: [push, pull_request]

jobs:
  property-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: pip install -e ".[dev,all]"
      - run: pytest tests/property/ -v --hypothesis-show-statistics
      - name: Report missing contracts
        if: failure()
        run: |
          echo "::error::Contract matrix has gaps. Add them to BUILTIN_VIOLATIONS."
```

### 7.3 Time Budget Controller

```python
# plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/time_budget.py

class TimeBudgetController:
    """Spans all layers"""

    def __init__(self, total_budget: float = 300.0):
        self._total_budget = total_budget
        self._start_time = time.time()
        self._table_allocations: dict[str, float] = {}

    def allocate_tables(self, table_names: list[str]) -> dict[str, float]:
        """Dynamic per-table allocation: TimeRemain / NRemain"""
        remaining = self.remaining()
        remaining_tables = [t for t in table_names if t not in self._table_allocations]
        if not remaining_tables:
            return self._table_allocations
        per_table = remaining / len(remaining_tables)
        for t in remaining_tables:
            self._table_allocations[t] = per_table
        return self._table_allocations

    def remaining(self) -> float:
        return max(0.0, self._total_budget - (time.time() - self._start_time))

    def is_exhausted(self) -> bool:
        return self.remaining() <= 0
```

### 7.4 Schema Snapshot + Optimistic Lock (Defense 8)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/validator/schema_snapshot.py
#
# Adversarial fix (C4 from cross-agent review): SchemaSnapshot lives in
# validator/, not auto_heal/, because Layer 2 (FastValidator) uses it
# heavily. Co-locating avoids a circular import (auto_heal → validator
# → auto_heal) and keeps the dependency direction clean.

class SchemaSnapshot:
    """[Defense 8] Static snapshot locked at startup"""

    def __init__(self, db_path: str | None = None, url: str | None = None):
        self.captured_at = datetime.now()
        self.tables: dict[str, TableMeta] = self._capture(db_path, url)
        self.schema_hash = self._compute_hash()
        # [Defense 3] Pre-cache constraint map (no runtime SQL queries)
        self.constraint_map = self._build_constraint_map(db_path, url)

    def _compute_hash(self) -> str:
        content = json.dumps({
            t: {"columns": c.columns, "constraints": c.constraints}
            for t, c in self.tables.items()
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def validate_against_current(self, db_path: str | None = None,
                                 url: str | None = None) -> bool:
        """[Defense 8] Optimistic lock: compare current DB schema_hash with snapshot"""
        current_hash = SchemaSnapshot(db_path, url).schema_hash
        if current_hash != self.schema_hash:
            logger.error("Schema drift detected",
                        snapshot_hash=self.schema_hash, current_hash=current_hash)
            return False
        return True


def write_yaml_with_optimistic_lock(config: dict, output_path: Path,
                                    snapshot: SchemaSnapshot,
                                    db_path: str | None = None,
                                    url: str | None = None) -> None:
    """[Defense 8] Verify schema unchanged before writing YAML"""
    if not snapshot.validate_against_current(db_path, url):
        raise SchemaDriftError(
            "Database schema has changed since analysis started. "
            "Please re-run ai-analyze to get a fresh snapshot."
        )
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
```

### 7.5 AutoHealOrchestrator (Main Integration)

```python
# plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py

class AutoHealOrchestrator:
    """Main orchestrator: Layer 1-5 coordination"""

    def __init__(self, config: AIConfig, time_budget: float = 300.0):
        self._config = config
        self._time_budget = TimeBudgetController(time_budget)
        self._registry = LearnedContractsRegistry()
        self._resolver: ContractResolver | None = None
        self._validator: FastValidator | None = None
        self._executor: RepairExecutor | None = None
        self._layer4: Layer4Coordinator | None = None

    def run(self, db_path: str | None = None, url: str | None = None,
            output_path: Path | None = None,
            max_heal_iterations: int = 3) -> dict:
        # [Defense 8] Lock schema snapshot at startup
        snapshot = SchemaSnapshot(db_path, url)
        logger.info("Schema snapshot locked", hash=snapshot.schema_hash,
                    tables=len(snapshot.tables))

        # Initialize layers
        self._resolver = ContractResolver(
            BUILTIN_VIOLATIONS,
            self._registry.filter_by_schema_hash(snapshot.schema_hash),
        )
        self._validator = FastValidator(self._resolver)
        self._executor = RepairExecutor()
        self._layer4 = Layer4Coordinator(
            self._config, self._registry, self._time_budget.remaining()
        )

        # Stage 1+2: Initial LLM generation
        config = self._initial_llm_generation(snapshot)
        self._time_budget.allocate_tables([t["name"] for t in config.get("tables", [])])

        # Heal loop
        all_fixes: list[AppliedFix] = []
        for iteration in range(max_heal_iterations):
            logger.info("Heal iteration", iteration=iteration + 1,
                       remaining_budget=self._time_budget.remaining())

            if self._time_budget.is_exhausted():
                logger.warning("Time budget exhausted, forcing degrade")
                config, fixes = self._force_degrade_all(config, snapshot)
                all_fixes.extend(fixes)
                break

            # Layer 2 validate
            validation = self._validator.validate(config, snapshot)
            if validation.is_clean:
                logger.info("All violations resolved", iteration=iteration + 1)
                break

            # Layer 3 repair
            repair_result = self._executor.repair(config, validation.violations, snapshot)
            all_fixes.extend(repair_result.applied_fixes)

            if not repair_result.unfixable:
                # [Incremental verification] All fixed, skip second global validate
                continue

            # Layer 4 LLM Healer
            heal_result = self._layer4.heal(config, repair_result.unfixable,
                                           snapshot, validation.column_groups)
            all_fixes.extend(heal_result.applied_fixes)

            if heal_result.degraded_columns:
                logger.warning("Columns degraded to Core",
                              count=len(heal_result.degraded_columns),
                              reasons=heal_result.degrade_reasons)

        # Post-repair: align broken edges (Defense 6 completion)
        self._layer4.repair_broken_edges(config, snapshot)

        # [Defense 8] Optimistic lock before write
        if output_path:
            write_yaml_with_optimistic_lock(config, output_path, snapshot, db_path, url)

        return {
            "config": config,
            "total_fixes": len(all_fixes),
            "learned_contracts": self._registry.size(),
            "elapsed": self._time_budget._total_budget - self._time_budget.remaining(),
            "schema_hash": snapshot.schema_hash,
        }
```

### 7.6 CLI Integration

```python
# plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py (modified)

@click.command("ai-analyze")
@click.option("--auto-heal", is_flag=True, default=False,
              help="Enable auto-heal loop: validate → repair → LLM heal → degrade")
@click.option("--time-budget", default=300.0, type=float,
              help="Total time budget in seconds (default: 300)")
@click.option("--max-heal-iterations", default=3, type=int,
              help="Max heal iterations before forcing degrade (default: 3)")
def ai_analyze(..., auto_heal=False, time_budget=300.0, max_heal_iterations=3):
    """AI-powered schema analysis with optional auto-heal loop."""
    config = _build_ai_config(...)

    if auto_heal:
        orchestrator = AutoHealOrchestrator(config, time_budget=time_budget)
        result = orchestrator.run(db_path=db, url=url, output_path=Path(output),
                                  max_heal_iterations=max_heal_iterations)
        click.echo(f"✓ Auto-heal completed: {result['total_fixes']} fixes applied")
        click.echo(f"  Learned contracts: {result['learned_contracts']}")
        click.echo(f"  Elapsed: {result['elapsed']:.1f}s")
    else:
        _run_legacy_staged_pipeline(...)  # Backward compatible
```

---

## 8. PR Landing Path

| PR | Content | Defenses | Risk | Effort |
|----|---------|----------|------|--------|
| **PR 1** | Layer 1 sparse matrix + Layer 2 validator + dialect parser + SchemaSnapshot + optimistic lock | 1, 3, 8 | Low (additive) | 4-5 days |
| **PR 2** | Layer 3 stateless repair engine + LegacyRuleBridge + dual-track | - | Medium (refactor) | 3-4 days |
| **PR 3** | Layer 4 LLM Healer + oscillation + progressive degrade + cascade (incl. derive_from) + composite FK | 4, 5 | Medium (new) | 4-5 days |
| **PR 4** | Tarjan SCC + megacluster breaking + broken-edge post-repair | 2, 6 | Medium (algorithm) | 3-4 days |
| **PR 5** | Diff learning + JSON registry + RCE interception + safety sandbox | 1, 7 | Low (persistence) | 2-3 days |
| **PR 6** | Layer 5 Property-Based Testing + CI + TimeBudgetController + AutoHealOrchestrator + CLI `--auto-heal` | - | Low (testing+integration) | 2-3 days |

**Total: 18-24 days**, each PR independently testable and rollbackable.

---

## 9. Compatibility

| Existing Feature | v4 Compatibility |
|-----------------|------------------|
| `sqlseed ai-analyze` (without `--auto-heal`) | ✅ Fully preserved (legacy path) |
| `sqlseed ai-analyze --staged-pipeline` | ✅ Fully preserved |
| `sqlseed ai-analyze --log-llm` | ✅ Fully preserved |
| `sqlseed ai-analyze --merge` | ✅ Fully preserved |
| Existing 16 rules | ✅ Dual-track, gradual switch |
| Existing YAML config format | ✅ Fully compatible (may have `_degraded: true` marker) |
| Core 9-level mapper | ✅ Used as degrade fallback |

---

## 10. Key Performance Indicators (KPI)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Layer 2 validation latency | < 50ms (1000 columns) | benchmark |
| Layer 3 repair latency | < 100ms (100 violations) | benchmark |
| Auto-heal convergence rate | > 95% (within 3 iterations) | Integration test stats |
| Degrade fallback success rate | 100% | Property-based testing |
| Learned contract reuse rate | > 80% | Production stats |
| Schema drift detection rate | 100% | Integration test |

---

## 11. Error Handling Summary

| Error Type | Layer | Strategy |
|-----------|-------|----------|
| Contract violation | Layer 2 | Report + Layer 3 repair |
| Repair function exception | Layer 3 | Log warning + add to unfixable |
| LLM timeout/connection failure | Layer 4 | Degrade to Core |
| Oscillation detected | Layer 4 | Immediate degrade |
| Time budget exhausted | Layer 4 | Force degrade remaining tables |
| Composite FK partial failure | Layer 4 | Group coordinated degrade |
| Upstream degrade | Layer 4 | Cascade downstream (incl. derive_from) |
| Diff learning RCE risk | Layer 4 | Refuse to persist |
| Schema drift | Startup+Write | Error + prompt re-analyze |
| JSON registry corruption | Layer 1 | Degrade to builtin-only |

---

## 12. Complete Defense Lines Summary

| # | Defense | Layer | Implementation |
|---|---------|-------|----------------|
| 1 | Safety sandbox JSON registry | Layer 1 | Whitelist strategies + schema_hash versioning |
| 2 | Tarjan SCC merge | Startup | Strongly connected components as single virtual nodes |
| 3 | Dialect-aware error parser | Layer 2 | SQLite text + PG diag + pre-cached constraint_map |
| 4 | Cascade degrade + lock rebuild | Layer 4 | Upstream degrade clears downstream (FK + derive_from) |
| 5 | Composite FK coordinator | Layer 2+4 | Bind coordinated groups + group degrade |
| 6 | Megacluster weak-link breaking | Startup | Break nullable FK edges + post-repair align |
| 7 | RCE execution-time interception | Layer 4e | Absolute blacklist custom_function/expression |
| 8 | Schema snapshot + optimistic lock | Startup+Write | Lock hash at startup + verify before write |

---

## 13. How v4 Resolves Original Concerns

| Concern | v4 Solution | Defense |
|---------|------------|---------|
| Patch-style fixes | Sparse matrix + property-based testing | - |
| Reactive problem-solving | Dev-time enumeration + CI completeness verification | - |
| High learning cost | `--auto-heal` one command | - |
| Inefficient | Layer 2/3 millisecond, 90%+ resolved here | - |
| Frequent core maintenance | Sparse matrix closed set + auto-learning | 1 |
| Small model failure loops | Oscillation detection + progressive degrade + time budget | - |
| Circular dependency deadlock | Tarjan SCC merge | 2 |
| Megacluster context overflow | Weak-link breaking | 6 |
| Multi-DB support | Dialect-aware error parser | 3 |
| Learning non-persistent | Local JSON registry | 1 |
| Upstream degrade breaks downstream | Cascade degrade + lock rebuild | 4 |
| Composite FK conflict | Coordinated generation groups + group degrade | 5 |
| RCE security vulnerability | Execution-time absolute blacklist | 7 |
| Schema drift | Static snapshot + optimistic lock | 8 |

---

## 14. Implementation Adversarial Notes

> Final-round adversarial review identified three concrete coding pitfalls.
> Implementers MUST honor these notes during PR execution to avoid subtle bugs.

### 14.1 SQLite Constraint Name Lookup Is Unreliable (Defense 3)

**Pitfall:** `SchemaSnapshot._build_constraint_map` plans to parse SQLite's
`sqlite_master` DDL to build a `constraint_name → columns/expressions` cache.
However, SQLite `CHECK` constraints are frequently **unnamed** in DDL
(e.g., `CHECK (price >= 0)` rather than `CONSTRAINT price_check CHECK (price >= 0)`),
so no `constraint_name` exists for reverse lookup.

**Implementation rule:**
- Do **NOT** parse SQLite DDL AST to reverse-lookup constraint names.
- `DialectErrorParser._parse_sqlite` MUST extract `raw_expression` directly from
  the `IntegrityError` text via regex (SQLite error text is self-contained:
  `CHECK constraint failed: sale_price >= cost_price`).
- The pre-cached `constraint_map` lookup is **PostgreSQL-only**.
- SQLite path: regex on error text → `ViolationReport(raw_expression=...)`.
- PostgreSQL path: `diag.constraint_name` → `snapshot.constraint_map[name]` →
  `ViolationReport(columns=info.columns, raw_expression=info.expression)`.

### 14.2 Cascade Degrade Cycle Termination (Defense 4)

**Pitfall:** `_cascade_degrade` walks downstream via
`_find_downstream_inclusive` (covering both FK and `derive_from`). If the
schema contains cycles (e.g., `A` derives from `B`, `B` derives from `A`;
or mutual FK references), naive recursion can stack-overflow.

**Implementation rule:**
- The existing `if ds_col and not ds_col.get("_degraded")` guard terminates
  cycles via the `_degraded` marker, BUT implementers MUST add a **second
  explicit termination guarantee**:
- `_cascade_degrade` MUST accept a `visited: set[tuple[str, str]]` parameter
  (initially empty), and check `(table_name, col_name) in visited` **before**
  recursing into a downstream column. Add to `visited` upon entry.
- This dual-layer termination (marker + visited set) guarantees 100% cycle
  safety even if the `_degraded` marker is ever cleared by a future refactor.
- Recommended signature:
  ```python
  def _cascade_degrade(
      self,
      config: dict,
      failed_columns: dict[str, DegradeReason],
      applied_fixes: list[AppliedFix],
      visited: set[tuple[str, str]] | None = None,
  ) -> None:
      visited = visited or set()
      ...
  ```

### 14.3 In-Memory Shadow FK Scan Orchestration (SQLite FK Localization)

**Pitfall:** SQLite `FOREIGN KEY constraint failed` errors do not identify
which column violated the constraint. Spec returns
`ViolationReport(columns=[], fix_hint="shadow_fk_scan")`, but the actual
localization logic must live somewhere.

**Implementation rule:**
- The shadow FK scan MUST live in the **orchestrator layer**
  (`auto_heal/orchestrator.py` or `validator/main.py`), NOT inside
  `DialectErrorParser` (which stays a pure text-parsing utility).
- Trigger condition: when `DialectErrorParser` returns a `ViolationReport`
  with `constraint_type == ConstraintType.FK` AND `columns == []`.
- Shadow scan algorithm:
  1. Identify all FK columns in the failing table from `SchemaSnapshot`.
  2. For each FK column, sample the generated values from the failed batch.
  3. Query the parent table's primary key set (from `SchemaSnapshot` cache
     or a single `SELECT` against the in-memory snapshot).
  4. The FK column whose values are NOT a subset of the parent PK set is the
     culprit; backfill `ViolationReport.columns = [culprit_col]`.
- Only after backfill can Layer 3/4 repair target the correct column.

---

**End of Design Specification**
