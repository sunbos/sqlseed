# sqlseed 全面诊断与渐进式改进 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 3 个严重 Bug、补全测试覆盖、重构 DataOrchestrator God Class、统一代码规范

**Architecture:** 渐进式 4 Phase 推进——Bug 修复 → 测试补全 → 架构重构 → 规范增强。每个 Phase 完成后运行全量测试确保无回归。

**Tech Stack:** Python 3.10+、pytest、ruff、mypy、structlog、pydantic、pluggy

---

## File Structure

### Phase 1 — Bug 修复

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `src/sqlseed/__init__.py` | 给 fill/preview 添加 transform 参数；fill_from_config 添加 FK 拓扑排序 |
| Modify | `src/sqlseed/cli/main.py` | CLI fill 传递 transform；inspect 改用公共 API |
| Modify | `src/sqlseed/core/constraints.py` | hash() → hashlib.sha256；reset_column 修复 |
| Modify | `src/sqlseed/core/relation.py` | SharedPool 添加 items()/__bool__ |
| Modify | `src/sqlseed/core/orchestrator.py` | 添加公共方法；改用 SharedPool 公共接口 |
| Modify | `src/sqlseed/generators/faker_provider.py` | generate_pattern 改用 self._rng |
| Modify | `src/sqlseed/generators/mimesis_provider.py` | generate_pattern 改用 self._rng |

### Phase 2 — 测试补全

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `tests/test_core/test_column_dag.py` | ColumnDAG + ColumnNode 测试 |
| Create | `tests/test_core/test_constraints.py` | ConstraintSolver 测试 |
| Create | `tests/test_core/test_transform.py` | load_transform 测试 |
| Modify | `tests/test_generators/test_stream.py` | 补充回溯/错误场景 |
| Modify | `tests/test_public_api.py` | fill_from_config FK 顺序测试 |
| Modify | `tests/test_cli.py` | --transform 端到端测试 |
| Delete | `test_default.py` 等 5 个根目录文件 | 清理散落调试脚本 |

### Phase 3 — 架构重构

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/sqlseed/core/enrichment.py` | EnrichmentEngine（~150 行） |
| Create | `src/sqlseed/core/unique_adjuster.py` | UniqueAdjuster（~100 行） |
| Modify | `src/sqlseed/core/orchestrator.py` | 删除迁移代码，委托新模块 |
| Modify | `src/sqlseed/core/schema.py` | 添加 detect_unique_columns |
| Create | `tests/test_core/test_enrichment.py` | EnrichmentEngine 测试 |
| Create | `tests/test_core/test_unique_adjuster.py` | UniqueAdjuster 测试 |

### Phase 4 — 规范与增强

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | 8 个 `__init__.py` + `_version.py` | 补全 from __future__ import annotations |
| Modify | `_utils/sql_safe.py`、`_utils/schema_helpers.py` | logging → structlog |
| Create | `tests/benchmarks/bench_fill.py` | 性能基准测试 |

---

## Phase 1 — Bug 修复

### Task 1: 修复 CLI transform_fn 未传递

**Files:**
- Modify: `src/sqlseed/__init__.py:33-61`（fill 函数）、`src/sqlseed/__init__.py:103-126`（preview 函数）
- Modify: `src/sqlseed/cli/main.py:62-83`（fill 命令）
- Test: `tests/test_cli.py`、`tests/test_public_api.py`

- [ ] **Step 1: 给 `sqlseed.fill()` 添加 `transform` 参数**

在 `src/sqlseed/__init__.py` 中，修改 `fill()` 函数签名，添加 `transform: str | None = None`，并传递给 `orch.fill_table()`：

```python
def fill(
    db_path: str,
    *,
    table: str,
    count: int = 1000,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    batch_size: int = 5000,
    clear_before: bool = False,
    optimize_pragma: bool = True,
    enrich: bool = False,
    transform: str | None = None,
) -> GenerationResult:
    with DataOrchestrator(
        db_path=db_path,
        provider_name=provider,
        locale=locale,
        optimize_pragma=optimize_pragma,
    ) as orch:
        return orch.fill_table(
            table_name=table,
            count=count,
            columns=columns,
            seed=seed,
            batch_size=batch_size,
            clear_before=clear_before,
            enrich=enrich,
            transform=transform,
        )
```

- [ ] **Step 2: 给 `sqlseed.preview()` 添加 `transform` 参数**

在 `src/sqlseed/__init__.py` 中，修改 `preview()` 函数签名，添加 `transform: str | None = None`，并传递给 `orch.preview_table()`：

```python
def preview(
    db_path: str,
    *,
    table: str,
    count: int = 5,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    enrich: bool = False,
    transform: str | None = None,
) -> list[dict[str, Any]]:
    with DataOrchestrator(
        db_path=db_path,
        provider_name=provider,
        locale=locale,
        optimize_pragma=False,
    ) as orch:
        return orch.preview_table(
            table_name=table,
            count=count,
            columns=columns,
            seed=seed,
            enrich=enrich,
            transform=transform,
        )
```

- [ ] **Step 3: 修改 CLI fill 命令传递 transform**

在 `src/sqlseed/cli/main.py` 中，将 `fill` 命令的 transform 处理逻辑改为直接传递 `transform_path`：

```python
@cli.command()
@click.argument("db_path", required=False)
@click.option("--table", "-t", default=None, help="Target table name")
@click.option("--count", "-n", default=1000, type=int, help="Number of rows to generate")
@click.option("--provider", "-p", default="mimesis", help="Data provider (mimesis|faker|base)")
@click.option("--locale", "-l", default="en_US", help="Locale for data generation")
@click.option("--seed", "-s", default=None, type=int, help="Random seed for reproducibility")
@click.option("--batch-size", "-b", default=5000, type=int, help="Batch size for insertion")
@click.option("--clear", is_flag=True, help="Clear table before generating")
@click.option("--config", "-c", "config_path", default=None, help="YAML/JSON config file path")
@click.option("--transform", "transform_path", default=None, help="Python transform script path")
@click.option("--snapshot", is_flag=True, help="Save generation snapshot for replay")
@click.option("--enrich", is_flag=True, help="Enrich data using existing table distribution")
def fill(
    db_path: str | None,
    table: str | None,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    config_path: str | None,
    transform_path: str | None,
    snapshot: bool,
    enrich: bool,
) -> None:
    if config_path:
        from sqlseed import fill_from_config

        results = fill_from_config(config_path)
        for result in results:
            click.echo(str(result))
        return

    if not db_path:
        raise click.UsageError("db_path is required when not using --config")
    if not table:
        raise click.UsageError("--table is required when not using --config")

    from sqlseed import fill as api_fill

    result = api_fill(
        db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        clear_before=clear,
        enrich=enrich,
        transform=transform_path,
    )
    click.echo(str(result))

    if snapshot:
        from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
        from sqlseed.config.snapshot import SnapshotManager

        config = GeneratorConfig(
            db_path=db_path,
            provider=ProviderType(provider),
            locale=locale,
            tables=[
                TableConfig(
                    name=table,
                    count=count,
                    batch_size=batch_size,
                    clear_before=clear,
                    seed=seed,
                )
            ],
        )
        manager = SnapshotManager()
        snapshot_path = manager.save(config, table, count, seed)
        click.echo(f"Snapshot saved: {snapshot_path}")
```

- [ ] **Step 4: 添加 CLI --transform 端到端测试**

在 `tests/test_cli.py` 中添加测试：

```python
def test_fill_with_transform(tmp_path):
    from click.testing import CliRunner

    from sqlseed.cli.main import cli

    db_path = str(tmp_path / "test.db")
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.close()

    transform_path = str(tmp_path / "transform.py")
    with open(transform_path, "w") as f:
        f.write("def transform_row(row, ctx):\n    row['name'] = row.get('name', '').upper()\n    return row\n")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "fill", db_path,
        "--table", "users",
        "--count", "5",
        "--provider", "base",
        "--transform", transform_path,
    ])
    assert result.exit_code == 0

    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name FROM users").fetchall()
    conn.close()
    for (name,) in rows:
        assert name == name.upper()
```

- [ ] **Step 5: 运行测试验证**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_cli.py::test_fill_with_transform -v`
Expected: PASS

- [ ] **Step 6: 运行全量测试确保无回归**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/sqlseed/__init__.py src/sqlseed/cli/main.py tests/test_cli.py
git commit -m "fix: pass transform parameter from CLI to fill_table API"
```

---

### Task 2: 修复 fill_from_config FK 顺序

**Files:**
- Modify: `src/sqlseed/__init__.py:79-100`
- Modify: `src/sqlseed/core/orchestrator.py`（添加 `get_topological_table_order` 公共方法）
- Test: `tests/test_public_api.py`

- [ ] **Step 1: 给 DataOrchestrator 添加 `get_topological_table_order` 公共方法**

在 `src/sqlseed/core/orchestrator.py` 中，在 `get_skippable_columns` 方法后添加：

```python
def get_topological_table_order(self, table_names: list[str]) -> list[str]:
    self._ensure_connected()
    return self._relation.topological_sort(table_names)
```

- [ ] **Step 2: 修改 `fill_from_config` 使用拓扑排序**

在 `src/sqlseed/__init__.py` 中，修改 `fill_from_config` 函数：

```python
def fill_from_config(config_path: str) -> list[GenerationResult]:
    config = load_config(config_path)
    results: list[GenerationResult] = []
    with DataOrchestrator(
        db_path=config.db_path,
        provider_name=config.provider.value,
        locale=config.locale,
        optimize_pragma=config.optimize_pragma,
    ) as orch:
        table_names = [tc.name for tc in config.tables]
        sorted_names = orch.get_topological_table_order(table_names)
        name_to_config = {tc.name: tc for tc in config.tables}
        for name in sorted_names:
            table_config = name_to_config[name]
            result = orch.fill_table(
                table_name=table_config.name,
                count=table_config.count,
                seed=table_config.seed,
                batch_size=table_config.batch_size,
                clear_before=table_config.clear_before,
                column_configs=table_config.columns,
                transform=table_config.transform,
                enrich=table_config.enrich,
            )
            results.append(result)
    return results
```

- [ ] **Step 3: 添加 FK 顺序测试**

在 `tests/test_public_api.py` 中添加测试：

```python
def test_fill_from_config_respects_fk_order(tmp_path):
    import sqlite3
    import yaml

    db_path = str(tmp_path / "fk_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER REFERENCES departments(id))")
    conn.close()

    config_data = {
        "db_path": db_path,
        "provider": "base",
        "tables": [
            {"name": "employees", "count": 5, "columns": [
                {"name": "name", "generator": "string"},
                {"name": "dept_id", "generator": "foreign_key", "params": {"ref_table": "departments", "ref_column": "id"}},
            ]},
            {"name": "departments", "count": 3, "columns": [
                {"name": "name", "generator": "string"},
            ]},
        ],
    }
    config_path = str(tmp_path / "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    from sqlseed import fill_from_config

    results = fill_from_config(config_path)
    assert len(results) == 2

    conn = sqlite3.connect(db_path)
    emp_rows = conn.execute("SELECT dept_id FROM employees").fetchall()
    dept_rows = conn.execute("SELECT id FROM departments").fetchall()
    conn.close()

    dept_ids = {r[0] for r in dept_rows}
    for (dept_id,) in emp_rows:
        if dept_id is not None:
            assert dept_id in dept_ids
```

- [ ] **Step 4: 运行测试验证**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_public_api.py::test_fill_from_config_respects_fk_order -v`
Expected: PASS

- [ ] **Step 5: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/sqlseed/__init__.py src/sqlseed/core/orchestrator.py tests/test_public_api.py
git commit -m "fix: use topological sort for table fill order in fill_from_config"
```

---

### Task 3: 修复 ConstraintSolver hash() 缺陷 + reset_column

**Files:**
- Modify: `src/sqlseed/core/constraints.py`
- Test: `tests/test_core/test_constraints.py`（Phase 2 创建，此处先写基础测试）

- [ ] **Step 1: 编写 ConstraintSolver hash 修复的失败测试**

创建 `tests/test_core/test_constraints.py`：

```python
from __future__ import annotations

import pytest

from sqlseed.core.constraints import ConstraintSolver, RegisterResult


class TestConstraintSolver:
    def test_check_and_register_non_unique(self):
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, unique=False) is True
        assert solver.check_and_register("col", 1, unique=False) is True

    def test_check_and_register_unique_first_time(self):
        solver = ConstraintSolver()
        assert solver.check_and_register("col", 1, unique=True) is True

    def test_check_and_register_unique_duplicate(self):
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, unique=True)
        assert solver.check_and_register("col", 1, unique=True) is False

    def test_try_register_returns_backtrack(self):
        solver = ConstraintSolver()
        solver.try_register("col", 1, unique=True)
        result = solver.try_register("col", 1, unique=True, source_columns=["src"])
        assert isinstance(result, RegisterResult)
        assert result.registered is False
        assert result.need_backtrack is True
        assert "src" in result.backtrack_targets

    def test_try_register_none_value_allowed(self):
        solver = ConstraintSolver()
        solver.try_register("col", None, unique=True)
        result = solver.try_register("col", None, unique=True)
        assert result.registered is True

    def test_unregister_then_reregister(self):
        solver = ConstraintSolver()
        solver.check_and_register("col", 1, unique=True)
        solver.unregister("col", 1)
        assert solver.check_and_register("col", 1, unique=True) is True

    def test_check_composite_unique(self):
        solver = ConstraintSolver()
        assert solver.check_composite("idx", (1, "a")) is True
        assert solver.check_composite("idx", (1, "b")) is True
        assert solver.check_composite("idx", (1, "a")) is False

    def test_check_composite_with_null(self):
        solver = ConstraintSolver()
        assert solver.check_composite("idx", (1, None)) is True
        assert solver.check_composite("idx", (1, None)) is True

    def test_reset_clears_all(self):
        solver = ConstraintSolver()
        solver.check_and_register("col1", 1, unique=True)
        solver.check_and_register("col2", 2, unique=True)
        solver.reset()
        assert solver.check_and_register("col1", 1, unique=True) is True
        assert solver.check_and_register("col2", 2, unique=True) is True

    def test_reset_column(self):
        solver = ConstraintSolver()
        solver.check_and_register("col1", 1, unique=True)
        solver.check_and_register("col2", 2, unique=True)
        solver.reset_column("col1")
        assert solver.check_and_register("col1", 1, unique=True) is True
        assert solver.check_and_register("col2", 2, unique=True) is False

    def test_probabilistic_mode_deterministic_hash(self):
        solver = ConstraintSolver(probabilistic=True, expected_count=1000)
        assert solver.check_and_register("col", 42, unique=True) is True
        assert solver.check_and_register("col", 42, unique=True) is False
        assert solver.check_and_register("col", 43, unique=True) is True

    def test_probabilistic_reset_column(self):
        solver = ConstraintSolver(probabilistic=True, expected_count=1000)
        solver.check_and_register("col", 1, unique=True)
        solver.reset_column("col")
        assert solver.check_and_register("col", 1, unique=True) is True

    def test_unregister_composite(self):
        solver = ConstraintSolver()
        solver.check_composite("idx", (1, "a"))
        solver.unregister_composite("idx", (1, "a"))
        assert solver.check_composite("idx", (1, "a")) is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_core/test_constraints.py -v`
Expected: `test_probabilistic_reset_column` FAIL（因为 `reset_column` 未清除 `_hash_seen`）

- [ ] **Step 3: 修复 ConstraintSolver**

在 `src/sqlseed/core/constraints.py` 中，替换整个文件内容：

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegisterResult:
    registered: bool = True
    need_backtrack: bool = False
    backtrack_targets: list[str] = field(default_factory=list)


class ConstraintSolver:
    """约束求解器，支持回溯和复合唯一约束

    For large datasets (>100K rows), set probabilistic=True to use
    a hash-based probabilistic set that trades a small false-positive
    rate for significantly reduced memory usage.
    """

    def __init__(
        self,
        *,
        probabilistic: bool = False,
        expected_count: int = 10000,
    ) -> None:
        self._probabilistic = probabilistic
        self._expected_count = expected_count
        self._seen: dict[str, set[Any]] = {}
        self._composite_seen: dict[str, set[tuple[Any, ...]]] = {}
        if probabilistic:
            self._hash_seen: dict[str, set[int]] = {}

    def _deterministic_hash(self, value: Any) -> int:
        data = f"{value!r}".encode("utf-8")
        return int(hashlib.sha256(data).hexdigest()[:16], 16)

    def _is_seen(self, column_name: str, value: Any) -> bool:
        if self._probabilistic:
            h = self._deterministic_hash(value)
            if column_name not in self._hash_seen:
                self._hash_seen[column_name] = set()
            if h in self._hash_seen[column_name]:
                return True
            self._hash_seen[column_name].add(h)
            return False
        if column_name not in self._seen:
            self._seen[column_name] = set()
        if value in self._seen[column_name]:
            return True
        self._seen[column_name].add(value)
        return False

    def _unregister_value(self, column_name: str, value: Any) -> None:
        if self._probabilistic:
            if column_name in self._hash_seen:
                self._hash_seen[column_name].discard(self._deterministic_hash(value))
        elif column_name in self._seen:
            self._seen[column_name].discard(value)

    def check_and_register(
        self,
        column_name: str,
        value: Any,
        unique: bool = False,
    ) -> bool:
        if unique:
            return not self._is_seen(column_name, value)
        return True

    def try_register(
        self,
        column_name: str,
        value: Any,
        unique: bool = False,
        source_columns: list[str] | None = None,
    ) -> RegisterResult:
        if not unique:
            return RegisterResult(registered=True)

        if value is None:
            return RegisterResult(registered=True)

        if self._is_seen(column_name, value):
            return RegisterResult(
                registered=False,
                need_backtrack=True,
                backtrack_targets=source_columns if source_columns else [column_name],
            )
        return RegisterResult(registered=True)

    def check_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
    ) -> bool:
        if any(v is None for v in values):
            return True

        if key_name not in self._composite_seen:
            self._composite_seen[key_name] = set()
        if values in self._composite_seen[key_name]:
            return False
        self._composite_seen[key_name].add(values)
        return True

    def unregister_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
    ) -> None:
        if key_name in self._composite_seen:
            self._composite_seen[key_name].discard(values)

    def reset(self) -> None:
        self._seen.clear()
        self._composite_seen.clear()
        if self._probabilistic:
            self._hash_seen.clear()

    def reset_column(self, column_name: str) -> None:
        self._seen.pop(column_name, None)
        if self._probabilistic:
            self._hash_seen.pop(column_name, None)

    def unregister(self, column_name: str, value: Any) -> None:
        self._unregister_value(column_name, value)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_core/test_constraints.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/sqlseed/core/constraints.py tests/test_core/test_constraints.py
git commit -m "fix: replace hash() with deterministic hashlib.sha256 in ConstraintSolver probabilistic mode"
```

---

### Task 4: 修复 SharedPool 封装 + DataOrchestrator 公共方法

**Files:**
- Modify: `src/sqlseed/core/relation.py`（SharedPool 添加 items/__bool__）
- Modify: `src/sqlseed/core/orchestrator.py`（添加公共方法、改用 SharedPool 公共接口）
- Modify: `src/sqlseed/cli/main.py`（inspect 改用公共 API）
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: 给 SharedPool 添加 items() 和 __bool__**

在 `src/sqlseed/core/relation.py` 的 `SharedPool` 类中，在 `clear()` 方法后添加：

```python
def items(self) -> dict[str, list[Any]]:
    return dict(self._pools)

def __bool__(self) -> bool:
    return bool(self._pools)
```

- [ ] **Step 2: 修改 relation.py 中 load_shared_pool 使用 items()**

在 `src/sqlseed/core/relation.py` 的 `load_shared_pool` 方法中，将：

```python
for col_name, values in shared_pool._pools.items():
```

改为：

```python
for col_name, values in shared_pool.items():
```

- [ ] **Step 3: 修改 orchestrator.py 中 _resolve_implicit_associations 使用 __bool__**

在 `src/sqlseed/core/orchestrator.py` 的 `_resolve_implicit_associations` 方法中，将：

```python
if not self._shared_pool._pools:
```

改为：

```python
if not self._shared_pool:
```

- [ ] **Step 4: 给 DataOrchestrator 添加公共方法**

在 `src/sqlseed/core/orchestrator.py` 中，在 `get_skippable_columns` 方法后添加：

```python
def get_table_names(self) -> list[str]:
    self._ensure_connected()
    return self._db.get_table_names()

def get_column_info(self, table_name: str) -> list[Any]:
    self._ensure_connected()
    return self._schema.get_column_info(table_name)

def get_foreign_keys(self, table_name: str) -> list[Any]:
    self._ensure_connected()
    return self._db.get_foreign_keys(table_name)

def get_row_count(self, table_name: str) -> int:
    self._ensure_connected()
    return self._db.get_row_count(table_name)

def map_column(self, column_info: Any) -> Any:
    return self._mapper.map_column(column_info)
```

- [ ] **Step 5: 修改 CLI inspect 命令使用公共 API**

在 `src/sqlseed/cli/main.py` 的 `inspect` 命令中，将所有 `orch._db`、`orch._schema`、`orch._mapper` 替换为公共方法：

```python
@cli.command()
@click.argument("db_path")
@click.option("--table", "-t", default=None, help="Specific table to inspect")
@click.option("--show-mapping", is_flag=True, help="Show column mapping strategy")
def inspect(db_path: str, table: str | None, show_mapping: bool) -> None:
    """Inspect database schema and column mapping strategies."""
    from rich.console import Console
    from rich.table import Table as RichTable

    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        console = Console()

        tables = [table] if table else orch.get_table_names()

        for tbl in tables:
            count = orch.get_row_count(tbl)
            columns = orch.get_column_info(tbl)
            fks = orch.get_foreign_keys(tbl)

            rich_table = RichTable(title=f"Table: {tbl} ({count} rows)")
            rich_table.add_column("Column")
            rich_table.add_column("Type")
            rich_table.add_column("Nullable")
            rich_table.add_column("PK")
            rich_table.add_column("Auto")

            if show_mapping:
                rich_table.add_column("Generator")
                rich_table.add_column("Params")

            for col in columns:
                row_data = [
                    col.name,
                    col.type,
                    "✓" if col.nullable else "✗",
                    "✓" if col.is_primary_key else "",
                    "✓" if col.is_autoincrement else "",
                ]
                if show_mapping:
                    spec = orch.map_column(col)
                    row_data.extend([spec.generator_name, str(spec.params)])
                rich_table.add_row(*row_data)

            console.print(rich_table)

            if fks:
                fk_table = RichTable(title=f"Foreign Keys: {tbl}")
                fk_table.add_column("Column")
                fk_table.add_column("Ref Table")
                fk_table.add_column("Ref Column")
                for fk in fks:
                    fk_table.add_row(fk.column, fk.ref_table, fk.ref_column)
                console.print(fk_table)
```

- [ ] **Step 6: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/sqlseed/core/relation.py src/sqlseed/core/orchestrator.py src/sqlseed/cli/main.py
git commit -m "fix: add SharedPool public interface and DataOrchestrator public methods"
```

---

### Task 5: 修复 generate_pattern 使用 import random

**Files:**
- Modify: `src/sqlseed/generators/faker_provider.py:151-157`
- Modify: `src/sqlseed/generators/mimesis_provider.py:197-203`

- [ ] **Step 1: 修复 FakerProvider.generate_pattern**

在 `src/sqlseed/generators/faker_provider.py` 中，需要先添加 `_rng` 属性（FakerProvider 当前没有）。在 `__init__` 中添加 `self._rng`，在 `set_seed` 中同步更新：

在 `__init__` 方法中，在 `self._init_faker()` 后添加：

```python
self._rng = random.Random()
```

在文件顶部添加 `import random`（与其他 import 一起）。

在 `set_seed` 方法中，在 `self._faker.seed_instance(seed)` 后添加：

```python
self._rng = random.Random(seed)
```

然后将 `generate_pattern` 修改为：

```python
def generate_pattern(self, *, regex: str) -> str:
    import rstr

    return rstr.Rstr(self._rng).xeger(regex)
```

- [ ] **Step 2: 修复 MimesisProvider.generate_pattern**

在 `src/sqlseed/generators/mimesis_provider.py` 中，需要先添加 `_rng` 属性。在 `__init__` 中添加 `self._rng`：

在 `__init__` 方法中，在 `self._init_mimesis()` 后添加：

```python
self._rng = random.Random()
```

在文件顶部添加 `import random`。

在 `set_seed` 方法中，在 `self._generic = Generic(locale_enum, seed=seed)` 后添加：

```python
self._rng = random.Random(seed)
```

然后将 `generate_pattern` 修改为：

```python
def generate_pattern(self, *, regex: str) -> str:
    import rstr

    return rstr.Rstr(self._rng).xeger(regex)
```

- [ ] **Step 3: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sqlseed/generators/faker_provider.py src/sqlseed/generators/mimesis_provider.py
git commit -m "fix: use provider _rng instead of import random in generate_pattern"
```

---

## Phase 2 — 测试补全

### Task 6: 新增 test_column_dag.py

**Files:**
- Create: `tests/test_core/test_column_dag.py`

- [ ] **Step 1: 编写 ColumnDAG 测试**

创建 `tests/test_core/test_column_dag.py`：

```python
from __future__ import annotations

import pytest

from sqlseed.config.models import ColumnConstraintsConfig, ColumnConfig
from sqlseed.core.column_dag import ColumnConstraints, ColumnDAG, ColumnNode
from sqlseed.core.mapper import GeneratorSpec


class TestColumnNode:
    def test_is_skip_true(self):
        spec = GeneratorSpec(generator_name="skip")
        node = ColumnNode(name="id", generator_spec=spec)
        assert node.is_skip is True

    def test_is_skip_false(self):
        spec = GeneratorSpec(generator_name="string")
        node = ColumnNode(name="name", generator_spec=spec)
        assert node.is_skip is False


class TestColumnDAG:
    def test_build_simple_columns(self):
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "name": GeneratorSpec(generator_name="string"),
            "email": GeneratorSpec(generator_name="email"),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs)
        names = [n.name for n in nodes]
        assert set(names) == {"id", "name", "email"}

    def test_build_with_derived_column(self):
        specs = {
            "card_number": GeneratorSpec(generator_name="string"),
            "last_eight": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="card_number", generator="string"),
            ColumnConfig(name="last_eight", derive_from="card_number", expression="value[-8:]"),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        names = [n.name for n in nodes]
        assert names.index("card_number") < names.index("last_eight")
        last_eight_node = next(n for n in nodes if n.name == "last_eight")
        assert last_eight_node.is_derived is True
        assert last_eight_node.depends_on == ["card_number"]
        assert last_eight_node.expression == "value[-8:]"

    def test_build_with_unique_constraint(self):
        specs = {
            "email": GeneratorSpec(generator_name="email"),
            "name": GeneratorSpec(generator_name="string"),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs, unique_columns={"email"})
        email_node = next(n for n in nodes if n.name == "email")
        assert email_node.constraints is not None
        assert email_node.constraints.unique is True

    def test_build_with_column_config_constraints(self):
        specs = {
            "age": GeneratorSpec(generator_name="integer"),
        }
        configs = [
            ColumnConfig(
                name="age",
                generator="integer",
                constraints=ColumnConstraintsConfig(unique=True, max_retries=50),
            ),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        age_node = next(n for n in nodes if n.name == "age")
        assert age_node.constraints is not None
        assert age_node.constraints.unique is True
        assert age_node.constraints.max_retries == 50

    def test_topological_sort_order(self):
        specs = {
            "a": GeneratorSpec(generator_name="string"),
            "b": GeneratorSpec(generator_name="__derive__"),
            "c": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="a", generator="string"),
            ColumnConfig(name="b", derive_from="a", expression="upper(value)"),
            ColumnConfig(name="c", derive_from="b", expression="lower(value)"),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        names = [n.name for n in nodes]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_circular_dependency_raises(self):
        specs = {
            "a": GeneratorSpec(generator_name="__derive__"),
            "b": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="a", derive_from="b", expression="value"),
            ColumnConfig(name="b", derive_from="a", expression="value"),
        ]
        dag = ColumnDAG()
        with pytest.raises(ValueError, match="Circular dependency"):
            dag.build(specs, configs)
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_core/test_column_dag.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_core/test_column_dag.py
git commit -m "test: add ColumnDAG and ColumnNode tests"
```

---

### Task 7: 新增 test_transform.py

**Files:**
- Create: `tests/test_core/test_transform.py`

- [ ] **Step 1: 编写 transform 测试**

创建 `tests/test_core/test_transform.py`：

```python
from __future__ import annotations

import pytest

from sqlseed.core.transform import load_transform


class TestLoadTransform:
    def test_load_valid_transform(self, tmp_path):
        script = tmp_path / "transform.py"
        script.write_text(
            "def transform_row(row, ctx):\n"
            "    row['name'] = row.get('name', '').upper()\n"
            "    return row\n"
        )
        fn = load_transform(str(script))
        result = fn({"name": "alice"}, {})
        assert result["name"] == "ALICE"

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Transform script not found"):
            load_transform(str(tmp_path / "nonexistent.py"))

    def test_load_missing_function(self, tmp_path):
        script = tmp_path / "bad_transform.py"
        script.write_text("x = 1\n")
        with pytest.raises(AttributeError, match="transform_row"):
            load_transform(str(script))

    def test_load_invalid_syntax(self, tmp_path):
        script = tmp_path / "syntax_error.py"
        script.write_text("def broken(\n")
        with pytest.raises(ImportError, match="Cannot load"):
            load_transform(str(script))
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_core/test_transform.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_core/test_transform.py
git commit -m "test: add load_transform tests"
```

---

### Task 8: 补全 test_stream.py + 清理根目录文件

**Files:**
- Modify: `tests/test_generators/test_stream.py`
- Delete: `test_default.py`、`test_default_raw.py`、`test_insert.py`、`test_raw.py`、`test_sqlite_utils.py`

- [ ] **Step 1: 补充 DataStream 测试**

在 `tests/test_generators/test_stream.py` 中添加以下测试：

```python
def test_unknown_generator_error():
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.generators.stream import DataStream, UnknownGeneratorError

    from sqlseed.core.column_dag import ColumnNode
    from sqlseed.core.expression import ExpressionEngine
    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.generators.base_provider import BaseProvider

    nodes = [ColumnNode(
        name="col",
        generator_spec=GeneratorSpec(generator_name="nonexistent_generator"),
    )]
    provider = BaseProvider()
    stream = DataStream(
        dag_nodes=nodes,
        provider=provider,
        expr_engine=ExpressionEngine(),
        constraint_solver=ConstraintSolver(),
        seed=42,
    )
    with pytest.raises(UnknownGeneratorError, match="nonexistent_generator"):
        next(stream.generate(1))


def test_generate_max_retries_exceeded():
    from sqlseed.core.column_dag import ColumnNode
    from sqlseed.core.expression import ExpressionEngine
    from sqlseed.core.constraints import ConstraintSolver, ColumnConstraints
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.generators.base_provider import BaseProvider
    from sqlseed.generators.stream import DataStream

    nodes = [ColumnNode(
        name="col",
        generator_spec=GeneratorSpec(generator_name="integer", params={"min_value": 1, "max_value": 1}),
        constraints=ColumnConstraints(unique=True, max_retries=2),
    )]
    provider = BaseProvider()
    stream = DataStream(
        dag_nodes=nodes,
        provider=provider,
        expr_engine=ExpressionEngine(),
        constraint_solver=ConstraintSolver(),
        seed=42,
    )
    with pytest.raises(RuntimeError, match="maximum retries"):
        next(stream.generate(3))
```

- [ ] **Step 2: 运行新增测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_generators/test_stream.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 删除根目录散落文件**

```bash
rm test_default.py test_default_raw.py test_insert.py test_raw.py test_sqlite_utils.py
```

- [ ] **Step 4: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_generators/test_stream.py
git rm test_default.py test_default_raw.py test_insert.py test_raw.py test_sqlite_utils.py
git commit -m "test: add DataStream error tests and clean up root-level debug scripts"
```

---

## Phase 3 — 架构重构

### Task 9: 提取 EnrichmentEngine

**Files:**
- Create: `src/sqlseed/core/enrichment.py`
- Modify: `src/sqlseed/core/orchestrator.py`（删除迁移代码，委托 EnrichmentEngine）
- Create: `tests/test_core/test_enrichment.py`

- [ ] **Step 1: 创建 EnrichmentEngine**

创建 `src/sqlseed/core/enrichment.py`，将 `DataOrchestrator` 中的以下内容迁移：
- `_ENUM_NAME_PATTERNS` → `EnrichmentEngine.ENUM_NAME_PATTERNS`
- `_SMALL_INT_TYPES` → `EnrichmentEngine.SMALL_INT_TYPES`
- `_is_enumeration_column()` → `EnrichmentEngine.is_enumeration_column()`
- `_apply_enrich()` → `EnrichmentEngine.apply()`
- `_build_enriched_spec()` → `EnrichmentEngine._build_enriched_spec()`

```python
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.core.schema import SchemaInferrer

logger = get_logger(__name__)


class EnrichmentEngine:
    ENUM_NAME_PATTERNS: ClassVar[list[str]] = [
        r"^[bB]y[A-Za-z]",
        r".*_type$",
        r".*_status$",
        r"^is_.*",
        r"^has_.*",
        r"^can_.*",
        r".*_level$",
        r".*_category$",
        r".*_class$",
        r".*_flag$",
        r".*_kind$",
        r".*_grade$",
        r".*_rank$",
        r".*_tier$",
        r".*_mode$",
        r".*_stage$",
        r".*_phase$",
        r".*_state$",
        r".*_group$",
    ]

    SMALL_INT_TYPES: ClassVar[tuple[str, ...]] = ("INT8", "INT16", "TINYINT", "SMALLINT")

    def __init__(self, db: DatabaseAdapter, mapper: ColumnMapper, schema: SchemaInferrer) -> None:
        self._db = db
        self._mapper = mapper
        self._schema = schema

    def is_enumeration_column(
        self,
        col_name: str,
        col_info: Any,
        distinct_count: int,
        total_rows: int,
        is_unique: bool,
    ) -> bool:
        if is_unique:
            return False
        if total_rows == 0 or distinct_count == 0:
            return False
        cardinality_ratio = distinct_count / total_rows
        name_matches_enum = any(re.match(p, col_name) for p in self.ENUM_NAME_PATTERNS)
        col_type_upper = col_info.type.upper() if col_info and hasattr(col_info, "type") else ""
        is_small_int = any(t in col_type_upper for t in self.SMALL_INT_TYPES)
        return (
            (name_matches_enum and cardinality_ratio < 0.1)
            or (is_small_int and cardinality_ratio < 0.1)
            or (distinct_count <= 10 and cardinality_ratio < 0.05)
            or (
                distinct_count <= 30
                and cardinality_ratio < 0.01
                and "CHAR" not in col_type_upper
                and "TEXT" not in col_type_upper
            )
        )

    def apply(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        column_infos: list[Any],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        has_enrich = any(s.generator_name == "__enrich__" for s in specs.values())
        if not has_enrich:
            return specs

        unique_columns = unique_columns or set()
        row_count = self._db.get_row_count(table_name)
        if row_count == 0:
            for col_name, spec in specs.items():
                if spec.generator_name == "__enrich__":
                    specs[col_name] = GeneratorSpec(generator_name="skip")
            return specs

        for col_name, spec in list(specs.items()):
            if spec.generator_name != "__enrich__":
                continue
            is_unique = col_name in unique_columns
            specs[col_name] = self._build_enriched_spec(table_name, col_name, spec, column_infos, is_unique)

        return specs

    def _build_enriched_spec(
        self,
        table_name: str,
        col_name: str,
        spec: GeneratorSpec,
        column_infos: list[Any],
        is_unique: bool = False,
    ) -> GeneratorSpec:
        col_info = next((c for c in column_infos if c.name == col_name), None)

        try:
            values = self._db.get_column_values(table_name, col_name, limit=10000)
        except Exception:
            return GeneratorSpec(generator_name="skip")

        if not values:
            return GeneratorSpec(generator_name="skip")

        null_count = sum(1 for v in values if v is None)
        non_null_values = [v for v in values if v is not None]
        null_ratio = round(null_count / len(values), 3) if values else 0.0

        if not non_null_values:
            return GeneratorSpec(generator_name="skip")

        if col_info and not col_info.nullable:
            null_ratio = 0.0

        if is_unique:
            null_ratio = 0.0

        distinct_values = list(set(non_null_values))
        distinct_count = len(distinct_values)
        row_count = self._db.get_row_count(table_name)

        if self.is_enumeration_column(col_name, col_info, distinct_count, row_count, is_unique):
            choices = distinct_values
            if col_info and "INT" in col_info.type.upper():
                choices = [int(v) if isinstance(v, (int, float, str)) else v for v in choices]
            return GeneratorSpec(
                generator_name="choice",
                params={"choices": choices},
                null_ratio=null_ratio,
            )

        if col_info:
            fallback_spec = self._mapper.map_column(col_info, force_type_infer=True)
            if fallback_spec.generator_name != "skip":
                return GeneratorSpec(
                    generator_name=fallback_spec.generator_name,
                    params=fallback_spec.params,
                    null_ratio=null_ratio,
                    provider=fallback_spec.provider,
                )

        return GeneratorSpec(generator_name="skip")
```

- [ ] **Step 2: 修改 DataOrchestrator 委托 EnrichmentEngine**

在 `src/sqlseed/core/orchestrator.py` 中：

1. 添加导入：`from sqlseed.core.enrichment import EnrichmentEngine`
2. 在 `__init__` 中添加：`self._enrichment: EnrichmentEngine | None = None`
3. 在 `_ensure_connected` 末尾初始化：`self._enrichment = EnrichmentEngine(self._db, self._mapper, self._schema)`
4. 将 `fill_table` 中的 `self._apply_enrich(...)` 改为 `self._enrichment.apply(...)`
5. 将 `preview_table` 中的 `self._apply_enrich(...)` 改为 `self._enrichment.apply(...)`
6. 删除 `_ENUM_NAME_PATTERNS`、`_SMALL_INT_TYPES`、`_is_enumeration_column`、`_apply_enrich`、`_build_enriched_spec` 方法

- [ ] **Step 3: 创建 EnrichmentEngine 测试**

创建 `tests/test_core/test_enrichment.py`：

```python
from __future__ import annotations

import sqlite3

import pytest

from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter


class TestEnrichmentEngine:
    def test_apply_no_enrich_specs(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        mapper = ColumnMapper()
        schema = SchemaInferrer(adapter)
        engine = EnrichmentEngine(adapter, mapper, schema)

        specs = {"name": GeneratorSpec(generator_name="string")}
        result = engine.apply("t", specs, schema.get_column_info("t"))
        assert result["name"].generator_name == "string"

    def test_apply_empty_table_skips_enrich(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT)")
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        mapper = ColumnMapper()
        schema = SchemaInferrer(adapter)
        engine = EnrichmentEngine(adapter, mapper, schema)

        specs = {"status": GeneratorSpec(generator_name="__enrich__")}
        result = engine.apply("t", specs, schema.get_column_info("t"))
        assert result["status"].generator_name == "skip"

    def test_is_enumeration_column_by_name(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        mapper = ColumnMapper()
        schema = SchemaInferrer(adapter)
        engine = EnrichmentEngine(adapter, mapper, schema)

        assert engine.is_enumeration_column("user_status", None, 3, 100, False) is True
        assert engine.is_enumeration_column("email", None, 50, 100, False) is False
        assert engine.is_enumeration_column("id", None, 100, 100, True) is False
```

- [ ] **Step 4: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/sqlseed/core/enrichment.py src/sqlseed/core/orchestrator.py tests/test_core/test_enrichment.py
git commit -m "refactor: extract EnrichmentEngine from DataOrchestrator"
```

---

### Task 10: 提取 UniqueAdjuster + detect_unique_columns

**Files:**
- Create: `src/sqlseed/core/unique_adjuster.py`
- Modify: `src/sqlseed/core/schema.py`（添加 detect_unique_columns）
- Modify: `src/sqlseed/core/orchestrator.py`（删除迁移代码，委托新模块）
- Create: `tests/test_core/test_unique_adjuster.py`

- [ ] **Step 1: 创建 UniqueAdjuster**

创建 `src/sqlseed/core/unique_adjuster.py`，将 `DataOrchestrator._adjust_specs_for_unique` 迁移：

```python
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

logger = get_logger(__name__)


class UniqueAdjuster:
    def __init__(self, mapper: ColumnMapper) -> None:
        self._mapper = mapper

    def adjust(
        self,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str],
        count: int,
        column_infos: list[ColumnInfo] | None = None,
    ) -> dict[str, GeneratorSpec]:
        for col_name in unique_columns:
            if col_name not in specs:
                continue
            spec = specs[col_name]
            if spec.generator_name == "skip":
                continue

            if spec.generator_name == "string":
                specs[col_name] = self._adjust_string(spec, col_name, count, column_infos)
            elif spec.generator_name == "integer":
                specs[col_name] = self._adjust_integer(spec, col_name, count, column_infos)
            elif spec.generator_name == "choice":
                specs = self._adjust_choice(specs, spec, col_name, count, column_infos)

        return specs

    def _adjust_string(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
    ) -> GeneratorSpec:
        params = dict(spec.params)
        charset_size = 62
        if params.get("charset") == "digits":
            charset_size = 10
        elif params.get("charset") == "alpha":
            charset_size = 52

        max_length = params.get("max_length", 50)
        min_needed = max(1, math.ceil(math.log(max(count * count * 50, 1)) / math.log(charset_size)))
        current_min = params.get("min_length", 1)
        params["min_length"] = max(current_min, min_needed)

        if params["min_length"] > max_length:
            if params.get("charset") is None:
                params["charset"] = "alphanumeric"
                charset_size = 62
                min_needed = max(1, math.ceil(math.log(max(count * count * 50, 1)) / math.log(charset_size)))
                params["min_length"] = max(current_min, min_needed)
            if params["min_length"] > max_length:
                logger.warning(
                    "Cannot guarantee uniqueness for VARCHAR(%d) with count=%d",
                    max_length,
                    count,
                    column=col_name,
                )
                params["max_length"] = max(params["min_length"], max_length)
        elif params["max_length"] < params["min_length"]:
            params["max_length"] = params["min_length"]

        return GeneratorSpec(
            generator_name=spec.generator_name,
            params=params,
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )

    def _adjust_integer(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
    ) -> GeneratorSpec:
        params = dict(spec.params)
        min_val = params.get("min_value", 0)
        max_val = params.get("max_value", 999999)
        if max_val - min_val < count * 10:
            col_info = next((c for c in (column_infos or []) if c.name == col_name), None)
            if col_info:
                col_type_upper = col_info.type.upper()
                if "INT8" in col_type_upper and count > 255:
                    logger.warning(
                        "INT8 column with UNIQUE constraint cannot guarantee uniqueness for count > 255",
                        column=col_name,
                        count=count,
                    )
                elif "INT16" in col_type_upper and count > 65535:
                    logger.warning(
                        "INT16 column with UNIQUE constraint cannot guarantee uniqueness for count > 65535",
                        column=col_name,
                        count=count,
                    )
            params["max_value"] = min_val + count * 10
        return GeneratorSpec(
            generator_name=spec.generator_name,
            params=params,
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )

    def _adjust_choice(
        self,
        specs: dict[str, GeneratorSpec],
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
    ) -> dict[str, GeneratorSpec]:
        choices = spec.params.get("choices", [])
        if len(choices) < count:
            col_info = None
            if column_infos:
                col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info:
                fallback = self._mapper.map_column(col_info, force_type_infer=True)
                if fallback.generator_name not in ("skip", "choice"):
                    specs[col_name] = GeneratorSpec(
                        generator_name=fallback.generator_name,
                        params=fallback.params,
                        null_ratio=spec.null_ratio,
                        provider=fallback.provider,
                    )
                    specs = self.adjust(specs, {col_name}, count, column_infos)
        return specs
```

- [ ] **Step 2: 给 SchemaInferrer 添加 detect_unique_columns**

在 `src/sqlseed/core/schema.py` 中，添加方法：

```python
def detect_unique_columns(self, table_name: str) -> set[str]:
    unique_cols: set[str] = set()
    try:
        indexes = self.get_index_info(table_name)
        for idx in indexes:
            if idx.unique and len(idx.columns) == 1:
                unique_cols.add(idx.columns[0])
    except Exception:
        logger.debug("Failed to detect unique constraints from indexes", table_name=table_name)

    try:
        pks = self._db.get_primary_keys(table_name)
        column_infos = self.get_column_info(table_name)
        autoincrement_pks = {c.name for c in column_infos if c.is_primary_key and c.is_autoincrement}
        for pk in pks:
            if pk not in autoincrement_pks:
                unique_cols.add(pk)
    except Exception:
        logger.debug("Failed to detect PK unique constraints", table_name=table_name)

    return unique_cols
```

- [ ] **Step 3: 修改 DataOrchestrator 委托新模块**

在 `src/sqlseed/core/orchestrator.py` 中：

1. 添加导入：`from sqlseed.core.unique_adjuster import UniqueAdjuster`
2. 在 `__init__` 中添加：`self._unique_adjuster = UniqueAdjuster(self._mapper)`
3. 将 `fill_table` 中的 `self._detect_unique_columns(table_name)` 改为 `self._schema.detect_unique_columns(table_name)`
4. 将 `self._adjust_specs_for_unique(...)` 改为 `self._unique_adjuster.adjust(...)`
5. 同样修改 `preview_table`
6. 删除 `_detect_unique_columns`、`_adjust_specs_for_unique` 方法

- [ ] **Step 4: 创建 UniqueAdjuster 测试**

创建 `tests/test_core/test_unique_adjuster.py`：

```python
from __future__ import annotations

from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.unique_adjuster import UniqueAdjuster


class TestUniqueAdjuster:
    def test_adjust_string_increases_min_length(self):
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"code": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, {"code"}, 10000)
        assert result["code"].params["min_length"] > 1

    def test_adjust_integer_expands_range(self):
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 100})}
        result = adjuster.adjust(specs, {"id"}, 10000)
        assert result["id"].params["max_value"] > 100

    def test_adjust_skip_column_unchanged(self):
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"name": GeneratorSpec(generator_name="string", params={"min_length": 5, "max_length": 50})}
        result = adjuster.adjust(specs, {"name"}, 100)
        assert result["name"].params["min_length"] == 5

    def test_adjust_skips_skip_generator(self):
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="skip")}
        result = adjuster.adjust(specs, {"id"}, 1000)
        assert result["id"].generator_name == "skip"
```

- [ ] **Step 5: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/sqlseed/core/unique_adjuster.py src/sqlseed/core/schema.py src/sqlseed/core/orchestrator.py tests/test_core/test_unique_adjuster.py
git commit -m "refactor: extract UniqueAdjuster and detect_unique_columns from DataOrchestrator"
```

---

## Phase 4 — 规范与增强

### Task 11: 代码规范修复

**Files:**
- Modify: 8 个 `__init__.py` + `_version.py`
- Modify: `_utils/sql_safe.py`、`_utils/schema_helpers.py`

- [ ] **Step 1: 补全 `from __future__ import annotations`**

在以下 9 个文件的第一行添加 `from __future__ import annotations`：

1. `src/sqlseed/plugins/__init__.py`
2. `src/sqlseed/generators/__init__.py`
3. `src/sqlseed/database/__init__.py`
4. `src/sqlseed/core/__init__.py`
5. `src/sqlseed/config/__init__.py`
6. `src/sqlseed/cli/__init__.py`
7. `src/sqlseed/_utils/__init__.py`
8. `src/sqlseed/_version.py`

注意：仅当文件包含 Python 代码（非空 `__init__.py`）时才添加。

- [ ] **Step 2: 统一日志系统**

在 `src/sqlseed/_utils/sql_safe.py` 中，将：

```python
import logging
logger = logging.getLogger(__name__)
```

替换为：

```python
from sqlseed._utils.logger import get_logger
logger = get_logger(__name__)
```

在 `src/sqlseed/_utils/schema_helpers.py` 中做同样替换。

- [ ] **Step 3: 运行 ruff + mypy**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m ruff check src/ && python3 -m mypy src/sqlseed/`
Expected: 无错误

- [ ] **Step 4: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/sqlseed/
git commit -m "style: add future annotations and unify logging to structlog"
```

---

### Task 12: 性能基准测试框架

**Files:**
- Create: `tests/benchmarks/__init__.py`
- Create: `tests/benchmarks/bench_fill.py`
- Modify: `pyproject.toml`（添加 pytest-benchmark 到 dev 依赖）

- [ ] **Step 1: 添加 pytest-benchmark 依赖**

在 `pyproject.toml` 的 `[project.optional-dependencies].dev` 列表中添加 `"pytest-benchmark>=4.0"`。

- [ ] **Step 2: 创建基准测试**

创建 `tests/benchmarks/__init__.py`（空文件）和 `tests/benchmarks/bench_fill.py`：

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sqlseed import fill


@pytest.fixture
def bench_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "bench.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER, created_at TEXT)"
    )
    conn.close()
    return db_path


@pytest.mark.benchmark(group="fill")
def test_bench_fill_1k_rows(benchmark, bench_db):
    benchmark(fill, bench_db, table="users", count=1000, provider="base", clear_before=True)


@pytest.mark.benchmark(group="fill")
def test_bench_fill_10k_rows(benchmark, bench_db):
    benchmark(fill, bench_db, table="users", count=10000, provider="base", clear_before=True)


@pytest.mark.benchmark(group="fill")
def test_bench_preview_5_rows(benchmark, bench_db):
    from sqlseed import preview

    benchmark(preview, bench_db, table="users", count=5, provider="base")
```

- [ ] **Step 3: 运行基准测试验证**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/benchmarks/bench_fill.py -v --benchmark-disable`
Expected: PASS（使用 `--benchmark-disable` 跳过实际基准测量，仅验证测试可运行）

- [ ] **Step 4: Commit**

```bash
git add tests/benchmarks/ pyproject.toml
git commit -m "feat: add performance benchmark framework"
```

---

## 最终验证

### Task 13: 全量验证

- [ ] **Step 1: 运行全量测试 + 覆盖率**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --cov=sqlseed --cov-report=term-missing --tb=short -q`

验证：
- 全部测试 PASS
- 关键模块覆盖率 ≥ 85%：`constraints.py`、`column_dag.py`、`transform.py`、`stream.py`
- 新模块覆盖率 ≥ 90%：`enrichment.py`、`unique_adjuster.py`

- [ ] **Step 2: 运行 ruff check**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m ruff check src/ tests/`
Expected: 无错误

- [ ] **Step 3: 运行 mypy**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m mypy src/sqlseed/`
Expected: 无错误

- [ ] **Step 4: 验证 DataOrchestrator 行数**

Run: `wc -l src/sqlseed/core/orchestrator.py`
Expected: ≤ 550 行

- [ ] **Step 5: 验证根目录无散落测试文件**

Run: `ls test_*.py 2>/dev/null || echo "No stray test files"`
Expected: "No stray test files"
