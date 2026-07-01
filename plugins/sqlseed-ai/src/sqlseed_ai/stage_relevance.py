"""Layer 2: Stage relevance determination.

Consumes StructuralFeatures (from Layer 1) and outputs StageRelevance —
a deterministic, no-LLM judgment of which structural features each
stage (1/2/3) needs.

Spec §5: stage relevance matrix + determinator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlseed.core.features import StructuralFeatures


@dataclass
class StageRelevance:
    """Per-stage feature relevance, deterministic pre-analysis judgment.

    Each dict maps feature name -> bool (True: stage needs it, False: skip).
    Keys are documented in spec §5.2 relevance matrix.
    """

    stage1: dict[str, bool]  # Structure analysis
    stage2: dict[str, bool]  # Column analysis
    stage3: dict[str, bool]  # Validation + auto-fix


def determine_stage_relevance(features: StructuralFeatures) -> StageRelevance:
    """Determine which features each stage needs.

    Pure deterministic rules, no LLM, dialect-agnostic
    (operates on normalized StructuralFeatures).
    """
    # Detect optional features across all tables
    has_composite_unique = any(len(uc.columns) > 1 for t in features.tables for uc in t.unique_constraints)
    has_composite_fk = any(len(fk.columns) > 1 for t in features.tables for fk in t.foreign_keys)
    has_collate = any(c.collation is not None for t in features.tables for c in t.columns)
    has_strict = any(t.is_strict for t in features.tables)  # SQLite-only
    has_partial_index = any(idx.partial_predicate is not None for t in features.tables for idx in t.indexes)
    has_on_conflict = any(t.on_conflict for t in features.tables)  # SQLite-only
    has_default = any(c.default is not None for t in features.tables for c in t.columns)
    has_autoincrement = any(c.is_autoincrement for t in features.tables for c in t.columns)
    has_generated = any(c.is_computed for t in features.tables for c in t.columns)

    return StageRelevance(
        stage1={
            "tables": True,
            "columns": True,
            "types": True,
            "pk": True,
            "fk": True,
            "check": True,
            "unique": True,
            "composite_unique": has_composite_unique,
            "composite_fk": has_composite_fk,
        },
        stage2={
            "not_null": True,
            "default": has_default,
            "autoincrement": has_autoincrement,
            "generated": has_generated,
            "pk": True,
            "fk": True,
            "check": True,
            "unique": True,
            "collate": has_collate,
            "strict": has_strict,
            "partial_unique": has_partial_index,
        },
        stage3={
            "check": True,
            "fk": True,
            "unique": True,
            "composite_unique": has_composite_unique,
            "on_conflict": has_on_conflict,
            "collate": has_collate,
            "strict": has_strict or features.dialect == "postgresql",
            "partial_unique": has_partial_index,
        },
    )
