from __future__ import annotations

from sqlseed_ai.healer.subgraph import (
    SubgraphSplitter,
    TarjanSCC,
    broken_edges_from_split,
)


def _fk_graph(edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        graph.setdefault(dst, [])  # ensure every node is present
    return graph


def test_tarjan_no_cycles_returns_singletons():
    graph = _fk_graph([("users", "orders")])
    sccs = TarjanSCC.find_sccs(graph)
    assert len(sccs) == 2
    flat = {frozenset(s) for s in sccs}
    assert frozenset({"users"}) in flat
    assert frozenset({"orders"}) in flat


def test_tarjan_detects_two_node_cycle():
    graph = _fk_graph([("a", "b"), ("b", "a")])
    sccs = TarjanSCC.find_sccs(graph)
    assert len(sccs) == 1
    assert set(sccs[0]) == {"a", "b"}


def test_tarjan_detects_three_node_cycle():
    graph = _fk_graph([("a", "b"), ("b", "c"), ("c", "a")])
    sccs = TarjanSCC.find_sccs(graph)
    assert len(sccs) == 1
    assert set(sccs[0]) == {"a", "b", "c"}


def test_megacluster_breaking_splits_large_scc():
    """Defense 6: SCC > 3 tables is broken at weak links."""
    # 5-table cycle: a -> b -> c -> d -> e -> a
    graph = _fk_graph([
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "a"),
    ])
    splitter = SubgraphSplitter(max_scc_size=3)
    subgraphs, broken = splitter.split(graph)
    # At least 2 subgraphs after breaking
    assert len(subgraphs) >= 2
    # Each subgraph should be <= 3 tables
    for sg in subgraphs:
        assert len(sg) <= 3
    # At least one broken edge recorded
    assert len(broken) >= 1


def test_megacluster_no_break_for_small_scc():
    """SCC with <=3 tables is preserved (no breaking)."""
    graph = _fk_graph([("a", "b"), ("b", "c"), ("c", "a")])
    splitter = SubgraphSplitter(max_scc_size=3)
    subgraphs, broken = splitter.split(graph)
    assert len(subgraphs) == 1
    assert set(subgraphs[0]) == {"a", "b", "c"}
    assert broken == []


def test_broken_edges_recorded_for_post_repair():
    """Broken edges are returned for post-repair alignment."""
    graph = _fk_graph([
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "a"),
    ])
    splitter = SubgraphSplitter(max_scc_size=3)
    _, broken = splitter.split(graph)
    # Each broken edge is a (src, dst) tuple
    for edge in broken:
        assert isinstance(edge, tuple)
        assert len(edge) == 2


def test_broken_edges_from_split_helper():
    """Helper produces post-repair alignment spec."""
    broken = [("a", "b"), ("c", "d")]
    spec = broken_edges_from_split(broken)
    assert spec["count"] == 2
    assert ("a", "b") in spec["edges"]
    assert ("c", "d") in spec["edges"]
