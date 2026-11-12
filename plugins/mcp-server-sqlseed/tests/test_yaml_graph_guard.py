"""Graph traversal keeps alias identity and detects cycles at all container boundaries."""

from __future__ import annotations

import pytest
from mcp_server_sqlseed.server import _validate_acyclic_yaml


@pytest.mark.parametrize("shape", ["dict", "list", "tuple"])
@pytest.mark.parametrize("cyclic", [False, True])
def test_wide_shared_alias_graph_preserves_nodes(shape: str, cyclic: bool) -> None:
    leaf: list[object] = []
    members = [leaf] * 5000
    containers = {"dict": dict(enumerate(members)), "list": members, "tuple": tuple(members)}
    root = containers[shape]
    if cyclic:
        leaf.append(root)
    before = tuple(id(child) for child in (root.values() if isinstance(root, dict) else root))

    if cyclic:
        with pytest.raises(ValueError, match="Configuration contains a cyclic YAML alias reference"):
            _validate_acyclic_yaml(root)
    else:
        _validate_acyclic_yaml(root)

    assert tuple(id(child) for child in (root.values() if isinstance(root, dict) else root)) == before
    assert all(child is leaf for child in (root.values() if isinstance(root, dict) else root))
    assert len(leaf) == int(cyclic)
    if cyclic:
        assert leaf[0] is root


@pytest.mark.parametrize("value", [None, 0, "scalar", {}, [], ()])
def test_scalar_and_empty_nodes_are_accepted(value: object) -> None:
    _validate_acyclic_yaml(value)
