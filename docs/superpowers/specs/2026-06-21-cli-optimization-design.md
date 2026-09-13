# cli/ 目录优化设计文档

**生成日期**: 2026-06-21
**目标目录**: `src/sqlseed/cli/`
**方法论**: 9 步流程（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）
**前序参考**: `2026-06-21-utils-optimization-design.md`（_utils/ 优化已完成）

---

## 1. 背景

`_utils/` 优化已完成并通过验证（ruff/mypy/pytest 100 passed）。用户要求将相同方法论应用到 `cli/` 目录。`cli/` 目录包含 4 个文件，是用户与 sqlseed 交互的入口层，代码质量直接影响用户体验。

### 1.1 用户对齐答复

| 问题 | 用户选择 |
|------|----------|
| `_save_snapshot_cmd` URL/db_path Bug | 修复 Bug + 增加 URL 支持 |
| `fill` 命令是否重构为显式参数 | 重构为显式参数 |
| `signal.SIGALRM` 跨平台方案 | **根本性解决**，不是规避 |
| 3 智能体介入时机 | 方案对齐后执行 |

### 1.2 根本性超时方案调研结论

**调研发现**：
- `_client.py:get_openai_client()` 已为本地后端（LM_STUDIO/OLLAMA）配置 `httpx.Timeout(connect=10s, read=total, write=30s, pool=10s)`
- `analyzer.py:_call_with_fallback()` 已捕获 `APITimeoutError`/`APIConnectionError` 并触发模型降级
- **缺陷**：云端后端（google_ai_studio/openai_compat）未配置显式 timeout，依赖 OpenAI SDK 默认值（可能很长）

**根本性方案**：
1. 在 `_client.py` 中为**所有后端**统一配置 httpx timeout（当前仅本地后端配置）
2. 在 CLI 层**移除 SIGALRM 机制**（冗余防御 + 不跨平台 + 技术债）
3. 超时由 HTTP 客户端层（httpx）统一处理，错误通过 `APITimeoutError` → `RuntimeError` 传播到 CLI 层

**为什么这是根本性解决**：
- 超时责任交给最合适的层（HTTP 客户端），而非用信号 hack 中断主线程
- 跨平台一致（Windows/Linux/macOS 行为统一）
- 云端和本地后端统一处理（消除当前的不一致）
- 移除 `signal.SIGALRM`/`hasattr` 检查/`vars(signal)["alarm"]` 不寻常用法

---

## 2. 影响分析

### 2.1 受影响文件

| 文件 | 变更类型 | 影响范围 |
|------|----------|----------|
| `src/sqlseed/cli/main.py` | 修改 | fill 命令重构、_save_snapshot_cmd Bug 修复、_execute_fill 清理、replay 错误处理、模块 docstring |
| `src/sqlseed/cli/ai_commands.py` | 修改 | 移除 SIGALRM、_sigalrm_handler 位置调整、模块 docstring、_sanitize_table_config 导入优化 |
| `src/sqlseed/cli/AGENTS.md` | 修改 | 日期更新、描述修正、补充 --url/超时机制说明 |
| `src/sqlseed/cli/__init__.py` | 不变 | 无需修改 |
| `plugins/sqlseed-ai/src/sqlseed_ai/_client.py` | 修改 | 为所有后端统一配置 httpx timeout |
| `tests/test_cli.py` | 可能修改 | 适配 fill 命令签名变更（如有必要） |
| `tests/test_ai_plugin.py` | 可能修改 | 适配 SIGALRM 移除后的测试 |

### 2.2 破坏性变更评估

| 变更 | 破坏性 | 缓解措施 |
|------|--------|----------|
| `fill` 命令 `**kwargs` → 显式参数 | 内部实现变更，CLI 接口不变 | 无外部影响 |
| `_save_snapshot_cmd` 增加 `url` 参数 | 内部函数，不影响外部 API | 无 |
| 移除 `signal.SIGALRM` 机制 | 行为变更：Windows 用户不再无超时保护（反而获得超时保护） | 正面变更 |
| `_client.py` 云端后端增加 timeout | 行为变更：云端调用现在有显式超时 | 正面变更，避免无限等待 |

---

## 3. 详细优化计划

### 3.1 P0 Bug 修复

#### 3.1.1 `_save_snapshot_cmd` URL/db_path Bug 修复（main.py:219-229）

**问题**：
```python
# 当前代码（有 Bug）
if opts.get("snapshot"):
    _save_snapshot_cmd(
        fill_url or fill_db_path or "",  # Bug: fill_url 是 URL，被当作 db_path 传给 GeneratorConfig
        ...
    )
```

**修复方案**：为 `_save_snapshot_cmd` 增加 `url` 参数，正确区分 db_path 和 url：

```python
def _save_snapshot_cmd(
    db_path: str | None,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    *,
    url: str | None = None,
) -> None:
    config = GeneratorConfig(
        db_path=db_path,
        url=url,  # 新增：支持 URL 连接
        provider=ProviderType(provider),
        locale=locale,
        tables=[
            TableConfig(
                name=table,
                count=count,
                batch_size=batch_size,
                clear_before=clear,
                seed=seed,
            )
        ],
    )
    manager = SnapshotManager()
    snapshot_path = manager.save(config, table, count, seed)
    click.echo(f"Snapshot saved: {snapshot_path}")
```

**调用处修改**：
```python
if opts.get("snapshot"):
    _save_snapshot_cmd(
        db_path=fill_db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        clear=clear_before,
        url=fill_url,
    )
```

**前置条件**：需确认 `GeneratorConfig` 和 `TableConfig` 是否已支持 `url` 字段（根据 project_memory，`feat/multi-db-support` 分支已添加）。

#### 3.1.2 `fill` 命令冗余赋值清理（main.py:146）

**问题**：
```python
count = kwargs.get("count")
# ... 校验逻辑 ...
kwargs["count"] = count  # 冗余：count 已经在 kwargs 中
```

**修复**：重构为显式参数后，此问题自动消失（见 3.2.1）。

### 3.2 P1 代码质量

#### 3.2.1 `fill` 命令重构为显式参数（main.py:115-147）

**问题**：当前使用 `**kwargs`，与 `preview`/`inspect` 风格不一致，降低类型安全性。

**修复方案**：改为显式参数，与 `preview` 命令风格对齐：

```python
def fill(
    db_path: str | None,
    table: str | None,
    count: int | None,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    config_path: str | None,
    transform_path: str | None,
    snapshot: bool,
    enrich: bool,
    no_ai: bool,
    db_url: str | None,
) -> None:
    """Fill a table with generated test data.

    Use --config for config-driven generation, or provide db_path + --table
    + --count for direct generation. When using --config, CLI options
    override the corresponding YAML values.

    Connection methods (mutually exclusive):
    - Positional db_path: sqlseed fill app.db -t users -n 1000
    - --url flag: sqlseed fill --url "postgresql://user:pass@host/db" -t users -n 1000
    """
    if count is not None and count <= 0:
        logger.debug("Invalid count value", count=count)
        raise click.UsageError(f"--count must be greater than 0, got {count}")

    if not config_path and count is None:
        raise click.UsageError(
            "--count is required when not using --config. Use -n <number> to specify the number of rows to generate."
        )

    # 校验 db_path 和 --url 互斥
    if db_path and db_url:
        raise click.UsageError("Cannot specify both positional db_path and --url. Use one or the other.")
    if not config_path and not db_path and not db_url:
        raise click.UsageError("db_path or --url is required when not using --config.")

    _execute_fill(
        db_path=db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        clear=clear,
        config_path=config_path,
        transform_path=transform_path,
        snapshot=snapshot,
        enrich=enrich,
        no_ai=no_ai,
        db_url=db_url,
    )
```

#### 3.2.2 `_execute_fill` 清理重复默认值（main.py:150-229）

**问题**：click option 已定义默认值，`_execute_fill` 内又用 `opts.get(..., default)` 重复一遍。

**修复方案**：移除函数内重复默认值，依赖 click option 层的默认值。同时改为显式参数：

```python
def _execute_fill(
    *,
    db_path: str | None,
    table: str | None,
    count: int | None,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    config_path: str | None,
    transform_path: str | None,
    snapshot: bool,
    enrich: bool,
    no_ai: bool,
    db_url: str | None,
) -> None:
    if config_path:
        logger.debug("Using config-driven generation", config_path=config_path)
        _fill_from_config_cmd(
            config_path,
            clear_before=clear,
            skip_ai=no_ai,
            count=count,
            provider=provider,
            seed=seed,
            batch_size=batch_size,
            locale=locale,
        )
        return

    if not table:
        raise click.UsageError("--table is required when not using --config")

    # count 为 None 时使用默认值（config 模式下 count 可能为 None）
    effective_count = count if count is not None else _FILL_DEFAULT_COUNT

    # 解析连接目标：db_url 优先于 db_path
    # api_fill 的 db_path 和 url 互斥，需分别传 None
    if db_url:
        fill_db_path: str | None = None
        fill_url: str | None = db_url
    else:
        fill_db_path = db_path
        fill_url = None

    if not (fill_db_path or fill_url):
        raise click.UsageError("db_path or --url is required when not using --config")

    logger.debug("Starting fill", target=fill_url or fill_db_path, table=table, count=effective_count)

    try:
        result = api_fill(
            fill_db_path,
            url=fill_url,
            table=table,
            count=effective_count,
            provider=provider,
            locale=locale,
            seed=seed,
            batch_size=batch_size,
            clear_before=clear,
            enrich=enrich,
            transform=transform_path,
            skip_ai=no_ai,
        )
    except ValueError as exc:
        logger.debug("Fill failed with ValueError", error=str(exc))
        raise click.UsageError(str(exc)) from exc
    click.echo(str(result))
    if result.errors:
        for err in result.errors:
            click.echo(f"  Warning: {err}", err=True)

    if snapshot:
        _save_snapshot_cmd(
            db_path=fill_db_path,
            table=table,
            count=effective_count,
            provider=provider,
            locale=locale,
            seed=seed,
            batch_size=batch_size,
            clear=clear,
            url=fill_url,
        )
```

#### 3.2.3 `replay` 命令增加错误处理（main.py:387-413）

**问题**：`manager.load()` 可能抛出 `FileNotFoundError`，`GeneratorConfig(**data)` 可能抛出 `ValidationError`，均未捕获。

**修复方案**：

```python
@cli.command()
@click.argument("snapshot_path")
def replay(snapshot_path: str) -> None:
    """Replay a previously saved snapshot."""
    manager = SnapshotManager()
    try:
        data = manager.load(snapshot_path)
    except FileNotFoundError as exc:
        raise click.UsageError(f"Snapshot file not found: {snapshot_path}") from exc
    except (ValueError, KeyError) as exc:
        raise click.UsageError(f"Invalid snapshot file format: {exc}") from exc

    try:
        config = GeneratorConfig(**data["config"])
    except Exception as exc:  # Pydantic ValidationError
        raise click.UsageError(f"Invalid config in snapshot: {exc}") from exc

    table_name = data["table_name"]
    count = data["count"]
    seed = data.get("seed")

    table_config = None
    for tc in config.tables:
        if tc.name == table_name:
            table_config = tc
            break

    with DataOrchestrator.from_config(config) as orch:
        result = orch.fill_table(
            table_name=table_name,
            count=count,
            seed=seed,
            batch_size=table_config.batch_size if table_config else 5000,
            clear_before=table_config.clear_before if table_config else False,
            column_configs=table_config.columns if table_config else None,
        )
    click.echo(str(result))
```

#### 3.2.4 `_sigalrm_handler` 位置调整 + SIGALRM 移除（ai_commands.py）

**问题**：
- `_sigalrm_handler` 定义在文件末尾，但在 `ai_suggest` 中引用
- `signal.SIGALRM` 不跨平台
- `vars(signal)["alarm"]` 用法不寻常

**修复方案**：根本性移除 SIGALRM 机制，依赖 LLM 客户端层超时（见 3.4.1）。

```python
# 移除以下代码：
# - _sigalrm_handler 函数
# - ai_suggest 中的 SIGALRM 注册/恢复逻辑
# - import signal

# ai_suggest 简化为：
def ai_suggest(
    db_path: str,
    table: str,
    output: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    max_retries: int,
    verify: bool,
    no_cache: bool,
    timeout: float,
) -> None:
    """Analyze table schema and suggest generation rules via AI."""
    if not HAS_AI_PLUGIN:
        raise click.UsageError("sqlseed-ai plugin is required for this command. Run `pip install sqlseed-ai`.")

    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)
    ai_config.timeout = timeout

    if not ai_config.resolve_api_key():
        click.echo(
            "Error: AI API key not configured. "
            "Set SQLSEED_AI_API_KEY or OPENAI_API_KEY. "
            "For Google AI Studio, set GOOGLE_API_KEY. "
            "For LM Studio/Ollama, set SQLSEED_AI_BACKEND=lm_studio or ollama.",
            err=True,
        )
        raise SystemExit(1)

    resolved_model = ai_config.resolve_model()
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})")

    analyzer = SchemaAnalyzer(config=ai_config)

    # 超时由 LLM 客户端层（httpx）统一处理，无需 CLI 层信号 hack
    try:
        result = _run_ai_analysis(analyzer, db_path, table, verify, max_retries, no_cache)
    except (ValueError, RuntimeError, OSError) as exc:
        err_msg = str(exc).lower()
        if "timeout" in err_msg or "timed out" in err_msg:
            click.echo(
                f"\nError: AI suggestion timed out. "
                f"Try a different model with --model, or increase timeout with --timeout.",
                err=True,
            )
        else:
            click.echo(f"AI suggestion failed: {exc}", err=True)
        raise SystemExit(1) from exc

    if result:
        _write_ai_output(output, db_path, result)
    else:
        _report_ai_failure()
```

#### 3.2.5 模块级 docstring 补充

**main.py** 顶部增加：
```python
"""sqlseed CLI 入口模块。

定义 `cli` group 和核心子命令：fill, preview, inspect, init, replay。
AI 相关命令（ai-suggest）在 ai_commands.py 中定义，通过模块级 import 注册。
"""
```

**ai_commands.py** 顶部增加：
```python
"""sqlseed CLI AI 子命令模块。

定义 `ai-suggest` 命令，调用 sqlseed-ai 插件分析表结构并生成数据配置建议。
支持流式输出显示和自纠正流程。
"""
```

### 3.3 P2 文档更新

#### 3.3.1 AGENTS.md 更新

- 日期：`2026-04-29` → `2026-06-21`
- Purpose 描述修正：`fill、preview、init、snapshot` → `fill、preview、inspect、init、replay、ai-suggest`
- Key Files 补充：`__init__.py` 行
- Common Patterns 补充：
  - `--url` 多数据库支持（与 db_path 互斥）
  - `_StreamingProgressDisplay` 流式进度显示
  - 超时机制：LLM 客户端层（httpx）统一处理，CLI 层不使用信号
- Testing Requirements 补充：`pytest tests/test_cli.py tests/test_ai_plugin.py`

### 3.4 P3 设计优化

#### 3.4.1 `_client.py` 统一超时配置（根本性修复）

**问题**：当前只为本地后端配置 httpx timeout，云端后端依赖 OpenAI SDK 默认值。

**修复方案**：为所有后端统一配置 timeout：

```python
def get_openai_client(config: AIConfig | None = None) -> Any:
    if config is None:
        config = AIConfig.from_env()

    kwargs = config.to_openai_kwargs()
    # 所有后端统一配置 httpx 超时：
    # - connect=10s：快速检测死连接
    # - read=total：允许慢推理（本地 GPU）
    # - write=30s：上传 prompt 的超时
    # - pool=10s：连接池获取超时
    kwargs["timeout"] = httpx_timeout(config.resolve_timeout())
    logger.info("Creating OpenAI client", **{"backend": config.backend.value, "base_url": kwargs["base_url"]})
    return OpenAI(**kwargs)
```

**影响**：
- 云端后端现在有显式超时（之前依赖 SDK 默认值）
- 本地后端行为不变（原本就有 timeout）
- 移除 `if config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA)` 条件分支

#### 3.4.2 `_sanitize_table_config` 导入优化（ai_commands.py:265）

**问题**：跨模块导入私有函数（`from sqlseed.cli.main import _sanitize_table_config`）。

**修复方案**：保持现状（YAGNI）。该函数仅在 ai_commands.py 使用一次，提升为公共函数会过度设计。在注释中说明跨模块导入的原因即可。

---

## 4. 3 智能体交叉执行计划

### 4.1 智能体分工

| 智能体 | 职责 | 范围 |
|--------|------|------|
| **Agent A** | main.py 优化 | fill 重构、_save_snapshot_cmd Bug 修复、_execute_fill 清理、replay 错误处理、模块 docstring |
| **Agent B** | ai_commands.py + _client.py 优化 | SIGALRM 移除、_sigalrm_handler 清理、模块 docstring、_client.py 统一超时 |
| **Agent C** | 审查 + 合并 + AGENTS.md 更新 | 审查 A/B 结果、解决冲突、更新 AGENTS.md、运行验证 |

### 4.2 执行顺序

1. **A/B 并行执行**（独立文件，无冲突）
2. **C 审查合并**（A/B 完成后）
3. **C 更新 AGENTS.md**（基于 A/B 的最终代码）
4. **C 运行验证**：`ruff check . && ruff format . && mypy src plugins && python -m pytest`

### 4.3 冲突预防

- A 和 B 操作不同文件，无直接冲突
- AGENTS.md 由 C 统一更新，避免 A/B 同时修改
- `_client.py` 属于 plugins/sqlseed-ai，由 B 独占修改

---

## 5. 验收标准

### 5.1 功能验收

- [ ] `sqlseed fill app.db -t users -n 100` 正常工作
- [ ] `sqlseed fill --url "postgresql://..." -t users -n 100` 正常工作
- [ ] `sqlseed fill app.db -t users -n 100 --snapshot` 保存的 snapshot 中 db_path 正确
- [ ] `sqlseed fill --url "..." -t users -n 100 --snapshot` 保存的 snapshot 中 url 正确（非 db_path）
- [ ] `sqlseed replay <snapshot>` 能正确恢复 URL 连接
- [ ] `sqlseed replay <nonexistent>` 给出友好错误提示
- [ ] `sqlseed ai-suggest ...` 在 Windows 上不再依赖 SIGALRM
- [ ] 云端后端 AI 调用有显式超时

### 5.2 代码质量验收

- [ ] `ruff check .` 全部通过
- [ ] `ruff format .` 无需格式化
- [ ] `mypy src plugins` 无错误
- [ ] `python -m pytest` 全部通过（含原有测试）
- [ ] main.py 和 ai_commands.py 有模块级 docstring
- [ ] `fill` 命令使用显式参数（非 `**kwargs`）
- [ ] 无 `signal.SIGALRM` / `vars(signal)["alarm"]` 残留
- [ ] AGENTS.md 日期为 2026-06-21

---

## 6. YAGNI 清单（不做）

- ❌ 不重构 `_sanitize_table_config` 为公共函数（仅用一次，过度设计）
- ❌ 不为 `replay` 命令增加 `--url` 支持（snapshot 已保存连接信息）
- ❌ 不引入 `threading.Timer` 作为 SIGALRM 替代（httpx timeout 已根本解决）
- ❌ 不重构 CLI 命令为类（Click 函数式风格足够）
- ❌ 不增加新的 CLI 命令或选项

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `GeneratorConfig` 不支持 `url` 字段 | 低 | 阻塞 _save_snapshot_cmd 修复 | 前置检查：确认 feat/multi-db-support 已合并 url 字段 |
| 移除 SIGALRM 后 Windows 用户超时行为变化 | 低 | 正面影响（获得超时保护） | 无需缓解 |
| `_client.py` 修改影响 AI 插件测试 | 中 | 测试失败 | Agent B 负责运行 test_ai_plugin.py 验证 |
| `fill` 重构遗漏参数 | 中 | CLI 报错 | Agent C 审查时对照 click option 列表 |
