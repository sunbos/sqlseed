"""
快速入门演示脚本 - 实时进度显示

功能：
- 创建包含 8 张表的演示数据库
- 带实时进度条填充测试数据
- 展示完成统计和样本数据
- 快速执行（约 10 秒）

用法：
    python quick_demo.py

适合现场演示！
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from build_demo_db import build as build_demo
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from sqlseed import fill


def main():
    console = Console()

    # 步骤 1：创建数据库
    console.print("\n[bold blue]🚀 快速入门演示：sqlseed SQLite 测试数据生成器[/bold blue]")
    console.print("=" * 60)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("正在创建演示数据库...", total=None)
        db_path = str(build_demo(Path(__file__).parent / "_demo.db"))
        progress.update(task, completed=1)

    console.print(f"✅ 数据库已创建：[green]{db_path}[/green]")

    # 步骤 2：带进度条填充数据
    console.print("\n[bold blue]📊 正在填充测试数据（实时进度）：[/bold blue]")

    fill_stats = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        refresh_per_second=2,
    ) as progress:
        # organizations
        task = progress.add_task("organizations", total=10)
        result = fill(db_path, table="organizations", count=10)
        fill_stats.append(("organizations", result.count, result.elapsed))
        progress.update(task, completed=10)

        # members
        task = progress.add_task("members", total=100)
        result = fill(db_path, table="members", count=100)
        fill_stats.append(("members", result.count, result.elapsed))
        progress.update(task, completed=100)

        # projects
        task = progress.add_task("projects", total=30)
        result = fill(db_path, table="projects", count=30)
        fill_stats.append(("projects", result.count, result.elapsed))
        progress.update(task, completed=30)

        # tasks
        task = progress.add_task("tasks", total=200)
        result = fill(db_path, table="tasks", count=200)
        fill_stats.append(("tasks", result.count, result.elapsed))
        progress.update(task, completed=200)

    # 步骤 3：展示汇总统计
    console.print("\n[bold blue]📈 填充统计：[/bold blue]")
    table = Table(show_header=True, header_style="bold green")
    table.add_column("表名")
    table.add_column("行数")
    table.add_column("耗时 (s)", justify="right")

    total_rows = 0
    total_time = 0.0
    for table_name, count, elapsed in fill_stats:
        table.add_row(table_name, str(count), f"{elapsed:.2f}")
        total_rows += count
        total_time += elapsed

    table.add_row("[bold]合计[/bold]", str(total_rows), f"[bold]{total_time:.2f}[/bold]")
    console.print(table)

    # 步骤 4：展示样本数据
    console.print("\n[bold blue]🔍 样本数据预览：[/bold blue]")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 预览 members 表
    console.print("\n[bold green]members[/bold green]（3 行）：")
    cursor = conn.execute("SELECT member_id, name, email, org_code FROM members LIMIT 3")
    rows = cursor.fetchall()
    member_table = Table()
    for col in ("member_id", "name", "email", "org_code"):
        member_table.add_column(col, style="cyan")
    for row in rows:
        member_table.add_row(*[str(row[c]) for c in ("member_id", "name", "email", "org_code")])
    console.print(member_table)

    # 预览 tasks 表
    console.print("\n[bold green]tasks[/bold green]（3 行）：")
    cursor = conn.execute("SELECT task_id, project_id, title, priority, status FROM tasks LIMIT 3")
    rows = cursor.fetchall()
    task_table = Table()
    for col in ("task_id", "project_id", "title", "priority", "status"):
        task_table.add_column(col, style="cyan")
    for row in rows:
        task_table.add_row(*[str(row[c]) for c in ("task_id", "project_id", "title", "priority", "status")])
    console.print(task_table)

    conn.close()

    # 步骤 5：结束信息
    console.print("\n" + "=" * 60)
    console.print("[bold green]🎉 演示完成！[/bold green]")
    console.print("\n已展示的核心功能：")
    console.print("  • 自动模式检测")
    console.print("  • 智能列类型匹配")
    console.print("  • 外键完整性")
    console.print("  • 实时进度追踪")
    console.print(f"\n[italic]总耗时：[/italic][bold]{total_time:.2f} 秒[/bold]")


if __name__ == "__main__":
    main()
