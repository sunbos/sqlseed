from __future__ import annotations

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


def create_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        transient=True,
    )
