<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# config

## Purpose

YAML/JSON 配置文件的加载、校验和模型定义。基于 Pydantic 构建类型安全的配置模型。

## Key Files

| File | Description |
|------|-------------|
| `models.py` | Pydantic 配置模型：`GeneratorConfig`, `TableConfig`, `ColumnConfig`, `ColumnConstraintsConfig`, `ProviderType` |
| `loader.py` | 配置文件加载器，支持 YAML 和 JSON 格式，含模板生成功能 |
| `snapshot.py` | `SnapshotManager` 配置快照的保存与恢复 |

## For AI Agents

### Working In This Directory

- 源列模式（`generator` + `params`）和派生列模式（`derive_from` + `expression`）互斥，通过 `model_validator` 校验，不要破坏此约束
- `ProviderType` 枚举包含 BASE/FAKER/MIMESIS/CUSTOM/AI 五种类型
- Pydantic 模型修改需考虑向后兼容，已有配置文件不应因模型变更而无法加载
- `field_validator`/`model_validator` 是核心校验逻辑，修改需确保所有约束条件仍然满足
- 新增配置项应提供合理默认值，避免破坏现有用户配置
- `ColumnAssociation` 是独立的跨表关联模型（非 ColumnConfig 内部枚举），字段：`column_name`, `source_table`, `source_column`(默认 None 回退到 column_name), `target_tables`, `strategy="shared_pool"`

### Testing Requirements

```bash
pytest tests/test_config/
```

### Common Patterns

- 模型层次：`GeneratorConfig` → `TableConfig` → `ColumnConfig` → `ColumnConstraintsConfig`
- `SnapshotManager` 按时间戳命名快照文件
- 配置模板通过 `loader.py` 的 `generate_template()` 生成

## Dependencies

### Internal

- `_utils`（logger）

### External

- `pydantic>=2.0` — 模型定义与校验
- `pyyaml>=6.0` — YAML 加载

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
