const test = require('node:test');
const assert = require('node:assert/strict');
const {layoutGraph} = require('../src/sqlseed_web/static/js/workbench/graph-layout.js');

const pointsOf = edge => [...edge.path.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)]
  .map(match => [+match[1], +match[2]]);
const segmentsOf = edge => {
  const points = pointsOf(edge);
  return points.slice(1).map((point, i) => [points[i], point]);
};
const permutations = values => values.length < 2 ? [values]
  : values.flatMap((value, index) => permutations(values.filter((_, i) => i !== index))
    .map(rest => [value, ...rest]));

// Measure rendered routes independently of the layout's candidate scoring.
// Shared endpoints are junctions, not crossings; only strict interiors count.
function metrics(layout) {
  let crossings = 0, length = 0, bends = 0;
  for (let i = 0; i < layout.edges.length; i++) {
    const segments = segmentsOf(layout.edges[i]);
    bends += Math.max(0, segments.length - 1);
    for (const [a, b] of segments) length += Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]);
    for (let j = i + 1; j < layout.edges.length; j++) {
      const intersections = new Set();
      for (const a of segments) for (const b of segmentsOf(layout.edges[j])) {
        const aVertical = a[0][0] === a[1][0], bVertical = b[0][0] === b[1][0];
        if (aVertical === bVertical) continue;
        const vertical = aVertical ? a : b, horizontal = aVertical ? b : a;
        const x = vertical[0][0], y = horizontal[0][1];
        if (x > Math.min(horizontal[0][0], horizontal[1][0]) &&
            x < Math.max(horizontal[0][0], horizontal[1][0]) &&
            y > Math.min(vertical[0][1], vertical[1][1]) &&
            y < Math.max(vertical[0][1], vertical[1][1])) intersections.add(`${x},${y}`);
      }
      crossings += intersections.size;
    }
  }
  return {crossings, bends, length};
}

function shopFixture() {
  return {
    nodes: ['order_items', 'orders', 'products', 'users'].map((id, i) => ({
      id, selected: i !== 2, referenced: i === 2, count: 100 + i,
      columns: [{name: 'id', type: 'INTEGER'}],
    })),
    edges: [['products', 'order_items'], ['orders', 'order_items'], ['users', 'orders']]
      .map(([source, target], i) => ({id: `fk-${i}`, source, target,
        sourceColumns: ['tenant_id', 'id'], targetColumns: ['tenant_id', `${source}_id`]})),
  };
}

function assertBusinessPreserved(data, layout) {
  for (const collection of ['nodes', 'edges']) {
    assert.deepEqual(layout[collection].map(item => item.id), data[collection].map(item => item.id));
    data[collection].forEach((item, index) => {
      for (const key of Object.keys(item)) assert.deepEqual(layout[collection][index][key], item[key]);
    });
  }
  const nodes = new Map(layout.nodes.map(node => [node.id, node]));
  for (const edge of data.edges) assert.ok(nodes.get(edge.source).rank < nodes.get(edge.target).rank,
    `${edge.id} retains its parent-to-child direction`);
  for (let i = 0; i < layout.nodes.length; i++) for (let j = i + 1; j < layout.nodes.length; j++) {
    const a = layout.nodes[i], b = layout.nodes[j];
    assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x ||
      a.y + a.height <= b.y || b.y + b.height <= a.y, `${a.id} and ${b.id} do not overlap`);
  }
}

test('four-table routes remove the old crossing without increasing bends or distance', () => {
  const data = shopFixture(), layout = layoutGraph(data.nodes, data.edges);
  const quality = metrics(layout);
  // Previous routes: one crossing at (416,162), three bends, total length 908.
  assert.equal(quality.crossings, 0);
  assert.ok(quality.bends <= 3, JSON.stringify(quality));
  assert.ok(quality.length < 908, JSON.stringify(quality));
});

test('all node and edge permutations preserve business data and clear four-table routing', () => {
  const fixture = shopFixture();
  const cases = [
    ...permutations(fixture.nodes).map(nodes => ({nodes, edges: fixture.edges})),
    ...permutations(fixture.edges).map(edges => ({nodes: fixture.nodes, edges})),
  ];
  for (const data of cases) {
    const before = structuredClone(data), layout = layoutGraph(data.nodes, data.edges);
    assertBusinessPreserved(data, layout);
    assert.deepEqual(data, before, 'Presentation ordering never mutates the schema or selection');
    const quality = metrics(layout);
    assert.equal(quality.crossings, 0, JSON.stringify(data.nodes.map(node => node.id)));
    assert.ok(quality.bends <= 3, JSON.stringify(quality));
  }
});

test('same-layer ordering removes an avoidable crossing between reversed sibling branches', () => {
  const nodes = ['parent-a', 'parent-b', 'child-b', 'child-a'].map(id => ({id}));
  const edges = [
    {id: 'a', source: 'parent-a', target: 'child-a'},
    {id: 'b', source: 'parent-b', target: 'child-b'},
  ];
  const layout = layoutGraph(nodes, edges), quality = metrics(layout);
  assert.equal(quality.crossings, 0);
  assert.equal(quality.bends, 0, 'Reordering siblings permits both relationships to remain straight');
  assertBusinessPreserved({nodes, edges}, layout);
});

test('selection and row-count changes leave deterministic graph geometry unchanged', () => {
  const data = shopFixture(), first = layoutGraph(data.nodes, data.edges);
  assert.deepEqual(layoutGraph(data.nodes, data.edges), first);
  const changed = data.nodes.map(node => ({...node, selected: !node.selected,
    referenced: !node.referenced, count: node.count * 10}));
  const next = layoutGraph(changed, data.edges);
  const geometry = layout => ({
    nodes: layout.nodes.map(({id, x, y, width, height, rank}) => ({id, x, y, width, height, rank})),
    edges: layout.edges.map(({id, source, target, path}) => ({id, source, target, path})),
    width: layout.width, height: layout.height,
  });
  assert.deepEqual(geometry(next), geometry(first));
  assertBusinessPreserved({nodes: changed, edges: data.edges}, next);
});
