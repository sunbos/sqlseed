# config/ 目录优化设计文档

**生成日期**: 2026-06-21
**目标目录**: `src/sqlseed/config/`
**方法论**: 9 步流程（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）
**前序参考**: `2026-06-21-utils-optimization-design.md`、`2026-06-21-cli-optimization-design.md`

---

## 1. 背景

`_utils/` 和 `cli/` 优化已完成并通过验证。用户要求将相同方法论应用到 `config/` 目录。`config/` 目录包含 5 个文件，是 sqlseed 配置系统的核心，定义了 Pydantic 模型、加载器和快照管理。

### 1.1 用户对齐答复

| 问题 | 用户选择 |
|------|----------|
| `GeneratorConfig.log_level` 死字段 | 删除 log_level 字段 |
| `generate_template` 是否支持 URL | 增加 URL 支持 |
| validator 方法命名 | 保持现状 |
| 3 智能体介入时机 | 方案对齐后执行 |

### 1.2 关键调研结论

**`log_level` 字段调研**：
- `GeneratorConfig.log_level`（models.py:142）从未被读取使用
- CLI 用环境变量 `SQLSEED_LOG_LEVEL` 控制日志级别（main.py:34）
- 删除后，已有配置文件中的 `log_level` 会被 Pydantic 忽略（`model_config` 默认 `extra='ignore'`），不会报错

**`generate_template` URL 支持调研**：
- 当前 `generate_template(db_path: str, table_name: str | None = None)` 只支持 SQLite 文件路径
- `_read_sqlite_table_names` 直接用 `sqlite3` 模块读取表名
- `SQLAlchemyAdapter.connect()` 已支持 URL 和文件路径（sqlalchemy_adapter.py:113）
- 测试 `test_generate_template_does_not_accept_url` 明确断言不支持 URL，需更新

**`init` 命令调研**：
- 当前 `init` 命令只有 `--db` 选项（默认 "test.db"），不支持 `--url`
- 需增加 `--url` 选项，与 `--db` 互斥

---

## 2. 影响分析

### 2.1 受影响文件

| 文件 | 变更类型 | 影响范围 |
|------|----------|----------|
| `src/sqlseed/config/models.py` | 修改 | 删除 `log_level` 字段、模块 docstring |
| `src/sqlseed/config/loader.py` | 修改 | `generate_template` URL 支持、`_read_table_names` 重构、模块/函数 docstring、常量提取 |
| `src/sqlseed/config/snapshot.py` | 修改 | 模块/类/方法 docstring |
| `src/sqlseed/config/AGENTS.md` | 修改 | 日期更新、描述补充 |
| `src/sqlseed/config/__init__.py` | 不变 | 无需修改 |
| `src/sqlseed/cli/main.py` | 修改 | `init` 命令增加 `--url` 选项 |
| `tests/test_config/test_loader.py` | 修改 | 更新 `test_generate_template_does_not_accept_url`、适配 `_read_table_names` |
| `tests/test_config/test_models.py` | 可能修改 | 移除 `log_level` 相关测试（如有） |
| `tests/test_cli.py` | 可能修改 | 增加 `init --url` 测试（如有必要） |

### 2.2 破坏性变更评估

| 变更 | 破坏性 | 缓解措施 |
|------|--------|----------|
| 删除 `GeneratorConfig.log_level` 字段 | 低：已有配置文件的 `log_level` 会被忽略 | Pydantic `extra='ignore'` 自动处理 |
| `generate_template` 签名变更 | 中：`db_path` 从 `str` 变为 `str | None`，增加 `url` 参数 | 保持 positional 兼容，旧调用 `generate_template("test.db")` 仍可用 |
| `_read_sqlite_table_names` → `_read_table_names` | 低：私有函数，但测试直接引用 | 更新测试导入 |
| `init` 命令增加 `--url` | 无：新增选项，向后兼容 | 保留 `--db` 默认值 |

---

## 3. 详细优化计划

### 3.1 P0: 删除 `log_level` 死字段（models.py:142）

**问题**：`GeneratorConfig.log_level` 从未被读取使用，CLI 用环境变量控制日志级别。

**修复**：删除该字段。

```python
# 删除这一行：
# log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
```

**影响**：
- 已有配置文件中的 `log_level` 会被 Pydantic 忽略（`model_config` 默认 `extra='ignore'`）
- 如果有测试覆盖 `log_level`，需移除
- `Literal` 导入如果不再使用，需移除（检查其他字段是否用 `Literal`）

### 3.2 P0: `generate_template` 增加 URL 支持（loader.py）

**问题**：`generate_template` 只支持 SQLite 文件路径，不支持 URL。

**修复方案**：

#### 3.2.1 `_read_sqlite_table_names` → `_read_table_names`

用 SQLAlchemy 替代 sqlite3，支持多数据库：

```python
def _read_table_names(target: str) -> list[str]:
    """读取数据库中的所有用户表名。

    支持 SQLite 文件路径和数据库 URL（postgresql://、mysql:// 等）。
    排除 SQLite 系统表（sqlite_ 前缀）。

    Args:
        target: 数据库文件路径或 URL

    Returns:
        用户表名列表

    Raises:
        OSError: 文件不存在或无法访问
        RuntimeError: 数据库驱动未安装或连接失败
        ValueError: 无效的 URL
    """
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    # 纯文件路径自动转为 SQLite URL
    db_url = target if "://" in target else f"sqlite:///{target}"
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        # inspector.get_table_names() 默认不返回 SQLite 系统表，但保险起见过滤
        return [name for name in table_names if not name.startswith("sqlite_")]
    finally:
        engine.dispose()
```

#### 3.2.2 `generate_template` 签名变更

```python
_DEFAULT_TEMPLATE_COUNT = 1000


def generate_template(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table_name: str | None = None,
) -> GeneratorConfig:
    """生成配置模板。

    从数据库读取表名，生成包含所有表的配置模板。
    支持 SQLite 文件路径和数据库 URL（postgresql://、mysql:// 等）。

    Args:
        db_path: SQLite 数据库文件路径。与 url 互斥。
        url: 数据库 URL（如 postgresql://user:pass@host/db）。与 db_path 互斥。
        table_name: 若指定，仅生成该表的配置（不读取数据库）。

    Returns:
        GeneratorConfig 配置模板

    Raises:
        ValueError: 当 db_path 和 url 同时提供，或都未提供时
    """
    if db_path and url:
        raise ValueError("Cannot specify both 'db_path' and 'url'. Use one or the other.")
    if not db_path and not url:
        raise ValueError("Either 'db_path' or 'url' must be provided.")

    tables: list[TableConfig] = []
    if table_name:
        tables.append(
            TableConfig(
                name=table_name,
                count=_DEFAULT_TEMPLATE_COUNT,
                columns=[],
            )
        )
    else:
        connection_target = url if url else db_path
        if connection_target is None:
            raise ValueError("Either db_path or url must be provided.")
        try:
            for tbl_name in _read_table_names(connection_target):
                tables.append(
                    TableConfig(
                        name=tbl_name,
                        count=_DEFAULT_TEMPLATE_COUNT,
                        columns=[],
                    )
                )
        except (OSError, ValueError, RuntimeError):
            logger.warning("Could not read tables from database", target=connection_target)

    return GeneratorConfig(
        db_path=db_path,
        url=url,
        tables=tables,
    )
```

**关键变更**：
- `db_path` 从 `str` 变为 `str | None = None`
- 增加 `url` 关键字参数
- `table_name` 改为关键字参数（保持向后兼容，旧调用 `generate_template("test.db", "users")` 仍可用）
- 提取 `_DEFAULT_TEMPLATE_COUNT = 1000` 常量
- `GeneratorConfig` 构造时传入 `url=url`

### 3.3 P0: `init` 命令增加 `--url` 选项（main.py）

**问题**：`init` 命令只有 `--db` 选项，不支持 `--url`。

**修复方案**：

```python
@cli.command()
@click.argument("config_path")
@click.option("--db", default="test.db", help="Database path for template (default: test.db)")
@click.option(
    "--url",
    "db_url",
    default=None,
    help="Database URL (e.g., postgresql://user:pass@host/db). Alternative to --db.",
)
def init(config_path: str, db: str, db_url: str | None) -> None:
    """Generate a YAML configuration template.

    Connection methods (mutually exclusive):
    - --db flag: sqlseed init config.yaml --db app.db
    - --url flag: sqlseed init config.yaml --url "postgresql://..."
    """
    if db and db_url:
        raise click.UsageError("Cannot specify both --db and --url. Use one or the other.")

    # --db 默认 "test.db"，但如果用户提供了 --url，则忽略 --db 的默认值
    effective_db = None if db_url else db

    config = generate_template(db_path=effective_db, url=db_url)
    save_config(config, config_path)
    click.echo(f"Configuration template saved to: {config_path}")
```

### 3.4 P1: 模块级 docstring 补充

**models.py** 顶部增加：
```python
"""sqlseed 配置模型定义。

基于 Pydantic 构建类型安全的配置模型，包含：
- GeneratorConfig: 全局生成配置（连接目标、provider、locale 等）
- TableConfig: 单表生成配置
- ColumnConfig: 列配置（支持源列和派生列两种模式）
- ColumnAssociation: 跨表列关联声明
- ColumnConstraintsConfig: 列约束配置
- ProviderType: 数据提供者类型枚举
"""
```

**loader.py** 顶部增加：
```python
"""sqlseed 配置文件加载器。

支持 YAML 和 JSON 格式的配置文件加载、保存和模板生成。
模板生成支持 SQLite 文件路径和数据库 URL（多数据库）。
"""
```

**snapshot.py** 顶部增加：
```python
"""sqlseed 配置快照管理。

SnapshotManager 负责保存、加载和列出配置快照，
用于 replay 功能（重新生成之前保存的配置）。
"""
```

### 3.5 P1: 函数/方法 docstring 补充

#### loader.py
- `load_config`: 添加 docstring 说明加载流程
- `save_config`: 添加 docstring 说明保存流程
- `generate_template`: 已在 3.2.2 中添加

#### snapshot.py
- `SnapshotManager` 类: 添加类 docstring
- `save`: 添加方法 docstring
- `load`: 添加方法 docstring
- `list_snapshots`: 添加方法 docstring

### 3.6 P2: AGENTS.md 更新

- 日期：`2026-04-29` → `2026-06-21`
- Key Files 补充 `__init__.py` 行
- Purpose 描述补充 URL 支持
- Common Patterns 补充：
  - `url` 多数据库支持（与 db_path 互斥）
  - `connection_target` property
  - `generate_template` 支持 URL
- Dependencies 补充：
  - Internal: `paths`（snapshot.py 使用 get_cache_dir）
  - External: `typing_extensions`（Self）、`sqlalchemy`（loader.py 读取表名）

### 3.7 测试更新

#### test_loader.py
- `test_generate_template_does_not_accept_url` → 改为 `test_generate_template_accepts_url`
- `TestReadSqliteTableNames` 类名保持（测试 SQLite 行为），但导入改为 `_read_table_names`
- 增加 `test_generate_template_with_url` 测试（如有 PostgreSQL 测试环境）
- 增加 `test_generate_template_db_path_and_url_mutually_exclusive` 测试

#### test_models.py
- 移除 `log_level` 相关测试（如有）

#### test_cli.py
- 增加 `test_init_with_url` 测试（如有 PostgreSQL 测试环境）

---

## 4. 3 智能体交叉执行计划

### 4.1 智能体分工

| 智能体 | 职责 | 范围 |
|--------|------|------|
| **Agent A** | models.py + snapshot.py 优化 | 删除 log_level、模块 docstring、函数/类/方法 docstring |
| **Agent B** | loader.py 优化 | generate_template URL 支持、_read_table_names 重构、模块/函数 docstring、常量提取 |
| **Agent C** | main.py init 命令 + 测试更新 + 审查合并 + AGENTS.md + 验证 | init --url、测试更新、审查 A/B、AGENTS.md、ruff/mypy/pytest |

### 4.2 执行顺序

1. **A/B 并行执行**（独立文件，无冲突）
2. **C 执行 main.py init 修改 + 测试更新**（A/B 完成后）
3. **C 审查 A/B 结果**
4. **C 更新 AGENTS.md**
5. **C 运行验证**：`ruff check . && ruff format . && mypy src plugins && python -m pytest`

### 4.3 冲突预防

- A 和 B 操作不同文件，无直接冲突
- C 操作 main.py（init 命令）和测试文件，与 A/B 无冲突
- AGENTS.md 由 C 统一更新

---

## 5. 验收标准

### 5.1 功能验收

- [ ] `sqlseed init config.yaml` 仍可用（默认 "test.db"）
- [ ] `sqlseed init config.yaml --db app.db` 仍可用
- [ ] `sqlseed init config.yaml --url "postgresql://..."` 新增可用
- [ ] `generate_template("test.db")` 仍可用（positional 兼容）
- [ ] `generate_template(db_path="test.db")` 可用
- [ ] `generate_template(url="postgresql://...")` 可用
- [ ] `generate_template(db_path="test.db", url="...")` 抛 ValueError
- [ ] `GeneratorConfig` 不再有 `log_level` 字段
- [ ] 已有配置文件中的 `log_level` 被忽略（不报错）

### 5.2 代码质量验收

- [ ] `ruff check .` 变更文件全部通过
- [ ] `ruff format .` 无需格式化
- [ ] `mypy src plugins` 无错误
- [ ] `python -m pytest` 全部通过（不含 Docker 环境错误）
- [ ] models.py、loader.py、snapshot.py 有模块级 docstring
- [ ] 所有公共函数/方法有 docstring
- [ ] AGENTS.md 日期为 2026-06-21

---

## 6. YAGNI 清单（不做）

- ❌ 不重构 validator 方法命名（用户选择保持现状）
- ❌ 不为 `SnapshotManager.load` 返回 TypedDict（YAGNI）
- ❌ 不移除 `ColumnConfig.model_config = {"extra": "ignore"}`（防御性保留）
- ❌ 不为 `generate_template` 增加更多参数（如 count、provider 等）
- ❌ 不重构 `connection_target` property（已有验证保护，RuntimeError 不会触发）

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 删除 `log_level` 影响已有用户配置 | 低 | Pydantic `extra='ignore'` 自动忽略 | 无需缓解 |
| `generate_template` 签名变更破坏调用方 | 低 | 保持 positional 兼容 | 旧调用 `generate_template("test.db")` 仍可用 |
| SQLAlchemy 导入增加 loader.py 依赖 | 低 | sqlalchemy 是核心依赖 | 用延迟导入（函数内导入） |
| `_read_table_names` 在无驱动的 PG 上失败 | 中 | 抛 RuntimeError | `generate_template` 已捕获并 warning |
| 测试 `test_generate_template_does_not_accept_url` 需更新 | 确定 | 测试失败 | Agent C 负责更新 |
