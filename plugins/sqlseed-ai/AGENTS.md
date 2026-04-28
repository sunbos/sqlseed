<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# sqlseed-ai

## Purpose

基于 OpenAI 兼容 API 的智能数据生成插件。通过 LLM 分析数据库模式并推荐数据生成配置。

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | 插件元数据，入口点 `ai = "sqlseed_ai:plugin"` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/sqlseed_ai/` | 插件源码（见 `src/sqlseed_ai/AGENTS.md`） |

## For AI Agents

### Working In This Directory

- 保持可选插件边界，主包 `sqlseed` 不能因 `openai` 未安装而整体失效
- OpenAI API 调用需处理 `APITimeoutError`/`APIConnectionError`/`APIError`

### Testing Requirements

```bash
pip install -e "./plugins/sqlseed-ai"
pytest tests/test_ai_plugin.py tests/test_refiner.py
```

### Common Patterns

- 构建系统：hatchling + hatch-vcs（root 指向项目根目录）
- 入口点：`[project.entry-points."sqlseed"]` 中的 `ai = "sqlseed_ai:plugin"`

## Dependencies

### Internal

- `sqlseed>=0.1.0,<2`

### External

- `openai>=1.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
