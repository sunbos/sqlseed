const assert = require('node:assert/strict');
const test = require('node:test');
const {harness, schema, deferred, plain} = require('./workbench_harness.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const emptySchema = () => ({...schema('A'), schema_hash:'empty', tables:[], nodes:[], edges:[]});
const emptyPanel = ui => ui.root().querySelector('.wb-empty-schema');

test('an empty database explains the existing workflow and offers direct recovery without generation requests', async () => {
  const ui = harness();
  ui.routes.set('/api/workbench/connections/A/schema', emptySchema);
  await ui.mount();
  assert.match(emptyPanel(ui).textContent, /先在数据库工具中创建表.*重新读取结构/);
  for (const label of ['全选','清空选择','依赖检查','查看生成计划','AI 配置助手']) {
    const control = ui.button(label); assert.ok(control, label); assert.equal(control.disabled, true, label);
    await control.click();
  }
  assert.equal(ui.root().querySelector('[aria-label="查找表"]').disabled, true);
  assert.equal(ui.root().querySelector('.wb-next-step').hidden, true);
  assert.equal(ui.requests.some(request => request.options.method === 'POST'), false);
  const before = plain(ui.modelState().document);
  ui.routes.set('/api/connections', () => ({connections:[]}));
  await ui.button('选择其他数据库', emptyPanel(ui)).click();
  assert.ok(ui.document.querySelector('.connection-modal'));
  assert.deepEqual(plain(ui.modelState().document), before);
  assert.equal(ui.store.connId, 'A');
  await ui.button('取消', ui.document).click();
  ui.leave();
});

test('refreshing an empty schema shares the busy gate and reveals new tables without selecting or generating them', async () => {
  const ui = harness(), gate = deferred();
  ui.routes.set('/api/workbench/connections/A/schema', emptySchema);
  await ui.mount();
  ui.routes.set('/api/workbench/connections/A/schema', () => gate.promise);
  const refresh = ui.button('重新读取结构', emptyPanel(ui));
  const pending = refresh.click(); await tick();
  assert.equal(refresh.disabled, true);
  assert.equal(ui.button('选择其他数据库', emptyPanel(ui)).disabled, true);
  await ui.button('重新读取结构', ui.root().querySelector('.wb-structure-menu')).click();
  assert.equal(ui.requests.filter(request => request.url.endsWith('/schema')).length, 2);
  const next = {...schema('A'), schema_hash:'created'};
  gate.resolve(next); await pending;
  assert.equal(emptyPanel(ui), null);
  assert.equal(ui.modelState().view.table, 'users');
  assert.equal(ui.modelState().document.tables.length, 0);
  assert.ok(ui.root().querySelector('[aria-label="users 生成数量"]'));
  for (const label of ['全选','清空选择','依赖检查','查看生成计划','AI 配置助手']) {
    assert.equal(ui.button(label).disabled, false, label);
  }
  assert.equal(ui.requests.some(request => request.options.method === 'POST'), false);
  ui.leave();
});

test('an empty refresh result preserves disabled prerequisites after busy release and late refresh cannot replace another page', async () => {
  const ui = harness();
  ui.routes.set('/api/workbench/connections/A/schema', emptySchema); await ui.mount();
  await ui.button('重新读取结构', emptyPanel(ui)).click();
  assert.equal(ui.button('依赖检查').disabled, true);
  assert.equal(ui.button('查看生成计划').disabled, true);
  assert.equal(ui.button('重新读取结构', emptyPanel(ui)).disabled, false);
  const gate = deferred(); ui.routes.set('/api/workbench/connections/A/schema', () => gate.promise);
  const pending = ui.button('重新读取结构', emptyPanel(ui)).click(); await tick();
  ui.leave(); ui.store.connId='B'; await ui.mount();
  gate.resolve(schema('A')); await pending;
  assert.equal(ui.modelState().schema.target_key, 'target-B');
  assert.equal(ui.modelState().document.tables.length, 0);
  ui.leave();
});
