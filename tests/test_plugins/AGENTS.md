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

- 直接实例化 `PluginManager`，注册 dummy 插件类验证 hook 分派
- 通过 `hookspec` 属性逐项验证 hook 规范定义

## Dependencies

### Internal

- `src/sqlseed/plugins/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
