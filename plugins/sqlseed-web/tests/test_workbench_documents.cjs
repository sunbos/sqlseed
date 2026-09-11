const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {harness, plain, deferred} = require('./workbench_harness.cjs');
const {createDom} = require('./frontend_helpers.cjs');

const config = count => ({provider: 'base', locale: 'en_US', tables: [{name: 'users', count, columns: []}]});
const graphView = ui => plain(vm.runInContext('graph.getView()', ui.context));
const nodeNames = ui => ui.root().querySelectorAll('[data-graph-node]').map(node => node.getAttribute('data-graph-node')).sort();
const structure = () => ({
  format: 'sqlseed-schema-graph', version: 1, label: '跨部门结构',
  nodes: [{id: 'parents', label: '父表'}, {id: 'children', label: '子表'}],
  edges: [{id: 'compound-fk', source: 'parents', target: 'children',
    sourceColumns: ['tenant_id', 'id'], targetColumns: ['tenant_id', 'parent_id'], nullable: false}],
});
async function editText(ui, label, value) {
  const input = ui.document.querySelector(`[aria-label="${label}"]`);
  assert.ok(input, `Missing ${label}`);
  input.value = value;
  await input.dispatchEvent('input');
  return input;
}
async function importGraph(ui, data) {
  await ui.button('导入关系图 JSON').click();
  await editText(ui, '关系图 JSON', JSON.stringify(data));
  await ui.button('导入关系图', ui.document).click();
}
async function selectUsers(ui) {
  const checkbox = ui.root().querySelector('[data-table="users"]').querySelector('input');
  checkbox.checked = true;
  await checkbox.dispatchEvent('change');
}
async function selectDownloadFormat(ui, format) {
  const control = ui.document.querySelector('[role="combobox"][aria-label="下载格式"]');
  assert.ok(control, 'Download format has a named select control');
  await control.click();
  const option = ui.document.querySelectorAll('.dropdown-item').find(item => item.textContent === format);
  assert.ok(option, `Missing download format ${format}`);
  await option.click();
  assert.equal(ui.document.querySelector('.dropdown-floating'), null);
}

test('the DOM boundary inserts and moves existing toolbar nodes with native parent ordering', () => {
  const document = createDom(), body = document.createElement('section'), other = document.createElement('aside');
  const first = document.createElement('textarea'), next = document.createElement('footer'), toolbar = document.createElement('div');
  body.append(first, next); other.append(toolbar); document.body.append(body, other);
  assert.equal(body.insertBefore(toolbar, first), toolbar);
  assert.deepEqual(body.children, [toolbar, first, next]);
  assert.equal(toolbar.parentNode, body); assert.equal(other.children.length, 0);
  body.insertBefore(next, toolbar);
  assert.deepEqual(body.children, [next, toolbar, first]);
  body.insertBefore(toolbar, toolbar);
  assert.deepEqual(body.children, [next, toolbar, first]);
  body.insertBefore(next, null);
  assert.deepEqual(body.children, [toolbar, first, next]);
  assert.throws(() => other.insertBefore(first, next));
  assert.deepEqual(body.children, [toolbar, first, next]);
});

test('YAML editing separates file tools from the two configuration decisions', async () => {
  const ui=harness();await ui.mount();await ui.button('编辑 YAML').click();
  const dialog=ui.document.querySelector('[role="dialog"]');
  assert.equal(dialog.getAttribute('aria-label'),'编辑 YAML');
  const tools=dialog.querySelector('[aria-label="配置文件工具"]');assert.ok(tools);
  assert.ok(ui.button('读取文件',tools));assert.ok(ui.button('下载配置',tools));
  assert.equal(tools.querySelector('[aria-label="下载格式"]').textContent,'YAML');
  assert.deepEqual(dialog.querySelector('.wb-modal-actions').querySelectorAll('button').map(button=>button.textContent),['取消','应用配置']);
  await selectDownloadFormat(ui,'JSON');
  const control=tools.querySelector('[aria-label="下载格式"]');await control.click();
  assert.ok(ui.document.querySelector('.dropdown-floating'));
  await ui.button('取消',dialog).click();
  assert.equal(ui.document.querySelector('.dropdown-floating'),null,'Closing destroys the portalled format picker');
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/parse')).length,0);
  assert.equal(ui.modelState().document.tables.length,0);
});

test('reading a file changes only visible text and a late read never replaces newer typing',async()=>{
  const ui=harness();await ui.mount();await ui.button('编辑 YAML').click();
  const dialog=ui.document.querySelector('[role="dialog"]'),file=dialog.querySelector('input[type="file"]');
  const input=dialog.querySelector('[aria-label="YAML 或 JSON 配置"]');
  file.files=[{size:25,text:async()=>JSON.stringify(config(27))}];await file.dispatchEvent('change');
  assert.deepEqual(JSON.parse(input.value),config(27));
  assert.equal(ui.modelState().document.tables.length,0);
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/parse')).length,0);
  const gate=deferred();file.files=[{size:30,text:()=>gate.promise}];const pending=file.dispatchEvent('change');
  await editText(ui,'YAML 或 JSON 配置',JSON.stringify(config(99)));
  gate.resolve(JSON.stringify(config(30)));await pending;
  assert.deepEqual(JSON.parse(input.value),config(99));
  assert.equal(ui.modelState().document.tables.length,0);
});

test('a parse response cannot replace newer visible configuration text', async () => {
  const ui = harness(); await ui.mount(); await ui.button('编辑 YAML').click();
  const before = plain(ui.modelState().document);
  const older = JSON.stringify(config(27)), newer = JSON.stringify(config(99));
  await editText(ui, 'YAML 或 JSON 配置', older);
  const gate = deferred(); ui.routes.set('/api/workbench/parse', () => gate.promise);
  const pending = ui.button('应用配置', ui.document).click();
  const input = await editText(ui, 'YAML 或 JSON 配置', newer);
  gate.resolve({document: config(27)}); await pending;
  assert.deepEqual(plain(ui.modelState().document), before);
  assert.equal(input.isConnected, true);
  assert.equal(input.value, newer);
  assert.match(ui.document.querySelector('[role="alert"]').textContent, /文本已变化/);
  ui.routes.set('/api/workbench/parse', options => ({document: JSON.parse(JSON.parse(options.body).text)}));
  await ui.button('应用配置', ui.document).click();
  assert.equal(ui.modelState().table('users').count, 99);
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
});

test('JSON download parses the visible text and exports that document without applying it', async () => {
  const ui = harness(); await ui.mount(); await ui.button('编辑 YAML').click();
  const before = plain(ui.modelState().document), current = config(27), raw = JSON.stringify(current);
  const downloads = []; ui.context.download = (...args) => downloads.push(args);
  await editText(ui, 'YAML 或 JSON 配置', raw);
  ui.routes.set('/api/workbench/parse', options => {
    assert.deepEqual(JSON.parse(options.body), {conn_id: 'A', text: raw});
    return {document: current};
  });
  ui.routes.set('/api/workbench/export', options => {
    assert.deepEqual(JSON.parse(options.body), {conn_id: 'A', document: current});
    return {json: current, yaml: 'tables:\n  - name: users\n    count: 27\n'};
  });
  await selectDownloadFormat(ui, 'JSON');
  await ui.button('下载配置', ui.document).click();
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0][0], 'sqlseed.json');
  assert.deepEqual(JSON.parse(downloads[0][1]), current);
  assert.equal(downloads[0][2], 'application/json');
  assert.deepEqual(plain(ui.modelState().document), before);
});

test('the default YAML download validates current text and leaves configuration unapplied',async()=>{
  const ui=harness();await ui.mount();await ui.button('编辑 YAML').click();
  const before=plain(ui.modelState().document),downloads=[];
  ui.context.download=(...args)=>downloads.push(args);
  const raw='provider: base\ntables:\n  - name: users\n    count: 27\n';
  await editText(ui,'YAML 或 JSON 配置',raw);
  ui.routes.set('/api/workbench/parse',options=>{
    assert.equal(JSON.parse(options.body).text,raw);return {document:config(27)};
  });
  ui.routes.set('/api/workbench/export',options=>{
    assert.deepEqual(JSON.parse(options.body).document,config(27));return {yaml:raw,json:config(27)};
  });
  await ui.button('下载配置',ui.document).click();
  assert.deepEqual(downloads,[['sqlseed.yaml',raw,'application/yaml']]);
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.ok(ui.document.querySelector('[role="dialog"]'));
});

test('invalid configuration text prevents both application and export and restores actions for correction',async()=>{
  const ui=harness();await ui.mount();await ui.button('编辑 YAML').click();
  const before=plain(ui.modelState().document),downloads=[];
  ui.context.download=(...args)=>downloads.push(args);
  await editText(ui,'YAML 或 JSON 配置','tables: [invalid');
  ui.routes.set('/api/workbench/parse',()=>{throw new Error('配置语法错误：缺少右括号');});
  await ui.button('下载配置',ui.document).click();
  assert.equal(downloads.length,0);
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/export')).length,1,'Only the initial document serialization was requested');
  assert.match(ui.document.querySelector('[role="alert"]').textContent,/缺少右括号/);
  assert.equal(ui.button('下载配置',ui.document).disabled,false);
  assert.equal(ui.button('应用配置',ui.document).disabled,false);
  await ui.button('应用配置',ui.document).click();
  assert.deepEqual(plain(ui.modelState().document),before);
  await editText(ui,'YAML 或 JSON 配置',JSON.stringify(config(12)));
  ui.routes.set('/api/workbench/parse',()=>({document:config(12)}));
  await ui.button('应用配置',ui.document).click();
  assert.equal(ui.modelState().table('users').count,12);
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
});

for (const format of ['JSON', 'YAML']) {
  test(`${format} download discards an exported response after the visible text changes`, async () => {
    const ui = harness(); await ui.mount(); await ui.button('编辑 YAML').click();
    const downloads = []; ui.context.download = (...args) => downloads.push(args);
    await editText(ui, 'YAML 或 JSON 配置', JSON.stringify(config(27)));
    ui.routes.set('/api/workbench/parse', () => ({document: config(27)}));
    const gate = deferred(); ui.routes.set('/api/workbench/export', () => gate.promise);
    await selectDownloadFormat(ui, format);
    const pending = ui.button('下载配置', ui.document).click();
    await new Promise(resolve => setImmediate(resolve));
    const exports = ui.requests.filter(request => request.url === '/api/workbench/export');
    assert.equal(exports.length, 2, 'the second export must be in flight before editing');
    assert.deepEqual(JSON.parse(exports[1].options.body).document, config(27));
    const input = await editText(ui, 'YAML 或 JSON 配置', JSON.stringify(config(99)));
    gate.resolve({json: config(27), yaml: 'tables: []'}); await pending;
    assert.equal(downloads.length, 0);
    assert.equal(input.isConnected, true);
    assert.deepEqual(JSON.parse(input.value), config(99));
    assert.equal(ui.modelState().document.tables.length, 0);
  });
}

test('a late configuration-dialog request cannot close a newer edited rule drawer', async () => {
  const ui = harness(); await ui.mount();
  const gate = deferred(); ui.routes.set('/api/workbench/export', () => gate.promise);
  const pending = ui.button('编辑 YAML').click();
  const drawer = await ui.openRule('amount'), input = await ui.edit('max_value', '37');
  gate.resolve({yaml: 'tables: []', json: {tables: []}}); await pending;
  assert.equal(ui.document.querySelector('.drawer'), drawer);
  assert.equal(ui.field('max_value'), input);
  assert.equal(input.value, '37');
  assert.equal(ui.modelState().rule('users', 'amount').params.max_value, 9);
  await ui.applyRule();
  assert.equal(ui.modelState().rule('users', 'amount').params.max_value, 37);
});

test('opening a different saved configuration does not inherit the previous graph search', async () => {
  const ui = harness(); await ui.mount();
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  await editText(ui, '查找表或字段', 'orders');
  assert.equal(graphView(ui).search, 'orders');
  ui.routes.set('/api/workbench/drafts?conn_id=A', () => ({drafts: [{id: 'audit-draft', name: 'Audit config', revision: 1}]}));
  ui.routes.set('/api/workbench/drafts/audit-draft', () => ({
    id: 'audit-draft', name: 'Audit config', revision: 1, target_key: 'target-A', schema_hash: 'schema-v1',
    document: {provider: 'base', locale: 'en_US', tables: [{name: 'audit', count: 20, columns: []}]},
    view_state: {table: 'audit', page: 'graph', graphMode: 'all', pathMode: 'complete', tableDrafts: {}},
  }));
  await ui.button('打开配置').click(); await ui.document.querySelector('.wb-draft-card').click();
  const view = graphView(ui);
  assert.equal(ui.modelState().view.table, 'audit');
  assert.equal(view.focus, 'audit');
  assert.equal(view.mode, 'all');
  assert.equal(view.search, '');
  assert.deepEqual(nodeNames(ui), ['audit', 'orders', 'users']);
  assert.equal(ui.modelState().table('audit').count, 20);
});

test('invalid count veto preserves the model, graph focus, highlight and quantity target together', async () => {
  const ui = harness(); await ui.mount(); await selectUsers(ui);
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  const count = await editText(ui, 'users 生成数量', '0');
  await ui.root().querySelector('[data-graph-node="orders"]').click();
  assert.equal(ui.modelState().view.table, 'users');
  assert.equal(graphView(ui).focus, 'users');
  assert.deepEqual(ui.root().querySelectorAll('[data-current="true"]').map(node => node.getAttribute('data-graph-node')), ['users']);
  assert.equal(ui.root().querySelector('.table-heading').querySelector('h2').textContent, 'users');
  assert.equal(ui.root().querySelector('[aria-label="users 生成数量"]'), count);
  assert.equal(count.value, '0');
  assert.equal(ui.modelState().selected('orders'), false);
});

test('v8 format and label import remains available after returning and remounting without changing generation', async () => {
  const ui = harness(); await ui.mount(); await selectUsers(ui);
  await editText(ui, 'users 生成数量', '12');
  await ui.openRule('amount'); await ui.edit('max_value', '22'); await ui.applyRule();
  const before = plain(ui.modelState().document), target = ui.modelState().schema.target_key;
  await importGraph(ui, structure());
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.match(ui.root().querySelector('.wb-imported-structure').textContent, /跨部门结构/);
  assert.deepEqual(nodeNames(ui), ['children', 'parents']);
  await ui.root().querySelector('[data-graph-edge="compound-fk"]').click();
  const mapping = ui.root().querySelector('.wb-imported-structure').querySelector('.wb-edge-mapping');
  assert.equal(mapping.hidden, false);
  assert.deepEqual(mapping.querySelectorAll('code').map(node => node.textContent), ['tenant_id → tenant_id', 'id → parent_id']);
  assert.deepEqual(plain(ui.modelState().document), before);
  await ui.button('返回当前数据库').click();
  assert.equal(ui.root().querySelector('.wb-imported-structure'), null);
  await ui.button('查看已导入关系图').click();
  assert.deepEqual(nodeNames(ui), ['children', 'parents']);
  ui.leave(); await ui.mount();
  assert.match(ui.root().querySelector('.wb-imported-structure').textContent, /跨部门结构/);
  assert.deepEqual(plain(ui.modelState().document), before);
  assert.equal(ui.modelState().schema.target_key, target);
  assert.equal(ui.requests.some(request => request.url === '/api/workbench/runs'), false);
});

for (const invalid of [
  {name: 'unequal composite column counts', change: value => {value.edges[0].targetColumns = ['parent_id'];}},
  {name: 'non-array source columns', change: value => {value.edges[0].sourceColumns = 'id';}},
  {name: 'empty column names', change: value => {value.edges[0].sourceColumns[0] = ''; }},
  {name: 'unsupported format', change: value => {value.format = 'not-sqlseed';}},
]) {
  test(`structure import rejects ${invalid.name} and keeps the previous structure usable`, async () => {
    const ui = harness(); await ui.mount(); await selectUsers(ui);
    const before = plain(ui.modelState().document);
    await importGraph(ui, structure());
    const graph = ui.root().querySelector('.wb-imported-structure'), invalidData = structure();
    invalid.change(invalidData);
    await importGraph(ui, invalidData);
    assert.ok(ui.document.querySelector('[role="dialog"]'));
    assert.ok(ui.document.querySelector('[role="alert"]').textContent);
    assert.equal(ui.root().querySelector('.wb-imported-structure'), graph);
    await ui.button('关闭', ui.document).click();
    await ui.root().querySelector('[data-graph-edge="compound-fk"]').click();
    assert.equal(graph.querySelector('.wb-edge-mapping').hidden, false);
    assert.deepEqual(nodeNames(ui), ['children', 'parents']);
    assert.deepEqual(plain(ui.modelState().document), before);
  });
}

test('the downloadable structure template imports through the same v8 contract', async () => {
  const ui = harness(); await ui.mount(); await ui.button('导入关系图 JSON').click();
  const before = plain(ui.modelState().document), downloads = [];
  ui.context.download = (...args) => downloads.push(args);
  await ui.button('下载格式模板', ui.document).click();
  assert.equal(downloads.length, 1);
  const template = JSON.parse(downloads[0][1]);
  assert.equal(template.format, 'sqlseed-schema-graph');
  assert.equal(template.version, 1);
  assert.deepEqual(template.edges[0].sourceColumns, ['id']);
  assert.deepEqual(template.edges[0].targetColumns, ['user_id']);
  await editText(ui, '关系图 JSON', downloads[0][1]);
  await ui.button('导入关系图', ui.document).click();
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.deepEqual(nodeNames(ui), ['orders', 'users']);
  assert.deepEqual(plain(ui.modelState().document), before);
});

test('browsing an imported graph cannot overwrite the live configuration graph viewport', async () => {
  const ui = harness(); await ui.mount(); await selectUsers(ui);
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  await ui.root().querySelector('[data-graph-action="upstream"]').click();
  await editText(ui, '查找表或字段', 'amount');
  await ui.root().querySelector('[data-graph-action="zoom-in"]').click();
  const canvas = ui.root().querySelector('[data-graph-canvas]');
  canvas.scrollLeft = 45; canvas.scrollTop = 23; await canvas.dispatchEvent('scroll');
  const beforeView = graphView(ui), beforeDocument = plain(ui.modelState().document);
  await importGraph(ui, structure());
  await editText(ui, '查找表或字段', 'parents');
  await ui.root().querySelector('[data-graph-action="downstream"]').click();
  await ui.root().querySelector('[data-graph-action="zoom-in"]').click();
  await ui.button('返回当前数据库').click();
  assert.deepEqual(graphView(ui), beforeView);
  assert.deepEqual(plain(ui.modelState().document), beforeDocument);
  await ui.button('查看已导入关系图').click();
  assert.deepEqual(nodeNames(ui), ['children', 'parents']);
  assert.deepEqual(plain(ui.modelState().document), beforeDocument);
});
