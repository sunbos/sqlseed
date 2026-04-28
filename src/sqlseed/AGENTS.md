<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# sqlseed

## Purpose

主包公共 API 入口和子模块组织。用户通过此包访问所有核心功能。

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 公共 API 导出：fill, connect, fill_from_config, preview, load_config 及类型 |
| `_version.py` | 版本号（hatch-vcs 自动生成，禁止手动修改） |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | 数据生成编排引擎（见 `core/AGENTS.md`） |
| `generators/` | 数据提供者抽象与实现（见 `generators/AGENTS.md`） |
| `database/` | SQLite 数据库适配层（见 `database/AGENTS.md`） |
| `config/` | 配置模型与加载器（见 `config/AGENTS.md`） |
| `cli/` | Click 命令行接口（见 `cli/AGENTS.md`） |
| `_utils/` | 跨模块共享工具（见 `_utils/AGENTS.md`） |
| `plugins/` | pluggy 插件框架集成（见 `plugins/AGENTS.md`） |

## For AI Agents

### Working In This Directory

- `__all__` 只导出用户面向的公共接口，内部实现不要加入
- 新增公共 API 需同步更新 `__all__` 列表
- 保持可选依赖边界：`faker`、`mimesis`、`sqlseed_ai`、`mcp` 相关导入应维持懒加载或局部导入
- CLI 应做薄封装，参数校验和生成逻辑留在库层

### Testing Requirements

```bash
pytest tests/test_public_api.py tests/test_cli.py
```

### Common Patterns

- 公共 API 使用仅关键字参数
- `_version.py` 使用 `importlib.metadata.version("sqlseed")` 动态获取版本，回退 `"0.0.0+unknown"`

## Dependencies

### Internal

- 所有子模块（core, generators, database, config, cli, _utils, plugins）

### External

- 见根目录 `AGENTS.md` 的外部依赖列表

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
