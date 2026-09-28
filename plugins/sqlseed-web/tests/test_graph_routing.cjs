const test = require('node:test');
const assert = require('node:assert/strict');
const {layoutGraph, placeEdgeLabels} = require('../src/sqlseed_web/static/js/workbench/graph-layout.js');

const pointsOf = edge => [...edge.path.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)].map(match => [+match[1], +match[2]]);
const fixture = (ids, pairs) => ({nodes: ids.map(id => ({id})),
  edges: pairs.map(([source, target], i) => ({id: `fk-${i}`, source, target}))});
const boundary = (point, node) => ((point[0] === node.x || point[0] === node.x + node.width) &&
  point[1] >= node.y && point[1] <= node.y + node.height) ||
  ((point[1] === node.y || point[1] === node.y + node.height) && point[0] >= node.x && point[0] <= node.x + node.width);

function assertClearRoutes(layout) {
  const nodes = new Map(layout.nodes.map(node => [node.id, node]));
  for (const edge of layout.edges) {
    const points = pointsOf(edge);
    assert.ok(boundary(points[0], nodes.get(edge.source)), `${edge.id} starts on its actual source`);
    assert.ok(boundary(points.at(-1), nodes.get(edge.target)), `${edge.id} ends on its actual target`);
    for (const point of points) {
      assert.ok(point[0] >= 0 && point[0] <= layout.width && point[1] >= 0 && point[1] <= layout.height, `${edge.id} stays inside the canvas`);
    }
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      assert.ok(a[0] === b[0] || a[1] === b[1], `${edge.id} has only orthogonal segments`);
      assert.notDeepEqual(a, b, `${edge.id} has no zero-length segment`);
      for (const node of layout.nodes) {
        const intersects = a[0] === b[0]
          ? a[0] > node.x && a[0] < node.x + node.width && Math.max(a[1], b[1]) > node.y && Math.min(a[1], b[1]) < node.y + node.height
          : a[1] > node.y && a[1] < node.y + node.height && Math.max(a[0], b[0]) > node.x && Math.min(a[0], b[0]) < node.x + node.width;
        assert.equal(intersects, false, `${edge.id} must not pass through ${node.id}`);
      }
    }
  }
}

test('the four-table workbench aligns the main chain and brings its side source beside the merge', () => {
  const data = fixture(['order_items', 'orders', 'products', 'users'],
    [['products', 'order_items'], ['orders', 'order_items'], ['users', 'orders']]);
  const before = structuredClone(data), layout = layoutGraph(data.nodes, data.edges);
  const orders = layout.nodes.find(node => node.id === 'orders');
  const products = layout.nodes.find(node => node.id === 'products');
  const direct = pointsOf(layout.edges[1]), branch = pointsOf(layout.edges[0]);
  assert.equal(direct.length, 2, 'Adjacent same-height tables connect without port-induced bends');
  assert.equal(products.rank, orders.rank, 'A source with rank slack belongs beside the merge instead of crossing an earlier chain');
  assert.equal(branch.length, 3, 'The side source reaches the merge with one elbow');
  assert.equal(pointsOf(layout.edges[2]).length, 2, 'The principal dependency chain stays straight');
  assert.deepEqual(layout.edges.map(({id, source, target}) => ({id, source, target})), data.edges);
  assert.deepEqual(data, before, 'Routing never mutates schema or generation selection');
  assertClearRoutes(layout);
});

test('parallel foreign keys retain distinct source and target ports without artificial bends', () => {
  const data = fixture(['parent', 'child'], Array.from({length: 7}, () => ['parent', 'child']));
  const layout = layoutGraph(data.nodes, data.edges);
  assert.equal(new Set(layout.edges.map(edge => edge.path)).size, 7);
  assert.equal(new Set(layout.edges.map(edge => JSON.stringify(pointsOf(edge)[0]))).size, 7);
  assert.equal(new Set(layout.edges.map(edge => JSON.stringify(pointsOf(edge).at(-1)))).size, 7);
  assert.ok(layout.edges.every(edge => pointsOf(edge).length === 2));
  assertClearRoutes(layout);
});

test('self references and reverse SCC edges preserve clear dedicated routes alongside normal edges', () => {
  const data = fixture(['a', 'b', 'child', 'other'],
    [['a', 'a'], ['a', 'a'], ['a', 'b'], ['b', 'a'], ['a', 'child'], ['b', 'child'], ['other', 'child']]);
  const layout = layoutGraph(data.nodes, data.edges);
  assert.deepEqual(layout.edges.slice(0, 4).map(edge => edge.kind), ['self', 'self', 'cycle', 'cycle']);
  assert.equal(new Set(layout.edges.map(edge => edge.path)).size, layout.edges.length);
  assertClearRoutes(layout);
  assert.deepEqual(layoutGraph(data.nodes, data.edges), layout, 'Cyclic and parallel routes stay deterministic');
});

test('dense multi-rank dependencies remain bounded, deterministic and avoid every table', () => {
  const first = ['a0', 'a1', 'a2', 'a3'], middle = ['b0', 'b1', 'b2', 'b3', 'b4', 'b5'];
  const last = ['c0', 'c1', 'c2', 'c3', 'c4'];
  const pairs = [...first.flatMap(a => middle.map(b => [a, b])),
    ...middle.flatMap(b => last.map(c => [b, c])), ...first.flatMap(a => last.map(c => [a, c]))];
  const data = fixture([...last, ...middle, ...first], pairs), layout = layoutGraph(data.nodes, data.edges);
  assertClearRoutes(layout);
  assert.deepEqual(layoutGraph(data.nodes, data.edges), layout);
  assert.equal(layout.edges.length, pairs.length);
});

test('routes between interior ranks also avoid tables before the source and after the target', () => {
  const data = fixture(['origin', 'left_sibling', 'middle_upper', 'middle_lower', 'target_upper', 'target_lower', 'tail', 'right_sibling'],
    [['origin', 'middle_upper'], ['origin', 'middle_lower'], ['left_sibling', 'middle_lower'],
      ['middle_upper', 'target_upper'], ['middle_lower', 'target_lower'], ['middle_lower', 'target_upper'],
      ['target_upper', 'tail'], ['target_lower', 'right_sibling']]);
  const layout = layoutGraph(data.nodes, data.edges), byId = new Map(layout.nodes.map(node => [node.id, node]));
  assert.ok(byId.get('middle_lower').rank > byId.get('origin').rank);
  assert.ok(byId.get('target_upper').rank < byId.get('tail').rank);
  assertClearRoutes(layout);
});

test('shortened routes remain unchanged when full field captions are placed', () => {
  const data = fixture(['items', 'orders', 'products', 'users'],
    [['products', 'items'], ['orders', 'items'], ['users', 'orders']]);
  const layout = layoutGraph(data.nodes, data.edges);
  const labelled = placeEdgeLabels(layout, layout.edges.map(edge => ({edgeId: edge.id,
    text: `${edge.source}.id → ${edge.target}.source_identifier`})));
  assert.deepEqual(labelled.edges, layout.edges);
  assert.deepEqual(labelled.nodes, layout.nodes);
  assert.equal(labelled.labels.length, 3);
  assertClearRoutes(labelled);
});

test('varied acyclic branches and parallel references never send routes through unrelated nodes', () => {
  let seed = 9026;
  const random = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32);
  for (let scenario = 0; scenario < 12; scenario++) {
    const ids = Array.from({length: 16}, (_, i) => `table-${i}`), pairs = [];
    for (let source = 0; source < ids.length; source++) for (let target = source + 1; target < ids.length; target++) {
      if (random() < .18) {
        pairs.push([ids[source], ids[target]]);
        if (random() < .1) pairs.push([ids[source], ids[target]]);
      }
    }
    const data = fixture(ids, pairs), layout = layoutGraph(data.nodes, data.edges);
    assertClearRoutes(layout);
    assert.equal(new Set(layout.edges.map(edge => edge.path)).size, pairs.length);
  }
});

test('large simple dependency chains retain direct routes without recursive routing', () => {
  const ids = Array.from({length: 1200}, (_, i) => `table-${i}`);
  const data = fixture(ids, ids.slice(1).map((id, i) => [ids[i], id]));
  const layout = layoutGraph(data.nodes, data.edges);
  assert.equal(layout.nodes.length, ids.length);
  assert.equal(layout.edges.length, ids.length - 1);
  assert.ok(layout.edges.every(edge => pointsOf(edge).length === 2));
});

test('a 200-table, 1000-reference overview keeps every route safe with the dense search budget', t => {
  let seed = 927;
  const random = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32);
  const ids = Array.from({length: 200}, (_, i) => `table-${i}`);
  // Keep a long backbone as well as references across many layers. This is
  // more demanding than a shallow graph with the same node and edge counts.
  const pairs = new Map(ids.slice(1).map((id, i) => [`${i},${i + 1}`, [ids[i], id]]));
  while (pairs.size < 1000) {
    const source = Math.floor(random() * 199);
    const target = source + 1 + Math.floor(random() * (199 - source));
    pairs.set(`${source},${target}`, [ids[source], ids[target]]);
  }
  const data = fixture(ids, [...pairs.values()]), before = structuredClone(data);
  const started = performance.now(), layout = layoutGraph(data.nodes, data.edges);
  const firstDuration = performance.now() - started;
  assertClearRoutes(layout);
  const repeated = performance.now(), next = layoutGraph(data.nodes, data.edges);
  const nextDuration = performance.now() - repeated;
  assert.deepEqual(next, layout);
  assert.deepEqual(data, before);
  assert.equal(layout.nodes.length, 200);
  assert.equal(layout.edges.length, 1000);
  assert.equal(new Set(layout.edges.map(edge => edge.path)).size, 1000);
  t.diagnostic(`Dense overview layout: ${firstDuration.toFixed(0)}ms / ${nextDuration.toFixed(0)}ms; includes all 1000 routes`);
});
