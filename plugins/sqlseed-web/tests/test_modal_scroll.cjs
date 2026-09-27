const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness({locked = false, getComputedStyle} = {}) {
  const document = createDom();
  document.createElement = tag => {
    const element = new Element(tag);
    element.focus = () => { document.activeElement = element; };
    return element;
  };
  document.documentElement = new Element('html');
  document.scrollingElement = document.documentElement;
  document.documentElement.scrollTop = 384;
  document.documentElement.scrollLeft = 27;
  if (locked) document.documentElement.classList.add('wb-scroll-locked');
  const trigger = new Element('button');
  const focus = [];
  trigger.focus = options => { focus.push(options); document.activeElement = trigger; };
  document.body.append(trigger); document.activeElement = trigger;
  const context = loadFrontend('workbench/ui.js', {document, ...(getComputedStyle ? {getComputedStyle} : {})});
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

test('read-only dialogs expose one header dismissal; closing restores focus without a footer action', async () => {
  const ui = harness();
  const dialog = ui.context.modal('数据库当前数据');
  assert.equal(dialog.actions.querySelectorAll('button').length, 0);
  const close = dialog.header.querySelector('[aria-label="关闭"]');
  assert.equal(ui.document.activeElement, close);
  await close.click();
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.equal(ui.document.activeElement, ui.trigger);
});

test('editing dialogs start at their title, trap keyboard focus and cancel without submitting', async () => {
  const ui = harness();
  let submitted = false, closed = 0;
  const dialog = ui.context.modal('编辑 YAML', { dismiss: 'footer', onClose: () => closed++ });
  const field = ui.document.createElement('textarea');
  dialog.body.append(field);
  const cancel = ui.context.button('取消', dialog.close);
  const apply = ui.context.button('应用', () => { submitted = true; });
  dialog.actions.append(cancel, apply);
  assert.equal(dialog.header.querySelector('button'), null);
  assert.equal(ui.document.activeElement, dialog.header.querySelector('h2'));
  let prevented = 0;
  await ui.document.dispatchEvent({ type: 'keydown', key: 'Tab', preventDefault: () => prevented++ });
  assert.equal(ui.document.activeElement, field);
  field.focus();
  await ui.document.dispatchEvent({ type: 'keydown', key: 'Tab', shiftKey: true, preventDefault() {} });
  assert.equal(ui.document.activeElement, apply);
  assert.equal(prevented, 1);
  await cancel.click();
  assert.equal(submitted, false);
  assert.equal(closed, 1);
  assert.equal(ui.document.activeElement, ui.trigger);
});

test('Escape dismisses an editing dialog once and restores its inert background', async () => {
  const ui = harness();
  const dialog = ui.context.modal('AI 配置助手', { dismiss: 'footer' });
  dialog.actions.append(ui.context.button('取消', dialog.close));
  assert.equal(ui.trigger.inert, true);
  await ui.document.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.equal(ui.trigger.inert, false);
  assert.equal(ui.document.activeElement, ui.trigger);
});

test('current-data scroll region remains in the dialog keyboard sequence instead of jumping to close', async () => {
  const ui = harness();
  const component = loadFrontend('workbench/table-data.js', {
    document: ui.document, AbortController, URLSearchParams,
    modal: ui.context.modal, button: ui.context.button, valueText: ui.context.valueText,
    api: async () => ({table:'users', target_key:'target', target_label:'sample.db', dialect:'sqlite',
      columns:[{name:'id',type:'INTEGER',is_primary_key:true}], rows:[{id:1}], total:102,
      limit:50, offset:0, order_by:['id'], read_at:'2026-09-28T00:00:00Z'})
  });
  const panel = component.openTableData({connId:'connection',table:'users',targetKey:'target'});
  await panel.ready;
  const scroll = ui.document.querySelector('.wb-table-data-scroll');
  assert.ok(scroll); scroll.focus();
  let prevented = false;
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault:()=>{prevented=true;}});
  assert.equal(prevented, false, 'Native Tab must proceed from the table scrollport to the enabled next-page action');
  assert.equal(ui.document.activeElement, scroll);
  await ui.document.querySelector('[aria-label="关闭"]').click();
  assert.equal(ui.document.activeElement, ui.trigger);
});

test('dialog tab boundaries include SVG and explicit tab stops in browser tabindex order', async () => {
  const ui = harness(), dialog = ui.context.modal('关系与数据', {dismiss:'footer'});
  const h = ui.context.h;
  const first = h('button', {tabindex:1}, '第一项'), second = h('button', {tabindex:2}, '第二项');
  const canvas = h('div', {tabindex:0}, '可滚动画布');
  const svgNode = h('g', {tabindex:0, role:'button', 'aria-label':'查看 users'});
  const passive = h('div', {}, '普通说明');
  const disabledGroup = h('fieldset', {disabled:true}, h('button', {}, '继承禁用'));
  const inertGroup = h('section', {inert:true}, h('button', {}, '不可交互'));
  dialog.body.append(second, canvas, first, svgNode, passive, h('div', {tabindex:-1}, '程序焦点'),
    h('button', {disabled:true}, '禁用'), h('input', {type:'hidden'}), h('button', {tabindex:-2}, '负序号'),
    h('section', {hidden:true}, h('button', {}, '隐藏')), disabledGroup, inertGroup);
  let prevented = false;
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault:()=>{prevented=true;}});
  assert.equal(prevented, true); assert.equal(ui.document.activeElement, first);
  first.focus();
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',shiftKey:true,preventDefault(){}});
  assert.equal(ui.document.activeElement, svgNode, 'Last actual stop excludes passive, negative, disabled, hidden and inert nodes');
  canvas.focus(); prevented = false;
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault:()=>{prevented=true;}});
  assert.equal(prevented, false); assert.equal(ui.document.activeElement, canvas);
  svgNode.focus();
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault(){}});
  assert.equal(ui.document.activeElement, first);
  dialog.close(); assert.equal(ui.document.activeElement, ui.trigger);
});

test('dialog tab boundaries follow CSS visibility and preserve the first disabled-fieldset legend controls', async () => {
  const ui = harness({getComputedStyle: element => ({
    display: element.style.display || 'block', visibility: element.style.visibility || 'visible'
  })});
  const dialog = ui.context.modal('表单', {dismiss:'footer'}), h = ui.context.h;
  const firstLegend = h('button', {}, '第一图例入口'), hiddenLegend = h('button', {}, '第二图例入口');
  const last = h('select', {}, h('option', {}, '可选择'));
  const hiddenParent = h('div', {}, h('button', {}, '隐藏容器内'));
  hiddenParent.style.display = 'none';
  const invisible = h('button', {}, '不可见'); invisible.style.visibility = 'hidden';
  dialog.body.append(h('fieldset', {disabled:true}, h('legend', {}, firstLegend),
    h('legend', {}, hiddenLegend), h('input')), last, hiddenParent, invisible);
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault(){}});
  assert.equal(ui.document.activeElement, firstLegend);
  firstLegend.focus();
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',shiftKey:true,preventDefault(){}});
  assert.equal(ui.document.activeElement, last);
  last.focus();
  await ui.document.dispatchEvent({type:'keydown',key:'Tab',preventDefault(){}});
  assert.equal(ui.document.activeElement, firstLegend);
  dialog.close();
});
