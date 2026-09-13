/* Pure graph-view projection; implemented independently from DOM and layout. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SqlseedDependencyView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MODES = new Set(['paths', 'upstream', 'downstream', 'neighbors']);

  function indexGraph(data) {
    if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
      throw new TypeError('Expected node and edge arrays');
    }
    const parents = new Map(), children = new Map(), edgeIds = new Set();
    for (const node of data.nodes) {
      if (!node || typeof node.id !== 'string' || !node.id) throw new TypeError('Node id must be a nonempty string');
      if (parents.has(node.id)) throw new Error(`Duplicate node id: ${node.id}`);
      parents.set(node.id, new Set());
      children.set(node.id, new Set());
    }
    for (const edge of data.edges) {
      if (!edge || typeof edge.id !== 'string' || !edge.id) throw new TypeError('Edge id must be a nonempty string');
      if (edgeIds.has(edge.id)) throw new Error(`Duplicate edge id: ${edge.id}`);
      if (!parents.has(edge.source) || !parents.has(edge.target)) throw new Error(`Unknown endpoint on edge: ${edge.id}`);
      edgeIds.add(edge.id);
      children.get(edge.source).add(edge.target);
      parents.get(edge.target).add(edge.source);
    }
    return { parents, children };
  }

  // Multi-source traversal visits each node at most once; cycles and diamonds
  // never trigger path enumeration or recursive call-stack growth.
  function reachable(adjacency, seeds) {
    const visited = new Set(seeds), queue = [...visited];
    for (let i = 0; i < queue.length; i++) {
      for (const id of adjacency.get(queue[i])) {
        if (!visited.has(id)) { visited.add(id); queue.push(id); }
      }
    }
    return visited;
  }

  function project(data, visible) {
    return {
      nodes: data.nodes.filter(node => visible.has(node.id)),
      edges: data.edges.filter(edge => visible.has(edge.source) && visible.has(edge.target)),
    };
  }

  /**
   * Arrows run from referenced parent (source) to referencing child (target).
   *
   * paths: focus + recursive descendants, then ALL ancestors of that set.
   * This includes every source required by the visible descendants, without
   * expanding unrelated children of those additional sources. For example,
   * orders includes users → orders → items ← products, but excludes reviews
   * referenced from users and inventory referenced from products.
   * upstream/downstream: focus + all ancestors/descendants respectively.
   * neighbors: focus + one hop in either direction, deliberately incomplete.
   *
   * Every FK between visible tables is retained, including parallel constraints,
   * self references and composite column metadata. Input objects are unchanged.
   * upstreamIds/downstreamIds describe the full focal ancestry, excluding focus;
   * relatedSourceIds are extra ancestors added only in paths mode. roles applies
   * to visible nodes; a node both upstream and downstream has role cycle.
   * This projection controls browsing, never the generation selection itself.
   */
  function selectGraph(data, focusId, mode = 'paths') {
    if (!MODES.has(mode)) throw new Error(`Unknown mode: ${mode}`);
    const { parents, children } = indexGraph(data);
    const roles = Object.create(null);
    if (!parents.has(focusId)) {
      return { nodes: [], edges: [], focusId: null, mode, upstreamIds: [], downstreamIds: [], relatedSourceIds: [], roles };
    }
    const upstream = reachable(parents, [focusId]), downstream = reachable(children, [focusId]);
    let visible;
    if (mode === 'paths') visible = reachable(parents, downstream);
    else if (mode === 'upstream') visible = upstream;
    else if (mode === 'downstream') visible = downstream;
    else visible = new Set([focusId, ...parents.get(focusId), ...children.get(focusId)]);
    const relatedSources = new Set([...visible].filter(id => !upstream.has(id) && !downstream.has(id)));
    for (const node of data.nodes) {
      const id = node.id;
      if (!visible.has(id)) continue;
      roles[id] = id === focusId ? 'focus'
        : upstream.has(id) && downstream.has(id) ? 'cycle'
          : upstream.has(id) ? 'upstream'
            : downstream.has(id) ? 'downstream' : 'relatedSource';
    }
    const orderedIds = set => data.nodes.filter(node => node.id !== focusId && set.has(node.id)).map(node => node.id);
    return {
      ...project(data, visible), focusId, mode, roles,
      upstreamIds: orderedIds(upstream),
      downstreamIds: orderedIds(downstream),
      relatedSourceIds: orderedIds(relatedSources),
    };
  }

  /**
   * Dependency analysis uses the REAL set of generation targets, independent
   * of what the user happens to view. Return the targets and all their parents;
   * whether a parent is written, referenced from existing rows, or blocks the
   * run must be resolved by a separate constraint-aware execution planner.
   */
  function dependencyClosure(data, targetIds) {
    if (!Array.isArray(targetIds)) throw new TypeError('Expected target id array');
    const { parents } = indexGraph(data), targets = new Set(targetIds);
    for (const id of targets) if (!parents.has(id)) throw new Error(`Unknown target: ${id}`);
    const visible = reachable(parents, targets);
    return {
      ...project(data, visible),
      targetIds: data.nodes.filter(node => targets.has(node.id)).map(node => node.id),
      upstreamIds: data.nodes.filter(node => visible.has(node.id) && !targets.has(node.id)).map(node => node.id),
    };
  }
  return { selectGraph, dependencyClosure };
});
