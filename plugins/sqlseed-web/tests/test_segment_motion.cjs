const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness({connected = true, reduced = false, observe = true} = {}) {
  const document = createDom(), window = new Element('window'), preference = new Element('media');
  preference.matches = reduced;
  window.matchMedia = () => preference;
  const observers = [];
  class ResizeObserver {
    constructor(callback) {this.callback = callback; this.nodes = new Set(); observers.push(this);}
    observe(node) {this.nodes.add(node);}
    disconnect() {this.nodes.clear();}
  }
  const context = loadFrontend('segment-motion.js', {document, window,
    ...(observe ? {ResizeObserver} : {}),
    requestAnimationFrame() {throw new Error('Decoration must not delay selection with a frame');},
    setTimeout() {throw new Error('Decoration must not delay selection with a timer');},
  });
  const group = new Element('div');
  group.clientLeft = 2; group.clientTop = 1; group.scrollLeft = 12; group.scrollTop = 4;
  group.getBoundingClientRect = () => ({left:100, top:40, width:450, height:48});
  const boxes = [0, 1, 2].map(index => ({left:110 + index * 120, top:45, width:112, height:38}));
  const buttons = boxes.map((box, index) => {
    const button = new Element('button', `Choice ${index}`);
    button.setAttribute('aria-pressed', String(index === 0));
    button.getBoundingClientRect = () => box;
    button.focus = () => {throw new Error('Decoration must not change keyboard focus');};
    group.append(button); return button;
  });
  if (connected) document.body.append(group);
  const control = context.createSegmentIndicator(group);
  const indicator = group.querySelector('.segment-indicator');
  const select = index => {
    buttons.forEach((button, at) => button.setAttribute('aria-pressed', String(index === at)));
    control.update({animate:true});
  };
  return {document, window, preference, observers, group, boxes, buttons, control, indicator, select};
}

test('first placement accounts for the actual group border and scroll without changing controls', () => {
  const ui = harness();
  assert.equal(ui.indicator.style.transform, 'translate(20px, 8px)');
  assert.equal(ui.indicator.style.width, '112px');
  assert.equal(ui.indicator.style.height, '38px');
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
  assert.equal(ui.indicator.getAttribute('aria-hidden'), 'true');
  assert.deepEqual(ui.group.querySelectorAll('button'), ui.buttons);
  assert.equal(ui.buttons[0].getAttribute('aria-pressed'), 'true');
  assert.equal(ui.observers[0].nodes.size, 4);
});

test('rapid reversals reuse one plate, commit the current target immediately and ignore identical redraws', () => {
  const ui = harness();
  ui.select(2);
  assert.equal(ui.buttons[2].getAttribute('aria-pressed'), 'true');
  assert.equal(ui.indicator.style.transform, 'translate(260px, 8px)');
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'true');
  ui.select(0);
  assert.equal(ui.indicator.style.transform, 'translate(20px, 8px)');
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'true');
  ui.control.update();
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'true', 'same-target redraw must not interrupt the CSS transition');
  assert.equal(ui.group.querySelectorAll('.segment-indicator').length, 1);
  assert.deepEqual(ui.group.querySelectorAll('button'), ui.buttons);
});

test('wrapped, translated and resized controls align directly on both axes', () => {
  const ui = harness();
  ui.select(1);
  Object.assign(ui.boxes[1], {left:110, top:95, width:360, height:54});
  ui.observers[0].callback();
  assert.equal(ui.indicator.style.transform, 'translate(20px, 58px)');
  assert.equal(ui.indicator.style.width, '360px');
  assert.equal(ui.indicator.style.height, '54px');
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
  ui.select(2);
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'true');
});

test('enabling reduced motion immediately ends a running transition and later selections remain immediate', async () => {
  const ui = harness();
  ui.select(1);
  ui.preference.matches = true;
  await ui.preference.dispatchEvent('change');
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
  assert.equal(ui.indicator.style.transform, 'translate(140px, 8px)');
  ui.select(2);
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
  assert.equal(ui.indicator.style.transform, 'translate(260px, 8px)');
});

test('detached and hidden groups keep the normal selected surface, then show directly on first layout', () => {
  const ui = harness({connected:false});
  assert.equal(ui.group.getAttribute('data-segment-ready'), null);
  ui.document.body.append(ui.group);
  ui.select(2);
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
  ui.boxes[2].width = 0;
  ui.control.update();
  assert.equal(ui.group.getAttribute('data-segment-ready'), null);
  ui.boxes[2].width = 112;
  ui.control.update({animate:true});
  assert.equal(ui.group.getAttribute('data-segment-slide'), 'false');
});

test('window resize fallback and idempotent disposal release all listeners and leave selection intact', async () => {
  const ui = harness({observe:false});
  ui.boxes[0].width = 140;
  await ui.window.dispatchEvent('resize');
  assert.equal(ui.indicator.style.width, '140px');
  ui.control.destroy(); ui.control.destroy();
  assert.equal(ui.window.listeners.get('resize').size, 0);
  assert.equal(ui.preference.listeners.get('change').size, 0);
  assert.equal(ui.group.querySelector('.segment-indicator'), null);
  assert.equal(ui.group.classList.contains('segment-motion'), false);
  assert.equal(ui.buttons[0].getAttribute('aria-pressed'), 'true');
  ui.control.update({animate:true});
  assert.equal(ui.group.getAttribute('data-segment-ready'), null);
  const observed = harness(); observed.control.destroy();
  assert.equal(observed.observers[0].nodes.size, 0);
});
