"""User transform script loading for the row/batch transform pipeline."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

RowTransformFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def load_transform(script_path: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Load a user transform script and return its ``transform_row`` callable.

    The script is loaded via :mod:`importlib` and must expose a callable named
    ``transform_row(row, ctx)``. Raises ``FileNotFoundError`` if the script is
    missing, ``ImportError`` if it cannot be loaded, ``AttributeError`` if
    ``transform_row`` is absent, or ``TypeError`` if it is not callable.
    """
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Transform script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("user_transform", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load transform script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Use direct attribute access (not getattr with None default) so pylint
    # infers the type as Any (callable) rather than None. getattr with a None
    # default causes pylint to infer the return as None, which propagates
    # through the return type and triggers not-callable (E1102) on callers.
    try:
        transform_fn_any: Any = module.transform_row
    except AttributeError:
        raise AttributeError(
            f"Transform script must define a 'transform_row(row, ctx)' function: {script_path}"
        ) from None
    if not callable(transform_fn_any):
        raise TypeError(f"Transform script's 'transform_row' must be a callable function: {script_path}")
    fn: RowTransformFn = transform_fn_any
    return fn
