# 项目整体优化设计文档

**生成日期**：2026-06-22
**范围**：整个项目（除已优化的 src/sqlseed/、plugins/、tests/、docs/superpowers/specs/）
**目标**：修复 27 个 WARN + 11 个 MISSING = 38 个问题
**约束**：保证 CLI 正常运行；CI 添加 PostgreSQL 集成测试

---

## 一、背景

之前已优化 src/sqlseed/、plugins/、tests/、docs/superpowers/specs/。本次处理剩余文件：
- 根目录文件（README、GEMINI.md、mkdocs.yml、.pre-commit-config.yaml）
- docs/ 目录（除 specs/）
- examples/ 目录
- .github/ 目录
- 缺失的配置文件和社区文件

## 二、影响分析

| 变更类型 | 影响范围 | 风险 |
|----------|----------|------|
| P0 过时内容修复 | notebook 04 | 低（仅文档） |
| P0 CI 添加 PG 测试 | ci.yml | 中（需验证 CLI 正常） |
| P1 品牌定位更新 | README、GEMINI.md、docs/index.md | 低（仅文档） |
| P1 pre-commit 完善 | .pre-commit-config.yaml | 低 |
| P2 语言统一 | examples/、docs/specs/、plans/ | 低（仅文档） |
| P3 缺失文件创建 | 11 个新文件 | 无 |

## 三、详细优化计划

### 3.1 批次 1：P0+P1（7 个问题）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `examples/notebooks/04-database-advanced.ipynb` | 引用已退役的 sqlite-utils | 修正为 SQLAlchemyAdapter + RawSQLiteAdapter |
| 2 | `.github/workflows/ci.yml` | 未运行 PG 集成测试 | 新增 integration job（保证 CLI 正常） |
| 3 | `README.md` | 标题/介绍未反映多数据库 | 改为 "Multi-Database Test Data Generation Toolkit" |
| 4 | `README.zh-CN.md` | 同上 | 同步更新 |
| 5 | `docs/index.md` | 同上 | 同步更新 |
| 6 | `GEMINI.md` | 同上 | 同步更新 |
| 7 | `.pre-commit-config.yaml` | 缺 ruff/mypy hooks | 添加官方 ruff/mypy hooks + 通用 hooks |

### 3.2 批次 2：P2 语言统一（18 个问题）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 8 | `examples/quick_demo.py` | 全中文 | 转英文 |
| 9 | `examples/build_demo_db.py` | 全中文 | 转英文 |
| 10-21 | `examples/notebooks/*.ipynb`（12 个） | 全中文 | 转英文 |
| 22-24 | `docs/specs/*.md`（3 个） | 全中文 | 转英文 |
| 25-27 | `docs/superpowers/plans/*.md`（3 个） | 全中文 | 转英文 |

### 3.3 批次 3：P3 + MISSING（13 个问题）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 28 | `mkdocs.yml` | nav 不完整 + site_url 错误 | 补充 nav + 修正 URL |
| 29 | `.editorconfig` | 缺失 | 创建 |
| 30 | `.env.example` | 缺失 | 创建 |
| 31 | `CONTRIBUTING.md` | 缺失 | 创建 |
| 32 | `SECURITY.md` | 缺失 | 创建 |
| 33 | `CODE_OF_CONDUCT.md` | 缺失 | 创建 |
| 34 | `Makefile` | 缺失 | 创建 |
| 35 | `.github/ISSUE_TEMPLATE/bug_report.md` | 缺失 | 创建 |
| 36 | `.github/ISSUE_TEMPLATE/feature_request.md` | 缺失 | 创建 |
| 37 | `.github/PULL_REQUEST_TEMPLATE.md` | 缺失 | 创建 |
| 38 | `.github/CODEOWNERS` | 缺失 | 创建 |
| 39 | `docs/api.md` | 缺失 | 创建 |
| 40 | `docs/guide.md` | 缺失 | 创建 |

## 四、3 智能体分工（每批次）

### 批次 1（P0+P1）
- **Agent A**: P0 — notebook 04 修正 + CI PostgreSQL 集成测试
- **Agent B**: P1 — README.md + README.zh-CN.md + docs/index.md + GEMINI.md 品牌定位
- **Agent C**: P1 — .pre-commit-config.yaml + 验证

### 批次 2（P2 语言统一）
- **Agent A**: examples/quick_demo.py + build_demo_db.py
- **Agent B**: examples/notebooks/ 12 个 notebook
- **Agent C**: docs/specs/ 3 个 + docs/superpowers/plans/ 3 个

### 批次 3（P3 + MISSING）
- **Agent A**: mkdocs.yml + docs/api.md + docs/guide.md
- **Agent B**: .editorconfig + .env.example + Makefile + CONTRIBUTING.md + SECURITY.md + CODE_OF_CONDUCT.md
- **Agent C**: .github/ ISSUE_TEMPLATE + PR_TEMPLATE + CODEOWNERS

## 五、验证标准

```bash
# 批次 1 验证
ruff check . && mypy src/sqlseed/ plugins/
python -m pytest tests/ -k "not postgresql_real_llm and not pg and not url_passes" --tb=short -q
python -c "from sqlseed.cli.main import cli; print('CLI OK')"

# 批次 2 验证
ruff check examples/
python examples/quick_demo.py --help  # 或类似验证

# 批次 3 验证
mkdocs build --strict
pre-commit run --all-files
```

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| CI PG 集成测试失败 | 中 | CI 阻塞 | 先本地验证，使用 continue-on-error |
| notebook 转英文破坏 JSON | 低 | notebook 无法打开 | 使用 json 库操作 |
| mkdocs build 失败 | 中 | 文档无法部署 | 严格验证 nav 引用 |

## 七、YAGNI 清单（不做）

- ❌ 不修改已优化的 src/sqlseed/、plugins/、tests/
- ❌ 不修改 uv.lock
- ❌ 不重构现有代码逻辑
- ❌ 不添加新功能（仅文档和配置）
