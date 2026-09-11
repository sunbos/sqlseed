const test = require('node:test');
const assert = require('node:assert/strict');
const {harness, plain, deferred} = require('./workbench_harness.cjs');

test('empty generation scope explains table selection without checking or showing blockers', async () => {
  const ui = harness(); await ui.mount();
  const before = plain(ui.modelState().document);
  await ui.button('依赖检查').click();
  assert.equal(ui.requests.filter(request => request.url.endsWith('/check')).length, 0);
  const dialog = ui.document.querySelector('[role="dialog"]');
  assert.equal(dialog.getAttribute('aria-label'), '尚未选择生成表');
  assert.match(dialog.textContent, /左侧.*勾选.*表/);
  assert.equal(dialog.querySelector('.wb-dependency-summary'), null);
  assert.equal(dialog.querySelector('.wb-dependency-sources'), null);
  assert.equal(dialog.querySelector('.execution-sequence'), null);
  assert.doesNotMatch(dialog.textContent, /阻断|循环|来源明细/);
  assert.equal(ui.button('生成数据', dialog), undefined);
  assert.ok(ui.button('选择生成表', dialog));
  assert.deepEqual(plain(ui.modelState().document), before);
});

for (const query of ['', 'audit', 'missing']) {
  test(`empty-scope selection action closes the dialog and locates the visible entry: ${query || 'all'}`, async () => {
    const ui = harness(); await ui.mount();
    const search = ui.root().querySelector('input[aria-label="查找表"]');
    search.value = query; await search.dispatchEvent('input');
    const before = plain(ui.modelState().document);
    await ui.button('依赖检查').click();
    const dialog = ui.document.querySelector('[role="dialog"]');
    const locate = ui.button('选择生成表', dialog); assert.ok(locate);
    await locate.click();
    assert.equal(ui.document.querySelector('[role="dialog"]'), null);
    assert.equal(ui.document.activeElement.getAttribute('aria-label'), query === 'missing' ? '查找表' : `生成 ${query || 'users'}`);
    assert.deepEqual(plain(ui.modelState().document), before);
    assert.equal(ui.modelState().epoch, 0);
    assert.equal(ui.root().querySelectorAll('input[type="checkbox"]').some(input => input.checked), false);
    assert.equal(ui.requests.some(request => request.url.endsWith('/check') || request.url.endsWith('/runs')), false);
  });
}

test('empty-scope dialog respects the database operation gate and closes on leaving', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('/api/workbench/preview', () => gate.promise);
  const pending = ui.button('预览数据').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.button('依赖检查').disabled, true);
  await ui.button('依赖检查').click();
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  gate.resolve({ok: true, samples: {users: [{amount: 7}]}, issues: []}); await pending;
  assert.equal(ui.button('依赖检查').disabled, false);
  await ui.button('依赖检查').click();
  const dialog = ui.document.querySelector('[role="dialog"]');
  assert.equal(dialog.getAttribute('aria-label'), '尚未选择生成表');
  ui.leave();
  assert.equal(dialog.isConnected, false);
  assert.equal(ui.requests.filter(request => request.url.endsWith('/check')).length, 0);
});

test('an outdated empty-scope dialog cannot focus controls in a newer page', async () => {
  const ui = harness(); await ui.mount(); await ui.button('依赖检查').click();
  const locate = ui.button('选择生成表', ui.document.querySelector('[role="dialog"]'));
  assert.ok(locate);
  ui.leave(); await ui.mount();
  const search = ui.root().querySelector('input[aria-label="查找表"]'); search.focus();
  await locate.click();
  assert.equal(ui.document.activeElement, search);
  assert.equal(ui.modelState().document.tables.length, 0);
});

test('table path buttons expose pressed state through graph, table, and tab navigation', async () => {
  const ui = harness(); await ui.mount(); const before = plain(ui.modelState().document);
  const states = () => Object.fromEntries(ui.root().querySelectorAll('.wb-table-entry').map(row => [
    row.dataset.table, row.querySelector('.wb-table-graph').getAttribute('aria-pressed'),
  ]));
  assert.deepEqual(states(), {users: 'false', orders: 'false', audit: 'false'});
  await ui.button('orders 的依赖路径').click();
  assert.deepEqual(states(), {users: 'false', orders: 'true', audit: 'false'});
  await ui.root().querySelector('[data-graph-node="users"]').click();
  assert.deepEqual(states(), {users: 'true', orders: 'false', audit: 'false'});
  await ui.button('audit 的依赖路径').click();
  assert.deepEqual(states(), {users: 'false', orders: 'false', audit: 'true'});
  await ui.button('字段规则').click();
  assert.deepEqual(states(), {users: 'false', orders: 'false', audit: 'false'});
  await ui.button('关系图').click();
  assert.deepEqual(states(), {users: 'false', orders: 'false', audit: 'true'});
  await ui.button('预览数据').click();
  assert.deepEqual(states(), {users: 'false', orders: 'false', audit: 'false'});
  assert.deepEqual(plain(ui.modelState().document), before);
});

test('relationship graph JSON tools explain the read-only scope and preserve the export contract', async () => {
  const ui = harness(); await ui.mount(); const downloads = [];
  ui.context.download = (...args) => downloads.push(args);
  const exportButton = ui.button('导出关系图 JSON'); assert.ok(exportButton);
  await exportButton.click();
  const [name, data] = downloads[0], exported = JSON.parse(data), schema = ui.modelState().schema;
  assert.equal(name, 'sqlseed-schema.json');
  assert.deepEqual(exported, {format: 'sqlseed-schema-graph', version: 1, label: schema.target_label, title: schema.target_label,
    nodes: plain(schema.nodes), edges: plain(schema.edges)});
  const before = plain(ui.modelState().document);
  await ui.button('导入关系图 JSON').click();
  const dialog = ui.document.querySelector('[role="dialog"]');
  assert.equal(dialog.getAttribute('aria-label'), '导入关系图 JSON');
  assert.match(dialog.textContent, /只.*浏览.*表.*外键关系/);
  assert.match(dialog.textContent, /不.*创建.*修改数据库/);
  assert.ok(dialog.querySelector('textarea[aria-label="关系图 JSON"]'));
  assert.ok(ui.button('导入关系图', dialog));
  assert.deepEqual(plain(ui.modelState().document), before);
  assert.equal(ui.requests.some(request => request.url.endsWith('/check') || request.url.endsWith('/runs')), false);
});
