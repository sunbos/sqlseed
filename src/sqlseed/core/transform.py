from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Protocol, cast


class RowTransformFn(Protocol):
    def __call__(self, row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]: ...


def load_transform(script_path: str) -> RowTransformFn:
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Transform script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("user_transform", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load transform script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, "transform_row", None)
    if fn is None:
        raise AttributeError(
            f"Transform script must define a 'transform_row(row, ctx)' function: {script_path}"
        )
    return cast(RowTransformFn, fn)
