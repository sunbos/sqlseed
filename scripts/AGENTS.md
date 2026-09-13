# 辅助脚本

继承 [根指南](../AGENTS.md)。这些脚本服务于维护、演示和验收；普通开发者安装 PyPI 包后使用公开入口，不依赖本目录启动服务。

## 正式入口

| 脚本 | 用途与边界 |
|---|---|
| [sync_docs.py](sync_docs.py)、[_fact_extractors.py](_fact_extractors.py) | 从源码提取事实并校验 Markdown 标记；不手动固定计数 |
| [check_wheel_install.py](check_wheel_install.py) | 验证已安装 Core/Web、真实 HTTP/SQLite 与最小可选组件边界 |
| [check_public_entrypoints.py](check_public_entrypoints.py) | 验证发行包 CLI/MCP 的真实入口及写入结果 |
| [check_pypi_metadata.py](check_pypi_metadata.py) | 校验正式 PyPI metadata、安装报告中的文件来源与哈希 |
| [verify_pypi_release.sh](verify_pypi_release.sh) | 从正式 PyPI 安装指定版本，验收五包、最小环境及 sdist |
| [quickstart.py](quickstart.py)、[make_test_db.py](make_test_db.py) | 演示和测试数据库辅助入口；执行前核对参数与目标路径 |
| [complex_validation/](complex_validation/) | 专项语料与复现工具；不是替代 pytest 的统一产品门禁 |

## 验收隔离

- wheel/发行验收使用新的 virtualenv 和临时数据库、workspace、settings；确认 import 来自该环境的 site-packages，不能从 editable checkout 借用缺失实现。
- `verify_pypi_release.sh <version>` 在 macOS/Linux 运行，可通过 `PYTHON_BIN` 指定解释器；它保留临时证据目录。五包版本、公共索引、安装报告、来源与哈希检查必须保持，不能用本地 wheel 验证替代正式 PyPI 验收。
- 保留 full、Core/Web minimal 和 sdist 三条路径；minimal 中可选包必须实际缺失。CLI/MCP 必须启动安装后的命令并核验数据库结果，不能只检查 `--help` 或 mock 调用。
- 清理继承的源码路径、AI 密钥与后端配置，避免验收误用用户服务；不要输出凭据或修改用户现有 Python 环境。真实 LLM、PostgreSQL 和浏览器视觉验收各自记录，脚本成功不覆盖这些范围。
- 演示和 ad-hoc 日志只作参考，不把临时 `.db`、复现文件或硬编码本机路径加入运行时依赖。

## 修改后验证

- 文档事实提取：运行 `python scripts/sync_docs.py --check` 和 `pytest tests/test_doc_sync.py`。
- 包/入口验收：在对应的隔离安装环境中运行改动的检查，并核对实际文件来源和生成结果；shell 变更先通过 `bash -n scripts/verify_pypi_release.sh`。
- 脚本不在根默认 ruff 的 src/tests/plugins 范围内；修改 Python 脚本时显式运行 `ruff check <file>` 与 `ruff format --check <file>`，不要因默认 CI 未覆盖而省略局部校验。
