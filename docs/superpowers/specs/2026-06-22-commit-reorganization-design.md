# 提交历史重新整理设计文档

**生成日期**：2026-06-22
**范围**：从 `1dd2c29` 之后的 7 个提交（`9662fd8`..`640950e`）
**目标**：按功能模块重新整理为 17 个细粒度提交
**方法**：备份分支 + `git reset --mixed` + 逐个重新提交
**分支**：`feat/multi-db-support`（未推送远程，rewrite 安全）

---

## 一、背景

当前 `feat/multi-db-support` 分支从 `1dd2c29` 之后有 7 个提交，多个提交混合了不同文件夹的变更，导致提交历史不够清晰。例如：

- `9662fd8`（38 文件）混合了 `plugins/sqlseed-ai/` + `plugins/mcp-server-sqlseed/` + `tests/` + `docs/specs/`
- `13adf6b`（16 文件）混合了根目录文档 + `docs/specs/` + `pyproject.toml` + `tests/`
- `25b5029`（20 文件）混合了 `examples/` + `docs/specs/` + `docs/superpowers/plans/`
- `640950e`（13 文件）混合了社区文件 + 配置 + 文档 + 设计文档

### 重新整理目标

1. 每个提交对应一个清晰的功能模块边界
2. 每个文件只出现在一个提交中（避免跨提交修改的文件冲突）
3. 提交顺序按逻辑排列：`plugins/` → `tests/` → `docs/specs/` → 根目录文档 → `examples/` → `docs/` 语言统一 → CI 配置 → 新增文件

---

## 二、安全策略

**核心原则**：先备份，再操作，可回滚。

### 操作步骤

1. **创建备份分支**：`git branch feat/multi-db-support-backup`，保留原始 7 个提交历史
2. **在原分支上 reset**：`git reset --mixed 1dd2c29`，将所有变更回退到工作树
3. **按 17 个功能模块逐个提交**：每个模块 `git add <files>` + `git commit -m "<message>"`
4. **验证内容一致性**：`git diff feat/multi-db-support-backup HEAD` 应为空
5. **验证提交数**：`git rev-list 1dd2c29..HEAD --count` 应为 17

### 回滚方案

如出现问题，执行 `git reset --hard feat/multi-db-support-backup` 即可恢复原始历史。

---

## 三、跨提交修改的文件处理

以下文件在原始 7 个提交中被多次修改，需要合并到最终状态的 commit 中：

| 文件 | 原始涉及的 commit | 合并到 |
|------|-------------------|--------|
| `AGENTS.md` | `13adf6b` + `1fe741f` | Commit 10（品牌定位更新） |
| `CLAUDE.md` | `13adf6b` + `1fe741f` | Commit 10（品牌定位更新） |
| `pyproject.toml` | `13adf6b` + `ac4147c` | Commit 13（CI 配置） |

**处理方式**：在 reset 后，这些文件的工作树状态是最终的合并状态，直接分配到对应的 commit 中即可。

---

## 四、17 个 Commit 详细设计

### Phase 1: plugins/ 优化（5 个 commit）

#### Commit 1: `refactor: optimize plugins/sqlseed-ai/ source code`

**文件**（12 个）：
- `plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md`
- `plugins/sqlseed-ai/src/sqlseed_ai/__init__.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_client.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_json_utils.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_prompts.py`（新增）
- `plugins/sqlseed-ai/src/sqlseed_ai/_tools.py`（新增）
- `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/config.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/errors.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/examples.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py`

**变更内容**：
- 拆分 `analyzer.py`（842 行）为 `analyzer.py`（580）+ `_prompts.py`（120）+ `_tools.py`（80）
- 添加 3 层 prompt 系统（full/compact/ultra-compact）
- `resolve_model`/`resolve_base_url` 改为纯函数
- 类型安全改进：`Any` → `OpenAI`/`DataOrchestrator`/`httpx.Timeout`
- 添加英文 docstrings

#### Commit 2: `docs: update plugins/sqlseed-ai/ documentation`

**文件**（3 个）：
- `plugins/sqlseed-ai/AGENTS.md`
- `plugins/sqlseed-ai/README.md`
- `plugins/sqlseed-ai/README.zh-CN.md`

**变更内容**：
- 更新 `_prompts.py`/`_tools.py` 引用
- 修正 API key 回退链、超时默认值、hook 表、函数名

#### Commit 3: `refactor: optimize plugins/mcp-server-sqlseed/ source code`

**文件**（5 个）：
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/AGENTS.md`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/__init__.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/__main__.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/config.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py`

**变更内容**：
- 修复 byte/character 检查 bug
- 修复硬编码 provider（mimesis → faker）
- `_validate_db_path` → `_validate_db_target` 重命名
- 添加 Pydantic field_validator（port 1-65535, host 非空）
- 中文 docstrings/comments 转英文

#### Commit 4: `docs: update plugins/mcp-server-sqlseed/ documentation and config`

**文件**（4 个）：
- `plugins/mcp-server-sqlseed/AGENTS.md`
- `plugins/mcp-server-sqlseed/README.md`
- `plugins/mcp-server-sqlseed/README.zh-CN.md`
- `plugins/mcp-server-sqlseed/pyproject.toml`

**变更内容**：
- 添加日期头、中文转英文、工具表（3→6）、Gemma 4 章节
- 添加 ruff/mypy/pytest 配置

#### Commit 5: `test: add plugins/mcp-server-sqlseed/ test suite`

**文件**（4 个）：
- `plugins/mcp-server-sqlseed/tests/__init__.py`
- `plugins/mcp-server-sqlseed/tests/conftest.py`
- `plugins/mcp-server-sqlseed/tests/test_server.py`
- `plugins/mcp-server-sqlseed/tests/test_validate_db_path.py`

### Phase 2: tests/ 优化（3 个 commit）

#### Commit 6: `test: add sqlseed-ai plugin test suite`

**文件**（8 个）：
- `tests/test_ai_analyzer_streaming.py`
- `tests/test_ai_client.py`
- `tests/test_ai_config.py`
- `tests/test_ai_errors.py`
- `tests/test_ai_json_utils.py`
- `tests/test_ai_model_selector.py`
- `tests/test_ai_plugin_init.py`
- `tests/test_ai_prompts_tools.py`

#### Commit 7: `test: unify tests/ language to English and improve type annotations`

**文件**（13 个）：
- `tests/conftest.py`
- `tests/integration/test_pg_integration.py`
- `tests/integration/test_url_e2e.py`
- `tests/test_ai_plugin.py`
- `tests/test_cli.py`
- `tests/test_config/test_loader.py`
- `tests/test_config/test_models.py`
- `tests/test_database/test_adapter_contract.py`
- `tests/test_database/test_dialect.py`
- `tests/test_database/test_optimizer.py`
- `tests/test_database/test_sqlalchemy_adapter_boundary.py`
- `tests/test_orchestrator.py`
- `tests/test_orchestrator_adapter.py`

**变更内容**：
- 中文 docstrings/comments 转英文
- 类型注解改进：`tmp_path: Any` → `tmp_path: Path`，`monkeypatch: Any` → `pytest.MonkeyPatch`
- 添加模块级 docstrings

#### Commit 8: `test: add sql_safe and schema_helpers unit tests`

**文件**（2 个）：
- `tests/test_database/test_sql_safe.py`
- `tests/test_utils/test_schema_helpers.py`

### Phase 3: 设计文档（1 个 commit）

#### Commit 9: `docs: add optimization design specifications`

**文件**（15 个）：
- `docs/superpowers/specs/2026-06-20-project-consolidation-design.md`
- `docs/superpowers/specs/2026-06-21-cli-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-config-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-core-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-database-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-generators-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-language-unification-design.md`
- `docs/superpowers/specs/2026-06-21-plugins-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-root-and-holistic-review-design.md`
- `docs/superpowers/specs/2026-06-21-sqlseed-ai-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-utils-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-mcp-server-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-sqlseed-ai-tests-docs-design.md`
- `docs/superpowers/specs/2026-06-22-project-wide-optimization-design.md`
- `docs/superpowers/specs/2026-06-22-commit-reorganization-design.md`（本文档）

### Phase 4: 根目录文档品牌定位（1 个 commit）

#### Commit 10: `docs: update brand positioning from SQLite-only to Multi-Database`

**文件**（6 个）：
- `AGENTS.md`（合并 `13adf6b` + `1fe741f` 的变更）
- `CLAUDE.md`（合并 `13adf6b` + `1fe741f` 的变更）
- `GEMINI.md`
- `README.md`
- `README.zh-CN.md`
- `docs/index.md`

**变更内容**：
- 项目描述从 "SQLite test data generation toolkit" 更新为 "Multi-Database test data generation toolkit"
- 添加 PostgreSQL/MySQL 安装说明和连接示例
- 更新项目知识库（AGENTS.md, CLAUDE.md）

### Phase 5: examples/ 语言统一（1 个 commit）

#### Commit 11: `docs: unify examples/ language to English`

**文件**（14 个）：
- `examples/quick_demo.py`
- `examples/build_demo_db.py`
- `examples/notebooks/01-quickstart.ipynb`
- `examples/notebooks/02-column-mapping.ipynb`
- `examples/notebooks/03-generators.ipynb`
- `examples/notebooks/04-database-advanced.ipynb`
- `examples/notebooks/05-dag-and-constraints.ipynb`
- `examples/notebooks/06-config-deep-dive.ipynb`
- `examples/notebooks/07-ai-plugin.ipynb`
- `examples/notebooks/08-mcp-server.ipynb`
- `examples/notebooks/09-plugin-hooks.ipynb`
- `examples/notebooks/10-cli-reference.ipynb`
- `examples/notebooks/11-utilities.ipynb`
- `examples/notebooks/12-testing-patterns.ipynb`

### Phase 6: docs/ 语言统一（1 个 commit）

#### Commit 12: `docs: unify docs/specs/ and docs/superpowers/plans/ language to English`

**文件**（6 个）：
- `docs/specs/2026-06-19-multi-db-support-design.md`
- `docs/specs/2026-06-20-multi-db-test-completion-design.md`
- `docs/specs/2026-06-20-project-consolidation-design.md`
- `docs/superpowers/plans/2026-06-20-cp1-p0-core-features.md`
- `docs/superpowers/plans/2026-06-20-cp2-p1-boundary-contract.md`
- `docs/superpowers/plans/2026-06-20-cp3-p2-integration-e2e.md`

### Phase 7: CI 和开发工具配置（1 个 commit）

#### Commit 13: `ci: add PostgreSQL integration tests and expand dev tooling`

**文件**（4 个）：
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`
- `pyproject.toml`（合并 `13adf6b` + `ac4147c` 的变更）
- `mkdocs.yml`

**变更内容**：
- CI 添加 PostgreSQL 16 集成测试 job
- pre-commit hooks 从 2 个扩展到 10 个
- pyproject.toml 排除 `examples/notebooks` 的 ruff 检查
- mkdocs.yml 修正 site_url + 扩展 nav

### Phase 8: 新增项目文件（4 个 commit）

#### Commit 14: `chore: add project configuration files`

**文件**（3 个）：
- `.editorconfig`
- `.env.example`
- `Makefile`

#### Commit 15: `docs: add community files`

**文件**（3 个）：
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`

#### Commit 16: `chore: add GitHub templates and CODEOWNERS`

**文件**（4 个）：
- `.github/CODEOWNERS`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`

#### Commit 17: `docs: add API reference and user guide`

**文件**（2 个）：
- `docs/api.md`
- `docs/guide.md`

---

## 五、验证方案

### 内容一致性验证

```bash
# 备份分支与重新整理后的 HEAD 内容应完全一致
git diff feat/multi-db-support-backup HEAD
# 期望输出：空（无差异）
```

### 提交数验证

```bash
# 从 1dd2c29 之后的提交数应为 17
git rev-list 1dd2c29..HEAD --count
# 期望输出：17
```

### 文件完整性验证

```bash
# 变更文件统计应与原始一致
git diff 1dd2c29 HEAD --stat
# 期望：约 103 个文件，+8000/-4000 行
```

### 测试验证

```bash
ruff check .                    # 期望：All checks passed
mypy src plugins                # 期望：Success: no issues found
pytest                          # 期望：964 passed, 2 skipped
mkdocs build --strict           # 期望：Documentation built
```

---

## 六、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| reset 后工作树文件丢失 | 先创建备份分支，确认 `git diff feat/multi-db-support-backup` 为空 |
| 文件分配错误 | 每个 commit 后运行 `git status` 确认无遗漏 |
| 跨 commit 修改的文件冲突 | 合并到最终状态的 commit 中（AGENTS.md → Commit 10, pyproject.toml → Commit 13） |
| 提交信息不准确 | 严格按功能模块撰写，每个 commit 只涉及一个功能 |
| 设计文档本身被 reset | 设计文档作为 Commit 9 的一部分提交 |

---

## 七、YAGNI 清单

以下事项**不在本次范围内**：

- 不修改任何代码逻辑（仅重新组织提交历史）
- 不修改提交信息的内容（保持原始变更描述）
- 不推送到远程（本地操作，用户手动推送）
- 不修改 `main` 分支
- 不修改 `1dd2c29` 之前的提交历史

---

## 八、执行顺序

1. 写入本设计文档到磁盘
2. 创建备份分支 `feat/multi-db-support-backup`
3. `git reset --mixed 1dd2c29`
4. 按 Commit 1-17 顺序逐个 `git add` + `git commit`
5. 验证内容一致性、提交数、文件完整性
6. 运行测试验证（ruff, mypy, pytest, mkdocs build）
7. 用户确认后，可选择删除备份分支
