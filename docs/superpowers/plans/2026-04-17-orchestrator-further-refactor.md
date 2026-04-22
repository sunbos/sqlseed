# DataOrchestrator 进一步拆分 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 DataOrchestrator 从 616 行降至 ~432 行，提取 PluginMediator 和扩展 RelationResolver

**Architecture:** 提取两个维度的非编排职责：1) AI/模板池/批量变换等插件交互逻辑 → PluginMediator；2) FK 解析/隐式关联/SharedPool 注册 → RelationResolver。DataOrchestrator 只保留编排调用链。

**Tech Stack:** Python 3.10+、pytest、ruff、structlog、pluggy

---

## File Structure

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/sqlseed/core/plugin_mediator.py` | PluginMediator（~130 行） |
| Modify | `src/sqlseed/core/relation.py` | 添加 resolve_foreign_keys/resolve_implicit_associations/register_shared_pool |
| Modify | `src/sqlseed/core/orchestrator.py` | 删除迁移代码，委托新模块 |
| Create | `tests/test_core/test_plugin_mediator.py` | PluginMediator 测试 |
| Modify | `tests/test_relation.py` | 扩展 FK 解析/隐式关联/SharedPool 注册测试 |

---

## Task 1: 创建 PluginMediator

**Files:**
- Create: `src/sqlseed/core/plugin_mediator.py`
- Create: `tests/test_core/test_plugin_mediator.py`

- [ ] **Step 1: 创建 PluginMediator 模块**

创建 `src/sqlseed/core/plugin_mediator.py`：

```python
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


class PluginMediator:
    AI_APPLICABLE_GENERATORS: ClassVar[frozenset[str]] = frozenset(
        {"string", "integer", "date", "datetime", "choice"}
    )

    def __init__(
        self,
        plugins: PluginManager,
        db: DatabaseAdapter,
        schema: SchemaInferrer,
    ) -> None:
        self._plugins = plugins
        self._db = db
        self._schema = schema

    def apply_ai_suggestions(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]:
        unmatched_cols = [
            col
            for col in column_infos
            if specs.get(col.name) is not None
            and specs[col.name].generator_name in self.AI_APPLICABLE_GENERATORS
            and not col.is_primary_key
            and not col.is_autoincrement
            and col.default is None
        ]
        if not unmatched_cols:
            return specs

        try:
            fks = self._db.get_foreign_keys(table_name)
            all_tables = self._db.get_table_names()
            indexes = self._schema.get_index_info(table_name)
            sample_data = self._schema.get_sample_data(table_name, limit=5)

            ai_result = self._plugins.hook.sqlseed_ai_analyze_table(
                table_name=table_name,
                columns=column_infos,
                indexes=[{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                sample_data=sample_data,
                foreign_keys=fks,
                all_table_names=all_tables,
            )

            if ai_result and isinstance(ai_result, dict):
                ai_columns = ai_result.get("columns", [])
                if isinstance(ai_columns, list):
                    for col_cfg in ai_columns:
                        col_name = col_cfg.get("name") if isinstance(col_cfg, dict) else None
                        if col_name and col_name in specs:
                            gen = col_cfg.get("generator")
                            if gen and gen != "skip":
                                derive_from = col_cfg.get("derive_from")
                                expression = col_cfg.get("expression")

                                if derive_from and expression:
                                    specs[col_name] = GeneratorSpec(
                                        generator_name="__derive__",
                                        params={"derive_from": derive_from, "expression": expression},
                                    )
                                else:
                                    params = col_cfg.get("params", {})
                                    if isinstance(params, dict):
                                        specs[col_name] = GeneratorSpec(
                                            generator_name=gen,
                                            params=params,
                                        )

        except Exception as e:
            logger.debug("AI suggestions not available", table_name=table_name, error=str(e))

        return specs

    def apply_template_pool(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
        count: int,
    ) -> dict[str, GeneratorSpec]:
        for col_name, spec in list(specs.items()):
            if spec.generator_name != "string":
                continue
            col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info is None or col_info.is_primary_key or col_info.is_autoincrement:
                continue
            if col_info.default is not None:
                continue

            sample_data_for_col: list[Any] = []
            with contextlib.suppress(Exception):
                sample_data_for_col = self._db.get_column_values(table_name, col_name, limit=10)

            template_values = self._plugins.hook.sqlseed_pre_generate_templates(
                table_name=table_name,
                column_name=col_name,
                column_type=col_info.type,
                count=min(count, 50),
                sample_data=sample_data_for_col,
            )
            if template_values:
                specs[col_name] = GeneratorSpec(
                    generator_name="foreign_key",
                    params={
                        "ref_table": "__template_pool__",
                        "ref_column": col_name,
                        "strategy": "random",
                        "_ref_values": template_values,
                    },
                )
        return specs

    def apply_batch_transforms(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = self._plugins.hook.sqlseed_transform_batch(
            table_name=table_name,
            batch=batch,
        )
        current = batch
        if results:
            for r in results:
                if r is not None:
                    current = r
        return current
```

- [ ] **Step 2: 创建 PluginMediator 测试**

创建 `tests/test_core/test_plugin_mediator.py`：

```python
from __future__ import annotations

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.plugin_mediator import PluginMediator
from sqlseed.plugins.manager import PluginManager


class TestPluginMediator:
    def test_ai_applicable_generators(self):
        assert "string" in PluginMediator.AI_APPLICABLE_GENERATORS
        assert "integer" in PluginMediator.AI_APPLICABLE_GENERATORS
        assert "email" not in PluginMediator.AI_APPLICABLE_GENERATORS

    def test_apply_ai_suggestions_no_unmatched(self, tmp_path):
        import sqlite3

        from sqlseed.core.schema import SchemaInferrer
        from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        schema = SchemaInferrer(adapter)
        plugins = PluginManager()
        plugins.load_plugins()

        mediator = PluginMediator(plugins, adapter, schema)
        specs = {"name": GeneratorSpec(generator_name="email")}
        result = mediator.apply_ai_suggestions("t", schema.get_column_info("t"), specs)
        assert result["name"].generator_name == "email"

    def test_apply_batch_transforms_no_hooks(self, tmp_path):
        import sqlite3

        from sqlseed.core.schema import SchemaInferrer
        from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        schema = SchemaInferrer(adapter)
        plugins = PluginManager()
        plugins.load_plugins()

        mediator = PluginMediator(plugins, adapter, schema)
        batch = [{"name": "alice"}, {"name": "bob"}]
        result = mediator.apply_batch_transforms("t", batch)
        assert result == batch

    def test_apply_template_pool_no_hooks(self, tmp_path):
        import sqlite3

        from sqlseed.core.schema import SchemaInferrer
        from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        schema = SchemaInferrer(adapter)
        plugins = PluginManager()
        plugins.load_plugins()

        mediator = PluginMediator(plugins, adapter, schema)
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator.apply_template_pool("t", schema.get_column_info("t"), specs, 10)
        assert result["name"].generator_name == "string"
```

- [ ] **Step 3: 运行测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_core/test_plugin_mediator.py -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sqlseed/core/plugin_mediator.py tests/test_core/test_plugin_mediator.py
git commit -m "feat: add PluginMediator for AI/template/batch plugin interactions"
```

---

## Task 2: 扩展 RelationResolver

**Files:**
- Modify: `src/sqlseed/core/relation.py`
- Modify: `tests/test_relation.py`

- [ ] **Step 1: 给 RelationResolver 添加 resolve_foreign_keys 方法**

在 `src/sqlseed/core/relation.py` 的 `RelationResolver` 类中，在 `load_shared_pool` 方法后添加：

```python
def resolve_foreign_keys(
    self,
    table_name: str,
    specs: dict[str, GeneratorSpec],
) -> dict[str, GeneratorSpec]:
    for col_name, spec in specs.items():
        if spec.generator_name == "foreign_key_or_integer":
            fk_info = self.get_fk_info(table_name, col_name)
            if fk_info:
                ref_values = self.resolve_foreign_key_values(table_name, col_name)
                new_spec = GeneratorSpec(
                    generator_name="foreign_key",
                    params={
                        "ref_table": fk_info.ref_table,
                        "ref_column": fk_info.ref_column,
                        "strategy": "random",
                        "_ref_values": ref_values,
                    },
                    null_ratio=spec.null_ratio,
                    provider=spec.provider,
                )
                specs[col_name] = new_spec
            else:
                specs[col_name] = GeneratorSpec(
                    generator_name="integer",
                    params={"min_value": 1, "max_value": 999999},
                    null_ratio=spec.null_ratio,
                    provider=spec.provider,
                )

        elif spec.generator_name == "foreign_key":
            if "ref_table" in spec.params:
                ref_values = self._db.get_column_values(
                    spec.params["ref_table"],
                    spec.params["ref_column"],
                )
                spec.params["_ref_values"] = ref_values

    return self.resolve_implicit_associations(table_name, specs)
```

需要在 `relation.py` 顶部添加导入：

```python
from sqlseed.core.mapper import GeneratorSpec
```

- [ ] **Step 2: 给 RelationResolver 添加 resolve_implicit_associations 方法**

在 `resolve_foreign_keys` 方法后添加：

```python
def resolve_implicit_associations(
    self,
    table_name: str,
    specs: dict[str, GeneratorSpec],
) -> dict[str, GeneratorSpec]:
    if not self._shared_pool:
        return specs

    for col_name, spec in list(specs.items()):
        if spec.generator_name != "foreign_key_or_integer":
            continue
        if not self._shared_pool.has(col_name):
            continue

        pool_values = self._shared_pool.get(col_name)
        if not pool_values:
            continue

        specs[col_name] = GeneratorSpec(
            generator_name="foreign_key",
            params={
                "ref_table": "__shared_pool__",
                "ref_column": col_name,
                "strategy": "random",
                "_ref_values": pool_values,
            },
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )
        logger.debug(
            "Resolved implicit association via SharedPool",
            table_name=table_name,
            column_name=col_name,
            pool_size=len(pool_values),
        )

    return specs
```

- [ ] **Step 3: 给 RelationResolver 添加 register_shared_pool 方法**

在 `resolve_implicit_associations` 方法后添加：

```python
def register_shared_pool(
    self,
    table_name: str,
    generator_specs: dict[str, GeneratorSpec],
) -> None:
    for col_name, spec in generator_specs.items():
        if spec.generator_name == "skip":
            continue
        with contextlib.suppress(Exception):
            values = self._db.get_column_values(table_name, col_name, limit=10000)
            if values:
                self._shared_pool.merge(col_name, values)
```

需要在 `relation.py` 顶部添加导入：

```python
import contextlib
```

- [ ] **Step 4: 给 RelationResolver.__init__ 添加 shared_pool 参数**

修改 `RelationResolver.__init__`：

```python
def __init__(self, db_adapter: Any, shared_pool: SharedPool | None = None) -> None:
    self._db = db_adapter
    self._fk_cache: dict[str, list[ForeignKeyInfo]] = {}
    self._shared_pool = shared_pool or SharedPool()
```

- [ ] **Step 5: 添加 RelationResolver 新方法测试**

在 `tests/test_relation.py` 中添加测试：

```python
def test_resolve_foreign_keys_with_fk():
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.relation import RelationResolver, SharedPool

    class FakeDB:
        def get_foreign_keys(self, table_name):
            from sqlseed.database._protocol import ForeignKeyInfo
            return [ForeignKeyInfo(column="dept_id", ref_table="departments", ref_column="id")]
        def get_column_values(self, table_name, column_name, limit=1000):
            return [1, 2, 3]

    resolver = RelationResolver(FakeDB(), SharedPool())
    specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
    result = resolver.resolve_foreign_keys("employees", specs)
    assert result["dept_id"].generator_name == "foreign_key"
    assert result["dept_id"].params["ref_table"] == "departments"


def test_resolve_foreign_keys_without_fk():
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.relation import RelationResolver, SharedPool

    class FakeDB:
        def get_foreign_keys(self, table_name):
            return []
        def get_column_values(self, table_name, column_name, limit=1000):
            return []

    resolver = RelationResolver(FakeDB(), SharedPool())
    specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
    result = resolver.resolve_foreign_keys("employees", specs)
    assert result["dept_id"].generator_name == "integer"


def test_resolve_implicit_associations():
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.relation import RelationResolver, SharedPool

    class FakeDB:
        def get_foreign_keys(self, table_name):
            return []

    pool = SharedPool()
    pool.register("account_id", [10, 20, 30])
    resolver = RelationResolver(FakeDB(), pool)
    specs = {"account_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
    result = resolver.resolve_implicit_associations("orders", specs)
    assert result["account_id"].generator_name == "foreign_key"
    assert result["account_id"].params["ref_table"] == "__shared_pool__"


def test_register_shared_pool():
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.relation import RelationResolver, SharedPool

    class FakeDB:
        def get_column_values(self, table_name, column_name, limit=10000):
            return ["alice", "bob"]

    pool = SharedPool()
    resolver = RelationResolver(FakeDB(), pool)
    specs = {"name": GeneratorSpec(generator_name="string"), "id": GeneratorSpec(generator_name="skip")}
    resolver.register_shared_pool("users", specs)
    assert pool.has("name")
    assert not pool.has("id")
```

- [ ] **Step 6: 运行测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_relation.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/sqlseed/core/relation.py tests/test_relation.py
git commit -m "feat: add FK resolution and SharedPool methods to RelationResolver"
```

---

## Task 3: 重构 DataOrchestrator 委托新模块

**Files:**
- Modify: `src/sqlseed/core/orchestrator.py`

- [ ] **Step 1: 添加 PluginMediator 导入和初始化**

在 `src/sqlseed/core/orchestrator.py` 中：

1. 添加导入：`from sqlseed.core.plugin_mediator import PluginMediator`
2. 在 `__init__` 中将 `self._shared_pool = SharedPool()` 改为：
   ```python
   self._shared_pool = SharedPool()
   self._relation = RelationResolver(self._db, self._shared_pool)
   self._plugin_mediator: PluginMediator | None = None
   ```
3. 在 `_ensure_connected` 末尾添加：
   ```python
   self._plugin_mediator = PluginMediator(self._plugins, self._db, self._schema)
   ```

- [ ] **Step 2: 替换 fill_table 中的方法调用**

在 `fill_table` 方法中，将：

```python
generator_specs = self._resolve_foreign_keys(table_name, generator_specs)
generator_specs = self._apply_ai_suggestions(table_name, column_infos, generator_specs)
generator_specs = self._apply_template_pool(table_name, column_infos, generator_specs, count)
```

替换为：

```python
generator_specs = self._relation.resolve_foreign_keys(table_name, generator_specs)
generator_specs = self._plugin_mediator.apply_ai_suggestions(table_name, column_infos, generator_specs)
generator_specs = self._plugin_mediator.apply_template_pool(table_name, column_infos, generator_specs, count)
```

将：

```python
current_batch = self._apply_batch_transforms(table_name, batch)
```

替换为：

```python
current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
```

将：

```python
self._register_shared_pool(table_name, generator_specs)
```

替换为：

```python
self._relation.register_shared_pool(table_name, generator_specs)
```

- [ ] **Step 3: 替换 preview_table 中的方法调用**

在 `preview_table` 方法中，将：

```python
generator_specs = self._resolve_foreign_keys(table_name, generator_specs)
```

替换为：

```python
generator_specs = self._relation.resolve_foreign_keys(table_name, generator_specs)
```

将：

```python
current_batch = self._apply_batch_transforms(table_name, batch)
```

替换为：

```python
current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
```

- [ ] **Step 4: 删除已迁移的方法**

从 `DataOrchestrator` 中删除以下方法和常量：

1. `AI_APPLICABLE_GENERATORS` 常量（第 447 行）
2. `_apply_ai_suggestions` 方法（第 449-509 行）
3. `_apply_batch_transforms` 方法（第 511-525 行）
4. `_apply_template_pool` 方法（第 527-564 行）
5. `_resolve_foreign_keys` 方法（第 362-400 行）
6. `_resolve_implicit_associations` 方法（第 402-445 行）
7. `_register_shared_pool` 方法（第 566-577 行）

- [ ] **Step 5: 清理不再需要的导入**

从 `orchestrator.py` 顶部删除不再直接使用的导入：

- `contextlib`（仅被 `_apply_template_pool` 使用，现在在 `PluginMediator` 中）
- `ClassVar`（仅被 `AI_APPLICABLE_GENERATORS` 使用）

确认 `SharedPool` 导入仍需保留（`__init__` 中创建实例）。

- [ ] **Step 6: 运行全量测试**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --tb=short -q`
Expected: 全部 PASS

- [ ] **Step 7: 运行 ruff check**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m ruff check src/ tests/`
Expected: 无错误

- [ ] **Step 8: 验证 DataOrchestrator 行数**

Run: `wc -l src/sqlseed/core/orchestrator.py`
Expected: ≤ 550 行

- [ ] **Step 9: Commit**

```bash
git add src/sqlseed/core/orchestrator.py
git commit -m "refactor: delegate plugin and FK logic from DataOrchestrator to PluginMediator and RelationResolver"
```

---

## Task 4: 最终验证

- [ ] **Step 1: 运行全量测试 + 覆盖率**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest --cov=sqlseed --cov-report=term-missing --tb=short -q`

验证：
- 全部测试 PASS
- `plugin_mediator.py` 覆盖率 ≥ 90%
- `relation.py` 新方法覆盖率 ≥ 85%

- [ ] **Step 2: 运行 ruff check**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m ruff check src/ tests/`
Expected: 无错误

- [ ] **Step 3: 验证 DataOrchestrator 行数**

Run: `wc -l src/sqlseed/core/orchestrator.py`
Expected: ≤ 550 行

- [ ] **Step 4: 验证公共 API 行为不变**

Run: `cd /Users/sunbo/Documents/webblock/sqlseed && python3 -m pytest tests/test_public_api.py tests/test_cli.py -v`
Expected: 全部 PASS
