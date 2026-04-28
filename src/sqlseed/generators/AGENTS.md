<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# generators

## Purpose

数据提供者的抽象层和具体实现。通过 Protocol 定义接口，支持 Base（内置）、Faker（可选）、Mimesis（可选）三种数据生成引擎。

## Key Files

| File | Description |
|------|-------------|
| `_protocol.py` | `DataProvider` Protocol 接口定义，`UnknownGeneratorError` 异常 |
| `base_provider.py` | `BaseProvider` 内置生成器，零外部依赖，提供基础数据类型 |
| `faker_provider.py` | `FakerProvider` 基于 Faker 的生成器（可选依赖，`HAS_FAKER` 标志） |
| `mimesis_provider.py` | `MimesisProvider` 基于 Mimesis 的生成器（可选依赖，`HAS_MIMESIS` 标志） |
| `registry.py` | `ProviderRegistry` 提供者注册表，通过 entry_points 自动发现 |
| `stream.py` | `DataStream` 从 DAG 节点批量生成行数据，处理约束和派生列 |
| `_dispatch.py` | `GeneratorDispatchMixin` 方法分派混入，将生成器名映射到方法调用 |
| `_json_helpers.py` | JSON 数据生成辅助 |
| `_string_helpers.py` | 随机字符串生成辅助 |

## 生成器覆盖矩阵（31 种）

`_dispatch.py` 的 `_GENERATOR_MAP` 定义了所有生成器名称到方法的映射：

| 生成器 | Base | Faker | Mimesis |
|--------|------|-------|---------|
| string | ✅ | ✅ | ✅ |
| integer | ✅ | ✅ | ✅ |
| float | ✅ | ✅ | ✅ |
| boolean | ✅ | ✅ | ✅ |
| bytes | ✅ | ✅ | ✅ |
| name | ✅ | ✅ | ✅ |
| first_name | ✅ | ✅ | ✅ |
| last_name | ✅ | ✅ | ✅ |
| email | ✅ | ✅ | ✅ |
| phone | ✅ | ✅ | ✅ |
| address | ✅ | ✅ | ✅ |
| company | ✅ | ✅ | ✅ |
| url | ✅ | ✅ | ✅ |
| ipv4 | ✅ | ✅ | ✅ |
| uuid | ✅ | ✅ | ✅ |
| date | ✅ | ✅ | ✅ |
| datetime | ✅ | ✅ | ✅ |
| timestamp | ✅ | ✅ | ✅ |
| text | ✅ | ✅ | ✅ |
| sentence | ✅ | ✅ | ✅ |
| password | ✅ | ✅ | ✅ |
| choice | ✅ | ✅ | ✅ |
| json | ✅ | ✅ | ❌ |
| pattern | ✅ | ❌ | ❌ |
| username | ✅ | ✅ | ✅ |
| city | ✅ | ✅ | ✅ |
| country | ✅ | ✅ | ✅ |
| state | ✅ | ✅ | ✅ |
| zip_code | ✅ | ✅ | ✅ |
| job_title | ✅ | ✅ | ✅ |
| country_code | ✅ | ✅ | ✅ |

- `pattern` 仅 BaseProvider 实现（使用 `rstr` 库），Faker/Mimesis 回退到 BaseProvider
- `json` 仅 BaseProvider 和 FakerProvider 实现，MimesisProvider 回退到 BaseProvider
- FakerProvider 覆盖 28 个方法，MimesisProvider 覆盖 27 个方法

## For AI Agents

### Working In This Directory

- 新增 Provider 必须实现 `DataProvider` Protocol 的所有方法
- Faker/Mimesis 为可选依赖，导入时必须 try/except，设置 `HAS_FAKER`/`HAS_MIMESIS` 标志
- `BaseProvider` 作为兜底实现，确保即使无 faker/mimesis 也能生成基本数据
- Faker/Mimesis Provider 继承 BaseProvider，优先使用原生方法（`native_faker_method`/`native_mimesis_method`），回退到 BaseProvider
- `_dispatch.py` 的方法分派逻辑是生成器调用的核心，修改需确保所有生成器名都有对应方法
- `generate_choice(choices)` 的 `choices` 是位置参数，这是已知例外，不要改为仅关键字参数
- `stream.py` 的批量生成逻辑影响性能，修改需跑基准测试

### Testing Requirements

```bash
pytest tests/test_generators/
```

### Common Patterns

- Provider 层次：`DataProvider`(Protocol) → `BaseProvider`(内置) → `FakerProvider`/`MimesisProvider`(可选)
- `ProviderRegistry` 通过 `importlib.metadata` 扫描 `sqlseed` entry_points 自动注册
- `DataStream` 从 DAG 节点按拓扑顺序生成行，处理唯一约束和派生列

## Dependencies

### Internal

- `_utils`（logger）
- `core`（ColumnDAG, ConstraintSolver, ExpressionEngine — 仅 TYPE_CHECKING）

### External

- 可选：`faker>=30.0`, `mimesis>=18.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
