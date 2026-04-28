<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_config

## Purpose

配置系统测试。覆盖模型校验、文件加载和快照管理。

## Key Files

| File | Description |
|------|-------------|
| `test_loader.py` | YAML/JSON 配置加载测试 |
| `test_models.py` | Pydantic 模型校验测试 |
| `test_snapshot.py` | SnapshotManager 快照管理测试 |

## For AI Agents

### Working In This Directory

- 模型校验需覆盖源列/派生列互斥约束
- 加载器需覆盖 YAML 和 JSON 两种格式
- 需测试非法配置文件的错误提示

### Testing Requirements

```bash
pytest tests/test_config/
```

### Common Patterns

- 使用临时文件（`tmp_path`）创建测试配置文件

## Dependencies

### Internal

- `src/sqlseed/config/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
