const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness({locked = false} = {}) {
  const document = createDom();
  document.documentElement = new Element('html');
  document.scrollingElement = document.documentElement;
  document.documentElement.scrollTop = 384;
  document.documentElement.scrollLeft = 27;
  if (locked) document.documentElement.classList.add('wb-scroll-locked');
  const trigger = new Element('button');
  const focus = [];
  trigger.focus = options => { focus.push(options); document.activeElement = trigger; };
  document.body.append(trigger); document.activeElement = trigger;
  const context = loadFrontend('workbench/ui.js', {document});
  return {document, root: document.documentElement, context, trigger, focus};
}

for (const drawer of [false, true]) {
  test(`${drawer ? 'drawer' : 'modal'} locks background scrolling and restores its original position on close`, () => {
    const ui = harness();
    const dialog = ui.context.modal('查看字段', {drawer});
    assert.equal(ui.root.classList.contains('wb-scroll-locked'), true);
    ui.root.scrollTop = 0; ui.root.scrollLeft = 0;
    dialog.close();
    assert.equal(ui.root.classList.contains('wb-scroll-locked'), false);
    assert.equal(ui.root.scrollTop, 384);
    assert.equal(ui.root.scrollLeft, 27);
    assert.equal(ui.document.activeElement, ui.trigger);
    assert.equal(ui.focus.at(-1).preventScroll, true);
    ui.root.scrollTop = 700;
    dialog.close();
    assert.equal(ui.root.scrollTop, 700, 'Closing an already closed dialog cannot move the page');
  });
}

test('replacing a modal leaves the replacement locked and stale close callbacks cannot release it', () => {
  const ui = harness();
  const first = ui.context.modal('预览已选表');
  const second = ui.context.modal('取值规则', {drawer: true});
  assert.equal(ui.document.querySelectorAll('.wb-overlay').length, 1);
  first.close();
  assert.equal(ui.root.classList.contains('wb-scroll-locked'), true);
  second.close();
  assert.equal(ui.root.classList.contains('wb-scroll-locked'), false);
  assert.equal(ui.root.scrollTop, 384);
});

test('a pre-existing page scroll lock survives the modal lifecycle', () => {
  const ui = harness({locked: true});
  const dialog = ui.context.modal('查看字段');
  dialog.close();
  assert.equal(ui.root.classList.contains('wb-scroll-locked'), true);
});

for (const connectionFirst of [false, true]) {
  test(`overlapping connection and rule dialogs restore scrolling only after both close (${connectionFirst ? 'connection' : 'rule'} first)`, () => {
    const ui = harness();
    const rule = ui.context.modal('取值规则', {drawer: true});
    const connectionContext = loadFrontend('workbench/connection.js', {
      document: ui.document, get: async () => ({connections: []}),
    });
    const connection = connectionContext.openConnectionDialog();
    const [first, last] = connectionFirst ? [connection, rule] : [rule, connection];
    first.close();
    assert.equal(ui.root.classList.contains('wb-scroll-locked'), true);
    ui.root.scrollTop = 12;
    last.close();
    assert.equal(ui.root.classList.contains('wb-scroll-locked'), false);
    assert.equal(ui.root.scrollTop, 384);
    assert.equal(ui.root.scrollLeft, 27);
  });
}
