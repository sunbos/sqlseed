from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable  # noqa: UP035

RowTransformFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def load_transform(script_path: str) -> RowTransformFn:
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Transform script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("user_transform", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load transform script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn_any = getattr(module, "transform_row", None)
    if fn_any is None:
        raise AttributeError(f"Transform script must define a 'transform_row(row, ctx)' function: {script_path}")
    if not callable(fn_any):
        raise TypeError(f"Transform script's 'transform_row' must be a callable function: {script_path}")
    return fn_any  # type: ignore[no-any-return]
