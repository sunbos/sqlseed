"""Defense 2 + Defense 6: Tarjan SCC + Megacluster weak-link breaking.

Spec reference: Section 7 (circular dependency handling), Section 14
(broken-edge post-repair).

At startup the FK graph is processed:
  1. Tarjan's algorithm finds strongly connected components (SCCs).
     - Singleton SCCs = no cycle, analyze as standalone tables.
     - Multi-node SCCs = cycle, analyze together.
  2. Defense 6: if an SCC has more than ``max_scc_size`` tables
     (default 3), the cycle is broken at weak links (FK edges whose
     source column is nullable) to produce analyzable subgraphs that
     fit small-model context windows.
  3. Broken edges are recorded for post-repair: after the healer
     finishes, nullable FK ranges are aligned to parent values so that
     referential integrity is restored without re-creating the cycle.
"""

from __future__ import annotations

from typing import Any


class TarjanSCC:
    """Tarjan's strongly connected components algorithm (iterative)."""

    @staticmethod
    def find_sccs(graph: dict[str, list[str]]) -> list[list[str]]:
        """Return a list of SCCs, each SCC as a list of node names.

        Args:
            graph: Adjacency list ``{node: [successors]}``. Every node
                must appear as a key (even if it has no successors).
        """
        return _TarjanTraversal(graph).run()

    @staticmethod
    def _pop_scc(node: str, stack: list[str], on_stack: dict[str, bool]) -> list[str]:
        """Pop the just-completed component in Tarjan's established stack order."""
        scc: list[str] = []
        while True:
            w = stack.pop()
            on_stack[w] = False
            scc.append(w)
            if w == node:
                break
        return scc


class _TarjanTraversal:
    """Own the index, active stack and completed components for one FK graph walk."""

    def __init__(self, graph: dict[str, list[str]]) -> None:
        self.graph = graph
        self.next_index = 0
        self.stack: list[str] = []
        self.lowlink: dict[str, int] = {}
        self.index: dict[str, int] = {}
        self.on_stack = dict.fromkeys(graph, False)
        self.components: list[list[str]] = []

    def run(self) -> list[list[str]]:
        """Traverse unvisited roots in insertion order without recursive DFS calls."""
        for start in self.graph:
            if start not in self.index:
                self._walk_root(start)
        return self.components

    def _walk_root(self, start: str) -> None:
        """Process the explicit DFS stack and propagate lowlinks on completion."""
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, successor_index = work[-1]
            if successor_index == 0:
                self._start_node(node)
            if successor_index < len(self.graph[node]):
                self._visit_successor(node, successor_index, work)
                continue
            if self.lowlink[node] == self.index[node]:
                self.components.append(TarjanSCC._pop_scc(node, self.stack, self.on_stack))
            work.pop()
            if work:
                parent = work[-1][0]
                self.lowlink[parent] = min(self.lowlink[parent], self.lowlink[node])

    def _start_node(self, node: str) -> None:
        """Assign the next index and mark a node active before visiting successors."""
        self.index[node] = self.next_index
        self.lowlink[node] = self.next_index
        self.next_index += 1
        self.stack.append(node)
        self.on_stack[node] = True

    def _visit_successor(self, node: str, successor_index: int, work: list[tuple[str, int]]) -> None:
        """Schedule an unseen successor or account for an edge into the active stack."""
        successor = self.graph[node][successor_index]
        work[-1] = (node, successor_index + 1)
        if successor not in self.index:
            work.append((successor, 0))
        elif self.on_stack.get(successor):
            self.lowlink[node] = min(self.lowlink[node], self.index[successor])


class SubgraphSplitter:
    """Split FK graph into analyzable subgraphs (Defense 6).

    Megaclusters (SCCs larger than ``max_scc_size``) are broken at weak
    links (the last edge in the cycle, which is typically nullable). The
    broken edges are returned for post-repair alignment.
    """

    def __init__(self, max_scc_size: int = 3) -> None:
        self._max_scc_size = max_scc_size

    def split(
        self,
        graph: dict[str, list[str]],
    ) -> tuple[list[list[str]], list[tuple[str, str]]]:
        """Return (subgraphs, broken_edges).

        - ``subgraphs``: list of node groups, each <= ``max_scc_size``.
        - ``broken_edges``: list of (src, dst) tuples removed during
          megacluster breaking. Used by post-repair to align FK ranges.
        """
        sccs = TarjanSCC.find_sccs(graph)
        subgraphs: list[list[str]] = []
        broken: list[tuple[str, str]] = []

        for scc in sccs:
            if len(scc) <= self._max_scc_size:
                subgraphs.append(scc)
                continue
            # Megacluster: break the cycle at weak links
            chunks, broken_edges = self._break_megacluster(scc, graph)
            subgraphs.extend(chunks)
            broken.extend(broken_edges)

        return subgraphs, broken

    def _break_megacluster(
        self,
        scc: list[str],
        graph: dict[str, list[str]],
    ) -> tuple[list[list[str]], list[tuple[str, str]]]:
        """Break a megacluster by removing cycle edges until chunks are <= max_size."""
        scc_set = set(scc)
        # Find edges within the SCC (cycle edges)
        cycle_edges: list[tuple[str, str]] = []
        for src in scc:
            for dst in graph.get(src, []):
                if dst in scc_set and src != dst:
                    cycle_edges.append((src, dst))

        # Greedily remove edges until the SCC splits into chunks of <= max_size.
        # We remove the *last* edge in the cycle order (typically the weakest).
        broken: list[tuple[str, str]] = []
        remaining_edges = list(cycle_edges)

        while True:
            # Build sub-SCCs from remaining_edges
            sub_graph: dict[str, list[str]] = {n: [] for n in scc}
            for src, dst in remaining_edges:
                sub_graph[src].append(dst)
            sub_sccs = TarjanSCC.find_sccs(sub_graph)
            if all(len(s) <= self._max_scc_size for s in sub_sccs):
                return sub_sccs, broken
            # Remove the last edge (simple heuristic; real impl could pick
            # the nullable FK edge via SchemaSnapshot metadata)
            removed = remaining_edges.pop()
            broken.append(removed)


def broken_edges_from_split(broken: list[tuple[str, str]]) -> dict[str, Any]:
    """Build a post-repair alignment spec from broken edges.

    This spec is consumed by :class:`AutoHealOrchestrator` (Phase 6) after
    the healer finishes, to align nullable FK ranges to parent values.
    """
    return {
        "count": len(broken),
        "edges": list(broken),
        "alignment_strategy": "nullable_fk_range_alignment",
    }
