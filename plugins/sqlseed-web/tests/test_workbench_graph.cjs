const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const root = path.join(__dirname, '../src/sqlseed_web/static/js/workbench');
const ids = ['users', 'orders', 'items', 'products', 'reviews', 'inventory', 'audit'];
function schema() {
  return {
    tables: ids.map(name => ({name, row_count: 0, columns: [{name:'id'}]})),
    nodes: ids.map(id => ({id, name:id})),
    edges: [
      ['users', 'orders'], ['orders', 'items'], ['products', 'items'],
      ['users', 'reviews'], ['products', 'inventory'],
    ].map(([source,target], index) => ({id:`fk-${index}`, source, target, sourceColumns:['id'], targetColumns:[`${source}_id`], nullable:false})),
  };
}

function harness() {
  const document = createDom();
  const create = tag => {
    const element = new Element(tag);
    element.clientWidth = 800; element.clientHeight = 420;
    element.scrollLeft = 0; element.scrollTop = 0;
    element.setPointerCapture = () => {};
    return element;
  };
  document.createElement = create;
  document.createElementNS = (_,tag) => create(tag);
  const observers = [];
  class ResizeObserver {
    constructor(callback) { this.callback=callback; this.disconnected=false; observers.push(this); }
    observe() {}
    disconnect() { this.disconnected=true; }
  }
  const context = loadFrontend('api.js', {document, ResizeObserver});
  for (const name of ['graph-layout.js','dependency-view.js','graph.js']) {
    const source = fs.readFileSync(path.join(root,name),'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export /gm,'');
    vm.runInContext(source, context, {filename:name});
  }
  return {document, observers, create: options => context.createSchemaGraph(options), viewport:context.graphViewport};
}

const nodeIds = graph => graph.el.querySelectorAll('[data-graph-node]').map(node=>node.getAttribute('data-graph-node'));
const button = (graph, action) => graph.el.querySelector(`[data-graph-action="${action}"]`) || graph.toolbar?.querySelector(`[data-graph-action="${action}"]`);
const searchInput = graph => (graph.toolbar || graph.el).querySelector('[data-graph-search]');

test('real schema nodes and FK directions survive rendering; browsing never changes inputs', async () => {
  const {create} = harness();
  const data = schema(); const before = structuredClone(data); const selected=[]; const edges=[];
  const graph=create({schema:data,focus:'orders',onSelect:id=>selected.push(id),onEdge:edge=>edges.push(edge)});
  assert.deepEqual(nodeIds(graph).sort(), ids.slice().sort());
  assert.equal(graph.el.querySelectorAll('[data-graph-edge]').length,5);
  const current=graph.el.querySelector('[data-graph-node="orders"]');
  assert.equal(current.getAttribute('aria-pressed'),'true');
  await graph.el.querySelector('[data-graph-node="products"]').click();
  assert.deepEqual(selected,['products']);
  await graph.el.querySelector('[data-graph-edge="fk-1"]').click();
  assert.equal(edges[0].source,'orders'); assert.equal(edges[0].target,'items');
  assert.deepEqual(data,before);
});

test('complete paths include side sources without unrelated descendants', async () => {
  const {create}=harness(); const graph=create({schema:schema(),focus:'orders',mode:'paths'});
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  await button(graph,'upstream').click();
  assert.deepEqual(nodeIds(graph).sort(),['orders','users']);
  await button(graph,'downstream').click();
  assert.deepEqual(nodeIds(graph).sort(),['items','orders']);
  await button(graph,'neighbors').click();
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','users']);
  await button(graph,'all').click();
  assert.equal(nodeIds(graph).length,7);
});

test('the percentage reports actual diagram scale and fit stays distinct from natural reading size', async () => {
  const {create}=harness(); const graph=create({schema:schema(),focus:'items'});
  const zoom=graph.el.querySelector('[data-graph-zoom]');
  const svg=graph.el.querySelector('svg');
  const actualPercent=()=>Math.round(Number(svg.getAttribute('width'))/Number(svg.getAttribute('viewBox').split(' ')[2])*100)+'%';
  assert.equal(zoom.textContent,actualPercent());
  assert.notEqual(zoom.textContent,'100%');
  assert.ok(Number(svg.getAttribute('width'))<=800);
  assert.ok(Number(svg.getAttribute('height'))<=420);
  await button(graph,'zoom-in').click();
  assert.equal(zoom.textContent,actualPercent());
  await button(graph,'fit').click();
  await button(graph,'readable').click();
  const layoutWidth=Number(svg.getAttribute('viewBox').split(' ')[2]);
  assert.equal(Number(svg.getAttribute('width')),layoutWidth);
  assert.equal(zoom.textContent,'100%');
  await button(graph,'zoom-in').click();
  assert.equal(zoom.textContent,'125%');
  assert.equal(button(graph,'readable').disabled,false,'Natural reading size remains available after zooming above it');
  await button(graph,'readable').click();
  assert.equal(zoom.textContent,'100%');
  await button(graph,'fit').click();
  assert.equal(zoom.textContent,actualPercent());
  assert.equal(button(graph,'fit').getAttribute('aria-pressed'),'true');
});

test('a 24-table overview has a direct readable full dependency path for the current table',async()=>{
  const {create}=harness(),data=schema();
  for(let index=0;index<17;index++){
    const name=`unrelated_audit_${index}`;data.nodes.push({id:name,name});data.tables.push({name,columns:[{name:'id'}]});
  }
  data.nodes.find(node=>node.id==='orders').selected=true;
  const before=structuredClone(data),selections=[];
  const graph=create({schema:data,focus:'orders',onSelect:name=>selections.push(name)});
  const guide=graph.toolbar.querySelector('.graph-reading-guide');assert.ok(guide);
  assert.match(guide.textContent,/整库总览/);
  assert.equal(nodeIds(graph).length,24);
  assert.ok(Number.parseInt(graph.el.querySelector('[data-graph-zoom]').textContent)<100);
  await button(graph,'focus-readable').click();
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  assert.equal(graph.getView().mode,'paths');assert.equal(graph.getView().pathMode,'complete');
  assert.equal(graph.el.querySelector('[data-graph-zoom]').textContent,'100%');
  assert.equal(graph.el.querySelector('[data-graph-node="orders"]').getAttribute('data-current'),'true');
  assert.deepEqual(selections,[],'Reading the current table does not change the host selection');
  await button(graph,'all').click();assert.equal(nodeIds(graph).length,24);
  assert.deepEqual(data,before);
});

test('search results locate a readable dependency path without mutating selected tables or composite mappings',async()=>{
  const {create}=harness(),data=schema(),selected=[];
  data.tables.find(table=>table.name==='orders').columns.push({name:'订单编号'});
  data.edges[0].sourceColumns=['tenant_id','id'];data.edges[0].targetColumns=['tenant_id','users_id'];
  const before=structuredClone(data),graph=create({schema:data,focus:'audit',onSelect:name=>selected.push(name)}),input=searchInput(graph);
  input.value='订单编号';await input.dispatchEvent('input');
  const results=graph.toolbar.querySelectorAll('[data-graph-match]');
  assert.deepEqual(results.map(node=>node.getAttribute('data-graph-match')),['orders']);
  assert.match(results[0].textContent,/订单编号/);
  await results[0].click();
  assert.equal(searchInput(graph),input);assert.equal(input.value,'');
  assert.deepEqual(selected,['orders']);assert.equal(graph.getView().focus,'orders');
  assert.equal(graph.el.querySelector('[data-graph-zoom]').textContent,'100%');
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  assert.match(graph.el.querySelector('[data-graph-edge="fk-0"]').getAttribute('aria-label'),/tenant_id \+ id.*tenant_id \+ users_id/);
  assert.deepEqual(data,before);
});

test('search result navigation honors host veto and Enter cannot commit an IME candidate',async()=>{
  const {create}=harness();let blocked=true;const selected=[];
  const graph=create({schema:schema(),focus:'audit',onSelect:name=>{selected.push(name);return !blocked;}}),input=searchInput(graph);
  input.value='orders';await input.dispatchEvent('input');
  const before=JSON.parse(JSON.stringify(graph.getView()));
  await graph.toolbar.querySelector('[data-graph-match="orders"]').click();
  assert.deepEqual(JSON.parse(JSON.stringify(graph.getView())),before);
  assert.equal(input.value,'orders');
  await input.dispatchEvent('compositionstart');await input.dispatchEvent({type:'keydown',key:'Enter',isComposing:true});
  assert.deepEqual(selected,['orders']);
  await input.dispatchEvent('compositionend');blocked=false;
  await input.dispatchEvent({type:'keydown',key:'Enter'});
  assert.equal(graph.getView().focus,'orders');assert.equal(graph.el.querySelector('[data-graph-zoom]').textContent,'100%');
});

test('ambiguous search keeps its result count and Enter moves to a result without choosing a table',async()=>{
  const {create}=harness(),selected=[];
  const graph=create({schema:schema(),focus:'audit',onSelect:name=>selected.push(name)}),input=searchInput(graph);
  input.value='id';await input.dispatchEvent('input');
  assert.match(graph.toolbar.querySelector('.graph-search-count').textContent,/匹配 7 张表/);
  const first=graph.toolbar.querySelector('[data-graph-match]');let focused=false;
  first.focus=()=>{focused=true;};
  await input.dispatchEvent({type:'keydown',key:'Enter'});
  assert.equal(focused,true);assert.deepEqual(selected,[]);
  assert.equal(graph.getView().focus,'audit');assert.equal(input.value,'id');
  await first.click();assert.equal(graph.getView().focus,'users');assert.deepEqual(selected,['users']);
  assert.equal(graph.toolbar.querySelector('.graph-search-results').hidden,true);
  await graph.el.querySelector('[data-graph-node="orders"]').click();
  assert.match(button(graph,'focus-readable').getAttribute('aria-label'),/orders/);
  assert.match(graph.toolbar.querySelector('.graph-scope-note').textContent,/users/);
});

test('inspecting another node keeps the displayed path anchored until the explicit reading action, including restore',async()=>{
  const {create}=harness(),data=schema(),graph=create({schema:data,focus:'orders',mode:'paths'});
  const svg=graph.el.querySelector('svg'),before=nodeIds(graph).sort();
  await graph.el.querySelector('[data-graph-node="users"]').click();
  assert.equal(graph.el.querySelector('svg'),svg,'Node inspection keeps the current drawing stable');
  assert.deepEqual(nodeIds(graph).sort(),before);
  assert.equal(graph.getView().focus,'users');
  assert.match(graph.toolbar.querySelector('.graph-scope-note').textContent,/orders/);
  assert.match(graph.toolbar.querySelector('.graph-inspected-table').textContent,/当前查看：users/);
  assert.equal(graph.toolbar.querySelector('.graph-inspected-table').hidden,false);
  assert.match(button(graph,'focus-readable').getAttribute('aria-label'),/users/);
  const restored=create({schema:data,initialView:graph.getView()});
  assert.deepEqual(nodeIds(restored).sort(),before,'Restoring inspection must not silently add a different path');
  assert.match(restored.toolbar.querySelector('.graph-scope-note').textContent,/orders/);
  await button(restored,'focus-readable').click();
  assert.deepEqual(nodeIds(restored).sort(),['items','orders','products','reviews','users']);
  assert.match(restored.toolbar.querySelector('.graph-scope-note').textContent,/users/);
  assert.equal(restored.toolbar.querySelector('.graph-inspected-table').hidden,true);
  assert.equal(restored.el.querySelector('[data-graph-zoom]').textContent,'100%');
});

test('column captions keep composite mappings and select their relation', async () => {
  const {create}=harness(); const data=schema(); const selected=[];
  data.edges[0].sourceColumns=['tenant_id','id']; data.edges[0].targetColumns=['tenant_id','users_id'];
  const graph=create({schema:data,onEdge:edge=>selected.push(edge.id)});
  const toggle=graph.el.querySelector('[data-graph-label-toggle]');
  toggle.checked=true; await toggle.dispatchEvent('change');
  const label=graph.el.querySelector('[data-graph-label="fk-0"]');
  assert.match(label.textContent,/tenant_id/);
  assert.match(label.textContent,/users_id/);
  await label.click(); assert.deepEqual(selected,['fk-0']);
});

test('canvas supports keyboard and drag navigation and disconnects resize observation', async () => {
  const {create,observers}=harness(); const graph=create({schema:schema()});
  const canvas=graph.el.querySelector('[data-graph-canvas]');
  await canvas.dispatchEvent({type:'keydown',key:'ArrowRight'});
  assert.equal(canvas.scrollLeft,60);
  await canvas.dispatchEvent({type:'pointerdown',button:0,clientX:100,clientY:100,pointerId:1});
  await canvas.dispatchEvent({type:'pointermove',clientX:70,clientY:50});
  assert.equal(canvas.scrollLeft,90); assert.equal(canvas.scrollTop,50);
  await canvas.dispatchEvent({type:'pointerup',pointerId:1});
  graph.destroy();
  assert.ok(observers.every(observer=>observer.disconnected));
  assert.equal([...canvas.listeners.values()].reduce((count,listeners)=>count+listeners.size,0),0);
});

test('empty schemas display a meaningful empty state without fabricated tables', () => {
  const {create}=harness(); const graph=create({schema:{nodes:[],edges:[],tables:[]}});
  assert.equal(nodeIds(graph).length,0);
  assert.match(graph.el.textContent,/没有.*表|暂无.*表/);
});

test('issue view shows actual affected relationships and keeps cyclic graphs operable', () => {
  const {create}=harness(); const data=schema();
  data.edges.push({id:'self',source:'users',target:'users',sourceColumns:['id'],targetColumns:['manager_id']});
  const graph=create({schema:data,focus:'orders',mode:'issues',issues:[{table:'orders',column:'users_id',severity:'error'}]});
  assert.deepEqual(nodeIds(graph).sort(),['orders','users']);
  assert.ok(graph.el.querySelector('[data-graph-edge="self"]'));
});

test('long Chinese identifiers stay readable inside nodes with their full accessible names', () => {
  const {create}=harness();
  const name='用于回归验证非常长的中文数据库表名称';
  const graph=create({schema:{nodes:[{id:name}],edges:[],tables:[{name,columns:[]}]}});
  const node=graph.el.querySelector('[data-graph-node]');
  assert.ok(node.querySelector('.sg-node-title').textContent.length<=13);
  assert.equal(node.querySelector('title').textContent,name);
  assert.ok(node.getAttribute('aria-label').includes(name));
});

test('searching table and field names shows full paths and preserves the input element', async () => {
  const {create}=harness(); const data=schema();
  data.tables.find(table=>table.name==='orders').columns.push({name:'订单编号'});
  const graph=create({schema:data,focus:'orders'});
  const input=searchInput(graph);
  assert.ok(input);
  input.value='orders'; await input.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  assert.equal(searchInput(graph),input);
  input.value='订单编'; await input.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  assert.equal(searchInput(graph),input);
  await button(graph,'clear-search').click();
  assert.equal(input.value,'');
  assert.equal(nodeIds(graph).length,7);
});

test('IME composition does not redraw partial search strings and commits once completed', async () => {
  const {create}=harness(); const data=schema();
  data.tables.find(table=>table.name==='orders').columns.push({name:'订单编号'});
  const graph=create({schema:data});
  const input=searchInput(graph);
  assert.ok(input);
  const before=graph.el.querySelector('svg');
  await input.dispatchEvent('compositionstart');
  input.value='ding'; await input.dispatchEvent({type:'input',isComposing:true});
  assert.equal(graph.el.querySelector('svg'),before);
  input.value='订单'; await input.dispatchEvent('compositionend');
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  const after=graph.el.querySelector('svg');
  await input.dispatchEvent('input');
  assert.equal(graph.el.querySelector('svg'),after);
});

test('empty search results can be cleared back to the prior path scope', async () => {
  const {create}=harness();
  const graph=create({schema:schema(),focus:'orders',mode:'paths',pathMode:'upstream'});
  const input=searchInput(graph);
  assert.ok(input);
  input.value='does-not-exist'; await input.dispatchEvent('input');
  assert.equal(nodeIds(graph).length,0);
  assert.match(graph.el.textContent,/没有匹配.*表.*字段/);
  input.value=''; await input.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph).sort(),['orders','users']);
});

test('selected counts and read-only parent references remain distinct from focus', async () => {
  const {create}=harness(); const data=schema();
  data.nodes.find(node=>node.id==='orders').selected=true;
  data.nodes.find(node=>node.id==='orders').count=123;
  data.nodes.find(node=>node.id==='users').referenced=true;
  data.tables.find(table=>table.name==='users').row_count=20;
  const graph=create({schema:data,focus:'products'});
  const orders=graph.el.querySelector('[data-graph-node="orders"]');
  const users=graph.el.querySelector('[data-graph-node="users"]');
  assert.match(orders.querySelector('.sg-node-meta').textContent,/本次生成 123 行/);
  assert.equal(orders.getAttribute('data-selected'),'true');
  assert.match(users.querySelector('.sg-node-meta').textContent,/仅引用.*20/);
  assert.equal(users.getAttribute('data-referenced'),'true');
  assert.equal(users.getAttribute('data-selected'),'false');
  await users.click();
  assert.equal(users.getAttribute('aria-pressed'),'true');
  assert.equal(users.getAttribute('data-selected'),'false');
});

test('v8 graph exposes persistent full-width controls separately from its visual area', async () => {
  const {create,document}=harness(); const graph=create({schema:schema()});
  assert.ok(graph.toolbar, 'The host needs a toolbar above both graph and inspector');
  assert.equal(graph.el.contains(graph.toolbar),false);
  assert.ok(graph.toolbar.querySelector('.graph-toolbar'));
  assert.ok(graph.el.classList.contains('graph-visual'));
  assert.ok(graph.el.querySelector('.graph-canvas'));
  assert.equal(graph.el.querySelector('style'),null,'The application owns the shared v8 theme');
  document.body.append(graph.toolbar,graph.el);
  const input=searchInput(graph);
  input.value='orders'; await input.dispatchEvent('input');
  await button(graph,'complete').click();
  assert.equal(searchInput(graph),input);
  graph.destroy();
  assert.equal([...input.listeners.values()].reduce((count,listeners)=>count+listeners.size,0),0);
});

test('expanding the graph notifies the layout host without changing selection or search', async () => {
  const {create}=harness(); const data=schema(), before=structuredClone(data), expanded=[];
  const graph=create({schema:data,onExpand:value=>expanded.push(value)});
  const input=searchInput(graph);input.value='orders';await input.dispatchEvent('input');
  const expand=button(graph,'expand'); assert.ok(expand);
  await expand.click();
  assert.equal(expand.getAttribute('aria-pressed'),'true');
  assert.ok(graph.el.querySelector('.graph-canvas').classList.contains('expanded'));
  assert.equal(expand.textContent,'收起');
  assert.deepEqual(expanded,[true]);
  assert.equal(searchInput(graph),input);
  assert.equal(input.value,'orders');
  await expand.click();assert.deepEqual(expanded,[true,false]);
  assert.deepEqual(data,before);
});

test('field captions retain the actual reading scale and current viewing position', async () => {
  const {create}=harness();const graph=create({schema:schema(),focus:'orders'});
  await button(graph,'readable').click();
  const canvas=graph.el.querySelector('[data-graph-canvas]');
  canvas.scrollLeft=90;canvas.scrollTop=40;
  const before=graph.el.querySelector('svg'), scale=Number(before.getAttribute('width'))/Number(before.getAttribute('viewBox').split(' ')[2]);
  const toggle=graph.el.querySelector('[data-graph-label-toggle]');toggle.checked=true;await toggle.dispatchEvent('change');
  const after=graph.el.querySelector('svg');
  assert.equal(Number(after.getAttribute('width'))/Number(after.getAttribute('viewBox').split(' ')[2]),scale);
  assert.equal(canvas.scrollLeft,90);assert.equal(canvas.scrollTop,40);
});

test('enabling field captions keeps fit mode and reports the actual labelled diagram scale', async () => {
  const {create}=harness();const data=schema();
  data.edges[0].sourceColumns=['very_long_tenant_identifier','very_long_parent_identifier'];
  data.edges[0].targetColumns=['very_long_tenant_reference','very_long_parent_reference'];
  const graph=create({schema:data,focus:'orders'}),canvas=graph.el.querySelector('[data-graph-canvas]');
  const toggle=graph.el.querySelector('[data-graph-label-toggle]');
  toggle.checked=true;await toggle.dispatchEvent('change');
  const svg=graph.el.querySelector('svg');
  assert.equal(graph.el.querySelector('[data-graph-zoom]').textContent,Math.round(Number(svg.getAttribute('width'))/Number(svg.getAttribute('viewBox').split(' ')[2])*100)+'%');
  assert.equal(graph.getView().zoom,1);
  assert.ok(Number(svg.getAttribute('width'))<=canvas.clientWidth-24);
  assert.ok(Number(svg.getAttribute('height'))<=canvas.clientHeight-24);
  assert.equal(canvas.scrollLeft,0);assert.equal(canvas.scrollTop,0);
  toggle.checked=false;await toggle.dispatchEvent('change');
  assert.equal(graph.getView().zoom,1);
  assert.equal(button(graph,'fit').getAttribute('aria-pressed'),'true');
});

test('focusTable reveals an obscured node and keeps generation scope unchanged', async () => {
  const {create}=harness();const data=schema(),before=structuredClone(data);
  const graph=create({schema:data,focus:'orders',mode:'paths'});
  const input=searchInput(graph);input.value='orders';await input.dispatchEvent('input');
  assert.equal(typeof graph.focusTable,'function');
  assert.equal(graph.focusTable('audit'),true);
  assert.equal(input.value,'');
  assert.ok(nodeIds(graph).includes('audit'));
  assert.equal(graph.el.querySelector('[data-graph-node="audit"]').getAttribute('data-current'),'true');
  assert.equal(graph.focusTable('unknown'),false);
  assert.deepEqual(data,before);
});

test('graph view snapshots restore search, path mode, labels, zoom, expansion and scrolling', async () => {
  const {create}=harness();const data=schema(),before=structuredClone(data);
  const graph=create({schema:data,focus:'orders',mode:'paths'});
  await button(graph,'downstream').click();
  const input=searchInput(graph);input.value='orders';await input.dispatchEvent('input');
  const labels=graph.el.querySelector('[data-graph-label-toggle]');labels.checked=true;await labels.dispatchEvent('change');
  await button(graph,'readable').click();await button(graph,'zoom-in').click();await button(graph,'expand').click();
  const canvas=graph.el.querySelector('[data-graph-canvas]');canvas.scrollLeft=77;canvas.scrollTop=31;
  assert.equal(typeof graph.getView,'function');
  const view=JSON.parse(JSON.stringify(graph.getView()));
  assert.equal(view.mode,'paths');assert.equal(view.pathMode,'downstream');assert.equal(view.search,'orders');
  assert.equal(view.labels,true);assert.equal(view.expanded,true);assert.equal(view.focus,'orders');
  assert.equal(view.scrollLeft,77);assert.equal(view.scrollTop,31);
  const oldZoom=graph.el.querySelector('[data-graph-zoom]').textContent;graph.destroy();
  const expanded=[], restored=create({schema:data,initialView:view,onExpand:value=>expanded.push(value)});
  assert.equal(searchInput(restored).value,'orders');
  assert.equal(restored.el.querySelector('[data-graph-label-toggle]').checked,true);
  assert.equal(button(restored,'downstream').getAttribute('aria-pressed'),'true');
  assert.equal(restored.el.querySelector('[data-graph-zoom]').textContent,oldZoom);
  assert.equal(restored.el.querySelector('[data-graph-canvas]').scrollLeft,77);
  assert.equal(restored.el.querySelector('[data-graph-canvas]').scrollTop,31);
  assert.equal(button(restored,'expand').getAttribute('aria-pressed'),'true');
  assert.deepEqual(expanded,[true]);assert.deepEqual(data,before);
});

test('view change notifications expose current navigation without interrupting IME or surviving destroy', async () => {
  const {create}=harness(), changes=[];
  const graph=create({schema:schema(),onViewChange:view=>changes.push(JSON.parse(JSON.stringify(view)))});
  await button(graph,'paths').click();assert.ok(changes.length);
  assert.equal(changes.at(-1).mode,'paths');
  const input=searchInput(graph),count=changes.length;
  await input.dispatchEvent('compositionstart');input.value='ding';await input.dispatchEvent({type:'input',isComposing:true});
  assert.equal(changes.length,count);
  input.value='orders';await input.dispatchEvent('compositionend');assert.equal(changes.at(-1).search,'orders');
  const canvas=graph.el.querySelector('[data-graph-canvas]');canvas.scrollLeft=42;await canvas.dispatchEvent('scroll');
  assert.equal(changes.at(-1).scrollLeft,42);
  const atDestroy=changes.length;graph.destroy();
  await canvas.dispatchEvent('scroll');input.value='audit';await input.dispatchEvent('input');
  assert.equal(changes.length,atDestroy);
});

test('restoring a view tolerates removed focus nodes and unusable viewport values', () => {
  const {create}=harness();
  const graph=create({schema:schema(),initialView:{focus:'removed',mode:'invalid',pathMode:'invalid',zoom:NaN,scrollLeft:-3,scrollTop:Infinity}});
  assert.equal(typeof graph.getView,'function');
  const view=graph.getView();assert.ok(ids.includes(view.focus));
  assert.equal(view.mode,'all');assert.equal(view.pathMode,'complete');
  assert.equal(view.zoom,1);assert.equal(view.scrollLeft,0);assert.equal(view.scrollTop,0);
});

test('restored search uses its trimmed query while retaining the original input text', async () => {
  const {create}=harness();const graph=create({schema:schema()});
  const input=searchInput(graph);input.value=' orders ';await input.dispatchEvent('input');
  const expected=nodeIds(graph).sort(),view=graph.getView();graph.destroy();
  const restored=create({schema:schema(),initialView:view});
  assert.equal(searchInput(restored).value,' orders ');
  assert.deepEqual(nodeIds(restored).sort(),expected);
});

test('a host navigation veto leaves graph focus, highlighting and view notifications unchanged', async () => {
  const {create}=harness(),selected=[],changes=[];
  let blocked=true;
  const graph=create({schema:schema(),focus:'users',onSelect:name=>{selected.push(name);if(blocked)return false;},
    onViewChange:view=>changes.push(JSON.parse(JSON.stringify(view)))});
  const users=graph.el.querySelector('[data-graph-node="users"]'),orders=graph.el.querySelector('[data-graph-node="orders"]');
  const before=JSON.parse(JSON.stringify(graph.getView())),count=changes.length;
  await orders.click();
  assert.deepEqual(selected,['orders']);
  assert.deepEqual(JSON.parse(JSON.stringify(graph.getView())),before);
  assert.equal(users.getAttribute('data-current'),'true');
  assert.equal(orders.getAttribute('data-current'),'false');
  assert.equal(users.classList.contains('focused'),true);
  assert.equal(orders.classList.contains('focused'),false);
  assert.equal(changes.length,count);
  blocked=false;await orders.click();
  assert.equal(graph.getView().focus,'orders');
  assert.equal(users.getAttribute('data-current'),'false');
  assert.equal(orders.getAttribute('data-current'),'true');
  assert.equal(changes.at(-1).focus,'orders');
});

test('the graph explains node states and keeps the current-view ring separate from generation borders', () => {
  const {create}=harness(),data=schema();
  Object.assign(data.nodes.find(node=>node.id==='orders'),{selected:true,count:123});
  data.nodes.find(node=>node.id==='users').referenced=true;
  const graph=create({schema:data,focus:'users'}),legend=graph.el.querySelector('[data-graph-legend]');
  assert.ok(legend,'The live graph must display a legend');
  for(const label of ['本次生成','仅引用','其他表','当前查看'])assert.ok(legend.textContent.includes(label));
  const orders=graph.el.querySelector('[data-graph-node="orders"]'),users=graph.el.querySelector('[data-graph-node="users"]');
  assert.match(orders.getAttribute('aria-label'),/本次生成 123 行/);
  assert.match(users.getAttribute('aria-label'),/仅引用/);
  assert.match(graph.el.querySelector('[data-graph-node="audit"]').getAttribute('aria-label'),/其他表.*不参与本次生成/);
  const body=users.querySelector('.graph-node-body'),ring=users.querySelector('.graph-focus-ring');
  assert.ok(body);assert.ok(ring);
  assert.equal(ring.getAttribute('aria-hidden'),'true');
  assert.ok(Number(ring.getAttribute('x'))<Number(body.getAttribute('x')));
  assert.ok(Number(ring.getAttribute('width'))>Number(body.getAttribute('width')));
  assert.equal(users.getAttribute('data-referenced'),'true');
  assert.equal(users.getAttribute('aria-pressed'),'true');
});

test('node selection highlights complete dependencies in place and clears the old chain and selected edge', async () => {
  const {create}=harness(),data=schema(),before=structuredClone(data);
  const graph=create({schema:data,focus:'orders'}),canvas=graph.el.querySelector('[data-graph-canvas]');
  const related=()=>graph.el.querySelectorAll('[data-graph-edge]').filter(edge=>edge.classList.contains('path-related')).map(edge=>edge.getAttribute('data-graph-edge')).sort();
  assert.deepEqual(related(),['fk-0','fk-1','fk-2'],'Include products as the source required by the items branch');
  assert.ok(graph.el.querySelector('[data-graph-node="products"]').classList.contains('path-related'));
  assert.ok(graph.el.querySelector('[data-graph-edge="fk-3"]').classList.contains('path-unrelated'));
  await button(graph,'readable').click();canvas.scrollLeft=55;canvas.scrollTop=31;
  const svg=graph.el.querySelector('svg'),view=graph.getView(),coordinates=graph.el.querySelectorAll('.graph-node-body').map(rect=>[rect.getAttribute('x'),rect.getAttribute('y')]);
  await graph.el.querySelector('[data-graph-edge="fk-1"]').click();
  assert.equal(graph.getView().edgeId,'fk-1');
  await graph.el.querySelector('[data-graph-node="inventory"]').click();
  assert.deepEqual(related(),['fk-4']);
  assert.ok(graph.el.querySelector('[data-graph-edge="fk-1"]').classList.contains('path-unrelated'));
  assert.equal(graph.el.querySelector('[data-graph-edge="fk-1"]').classList.contains('focused'),false);
  assert.equal(graph.getView().edgeId,null);
  assert.equal(graph.el.querySelector('svg'),svg);
  assert.deepEqual(graph.el.querySelectorAll('.graph-node-body').map(rect=>[rect.getAttribute('x'),rect.getAttribute('y')]),coordinates);
  assert.equal(graph.getView().pathFocus,view.pathFocus);assert.equal(graph.getView().mode,view.mode);
  assert.equal(graph.getView().zoom,view.zoom);assert.equal(canvas.scrollLeft,55);assert.equal(canvas.scrollTop,31);
  assert.deepEqual(data,before);
});

test('cyclic dependencies terminate and unrelated issues stay identifiable during static highlighting', async () => {
  const {create}=harness(),data=schema();
  data.edges.push({id:'cycle',source:'items',target:'orders',sourceColumns:['id'],targetColumns:['item_id']});
  data.edges.push({id:'audit-self',source:'audit',target:'audit',sourceColumns:['id'],targetColumns:['previous_id']});
  const graph=create({schema:data,focus:'orders',issues:[{table:'audit',edge_id:'audit-self',severity:'error'}]});
  const highlighted=graph.el.querySelectorAll('[data-graph-edge]').filter(edge=>edge.classList.contains('path-related')).map(edge=>edge.getAttribute('data-graph-edge')).sort();
  assert.deepEqual(highlighted,['cycle','fk-0','fk-1','fk-2']);
  const issue=graph.el.querySelector('[data-graph-edge="audit-self"]');
  assert.ok(issue.classList.contains('problem'));assert.ok(issue.classList.contains('path-unrelated'));
  assert.equal(issue.getAttribute('data-issue'),'true');
  await issue.click();assert.ok(issue.classList.contains('focused'));
  assert.equal(issue.getAttribute('aria-pressed'),'true');
  assert.equal(graph.el.querySelector('[data-graph-edge="fk-0"]').getAttribute('aria-pressed'),'false');
});

test('keyboard selection updates the same dependency emphasis and relation captions as pointer selection', async () => {
  const {create}=harness(),selected=[],edges=[];
  const graph=create({schema:schema(),focus:'orders',onSelect:id=>selected.push(id),onEdge:edge=>edges.push(edge.id)});
  const toggle=graph.el.querySelector('[data-graph-label-toggle]');toggle.checked=true;await toggle.dispatchEvent('change');
  const inventory=graph.el.querySelector('[data-graph-node="inventory"]');
  await inventory.dispatchEvent({type:'keydown',key:'Enter'});
  assert.deepEqual(selected,['inventory']);assert.equal(inventory.getAttribute('aria-pressed'),'true');
  const label=graph.el.querySelector('[data-graph-label="fk-4"]');assert.ok(label.classList.contains('path-related'));
  await label.dispatchEvent({type:'keydown',key:' '});
  assert.deepEqual(edges,['fk-4']);assert.equal(label.getAttribute('aria-pressed'),'true');
  assert.ok(graph.el.querySelector('[data-graph-edge="fk-4"]').classList.contains('focused'));
  await graph.el.querySelector('[data-graph-node="audit"]').dispatchEvent({type:'keydown',key:' '});
  assert.deepEqual(selected,['inventory','audit']);assert.equal(label.getAttribute('aria-pressed'),'false');
  assert.equal(label.classList.contains('focused'),false);assert.ok(label.classList.contains('path-unrelated'));
});
