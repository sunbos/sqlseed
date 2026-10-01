const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');
const {layoutGraph, placeEdgeLabels} = require('../src/sqlseed_web/static/js/workbench/graph-layout.js');
const {selectPlanGraph, selectGraph} = require('../src/sqlseed_web/static/js/workbench/dependency-view.js');
// test_complex_graph_fixture.py regenerates a real SQLite schema through the HTTP
// route and checks this compact snapshot; it is not a hand-authored toy graph.
const stored = require('./complex_business_graph.json');
const fixture = process.env.SQLSEED_COMPLEX_SCHEMA_PATH
  ? {...JSON.parse(fs.readFileSync(process.env.SQLSEED_COMPLEX_SCHEMA_PATH, 'utf8')), checks: stored.checks} : stored;
const clone = value => structuredClone(value);
const points = edge => [...edge.path.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)].map(match => [+match[1], +match[2]]);
const ids = graph => graph.nodes.map(node => node.id);

function assertRoutes(layout, source) {
  assert.deepEqual(ids(layout), ids(source));
  assert.deepEqual(layout.edges.map(edge => edge.id), source.edges.map(edge => edge.id));
  const nodes = new Map(layout.nodes.map(node => [node.id, node])), ports = new Set();
  const boundary = ([x,y], node) => ((x === node.x || x === node.x + node.width) && y >= node.y && y <= node.y + node.height)
    || ((y === node.y || y === node.y + node.height) && x >= node.x && x <= node.x + node.width);
  for (const edge of layout.edges) {
    const route = points(edge), original = source.edges.find(item => item.id === edge.id);
    for (const key of ['source', 'target', 'sourceColumns', 'targetColumns', 'nullable']) assert.deepEqual(edge[key], original[key]);
    for (const [id, point] of [[edge.source, route[0]], [edge.target, route.at(-1)]]) {
      assert.ok(boundary(point, nodes.get(id)), `${edge.id} uses the actual ${id} boundary`);
      const key = JSON.stringify([id, point]);
      assert.ok(!ports.has(key), `${edge.id} keeps a distinct FK port at ${id}`); ports.add(key);
    }
    for (let i=1; i<route.length; i++) {
      const a=route[i-1], b=route[i];
      assert.ok(a[0]===b[0] || a[1]===b[1], 'Only orthogonal segments');
      assert.notDeepEqual(a,b);
      for (const node of layout.nodes) {
        const hit = a[0]===b[0]
          ? a[0]>node.x && a[0]<node.x+node.width && Math.max(a[1],b[1])>node.y && Math.min(a[1],b[1])<node.y+node.height
          : a[1]>node.y && a[1]<node.y+node.height && Math.max(a[0],b[0])>node.x && Math.min(a[0],b[0])<node.x+node.width;
        assert.equal(hit,false,`${edge.source}→${edge.target} cannot cross ${node.id}`);
      }
    }
    assert.ok(route.every(([x,y])=>x>=0 && y>=0 && x<=layout.width && y<=layout.height));
  }
}

function planned(name='fulfillment') {
  const data=clone(fixture), checked=data.checks[name], selected=new Set(checked.selected);
  const references=new Set(checked.sources.filter(source=>!source.selected && source.has_values).map(source=>source.source_table));
  data.nodes.forEach(node=>Object.assign(node,{selected:selected.has(node.id),referenced:references.has(node.id),count:3}));
  return data;
}

function ui(options) {
  const document=createDom();
  const create=tag=>{
    const node=new Element(tag);node.clientWidth=1000;node.clientHeight=600;
    node.scrollLeft=0;node.scrollTop=0;node.setPointerCapture=()=>{};return node;
  };
  document.createElement=create;document.createElementNS=(_,tag)=>create(tag);
  const context=loadFrontend('api.js',{document,ResizeObserver:class{observe(){} disconnect(){}}});
  for(const file of ['graph-layout.js','dependency-view.js','graph.js']) {
    const source=fs.readFileSync(path.join(__dirname,'../src/sqlseed_web/static/js/workbench',file),'utf8')
      .replace(/^import .*;\s*$/gm,'').replace(/^export /gm,'');
    vm.runInContext(source,context,{filename:file});
  }
  const graph=context.createSchemaGraph(options);
  return {graph, nodes:()=>graph.el.querySelectorAll('[data-graph-node]').map(node=>node.dataset.graphNode),
    edges:()=>graph.el.querySelectorAll('[data-graph-edge]'),
    action:name=>graph.toolbar.querySelector(`[data-graph-action="${name}"]`) || graph.el.querySelector(`[data-graph-action="${name}"]`)};
}

test('real 26-table/55-FK commerce schema retains ports, cycles and grouped columns without crossing tables', t=>{
  const before=clone(fixture), start=performance.now(), layout=layoutGraph(fixture.nodes,fixture.edges);
  const duration=performance.now()-start;
  assert.equal(layout.nodes.length,26);assert.equal(layout.edges.length,55);
  assertRoutes(layout,fixture);
  assert.deepEqual(layoutGraph(fixture.nodes,fixture.edges),layout);
  assert.deepEqual(fixture,before);
  assert.equal(layout.edges.filter(edge=>edge.kind==='self').length,5);
  assert.equal(layout.edges.filter(edge=>edge.kind==='cycle').length,2);
  assert.equal(layout.edges.filter(edge=>edge.targetColumns.length===2).length,2);
  // A coarse watchdog catches accidental unbounded search; timing is reported,
  // not presented as a guaranteed performance SLA for every user's machine.
  assert.ok(duration<5000,`26-table layout stalled for ${duration.toFixed(0)}ms`);
  t.diagnostic(`Real commerce layout ${duration.toFixed(1)}ms, ${layout.width}×${layout.height}`);
});

test('all 55 actual field captions preserve geometry and fit their complete column mappings', t=>{
  const layout=layoutGraph(fixture.nodes,fixture.edges), start=performance.now();
  const labelled=placeEdgeLabels(layout,fixture.edges.map(edge=>({edgeId:edge.id,
    text:`${edge.source}.${edge.sourceColumns.join(' + ')} → ${edge.target}.${edge.targetColumns.join(' + ')}`})));
  assert.equal(labelled.labels.length,55);assert.deepEqual(labelled.nodes,layout.nodes);assert.deepEqual(labelled.edges,layout.edges);
  assert.ok(labelled.labels.some(label=>label.text.includes('warehouse_id + bin_code')));
  assertRoutes(labelled,fixture);
  t.diagnostic(`55 grouped field captions ${(performance.now()-start).toFixed(1)}ms`);
});

test('real fulfilled plan ends at existing sources and excludes their ancestors and unselected returns',()=>{
  const data=planned(), before=clone(data), plan=selectPlanGraph(data);
  assert.equal(plan.nodes.length,11);assert.equal(plan.edges.length,13);
  assert.deepEqual(ids(plan).sort(),['addresses','carriers','customers','inventory','order_items','payments',
    'product_variants','sales_orders','shipment_items','shipments','warehouses'].sort());
  assert.ok(plan.edges.every(edge=>data.checks.fulfillment.selected.includes(edge.target)));
  assertRoutes(layoutGraph(plan.nodes,plan.edges),plan);
  assert.deepEqual(data,before);
});

test('complete, upstream, downstream and neighbor paths preserve closures through cycles and side sources',()=>{
  const data=planned();
  const complete=selectGraph(data,'sales_orders','paths');
  assert.equal(complete.nodes.length,22);
  for(const name of ['purchase_orders','purchase_items','receipts','receipt_items']) assert.ok(!ids(complete).includes(name));
  for(const mode of ['paths','upstream','downstream','neighbors']) {
    const projection=selectGraph(data,'sales_orders',mode);
    assertRoutes(layoutGraph(projection.nodes,projection.edges),projection);
  }
  const cycle=selectGraph(data,'departments','upstream');
  assert.deepEqual(ids(cycle).sort(),['departments','employees','tenants']);
  assert.equal(cycle.roles.employees,'cycle');
});

test('actual graph search respects plan scope, expands complete paths in overview and never changes selection',async()=>{
  const data=planned(),before=clone(data),view=ui({schema:data,focus:'sales_orders',mode:'plan'});
  const search=view.graph.toolbar.querySelector('[data-graph-search]');
  search.value='stock_movements';await search.dispatchEvent('input');assert.deepEqual(view.nodes(),[]);
  await view.action('all').click();assert.ok(view.nodes().includes('stock_movements'));
  await view.action('clear-search').click();assert.equal(view.nodes().length,26);assert.equal(view.edges().length,55);
  search.value='bin_code';await search.dispatchEvent('input');
  assert.ok(view.nodes().includes('inventory'));assert.ok(view.nodes().includes('warehouse_bins'));
  assert.deepEqual(data,before);view.graph.destroy();
});

test('real cross-table cycle result locates only its two members and internal FK edges',()=>{
  const data=planned('cycles'),issue=data.checks.cycles.issues.find(issue=>issue.code==='cross_table_cycle');
  const view=ui({schema:data,focus:'departments',mode:'issues',issues:[issue]});
  assert.deepEqual(view.nodes().sort(),['departments','employees']);
  assert.deepEqual(view.edges().filter(edge=>edge.classList.contains('problem')).map(edge=>edge.dataset.graphEdge).sort(),issue.edge_ids.slice().sort());
  assert.equal(view.edges().length,4,'Self references stay visible but are not falsely marked cross-table cycles');
  view.graph.destroy();
});

test('composite issue matches its exact group; structured identifiers and legacy joined columns agree',()=>{
  const data=planned('composite');
  const edge=data.edges.find(edge=>edge.target==='inventory' && edge.source==='warehouse_bins');
  for(const columns of [{columns:['warehouse_id','bin_code'],column:'obsolete legacy value'},{column:'warehouse_id,bin_code'}]) {
    const view=ui({schema:data,focus:'inventory',mode:'issues',issues:[{table:'inventory',source_table:'warehouse_bins',...columns}]});
    assert.deepEqual(view.nodes().sort(),['inventory','warehouse_bins']);
    assert.deepEqual(view.edges().filter(edge=>edge.classList.contains('problem')).map(edge=>edge.dataset.graphEdge),[edge.id]);
    view.graph.destroy();
  }
  const view=ui({schema:data,focus:'inventory',mode:'issues',issues:[{table:'inventory',columns:['warehouse_id']}]});
  assert.ok(!view.edges().some(item=>item.dataset.graphEdge===edge.id),'A single-column issue must not be mistaken for the composite constraint');
  view.graph.destroy();
});

test('unlocated global check errors retain selected context and explicitly request check details',()=>{
  const data=planned(),view=ui({schema:data,focus:'sales_orders',mode:'issues',issues:[{code:'snapshot_not_supported',severity:'error'}]});
  assert.equal(view.nodes().length,11);assert.ok(view.edges().every(edge=>!edge.classList.contains('problem')));
  assert.match(view.graph.toolbar.querySelector('.graph-scope-note').textContent,/整个生成计划.*检查详情/);
  view.graph.destroy();
});
