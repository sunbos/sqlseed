<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# cli

## Purpose

基于 Click 的命令行工具。提供 fill、preview、inspect、init、replay 子命令，以及 AI 子命令 ai-suggest。

## Key Files

| File | Description |
|------|-------------|
| `main.py` | CLI 入口，定义 `cli` group 和核心子命令（fill, preview, inspect, init, replay） |
| `ai_commands.py` | AI 相关子命令（ai-suggest），由 main.py 在启动时导入 |

## For AI Agents

### Working In This Directory

- 新增子命令需注册到 `cli` group
- AI 功能（sqlseed-ai）通过 `HAS_AI_PLUGIN` 标志控制，ImportError 时静默降级，不能让缺少 sqlseed-ai 导致 CLI 崩溃
- 用户面向的输出使用 click.echo / rich，内部日志使用 structlog
- CLI 层应做薄封装，参数校验和生成逻辑留在库层
- 日志级别通过环境变量 `SQLSEED_LOG_LEVEL` 控制

### Testing Requirements

```bash
pytest tests/test_cli.py
```

### Common Patterns

- 命令结构：`cli` (group) → `fill` / `preview` / `inspect` / `init` / `replay` 子命令（main.py）+ `ai-suggest` 子命令（ai_commands.py）
- 输出使用 rich 库美化（进度条、表格、高亮）
- AI 功能降级模式：`try: from sqlseed_ai import ... except ImportError: HAS_AI_PLUGIN = False`

## Dependencies

### Internal

- `sqlseed` 顶层 API（fill, fill_from_config, preview）
- `core`（DataOrchestrator）
- `config`（load_config, save_config, generate_template, GeneratorConfig, SnapshotManager）
- `_utils`（logger）
- `_version`（__version__）
- `sqlseed-ai`（可选，ai-suggest）

### External

- `click>=8.0` — CLI 框架
- `rich>=13.0` — 美化输出

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
