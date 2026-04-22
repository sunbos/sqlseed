# AGENTS.md — plugins/sqlseed-ai

## 作用域

- 本目录是可选分发包 `sqlseed-ai`，源码在 `plugins/sqlseed-ai/src/sqlseed_ai/`。
- 包入口通过 `[project.entry-points."sqlseed"]` 注册为 `ai = "sqlseed_ai:plugin"`。

## 本目录规则

- 保持它是可选插件。主包 `sqlseed` 不能因为这里或 `openai` 未安装而整体失效。
- OpenAI 兼容客户端配置统一走 `_client.py` 和 `AIConfig`；不要在多个模块里复制 API key、base URL、model 环境变量解析。
- `AISqlseedPlugin`、`SchemaAnalyzer`、模板生成和自纠正流程默认是软失败路径。AI 不可用时应返回 `None`、空结果或可读错误，而不是拖垮整条生成链。
- hook 方法名和参数必须与 `src/sqlseed/plugins/hookspecs.py` 保持一致。
- `refiner.py` 的缓存、schema hash 和重试回路属于包契约的一部分；改动时要同步更新测试。
- `provider.py` 当前是兼容性空壳；不要把真实 LLM 生成主逻辑塞到这里。
- `suggest.py`（`ColumnSuggester`）和 `nl_config.py`（`NLConfigGenerator`）已移除。其功能由 `SchemaAnalyzer` + `AiConfigRefiner` 完全替代。如有外部用户导入这些类，需在 CHANGELOG 中注明兼容性中断。

## 评审热点

- prompt、few-shot 示例、JSON 解析和错误摘要会直接影响 `tests/test_ai_plugin.py` 与 `tests/test_refiner.py`。
- `sqlseed ai-suggest` 的 CLI 集成在主包 `src/sqlseed/cli/main.py`，参数或环境变量改动通常需要同时改两边。
- `AIConfig.from_env()` 目前同时支持 `SQLSEED_AI_*` 和 `OPENAI_*` 环境变量，兼容性改动要慎重。

## 验证

- 安装插件：`pip install -e "./plugins/sqlseed-ai"`
- 相关测试：`pytest tests/test_ai_plugin.py tests/test_refiner.py tests/test_cli.py`
