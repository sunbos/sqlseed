"""
QuickStart Demo Script with Real-time Progress Display

Features:
- Creates demo database with 8 tables
- Fills data with real-time progress bars
- Shows completion stats and sample data
- Fast execution (~10 seconds total)

Usage:
    python quick_demo.py

Perfect for live demonstrations!
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

    # Step 1: Create database
    console.print("\n[bold blue]🚀 QuickStart Demo: sqlseed SQLite Test Data Generator[/bold blue]")
    console.print("=" * 60)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Creating demo database...", total=None)
        db_path = str(build_demo(Path(__file__).parent / "_demo.db"))
        progress.update(task, completed=1)

    console.print(f"✅ Database created: [green]{db_path}[/green]")

    # Step 2: Fill data with progress
    console.print("\n[bold blue]📊 Filling test data with real-time progress:[/bold blue]")

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

    # Step 3: Show summary
    console.print("\n[bold blue]📈 Fill Summary:[/bold blue]")
    table = Table(show_header=True, header_style="bold green")
    table.add_column("Table")
    table.add_column("Rows")
    table.add_column("Time (s)", justify="right")

    total_rows = 0
    total_time = 0.0
    for table_name, count, elapsed in fill_stats:
        table.add_row(table_name, str(count), f"{elapsed:.2f}")
        total_rows += count
        total_time += elapsed

    table.add_row("[bold]Total[/bold]", str(total_rows), f"[bold]{total_time:.2f}[/bold]")
    console.print(table)

    # Step 4: Show sample data
    console.print("\n[bold blue]🔍 Sample Data Preview:[/bold blue]")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Preview members
    console.print("\n[bold green]members[/bold green] (3 rows):")
    cursor = conn.execute("SELECT member_id, name, email, org_code FROM members LIMIT 3")
    rows = cursor.fetchall()
    member_table = Table()
    for col in ("member_id", "name", "email", "org_code"):
        member_table.add_column(col, style="cyan")
    for row in rows:
        member_table.add_row(*[str(row[c]) for c in ("member_id", "name", "email", "org_code")])
    console.print(member_table)

    # Preview tasks
    console.print("\n[bold green]tasks[/bold green] (3 rows):")
    cursor = conn.execute("SELECT task_id, project_id, title, priority, status FROM tasks LIMIT 3")
    rows = cursor.fetchall()
    task_table = Table()
    for col in ("task_id", "project_id", "title", "priority", "status"):
        task_table.add_column(col, style="cyan")
    for row in rows:
        task_table.add_row(*[str(row[c]) for c in ("task_id", "project_id", "title", "priority", "status")])
    console.print(task_table)

    conn.close()

    # Step 5: Final message
    console.print("\n" + "=" * 60)
    console.print("[bold green]🎉 Demo Complete! [/bold green]")
    console.print("\nKey Features Demonstrated:")
    console.print("  • Auto-schema detection")
    console.print("  • Smart column type matching")
    console.print("  • Foreign key integrity")
    console.print("  • Real-time progress tracking")
    console.print(f"\n[italic]Total time:[/italic] [bold]{total_time:.2f} seconds[/bold]")


if __name__ == "__main__":
    main()
