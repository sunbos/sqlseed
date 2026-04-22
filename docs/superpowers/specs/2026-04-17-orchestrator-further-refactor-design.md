# DataOrchestrator 进一步拆分设计

**日期**：2026-04-17
**状态**：已确认

---

## 摘要

DataOrchestrator 当前 616 行（目标 ≤ 550 行），仍承担 AI Hook 集成、模板池、FK 解析等非编排职责。通过提取 `PluginMediator` 和扩展 `RelationResolver`，将行数降至 ~432 行，消除技术债务。

---

## 动机

DataOrchestrator 当前职责分布：

| 方法 | 行数 | 职责分类 |
|------|------|----------|
| `fill_table` | 121 | 核心编排 ✅ |
| `_apply_ai_suggestions` | 63 | 插件交互 ❌ |
| `_resolve_implicit_associations` | 44 | FK 解析 ❌ |
| `preview_table` | 47 | 核心编排 ✅ |
| `_resolve_foreign_keys` | 39 | FK 解析 ❌ |
| `_apply_template_pool` | 38 | 插件交互 ❌ |
| `get_schema_context` | 28 | AI 上下文 ✅（保留） |
| `_resolve_user_configs` | 28 | 配置解析 ✅（保留） |
| `_apply_batch_transforms` | 15 | 插件交互 ❌ |
| `_register_shared_pool` | 12 | FK 注册 ❌ |
| 公共方法 + 基础设施 | 181 | 必要 ✅ |

**问题**：
- AI Hook 签名/返回格式变化时需改 Orchestrator
- FK 解析策略变化时需改 Orchestrator
- 新增 Hook 时需改 Orchestrator
- 这些都是隐性技术债务

---

## 设计

### 1. 新模块：`PluginMediator`

**文件**：`src/sqlseed/core/plugin_mediator.py`（~130 行）

**职责**：封装所有通过 PluginManager Hook 修改 GeneratorSpecs 的逻辑

**迁移内容**：
- `AI_APPLICABLE_GENERATORS` → `PluginMediator.AI_APPLICABLE_GENERATORS`
- `_apply_ai_suggestions()` → `PluginMediator.apply_ai_suggestions()`
- `_apply_template_pool()` → `PluginMediator.apply_template_pool()`
- `_apply_batch_transforms()` → `PluginMediator.apply_batch_transforms()`

**接口**：

```python
class PluginMediator:
    AI_APPLICABLE_GENERATORS: ClassVar[frozenset[str]] = frozenset({"string", "integer", "date", "datetime", "choice"})

    def __init__(self, plugins: PluginManager, db: DatabaseAdapter, schema: SchemaInferrer) -> None: ...

    def apply_ai_suggestions(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]: ...

    def apply_template_pool(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
        count: int,
    ) -> dict[str, GeneratorSpec]: ...

    def apply_batch_transforms(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...
```

### 2. 扩展：`RelationResolver` 吸收 FK 解析

**文件**：`src/sqlseed/core/relation.py`（增加 ~95 行）

**迁移内容**：
- `_resolve_foreign_keys()` → `RelationResolver.resolve_foreign_keys()`
- `_resolve_implicit_associations()` → `RelationResolver.resolve_implicit_associations()`
- `_register_shared_pool()` → `RelationResolver.register_shared_pool()`

**接口**：

```python
class RelationResolver:
    # 现有方法不变

    def resolve_foreign_keys(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]: ...

    def resolve_implicit_associations(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]: ...

    def register_shared_pool(
        self,
        table_name: str,
        generator_specs: dict[str, GeneratorSpec],
    ) -> None: ...
```

### 3. DataOrchestrator 变更

**净减**：~184 行 → 目标 ~432 行

`fill_table` 中的调用链变更：

```python
# Before
generator_specs = self._resolve_foreign_keys(table_name, generator_specs)
generator_specs = self._apply_ai_suggestions(table_name, column_infos, generator_specs)
generator_specs = self._apply_template_pool(table_name, column_infos, generator_specs, count)
# ... batch loop
current_batch = self._apply_batch_transforms(table_name, batch)
# ... after loop
self._register_shared_pool(table_name, generator_specs)

# After
generator_specs = self._relation.resolve_foreign_keys(table_name, generator_specs)
generator_specs = self._plugin_mediator.apply_ai_suggestions(table_name, column_infos, generator_specs)
generator_specs = self._plugin_mediator.apply_template_pool(table_name, column_infos, generator_specs, count)
# ... batch loop
current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
# ... after loop
self._relation.register_shared_pool(table_name, generator_specs)
```

### 4. 不改变的内容

- **公共 API**：`fill()`、`connect()`、`preview()`、`fill_from_config()` 签名不变
- **插件 Hook**：11 个 Hook 的调用时机和参数不变
- **数据流**：`GeneratorSpec` → `ColumnNode` → `DataStream` 管线不变
- **`get_schema_context`**：保留在 Orchestrator（它是编排层为 AI 提供上下文的公共方法）

### 5. 测试计划

| 文件 | 内容 |
|------|------|
| `tests/test_core/test_plugin_mediator.py`（新建） | AI 建议、模板池、批量变换 |
| `tests/test_relation.py`（扩展） | FK 解析、隐式关联、SharedPool 注册 |
| 现有测试 | 全部保留，确保无回归 |

---

## 验收标准

- [ ] DataOrchestrator 行数 ≤ 550 行
- [ ] 全量测试通过（pytest）
- [ ] ruff check 通过
- [ ] `PluginMediator` 覆盖率 ≥ 90%
- [ ] `RelationResolver` 新方法覆盖率 ≥ 85%
- [ ] 公共 API 行为不变
