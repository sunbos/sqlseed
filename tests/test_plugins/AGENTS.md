<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_plugins

## Purpose

插件系统测试。覆盖 hook 规范定义和插件管理器生命周期。

## Key Files

| File | Description |
|------|-------------|
| `test_hookspecs.py` | Hook 规范定义测试 |
| `test_manager.py` | PluginManager 生命周期测试 |

## For AI Agents

### Working In This Directory

- 测试插件的注册、发现和卸载
- 验证 hook 调用的正确分派
- 测试 entry_points 自动发现机制

### Testing Requirements

```bash
pytest tests/test_plugins/
```

### Common Patterns

- 使用 `unittest.mock.patch` 模拟 entry_points

## Dependencies

### Internal

- `src/sqlseed/plugins/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
