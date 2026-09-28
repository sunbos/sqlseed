const assert = require('node:assert/strict');
const test = require('node:test');
const {harness, plain} = require('./workbench_harness.cjs');

for (const ok of [false, true]) {
  test(`dependency group table buttons locate their target without changing the generation document (check ${ok})`, async () => {
    const ui = harness(); await ui.mount();
    const model = ui.modelState();
    model.toggleTable('users', true); model.toggleTable('orders', true);
    ui.routes.set('/api/workbench/check', () => ({ok,
      issues: ok ? [] : [{severity:'error', table:'orders', message:'测试依赖阻断'}],
      layers:[['users'], ['orders']], order:['users', 'orders']
    }));
    const before = plain(model.document);
    await ui.button('依赖检查').click();
    const body = ui.document.querySelector('.modal-body');
    const controls = body.querySelectorAll('.execution-table');
    assert.deepEqual(controls.map(control => control.textContent), ['users', 'orders']);
    assert.ok(controls.every(control => control.classList.contains('btn') && control.classList.contains('small')));
    assert.ok(controls.every(control => control.querySelector('.icon').getAttribute('aria-hidden') === 'true'));
    assert.equal(controls[1].getAttribute('aria-label'), '定位 orders');
    assert.equal(controls[1].querySelector('.execution-table-caption').textContent, 'orders');
    const requests = ui.requests.length;
    ui.context.setLanguage('en');
    assert.equal(controls[1].getAttribute('aria-label'), 'Locate orders');
    assert.equal(controls[1].getAttribute('title'), 'Locate orders');
    assert.equal(controls[1].textContent, 'orders');
    await controls[1].click();
    assert.equal(ui.document.querySelector('.modal'), null);
    assert.equal(model.view.table, 'orders');
    assert.equal(model.view.page, 'graph');
    assert.equal(ui.requests.length, requests);
    assert.deepEqual(plain(model.document), before);
  });
}
