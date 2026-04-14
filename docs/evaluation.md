# sqlseed 项目评价与演进路线

> 基于对整个代码库的深度审计，对 sqlseed 的当前状态进行客观评价，并提出后续优化和新增功能建议。

---

## 一、项目现状客观评价

### 1.1 总体评分

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| **架构设计** | ⭐⭐⭐⭐⭐ | Protocol 驱动 + 插件系统 + 分层架构，扩展性极强 |
| **代码质量** | ⭐⭐⭐⭐☆ | 严格类型注解、structlog 日志、统一错误处理，但部分模块缺少文档字符串 |
| **功能完整度** | ⭐⭐⭐⭐☆ | 核心功能完善（生成/映射/FK/约束/快照），但部分高级场景尚未覆盖 |
| **测试覆盖** | ⭐⭐⭐⭐☆ | 模块级测试较全，但集成/端到端测试可加强 |
| **文档质量** | ⭐⭐⭐⭐☆ | README 详尽，AGENTS.md/CLAUDE.md 面向 AI 的元文档优秀 |
| **AI 集成** | ⭐⭐⭐⭐⭐ | 一等公民插件设计、自纠正闭环、MCP 服务器，在同类工具中领先 |
| **性能优化** | ⭐⭐⭐⭐☆ | 流式生成 + PRAGMA 三级优化，但缺乏大规模基准测试数据 |
| **可用性** | ⭐⭐⭐⭐☆ | CLI 功能全面，但错误消息和用户引导可改善 |

### 1.2 架构亮点

#### ✅ Protocol 驱动设计

`DataProvider` 和 `DatabaseAdapter` 采用 `typing.Protocol` 实现，是 Python 类型系统的最佳实践。它达成了两个关键目标：

- **零耦合**：Provider 和 Adapter 不需要继承任何基类，满足 Protocol 形状即可
- **IDE 友好**：mypy/pyright 能静态验证实现的完整性

这种设计比传统的 ABC 继承更 Pythonic，也更适合插件生态。

#### ✅ 8 级策略链映射

`ColumnMapper` 的 8 级策略链（67 条精确规则 + 25 条模式正则 + 22 种类型回退）在同类工具中罕见。这意味着 sqlseed 即使在零配置模式下，也能为大多数常见列名和类型选择合理的生成器——这是"开箱即用"体验的基础。

#### ✅ 列依赖 DAG + 表达式引擎

v2.0 引入的 `ColumnDAG` + `ExpressionEngine` + `ConstraintSolver` 三件套解决了一个真实的工程痛点：派生列（如银行卡号后 8 位）。这在竞品中几乎没有——Faker 和 Mimesis 只能生成独立列，无法处理列间依赖。

#### ✅ AI 自纠正闭环

`AiConfigRefiner` 的设计非常成熟：

- 通过 `ErrorSummary` 将异常转化为结构化的 LLM 修正指令
- 智能区分 7 种错误类型（pydantic_validation / unknown_generator / column_mismatch 等）
- 支持 schema hash 缓存，避免重复 API 调用
- `preview_table(count=5)` 试运行验证，确保配置真正可执行

#### ✅ SharedPool 跨表关联

`SharedPool` + 隐式关联检测是外键维护的优雅方案。不仅处理显式 FK 约束，还能检测同名列的隐式关联——这在真实数据库中非常常见。

### 1.3 待改进之处

#### ⚠️ 文档字符串覆盖率不足

核心类（`DataOrchestrator`、`ColumnMapper`、`DataStream`）的方法大多缺少 docstring。虽然类型注解提供了签名信息，但 docstring 对于 IDE 悬停提示和自动文档生成（Sphinx/mkdocs）至关重要。

#### ⚠️ 错误消息用户友好度

CLI 在遇到错误时有时直接抛出 Python 异常栈。对于非开发者用户，应该有更友好的错误消息和修复建议。例如：

```
# 当前：
# KeyError: 'nonexistent_table'

# 期望：
# Error: Table 'nonexistent_table' not found in database 'app.db'.
# Available tables: users, orders, products
# Hint: Use 'sqlseed inspect app.db' to see all tables.
```

#### ⚠️ 大规模性能基准缺失

项目声称支持高性能批量生成，但缺少标准化的基准测试数据。添加 `benchmarks/` 目录和 CI 集成的性能回归检测会增强可信度。

#### ⚠️ 配置模式互斥的用户体验

`ColumnConfig` 中 `generator` 和 `derive_from` 互斥通过 Pydantic `model_validator` 实现。但错误消息对于不了解内部实现的用户不够直观。

#### ⚠️ 日志过于 Development 导向

`structlog` 的 `ConsoleRenderer` 在生产环境中不太合适。应该支持 JSON 格式输出以便日志聚合工具处理。

#### ⚠️ 测试缺口

- `test_core/` 目录下只有 `test_expression.py`，缺少 `test_column_dag.py`、`test_constraints.py`、`test_transform.py`
- 无端到端 CLI 集成测试（从 YAML 读取 → 生成 → 验证数据库内容）
- AI 插件测试依赖 mock，无法验证真实 LLM 响应的处理能力

---

## 二、短期优化建议（v2.1）

### 2.1 完善文档字符串

为所有公共类和方法添加 Google 风格 docstring。建议使用 `interrogate` 工具在 CI 中强制 docstring 覆盖率 ≥ 90%。

```python
# 参考格式
def fill_table(
    self,
    table_name: str,
    count: int = 1000,
    *,
    column_configs: list[ColumnConfig] | None = None,
) -> GenerationResult:
    """Fill a table with generated test data.

    Args:
        table_name: Name of the target table.
        count: Number of rows to generate.
        column_configs: Optional per-column configurations.
            If not provided, auto-mapping is used.

    Returns:
        GenerationResult with count, elapsed time, and any errors.

    Raises:
        ValueError: If the table does not exist.
        RuntimeError: If database connection is not established.
    """
```

### 2.2 增强错误处理与用户体验

```python
# 1. 自定义异常层次
class SqlseedError(Exception): ...
class TableNotFoundError(SqlseedError): ...
class ColumnConfigError(SqlseedError): ...
class ProviderNotInstalledError(SqlseedError): ...

# 2. CLI 错误美化（Rich 面板）
@cli.command()
def fill(...):
    try:
        ...
    except TableNotFoundError as e:
        console.print(Panel(
            f"[red]Table '{e.table_name}' not found[/red]\n\n"
            f"Available tables: {', '.join(e.available_tables)}\n\n"
            f"[dim]Hint: Use 'sqlseed inspect {db_path}' to see all tables.[/dim]",
            title="❌ Error",
            border_style="red",
        ))
        raise SystemExit(1)
```

### 2.3 补充测试

建议优先补充以下测试：

| 优先级 | 文件 | 覆盖内容 |
|:---|:---|:---|
| P0 | `test_core/test_column_dag.py` | DAG 构建、循环依赖检测、拓扑排序 |
| P0 | `test_core/test_constraints.py` | 唯一性求解、回溯触发、复合约束 |
| P0 | `test_core/test_transform.py` | 脚本加载、transform_row 调用 |
| P1 | `tests/test_e2e.py` | YAML → 生成 → 数据库验证的端到端测试 |
| P1 | `tests/test_dag_backtrack.py` | 派生列回溯的完整场景测试 |
| P2 | `tests/test_perf.py` | 性能回归测试（万行/秒指标） |

### 2.4 添加性能基准

```python
# benchmarks/bench_fill.py
import time
import sqlseed

def benchmark_fill(count: int, provider: str = "base"):
    result = sqlseed.fill(":memory:", table="bench", count=count, provider=provider)
    return {
        "count": count,
        "elapsed": result.elapsed,
        "rows_per_sec": count / result.elapsed,
        "provider": provider,
    }
```

建议在 CI 中使用 `pytest-benchmark` 或 `pyperf` 进行自动化性能跟踪。

### 2.5 日志格式可配置

```python
# 支持 JSON 格式日志输出
def configure_logging(level: str = "INFO", format: str = "console") -> None:
    renderer = (
        structlog.dev.ConsoleRenderer()
        if format == "console"
        else structlog.processors.JSONRenderer()
    )
    # ...
```

---

## 三、中期功能建议（v2.5）

### 3.1 多数据库支持

当前 sqlseed 仅支持 SQLite。作为测试数据生成工具，扩展到其他数据库将显著增加用户群：

```python
# 目标 API
sqlseed.fill("postgresql://user:pass@localhost/testdb", table="users", count=10000)
sqlseed.fill("mysql://user:pass@localhost/testdb", table="users", count=10000)
```

**实现思路**：
- `DatabaseAdapter` Protocol 已经提供了良好的抽象层
- 为 PostgreSQL（通过 `psycopg`）和 MySQL（通过 `pymysql`）分别实现 Adapter
- PRAGMA 优化器需要根据数据库类型切换（PostgreSQL 的 `SET synchronous_commit = off` 等）
- 可以考虑使用 SQLAlchemy 作为通用抽象

### 3.2 Web UI 数据预览

提供一个轻量级 Web 界面，用于可视化预览和配置：

- Tech stack：FastAPI + HTMX（保持轻量）
- 功能：Schema 浏览、实时预览、配置编辑器、生成报告

### 3.3 数据质量验证

生成后自动验证数据质量：

```python
result = sqlseed.fill("app.db", table="users", count=10000)
report = sqlseed.validate("app.db", table="users")
# → ValidationReport(
# →   unique_violations=0,
# →   null_violations=0,
# →   fk_violations=0,
# →   type_mismatches=0,
# →   distribution_uniformity=0.92
# → )
```

### 3.4 增量生成模式

支持在已有数据的基础上增量添加：

```python
# 检测已有 10000 行，从 10001 开始继续生成
sqlseed.fill("app.db", table="users", count=5000, mode="append")

# 保持外键引用到已有数据
sqlseed.fill("app.db", table="orders", count=5000, mode="append", reference_existing=True)
```

### 3.5 数据脱敏 / 混淆模式

从生产数据库读取 Schema 和数据分布，生成统计特征相似但完全匿名的数据：

```python
# 学习生产数据的分布特征
profile = sqlseed.learn("production.db", table="users")

# 用学习到的分布生成测试数据
sqlseed.fill("test.db", table="users", count=10000, profile=profile)
```

### 3.6 并行生成

对于大规模数据生成（百万行+），利用多核并行加速：

```python
# 4 个 worker 并行生成
sqlseed.fill("app.db", table="users", count=1_000_000, workers=4)
```

**注意事项**：
- SQLite 写入需要串行化（使用 WAL 模式可支持并发读 + 单写入）
- 可以将生成和插入分离：多线程生成 → 单线程写入队列
- 约束求解器的全局状态需要通过 `multiprocessing.Manager` 共享

### 3.7 条件生成

基于条件或规则生成关联数据：

```yaml
tables:
  - name: users
    count: 10000
    columns:
      - name: age
        generator: integer
        params: { min_value: 18, max_value: 80 }
      - name: is_student
        generator: choice
        params:
          choices: [true, false]
        conditions:
          - when: "age < 25"
            weight: 0.7    # 25 岁以下 70% 概率是学生
          - when: "age >= 25"
            weight: 0.05   # 25 岁以上 5% 概率
```

---

## 四、长期愿景（v3.0+）

### 4.1 Schema Evolution 追踪

自动检测数据库 Schema 变更并调整生成配置：

```bash
sqlseed migrate --config generate.yaml --db app.db
# → Detected changes:
# →   + Added column: users.avatar_url (TEXT)
# →   - Removed column: users.legacy_status
# →   ~ Modified column: users.age (INTEGER → INTEGER NOT NULL)
# → Updated generate.yaml with new column mappings.
```

### 4.2 Data Relationship Graph

构建完整的数据关系图谱，用于复杂场景的数据生成：

```python
# 自动分析整个数据库的实体关系
graph = sqlseed.analyze_relationships("app.db")
graph.visualize()  # 输出 Mermaid/GraphViz 关系图

# 基于关系图谱一键填充所有表
sqlseed.fill_all("app.db", count_strategy="proportional", total=100_000)
```

### 4.3 测试场景编排

从"生成数据"进化到"编排测试场景"：

```yaml
# scenarios/order_flow.yaml
scenario: "完整订单流程"
steps:
  - fill: { table: users, count: 100 }
  - fill: { table: products, count: 50 }
  - fill:
      table: orders
      count: 500
      constraints:
        - "每个用户至少 1 单"
        - "订单金额正态分布，均值 200，标准差 50"
  - fill:
      table: payments
      count: 500
      constraints:
        - "每个订单恰好 1 条支付记录"
        - "状态分布: paid=70%, pending=20%, failed=10%"
  - validate:
      - "所有外键完整"
      - "所有订单都有对应支付"
```

### 4.4 插件市场

建立社区驱动的插件/Provider 生态：

- **行业 Provider**：金融（银行卡号/SWIFT 代码）、医疗（ICD-10/HL7）、电商（SKU/订单号）
- **地区 Provider**：针对特定国家的身份证号、手机号格式
- **配置模板库**：社区共享的 YAML 配置模板（SaaS 应用、电商、社交网络等常见 Schema）

### 4.5 实时数据流

支持持续生成数据流，用于模拟生产环境的数据写入：

```python
# 每秒插入 100 行，持续 1 小时
with sqlseed.stream("app.db", table="events", rate=100) as s:
    s.run(duration="1h")
    # 支持动态调整速率
    s.set_rate(500)
```

---

## 五、竞品对比

| 特性 | sqlseed | Faker | Mimesis | Factory Boy | Hypothesis |
|:---|:---:|:---:|:---:|:---:|:---:|
| SQLite 原生集成 | ✅ | ❌ | ❌ | ⚠️ 需 ORM | ❌ |
| 零配置 Schema 推断 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 列语义映射 | ✅ 8 级 | ❌ | ❌ | 手动 | ❌ |
| 外键自动维护 | ✅ | ❌ | ❌ | 手动 | ❌ |
| 派生列 + 回溯约束 | ✅ | ❌ | ❌ | ❌ | 部分 |
| AI 驱动配置 | ✅ | ❌ | ❌ | ❌ | ❌ |
| MCP 集成 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 流式内存安全 | ✅ | N/A | N/A | ❌ | ❌ |
| 快照回放 | ✅ | ❌ | ❌ | ❌ | ⚠️(seed) |
| YAML 声明式配置 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 多 Provider 切换 | ✅ | 自身 | 自身 | Faker | 自身 |
| 插件系统 | ✅ 11 Hook | 有 | 无 | 有 | 有 |

**总结**：sqlseed 占据了一个独特的生态位——它不是通用的假数据库（Faker/Mimesis），而是**专注于 SQLite 的声明式测试数据编排工具**。其核心价值在于"零配置 + 智能推断 + AI 辅助"的端到端体验。

---

## 六、建议优先级路线图

```mermaid
gantt
    title sqlseed 功能演进路线图
    dateFormat YYYY-MM
    axisFormat %Y-%m

    section v2.1 (短期优化)
    补充文档字符串         :2026-05, 2026-06
    增强错误处理           :2026-05, 2026-06
    补充测试 (DAG/约束)    :2026-05, 2026-07
    性能基准框架           :2026-06, 2026-07
    日志格式可配置         :2026-06, 2026-07

    section v2.5 (中期功能)
    PostgreSQL 支持        :2026-07, 2026-09
    数据质量验证           :2026-08, 2026-09
    增量生成模式           :2026-08, 2026-10
    Web UI 预览            :2026-09, 2026-11
    并行生成               :2026-10, 2026-11
    条件生成               :2026-10, 2026-12

    section v3.0 (长期愿景)
    Schema Evolution 追踪  :2027-01, 2027-03
    Data Relationship Graph:2027-02, 2027-04
    测试场景编排           :2027-03, 2027-06
    插件市场               :2027-04, 2027-06
    实时数据流             :2027-05, 2027-07
```

---

> 📝 本评价基于 2026 年 4 月 15 日对代码库的完整审计。随着项目演进，部分评价可能需要更新。
