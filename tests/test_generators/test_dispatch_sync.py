"""Verify GENERATOR_MAP stays in sync with BaseProvider methods."""

from __future__ import annotations

import warnings

from sqlseed.generators._dispatch import verify_dispatch_sync


def test_dispatch_map_sync():
    """verify_dispatch_sync should not emit any warnings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        verify_dispatch_sync()
    assert len(caught) == 0, f"Dispatch sync warnings: {[str(w.message) for w in caught]}"
