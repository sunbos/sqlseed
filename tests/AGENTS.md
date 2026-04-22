# AGENTS.md — tests

## 作用域

- 本目录拥有整个 pytest 测试套件、共享 fixtures，以及少量性能基准。

## 布局规则

- 顶层 `test_*.py` 主要覆盖公共 API、CLI 和跨模块集成行为。
- `test_core/`、`test_generators/`、`test_database/`、`test_plugins/`、`test_config/`、`test_utils/` 对应主包的局部单测。
- `benchmarks/` 是性能基准，不是默认正确性断言入口。

## 本目录规则

- 优先复用 `tests/conftest.py` 里的 `tmp_db`、`tmp_db_with_data`、`bank_cards_db` fixtures；只有在现有 schema 不够表达需求时再新增 fixture。
- 新测试文件尽量跟源码职责对齐：核心逻辑放 `tests/test_core/`，生成器放 `tests/test_generators/`，数据库层放 `tests/test_database/`，以此类推。
- 可选插件相关测试继续使用 `pytest.importorskip(...)`，不要让整个测试套件无条件依赖可选安装。
- 断言优先描述可观察行为。若生产代码约定是返回 `GenerationResult.errors` 而非抛异常，测试也应锁定这个契约。
- 改 CLI 或公共 API 时，通常需要同步更新 `tests/test_cli.py` 和 `tests/test_public_api.py`。
- 改编排顺序、hook 负载、SharedPool/FK 行为时，只补单测不够，至少再补一条集成覆盖。

## 验证

- 全量：`pytest`
- 定向：`pytest tests/test_core`, `pytest tests/test_generators`, `pytest tests/test_database`, `pytest tests/test_plugins`, `pytest tests/test_config`
