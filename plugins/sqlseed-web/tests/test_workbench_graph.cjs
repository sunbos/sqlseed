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

function harness({animate, window} = {}) {
  const document = createDom();
  const registrations = [];
  const create = tag => {
    const element = new Element(tag);
    element.clientWidth = 800; element.clientHeight = 420;
    element.scrollLeft = 0; element.scrollTop = 0;
    element.setPointerCapture = () => {};
    if (animate) element.animate = (frames, options) => animate(element, frames, options);
    const add = element.addEventListener.bind(element);
    element.addEventListener = (type, callback, options) => {
      registrations.push({element, type, options});
      add(type, callback, options);
    };
    return element;
  };
  document.createElement = create;
  document.createElementNS = (_,tag) => create(tag);
  const observers = [];
  class ResizeObserver {
    constructor(callback) { this.callback=callback; this.disconnected=false; this.targets=[]; observers.push(this); }
    observe(target) { this.targets.push(target); }
    disconnect() { this.disconnected=true; }
  }
  const context = loadFrontend('api.js', {document, ResizeObserver, ...(window ? {window} : {})});
  for (const name of ['graph-layout.js','dependency-view.js','graph.js']) {
    const source = fs.readFileSync(path.join(root,name),'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export /gm,'');
    vm.runInContext(source, context, {filename:name});
  }
  return {document, context, observers, registrations, create: options => context.createSchemaGraph(options), viewport:context.graphViewport};
}

const nodeIds = graph => graph.el.querySelectorAll('[data-graph-node]').map(node=>node.getAttribute('data-graph-node'));
const button = (graph, action) => graph.el.querySelector(`[data-graph-action="${action}"]`) || graph.toolbar?.querySelector(`[data-graph-action="${action}"]`);
const searchInput = graph => (graph.toolbar || graph.el).querySelector('[data-graph-search]');

test('UI language updates graph controls and SVG descriptions without redrawing nodes or altering the viewport',async()=>{
  const ui=harness(); const data=schema(); const events=[];
  const graph=ui.create({schema:data,focus:'orders',onViewChange:view=>events.push(view)});
  ui.document.body.append(graph.toolbar,graph.el);
  await button(graph,'zoom-in').click();
  const search=searchInput(graph),svg=graph.el.querySelector('svg.schema-graph');
  const node=graph.el.querySelector('[data-graph-node="orders"]');
  ui.document.activeElement=search; search.selectionStart=0;
  const before=JSON.stringify(graph.getView()),eventCount=events.length;
  ui.context.setLanguage('en');
  assert.equal(graph.el.querySelector('svg.schema-graph'),svg);
  assert.equal(graph.el.querySelector('[data-graph-node="orders"]'),node);
  assert.equal(ui.document.activeElement,search); assert.equal(searchInput(graph),search);
  assert.match(node.getAttribute('aria-label'),/View fields and relationships for orders/);
  assert.match(search.getAttribute('placeholder'),/Find tables or fields/);
  assert.match(svg.getAttribute('aria-label'),/Tables and foreign-key relationships/);
  assert.equal(JSON.stringify(graph.getView()),before); assert.equal(events.length,eventCount);
  ui.context.setLanguage('zh-CN');
  assert.match(node.getAttribute('aria-label'),/查看 orders/);
  assert.equal(JSON.stringify(graph.getView()),before); assert.deepEqual(Array.from(ui.context.missingMessages()),[]);
  graph.destroy();
});

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

test('path selection commits its graph projection immediately while its decorative indicator moves', async () => {
  const ui=harness(), data=schema(), before=structuredClone(data);
  const graph=ui.create({schema:data,focus:'orders',mode:'paths'});
  ui.document.body.append(graph.toolbar,graph.el);
  const group=graph.toolbar.querySelector('.path-modes'), indicator=group.querySelector('.segment-indicator');
  const actions=['complete','upstream','downstream','neighbors'];
  group.getBoundingClientRect=()=>({left:50,top:40,width:360,height:32});
  actions.forEach((action,index)=>{
    button(graph,action).getBoundingClientRect=()=>({left:50+90*index,top:40,width:86,height:32});
  });
  const observer=ui.observers.find(item=>item.targets.includes(group));
  observer.callback([]);
  assert.equal(group.getAttribute('data-segment-slide'),'false');
  assert.equal(indicator.style.transform,'translate(0px, 0px)');
  const upstream=button(graph,'upstream'); ui.document.activeElement=upstream;
  await upstream.click();
  assert.equal(graph.getView().pathMode,'upstream');
  assert.deepEqual(nodeIds(graph).sort(),['orders','users']);
  assert.equal(upstream.getAttribute('aria-pressed'),'true');
  assert.equal(button(graph,'complete').getAttribute('aria-pressed'),'false');
  assert.equal(group.getAttribute('data-segment-slide'),'true');
  assert.equal(indicator.style.transform,'translate(90px, 0px)');
  assert.equal(button(graph,'upstream'),upstream); assert.equal(ui.document.activeElement,upstream);
  await button(graph,'complete').click();
  assert.equal(graph.getView().pathMode,'complete');
  assert.deepEqual(nodeIds(graph).sort(),['items','orders','products','users']);
  assert.equal(group.querySelector('.segment-indicator'),indicator);
  assert.equal(indicator.getAttribute('aria-hidden'),'true');
  assert.equal(indicator.style.transform,'translate(0px, 0px)');
  assert.deepEqual(data,before);
  graph.destroy();
  assert.equal(observer.disconnected,true); assert.equal(group.querySelector('.segment-indicator'),null);
  observer.callback([]); assert.equal(group.getAttribute('data-segment-ready'),null);
});

test('generation plan shows selected tables and resolved sources without adding their ancestors or downstream tables', async () => {
  const {create} = harness(), data = schema();
  data.nodes.forEach(node => {
    node.selected = ['orders', 'products'].includes(node.id);
    node.referenced = node.id === 'users';
  });
  data.nodes.push({id: 'countries', name: 'countries'});
  data.edges.push({id: 'country-user', source: 'countries', target: 'users'});
  const before = structuredClone(data);
  const graph = create({schema: data, focus: 'orders', mode: 'plan'});
  assert.deepEqual(nodeIds(graph).sort(), ['orders', 'products', 'users']);
  assert.deepEqual(graph.el.querySelectorAll('[data-graph-edge]').map(edge => edge.dataset.graphEdge), ['fk-0']);
  assert.equal(button(graph, 'plan').getAttribute('aria-pressed'), 'true');
  assert.match(graph.toolbar.querySelector('.graph-scope-note').textContent, /本次生成/);
  await button(graph, 'all').click();
  assert.ok(nodeIds(graph).includes('items'));
  assert.ok(nodeIds(graph).includes('countries'));
  await button(graph, 'paths').click();
  assert.deepEqual(nodeIds(graph).sort(), ['countries', 'items', 'orders', 'products', 'users']);
  await button(graph, 'plan').click();
  const restored = create({schema: data, initialView: graph.getView()});
  assert.equal(restored.getView().mode, 'plan');
  assert.deepEqual(nodeIds(restored).sort(), ['orders', 'products', 'users']);
  assert.deepEqual(data, before);
});

test('plan search cannot silently expand to unselected downstream tables', async () => {
  const {create} = harness(), data = schema();
  data.nodes.forEach(node => {
    node.selected = ['orders', 'products'].includes(node.id);
    node.referenced = node.id === 'users';
  });
  const graph = create({schema: data, focus: 'orders', mode: 'plan'});
  const search = searchInput(graph);
  search.value = 'items'; await search.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph), []);
  assert.match(graph.toolbar.querySelector('.graph-scope-note').textContent, /仅在本次生成/);
  search.value = 'orders'; await search.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph).sort(), ['orders', 'users']);
  await button(graph, 'clear-search').click();
  assert.deepEqual(nodeIds(graph).sort(), ['orders', 'products', 'users']);
});

test('empty generation plan offers whole-schema browsing without selecting a table', async () => {
  const {create} = harness(), data = schema(), before = structuredClone(data);
  const graph = create({schema: data, focus: 'orders', mode: 'plan'});
  assert.deepEqual(nodeIds(graph), []);
  assert.match(graph.el.querySelector('.graph-empty').textContent, /尚未选择生成表/);
  await graph.el.querySelector('.graph-empty-action').click();
  assert.equal(graph.getView().mode, 'all');
  assert.deepEqual(nodeIds(graph).sort(), ids.slice().sort());
  assert.deepEqual(data, before);
});

test('plan projection retains parallel, composite and self references without mutating source data', () => {
  const {selectPlanGraph} = require(path.join(root, 'dependency-view.js'));
  const data = {nodes: [{id: 'users', referenced: true}, {id: 'orders', selected: true}, {id: 'items'}], edges: [
    {id: 'one', source: 'users', target: 'orders', sourceColumns: ['id', 'tenant'], targetColumns: ['user', 'tenant']},
    {id: 'two', source: 'users', target: 'orders'},
    {id: 'self', source: 'orders', target: 'orders'},
    {id: 'excluded', source: 'orders', target: 'items'},
  ]};
  const before = structuredClone(data), plan = selectPlanGraph(data);
  assert.deepEqual(plan.edges.map(edge => edge.id), ['one', 'two', 'self']);
  assert.deepEqual(plan.edges[0].targetColumns, ['user', 'tenant']);
  assert.deepEqual(data, before);
  assert.deepEqual(selectPlanGraph({nodes: [{id: 'users', referenced: true}], edges: []}), {nodes: [], edges: []});
});

test('relationships between read-only sources appear only in whole-schema and dependency views', async () => {
  const {create} = harness();
  const data = {nodes: [{id: 'A', referenced: true}, {id: 'B', referenced: true}, {id: 'C', selected: true}], edges: [
    {id: 'A-B', source: 'A', target: 'B'},
    {id: 'A-C', source: 'A', target: 'C'},
    {id: 'B-C', source: 'B', target: 'C'},
  ]};
  const graph = create({schema: data, focus: 'C', mode: 'plan'});
  const edges = () => graph.el.querySelectorAll('[data-graph-edge]').map(edge => edge.dataset.graphEdge).sort();
  assert.deepEqual(nodeIds(graph).sort(), ['A', 'B', 'C']);
  assert.deepEqual(edges(), ['A-C', 'B-C']);
  const search = searchInput(graph);
  search.value = 'C'; await search.dispatchEvent('input');
  assert.deepEqual(nodeIds(graph).sort(), ['A', 'B', 'C']);
  assert.deepEqual(edges(), ['A-C', 'B-C']);
  await button(graph, 'clear-search').click();
  await button(graph, 'all').click();
  assert.deepEqual(edges(), ['A-B', 'A-C', 'B-C']);
  await button(graph, 'paths').click();
  assert.deepEqual(edges(), ['A-B', 'A-C', 'B-C']);
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

const scaleInput = graph => graph.el.querySelector('[data-graph-zoom-input]');
const actualScale = graph => {
  const svg = graph.el.querySelector('svg.schema-graph');
  return Number(svg.getAttribute('width')) / Number(svg.getAttribute('viewBox').split(' ')[2]);
};
async function editScale(graph, value, event = {type: 'keydown', key: 'Enter'}) {
  const input = scaleInput(graph);
  input.value = value;
  await input.dispatchEvent('input');
  await input.dispatchEvent(event);
}

test('editable scale applies actual percentages with Enter or blur and synchronizes all zoom actions in place', async () => {
  const ui = harness(), data = schema(), before = structuredClone(data);
  const graph = ui.create({schema: data, focus: 'items'});
  ui.document.body.append(graph.toolbar, graph.el);
  const input = scaleInput(graph), svg = graph.el.querySelector('svg.schema-graph');
  const node = graph.el.querySelector('[data-graph-node="items"]');
  const canvas = graph.el.querySelector('.graph-canvas');
  const geometry = () => graph.el.querySelectorAll('.edge-line').map(line => line.getAttribute('d'));
  const paths = geometry(); ui.document.activeElement = input;
  assert.equal(Number(input.value), Number((actualScale(graph) * 100).toFixed(2)));
  await editScale(graph, '125');
  assert.ok(Math.abs(actualScale(graph) - 1.25) < 1e-10);
  assert.equal(graph.el.querySelector('svg.schema-graph'), svg);
  assert.equal(graph.el.querySelector('[data-graph-node="items"]'), node);
  assert.equal(ui.document.activeElement, input); assert.equal(scaleInput(graph), input);
  assert.equal(input.value, '125'); assert.equal(input.getAttribute('aria-invalid'), null);
  await editScale(graph, ' 87.5% ', 'blur');
  assert.ok(Math.abs(actualScale(graph) - .875) < 1e-10); assert.equal(input.value, '87.5');
  await button(graph, 'zoom-in').click();
  assert.equal(Number(input.value), Number((actualScale(graph) * 100).toFixed(2)));
  await wheel(canvas, {ctrlKey: true});
  assert.equal(Number(input.value), Number((actualScale(graph) * 100).toFixed(2)));
  await button(graph, 'readable').click(); assert.equal(input.value, '100');
  await button(graph, 'fit').click();
  assert.equal(Number(input.value), Number((actualScale(graph) * 100).toFixed(2)));
  assert.equal(button(graph, 'fit').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(geometry(), paths); assert.deepEqual(data, before);
  graph.destroy();
});

test('invalid scale leaves the graph unchanged, retains correction text and cancels locally with Escape', async () => {
  const ui = harness(), changes = [], graph = ui.create({schema: schema(), onViewChange: view => changes.push(view)});
  ui.document.body.append(graph.toolbar, graph.el);
  await button(graph, 'readable').click();
  const input = scaleInput(graph), error = graph.el.querySelector('.graph-zoom-error');
  ui.document.activeElement = input;
  const view = JSON.stringify(graph.getView()), count = changes.length;
  for (const value of ['', ' ', '0', '-25', 'NaN', 'Infinity', '100x', '1e2', '99999999']) {
    await editScale(graph, value);
    assert.equal(input.value, value); assert.equal(input.getAttribute('aria-invalid'), 'true');
    assert.equal(error.hidden, false); assert.match(error.textContent, /请输入.*当前缩放未改变/);
    assert.equal(JSON.stringify(graph.getView()), view); assert.equal(changes.length, count);
    assert.equal(ui.document.activeElement, input);
  }
  ui.context.setLanguage('en');
  assert.match(error.textContent, /Enter a number.*unchanged/); assert.equal(input.value, '99999999');
  let prevented = false, stopped = false;
  await input.dispatchEvent({type: 'keydown', key: 'Escape', preventDefault() {prevented = true;}, stopPropagation() {stopped = true;}});
  assert.equal(prevented, true); assert.equal(stopped, true);
  assert.equal(input.value, '100'); assert.equal(input.getAttribute('aria-invalid'), null);
  assert.equal(error.hidden, true); assert.equal(JSON.stringify(graph.getView()), view);
  await editScale(graph, 'broken', 'blur');
  await button(graph, 'zoom-out').click();
  assert.equal(input.value, '80'); assert.equal(error.hidden, true);
  assert.equal(input.getAttribute('aria-invalid'), null);
  assert.deepEqual(Array.from(ui.context.missingMessages()), []);
  graph.destroy();
});

test('typed bounds follow the existing fit-relative range, including small fits and the 200 percent upper floor', async () => {
  const ui = harness(), data = structuredClone(require('./complex_business_graph.json'));
  const graph = ui.create({schema: data, focus: 'customers'}), input = scaleInput(graph);
  const fit = actualScale(graph), minimum = Number((fit * 25).toFixed(2));
  const maximum = Number((Math.max(8 * fit, 2) * 100).toFixed(2));
  assert.ok(minimum < 25);
  await editScale(graph, String(minimum));
  assert.equal(input.getAttribute('aria-invalid'), null);
  assert.ok(Math.abs(actualScale(graph) - minimum / 100) <= .00005 + 1e-10);
  await editScale(graph, String(minimum - .01));
  assert.equal(input.getAttribute('aria-invalid'), 'true');
  await editScale(graph, String(maximum));
  assert.equal(input.getAttribute('aria-invalid'), null);
  assert.ok(Math.abs(actualScale(graph) - maximum / 100) <= .00005 + 1e-10);
  await editScale(graph, String(maximum + .01));
  assert.equal(input.getAttribute('aria-invalid'), 'true');
  await button(graph, 'fit').click();
  const canvas = graph.el.querySelector('.graph-canvas');
  const observer = ui.observers.find(item => item.targets.includes(canvas));
  observer.callback([{target: canvas, contentRect: {width: 220.5, height: 170.25}}]);
  const newFit = actualScale(graph), newMinimum = Number((newFit * 25).toFixed(2));
  assert.ok(newMinimum < minimum); assert.ok(newFit < .25);
  await editScale(graph, '200');
  assert.ok(Math.abs(actualScale(graph) - 2) < 1e-10);
  await editScale(graph, '200.01'); assert.equal(input.getAttribute('aria-invalid'), 'true');
  graph.destroy();
});

test('manual percentages keep their actual scale when scrollbars resize the canvas, while fit remains responsive', async () => {
  const ui = harness(), graph = ui.create({schema: schema(), focus: 'orders'});
  ui.document.body.append(graph.toolbar, graph.el);
  const canvas = graph.el.querySelector('.graph-canvas'), input = scaleInput(graph);
  const observer = ui.observers.find(item => item.targets.includes(canvas));
  const resize = (width, height) => observer.callback([{target: canvas, contentRect: {width, height}}]);
  resize(800.5, 420.25);
  assert.equal(button(graph, 'fit').getAttribute('aria-pressed'), 'true');
  await editScale(graph, input.value);
  assert.equal(button(graph, 'fit').getAttribute('aria-pressed'), 'false', 'typing the fitted percentage selects a fixed scale, not responsive fit');
  await button(graph, 'fit').click();
  assert.equal(button(graph, 'fit').getAttribute('aria-pressed'), 'true');
  const svg = graph.el.querySelector('svg.schema-graph');
  const layout = {width: Number(svg.getAttribute('viewBox').split(' ')[2]), height: Number(svg.getAttribute('viewBox').split(' ')[3])};
  await editScale(graph, '75');
  ui.document.activeElement = input;
  await editScale(graph, '90.5%', 'blur');
  const originalZoom = graph.getView().zoom;
  resize(785.5, 405.25);
  assert.ok(Math.abs(actualScale(graph) - .905) < 1e-12);
  assert.equal(input.value, '90.5'); assert.equal(ui.document.activeElement, input);
  assert.notEqual(graph.getView().zoom, originalZoom, 'the snapshot multiplier must adapt to the new fit scale');
  const fitted = ui.viewport(layout, 785.5, 405.25);
  assert.ok(Math.abs(graph.getView().zoom * fitted.fitScale - .905) < 1e-12);
  for (let index = 0; index < 4; index++) {
    resize(800.5, 420.25); resize(785.5, 405.25);
    assert.ok(Math.abs(actualScale(graph) - .905) < 1e-12); assert.equal(input.value, '90.5');
  }
  await button(graph, 'zoom-in').click(); const buttonScale = actualScale(graph);
  resize(790.5, 410.25); assert.ok(Math.abs(actualScale(graph) - buttonScale) < 1e-12);
  await wheel(canvas, {ctrlKey: true}); const wheelScale = actualScale(graph);
  resize(775.5, 395.25); assert.ok(Math.abs(actualScale(graph) - wheelScale) < 1e-12);
  await button(graph, 'fit').click(); const fitScale = actualScale(graph);
  resize(650.5, 320.25);
  assert.equal(graph.getView().zoom, 1); assert.ok(actualScale(graph) < fitScale);
  assert.equal(button(graph, 'fit').getAttribute('aria-pressed'), 'true');
  assert.equal(graph.el.querySelector('svg.schema-graph'), svg);
  graph.destroy();
});

test('scale drafts survive language changes and composition; empty and destroyed graphs cannot accept edits', async () => {
  const ui = harness(), graph = ui.create({schema: schema()});
  ui.document.body.append(graph.toolbar, graph.el);
  const input = scaleInput(graph), before = JSON.stringify(graph.getView());
  ui.document.activeElement = input;
  await editScale(graph, '123.', {type: 'keydown', key: 'Enter', isComposing: true});
  assert.equal(JSON.stringify(graph.getView()), before); assert.equal(input.value, '123.');
  ui.context.setLanguage('en');
  assert.equal(input.value, '123.'); assert.equal(ui.document.activeElement, input);
  assert.equal(input.getAttribute('aria-label'), 'Graph scale percentage');
  await input.dispatchEvent({type: 'keydown', key: 'Enter'});
  assert.ok(Math.abs(actualScale(graph) - 1.23) < 1e-10);
  graph.destroy(); const destroyedView = JSON.stringify(graph.getView());
  await editScale(graph, '180');
  assert.equal(JSON.stringify(graph.getView()), destroyedView);
  const empty = ui.create({schema: {nodes: [], edges: []}});
  assert.equal(scaleInput(empty).disabled, true); assert.equal(scaleInput(empty).value, '');
  await editScale(empty, '100');
  assert.equal(empty.el.querySelector('svg.schema-graph'), null);
  empty.destroy();
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

test('fractional canvas measurements keep fit and redraw within the scrollport', async () => {
  const {create,observers}=harness();
  const graph=create({schema:schema(),focus:'orders'});
  const canvas=graph.el.querySelector('[data-graph-canvas]');
  const canvasObserver=observers.find(observer=>observer.targets.includes(canvas));
  const resize=(width,height)=>{
    canvas.clientWidth=Math.round(width); canvas.clientHeight=Math.round(height);
    canvasObserver.callback([{target:canvas,contentRect:{width,height}}]);
  };
  const fits=(width,height)=>{
    const stage=canvas.querySelector('.graph-stage');
    assert.ok(parseFloat(stage.style.width)<=width+1e-7,'stage must not create a horizontal scrollbar');
    assert.ok(parseFloat(stage.style.height)<=height+1e-7,'stage must not create a vertical scrollbar');
  };
  // At 150% display scale a 680px bordered canvas has a 678 2/3px content box.
  // Its integer clientHeight is 679; writing that back triggers scrollbar churn.
  resize(1103+1/3,678+2/3);
  fits(1103+1/3,678+2/3);
  await button(graph,'zoom-in').click();
  await button(graph,'fit').click();
  fits(1103+1/3,678+2/3);
  const toggle=graph.el.querySelector('[data-graph-label-toggle]');
  toggle.checked=true; await toggle.dispatchEvent('change');
  fits(1103+1/3,678+2/3);
  resize(643+1/3,388+2/3);
  fits(643+1/3,388+2/3);
  const svg=canvas.querySelector('svg'), before={...svg.style};
  resize(643+1/3,388+2/3);
  assert.deepEqual({...svg.style},before);
  graph.destroy();
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
  assert.ok(Math.abs(Number(after.getAttribute('width'))/Number(after.getAttribute('viewBox').split(' ')[2])-scale)<1e-12);
  assert.ok(Math.abs(canvas.scrollLeft-90)<1e-12);assert.ok(Math.abs(canvas.scrollTop-40)<1e-12);
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

test('overview node selection highlights direct relationships in place and clears the old chain and selected edge', async () => {
  const {create}=harness(),data=schema(),before=structuredClone(data);
  const graph=create({schema:data,focus:'orders'}),canvas=graph.el.querySelector('[data-graph-canvas]');
  const related=()=>graph.el.querySelectorAll('[data-graph-edge]').filter(edge=>edge.classList.contains('path-related')).map(edge=>edge.getAttribute('data-graph-edge')).sort();
  assert.deepEqual(related(),['fk-0','fk-1'],'The overview emphasizes only orders incident edges');
  assert.ok(graph.el.querySelector('[data-graph-node="products"]').classList.contains('path-unrelated'));
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
  assert.deepEqual(highlighted,['cycle','fk-0','fk-1']);
  const issue=graph.el.querySelector('[data-graph-edge="audit-self"]');
  assert.ok(issue.classList.contains('problem'));assert.ok(issue.classList.contains('path-unrelated'));
  assert.equal(issue.getAttribute('data-issue'),'true');
  await issue.click();assert.ok(issue.classList.contains('focused'));
  assert.equal(issue.getAttribute('aria-pressed'),'true');
  assert.equal(graph.el.querySelector('[data-graph-edge="fk-0"]').getAttribute('aria-pressed'),'false');
});

test('overview excludes edges between neighbors while retaining parallel, self and explicit edge emphasis', async () => {
  const {create}=harness(),data=schema();
  data.edges.push({id:'neighbors',source:'users',target:'items',sourceColumns:['id'],targetColumns:['user_id']},
    {id:'parallel',source:'users',target:'orders',sourceColumns:['id'],targetColumns:['owner_id']},
    {id:'self',source:'orders',target:'orders',sourceColumns:['id'],targetColumns:['previous_id']});
  const before=structuredClone(data),graph=create({schema:data,focus:'orders'});
  const related=()=>graph.el.querySelectorAll('[data-graph-edge]').filter(edge=>edge.classList.contains('path-related')).map(edge=>edge.dataset.graphEdge).sort();
  assert.deepEqual(related(),['fk-0','fk-1','parallel','self']);
  for(const id of ['users','items'])assert.ok(graph.el.querySelector(`[data-graph-node="${id}"]`).classList.contains('path-related'));
  const neighborEdge=graph.el.querySelector('[data-graph-edge="neighbors"]');
  assert.ok(neighborEdge.classList.contains('path-unrelated'),'Two related endpoints do not make their edge incident to orders');
  const svg=graph.el.querySelector('.schema-graph'),paths=graph.el.querySelectorAll('.edge-line').map(line=>line.getAttribute('d'));
  await neighborEdge.click();
  assert.ok(neighborEdge.classList.contains('focused'));
  assert.match(neighborEdge.querySelector('.edge-line').getAttribute('marker-end'),/-focused\)$/);
  assert.deepEqual(related(),['fk-0','fk-1','parallel','self']);
  assert.equal(graph.getView().focus,'orders');assert.equal(graph.getView().edgeId,'neighbors');
  assert.equal(graph.el.querySelector('.schema-graph'),svg);
  assert.deepEqual(graph.el.querySelectorAll('.edge-line').map(line=>line.getAttribute('d')),paths);
  assert.deepEqual(data,before);
  graph.destroy();
});

test('dependency paths retain their full closure and explain their emphasis in both languages', async () => {
  const ui=harness(),data=schema(),before=structuredClone(data);
  const graph=ui.create({schema:data,focus:'orders',mode:'paths'});
  const related=()=>graph.el.querySelectorAll('[data-graph-edge]').filter(edge=>edge.classList.contains('path-related')).map(edge=>edge.dataset.graphEdge).sort();
  const legend=graph.el.querySelector('[data-graph-legend]');
  assert.deepEqual(related(),['fk-0','fk-1','fk-2']);
  assert.ok(graph.el.querySelector('[data-graph-node="products"]').classList.contains('path-related'));
  for(const text of ['其他关系','关联路径','选中关系','问题关系'])assert.ok(legend.textContent.includes(text));
  const svg=graph.el.querySelector('.schema-graph');
  ui.context.setLanguage('en');
  assert.ok(legend.textContent.includes('Related paths'));assert.ok(legend.textContent.includes('Selected relationship'));
  assert.equal(graph.el.querySelector('.schema-graph'),svg);
  await button(graph,'all').click();
  assert.deepEqual(related(),['fk-0','fk-1']);
  assert.ok(legend.textContent.includes('Current table relationships'));
  assert.match(graph.el.querySelector('.graph-footer').textContent,/direct relationships/);
  assert.deepEqual(data,before);assert.deepEqual(Array.from(ui.context.missingMessages()),[]);
  graph.destroy();
});

test('issue legends distinguish flagged tables from references without changing table labels or geometry', () => {
  const ui = harness(), data = schema(), before = structuredClone(data);
  data.nodes.find(node => node.id === 'orders').selected = true;
  const baseline = ui.create({schema: data, focus: 'orders'});
  const graph = ui.create({schema: data, focus: 'orders', issues: [{table: 'orders', edge_id: 'fk-0', severity: 'warning'}]});
  ui.document.body.append(graph.toolbar, graph.el);
  const legend = graph.el.querySelector('[data-graph-legend]');
  assert.match(legend.textContent, /检查标记的表/); assert.match(legend.textContent, /问题关系/);
  assert.ok(legend.querySelector('.graph-legend-swatch.blocked'));
  assert.ok(legend.querySelector('.graph-legend-line.problem'));
  const node = graph.el.querySelector('[data-graph-node="orders"]');
  assert.equal(node.querySelector('.graph-table-name').textContent, 'orders');
  assert.ok(node.classList.contains('chosen')); assert.ok(node.classList.contains('blocked'));
  assert.match(node.getAttribute('aria-label'), /本次生成.*不表示数据库中的数据已损坏/);
  assert.match(node.querySelector('title').textContent, /orders.*生成来源或规则检查/);
  const edge = graph.el.querySelector('[data-graph-edge="fk-0"]');
  assert.match(edge.getAttribute('aria-label'), /users.id → orders.users_id.*此引用关系/);
  assert.match(graph.el.querySelector('.graph-footer').textContent, /橙色框.*橙色线.*不表示现有数据已损坏/);
  const geometry = value => value.el.querySelectorAll('.graph-node-body').map(rect => ['x', 'y', 'width', 'height'].map(key => rect.getAttribute(key)));
  assert.deepEqual(geometry(graph), geometry(baseline));
  ui.context.setLanguage('en');
  assert.match(legend.textContent, /Table flagged by a check/);
  assert.match(node.getAttribute('aria-label'), /does not indicate damaged database data/);
  assert.match(edge.getAttribute('aria-label'), /flagged this reference relationship/);
  assert.equal(node.querySelector('.graph-table-name').textContent, 'orders');
  assert.deepEqual(geometry(graph), geometry(baseline));
  assert.deepEqual(data.edges, before.edges);
  assert.deepEqual(Array.from(ui.context.missingMessages()), []);
  baseline.destroy(); graph.destroy();
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

function feedbackHarness(reduced = false) {
  const preference = new Element('media-query'); preference.matches = reduced;
  const window = new Element('window'); window.matchMedia = () => preference;
  const animations = [];
  const ui = harness({window, animate(element, frames, options) {
    const animation = {element, frames, options, cancelled: false, cancel() {this.cancelled = true;}};
    animations.push(animation); return animation;
  }});
  return {...ui, preference, animations};
}

test('explicit graph selections give one local decorative fade while real state, paths and hit geometry update immediately', async () => {
  const ui = feedbackHarness(), data = schema(), before = structuredClone(data), selected = [], inspected = [];
  const graph = ui.create({schema: data, focus: 'orders', initialView: {edgeId: 'fk-0'},
    onSelect: id => selected.push(id), onEdge: edge => inspected.push(edge.id)});
  ui.document.body.append(graph.toolbar, graph.el);
  const svg = graph.el.querySelector('svg.schema-graph');
  const geometry = () => graph.el.querySelectorAll('.edge-line').map(line => line.getAttribute('d'));
  const paths = geometry(); const view = graph.getView();
  assert.equal(ui.animations.length, 0, 'initial and restored selections remain static');
  const products = graph.el.querySelector('[data-graph-node="products"]');
  await products.dispatchEvent('pointerenter'); assert.equal(ui.animations.length, 0);
  await products.click();
  assert.deepEqual(selected, ['products']); assert.equal(graph.getView().focus, 'products');
  assert.equal(products.getAttribute('aria-pressed'), 'true'); assert.equal(graph.getView().edgeId, null);
  const nodeEffect = ui.animations[0];
  assert.equal(nodeEffect.element, products.querySelector('.graph-selection-halo'));
  assert.equal(nodeEffect.element.getAttribute('pointer-events'), 'none');
  assert.equal(nodeEffect.element.getAttribute('aria-hidden'), 'true');
  assert.equal(products.querySelector('.graph-focus-ring').style.opacity, undefined, 'the real focus ring never fades');
  assert.deepEqual(Array.from(nodeEffect.frames, frame => ({...frame})), [{opacity: .28}, {opacity: 0}]);
  assert.equal(nodeEffect.options.duration, 120); assert.equal(nodeEffect.options.iterations, undefined);
  const edge = graph.el.querySelector('[data-graph-edge="fk-2"]');
  await edge.dispatchEvent({type: 'keydown', key: 'Enter'});
  assert.deepEqual(inspected, ['fk-2']); assert.equal(graph.getView().edgeId, 'fk-2');
  assert.equal(edge.getAttribute('aria-pressed'), 'true'); assert.equal(nodeEffect.cancelled, true);
  assert.match(edge.querySelector('.edge-line').getAttribute('marker-end'), /-focused\)/);
  const edgeEffect = ui.animations[1];
  assert.equal(edgeEffect.element, edge.querySelector('.graph-selection-halo'));
  assert.equal(edgeEffect.element.getAttribute('d'), edge.querySelector('.edge-line').getAttribute('d'));
  assert.equal(edgeEffect.element.getAttribute('marker-end'), null, 'arrowheads stay static');
  assert.equal(edgeEffect.element.getAttribute('pointer-events'), 'none');
  assert.equal(edge.querySelector('.edge-hit').getAttribute('vector-effect'), 'non-scaling-stroke');
  await edge.click(); assert.equal(ui.animations.length, 2, 'reselecting the same relationship does not replay feedback');
  assert.equal(graph.el.querySelector('svg.schema-graph'), svg);
  assert.deepEqual(geometry(), paths); assert.equal(graph.getView().zoom, view.zoom);
  assert.equal(graph.getView().pathFocus, view.pathFocus); assert.deepEqual(data, before);
  graph.destroy(); assert.equal(edgeEffect.cancelled, true);
});

test('selection feedback respects reduced motion changes, navigation veto, redraw and graph disposal', async () => {
  const ui = feedbackHarness(true), graph = ui.create({schema: schema(), focus: 'orders', onSelect: id => id !== 'audit'});
  ui.document.body.append(graph.toolbar, graph.el);
  await graph.el.querySelector('[data-graph-node="products"]').click();
  assert.equal(graph.getView().focus, 'products'); assert.equal(ui.animations.length, 0);
  ui.preference.matches = false; await ui.preference.dispatchEvent('change');
  await graph.el.querySelector('[data-graph-node="audit"]').click();
  assert.equal(graph.getView().focus, 'products'); assert.equal(ui.animations.length, 0);
  await graph.el.querySelector('[data-graph-node="users"]').click();
  const first = ui.animations[0];
  await graph.el.querySelector('[data-graph-node="orders"]').click();
  const second = ui.animations[1]; assert.equal(first.cancelled, true);
  first.onfinish();
  ui.preference.matches = true; await ui.preference.dispatchEvent('change');
  assert.equal(second.cancelled, true, 'a stale completion cannot detach the newer animation from cleanup');
  await graph.el.querySelector('[data-graph-edge="fk-0"]').click(); assert.equal(ui.animations.length, 2);
  ui.preference.matches = false; await ui.preference.dispatchEvent('change');
  await graph.el.querySelector('[data-graph-node="products"]').click();
  const third = ui.animations[2];
  await button(graph, 'paths').click(); assert.equal(third.cancelled, true);
  assert.equal(ui.animations.length, 3, 'scope redraws do not animate their initial selection');
  const node = graph.el.querySelector('[data-graph-node="items"]');
  await node.click(); const located = ui.animations[3];
  assert.equal(graph.focusTable('products'), true);
  assert.equal(located.cancelled, true, 'locating another visible table clears the previous selection feedback');
  assert.equal(ui.animations.length, 4, 'programmatic location does not add a new animation');
  await node.click(); const last = ui.animations[4];
  graph.destroy(); assert.equal(last.cancelled, true);
  assert.equal(ui.preference.listeners.get('change').size, 0);
  await node.click(); await ui.preference.dispatchEvent('change'); assert.equal(ui.animations.length, 5);
});


function mountedScope(options = {}) {
  const ui = harness(), data = schema();
  const graph = ui.create({schema: data, focus: 'orders', issues: [{table: 'orders', severity: 'error'}], ...options});
  const group = graph.toolbar.querySelector('.graph-filters');
  const indicator = group.querySelector('.graph-filter-indicator');
  const frames = {
    all: {left: 105.5, top: 55.5, width: 60.5, height: 32},
    paths: {left: 170, top: 55.5, width: 92.75, height: 32},
    issues: {left: 266.75, top: 55.5, width: 74.25, height: 32},
  };
  group.getBoundingClientRect = () => ({left: 100, top: 50, width: 246.5, height: 43});
  group.clientLeft = 1; group.clientTop = 1;
  for (const mode of Object.keys(frames)) button(graph, mode).getBoundingClientRect = () => frames[mode];
  ui.document.body.append(graph.toolbar, graph.el);
  const observer = ui.observers.find(observer => observer.targets.includes(group));
  return {...ui, data, graph, group, indicator, frames, observer};
}

test('scope indicator initially snaps to the restored mode without moving buttons', () => {
  const ui = mountedScope({initialView: {mode: 'paths'}});
  const selected = button(ui.graph, 'paths');
  const buttons = ui.group.querySelectorAll('button');
  const before = buttons.map(control => ({control, text: control.textContent, style: {...control.style}}));
  assert.equal(ui.group.getAttribute('data-indicator-ready'), null);
  ui.observer.callback([{target: ui.group}]);
  assert.equal(ui.group.getAttribute('data-indicator-slide'), 'false');
  assert.equal(ui.indicator.getAttribute('aria-hidden'), 'true');
  assert.equal(ui.indicator.style.transform, 'translate(69px, 4.5px)');
  assert.equal(ui.indicator.style.width, '92.75px');
  assert.equal(ui.indicator.style.height, '32px');
  assert.equal(selected.getAttribute('aria-pressed'), 'true');
  assert.deepEqual(buttons.map(control => ({control, text: control.textContent, style: {...control.style}})), before);
});

test('user scope changes update business state immediately while retaining button identity and focus', async () => {
  const ui = mountedScope(), before = structuredClone(ui.data);
  ui.observer.callback([{target: ui.group}]);
  const paths = button(ui.graph, 'paths');
  ui.document.activeElement = paths;
  await paths.click();
  assert.equal(ui.graph.getView().mode, 'paths');
  assert.deepEqual(nodeIds(ui.graph).sort(), ['items', 'orders', 'products', 'users']);
  assert.equal(button(ui.graph, 'paths'), paths);
  assert.equal(ui.document.activeElement, paths);
  assert.equal(paths.getAttribute('aria-pressed'), 'true');
  assert.equal(button(ui.graph, 'all').getAttribute('aria-pressed'), 'false');
  assert.equal(ui.group.getAttribute('data-indicator-slide'), 'true');
  assert.equal(ui.indicator.style.transform, 'translate(69px, 4.5px)');
  assert.equal(ui.indicator.style.width, '92.75px');
  assert.deepEqual(ui.data, before);
  await button(ui.graph, 'issues').click();
  await button(ui.graph, 'all').click();
  assert.equal(ui.graph.getView().mode, 'all');
  assert.equal(ui.indicator.style.transform, 'translate(4.5px, 4.5px)');
  assert.equal(ui.group.querySelectorAll('[aria-pressed="true"]').length, 1);
  assert.equal(ui.group.querySelector('.graph-filter-indicator'), ui.indicator);
  assert.equal(nodeIds(ui.graph).length, ids.length);
});

test('scope resize and programmatic mode changes snap the indicator without a new animation', async () => {
  const ui = mountedScope(); ui.observer.callback([{target: ui.group}]);
  await button(ui.graph, 'paths').click();
  assert.equal(ui.group.getAttribute('data-indicator-slide'), 'true');
  ui.frames.paths.width = 102.5;
  ui.frames.paths.left = 181.25;
  ui.observer.callback([{target: button(ui.graph, 'paths')}]);
  assert.equal(ui.group.getAttribute('data-indicator-slide'), 'false');
  assert.equal(ui.indicator.style.transform, 'translate(80.25px, 4.5px)');
  assert.equal(ui.indicator.style.width, '102.5px');
  await button(ui.graph, 'all').click();
  await button(ui.graph, 'focus-readable').click();
  assert.equal(ui.graph.getView().mode, 'paths');
  assert.equal(ui.group.getAttribute('data-indicator-slide'), 'false');
  assert.equal(ui.indicator.style.transform, 'translate(80.25px, 4.5px)');
});

test('scope indicator disconnects sizing and ignores late callbacks after graph destruction', async () => {
  const ui = mountedScope(); ui.observer.callback([{target: ui.group}]);
  const before = {...ui.indicator.style};
  ui.graph.destroy();
  assert.equal(ui.observer.disconnected, true);
  ui.frames.all.width = 170;
  ui.observer.callback([{target: ui.group}]);
  await button(ui.graph, 'paths').click();
  assert.deepEqual({...ui.indicator.style}, before);
  assert.equal(ui.graph.getView().mode, 'all');
});

test('arrow markers keep live theme tokens and follow the existing selected and problem edge states', async () => {
  const {create} = harness();
  const graph = create({schema: schema(), focus: 'orders', issues: [{table: 'inventory', severity: 'error'}]});
  const markers = graph.el.querySelectorAll('marker');
  const expected = {normal: 'var(--graph-edge-default, var(--graph-chosen-edge))', related: 'var(--teal)',
    focused: 'var(--graph-inspect)', problem: 'var(--warning)'};
  for (const [state, color] of Object.entries(expected)) {
    assert.equal(markers.find(marker => marker.id.endsWith(`-${state}`)).querySelector('path').getAttribute('fill'), color);
  }
  const edge = graph.el.querySelector('[data-graph-edge="fk-1"]');
  assert.match(edge.querySelector('.edge-line').getAttribute('marker-end'), /-related\)/);
  await edge.click();
  assert.match(edge.querySelector('.edge-line').getAttribute('marker-end'), /-focused\)/);
  const problem = graph.el.querySelector('[data-graph-edge="fk-4"]');
  assert.match(problem.querySelector('.edge-line').getAttribute('marker-end'), /-problem\)/);
  assert.deepEqual(graph.el.querySelectorAll('marker'), markers);
});

test('complex graph arrowheads are independent of emphasis and remain bounded while zooming', async () => {
  const {create}=harness(),data=require('./complex_business_graph.json');
  const graph=create({schema:structuredClone(data),mode:'all',focus:'customers'});
  const svg=graph.el.querySelector('svg'),routes=graph.el.querySelectorAll('.edge-line');
  assert.equal(routes.length,55);
  const paths=routes.map(line=>line.getAttribute('d'));
  const edge=graph.el.querySelectorAll('[data-graph-edge]').find(element=>element.getAttribute('aria-label').includes('payments'));
  const markers=graph.el.querySelectorAll('marker');
  const sizes=()=>markers.map(marker=>[+marker.getAttribute('markerWidth'),+marker.getAttribute('markerHeight')]);
  for(const marker of markers) {
    assert.equal(marker.getAttribute('markerUnits'),'userSpaceOnUse','Stroke width cannot multiply arrow size');
    assert.equal(marker.getAttribute('refX'),'10','Arrow tip stops at the routed node boundary');
  }
  const resting=sizes();await edge.click();assert.deepEqual(sizes(),resting);
  const bounded=()=>{
    const scale=+svg.getAttribute('width') / +svg.getAttribute('viewBox').split(' ')[2];
    for(const [width,height] of sizes()) {
      assert.ok(width*scale<=10.000001 && height*scale<=10.000001);
      assert.ok(Math.abs(width*scale-Math.min(8*scale,10))<0.000001);
    }
  };
  await button(graph,'readable').click();bounded();
  await button(graph,'zoom-out').click();bounded();
  for(let i=0;i<8;i++){await button(graph,'zoom-in').click();bounded();}
  const beforeKeyboard=sizes();await edge.dispatchEvent({type:'keydown',key:'Enter'});assert.deepEqual(sizes(),beforeKeyboard);
  await button(graph,'fit').click();bounded();
  assert.equal(graph.el.querySelector('svg'),svg);
  assert.deepEqual(routes.map(line=>line.getAttribute('d')),paths);
});

test('hover targets stay on fixed hit geometry without changing complex graph routes or viewport', async () => {
  const {create}=harness(),changes=[],data=require('./complex_business_graph.json');
  const graph=create({schema:structuredClone(data),mode:'all',focus:'customers',onViewChange:view=>changes.push(view)});
  const labels=graph.el.querySelector('[data-graph-label-toggle]');labels.checked=true;await labels.dispatchEvent('change');
  const canvas=graph.el.querySelector('.graph-canvas'),svg=graph.el.querySelector('svg');
  const nodes=graph.el.querySelectorAll('[data-graph-node]'),edges=graph.el.querySelectorAll('[data-graph-edge]');
  const geometry=()=>JSON.stringify({viewBox:svg.getAttribute('viewBox'),width:svg.getAttribute('width'),height:svg.getAttribute('height'),
    nodes:nodes.map(node=>{const rect=node.querySelector('.graph-node-body');return ['x','y','width','height'].map(name=>rect.getAttribute(name));}),
    routes:edges.map(edge=>edge.querySelector('.edge-line').getAttribute('d'))});
  const before=geometry(),view=JSON.stringify(graph.getView()),published=changes.length;
  for(const edge of edges) {
    const hit=edge.querySelector('.edge-hit'),line=edge.querySelector('.edge-line');
    assert.equal(hit.getAttribute('vector-effect'),'non-scaling-stroke');
    assert.equal(line.getAttribute('pointer-events'),'none');
    assert.equal(hit.getAttribute('d'),line.getAttribute('d'));
    await canvas.dispatchEvent({type:'pointermove',target:hit,clientX:90,clientY:110});
    await edge.dispatchEvent({type:'pointerenter',target:hit});await edge.dispatchEvent({type:'pointerleave',target:hit});
  }
  for(const node of nodes) {
    assert.equal(node.querySelector('.graph-node-body').getAttribute('pointer-events'),'fill');
    for(const text of node.querySelectorAll('text'))assert.equal(text.getAttribute('pointer-events'),'none');
  }
  for(const label of graph.el.querySelectorAll('[data-graph-label]')) {
    assert.equal(label.querySelector('rect').getAttribute('pointer-events'),'fill');
    assert.equal(label.querySelector('text').getAttribute('pointer-events'),'none');
  }
  assert.equal(geometry(),before);assert.equal(JSON.stringify(graph.getView()),view);assert.equal(changes.length,published);
  await edges[0].dispatchEvent({type:'keydown',key:' '});assert.equal(graph.getView().edgeId,edges[0].dataset.graphEdge);
});

async function wheel(canvas, properties = {}) {
  let prevented = false;
  await canvas.dispatchEvent({type: 'wheel', deltaY: -100, deltaMode: 0, clientX: 300, clientY: 180,
    preventDefault() { prevented = true; }, ...properties});
  return prevented;
}

function graphPoint(graph, x, y) {
  const canvas = graph.el.querySelector('.graph-canvas'), svg = graph.el.querySelector('svg');
  const scale = Number(svg.getAttribute('width')) / Number(svg.getAttribute('viewBox').split(' ')[2]);
  return [(canvas.scrollLeft + x - parseFloat(svg.style.left)) / scale,
    (canvas.scrollTop + y - parseFloat(svg.style.top)) / scale];
}

test('Ctrl and Meta wheel zoom complex relationships around the mouse without redrawing or changing selection', async () => {
  const ui = harness(), changes = [], data = structuredClone(require('./complex_business_graph.json'));
  const before = structuredClone(data);
  const graph = ui.create({schema: data, focus: 'customers', onViewChange: view => changes.push(view)});
  await button(graph, 'readable').click();
  const canvas = graph.el.querySelector('.graph-canvas'), svg = graph.el.querySelector('svg');
  const edge = graph.el.querySelector('[data-graph-edge]'); await edge.click();
  const paths = graph.el.querySelectorAll('.edge-line').map(line => line.getAttribute('d'));
  const nodes = graph.el.querySelectorAll('.graph-node-body').map(rect => ['x', 'y'].map(key => rect.getAttribute(key)));
  canvas.getBoundingClientRect = () => ({left: 83.25, top: 52.5});
  canvas.clientLeft = 1; canvas.clientTop = 1;
  const observer = ui.observers.find(item => item.targets.includes(canvas));
  observer.callback([{target: canvas, contentRect: {width: 799.5, height: 419.75}}]);
  canvas.scrollLeft = 150.25; canvas.scrollTop = 210.5;
  const point = graphPoint(graph, 321.5, 169.25), view = graph.getView(), published = changes.length;
  for (const modifier of ['ctrlKey', 'metaKey']) {
    assert.equal(await wheel(canvas, {[modifier]: true, target: edge.querySelector('.edge-hit'),
      clientX: 83.25 + 1 + 321.5, clientY: 52.5 + 1 + 169.25}), true);
    graphPoint(graph, 321.5, 169.25).forEach((coordinate, index) => assert.ok(Math.abs(coordinate - point[index]) < 1e-8));
  }
  assert.ok(graph.getView().zoom > view.zoom);
  assert.equal(changes.length, published + 2);
  assert.equal(graph.getView().focus, view.focus); assert.equal(graph.getView().edgeId, view.edgeId);
  assert.equal(graph.getView().mode, view.mode); assert.equal(graph.getView().actualSize, false);
  assert.equal(graph.el.querySelector('svg'), svg);
  assert.deepEqual(graph.el.querySelectorAll('.edge-line').map(line => line.getAttribute('d')), paths);
  assert.deepEqual(graph.el.querySelectorAll('.graph-node-body').map(rect => ['x', 'y'].map(key => rect.getAttribute(key))), nodes);
  assert.deepEqual(data, before);
  const hint = graph.el.querySelector(`#${canvas.getAttribute('aria-describedby')}`);
  assert.match(hint.textContent, /Ctrl／⌘＋滚轮.*普通滚轮/);
});

test('ordinary wheel stays native, modifier wheel is confined to the canvas and destroy removes its active listener', async () => {
  const ui = harness(), changes = [], graph = ui.create({schema: schema(), onViewChange: view => changes.push(view)});
  const canvas = graph.el.querySelector('.graph-canvas'), before = JSON.stringify(graph.getView()), published = changes.length;
  assert.equal(await wheel(canvas), false);
  assert.equal(await wheel(canvas, {shiftKey: true}), false);
  assert.equal(await wheel(button(graph, 'zoom-in'), {ctrlKey: true}), false);
  assert.equal(JSON.stringify(graph.getView()), before); assert.equal(changes.length, published);
  const wheelRegistrations = ui.registrations.filter(item => item.type === 'wheel');
  assert.equal(wheelRegistrations.length, 1);
  assert.equal(wheelRegistrations[0].element, canvas); assert.equal(wheelRegistrations[0].options.passive, false);
  assert.equal(canvas.listeners.get('wheel').size, 1);
  graph.destroy(); assert.equal(canvas.listeners.get('wheel').size, 0);
  assert.equal(await wheel(canvas, {ctrlKey: true}), false);
  assert.equal(JSON.stringify(graph.getView()), before); assert.equal(changes.length, published);
});

test('wheel units normalize to pixels and graph zoom remains finite and bounded at both limits', async () => {
  const {create} = harness();
  const make = () => create({schema: schema(), focus: 'orders'});
  const pixel = make(), line = make(), page = make();
  for (const [graph, deltaY, deltaMode] of [[pixel, -48, 0], [line, -3, 1], [page, -48 / 420, 2]]) {
    const canvas = graph.el.querySelector('.graph-canvas');
    await wheel(canvas, {ctrlKey: true, deltaY, deltaMode});
  }
  assert.equal(pixel.getView().zoom, line.getView().zoom);
  assert.equal(pixel.getView().zoom, page.getView().zoom);
  const canvas = pixel.el.querySelector('.graph-canvas'), svg = pixel.el.querySelector('svg');
  for (let index = 0; index < 100; index++) await wheel(canvas, {ctrlKey: true, deltaY: -1e9});
  const max = pixel.getView().zoom, scale = Number(svg.getAttribute('width')) / Number(svg.getAttribute('viewBox').split(' ')[2]);
  assert.ok(Number.isFinite(max)); assert.ok(scale >= 2);
  assert.equal(await wheel(canvas, {ctrlKey: true}), true); assert.equal(pixel.getView().zoom, max);
  for (let index = 0; index < 100; index++) await wheel(canvas, {metaKey: true, deltaY: 1e9});
  assert.equal(pixel.getView().zoom, .25);
  assert.equal(canvas.scrollLeft, 0); assert.equal(canvas.scrollTop, 0);
  const min = JSON.stringify(pixel.getView());
  for (const deltaY of [0, NaN, Infinity]) assert.equal(await wheel(canvas, {ctrlKey: true, deltaY}), true);
  assert.equal(JSON.stringify(pixel.getView()), min);
});

test('modifier wheel never interrupts a captured drag and safely handles an empty graph', async () => {
  const {create} = harness(), graph = create({schema: schema()});
  const canvas = graph.el.querySelector('.graph-canvas'), zoom = graph.getView().zoom;
  await canvas.dispatchEvent({type: 'pointerdown', button: 0, clientX: 100, clientY: 100, pointerId: 1});
  assert.equal(await wheel(canvas, {ctrlKey: true}), true); assert.equal(graph.getView().zoom, zoom);
  await canvas.dispatchEvent({type: 'pointerup', pointerId: 1});
  await wheel(canvas, {ctrlKey: true}); assert.ok(graph.getView().zoom > zoom);
  const empty = create({schema: {nodes: [], edges: []}}), view = JSON.stringify(empty.getView());
  assert.equal(await wheel(empty.el.querySelector('.graph-canvas'), {ctrlKey: true}), true);
  assert.equal(JSON.stringify(empty.getView()), view);
});

test('check issues remains discoverable before and after a clean check without mutating generation inputs', async () => {
  const {create} = harness(), data = schema(), before = structuredClone(data);
  for (const checked of [false, true]) {
    const graph = create({schema: data, checked});
    const issues = button(graph, 'issues');
    assert.equal(Boolean(issues.disabled), false); assert.equal(issues.textContent, '检查问题');
    await issues.click();
    assert.equal(graph.getView().mode, 'issues'); assert.equal(issues.getAttribute('aria-pressed'), 'true');
    assert.deepEqual(nodeIds(graph), []);
    assert.match(graph.el.querySelector('.graph-empty').textContent, checked ? /当前检查没有发现问题.*清空范围/ : /运行依赖检查后/);
    await button(graph, 'all').click(); assert.equal(nodeIds(graph).length, ids.length);
  }
  assert.deepEqual(data, before);
});

test('check issue count includes warnings and locates only structured affected relationships', async () => {
  const {create} = harness(), data = schema();
  const graph = create({schema: data, issues: [{table: 'inventory', severity: 'warning'}, {table: 'orders', severity: 'error'}]});
  assert.equal(button(graph, 'issues').textContent, '检查问题 · 2');
  await button(graph, 'issues').click();
  assert.deepEqual(nodeIds(graph).sort(), ['inventory', 'orders', 'products', 'users']);
  assert.deepEqual(graph.el.querySelectorAll('[data-graph-edge]').map(edge => edge.dataset.graphEdge), ['fk-0', 'fk-4']);
  assert.match(graph.toolbar.querySelector('.graph-scope-note').textContent, /错误和提醒.*清空范围另行检查/);
});
