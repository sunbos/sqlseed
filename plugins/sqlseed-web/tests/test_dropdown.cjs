const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness(rect = {top: 540, bottom: 580, left: 330, right: 790, width: 460}, settings = {}) {
  const document = createDom(), window = {
    listeners: new Map(),
    addEventListener: Element.prototype.addEventListener,
    removeEventListener: Element.prototype.removeEventListener,
    dispatchEvent: Element.prototype.dispatchEvent,
  };
  const scrolls = [], created = [], createElement = document.createElement;
  document.createElement = tag => {
    const element = createElement(tag);
    created.push(element);
    element.scrollIntoView = () => scrolls.push({text: element.textContent, position: element.parentNode?.parentNode?.style.position || element.parentNode?.style.position});
    return element;
  };
  const overlay = new Element('div'); overlay.className = 'overlay';
  const modal = new Element('section'); modal.setAttribute('role', 'dialog');
  const body = new Element('div'); body.className = 'modal-body';
  document.body.append(overlay); overlay.append(modal); modal.append(body);
  let now = 0;
  class ClockDate extends Date {static now() {return now;}}
  const context = loadFrontend('dropdown.js', {document, window, innerWidth: 1144, innerHeight: 872, Date: ClockDate});
  const changes = [];
  const dropdown = context.createDropdown({value: 'en', label: '数据语言', options: [{value: 'zh', label: '中文'}, {value: 'en', label: 'English'}],
    onChange: value => changes.push(value), ...settings});
  body.append(dropdown.el);
  const button = dropdown.el.querySelector('button'), panel = dropdown.el.querySelector('.dropdown-panel');
  button.getBoundingClientRect = () => rect;
  dropdown.el.getBoundingClientRect = () => rect;
  const popup = created.find(element => element.classList.contains('dropdown-popup'));
  const controls = popup.querySelectorAll('.dropdown-scroll-button');
  panel.scrollHeight = 258;
  panel.getBoundingClientRect = () => ({height: 260});
  popup.getBoundingClientRect = () => panel.getBoundingClientRect();
  Object.defineProperty(panel, 'clientHeight', {get: () => Math.max(0,
    (Number.parseFloat(popup.style.maxHeight) || 260) - 2 - (controls.some(control => !control.hidden) ? 22 : 0))});
  let scrollTop = 0;
  Object.defineProperty(panel, 'scrollTop', {
    get: () => scrollTop,
    set: value => {scrollTop = Math.max(0, Math.min(Number(value) || 0, panel.scrollHeight - panel.clientHeight));},
  });
  button.focus = () => {document.activeElement = button;};
  const key = async (value, extra = {}) => {
    const event = {type: 'keydown', key: value, target: button, defaultPrevented: false, stopped: false,
      preventDefault() {this.defaultPrevented = true;}, stopImmediatePropagation() {this.stopped = true;}, ...extra};
    await (button.getAttribute('aria-expanded') === 'true' ? document : button).dispatchEvent(event);
    return event;
  };
  const active = () => document.getElementById(button.getAttribute('aria-activedescendant'));
  return {document, window, context, overlay, modal, body, dropdown, button, panel, popup, controls, changes, key, active, scrolls, advance: ms => {now += ms;}};
}

test('an implicit wrapper name follows its localized caption without lagging a language behind', async () => {
  const ui=harness(undefined,{label:undefined});
  ui.context.registerMessages('dropdownTest',{caption:['字段类型','Field type']});
  const wrapper=ui.context.h('label',{},ui.context.tr('dropdownTest.caption'),ui.dropdown.el);
  ui.body.append(wrapper);
  await ui.button.dispatchEvent('focus');
  assert.equal(ui.button.getAttribute('aria-label'),'字段类型');
  ui.context.setLanguage('en');
  assert.equal(ui.button.getAttribute('aria-label'),'Field type');
  ui.context.setLanguage('zh-CN');
  assert.equal(ui.button.getAttribute('aria-label'),'字段类型');
  assert.equal(ui.dropdown.get(),'en');
  assert.deepEqual(ui.changes,[]);
  ui.dropdown.destroy();
});

test('options escape a scroll-clipped modal body and selection still updates the control', async () => {
  const ui = harness();
  await ui.button.click();
  assert.equal(ui.popup.parentNode, ui.overlay);
  assert.equal(ui.panel.parentNode, ui.popup);
  assert.equal(ui.popup.style.position, 'fixed');
  assert.equal(ui.popup.style.top, '585px');
  assert.equal(ui.popup.style.width, '460px');
  assert.equal(ui.button.getAttribute('aria-expanded'), 'true');
  await ui.panel.querySelector('button').click();
  assert.equal(ui.dropdown.get(), 'zh');
  assert.deepEqual(ui.changes, ['zh']);
  assert.equal(ui.panel.parentNode, ui.dropdown.el);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
});

test('a menu near the bottom opens above the control and stays within the viewport', async () => {
  const ui = harness({top: 790, bottom: 830, left: 900, right: 1300, width: 400});
  await ui.button.click();
  assert.equal(ui.popup.style.top, '525px');
  assert.equal(ui.popup.style.left, '736px');
  assert.ok(Number.parseFloat(ui.popup.style.maxHeight) <= 260);
});

test('a short menu fits its fractional border box instead of clipping to scrollHeight', async () => {
  const ui = harness({top: 790, bottom: 830, left: 330, right: 790, width: 460});
  ui.panel.scrollHeight = 126;
  ui.panel.getBoundingClientRect = () => ({height: 127.667});
  await ui.button.click();
  assert.equal(ui.popup.style.maxHeight, '128px');
  assert.equal(ui.popup.style.top, '657px');
});

test('menu height is measured at the viewport-constrained width before positioning', async () => {
  const ui = harness({top: 790, bottom: 830, left: 0, right: 1500, width: 1500});
  ui.panel.scrollHeight = 70;
  ui.panel.getBoundingClientRect = () => ({height: ui.popup.style.width === '1128px' ? 150.5 : 70});
  await ui.button.click();
  assert.equal(ui.popup.style.left, '8px');
  assert.equal(ui.popup.style.width, '1128px');
  assert.equal(ui.popup.style.maxHeight, '151px');
  assert.equal(ui.popup.style.top, '634px');
});

test('window resize repositions an open menu without treating Window as a DOM Node', async () => {
  const ui = harness();
  const contains = ui.popup.contains.bind(ui.popup);
  // Native Node.contains rejects a Window; the generic DOM helper is permissive.
  ui.popup.contains = target => {
    if (target !== null && !(target instanceof Element)) {
      throw new TypeError("Failed to execute 'contains' on 'Node': parameter 1 is not of type 'Node'.");
    }
    return contains(target);
  };
  try {
    await ui.button.click();
    ui.panel.scrollTop = 40;
    const scrollTop = ui.panel.scrollTop;
    const active = ui.active();
    const options = ui.panel.querySelectorAll('[role="option"]');
    ui.context.innerWidth = 600;
    ui.context.innerHeight = 700;

    await ui.window.dispatchEvent('resize');

    assert.equal(ui.popup.style.left, '132px');
    assert.equal(ui.popup.style.top, '275px');
    assert.equal(ui.popup.style.width, '460px');
    assert.equal(ui.button.getAttribute('aria-expanded'), 'true');
    assert.equal(ui.popup.parentNode, ui.overlay);
    assert.equal(ui.panel.parentNode, ui.popup);
    assert.equal(ui.active(), active);
    assert.equal(ui.panel.scrollTop, scrollTop);
    for (const [index, option] of options.entries()) {
      assert.equal(ui.panel.querySelectorAll('[role="option"]')[index], option);
    }
    assert.equal(ui.dropdown.get(), 'en');
    assert.equal(ui.document.activeElement, ui.button);
    assert.deepEqual(ui.changes, []);
  } finally {
    ui.dropdown.destroy();
  }
});

test('Escape closes only the open menu and restores control focus', async () => {
  const ui = harness(); let focused = false, stopped = false;
  ui.button.focus = () => {focused = true;};
  await ui.button.click();
  await ui.document.dispatchEvent({type: 'keydown', key: 'Escape', stopImmediatePropagation() {stopped = true;}});
  assert.equal(ui.dropdown.el.classList.contains('open'), false);
  assert.equal(stopped, true); assert.equal(focused, true);
});

test('outside focus, destruction and detached controls remove the floating menu and listeners', async () => {
  const ui = harness();
  await ui.button.click();
  await ui.document.dispatchEvent({type: 'focusin', target: ui.document.body});
  assert.equal(ui.panel.parentNode, ui.dropdown.el);
  await ui.button.click(); ui.dropdown.el.remove();
  await ui.window.dispatchEvent('resize');
  assert.equal(ui.overlay.querySelector('.dropdown-panel'), null);
  assert.equal(ui.window.listeners.get('resize').size, 0);
  assert.equal(ui.document.listeners.get('scroll').size, 0);
  ui.body.append(ui.dropdown.el); await ui.button.click(); ui.dropdown.destroy();
  assert.equal(ui.overlay.querySelector('.dropdown-panel').parentNode, ui.dropdown.el);
  assert.equal(ui.document.listeners.get('keydown').size, 0);
});

test('combobox has a name, controlled listbox and one keyboard tab stop', async () => {
  const ui = harness();
  assert.equal(ui.button.getAttribute('role'), 'combobox');
  assert.equal(ui.button.getAttribute('aria-haspopup'), 'listbox');
  assert.equal(ui.button.getAttribute('aria-label'), '数据语言');
  assert.equal(ui.button.getAttribute('tabindex'), '0');
  assert.equal(ui.panel.getAttribute('role'), 'listbox');
  assert.equal(ui.button.getAttribute('aria-controls'), ui.panel.id);
  await ui.button.click();
  const options = ui.panel.querySelectorAll('[role="option"]');
  assert.equal(options.length, 2);
  assert.ok(options.every(option => option.getAttribute('tabindex') === '-1'));
  assert.equal(options.filter(option => option.getAttribute('aria-selected') === 'true').length, 1);
  assert.equal(ui.active().textContent, 'English');
  assert.equal(ui.document.activeElement, ui.button);
});

test('arrow and boundary navigation explore choices without committing until Enter', async () => {
  const ui = harness(undefined, {options: [{value: 'zh', label: '中文'}, {value: 'en', label: 'English'}, {value: 'ja', label: '日本語'}]});
  assert.ok((await ui.key('ArrowDown')).defaultPrevented);
  assert.equal(ui.active().textContent, 'English');
  await ui.key('ArrowDown'); assert.equal(ui.active().textContent, '日本語');
  await ui.key('ArrowDown'); assert.equal(ui.active().textContent, '日本語');
  await ui.key('Home'); assert.equal(ui.active().textContent, '中文');
  await ui.key('End'); assert.equal(ui.active().textContent, '日本語');
  assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
  assert.equal(ui.button.querySelector('.dropdown-btn-label').textContent, 'English');
  assert.equal(ui.panel.querySelector('[aria-selected="true"]').textContent, 'English');
  assert.equal(ui.active().getAttribute('aria-selected'), 'false');
  assert.equal(ui.active().classList.contains('active'), true);
  await ui.key('Enter');
  assert.equal(ui.dropdown.get(), 'ja'); assert.deepEqual(ui.changes, ['ja']);
  assert.equal(ui.button.getAttribute('aria-activedescendant'), null);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  await ui.button.click();
  assert.equal(ui.panel.querySelector('[aria-selected="true"]').textContent, '日本語');
  assert.equal(ui.active().getAttribute('aria-selected'), 'true');
});

test('disabled options expose their state and are skipped by navigation and typeahead', async () => {
  const ui = harness(undefined, {options: [{value: 'en', label: 'English'}, {value: 'es', label: 'Español', disabled: true}, {value: 'ja', label: '日本語'}]});
  await ui.key('ArrowDown');
  const disabled = ui.panel.querySelectorAll('[role="option"]')[1];
  assert.equal(disabled.getAttribute('aria-disabled'), 'true');
  assert.equal(disabled.getAttribute('aria-selected'), 'false');
  await ui.key('ArrowDown'); assert.equal(ui.active().textContent, '日本語');
  await ui.key('ArrowUp'); assert.equal(ui.active().textContent, 'English');
  await ui.key('e'); await ui.key('s'); assert.equal(ui.active().textContent, 'English');
  await disabled.click(); assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
});

test('Escape discards only pending navigation and restores the committed value and trigger focus', async () => {
  const ui = harness(); await ui.key('Home');
  assert.equal(ui.active().textContent, '中文');
  const event = await ui.key('Escape');
  assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
  assert.equal(ui.document.activeElement, ui.button);
  assert.equal(event.defaultPrevented, true); assert.equal(event.stopped, true);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
});

test('Tab accepts the pending option and leaves default focus movement available', async () => {
  const ui = harness(); await ui.key('Home');
  const event = await ui.key('Tab');
  assert.equal(event.defaultPrevented, false);
  assert.equal(ui.dropdown.get(), 'zh'); assert.deepEqual(ui.changes, ['zh']);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.panel.parentNode, ui.dropdown.el);
});

test('Space opens and confirms while focusing the control alone never opens or changes it', async () => {
  const ui = harness(); await ui.button.dispatchEvent('focus');
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false'); assert.deepEqual(ui.changes, []);
  assert.ok((await ui.key(' ')).defaultPrevented);
  await ui.key('Home'); await ui.key(' ');
  assert.equal(ui.dropdown.get(), 'zh'); assert.deepEqual(ui.changes, ['zh']);
});

test('typeahead supports prefix matching, repeated-letter cycling and timeout without eager value changes', async () => {
  const ui = harness(undefined, {options: [{value: 'en', label: 'English'}, {value: 'eo', label: 'Esperanto'}, {value: 'es', label: 'Español'}]});
  await ui.key('e'); assert.equal(ui.active().textContent, 'Esperanto');
  await ui.key('e'); assert.equal(ui.active().textContent, 'Español');
  ui.advance(1000);
  await ui.key('e'); await ui.key('n'); assert.equal(ui.active().textContent, 'English');
  assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
  await ui.key('Escape');
});

test('updated options reset stale active ids without changing values and all-disabled lists stay inert', async () => {
  const ui = harness(); await ui.key('Home');
  ui.dropdown.setOptions([{value: 'fr', label: 'Français'}]);
  assert.equal(ui.active().textContent, 'Français');
  assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
  ui.dropdown.setOptions([{value: 'fr', label: 'Français', disabled: true}]);
  assert.equal(ui.button.getAttribute('aria-activedescendant'), null);
  await ui.key('Home'); await ui.key('Enter');
  assert.equal(ui.dropdown.get(), 'en'); assert.deepEqual(ui.changes, []);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
});

test('active keyboard option is scrolled into view and separate controls have distinct ids', async () => {
  const ui = harness(); await ui.key('ArrowDown');
  let scrolled = false;
  ui.panel.querySelector('[role="option"]').scrollIntoView = () => {scrolled = true;};
  await ui.key('Home'); assert.equal(scrolled, true);
  const other = ui.context.createDropdown({label: '其他选择', options: [{value: 'a', label: 'A'}]});
  assert.notEqual(other.el.querySelector('.dropdown-btn').getAttribute('aria-controls'), ui.panel.id);
});

test('existing caller labels take precedence and container labels name generic controls on focus', async () => {
  const ui = harness(); ui.button.setAttribute('aria-label', '样例范围');
  await ui.button.dispatchEvent('focus'); await ui.key('ArrowDown');
  assert.equal(ui.button.getAttribute('aria-label'), '样例范围');
  ui.dropdown.destroy();
  const other = ui.context.createDropdown({options: [{value: 'a', label: 'A'}]});
  other.el.setAttribute('aria-label', '生成方式'); ui.body.append(other.el);
  await other.el.querySelector('.dropdown-btn').dispatchEvent('focus');
  assert.equal(other.el.querySelector('.dropdown-btn').getAttribute('aria-label'), '生成方式');
});

test('opening scrolls the active option only after the portal has been positioned', async () => {
  const ui = harness(); await ui.key('ArrowDown');
  assert.ok(ui.scrolls.length > 0);
  assert.ok(ui.scrolls.every(scroll => scroll.position === 'fixed'));
});

test('a detached or destroyed trigger cannot create an orphan portal or register listeners', async () => {
  const ui = harness(); ui.dropdown.el.remove(); await ui.button.click();
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.overlay.querySelector('.dropdown-floating'), null);
  assert.equal(ui.window.listeners.get('resize')?.size || 0, 0);
  ui.body.append(ui.dropdown.el); ui.dropdown.destroy(); await ui.button.click();
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.document.listeners.get('keydown')?.size || 0, 0);
});

test('clicking a wrapping label does not forward activation to the dropdown trigger', async () => {
  const ui = harness();
  const label = new Element('label'), caption = new Element('span');
  caption.textContent = '数据语言';
  ui.body.append(label); label.append(caption, ui.dropdown.el);
  const event = {type: 'click', target: caption, defaultPrevented: false,
    preventDefault() {this.defaultPrevented = true;}};
  await ui.document.dispatchEvent(event);
  // Native labels activate their first labelable control after event dispatch.
  if (!event.defaultPrevented) await ui.button.click();
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.deepEqual(ui.changes, []);
  await ui.button.click();
  assert.equal(ui.button.getAttribute('aria-expanded'), 'true');
  await ui.key('Escape'); await ui.key(' ');
  assert.equal(ui.button.getAttribute('aria-expanded'), 'true');
  ui.dropdown.destroy();
  assert.equal(ui.document.listeners.get('click')?.size || 0, 0);
});


const longOptions = Array.from({length: 30}, (_, index) => ({value: String(index), label: `选项 ${index + 1}`}));

test('short menus have no scroll prompts and the listbox contains only options', async () => {
  const ui = harness(); await ui.button.click();
  assert.ok(ui.controls.every(control => control.hidden));
  assert.equal(ui.panel.querySelectorAll('.dropdown-scroll-button').length, 0);
  assert.equal(ui.panel.querySelectorAll('[role="option"]').length, 2);
  assert.equal(ui.button.getAttribute('aria-controls'), ui.panel.id);
  assert.ok(ui.controls.every(control => control.getAttribute('tabindex') === '-1'));
});

test('long-menu scroll controls move the native viewport without committing or closing', async () => {
  const ui = harness(undefined, {value: '0', options: longOptions});
  ui.panel.scrollHeight = 1000;
  await ui.button.click();
  const [up, down] = ui.controls, activeId = ui.button.getAttribute('aria-activedescendant');
  assert.ok(ui.controls.every(control => !control.hidden));
  assert.equal(up.disabled, true); assert.equal(down.disabled, false);
  assert.equal(down.getAttribute('aria-controls'), ui.panel.id);
  assert.equal(down.getAttribute('aria-label'), '向下滚动选项');
  await ui.document.dispatchEvent({type: 'mousedown', target: down});
  let prevented = false;
  await down.dispatchEvent({type: 'mousedown', preventDefault() {prevented = true;}});
  await down.click();
  assert.equal(prevented, true);
  assert.ok(ui.panel.scrollTop > 0 && ui.panel.scrollTop < ui.panel.clientHeight);
  assert.equal(up.disabled, false);
  assert.equal(ui.dropdown.get(), '0'); assert.deepEqual(ui.changes, []);
  assert.equal(ui.button.getAttribute('aria-activedescendant'), activeId);
  assert.equal(ui.document.activeElement, ui.button);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'true');
  ui.panel.scrollTop = ui.panel.scrollHeight;
  await ui.panel.dispatchEvent('scroll');
  assert.equal(down.disabled, true); assert.equal(up.disabled, false);
  const bottom = ui.panel.scrollTop;
  await up.click();
  assert.ok(ui.panel.scrollTop < bottom);
  assert.equal(down.disabled, false);
});

test('native scrolling updates prompts without remeasuring the portal or changing selection', async () => {
  const ui = harness(undefined, {value: '0', options: longOptions});
  ui.panel.scrollHeight = 1000; await ui.button.click();
  let measured = 0;
  ui.popup.getBoundingClientRect = () => {measured++; return {height: 260};};
  const initialTop = ui.popup.style.top;
  ui.panel.scrollTop = 100;
  await ui.document.dispatchEvent({type: 'scroll', target: ui.panel});
  await ui.panel.dispatchEvent('scroll');
  assert.equal(measured, 0);
  assert.equal(ui.popup.style.top, initialTop);
  assert.equal(ui.panel.scrollTop, 100);
  assert.ok(ui.controls.every(control => !control.disabled));
  assert.equal(ui.dropdown.get(), '0'); assert.deepEqual(ui.changes, []);
  await ui.window.dispatchEvent('resize');
  assert.equal(measured, 1);
  assert.equal(ui.panel.scrollTop, 100);
});

test('option replacement removes unnecessary prompts and restores them for a long menu', async () => {
  const ui = harness(undefined, {value: '0', options: longOptions});
  ui.panel.scrollHeight = 1000; await ui.button.click();
  assert.ok(ui.controls.every(control => !control.hidden));
  ui.panel.scrollHeight = 126;
  ui.panel.getBoundingClientRect = () => ({height: 127.667});
  ui.dropdown.setOptions([{value: '0', label: '唯一选项'}]);
  assert.ok(ui.controls.every(control => control.hidden));
  assert.equal(ui.popup.style.maxHeight, '128px');
  assert.equal(ui.active().textContent, '唯一选项');
  ui.panel.scrollHeight = 1000;
  ui.panel.getBoundingClientRect = () => ({height: 260});
  ui.dropdown.setOptions(longOptions);
  assert.ok(ui.controls.every(control => !control.hidden));
  assert.equal(ui.popup.style.maxHeight, '260px');
  assert.equal(ui.dropdown.get(), '0'); assert.deepEqual(ui.changes, []);
});

test('keyboard navigation scrolls options and never explores scroll buttons', async () => {
  const ui = harness(undefined, {value: '0', options: longOptions});
  ui.panel.scrollHeight = 1000; await ui.button.click();
  const options = ui.panel.querySelectorAll('[role="option"]');
  options.at(-1).scrollIntoView = () => {ui.panel.scrollTop = ui.panel.scrollHeight;};
  options[0].scrollIntoView = () => {ui.panel.scrollTop = 0;};
  await ui.key('End');
  assert.equal(ui.active(), options.at(-1));
  assert.equal(ui.controls[1].disabled, true);
  assert.equal(ui.dropdown.get(), '0');
  await ui.key('Home');
  assert.equal(ui.active(), options[0]);
  assert.equal(ui.controls[0].disabled, true);
  await ui.key('ArrowDown'); await ui.key('Enter');
  assert.equal(ui.dropdown.get(), '1'); assert.deepEqual(ui.changes, ['1']);
});

test('closing and destroying removes the scroll listener and every floating control', async () => {
  const ui = harness(undefined, {value: '0', options: longOptions});
  ui.panel.scrollHeight = 1000; await ui.button.click();
  assert.equal(ui.panel.listeners.get('scroll').size, 1);
  await ui.key('Escape');
  assert.equal(ui.panel.listeners.get('scroll').size, 0);
  assert.equal(ui.document.querySelector('.dropdown-popup'), null);
  assert.equal(ui.document.querySelector('.dropdown-scroll-button'), null);
  await ui.button.click();
  assert.equal(ui.panel.listeners.get('scroll').size, 1);
  ui.dropdown.destroy();
  assert.equal(ui.panel.listeners.get('scroll').size, 0);
  assert.equal(ui.document.querySelector('.dropdown-floating'), null);
  assert.equal(ui.document.querySelector('.dropdown-popup'), null);
  assert.equal(ui.document.listeners.get('scroll').size, 0);
  assert.equal(ui.window.listeners.get('resize').size, 0);
});


test('disabling an open dropdown blocks pending pointer selection and removes its portal', async () => {
  const ui = harness();
  await ui.button.click();
  const pending = ui.panel.querySelector('[role="option"]');
  ui.button.disabled = true;
  await pending.click();
  assert.equal(ui.dropdown.get(), 'en');
  assert.deepEqual(ui.changes, []);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.document.querySelector('.dropdown-floating'), null);
  assert.equal(ui.document.listeners.get('keydown').size, 0);
});

test('Escape dismisses a newly disabled dropdown without reaching the parent or committing', async () => {
  const ui = harness(); await ui.key('Home');
  ui.button.disabled = true;
  const event = await ui.key('Escape');
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, true);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.dropdown.get(), 'en');
  assert.deepEqual(ui.changes, []);
});


test('host dismissal discards pending navigation, keeps the new focus and allows reopening', async () => {
  const ui = harness(); await ui.key('Home');
  assert.equal(ui.active().textContent, '中文');
  const destination = ui.document.createElement('button');
  ui.body.append(destination); ui.document.activeElement = destination;
  ui.dropdown.close();
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
  assert.equal(ui.dropdown.get(), 'en');
  assert.deepEqual(ui.changes, []);
  assert.equal(ui.document.activeElement, destination);
  assert.equal(ui.document.querySelector('.dropdown-popup'), null);
  for (const name of ['keydown', 'mousedown', 'focusin', 'scroll']) {
    assert.equal(ui.document.listeners.get(name)?.size || 0, 0);
  }
  assert.equal(ui.window.listeners.get('resize')?.size || 0, 0);
  ui.dropdown.close();
  await ui.button.click();
  assert.equal(ui.active().textContent, 'English');
  assert.equal(ui.active().getAttribute('aria-selected'), 'true');
});
