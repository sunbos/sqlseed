# mcp-server-sqlseed 优化设计文档

**生成日期**：2026-06-21
**范围**：`plugins/mcp-server-sqlseed/` 所有文件
**目标**：修复 22 个问题（P0: 3、P1: 12、P2: 7），包括 bug 修复、文档同步、语言统一化、类型安全、config 验证
**约束**：不补充 mock 测试（用户要求仅真实测试环境）；不修改 uv.lock

---

## 一、背景

mcp-server-sqlseed 插件存在多处问题：
1. **P0 严重 bug**：字节/字符检查不一致、硬编码 provider、文档工具表不完整
2. **P1 重要问题**：AGENTS.md 日期头缺失、中文 docstring、`Any` 类型滥用、死代码、测试断言过宽
3. **P2 次要问题**：缺模块级 docstring、config 无验证、pyproject 缺配置、函数命名误导

## 二、影响分析

| 变更类型 | 影响范围 | 风险 |
|----------|----------|------|
| P0 bug 修复 | server.py 核心逻辑 | 中（需验证不破坏现有行为） |
| 文档更新 | 4 个 md 文件 | 无 |
| 类型安全 | server.py、conftest.py | 低 |
| config 验证 | config.py | 低（Pydantic field_validator） |
| 重命名 | server.py `_validate_db_path` → `_validate_db_target` | 中（需更新测试） |

## 三、详细优化计划

### 3.1 P0 严重问题（3 个）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `server.py:213-214` | `len(yaml_config)` 检查字符数，错误消息说 "bytes" | 改为 `len(yaml_config.encode('utf-8'))` |
| 2 | `server.py:197` | 硬编码 `"provider": "mimesis"` | 改为 `"provider": "faker"`（faker 是必需依赖） |
| 3 | `README.md`/`README.zh-CN.md` | MCP Tools 表缺失 3 个 Gemma 4 工具 | 补全 6 个工具 |

### 3.2 P1 重要问题（12 个）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 4 | `AGENTS.md`（根） | 缺日期头 | 添加 `**Generated:** 2026-06-21` |
| 5 | `src/AGENTS.md` | HTML 注释日期 + 中文 | 改为 `**Generated:**` + 全文英文 |
| 6-7 | `server.py:62-80` | 中文 docstring + 注释 | 转英文 |
| 8 | `server.py:406` | `ai_config: Any` | 改为 `AIConfig`（TYPE_CHECKING） |
| 9 | `server.py:269,313` | 死代码 | 删除不可达 `raise ValueError` |
| 10 | `conftest.py:13` | `tmp_path: Any` | 改为 `Path` |
| 11 | `conftest.py:70,81` | `except Exception: pass` | 缩窄异常 + 日志 |
| 12 | `test_server.py:110` | `assert total >= 30` | 改为 `== 30` |
| 13 | `AGENTS.md` STRUCTURE | 缺 `tests/` | 补全 |
| 14-15 | `conftest.py`/`test_server.py` | 中文 | 转英文 |

### 3.3 P2 次要问题（7 个）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 16 | 所有 .py | 缺模块级 docstring | 补充英文 |
| 17 | `test_validate_db_path.py` | 中文 + 缺类型 | 转英文 + 补 `Path` |
| 18 | `README.md` | 缺 Gemma 4 章节 | 从中文版同步 |
| 19 | `config.py` | 缺验证 | 添加 `field_validator` |
| 20 | `pyproject.toml` | 缺配置 | 添加 ruff/mypy/pytest |
| 21 | `server.py:62-91` | 命名误导 | `_validate_db_path` → `_validate_db_target` |
| 22 | `config.py` | `db_path` 未使用 | 保留 + 注释说明 |

## 四、3 智能体分工

| 智能体 | 负责文件 | 任务 |
|--------|---------|------|
| **Agent A** | `server.py` + `config.py` + `__init__.py` + `__main__.py` | P0 bug + 类型 + docstring + 验证 + 重命名 |
| **Agent B** | `AGENTS.md`（根）+ `src/AGENTS.md` + `README.md` + `README.zh-CN.md` + `pyproject.toml` | 文档 + 工具表 + 日期 + 配置 |
| **Agent C** | `tests/` 4 个文件 + 验证 | 测试修复 + 全量验证 |

## 五、验证标准

```bash
ruff check plugins/mcp-server-sqlseed/
mypy plugins/mcp-server-sqlseed/src/
pytest plugins/mcp-server-sqlseed/tests/ -v --tb=short
```

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 字节/字符修复改变现有行为 | 低 | 测试可能失败 | Agent C 验证 |
| 重命名破坏测试 | 中 | 测试 import 失败 | Agent C 同步更新 |
| config 验证过于严格 | 低 | 现有配置失败 | 仅验证范围，不验证格式 |

## 七、YAGNI 清单（不做）

- ❌ 不补充 mock 单元测试
- ❌ 不修改 uv.lock
- ❌ 不重构现有测试结构
- ❌ 不删除 config.py 的 db_path 字段
