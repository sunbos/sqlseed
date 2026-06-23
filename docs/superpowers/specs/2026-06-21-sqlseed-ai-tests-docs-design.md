# sqlseed-ai 文档优化与测试补充设计文档

**生成日期**：2026-06-21
**范围**：`plugins/sqlseed-ai/` 根目录文档 + 8 个新测试文件
**目标**：更新文档以反映 _prompts.py/_tools.py 拆分；补充测试覆盖 P0+P1+P2 全量缺口（~70-80 个新测试）
**约束**：不修改 pyproject.toml/uv.lock；不重构现有测试；平铺测试文件组织

---

## 一、背景

sqlseed-ai 插件代码优化已完成（analyzer.py 拆分、_prompts.py/_tools.py 新建、resolve 纯函数化等），但：
1. 根目录文档（AGENTS.md、README.md、README.zh-CN.md）未反映 _prompts.py/_tools.py 拆分
2. 测试覆盖率仅 ~44%（39/111 成员已测），53 个成员未测
3. P0 严重缺口：AISqlseedPlugin hooks、_prompts.py、_tools.py、analyzer.py 流式调用链、config.py 解析方法

## 二、影响分析

| 变更类型 | 影响范围 | 风险 |
|----------|----------|------|
| 文档更新 | 3 个 md 文件 | 无（不影响逻辑） |
| 新增测试 | 8 个新测试文件 | 无（仅新增，不修改现有） |
| 现有测试 | 不修改 | 无 |

## 三、详细优化计划

### 3.1 文档优化

| 文件 | 处理方式 |
|------|----------|
| `AGENTS.md`（根目录） | 更新 STRUCTURE 表加入 `_prompts.py`、`_tools.py`；更新 WHERE TO LOOK 表；更新 ANTI-PATTERNS（openai 导入规则调整为"NEVER import openai at module top in analyzer.py"） |
| `README.md` | 更新 GEMMA_TOOLS 章节说明工具定义已移至 `_tools.py`；更新 Gemma 4 Integration 章节 |
| `README.zh-CN.md` | 同步 README.md 的更新 |
| `pyproject.toml` | **不修改**（依赖不变，packages 路径不变） |
| `uv.lock` | **不手动修改**（由 `uv lock` 自动生成） |

### 3.2 测试补充（8 个新文件）

| 新测试文件 | 测试目标 | 预估测试数 |
|-----------|----------|-----------|
| `test_ai_plugin_init.py` | AISqlseedPlugin 类（5 方法） | ~8 |
| `test_ai_client.py` | _client.py（httpx_timeout、get_openai_client） | ~4 |
| `test_ai_prompts_tools.py` | _prompts.py（4 常量验证）+ _tools.py（GEMMA_TOOLS 结构验证） | ~10 |
| `test_ai_config.py` | config.py 未测方法 | ~15 |
| `test_ai_analyzer_streaming.py` | analyzer.py 流式调用链 | ~12 |
| `test_ai_model_selector.py` | _model_selector.py | ~6 |
| `test_ai_errors.py` | errors.py 未测 handler | ~5 |
| `test_ai_json_utils.py` | _json_utils.py | ~4 |

### 3.3 测试编写原则

- 使用 `unittest.mock.patch` 和 `monkeypatch` mock LLM 调用
- 复用 `tests/conftest.py` 的 fixtures（make_col、tmp_db、available_llm_backend）
- 使用 `try/except ImportError` + `pytest.skip(allow_module_level=True)` 处理 sqlseed-ai 未安装
- 测试命名：`test_<function>_<scenario>`
- 每个测试函数聚焦单一行为

## 四、3 智能体分工

| 智能体 | 负责文件 | 任务 |
|--------|---------|------|
| **Agent A** | 文档（AGENTS.md、README.md、README.zh-CN.md）+ `test_ai_plugin_init.py` + `test_ai_client.py` + `test_ai_prompts_tools.py` | 文档更新 + 插件入口/客户端/prompts 测试 |
| **Agent B** | `test_ai_config.py` + `test_ai_analyzer_streaming.py` + `test_ai_model_selector.py` | config/analyzer streaming/model selector 测试 |
| **Agent C** | `test_ai_errors.py` + `test_ai_json_utils.py` + 验证 | errors/json_utils 测试 + 全量 ruff/mypy/pytest 验证 + 审查 A/B |

## 五、验证标准

```bash
ruff check tests/test_ai_*.py
mypy tests/test_ai_*.py
pytest tests/test_ai_*.py -v --tb=short
```

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 测试 mock 不当导致误报 | 中 | 测试通过但实际功能有问题 | Agent C 审查 mock 策略 |
| 流式调用链测试复杂度过高 | 中 | 测试难以维护 | 聚焦核心路径，不追求 100% 分支覆盖 |
| 文档更新遗漏 | 低 | 文档与代码不一致 | Agent C 对照代码验证文档 |

## 七、YAGNI 清单（不做）

- ❌ 不修改 `pyproject.toml`
- ❌ 不手动修改 `uv.lock`
- ❌ 不重构现有测试文件（test_ai_plugin.py、test_refiner.py、test_hardware.py 保持不变）
- ❌ 不创建 tests/test_ai_plugin/ 子目录
- ❌ 不补充 examples.py 结构验证（已有间接覆盖）
