const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Element, createDom} = require('./frontend_helpers.cjs');

// Execute the actual decoration module. Only browser geometry, animation,
// media-query and mutation delivery boundaries are controlled by this harness.
function harness({vertical = false, reduced = false} = {}) {
  const document = createDom(), preference = new Element('media');
  preference.matches = reduced;
  const frames = new Map(), animations = [], observers = [];
  let nextFrame = 0;
  class MutationObserver {
    constructor(callback) {this.callback = callback; observers.push(this);}
    observe() {this.observing = true;}
    disconnect() {this.observing = false;}
  }
  function animate(node, keyframes, options) {
    const animation = {node, keyframes, options, playState:'running', cancelCount:0,
      cancel() {this.cancelCount++; this.playState = 'idle'; this.oncancel?.();},
      finish() {this.playState = 'finished'; this.onfinish?.();}};
    animations.push(animation);
    return animation;
  }
  const createElement = document.createElement;
  document.createElement = tag => {
    const node = createElement(tag);
    node.animate = (keyframes, options) => animate(node, keyframes, options);
    node.getBoundingClientRect = () => node.box || node.parentNode.getBoundingClientRect();
    return node;
  };
  function addGroup(prefix, left = 0) {
    const group = new Element('div');
    group.setAttribute('role', 'tablist');
    if (vertical) group.setAttribute('aria-orientation', 'vertical');
    const tabs = [0, 1, 2].map(index => {
      const tab = document.createElement('button');
      tab.textContent = `Label ${prefix} ${index}`;
      tab.setAttribute('id', `${prefix}-${index}`);
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(index === 0));
      tab.setAttribute('tabindex', index === 0 ? '0' : '-1');
      tab.box = {left:left + (vertical ? 0 : index * 100), top:vertical ? index * 50 : 0,
        width:100, height:40};
      tab.focus = () => {throw new Error('Decoration must not move keyboard focus');};
      group.append(tab);
      return tab;
    });
    document.body.append(group);
    return {group, tabs};
  }
  const primary = addGroup('primary');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/sqlseed_web/static/js/tab-motion.js'), 'utf8'), {
    document, window:{matchMedia:() => preference}, MutationObserver,
    requestAnimationFrame(callback) {frames.set(++nextFrame, callback); return nextFrame;},
    cancelAnimationFrame(id) {frames.delete(id);},
  }, {filename:'tab-motion.js'});
  const capture = (tab, {type = 'click', key} = {}) => document.dispatchEvent({type, key, target:tab,
    preventDefault() {throw new Error('Decoration must not consume activation');},
    stopPropagation() {throw new Error('Decoration must not stop activation');}});
  const commit = tab => {
    const group = tab.closest('[role="tablist"]');
    for (const other of group.querySelectorAll('[role="tab"]')) {
      other.setAttribute('aria-selected', String(other === tab));
      other.setAttribute('tabindex', other === tab ? '0' : '-1');
    }
  };
  return {document, preference, frames, animations, observers, addGroup, ...primary, capture, commit,
    async activate(tab, event) {await capture(tab, event); commit(tab);},
    frame() {const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback());},
    mutations() {for (const observer of observers) if (observer.observing) observer.callback([]);},
    async reduce(matches = true) {preference.matches = matches; await preference.dispatchEvent('change');}};
}

function assertSettled(ui, selected) {
  assert.equal(ui.frames.size, 0);
  assert.equal(ui.document.querySelectorAll('.tab-motion-marker,.tab-motion-surface').length, 0);
  for (const tab of ui.document.querySelectorAll('[role="tab"]')) {
    assert.equal(tab.classList.contains('tab-motion-active'), false);
    assert.equal(tab.classList.contains('tab-motion-surface-active'), false);
  }
  assert.equal(selected.getAttribute('aria-selected'), 'true');
  assert.equal(selected.getAttribute('tabindex'), '0');
}

test('enabling reduced motion cancels a queued cue before the next frame', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]);
  assert.equal(ui.frames.size, 1);
  await ui.reduce();
  assertSettled(ui, ui.tabs[1]);
  ui.frame();
  assert.equal(ui.animations.length, 0);
});

test('the queued frame rechecks reduced motion even before its change event arrives', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]);
  ui.preference.matches = true;
  ui.frame();
  assert.equal(ui.animations.length, 0);
  assertSettled(ui, ui.tabs[1]);
});

for (const vertical of [false, true]) {
  const direction = vertical ? 'vertical' : 'horizontal';
  test(`${direction} feedback stops immediately when reduced motion becomes enabled`, async () => {
    const ui = harness({vertical});
    await ui.activate(ui.tabs[1]); ui.frame();
    assert.equal(ui.animations.length, 1);
    await ui.reduce();
    assert.equal(ui.animations[0].playState, 'idle');
    assertSettled(ui, ui.tabs[1]);
    await ui.activate(ui.tabs[2]); ui.frame();
    assert.equal(ui.animations.length, 1, 'later selection must use its normal static surface');
    assertSettled(ui, ui.tabs[2]);
  });

  test(`${direction} feedback cancels on target removal without waiting for animation completion`, async () => {
    const ui = harness({vertical});
    await ui.activate(ui.tabs[1]); ui.frame();
    const animation = ui.animations[0];
    ui.group.remove(); ui.mutations();
    assert.equal(animation.playState, 'idle');
    assert.equal(ui.tabs[1].children.length, 0);
    assert.equal(ui.tabs[1].classList.contains('tab-motion-active'), false);
    assert.equal(ui.tabs[1].classList.contains('tab-motion-surface-active'), false);
    assert.equal(ui.tabs[1].getAttribute('aria-selected'), 'true');
    assert.equal(ui.observers.some(observer => observer.observing), false);
  });
}

test('vertical feedback decorates an aria-hidden surface without animating the label', async () => {
  const ui = harness({vertical:true});
  const tab = ui.tabs[1], label = tab.textContent;
  await ui.activate(tab); ui.frame();
  const animation = ui.animations[0];
  assert.notEqual(animation.node, tab);
  assert.equal(animation.node.parentNode, tab);
  assert.equal(animation.node.getAttribute('aria-hidden'), 'true');
  assert.equal(animation.node.classList.contains('tab-motion-surface'), true);
  assert.equal(tab.textContent, label);
  assert.equal(tab.style.opacity, undefined);
  animation.finish();
  assertSettled(ui, tab);
});

test('horizontal reversal starts at the painted marker position and cancels the old cue immediately', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]); ui.frame();
  const first = ui.animations[0], oldFinish = first.onfinish;
  // The real marker sits at the bottom of the tab. Its top must not make a
  // horizontal reversal look like a switch between vertically stacked tabs.
  first.node.box = {left:42, top:38, width:96, height:2};
  await ui.activate(ui.tabs[0]);
  assert.equal(first.playState, 'idle');
  assert.equal(first.node.isConnected, false);
  assert.equal(ui.tabs[1].classList.contains('tab-motion-active'), false);
  ui.frame();
  const second = ui.animations[1];
  assert.equal(second.node.classList.contains('tab-motion-marker'), true);
  assert.equal(second.keyframes[0].transform, 'translateX(42px)');
  assert.equal(second.keyframes[0].width, '96px');
  oldFinish?.();
  assert.equal(second.playState, 'running', 'a late completion must not cancel the replacement');
  assert.equal(second.node.isConnected, true);
  second.finish();
  assertSettled(ui, ui.tabs[0]);
});

test('vertical reversals cancel the previous surface before scheduling the replacement', async () => {
  const ui = harness({vertical:true});
  await ui.activate(ui.tabs[1]); ui.frame();
  const first = ui.animations[0];
  await ui.activate(ui.tabs[0]);
  assert.equal(first.playState, 'idle');
  assert.equal(ui.tabs[1].children.length, 0);
  ui.frame();
  assert.equal(ui.animations.length, 2);
  assert.equal(ui.animations[1].node.parentNode, ui.tabs[0]);
  ui.animations[1].finish();
  assertSettled(ui, ui.tabs[0]);
});

test('several activations within one frame animate only the final selection', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]);
  await ui.activate(ui.tabs[2]);
  await ui.activate(ui.tabs[0]);
  assert.equal(ui.frames.size, 1);
  assert.equal(ui.tabs[0].getAttribute('aria-selected'), 'true');
  assert.equal(ui.tabs[2].getAttribute('aria-selected'), 'false');
  ui.frame();
  assert.equal(ui.animations.length, 1);
  assert.equal(ui.animations[0].node.parentNode, ui.tabs[0]);
  assert.equal(ui.animations[0].keyframes[0].transform, 'translateX(200px)');
});

test('repeated activation settles existing feedback without replaying it', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]); ui.frame();
  await ui.activate(ui.tabs[1]);
  assert.equal(ui.animations[0].playState, 'idle');
  assertSettled(ui, ui.tabs[1]);
  ui.frame();
  assert.equal(ui.animations.length, 1);
});

test('removing a pending target cancels its frame and releases observation', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]);
  ui.tabs[1].remove(); ui.mutations();
  assert.equal(ui.frames.size, 0);
  assert.equal(ui.observers.some(observer => observer.observing), false);
  ui.frame();
  assert.equal(ui.animations.length, 0);
});

test('removing only the decoration restores the selected tab immediately', async () => {
  const ui = harness();
  await ui.activate(ui.tabs[1]); ui.frame();
  ui.animations[0].node.remove(); ui.mutations();
  assert.equal(ui.animations[0].playState, 'idle');
  assertSettled(ui, ui.tabs[1]);
});

test('independent groups use their own selected geometry during rapid switches', async () => {
  const ui = harness(), secondGroup = ui.addGroup('second', 500);
  await ui.activate(ui.tabs[1]); ui.frame();
  ui.animations[0].node.box = {left:42, top:38, width:96, height:2};
  await ui.activate(secondGroup.tabs[1]);
  assert.equal(ui.animations[0].playState, 'idle');
  ui.frame();
  assert.equal(ui.animations[1].node.parentNode, secondGroup.tabs[1]);
  assert.equal(ui.animations[1].keyframes[0].transform, 'translateX(-100px)');
  assert.equal(ui.animations[1].keyframes[0].width, '100px');
  assert.equal(ui.tabs[1].getAttribute('aria-selected'), 'true');
  assert.equal(secondGroup.tabs[1].getAttribute('aria-selected'), 'true');
});

test('manual keyboard exploration has no selection, focus or animation side effects', async () => {
  const ui = harness();
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
    await ui.capture(ui.tabs[1], {type:'keydown', key});
  }
  assert.equal(ui.tabs[0].getAttribute('aria-selected'), 'true');
  assert.equal(ui.tabs[1].getAttribute('aria-selected'), 'false');
  assert.equal(ui.frames.size, 0);
  assert.equal(ui.animations.length, 0);
  await ui.capture(ui.tabs[1], {type:'keydown', key:'Enter'});
  assert.equal(ui.tabs[0].getAttribute('aria-selected'), 'true', 'capture cannot own the caller selection');
  ui.commit(ui.tabs[1]);
  assert.equal(ui.tabs[1].getAttribute('aria-selected'), 'true');
  assert.equal(ui.animations.length, 0, 'semantic state is final before decorative work starts');
  ui.frame();
  assert.equal(ui.animations.length, 1);
});

test('a rejected activation does not decorate an unselected target', async () => {
  const ui = harness();
  await ui.capture(ui.tabs[1]); ui.frame();
  assert.equal(ui.animations.length, 0);
  assertSettled(ui, ui.tabs[0]);
});

test('a synchronous caller redraw preserves the cue on the replacement selected tab', async () => {
  const ui = harness();
  await ui.capture(ui.tabs[1]);
  ui.group.remove();
  const replacement = ui.addGroup('primary');
  ui.commit(replacement.tabs[1]); ui.mutations(); ui.frame();
  assert.equal(ui.animations.length, 1);
  assert.equal(ui.animations[0].node.parentNode, replacement.tabs[1]);
  assert.equal(ui.tabs[1].children.length, 0);
});
