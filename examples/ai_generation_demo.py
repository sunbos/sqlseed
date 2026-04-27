"""
sqlseed AI 数据生成示例

演示两种 AI 生成模式：
  1. 默认自动选择免费模型（OpenRouter）
  2. 指定特定模型

前置条件：
  pip install -e ".[all,dev]"
  pip install -e "./plugins/sqlseed-ai"

  设置 API Key（OpenRouter 免费）：
  export SQLSEED_AI_API_KEY="your-openrouter-api-key"

  或使用其他 OpenAI 兼容 API：
  export SQLSEED_AI_API_KEY="your-api-key"
  export SQLSEED_AI_BASE_URL="https://api.openai.com/v1"
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import sqlseed
from sqlseed.config.loader import save_config
from sqlseed.config.models import (
    ColumnConfig,
    GeneratorConfig,
    ProviderType,
    TableConfig,
)


_CMD_FILL = "sqlseed fill --config config.yaml"
_CMD_AI_SUGGEST = "sqlseed ai-suggest test.db --table users --output config.yaml"


def _create_sample_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            age INTEGER,
            bio TEXT,
            city TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _build_user_config(db_path: str) -> GeneratorConfig:
    return GeneratorConfig(
        db_path=db_path,
        provider=ProviderType("ai"),
        locale="zh_CN",
        tables=[
            TableConfig(
                name="users",
                count=10,
                columns=[
                    ColumnConfig(name="username", generator="name"),
                    ColumnConfig(name="email", generator="email"),
                    ColumnConfig(name="age", generator="integer", params={"min_value": 18, "max_value": 65}),
                    ColumnConfig(name="bio", generator="sentence"),
                    ColumnConfig(name="city", generator="choice", params={"choices": ["北京", "上海", "深圳", "杭州", "成都"]}),
                    ColumnConfig(name="created_at", generator="datetime"),
                ],
            ),
        ],
    )


def _run_example(db_path: str, label: str) -> None:
    config = _build_user_config(db_path)
    config_path = str(Path(db_path).parent / "config.yaml")
    save_config(config, config_path)

    print("=" * 60)
    print(label)
    print("=" * 60)

    results = sqlseed.fill_from_config(config_path)
    for r in results:
        print(f"  表: {r.table_name}, 插入: {r.count} 行, 耗时: {r.elapsed:.2f}s")

    _print_table(db_path, "users")


def example_1_default_model() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "example1.db")
        _create_sample_db(db_path)
        _run_example(db_path, "方式一：默认自动选择免费模型（OpenRouter）")


def example_2_specified_model() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "example2.db")
        _create_sample_db(db_path)

        print("=" * 60)
        print("方式二：指定特定模型")
        print("  设置环境变量后运行：")
        print("  SQLSEED_AI_MODEL='deepseek/deepseek-r1-0528:free' \\")
        print("  SQLSEED_AI_API_KEY='your-key' \\")
        print("  python examples/ai_generation_demo.py")
        print("=" * 60)

        _run_example(db_path, "方式二：指定特定模型")


def example_3_cli_usage() -> None:
    """方式三：使用 CLI 命令

    CLI 提供了 ai-suggest 命令，可以自动分析表结构并生成配置。
    """
    print("=" * 60)
    print("方式三：CLI 命令行使用")
    print("=" * 60)
    print()
    print("# 1. 自动选择免费模型（默认行为）")
    print(_CMD_AI_SUGGEST)
    print(_CMD_FILL)
    print()
    print("# 2. 指定特定模型")
    print(_CMD_AI_SUGGEST + " \\")
    print("  --model 'deepseek/deepseek-r1-0528:free' \\")
    print("  --api-key 'your-openrouter-key'")
    print(_CMD_FILL)
    print()
    print("# 3. 使用 OpenAI 官方 API")
    print(_CMD_AI_SUGGEST + " \\")
    print("  --model 'gpt-4o-mini' \\")
    print("  --api-key 'sk-xxx' \\")
    print("  --base-url 'https://api.openai.com/v1'")
    print(_CMD_FILL)
    print()
    print("# 4. 使用 DeepSeek API")
    print(_CMD_AI_SUGGEST + " \\")
    print("  --model 'deepseek-chat' \\")
    print("  --api-key 'sk-xxx' \\")
    print("  --base-url 'https://api.deepseek.com/v1'")
    print(_CMD_FILL)


def _print_table(db_path: str, table_name: str, limit: int = 5) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    print(f"\n  {table_name} 表前 {limit} 行：")
    col_widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) for i, c in enumerate(columns)]
    header = " | ".join(str(c).ljust(w) for c, w in zip(columns, col_widths))
    print(f"  {header}")
    print(f"  {'-' * len(header)}")
    for row in rows:
        print(f"  {' | '.join(str(v).ljust(w) for v, w in zip(row, col_widths))}")
    print()


if __name__ == "__main__":
    print("\nsqlseed AI 数据生成示例\n")

    example_1_default_model()
    print()
    example_2_specified_model()
    print()
    example_3_cli_usage()
