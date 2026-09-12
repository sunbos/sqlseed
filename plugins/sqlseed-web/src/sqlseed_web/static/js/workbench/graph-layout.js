/* Standalone prototype layout: no DOM, dependencies, or database access. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SqlseedGraphLayout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const NODE_WIDTH = 210;
  const NODE_HEIGHT = 74;
  const PADDING = 36;
  const LANE = 7;

  /**
   * Parents point to children. Components are strongly connected components,
   * not disconnected subgraphs; a component is cyclic for a self-reference too.
   * Node and edge identities must be unique strings. Invalid references throw.
   * Returned paths contain orthogonal SVG M/L segments, ready for arrow markers.
   * Large graphs deliberately grow the canvas instead of overlapping nodes.
   */
  function layoutGraph(nodes, edges) {
    if (!Array.isArray(nodes) || !Array.isArray(edges)) throw new TypeError('Expected node and edge arrays');
    const original = new Map();
    const adjacency = new Map();
    const reverse = new Map();
    nodes.forEach((node, index) => {
      if (!node || typeof node.id !== 'string' || !node.id) throw new TypeError('Node id must be a nonempty string');
      if (original.has(node.id)) throw new Error(`Duplicate node id: ${node.id}`);
      original.set(node.id, index);
      adjacency.set(node.id, []);
      reverse.set(node.id, []);
    });
    const edgeIds = new Set();
    for (const edge of edges) {
      if (!edge || typeof edge.id !== 'string' || !edge.id) throw new TypeError('Edge id must be a nonempty string');
      if (edgeIds.has(edge.id)) throw new Error(`Duplicate edge id: ${edge.id}`);
      if (!original.has(edge.source) || !original.has(edge.target)) throw new Error(`Unknown endpoint on edge: ${edge.id}`);
      edgeIds.add(edge.id);
      adjacency.get(edge.source).push(edge.target);
      reverse.get(edge.target).push(edge.source);
    }

    // Iterative Kosaraju avoids call-stack limits on long dependency chains.
    const visited = new Set();
    const finishingOrder = [];
    for (const node of nodes) {
      if (visited.has(node.id)) continue;
      visited.add(node.id);
      const stack = [{ id: node.id, next: 0 }];
      while (stack.length) {
        const frame = stack[stack.length - 1];
        const neighbors = adjacency.get(frame.id);
        if (frame.next < neighbors.length) {
          const child = neighbors[frame.next++];
          if (!visited.has(child)) { visited.add(child); stack.push({ id: child, next: 0 }); }
        } else { finishingOrder.push(frame.id); stack.pop(); }
      }
    }
    const componentOf = new Map();
    const components = [];
    for (const start of finishingOrder.reverse()) {
      if (componentOf.has(start)) continue;
      const id = components.length;
      const nodeIds = [];
      const stack = [start];
      componentOf.set(start, id);
      while (stack.length) {
        const current = stack.pop();
        nodeIds.push(current);
        for (const parent of reverse.get(current)) {
          if (!componentOf.has(parent)) { componentOf.set(parent, id); stack.push(parent); }
        }
      }
      nodeIds.sort((a, b) => original.get(a) - original.get(b));
      components.push({ id, nodeIds, rank: 0, cyclic: nodeIds.length > 1 });
    }

    const children = components.map(() => new Set());
    const parents = components.map(() => new Set());
    for (const edge of edges) {
      const source = componentOf.get(edge.source), target = componentOf.get(edge.target);
      if (source === target) { components[source].cyclic = true; continue; }
      children[source].add(target);
      parents[target].add(source);
    }
    const indegree = parents.map(set => set.size);
    const queue = components.filter(c => !indegree[c.id]).map(c => c.id);
    for (let i = 0; i < queue.length; i++) {
      const component = components[queue[i]];
      for (const child of children[component.id]) {
        components[child].rank = Math.max(components[child].rank, component.rank + 1);
        if (--indegree[child] === 0) queue.push(child);
      }
    }

    const maxRank = components.reduce((max, c) => Math.max(max, c.rank), 0);
    const ranks = Array.from({ length: maxRank + 1 }, () => []);
    for (const component of components) ranks[component.rank].push(component);
    // Keep SCCs together and move children toward the average of their parents.
    const verticalCenter = new Map();
    const parentCenter = c => {
      const values = [...parents[c.id]].map(id => verticalCenter.get(id));
      return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : original.get(c.nodeIds[0]);
    };
    for (const rank of ranks) {
      rank.sort((a, b) => parentCenter(a) - parentCenter(b) || original.get(a.nodeIds[0]) - original.get(b.nodeIds[0]));
      let offset = 0;
      for (const component of rank) { verticalCenter.set(component.id, offset + component.nodeIds.length / 2); offset += component.nodeIds.length; }
    }

    const rightLanes = ranks.map(() => 0), leftLanes = ranks.map(() => 0);
    const outgoing = new Map(nodes.map(n => [n.id, 0])), incoming = new Map(nodes.map(n => [n.id, 0]));
    const selfCounts = new Map(nodes.map(n => [n.id, 0]));
    let longCount = 0;
    const routes = edges.map(edge => {
      const sourceRank = components[componentOf.get(edge.source)].rank;
      const targetRank = components[componentOf.get(edge.target)].rank;
      const kind = edge.source === edge.target ? 'self' : componentOf.get(edge.source) === componentOf.get(edge.target) ? 'cycle' : 'normal';
      const route = {
        edge, sourceRank, targetRank, kind, rightLane: rightLanes[sourceRank]++,
        leftLane: kind === 'normal' ? leftLanes[targetRank]++ : 0,
        sourcePort: outgoing.get(edge.source), targetPort: incoming.get(edge.target),
        topLane: targetRank - sourceRank > 1 ? longCount++ : -1,
        selfLane: selfCounts.get(edge.source),
      };
      outgoing.set(edge.source, route.sourcePort + 1);
      incoming.set(edge.target, route.targetPort + 1);
      if (kind === 'self') selfCounts.set(edge.source, route.selfLane + 1);
      return route;
    });
    const maxSelf = Math.max(0, ...selfCounts.values());
    const rowGap = Math.max(62, 28 + maxSelf * 8);
    const startY = PADDING + longCount * 10 + 30 + maxSelf * 8;
    const rankX = [PADDING];
    for (let i = 1; i <= maxRank; i++) rankX[i] = rankX[i - 1] + NODE_WIDTH + 56 + (rightLanes[i - 1] + leftLanes[i]) * LANE;
    const positioned = new Map();
    for (let rank = 0; rank < ranks.length; rank++) {
      let row = 0;
      for (const component of ranks[rank]) for (const id of component.nodeIds) {
        positioned.set(id, { ...nodes[original.get(id)], x: rankX[rank], y: startY + row++ * (NODE_HEIGHT + rowGap), width: NODE_WIDTH, height: NODE_HEIGHT, component: component.id, rank });
      }
    }

    const number = value => Math.round(value * 100) / 100;
    const pathFor = points => points.map(([x, y], i) => `${i ? 'L' : 'M'} ${number(x)} ${number(y)}`).join(' ');
    const routed = routes.map(route => {
      const { edge, kind } = route;
      const source = positioned.get(edge.source), target = positioned.get(edge.target);
      const sourceRight = source.x + NODE_WIDTH;
      const sourceY = number(source.y + NODE_HEIGHT * (route.sourcePort + 1) / (outgoing.get(edge.source) + 1));
      const targetY = number(target.y + NODE_HEIGHT * (route.targetPort + 1) / (incoming.get(edge.target) + 1));
      const rightX = sourceRight + 22 + route.rightLane * LANE;
      const leftX = target.x - 22 - route.leftLane * LANE;
      let points, labelX, labelY;
      if (kind === 'self') {
        const top = source.y - 18 - route.selfLane * 8;
        const endX = number(source.x + NODE_WIDTH * (0.3 + 0.4 * (route.selfLane + 1) / (selfCounts.get(edge.source) + 1)));
        points = [[sourceRight, sourceY], [rightX, sourceY], [rightX, top], [endX, top], [endX, source.y]];
        labelX = (rightX + endX) / 2; labelY = top - 5;
      } else if (kind === 'cycle') {
        points = [[sourceRight, sourceY], [rightX, sourceY], [rightX, targetY], [target.x + NODE_WIDTH, targetY]];
        labelX = rightX + 5; labelY = (sourceY + targetY) / 2;
      } else if (route.topLane >= 0) {
        const top = PADDING + route.topLane * 10;
        points = [[sourceRight, sourceY], [rightX, sourceY], [rightX, top], [leftX, top], [leftX, targetY], [target.x, targetY]];
        labelX = (rightX + leftX) / 2; labelY = top - 5;
      } else {
        points = [[sourceRight, sourceY], [rightX, sourceY], [rightX, targetY], [target.x, targetY]];
        labelX = (rightX + target.x) / 2; labelY = targetY - 7;
      }
      return { ...edge, path: pathFor(points), kind, labelX: number(labelX), labelY: number(labelY) };
    });
    const resultNodes = nodes.map(node => positioned.get(node.id));
    const width = nodes.length ? rankX[maxRank] + NODE_WIDTH + 56 + rightLanes[maxRank] * LANE + PADDING : PADDING * 2;
    const height = resultNodes.reduce((max, node) => Math.max(max, node.y + NODE_HEIGHT + PADDING), PADDING * 2);
    return { nodes: resultNodes, edges: routed, width, height, components };
  }

  /**
   * Place readable, unabridged edge captions after routing the graph. Labels are
   * rendered in a separate SVG layer: rect at x/y, then lines as tspans beginning
   * at textX/textY with lineHeight spacing. Geometry assumes 11px monospace text;
   * the conservative character widths also reserve space for CJK fallback fonts.
   * Every caption avoids nodes, other captions, and all original FK paths. A
   * short leader can join a nearby caption to its route. On crowded graphs an
   * outside caption may have no leader; its edgeId still identifies the relation.
   * Call this on the base layout again when labels change, never on its result.
   */
  function placeEdgeLabels(layout, captions) {
    if (!layout || !Array.isArray(layout.nodes) || !Array.isArray(layout.edges) || !Array.isArray(captions)) {
      throw new TypeError('Expected a graph layout and caption array');
    }
    const edgeById = new Map(layout.edges.map(edge => [edge.id, edge]));
    const seen = new Set();
    const lineHeight = 16, pad = 8, maxTextWidth = 196, gap = 7;
    const characterWidth = char => char.codePointAt(0) > 255 ? 12 : 7;
    const wrap = text => {
      const lines = [];
      let line = '', width = 0;
      for (const char of text) {
        const nextWidth = characterWidth(char);
        if (line && width + nextWidth > maxTextWidth) { lines.push(line); line = ''; width = 0; }
        line += char; width += nextWidth;
      }
      if (line || !lines.length) lines.push(line);
      return lines;
    };
    const segments = path => {
      const points = [...path.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)].map(m => [+m[1], +m[2]]);
      return points.slice(1).map((b, i) => [points[i], b]).filter(([a, b]) => a[0] !== b[0] || a[1] !== b[1]);
    };
    const edgeSegments = new Map(layout.edges.map(edge => [edge.id, segments(edge.path)]));
    const occupiedSegments = [...edgeSegments.values()].flat();
    const intersects = (a, b, clearance = gap) => a.x < b.x + b.width + clearance && a.x + a.width + clearance > b.x &&
      a.y < b.y + b.height + clearance && a.y + a.height + clearance > b.y;
    const crosses = ([a, b], box, clearance = 3) => {
      const left = box.x - clearance, right = box.x + box.width + clearance;
      const top = box.y - clearance, bottom = box.y + box.height + clearance;
      return a[0] === b[0]
        ? a[0] > left && a[0] < right && Math.max(a[1], b[1]) > top && Math.min(a[1], b[1]) < bottom
        : a[1] > top && a[1] < bottom && Math.max(a[0], b[0]) > left && Math.min(a[0], b[0]) < right;
    };
    const placed = [];
    let width = layout.width, height = layout.height;
    const pathFor = points => points.map(([x, y], i) => `${i ? 'L' : 'M'} ${Math.round(x * 100) / 100} ${Math.round(y * 100) / 100}`).join(' ');
    for (const caption of captions) {
      if (!caption || typeof caption.text !== 'string' || !caption.text || !edgeById.has(caption.edgeId)) throw new TypeError('Each caption needs a known edgeId and nonempty text');
      if (seen.has(caption.edgeId)) throw new Error(`Duplicate caption: ${caption.edgeId}`);
      seen.add(caption.edgeId);
      const edge = edgeById.get(caption.edgeId), lines = wrap(caption.text);
      const boxWidth = Math.max(...lines.map(line => [...line].reduce((sum, char) => sum + characterWidth(char), 0))) + pad * 2;
      const boxHeight = lines.length * lineHeight + 12;
      const candidates = [];
      const addCandidate = (x, y, anchor, endpoint) => {
        const box = { x, y, width: boxWidth, height: boxHeight };
        if (x < 8 || y < 8 || layout.nodes.some(node => intersects(box, node)) || placed.some(label => intersects(box, label))) return;
        if (occupiedSegments.some(segment => crosses(segment, box))) return;
        const leader = [anchor, endpoint];
        if (layout.nodes.some(node => crosses(leader, node, 2)) || placed.some(label => crosses(leader, label, 2))) return;
        const distance = Math.abs(endpoint[0] - anchor[0]) + Math.abs(endpoint[1] - anchor[1]);
        const expansion = Math.max(0, x + boxWidth + pad - width) + Math.max(0, y + boxHeight + pad - height);
        const score = distance + expansion * 2 + (Math.abs(anchor[0] - edge.labelX) + Math.abs(anchor[1] - edge.labelY)) * .2;
        candidates.push({ ...box, anchorX: anchor[0], anchorY: anchor[1], leaderPath: pathFor(leader), score });
      };
      for (const [a, b] of edgeSegments.get(edge.id)) {
        const horizontal = a[1] === b[1];
        for (const fraction of [.5, .25, .75]) {
          const anchor = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
          // Row/column boundaries provide exact clearances where a fixed step
          // could jump over a narrow but usable space between neighboring tables.
          const boundaries = [...layout.nodes, ...placed].flatMap(box => horizontal
            ? [box.y - boxHeight - gap, box.y + box.height + gap]
            : [box.x - boxWidth - gap, box.x + box.width + gap]);
          boundaries.sort((a, b) => Math.abs(a - anchor[horizontal ? 1 : 0]) - Math.abs(b - anchor[horizontal ? 1 : 0]));
          for (const position of [...new Set(boundaries)].slice(0, 12)) {
            if (horizontal) {
              if (position + boxHeight < anchor[1]) addCandidate(anchor[0] - boxWidth / 2, position, anchor, [anchor[0], position + boxHeight]);
              else if (position > anchor[1]) addCandidate(anchor[0] - boxWidth / 2, position, anchor, [anchor[0], position]);
            } else {
              if (position + boxWidth < anchor[0]) addCandidate(position, anchor[1] - boxHeight / 2, anchor, [position + boxWidth, anchor[1]]);
              else if (position > anchor[0]) addCandidate(position, anchor[1] - boxHeight / 2, anchor, [position, anchor[1]]);
            }
          }
          for (const offset of [8, 24, 44, 72, 104, 152, 224, 320]) {
            if (horizontal) {
              addCandidate(anchor[0] - boxWidth / 2, anchor[1] - offset - boxHeight, anchor, [anchor[0], anchor[1] - offset]);
              addCandidate(anchor[0] - boxWidth / 2, anchor[1] + offset, anchor, [anchor[0], anchor[1] + offset]);
            } else {
              addCandidate(anchor[0] - offset - boxWidth, anchor[1] - boxHeight / 2, anchor, [anchor[0] - offset, anchor[1]]);
              addCandidate(anchor[0] + offset, anchor[1] - boxHeight / 2, anchor, [anchor[0] + offset, anchor[1]]);
            }
          }
        }
      }
      candidates.sort((a, b) => a.score - b.score || a.y - b.y || a.x - b.x);
      let chosen = candidates[0];
      if (!chosen) {
        // Guaranteed unclipped fallback beyond all original routes. Nearby
        // placements above take precedence, so ordinary diagrams stay compact.
        chosen = { x: layout.width + 24, y: Math.max(8, edge.labelY - boxHeight / 2), width: boxWidth, height: boxHeight,
          anchorX: edge.labelX, anchorY: edge.labelY, leaderPath: '' };
        while (placed.some(label => intersects(chosen, label))) {
          chosen.y = Math.max(...placed.filter(label => intersects(chosen, label)).map(label => label.y + label.height + gap));
        }
        // The outside column contains no original FK path. It may contain a
        // leader from a previous caption; move below it instead of erasing it.
        while (occupiedSegments.some(segment => crosses(segment, chosen))) {
          chosen.y = Math.max(...occupiedSegments.filter(segment => crosses(segment, chosen)).flatMap(([a, b]) => [a[1], b[1]])) + gap;
          while (placed.some(label => intersects(chosen, label))) {
            chosen.y = Math.max(...placed.filter(label => intersects(chosen, label)).map(label => label.y + label.height + gap));
          }
        }
        // A gutter caption is still connected to its own relation. Try clear
        // horizontal rows via the source route's free vertical corridor; thin
        // leaders may cross FK strokes but never table or caption rectangles.
        const corridorX = chosen.x - gap, targetY = chosen.y + chosen.height / 2;
        const rows = [...new Set([8, height + gap, ...[...layout.nodes, ...placed].flatMap(box => [box.y - gap, box.y + box.height + gap])])].filter(y => y >= 8);
        const leaderCandidates = [];
        for (const [a, b] of edgeSegments.get(edge.id)) for (const fraction of [.5, .25, .75]) {
          const anchor = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
          for (const row of rows) {
            const points = [anchor, [anchor[0], row], [corridorX, row], [corridorX, targetY], [chosen.x, targetY]];
            const parts = points.slice(1).map((b, i) => [points[i], b]);
            if (parts.some(segment => [...layout.nodes, ...placed].some(box => crosses(segment, box, 2)))) continue;
            const distance = parts.reduce((sum, [a, b]) => sum + Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]), 0);
            leaderCandidates.push({ points, anchor, distance });
          }
        }
        leaderCandidates.sort((a, b) => a.distance - b.distance);
        if (leaderCandidates.length) {
          const leader = leaderCandidates[0];
          chosen.leaderPath = pathFor(leader.points);
          chosen.anchorX = leader.anchor[0]; chosen.anchorY = leader.anchor[1];
          width = Math.max(width, ...leader.points.map(point => point[0] + PADDING));
          height = Math.max(height, ...leader.points.map(point => point[1] + PADDING));
        }
      }
      const geometry = { ...chosen };
      delete geometry.score;
      const label = { edgeId: caption.edgeId, text: caption.text, lines, lineHeight, ...geometry,
        textX: chosen.x + pad, textY: chosen.y + 17 };
      placed.push(label);
      if (label.leaderPath) occupiedSegments.push(...segments(label.leaderPath));
      width = Math.max(width, label.x + label.width + PADDING);
      height = Math.max(height, label.y + label.height + PADDING);
    }
    return { ...layout, labels: placed, width, height };
  }

  return { layoutGraph, placeEdgeLabels };
});
