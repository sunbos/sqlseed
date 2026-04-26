# AGENTS.md — src/sqlseed/generators

## 作用域

- 本目录拥有 `DataProvider` Protocol、`GeneratorDispatchMixin` 分派基类、内置 Provider（Base/Faker/Mimesis/AI）、Provider Registry，以及按批流式产出数据的 `DataStream`。

## 文件清单

| 文件 | 职责 |
|------|------|
| `_protocol.py` | `DataProvider` Protocol（`@runtime_checkable`）、`UnknownGeneratorError` |
| `_dispatch.py` | `GeneratorDispatchMixin`（`_GENERATOR_MAP` 24 类型映射 + `generate()` 分派） |
| `_string_helpers.py` | `resolve_charset()`、`generate_random_string()` |
| `_json_helpers.py` | `generate_json_from_schema()`、`_generate_from_schema()`（递归 JSON Schema 生成） |
| `base_provider.py` | `BaseProvider(GeneratorDispatchMixin)` — 无外部依赖的核心实现，24 个 `_gen_*` 方法 |
| `faker_provider.py` | `FakerProvider(BaseProvider)` — 覆盖 18 个 `_gen_*` 方法，委托 Faker |
| `mimesis_provider.py` | `MimesisProvider(BaseProvider)` — 覆盖 19 个 `_gen_*` 方法，委托 Mimesis |
| `registry.py` | `ProviderRegistry` — Provider 注册、entry point 发现、惰性加载 |
| `stream.py` | `DataStream` — 逐批流式生成、约束回溯、null_ratio、transform |

## 本目录规则

- Provider surface 是外部契约。`name`、`set_locale()`、`set_seed()`、`generate()` 以及 `generate_choice(choices)` 的兼容性要和测试保持一致。
- `faker` / `mimesis` 相关导入继续保持可选；缺依赖时允许 registry 延迟报错，但不能让 `import sqlseed` 失败。
- `ProviderRegistry.register_from_entry_points()` 和 `ensure_provider()` 是插件发现与按需加载边界。不要把非 Provider entry point 当成功路径，也不要把插件包硬编码进核心导入链。
- `ProviderRegistry` 构造时自动注册 `BaseProvider("base")`，确保始终有一个可用 provider。
- `DataStream` 自己维护局部 RNG，并在有 seed 时单独给 Provider 设 seed；不要引入新的模块级随机状态。
- `_apply_generator()` 只对 `choice` 和 `foreign_key` 做本地特判；其余未知生成器应继续抛 `UnknownGeneratorError`，不要悄悄改成静默字符串回退。
- `_handle_foreign_key()` 在 `_ref_values` 为空时回退到 `provider.generate("integer", min_value=1, max_value=999999)`，而非直接抛异常。
- 回溯、null_ratio、transform ctx 和 batch yield 顺序都属于可观察行为，改动前先看 `tests/test_generators/test_stream.py` 与相关 orchestrator 集成测试。
- `_gen_pattern()` 使用 `rstr` 库（核心依赖），每次创建局部 `rstr.Rstr(self._rng)` 实例。
- `_gen_choice(choices)` 的 `choices` 是**位置参数**，这是项目中唯一的例外。
- `FakerProvider._gen_json()` 直接使用 `faker.json(data_columns=schema)`，不走 `_json_helpers`。
- `MimesisProvider.set_locale()` 使用映射表将 Faker 风格 locale（`en_US`）转为 Mimesis 短代码（`en`），回退策略为 `locale.split("_", maxsplit=1)[0]`。
- `MimesisProvider.set_seed()` 必须重建整个 `Generic` 实例（Mimesis 不支持运行时改种）。
- `MimesisProvider._gen_uuid()` 需要显式 `str()` 转换（Mimesis 返回 UUID 对象）。
- `generate_json_from_schema()` 支持 JSON Schema 风格的递归数据生成，`get_array_count` 回调由调用方提供。

## 24 种生成器类型覆盖情况

| 类型 | BaseProvider | FakerProvider | MimesisProvider |
|------|:---:|:---:|:---:|
| `string` | 自实现 | 继承 Base | 继承 Base |
| `integer` | `rng.randint` | `faker.random_int` | `generic.numeric` |
| `float` | `rng.uniform` | `faker.pyfloat` | `generic.numeric` |
| `boolean` | `rng.choice` | `faker.boolean` | `generic.development` |
| `bytes` | `rng.randbytes` | `faker.binary` | `generic.cryptographic` |
| `name` | 列表拼接 | `faker.name` | `generic.person` |
| `first_name` | 列表选择 | `faker.first_name` | `generic.person` |
| `last_name` | 列表选择 | `faker.last_name` | `generic.person` |
| `email` | 拼接 | `faker.email` | `generic.person` |
| `phone` | 格式化 | `faker.phone_number` | `generic.person` |
| `address` | 拼接 | `faker.address` | `generic.address` |
| `company` | 拼接 | `faker.company` | `generic.finance` |
| `url` | 拼接 | `faker.url` | `generic.internet` |
| `ipv4` | 随机段 | `faker.ipv4` | `generic.internet` |
| `uuid` | `uuid.UUID` | `faker.uuid4` | `generic.cryptographic` |
| `date` | `datetime` | `faker.date_between` | `generic.datetime` |
| `datetime` | `datetime` | `faker.date_time_between` | `generic.datetime` |
| `timestamp` | `datetime` | `faker.date_time_this_decade` | `generic.datetime` |
| `text` | 词表拼接 | `faker.text` | `generic.text` |
| `sentence` | 模板 | `faker.sentence` | `generic.text` |
| `password` | 随机字符 | `faker.password` | `generic.person` |
| `choice` | `rng.choice` | `faker.random_element` | `generic.random` |
| `json` | `_json_helpers` | `faker.json` | 继承 Base |
| `pattern` | `rstr.xeger` | 继承 Base | 继承 Base |

## 评审热点

- `stream.py` 同时承载 UNIQUE 回溯、外键值池、局部随机源和 transform 调用，属于生成链路的高风险热区。
- `registry.py` 既处理内置 Provider，也处理 entry point 自动发现；错误处理过硬会拖垮可选插件。
- Provider 的 locale / seed 语义要跨 `BaseProvider`、`FakerProvider`、`MimesisProvider` 对齐。
- `BaseProvider.FIRST_NAMES` 和 `LAST_NAMES` 各含 60 个条目，`generate_name()`、`generate_first_name()`、`generate_last_name()` 均使用同一组列表。

## 验证

- 生成器层：`pytest tests/test_generators`
- 关联行为：`pytest tests/test_mapper.py tests/test_orchestrator.py tests/test_relation.py`
