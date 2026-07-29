<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_generators

## Purpose

数据生成器的正确性和一致性测试。覆盖 Base/Faker/Mimesis 三种 Provider 和注册表。

## Key Files

| File | Description |
|------|-------------|
| `_mixin.py` | 共享测试混入，提取 Provider 通用测试逻辑 |
| `test_base_provider.py` | BaseProvider 内置生成器测试 |
| `test_faker_provider.py` | FakerProvider 测试（继承 _mixin 共享用例） |
| `test_mimesis_provider.py` | MimesisProvider 测试（继承 _mixin 共享用例） |
| `test_registry.py` | ProviderRegistry 注册和发现测试 |
| `test_stream.py` | DataStream 批量生成测试 |
| `test_dispatch_sync.py` | verify_dispatch_sync() 映射一致性测试 |

## For AI Agents

### Working In This Directory

- `_mixin.py` 提供共享的 Provider 测试方法（Core/Identity/Temporal/JsonSchema 四组混入），避免重复
- Faker/Mimesis 为可选依赖，dev 环境已安装，测试直接导入对应 Provider
- 生成器测试需验证 seed 可重现性

### Testing Requirements

```bash
pytest tests/test_generators/
```

### Common Patterns

- 使用 `_mixin.py` 混入避免重复测试逻辑
- 各 Provider 测试类在 `setup_method` 中实例化对应 Provider

## Dependencies

### Internal

- `src/sqlseed/generators/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
