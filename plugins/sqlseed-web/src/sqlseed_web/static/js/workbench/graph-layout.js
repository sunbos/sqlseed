/* 正交结构图布局，不访问 DOM、外部依赖或数据库。 */
(function (root) {
  'use strict';

  const NODE_WIDTH = 210;
  const NODE_HEIGHT = 74;
  const PADDING = 36;
  const LANE = 7;

  function indexLayoutGraph(nodes, edges) {
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
    return { original, adjacency, reverse };
  }

  function finishingNodeOrder(nodes, adjacency) {
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
    return finishingOrder;
  }

  function strongComponents(finishingOrder, reverse, original) {
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
    return { componentOf, components };
  }

  function rankComponents(components, componentOf, edges) {
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

    // Use legal rank slack only when it shortens the total inter-component
    // span. A side source can sit beside another parent instead of sending a
    // long edge across it. This is presentation, never execution ordering.
    for (const id of [...queue].reverse()) {
      if (children[id].size <= parents[id].size) continue;
      const latest = Math.min(...[...children[id]].map(child => components[child].rank - 1));
      components[id].rank = Math.max(components[id].rank, latest);
    }
    return children;
  }

  function addVirtualWaypoints(components, children, units, ranks, layerLinks) {
    // Virtual waypoints let the layer sweep see long references too. They
    // reserve a narrow routing corridor, but never become schema nodes.
    for (const component of components) for (const child of children[component.id]) {
      let previous = `node-${component.id}`;
      for (let rank = component.rank + 1; rank <= components[child].rank; rank++) {
        const id = rank === components[child].rank ? `node-${child}` : `route-${component.id}-${child}-${rank}`;
        if (!units.has(id)) {
          const unit = { id, component: null, size: .25 };
          units.set(id, unit); ranks[rank].push(unit);
        }
        layerLinks[rank - 1].push([previous, id]); previous = id;
      }
    }
  }

  function createLayers(components, children, original) {
    const maxRank = components.reduce((max, c) => Math.max(max, c.rank), 0);
    const ranks = Array.from({ length: maxRank + 1 }, () => []);
    const units = new Map();
    for (const component of components) {
      const unit = { id: `node-${component.id}`, component, size: component.nodeIds.length };
      units.set(unit.id, unit);
      ranks[component.rank].push(unit);
    }
    for (const rank of ranks) rank.sort((a, b) => original.get(a.component.nodeIds[0]) - original.get(b.component.nodeIds[0]));
    const layerLinks = Array.from({ length: maxRank }, () => []);
    addVirtualWaypoints(components, children, units, ranks, layerLinks);
    const predecessors = new Map([...units.keys()].map(id => [id, []]));
    const successors = new Map([...units.keys()].map(id => [id, []]));
    for (const links of layerLinks) for (const [a, b] of links) {
      successors.get(a).push(b); predecessors.get(b).push(a);
    }
    return { maxRank, ranks, layerLinks, predecessors, successors };
  }

  function layerCenters(ranks) {
    const values = new Map();
    for (const rank of ranks) {
      let row = 0;
      for (const unit of rank) { values.set(unit.id, row + unit.size / 2); row += unit.size; }
    }
    return values;
  }

  function layerCrossings(pairs, targetCount) {
    // Fenwick inversion count; links sharing a source or target do not
    // cross. This remains bounded on large, dense dependency graphs.
    const tree = new Array(targetCount + 1).fill(0);
    let count = 0, crossings = 0;
    for (let first = 0; first < pairs.length;) {
      let last = first;
      while (last < pairs.length && pairs[last][0] === pairs[first][0]) last++;
      for (let i = first; i < last; i++) {
        let smaller = 0;
        for (let index = pairs[i][1] + 1; index > 0; index -= index & -index) smaller += tree[index];
        crossings += count - smaller;
      }
      for (let i = first; i < last; i++) {
        for (let index = pairs[i][1] + 1; index < tree.length; index += index & -index) tree[index]++;
        count++;
      }
      first = last;
    }
    return crossings;
  }

  function layerQuality(ranks, layerLinks) {
    const positions = new Map();
    ranks.forEach(rank => rank.forEach((unit, index) => positions.set(unit.id, index)));
    const middle = layerCenters(ranks);
    let crossings = 0, distance = 0;
    for (let rank = 0; rank < layerLinks.length; rank++) {
      const pairs = layerLinks[rank].map(([a, b]) => {
        distance += Math.abs(middle.get(a) - middle.get(b));
        return [positions.get(a), positions.get(b)];
      }).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      crossings += layerCrossings(pairs, ranks[rank + 1].length);
    }
    return { crossings, distance };
  }

  function barycenter(unit, neighbors, middle) {
    const adjacent = neighbors.get(unit.id);
    return adjacent.length ? adjacent.reduce((sum, id) => sum + middle.get(id), 0) / adjacent.length : middle.get(unit.id);
  }

  function sweepLayers(ranks, neighbors, maxRank, forward) {
    const middle = layerCenters(ranks);
    for (let index = forward ? 1 : maxRank - 1; forward ? index <= maxRank : index >= 0; index += forward ? 1 : -1) {
      ranks[index].sort((a, b) => barycenter(a, neighbors, middle) - barycenter(b, neighbors, middle));
      let row = 0;
      for (const unit of ranks[index]) { middle.set(unit.id, row + unit.size / 2); row += unit.size; }
    }
  }

  function orderLayers(ranks, layerLinks, predecessors, successors, maxRank, denseRouting) {
    let bestOrder = ranks.map(rank => [...rank]), bestQuality = layerQuality(ranks, layerLinks);
    // Bounded two-way barycenter sweeps, with stable ties and best-order
    // retention. SCC members stay together and repeated input stays stable.
    for (let pass = 0; pass < (denseRouting ? 2 : 4); pass++) for (const forward of [true, false]) {
      sweepLayers(ranks, forward ? predecessors : successors, maxRank, forward);
      const quality = layerQuality(ranks, layerLinks);
      if (quality.crossings < bestQuality.crossings || quality.crossings === bestQuality.crossings && quality.distance < bestQuality.distance) {
        bestQuality = quality; bestOrder = ranks.map(rank => [...rank]);
      }
    }
    ranks.splice(0, ranks.length, ...bestOrder);
  }

  function routeKind(edge, componentOf) {
    if (edge.source === edge.target) return 'self';
    return componentOf.get(edge.source) === componentOf.get(edge.target) ? 'cycle' : 'normal';
  }

  function allocateRoutePorts(nodes, edges, ranks, components, componentOf) {
    const rightLanes = ranks.map(() => 0), leftLanes = ranks.map(() => 0);
    const outgoing = new Map(nodes.map(n => [n.id, 0])), incoming = new Map(nodes.map(n => [n.id, 0]));
    const selfCounts = new Map(nodes.map(n => [n.id, 0]));
    let longCount = 0;
    const routes = edges.map(edge => {
      const sourceRank = components[componentOf.get(edge.source)].rank;
      const targetRank = components[componentOf.get(edge.target)].rank;
      const kind = routeKind(edge, componentOf);
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
    return { routes, rightLanes, leftLanes, outgoing, incoming, selfCounts, longCount };
  }

  function positionNodes(nodes, ranks, maxRank, original, allocation) {
    const { routes, rightLanes, leftLanes, selfCounts, longCount } = allocation;
    const maxSelf = Math.max(0, ...selfCounts.values());
    // Cycle arrows enter the right face too. Share its allocation with outgoing
    // ports rather than using the independent left-face incoming fractions.
    const cycleIncoming = new Map(nodes.map(node => [node.id, 0]));
    for (const route of routes) if (route.kind === 'cycle') {
      route.cycleTargetPort = cycleIncoming.get(route.edge.target);
      cycleIncoming.set(route.edge.target, route.cycleTargetPort + 1);
    }
    const rowGap = Math.max(62, 28 + maxSelf * 8);
    const startY = PADDING + longCount * 10 + 30 + maxSelf * 8;
    const rankX = [PADDING];
    for (let i = 1; i <= maxRank; i++) rankX[i] = rankX[i - 1] + NODE_WIDTH + 56 + (rightLanes[i - 1] + leftLanes[i]) * LANE;
    const positioned = new Map();
    for (let rank = 0; rank < ranks.length; rank++) {
      let row = 0;
      for (const unit of ranks[rank]) {
        if (!unit.component) { row += unit.size; continue; }
        const component = unit.component;
        for (const id of component.nodeIds) {
          positioned.set(id, { ...nodes[original.get(id)], x: rankX[rank], y: startY + row++ * (NODE_HEIGHT + rowGap), width: NODE_WIDTH, height: NODE_HEIGHT, component: component.id, rank });
        }
      }
    }
    return { positioned, rankX, cycleIncoming };
  }

  const number = value => Math.round(value * 100) / 100;
  const pathFor = points => points.map(([x, y], i) => `${i ? 'L' : 'M'} ${number(x)} ${number(y)}`).join(' ');

  function legacyRouteGeometry(routes, positioned, outgoing, incoming, cycleIncoming, selfCounts) {
    const legacyRoutes = routes.map(route => {
      const { edge, kind } = route;
      const source = positioned.get(edge.source), target = positioned.get(edge.target);
      const sourceRight = source.x + NODE_WIDTH;
      const sourceY = number(source.y + NODE_HEIGHT * (route.sourcePort + 1) / (outgoing.get(edge.source) + cycleIncoming.get(edge.source) + 1));
      const targetY = kind === 'cycle'
        ? number(target.y + NODE_HEIGHT * (outgoing.get(edge.target) + route.cycleTargetPort + 1) / (outgoing.get(edge.target) + cycleIncoming.get(edge.target) + 1))
        : number(target.y + NODE_HEIGHT * (route.targetPort + 1) / (incoming.get(edge.target) + 1));
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
      return { ...edge, path: pathFor(points), kind, labelX: number(labelX), labelY: number(labelY), points };
    });
    return legacyRoutes;
  }

  const portKey = (node, side, point) => `${node.id}:${side}:${number(point[0])}:${number(point[1])}`;

  function reserveLegacyPorts(legacyRoutes, positioned, usedPorts, reservedPorts) {
    // 环和自引用继续使用独立通道。预留尚未处理边的原端口，确保优化失败时
    // 可以安全回退；已优化的边不能抢占其他边的兜底端口。
    for (const edge of legacyRoutes) {
      const source = positioned.get(edge.source), target = positioned.get(edge.target);
      const occupied = edge.kind === 'normal' ? reservedPorts : usedPorts;
      occupied.add(portKey(source, 'right', edge.points[0]));
      occupied.add(portKey(target, targetPortSide(edge.kind), edge.points.at(-1)));
    }
  }

  function targetPortSide(kind) {
    if (kind === 'self') return 'top';
    return kind === 'normal' ? 'left' : 'right';
  }

  function simplify(points) {
    const result = [];
    for (const point of points) {
      if (result.length && point[0] === result.at(-1)[0] && point[1] === result.at(-1)[1]) continue;
      while (result.length > 1 && ((result.at(-2)[0] === result.at(-1)[0] && point[0] === result.at(-1)[0]) ||
        (result.at(-2)[1] === result.at(-1)[1] && point[1] === result.at(-1)[1]))) result.pop();
      result.push(point);
    }
    return result;
  }

  function outward(side, from, to) {
    if (side === 'right') return to[1] === from[1] && to[0] > from[0];
    if (side === 'left') return to[1] === from[1] && to[0] < from[0];
    if (side === 'bottom') return to[0] === from[0] && to[1] > from[1];
    return to[0] === from[0] && to[1] < from[1];
  }

  function intersectsNode(a, b, node, padding) {
    const left = node.x - padding, right = node.x + node.width + padding;
    const top = node.y - padding, bottom = node.y + node.height + padding;
    return a[0] === b[0] ? a[0] > left && a[0] < right && Math.max(a[1], b[1]) > top && Math.min(a[1], b[1]) < bottom
      : a[1] > top && a[1] < bottom && Math.max(a[0], b[0]) > left && Math.min(a[0], b[0]) < right;
  }

  function parallelOverlap(a, b, c, d, vertical) {
    const axis = vertical ? 1 : 0, fixed = 1 - axis;
    if (a[fixed] !== c[fixed]) return 0;
    return Math.max(0, Math.min(Math.max(a[axis], b[axis]), Math.max(c[axis], d[axis])) -
      Math.max(Math.min(a[axis], b[axis]), Math.min(c[axis], d[axis])));
  }

  function crossingKey(a, b, other, vertical) {
    const v1 = vertical ? a : other.a, v2 = vertical ? b : other.b;
    const h1 = vertical ? other.a : a, h2 = vertical ? other.b : b;
    if (v1[0] >= Math.min(h1[0], h2[0]) && v1[0] <= Math.max(h1[0], h2[0]) &&
        h1[1] >= Math.min(v1[1], v2[1]) && h1[1] <= Math.max(v1[1], v2[1])) {
      return `${other.id}:${number(v1[0])}:${number(h1[1])}`;
    }
    return null;
  }

  function routeConflicts(points, nearbySegments) {
    const crossings = new Set();
    let overlap = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], vertical = a[0] === b[0];
      for (const other of nearbySegments) {
        if (vertical === (other.a[0] === other.b[0])) {
          overlap += parallelOverlap(a, b, other.a, other.b, vertical);
        } else {
          const key = crossingKey(a, b, other, vertical);
          if (key !== null) crossings.add(key);
        }
      }
    }
    return { crossings: crossings.size, overlap };
  }

  function considerStraightRoutes(sourcePorts, targetPorts, consider) {
    for (const from of sourcePorts) for (const to of targetPorts) consider([from.point, to.point], from, to);
  }

  function considerTwoBendRoutes(sourcePorts, targetPorts, xs, ys, consider) {
    for (const from of sourcePorts) for (const to of targetPorts) {
      const a = from.point, b = to.point;
      consider([a, [b[0], a[1]], b], from, to);
      consider([a, [a[0], b[1]], b], from, to);
      for (const x of xs) consider([a, [x, a[1]], [x, b[1]], b], from, to);
      for (const y of ys) consider([a, [a[0], y], [b[0], y], b], from, to);
    }
  }

  function considerThreeBendRoutes(sourcePorts, targetPorts, xs, ys, consider) {
    for (const from of sourcePorts) for (const to of targetPorts) {
      const a = from.point, b = to.point;
      for (const x of xs.slice(0, 4)) for (const y of ys.slice(0, 4)) {
        consider([a, [x, a[1]], [x, y], [b[0], y], b], from, to);
        consider([a, [a[0], y], [x, y], [x, b[1]], b], from, to);
      }
    }
  }

  function considerAllocatedRoute(route, source, target, sourcePorts, targetPorts, consider) {
    const from = sourcePorts.find(port => port.side === 'right'), to = targetPorts.find(port => port.side === 'left');
    if (!from || !to) return;
    const rightX = source.x + source.width + 22 + route.rightLane * LANE;
    const leftX = target.x - 22 - route.leftLane * LANE;
    const top = PADDING + route.topLane * 10;
    consider(route.topLane >= 0
      ? [from.point, [rightX, from.point[1]], [rightX, top], [leftX, top], [leftX, to.point[1]], to.point]
      : [from.point, [rightX, from.point[1]], [rightX, to.point[1]], to.point], from, to);
  }

  function optimizeRoutes(nodes, edges, allocation, legacyRoutes, positioned, denseRouting) {
    const { routes, outgoing, incoming } = allocation;
    const legacyById = new Map(legacyRoutes.map(edge => [edge.id, edge]));
    const resultNodes = nodes.map(node => positioned.get(node.id));
    const usedPorts = new Set();
    const reservedPorts = new Set();
    reserveLegacyPorts(legacyRoutes, positioned, usedPorts, reservedPorts);
    const degree = Math.max(1, ...nodes.map(node => outgoing.get(node.id) + incoming.get(node.id)));
    const clearance = 12;
    // A dense overview needs a bounded amount of routing work, not thousands
    // of candidates per edge. Its preallocated channels remain a safe fallback.
    // This budget depends only on graph size, so geometry stays deterministic.
    const candidateBudget = Math.max(32, Math.min(6000, Math.floor((denseRouting ? 64000 : 160000) / Math.max(1, edges.length))));
    const sides = ['right', 'bottom', 'top', 'left'];
    const ports = (node, other) => sides.flatMap(side => {
      const horizontal = side === 'left' || side === 'right';
      const start = horizontal ? node.y : node.x, length = horizontal ? node.height : node.width;
      const center = start + length / 2, otherCenter = horizontal ? other.y + other.height / 2 : other.x + other.width / 2;
      const step = Math.min(12, (length - 28) / (degree + 1));
      const coordinates = [center, otherCenter];
      for (let offset = step; offset <= length / 2 - 14; offset += step) coordinates.push(center + offset, center - offset);
      return [...new Set(coordinates.map(number))].filter(value => value >= start + 14 && value <= start + length - 14)
        .map(value => ({side, point: horizontal ? [side === 'right' ? node.x + node.width : node.x, value]
          : [value, side === 'bottom' ? node.y + node.height : node.y]}))
        .filter(port => !usedPorts.has(portKey(node, side, port.point)) && !reservedPorts.has(portKey(node, side, port.point))).slice(0, denseRouting ? 1 : 3);
    });
    const placedSegments = [];
    const reserveRoute = edge => {
      for (let i = 1; i < edge.points.length; i++) placedSegments.push({ id: edge.id, a: edge.points[i - 1], b: edge.points[i] });
    };
    legacyRoutes.filter(edge => edge.kind !== 'normal').forEach(reserveRoute);
    const shortestRoute = route => {
      const source = positioned.get(route.edge.source), target = positioned.get(route.edge.target);
      const sourcePorts = ports(source, target), targetPorts = ports(target, source);
      const obstacles = resultNodes.filter(node => node.x + node.width >= source.x && node.x <= target.x + target.width);
      const centerX = (source.x + source.width + target.x) / 2, centerY = (source.y + target.y + source.height) / 2;
      const channels = (values, center) => [...new Set(values.map(number))].filter(value => value >= 8)
        .sort((a, b) => Math.abs(a - center) - Math.abs(b - center) || a - b).slice(0, denseRouting ? 4 : 8);
      const xs = channels([centerX, ...obstacles.flatMap(node => [node.x - clearance, node.x + node.width + clearance])], centerX);
      const ys = channels([centerY, ...obstacles.flatMap(node => [node.y - clearance, node.y + node.height + clearance])], centerY);
      const nearbySegments = placedSegments.filter(({a, b}) => Math.max(a[0], b[0]) >= source.x - clearance &&
        Math.min(a[0], b[0]) <= target.x + target.width + clearance);
      let best = null, attempted = 0;
      const consider = (points, from, to) => {
        if (++attempted > candidateBudget) return;
        points = simplify(points);
        const bends = points.length - 2;
        if (points.length < 2 || points.some(point => point[0] < 8 || point[1] < 8)) return;
        if (!outward(from.side, points[0], points[1]) || !outward(to.side, points.at(-1), points.at(-2))) return;
        let length = 0;
        for (let i = 1; i < points.length; i++) length += Math.abs(points[i][0] - points[i - 1][0]) + Math.abs(points[i][1] - points[i - 1][1]);
        const baseScore = length + bends * NODE_HEIGHT;
        if (best && baseScore > best.score) return;
        for (let i = 1; i < points.length; i++) {
          if (points[i][0] !== points[i - 1][0] && points[i][1] !== points[i - 1][1]) return;
          if (resultNodes.some(node => intersectsNode(points[i - 1], points[i], node,
            (i === 1 && node === source) || (i === points.length - 1 && node === target) ? 0 : clearance))) return;
        }
        const {crossings, overlap} = routeConflicts(points, nearbySegments);
        // Crossing and shared-line penalties balance legibility against the
        // distance and bends of a detour; node clearance remains mandatory.
        const score = baseScore + crossings * NODE_WIDTH * 2 + overlap * 4;
        if (!best || score < best.score || score === best.score &&
            (bends < best.bends || bends === best.bends && length < best.length)) {
          best = {points, bends, length, from, to, crossings, overlap, score};
        }
      };
      // 有界候选：每个面最多三个可用端口，每轴最多八个邻近避障通道。
      // 综合交叉、共线、折点与曼哈顿长度，不承诺全局最优。
      // 无冲突直线已达到端口之间的最少折点及最短距离。
      considerStraightRoutes(sourcePorts, targetPorts, consider);
      if (!best || best.crossings || best.overlap) considerTwoBendRoutes(sourcePorts, targetPorts, xs, ys, consider);
      if (attempted < candidateBudget && (!best || !denseRouting && (best.bends > 2 || best.crossings || best.overlap))) {
        considerThreeBendRoutes(sourcePorts, targetPorts, xs, ys, consider);
      }
      // 拥挤图仍可沿预分配的层间/顶部通道绕行，优先使用未占用端口。
      if (!best || best.bends > 2 || best.crossings || best.overlap) {
        considerAllocatedRoute(route, source, target, sourcePorts, targetPorts, consider);
      }
      return best;
    };
    const optimized = new Map();
    // 相邻层先占用可直连端口，再处理跨层引用；保留输入的输出边序。
    const normalRoutes = routes.filter(route => route.kind === 'normal').sort((a, b) =>
      a.targetRank - a.sourceRank - (b.targetRank - b.sourceRank));
    for (const route of normalRoutes) {
      const original = legacyById.get(route.edge.id);
      const sourcePort = portKey(positioned.get(original.source), 'right', original.points[0]);
      const targetPort = portKey(positioned.get(original.target), 'left', original.points.at(-1));
      reservedPorts.delete(sourcePort);
      reservedPorts.delete(targetPort);
      const chosen = shortestRoute(route);
      if (!chosen) {
        // 有限候选不覆盖全部可行路径。保留经过预留的原端口和独立通道，
        // 优先让复杂结构可读，不因短路径优化失败而使整图无法显示。
        usedPorts.add(sourcePort);
        usedPorts.add(targetPort);
        optimized.set(original.id, original);
        reserveRoute(original);
        continue;
      }
      const {points, from, to} = chosen;
      usedPorts.add(portKey(positioned.get(route.edge.source), from.side, from.point));
      usedPorts.add(portKey(positioned.get(route.edge.target), to.side, to.point));
      const longest = points.slice(1).map((point, i) => ({a: points[i], b: point,
        length: Math.abs(point[0] - points[i][0]) + Math.abs(point[1] - points[i][1])}))
        .sort((a, b) => b.length - a.length)[0];
      optimized.set(route.edge.id, {...original, points, path: pathFor(points),
        labelX: number((longest.a[0] + longest.b[0]) / 2 + (longest.a[0] === longest.b[0] ? 5 : 0)),
        labelY: number((longest.a[1] + longest.b[1]) / 2 - (longest.a[1] === longest.b[1] ? 7 : 0))});
      reserveRoute({ id: route.edge.id, points });
    }
    return { optimized, resultNodes };
  }

  /**
   * Parents point to children. Components are strongly connected components,
   * not disconnected subgraphs; a component is cyclic for a self-reference too.
   * Node and edge identities must be unique strings. Invalid references throw.
   * Returned paths contain orthogonal SVG M/L segments, ready for arrow markers.
   * Large graphs deliberately grow the canvas instead of overlapping nodes.
   */
  function layoutGraph(nodes, edges) {
    const { original, adjacency, reverse } = indexLayoutGraph(nodes, edges);
    const denseRouting = edges.length > 256;

    const finishingOrder = finishingNodeOrder(nodes, adjacency);
    const { componentOf, components } = strongComponents(finishingOrder, reverse, original);
    const children = rankComponents(components, componentOf, edges);
    const { maxRank, ranks, layerLinks, predecessors, successors } = createLayers(components, children, original);
    orderLayers(ranks, layerLinks, predecessors, successors, maxRank, denseRouting);

    const allocation = allocateRoutePorts(nodes, edges, ranks, components, componentOf);
    const { routes, rightLanes, outgoing, incoming, selfCounts } = allocation;
    const { positioned, rankX, cycleIncoming } = positionNodes(nodes, ranks, maxRank, original, allocation);

    const legacyRoutes = legacyRouteGeometry(routes, positioned, outgoing, incoming, cycleIncoming, selfCounts);
    const { optimized, resultNodes } = optimizeRoutes(nodes, edges, allocation, legacyRoutes, positioned, denseRouting);
    let width = nodes.length ? rankX[maxRank] + NODE_WIDTH + 56 + rightLanes[maxRank] * LANE + PADDING : PADDING * 2;
    let height = resultNodes.reduce((max, node) => Math.max(max, node.y + NODE_HEIGHT + PADDING), PADDING * 2);
    const routed = legacyRoutes.map(edge => {
      const {points, ...result} = optimized.get(edge.id) || edge;
      for (const point of points) { width = Math.max(width, point[0] + PADDING); height = Math.max(height, point[1] + PADDING); }
      return result;
    });
    return { nodes: resultNodes, edges: routed, width, height, components };
  }

  const LABEL_LINE_HEIGHT = 16, LABEL_PAD = 8, LABEL_MAX_TEXT_WIDTH = 196, LABEL_GAP = 7;
  const characterWidth = char => char.codePointAt(0) > 255 ? 12 : 7;

  function wrapCaption(text) {
    const lines = [];
    let line = '', width = 0;
    for (const char of text) {
      const nextWidth = characterWidth(char);
      if (line && width + nextWidth > LABEL_MAX_TEXT_WIDTH) { lines.push(line); line = ''; width = 0; }
      line += char; width += nextWidth;
    }
    if (line || !lines.length) lines.push(line);
    return lines;
  }

  function pathSegments(path) {
    const points = [...path.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)].map(m => [+m[1], +m[2]]);
    return points.slice(1).map((b, i) => [points[i], b]).filter(([a, b]) => a[0] !== b[0] || a[1] !== b[1]);
  }

  const boxesIntersect = (a, b, clearance = LABEL_GAP) => a.x < b.x + b.width + clearance && a.x + a.width + clearance > b.x &&
    a.y < b.y + b.height + clearance && a.y + a.height + clearance > b.y;
  const segmentCrossesBox = ([a, b], box, clearance = 3) => intersectsNode(a, b, box, clearance);

  function measureCaption(caption, edgeById, seen) {
    if (!caption || typeof caption.text !== 'string' || !caption.text || !edgeById.has(caption.edgeId)) throw new TypeError('Each caption needs a known edgeId and nonempty text');
    if (seen.has(caption.edgeId)) throw new Error(`Duplicate caption: ${caption.edgeId}`);
    seen.add(caption.edgeId);
    const edge = edgeById.get(caption.edgeId), lines = wrapCaption(caption.text);
    const boxWidth = Math.max(...lines.map(line => [...line].reduce((sum, char) => sum + characterWidth(char), 0))) + LABEL_PAD * 2;
    const boxHeight = lines.length * LABEL_LINE_HEIGHT + 12;
    return { edge, lines, boxWidth, boxHeight, candidates: [] };
  }

  function addLabelCandidate(context, measurement, x, y, anchor, endpoint) {
    const { layout, placed, occupiedSegments, width, height } = context;
    const { boxWidth, boxHeight, edge, candidates } = measurement;
    const box = { x, y, width: boxWidth, height: boxHeight };
    if (x < 8 || y < 8 || layout.nodes.some(node => boxesIntersect(box, node)) || placed.some(label => boxesIntersect(box, label))) return;
    if (occupiedSegments.some(segment => segmentCrossesBox(segment, box))) return;
    const leader = [anchor, endpoint];
    if (layout.nodes.some(node => segmentCrossesBox(leader, node, 2)) || placed.some(label => segmentCrossesBox(leader, label, 2))) return;
    const distance = Math.abs(endpoint[0] - anchor[0]) + Math.abs(endpoint[1] - anchor[1]);
    const expansion = Math.max(0, x + boxWidth + LABEL_PAD - width) + Math.max(0, y + boxHeight + LABEL_PAD - height);
    const score = distance + expansion * 2 + (Math.abs(anchor[0] - edge.labelX) + Math.abs(anchor[1] - edge.labelY)) * .2;
    candidates.push({ ...box, anchorX: anchor[0], anchorY: anchor[1], leaderPath: pathFor(leader), score });
  }

  function addBoundaryLabelCandidate(context, measurement, anchor, horizontal, position) {
    const { boxWidth, boxHeight } = measurement;
    if (horizontal) {
      if (position + boxHeight < anchor[1]) addLabelCandidate(context, measurement, anchor[0] - boxWidth / 2, position, anchor, [anchor[0], position + boxHeight]);
      else if (position > anchor[1]) addLabelCandidate(context, measurement, anchor[0] - boxWidth / 2, position, anchor, [anchor[0], position]);
    } else {
      if (position + boxWidth < anchor[0]) addLabelCandidate(context, measurement, position, anchor[1] - boxHeight / 2, anchor, [position + boxWidth, anchor[1]]);
      else if (position > anchor[0]) addLabelCandidate(context, measurement, position, anchor[1] - boxHeight / 2, anchor, [position, anchor[1]]);
    }
  }

  function addOffsetLabelCandidates(context, measurement, anchor, horizontal) {
    const { boxWidth, boxHeight } = measurement;
    for (const offset of [8, 24, 44, 72, 104, 152, 224, 320]) {
      if (horizontal) {
        addLabelCandidate(context, measurement, anchor[0] - boxWidth / 2, anchor[1] - offset - boxHeight, anchor, [anchor[0], anchor[1] - offset]);
        addLabelCandidate(context, measurement, anchor[0] - boxWidth / 2, anchor[1] + offset, anchor, [anchor[0], anchor[1] + offset]);
      } else {
        addLabelCandidate(context, measurement, anchor[0] - offset - boxWidth, anchor[1] - boxHeight / 2, anchor, [anchor[0] - offset, anchor[1]]);
        addLabelCandidate(context, measurement, anchor[0] + offset, anchor[1] - boxHeight / 2, anchor, [anchor[0] + offset, anchor[1]]);
      }
    }
  }

  function labelCandidatesAtAnchor(context, measurement, anchor, horizontal) {
    const { boxWidth, boxHeight } = measurement;
    // Row/column boundaries provide exact clearances where a fixed step
    // could jump over a narrow but usable space between neighboring tables.
    const boundaries = [...context.layout.nodes, ...context.placed].flatMap(box => horizontal
      ? [box.y - boxHeight - LABEL_GAP, box.y + box.height + LABEL_GAP]
      : [box.x - boxWidth - LABEL_GAP, box.x + box.width + LABEL_GAP]);
    boundaries.sort((a, b) => Math.abs(a - anchor[horizontal ? 1 : 0]) - Math.abs(b - anchor[horizontal ? 1 : 0]));
    for (const position of [...new Set(boundaries)].slice(0, 12)) {
      addBoundaryLabelCandidate(context, measurement, anchor, horizontal, position);
    }
    addOffsetLabelCandidates(context, measurement, anchor, horizontal);
  }

  function collectLabelCandidates(context, measurement) {
    for (const [a, b] of context.edgeSegments.get(measurement.edge.id)) {
      const horizontal = a[1] === b[1];
      for (const fraction of [.5, .25, .75]) {
        const anchor = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
        labelCandidatesAtAnchor(context, measurement, anchor, horizontal);
      }
    }
    measurement.candidates.sort((a, b) => a.score - b.score || a.y - b.y || a.x - b.x);
  }

  function moveBelowLabels(chosen, placed) {
    while (placed.some(label => boxesIntersect(chosen, label))) {
      chosen.y = Math.max(...placed.filter(label => boxesIntersect(chosen, label)).map(label => label.y + label.height + LABEL_GAP));
    }
  }

  function outsideLabelBox(context, measurement) {
    const { layout, placed, occupiedSegments } = context;
    const { edge, boxWidth, boxHeight } = measurement;
    // Guaranteed unclipped fallback beyond all original routes. Nearby
    // placements take precedence, so ordinary diagrams stay compact.
    const chosen = { x: layout.width + 24, y: Math.max(8, edge.labelY - boxHeight / 2), width: boxWidth, height: boxHeight,
      anchorX: edge.labelX, anchorY: edge.labelY, leaderPath: '' };
    moveBelowLabels(chosen, placed);
    // The outside column may contain an earlier leader. Move below it.
    while (occupiedSegments.some(segment => segmentCrossesBox(segment, chosen))) {
      chosen.y = Math.max(...occupiedSegments.filter(segment => segmentCrossesBox(segment, chosen)).flatMap(([a, b]) => [a[1], b[1]])) + LABEL_GAP;
      moveBelowLabels(chosen, placed);
    }
    return chosen;
  }

  function addLeaderCandidates(context, chosen, anchor, rows, candidates) {
    const corridorX = chosen.x - LABEL_GAP, targetY = chosen.y + chosen.height / 2;
    for (const row of rows) {
      const points = [anchor, [anchor[0], row], [corridorX, row], [corridorX, targetY], [chosen.x, targetY]];
      const parts = points.slice(1).map((b, i) => [points[i], b]);
      if (parts.some(segment => [...context.layout.nodes, ...context.placed].some(box => segmentCrossesBox(segment, box, 2)))) continue;
      const distance = parts.reduce((sum, [a, b]) => sum + Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]), 0);
      candidates.push({ points, anchor, distance });
    }
  }

  function connectOutsideLabel(context, measurement, chosen) {
    // Gutter captions use clear rows in the route's free vertical corridor.
    // Leaders may cross FK strokes, but never table or caption rectangles.
    const rows = [...new Set([8, context.height + LABEL_GAP, ...[...context.layout.nodes, ...context.placed]
      .flatMap(box => [box.y - LABEL_GAP, box.y + box.height + LABEL_GAP])])].filter(y => y >= 8);
    const leaderCandidates = [];
    for (const [a, b] of context.edgeSegments.get(measurement.edge.id)) for (const fraction of [.5, .25, .75]) {
      const anchor = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
      addLeaderCandidates(context, chosen, anchor, rows, leaderCandidates);
    }
    leaderCandidates.sort((a, b) => a.distance - b.distance);
    if (leaderCandidates.length) {
      const leader = leaderCandidates[0];
      chosen.leaderPath = pathFor(leader.points);
      chosen.anchorX = leader.anchor[0]; chosen.anchorY = leader.anchor[1];
      context.width = Math.max(context.width, ...leader.points.map(point => point[0] + PADDING));
      context.height = Math.max(context.height, ...leader.points.map(point => point[1] + PADDING));
    }
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
    const edgeSegments = new Map(layout.edges.map(edge => [edge.id, pathSegments(edge.path)]));
    const context = { layout, edgeSegments, occupiedSegments: [...edgeSegments.values()].flat(), placed: [], width: layout.width, height: layout.height };
    for (const caption of captions) {
      const measurement = measureCaption(caption, edgeById, seen);
      collectLabelCandidates(context, measurement);
      let chosen = measurement.candidates[0];
      if (!chosen) {
        chosen = outsideLabelBox(context, measurement);
        connectOutsideLabel(context, measurement, chosen);
      }
      const geometry = { ...chosen };
      delete geometry.score;
      const label = { edgeId: caption.edgeId, text: caption.text, lines: measurement.lines, lineHeight: LABEL_LINE_HEIGHT, ...geometry,
        textX: chosen.x + LABEL_PAD, textY: chosen.y + 17 };
      context.placed.push(label);
      if (label.leaderPath) context.occupiedSegments.push(...pathSegments(label.leaderPath));
      context.width = Math.max(context.width, label.x + label.width + PADDING);
      context.height = Math.max(context.height, label.y + label.height + PADDING);
    }
    return { ...layout, labels: context.placed, width: context.width, height: context.height };
  }

  const api = { layoutGraph, placeEdgeLabels };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SqlseedGraphLayout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
