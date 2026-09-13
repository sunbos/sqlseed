from __future__ import annotations

from sqlseed_ai.healer.post_repair import BrokenEdgeAligner


def test_align_adds_nullable_constraint_to_fk():
    """Broken FK edge gets nullable=True to allow post-repair alignment."""
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                ],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "user_id", "generator": "integer"},
                ],
            },
        ]
    }
    aligner = BrokenEdgeAligner()
    broken = [("orders", "users")]
    new_config = aligner.align(config, broken)
    orders = next(t for t in new_config["tables"] if t["name"] == "orders")
    user_id = next(c for c in orders["columns"] if c["name"] == "user_id")
    # The FK column should be marked as nullable for post-repair alignment
    assert user_id.get("nullable") is True or user_id.get("null_ratio") is not None


def test_align_preserves_non_fk_columns():
    """Columns not part of broken edges are untouched."""
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "email"},
                ],
            },
        ]
    }
    aligner = BrokenEdgeAligner()
    new_config = aligner.align(config, [("users", "users")])
    email = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "email")
    assert email.get("generator") == "email"


def test_align_handles_empty_broken_edges():
    """No broken edges = no-op."""
    config = {"tables": [{"name": "t", "columns": [{"name": "id", "generator": "integer"}]}]}
    aligner = BrokenEdgeAligner()
    new_config = aligner.align(config, [])
    assert new_config == config
