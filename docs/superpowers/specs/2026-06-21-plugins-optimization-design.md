# plugins/ 目录优化设计文档

**生成日期**：2026-06-21
**目录范围**：`src/sqlseed/plugins/`（4 个文件）
**方法论**：9 步法（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）

---

## 一、问题识别

### P0（Bug）
无。

### P1（重要 — docstring 缺失）
| 文件 | 缺失项 |
|------|--------|
| `__init__.py` | 模块 docstring |
| `hookspecs.py` | 模块/类 docstring；5 个 hook 已有英文 docstring 需补充完善；6 个 hook 完全无 docstring |
| `manager.py` | 模块/类/方法 docstring（7 个方法全缺） |

### P2（设计 — AGENTS.md）
- 日期头过时（2026-04-29 → 2026-06-21）
- 格式与其他目录不一致（HTML 注释 `<!-- Generated: -->` vs `**Generated:**`）
- Key Files 表格缺失 `__init__.py`

### P3（风格 — pylint 注释）
- `hookspecs.py` 第 9 行：`# pylint: disable=unused-argument` 冗余（项目用 ruff，当前 ruff 检查通过证明不需要）

---

## 二、设计方案

### 2.1 P1 docstring 补充（英文）

#### `__init__.py`
- 模块级 docstring：说明"插件系统公共 API 导出"

#### `hookspecs.py`
- 模块级 docstring：说明"pluggy 插件 hook 规范定义，11 个 hook 覆盖注册/生成/变换/插入全生命周期"
- `SqlseedHookSpec` 类 docstring：说明 hook 规范类
- 11 个 hook 方法 docstring（5 英文补充完善，6 新增）：
  1. `sqlseed_register_providers`：注册数据提供者到注册表
  2. `sqlseed_register_column_mappers`：注册列映射规则到映射器
  3. `sqlseed_ai_analyze_table`：[AI Hook] 分析整表并返回列配置建议（firstresult）
  4. `sqlseed_before_generate`：生成前回调
  5. `sqlseed_after_generate`：生成后回调
  6. `sqlseed_transform_row`：变换单行（热路径，性能敏感）
  7. `sqlseed_transform_batch`：变换批次（支持链式应用）
  8. `sqlseed_before_insert`：插入前回调
  9. `sqlseed_after_insert`：插入后回调
  10. `sqlseed_shared_pool_loaded`：共享池加载完成回调
  11. `sqlseed_pre_generate_templates`：[AI Hook] 预生成候选值池（firstresult）

#### `manager.py`
- 模块级 docstring：说明"插件管理器，封装 pluggy.PluginManager，支持自动发现和注册"
- `PluginManager` 类 docstring
- 7 个方法 docstring：`__init__`、`load_plugins`、`register`、`unregister`、`hook`、`get_plugins`、`is_registered`

### 2.2 P3 pylint 注释清理

**`hookspecs.py` 第 7-9 行**：
```python
# 修改前
# pluggy hookspec methods use placeholder parameters that are intentionally
# unused — they define the hook signature for plugin implementers.
# pylint: disable=unused-argument

# 修改后
# pluggy hookspec methods use placeholder parameters that are intentionally unused — they define the hook signature for plugin implementers
```

删除 `# pylint: disable=unused-argument`，保留上方说明注释并转为中文。

### 2.3 P2 AGENTS.md 更新

1. **格式统一**：将 `<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->` 改为 `**Generated:** 2026-06-21`
2. **Key Files 表格**：添加 `__init__.py` 行
3. **保留**：Hook 完整列表、For AI Agents 等其他内容不变

---

## 三、3 智能体分工

### Agent A（hookspecs + __init__）
**文件**：
- `__init__.py`：模块 docstring
- `hookspecs.py`：模块 + 类 + 11 个 hook docstring（5 英文补充完善，6 新增）+ 删除 pylint 注释

### Agent B（manager）
**文件**：
- `manager.py`：模块 + 类 + 7 个方法 docstring

### Agent C（AGENTS.md + 审查 + 验证）
**任务**：
1. 更新 `AGENTS.md`（格式统一 + 日期 + `__init__.py`）
2. 审查 Agent A 和 B 的修改
3. 运行 `ruff check src/sqlseed/plugins/`
4. 运行 `mypy src/sqlseed/plugins/`
5. 运行 `python -m pytest tests/test_plugins/ -x --tb=short`
6. 修复任何验证失败

---

## 四、验证标准

| 命令 | 预期结果 |
|------|----------|
| `ruff check src/sqlseed/plugins/` | All checks passed |
| `mypy src/sqlseed/plugins/` | Success: no issues found |
| `python -m pytest tests/test_plugins/ -x --tb=short` | All tests passed |

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| hook docstring 描述不准确 | 低 | 插件开发者误解 hook 语义 | 基于 pluggy 文档和实际调用点编写 |
| 删除 pylint 注释后 ruff 报警 | 极低 | 项目用 ruff 不用 pylint | 已确认 ruff 检查通过 |

---

## 五、不修改项
- `PROJECT_NAME = "sqlseed"` 常量
- 11 个 hook 的签名（参数名、类型、返回类型）
- `manager.py` 业务逻辑
- AGENTS.md 中的 Hook 完整列表表格内容
