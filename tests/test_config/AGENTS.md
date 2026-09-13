# test_config

本目录验证 Pydantic 配置、YAML/JSON loader 与 snapshot；实现规则见 [config/AGENTS.md](../../src/sqlseed/config/AGENTS.md)。

## 入口与回归要求

- `test_models.py`：字段默认值、null_ratio、连接互斥与 `connection_target`；修改 model validator 时补充相关错误路径。
- 保留 source（generator/params）与 derived（derive_from/expression）模式互斥的验证要求；不要绕过 Pydantic 来构造本应非法的生产输入。
- `test_loader.py`：YAML 与 JSON 都要覆盖，包括无效文件和错误信息；配置文件放在 `tmp_path`。
- 多数据库配置使用 `url`，与 `db_path` 互斥；验证序列化后连接目标仍然一致。
- `test_normalization_and_save_regressions.py`：非法 params 必须拒绝，合法空值/映射保持兼容；不支持的格式不得创建文件或目录，JSON 编码失败不得截断原配置。
- `test_snapshot.py`：验证 save/load/list_snapshots 生命周期；snapshot 不负责执行 CLI replay。
- 尽量断言加载后的 model 字段和实际落盘内容，避免把 loader 的返回对象直接 mock 成期望值。

## 验证

从仓库根执行：

```bash
pytest tests/test_config/
pytest tests/test_public_api.py tests/test_url_connection.py
```

修改 `src/sqlseed/config/models.py` 时，还要同步双语 architecture 文档并运行 `pytest tests/test_doc_sync.py`。
