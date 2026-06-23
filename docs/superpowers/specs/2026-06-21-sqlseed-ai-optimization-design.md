# sqlseed-ai 插件优化设计文档

**生成日期**：2026-06-21
**范围**：`plugins/sqlseed-ai/src/sqlseed_ai/` 全部 11 个 Python 文件 + AGENTS.md
**目标**：docstring 补充、语言统一（英文）、analyzer.py 拆分、封装修复、resolve 纯函数化、类型安全、文档代码一致性修复
**约束**：保证与 `src/sqlseed/` 边界对齐，避免破坏插件与主包的接口

---

## 一、背景

sqlseed-ai 是基于 LLM 的数据库模式分析与测试数据生成配置推荐插件。通过 OpenAI 兼容 API 调用 Gemma 4 模型，支持 4 种后端（Google AI Studio、LM Studio、Ollama、OpenAI 兼容端点）。

当前存在以下问题：
1. docstring 缺失（9/11 文件无模块 docstring）
2. analyzer.py 过长（842 行）
3. 文档与代码不一致（3 处）
4. _client.py 有中文注释
5. AGENTS.md 为中文（与 src/sqlseed/ 的英文 AGENTS.md 不一致）
6. 封装违反、resolve 方法副作用不一致、类型安全损失

## 二、影响分析

| 变更类型 | 影响范围 | 风险 |
|----------|----------|------|
| docstring 补充 | 11 个文件 | 无（不影响逻辑） |
| 中文→英文 | _client.py, AGENTS.md | 无（不影响逻辑） |
| analyzer.py 拆分 | analyzer.py + 新建 _prompts.py + _tools.py | 低（仅 import 路径变化） |
| _detect_all_local_models 重命名 | config.py, analyzer.py | 低（仅 2 个调用点） |
| resolve 纯函数化 | config.py + 所有调用点 | 中（需更新所有调用方处理返回值） |
| 类型安全 | refiner.py, _client.py | 低（TYPE_CHECKING 导入） |
| _ULTRA_COMPACT_SYSTEM_PROMPT 新增 | analyzer.py | 低（新增常量，不影响现有逻辑） |

## 三、详细优化计划

### 3.1 P0: 文档与代码双向调整

| 问题 | 处理方式 |
|------|----------|
| AGENTS.md 提到 `_ULTRA_COMPACT_SYSTEM_PROMPT` 但代码不存在 | **修代码**：在 _prompts.py 新增 `_ULTRA_COMPACT_SYSTEM_PROMPT` 常量，从 `_COMPACT_SYSTEM_PROMPT` 派生但更精简 |
| AGENTS.md 称验证 `GeneratorConfig` 但代码用 `TableConfig` | **修文档**：AGENTS.md 改为 `TableConfig` |
| AGENTS.md 禁止顶部导入 openai 但 _client.py 违反 | **修文档**：AGENTS.md 调整为"NEVER import openai at module top in analyzer.py → use lazy init via _client.py" |

### 3.2 P1: docstring 补充 + 语言统一

- 11 个文件全部补充模块级英文 docstring
- 类和方法补充英文 docstring（遵循 PEP 257）
- `_client.py` 中文注释 → 英文
- `AGENTS.md` 中文 → 英文

### 3.3 P2: analyzer.py 拆分

```
analyzer.py (842行) → analyzer.py (~690行) + _prompts.py (~100行) + _tools.py (~80行)
```

- `_prompts.py`: SYSTEM_PROMPT, _COMPACT_SYSTEM_PROMPT, _ULTRA_COMPACT_SYSTEM_PROMPT, TEMPLATE_SYSTEM_PROMPT
- `_tools.py`: GEMMA_TOOLS
- `analyzer.py`: 从 `_prompts` 和 `_tools` 导入

### 3.4 P2: 封装修复

- `config.py`: `_detect_all_local_models` → `detect_all_local_models`（去掉下划线）
- `analyzer.py`: 更新调用点

### 3.5 P2: resolve 方法统一为纯函数

- `resolve_model`: 不修改 `self.model`，返回 `str`
- `resolve_base_url`: 不修改 `self.base_url`，返回 `str`
- 更新所有调用点

### 3.6 P2: 类型安全

- `refiner.py`: `orch: Any` → `DataOrchestrator`（使用 TYPE_CHECKING 导入避免循环依赖）
- `_client.py`: `get_openai_client` 返回类型 `Any` → `OpenAI`

### 3.7 P3: 代码异味清理

- `config.py`: `display_name` 属性的字典字面量提为类级常量
- `_json_utils.py`: `_sanitize_names` 补充 docstring

## 四、3 智能体分工

| 智能体 | 负责文件 | 任务 |
|--------|---------|------|
| **Agent A** | `__init__.py`, `_client.py`, `_hardware.py`, `_json_utils.py`, `_model_selector.py`, `errors.py`, `examples.py` | docstring 补充 + 中文注释转英文 + 类型安全 + 代码异味修复 |
| **Agent B** | `analyzer.py`, `config.py`, `refiner.py`, 新建 `_prompts.py` + `_tools.py` | 拆分 analyzer.py + 封装修复 + resolve 纯函数化 + docstring + _ULTRA_COMPACT 新增 |
| **Agent C** | `AGENTS.md`（src） + 验证 | AGENTS.md 转英文 + 文档代码一致性修复 + ruff/mypy/pytest 验证 + 审查 A/B 工作 |

## 五、验证标准

```bash
ruff check plugins/sqlseed-ai/src/sqlseed_ai/
mypy plugins/sqlseed-ai/src/sqlseed_ai/
pytest tests/test_ai_plugin.py
```

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| resolve 纯函数化遗漏调用点 | 中 | 运行时 AttributeError | Agent C 全量搜索调用点 |
| analyzer.py 拆分后 import 错误 | 低 | ImportError | Agent B 验证 import 路径 |
| _ULTRA_COMPACT_SYSTEM_PROMPT 新增影响逻辑 | 低 | 仅新增常量，不影响现有 | Agent C 验证 ultra_compact 路径 |
| 类型安全修改导致循环导入 | 低 | ImportError | 使用 TYPE_CHECKING 延迟导入 |
| 与 src/sqlseed 边界破坏 | 低 | 插件无法注册 | Agent C 验证 entry-points |

## 七、YAGNI 清单（不做）

- ❌ 不修改 `pyproject.toml`（依赖不变）
- ❌ 不修改 `uv.lock`
- ❌ 不重构 `_hardware.py`（质量已很高）
- ❌ 不修改根目录 `AGENTS.md`（已是英文）
- ❌ 不修改 `README.md` / `README.zh-CN.md`
- ❌ 不拆分 SchemaAnalyzer 类（方法间共享状态过多）
