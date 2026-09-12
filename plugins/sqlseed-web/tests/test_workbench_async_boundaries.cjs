const test = require('node:test');
const assert = require('node:assert/strict');
const {harness, deferred, schema} = require('./workbench_harness.cjs');

test('a queued connection change cannot receive the previous mount after document restoration', async () => {
  const ui = harness();
  const nextSchema = deferred();
  ui.routes.set('/api/workbench/connections/B/schema', () => nextSchema.promise);
  const consume = ui.context.consumeAIHandoff;
  let nextMount;
  let navigationQueued = false;
  ui.context.consumeAIHandoff = (...args) => {
    const handoff = consume(...args);
    if (!navigationQueued) {
      navigationQueued = true;
      queueMicrotask(() => {
        ui.leave();
        ui.store.connId = 'B';
        nextMount = ui.mount();
      });
    }
    return handoff;
  };
  try {
    await ui.mount();
    assert.equal(ui.store.connId, 'B');
    assert.equal(ui.root().querySelectorAll('.wb-field-name').length, 0);
    assert.equal(ui.root().textContent, '正在读取数据库结构…');
  } finally {
    ui.leave();
    nextSchema.resolve(schema('B'));
    await nextMount;
  }
});

for (const change of ['leave', 'edit']) {
  test(`AI eligibility completion cannot reopen an assistant after a queued ${change}`, async () => {
    const ui = harness();
    ui.routes.set('/api/workbench/ai/eligibility', () => ({
      schema_hash: 'schema-v1', default_modes: {users: {amount: 'integer'}},
    }));
    await ui.mount();
    const model = ui.modelState();
    model.schema.tables[0].columns[1].default = 7;
    model.putTable({...model.table('users'), enrich: true});
    const modal = ui.context.modal;
    let changeQueued = false;
    ui.context.modal = (...args) => {
      const dialog = modal(...args);
      const close = dialog.close;
      dialog.close = (...closeArgs) => {
        close(...closeArgs);
        if (!changeQueued) {
          changeQueued = true;
          queueMicrotask(() => {
            if (change === 'leave') ui.leave();
            else model.setCount('users', '77');
          });
        }
      };
      return dialog;
    };
    try {
      await ui.button('AI 配置助手').click();
      assert.equal(changeQueued, true);
      assert.equal(ui.document.querySelector('[role="dialog"]'), null);
      if (change === 'edit') assert.equal(model.table('users').count, 77);
    } finally {
      ui.leave();
    }
  });
}
