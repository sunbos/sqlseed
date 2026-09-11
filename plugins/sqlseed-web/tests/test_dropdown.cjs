const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness(rect = {top: 540, bottom: 580, left: 330, right: 790, width: 460}, settings = {}) {
  const document = createDom(), window = new Element('window');
  const scrolls = [], createElement = document.createElement;
  document.createElement = tag => {
    const element = createElement(tag);
    element.scrollIntoView = () => scrolls.push({text: element.textContent, position: element.parentNode?.style.position});
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
  panel.scrollHeight = 260;
  button.focus = () => {document.activeElement = button;};
  const key = async (value, extra = {}) => {
    const event = {type: 'keydown', key: value, target: button, defaultPrevented: false, stopped: false,
      preventDefault() {this.defaultPrevented = true;}, stopImmediatePropagation() {this.stopped = true;}, ...extra};
    await (button.getAttribute('aria-expanded') === 'true' ? document : button).dispatchEvent(event);
    return event;
  };
  const active = () => document.getElementById(button.getAttribute('aria-activedescendant'));
  return {document, window, context, overlay, modal, body, dropdown, button, panel, changes, key, active, scrolls, advance: ms => {now += ms;}};
}

test('options escape a scroll-clipped modal body and selection still updates the control', async () => {
  const ui = harness();
  await ui.button.click();
  assert.equal(ui.panel.parentNode, ui.overlay);
  assert.equal(ui.panel.style.position, 'fixed');
  assert.equal(ui.panel.style.top, '585px');
  assert.equal(ui.panel.style.width, '460px');
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
  assert.equal(ui.panel.style.top, '525px');
  assert.equal(ui.panel.style.left, '736px');
  assert.ok(Number.parseFloat(ui.panel.style.maxHeight) <= 260);
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
  await ui.key('Enter');
  assert.equal(ui.dropdown.get(), 'ja'); assert.deepEqual(ui.changes, ['ja']);
  assert.equal(ui.button.getAttribute('aria-activedescendant'), null);
  assert.equal(ui.button.getAttribute('aria-expanded'), 'false');
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
