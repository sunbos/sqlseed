const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness({drawer = false} = {}) {
  const document = createDom();
  document.createElement = tag => {
    const node = new Element(tag);
    node.focus = () => { document.activeElement = node; };
    if (tag === 'details') Object.defineProperty(node, 'open', {
      get: () => node.getAttribute('open') !== null,
      set: value => value ? node.setAttribute('open', '') : node.removeAttribute('open'),
    });
    return node;
  };
  const context = loadFrontend('workbench/ui.js', {document});
  const trigger = context.h('button', {}, '打开');
  document.body.append(trigger); trigger.focus();
  const dialog = context.modal('折叠内容', {drawer});
  const close = dialog.header.querySelector('button');
  async function tab(from, shiftKey = false) {
    from.focus();
    let prevented = false;
    await document.dispatchEvent({type: 'keydown', key: 'Tab', shiftKey,
      preventDefault: () => { prevented = true; }});
    return prevented;
  }
  return {document, h: context.h, dialog, close, trigger, tab};
}

for (const drawer of [false, true]) {
  test(`${drawer ? 'drawer' : 'modal'} wraps focus through a closed disclosure summary`, async () => {
    const ui = harness({drawer});
    const summary = ui.h('summary', {}, '高级配置');
    ui.dialog.body.append(ui.h('details', {}, summary, ui.h('p', {}, '说明')));
    assert.equal(await ui.tab(ui.close, true), true);
    assert.equal(ui.document.activeElement, summary);
    assert.equal(await ui.tab(summary), true);
    assert.equal(ui.document.activeElement, ui.close);
    ui.dialog.close();
  });
}

test('closed ancestors exclude their content while nested summaries become reachable after opening', async () => {
  const ui = harness();
  const outerSummary = ui.h('summary', {}, '表字段');
  const innerSummary = ui.h('summary', {}, '受保护字段');
  const action = ui.h('button', {}, '查看规则');
  const inner = ui.h('details', {}, innerSummary, action);
  const outer = ui.h('details', {}, outerSummary, ui.h('input'), inner);
  ui.dialog.body.append(outer);

  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, outerSummary, 'Closed content must not become the modal tab boundary');
  outer.open = true;
  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, innerSummary, 'The inner summary is reachable, but its closed content is not');
  inner.open = true;
  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, action);
  assert.equal(await ui.tab(action), true);
  assert.equal(ui.document.activeElement, ui.close);
  outer.open = false;
  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, outerSummary, 'Closing an ancestor excludes even an open nested disclosure');
  ui.dialog.close();
});

test('only the first direct summary participates in the tab loop', async () => {
  const ui = harness();
  const summary = ui.h('summary', {}, '配置说明');
  const details = ui.h('details', {open: true}, summary, ui.h('summary', {}, '普通内容'));
  ui.dialog.body.append(details, ui.h('summary', {}, '不属于 details 的内容'));
  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, summary);
  ui.dialog.close();
});

test('hidden and disabled controls stay excluded, and closing restores the original focus', async () => {
  const ui = harness();
  const action = ui.h('button', {}, '应用');
  ui.dialog.body.append(action,
    ui.h('details', {hidden: true}, ui.h('summary', {}, '隐藏说明')),
    ui.h('details', {}, ui.h('summary', {tabindex: -1}, '不可 Tab 定位')),
    ui.h('button', {disabled: true}, '不可应用'));
  await ui.tab(ui.close, true);
  assert.equal(ui.document.activeElement, action);
  await ui.document.dispatchEvent({type: 'keydown', key: 'Escape'});
  assert.equal(ui.document.activeElement, ui.trigger);
  assert.equal(ui.trigger.inert, false);
  assert.equal(ui.document.querySelector('.wb-overlay'), null);
  assert.equal(ui.document.listeners.get('keydown').size, 0);
});
