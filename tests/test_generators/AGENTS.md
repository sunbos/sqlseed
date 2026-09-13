# test_generators

本目录验证 Base/Faker/Mimesis providers、registry、dispatch、字符串/JSON 与 bytes media；实现规则见 [generators/AGENTS.md](../../src/sqlseed/generators/AGENTS.md)。

## 入口与回归要求

- `_mixin.py` 提供共享 provider 测试，公共契约优先复用 mixin；provider 独有行为保留在对应文件。
- `test_base_provider.py` 验证占位生成与 seed；`test_faker_provider.py` / `test_mimesis_provider.py` 验证真实 provider 行为。
- 检查 seed 可复现、值类型与约束满足；不要强制不同 provider 产生相同文本或相同 locale 电话格式。
- Faker 是必需依赖，Mimesis 是可选依赖。`test_registry.py` 的 discovery 用例使用 importorskip；专属 provider 测试会直接构造 provider，完整运行需安装 Mimesis。
- `test_dispatch_sync.py` 校验 `GENERATOR_MAP` 在 providers 间的一致性；`test_dispatch_exclude.py` 覆盖 exclude_values 透传。
- `test_parameter_bounds_regressions.py` 覆盖浮点精度、窄区间、反向/非有限边界与既有 seed 序列；`test_datetime_policy.py` 覆盖方法覆盖、签名与 locale fallback。不要用放宽断言掩盖越界值。
- `test_string_helpers.py` / `test_json_helpers.py` 覆盖随机字符串与 JSON schema 递归/边界。
- `test_bytes_media.py` 覆盖随机 bytes、PNG/JPEG 与目录读取：断言实际图片 header/尺寸、扩展名过滤、缺失目录/无匹配文件错误，以及 Faker/Mimesis 参数透传。
- 文件读取场景在 `tmp_path` 创建输入；可选 Pillow JPEG 测试采用现有 importorskip 模式。

## 验证

从仓库根执行：

```bash
pytest tests/test_generators/
```

修改 dispatch 名称集合后，同步 [docs/guide.md](../../docs/guide.md#generators) 的完整 generator 表与数量并运行 `pytest tests/test_architecture.py tests/test_doc_sync.py`。
