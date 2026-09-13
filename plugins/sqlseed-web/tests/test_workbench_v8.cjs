const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {harness, plain, deferred} = require('./workbench_harness.cjs');

test('the workbench presents table views and opens rules directly from a field', async () => {
  const ui = harness(); await ui.mount();
  assert.ok(ui.root().querySelector('.workspace'));
  assert.ok(ui.root().querySelector('.wb-sidebar').querySelector('.wb-structure-menu'));
  assert.equal(ui.root().querySelector('.database-toolbar'),null);
  assert.ok(ui.root().querySelector('.scope-summary'));
  assert.ok(ui.button('预览数据',ui.root().querySelector('[role="tablist"]')));
  assert.equal(ui.root().querySelector('.wb-preview-action'),null,'Preview scope belongs inside the dialog');
  assert.ok(ui.button('编辑 YAML'));
  assert.equal(ui.button('编辑 YAML').closest('details'),null,'The complete document editor is directly discoverable');
  assert.ok(ui.button('生成数据').classList.contains('primary'));
  await ui.openRule('amount');
  assert.equal(ui.root().querySelector('.wb-field-details'),null);
  assert.ok(ui.document.querySelector('.wb-rule-editor'));
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'), 'amount');
});

test('rule drawer applies atomically and cancel leaves the document unchanged', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('amount');
  const before = plain(ui.modelState().rule('users', 'amount'));
  assert.ok(ui.document.querySelector('.drawer'));
  const input = ui.document.querySelector('[data-field="max_value"]');
  input.value = '22'; await input.dispatchEvent('input');
  assert.deepEqual(plain(ui.modelState().rule('users', 'amount')), before);
  await ui.button('取消', ui.document).click();
  assert.equal(ui.document.querySelector('.drawer'), null);
  assert.deepEqual(plain(ui.modelState().rule('users', 'amount')), before);
  await ui.openRule('amount');
  const next = ui.document.querySelector('[data-field="max_value"]');
  next.value = '24'; await next.dispatchEvent('input');
  await ui.button('应用规则', ui.document).click();
  assert.equal(ui.modelState().rule('users', 'amount').params.max_value, 24);
  assert.equal(ui.document.querySelector('.drawer'), null);
  assert.equal(ui.modelState().document.tables.length, 0);
});

test('invalid drawer input blocks Apply, but Cancel does not trap table navigation', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('metadata');
  assert.ok(ui.document.querySelector('.drawer'));
  const input = ui.document.querySelector('[data-field="schema"]');
  input.value = '{'; await input.dispatchEvent('input');
  assert.equal(ui.button('应用规则', ui.document).disabled, true);
  assert.equal(ui.modelState().errors.size, 0);
  await ui.button('取消', ui.document).click();
  await ui.root().querySelector('[data-table="orders"]').querySelector('.wb-table-name').click();
  assert.equal(ui.modelState().view.table, 'orders');
});

test('graph fields open the same drawer and preserve the graph when applied', async () => {
  const ui = harness(); await ui.mount();
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  const card = ui.root().querySelectorAll('.wb-field-card').find(node => node.textContent.includes('amount'));
  await card.click();
  assert.ok(ui.document.querySelector('.drawer'));
  assert.equal(ui.modelState().view.page, 'graph');
  await ui.button('应用规则', ui.document).click();
  assert.equal(ui.modelState().view.page, 'graph');
});

test('applying a graph field rule retains search, path depth, zoom, expansion and scroll position', async () => {
  const ui = harness(); await ui.mount();
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  await ui.root().querySelector('[data-graph-action="upstream"]').click();
  const search = ui.root().querySelector('[data-graph-search]');
  search.value = 'amount'; await search.dispatchEvent('input');
  await ui.root().querySelector('[data-graph-action="expand"]').click();
  await ui.root().querySelector('[data-graph-action="zoom-in"]').click();
  const canvas = ui.root().querySelector('[data-graph-canvas]');
  canvas.scrollLeft = 72; canvas.scrollTop = 36; await canvas.dispatchEvent('scroll');
  const before = plain(vm.runInContext('graph.getView()', ui.context));
  assert.equal(before.search, 'amount'); assert.equal(before.pathMode, 'upstream');
  assert.equal(before.expanded, true); assert.ok(before.zoom > 1);
  await ui.root().querySelectorAll('.wb-field-card').find(card => card.textContent.includes('amount')).click();
  await ui.edit('max_value', '22'); await ui.applyRule();
  assert.equal(ui.modelState().rule('users', 'amount').params.max_value, 22);
  assert.deepEqual(plain(vm.runInContext('graph.getView()', ui.context)), before);
  assert.equal(ui.root().querySelector('[data-graph-search]').value, 'amount');
  assert.ok(ui.root().querySelector('[data-graph-canvas]').classList.contains('expanded'));
});

test('an empty generation count in the graph header blocks changing tables and retains the raw input', async () => {
  const ui = harness(); await ui.mount();
  const selection = ui.root().querySelector('[data-table="users"]').querySelector('input');
  selection.checked = true; await selection.dispatchEvent('change');
  await ui.root().querySelector('[data-table="users"]').querySelector('.wb-table-graph').click();
  // Node navigation rebuilds the graph header through syncTableHeading.
  await ui.root().querySelector('[data-graph-node="users"]').click();
  const count = ui.root().querySelector('[aria-label="users 生成数量"]');
  assert.equal(count.disabled, false);
  count.value = ''; await count.dispatchEvent('input');
  assert.equal(ui.modelState().errors.has('count:users'), true);
  await ui.root().querySelector('[data-graph-node="orders"]').click();
  assert.equal(ui.modelState().view.table, 'users');
  assert.equal(ui.root().querySelector('.table-heading').querySelector('h2').textContent, 'users');
  assert.equal(ui.root().querySelector('[aria-label="users 生成数量"]'), count);
  assert.equal(count.value, '');
  assert.equal(ui.modelState().view.invalidCounts.users, '');
  assert.equal(ui.modelState().selected('orders'), false);
});

for (const exit of ['close-summary', 'leave-page']) {
  test(`a pending run response cannot navigate after ${exit}`, async () => {
    const ui = harness(); await ui.mount();
    const model = ui.modelState(); model.toggleTable('users', true);
    model.markSaved({...plain(model.payload('Saved configuration')), id: 'saved-draft', revision: 4, target_key: 'target-A'}, model.epoch);
    ui.routes.set('/api/workbench/check', () => ({
      ok: true, schema_hash: 'schema-v1', config_hash: 'approved-plan', samples: {}, issues: [], order: ['users'], layers: [['users']],
    }));
    const gate = deferred();
    ui.routes.set('/api/workbench/runs', () => gate.promise);
    await ui.button('生成数据').click();
    const submit = ui.button('写入数据库', ui.document);
    assert.ok(submit); assert.equal(submit.disabled, false);
    const pending = submit.click();
    await new Promise(resolve => setImmediate(resolve));
    const request = ui.requests.find(request => request.url === '/api/workbench/runs');
    assert.ok(request, 'the test must reach the real session run request before closing');
    assert.deepEqual(JSON.parse(request.options.body), {
      conn_id: 'A', draft_id: 'saved-draft', revision: 4, schema_hash: 'schema-v1', config_hash: 'approved-plan',
    });
    assert.equal(submit.disabled, true);
    if (exit === 'close-summary') await ui.button('返回调整', ui.document).click();
    else {ui.leave(); ui.location.hash = '#/runs?id=already-selected';}
    const destination = ui.location.hash;
    gate.resolve({id: 'late-run', status: 'queued'}); await pending;
    assert.equal(ui.location.hash, destination);
    assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  });
}

test('a successful partial preview identifies unavailable related samples instead of claiming the whole group is complete', async () => {
  const ui = harness(); await ui.mount();
  ui.modelState().toggleTable('users', true); ui.modelState().toggleTable('orders', true);
  ui.routes.set('/api/workbench/preview', () => ({
    ok: true, schema_hash: 'schema-v1', config_hash: 'preview-plan', preview_complete: false,
    samples: {users: [{amount: 3}]}, order: ['users', 'orders'], layers: [['users'], ['orders']],
    issues: [{code: 'preview_requires_parent', severity: 'warning', table: 'orders', column: 'user_id', source_table: 'users',
      message: '父表当前没有可用值；执行时先填父表，预览无法提供完整关联样例'}],
  }));
  await ui.button('预览数据').click();
  const notice = ui.root().querySelector('.wb-table-preview').textContent;
  assert.match(notice, /部分|关联样例.*父表|父表.*关联样例/);
  assert.doesNotMatch(notice, /整组样例已更新|全部样例已更新|完整样例已更新/);
  assert.equal(ui.modelState().samples.users[0].amount, 3);
  assert.equal(ui.modelState().samples.orders, undefined);
  assert.equal(ui.modelState().previewIssues[0].code, 'preview_requires_parent');
});
