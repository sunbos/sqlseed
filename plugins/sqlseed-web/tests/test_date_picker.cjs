const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

function harness(value = '2024-02-29', {height = 872, width = 1144} = {}) {
  assert.ok(fs.existsSync(path.join(__dirname, '../src/sqlseed_web/static/js/workbench/date-picker.js')), 'Date picker component is missing');
  const document = createDom(), window = new Element('window');
  document.createElement = tag => {
    const node = new Element(tag);
    node.focus = () => {document.activeElement = node;};
    node.scrollIntoView = () => {};
    return node;
  };
  const captures = new Map();
  const add = document.addEventListener.bind(document), remove = document.removeEventListener.bind(document);
  document.addEventListener = (name, fn, options) => {add(name, fn); captures.set(fn, options === true || options?.capture);};
  document.removeEventListener = (name, fn) => {remove(name, fn); captures.delete(fn);};
  document.dispatchEvent = async event => {
    let stopped = false;
    event.preventDefault ||= () => {};
    event.stopPropagation ||= () => {};
    event.stopImmediatePropagation = () => {stopped = true;};
    const listeners = [...(document.listeners.get(event.type) || [])];
    for (const fn of [...listeners.filter(fn => captures.get(fn)), ...listeners.filter(fn => !captures.get(fn))]) {
      await fn(event);
      if (stopped) break;
    }
  };
  const page = document.createElement('main'), overlay = document.createElement('div'), body = document.createElement('div');
  overlay.className = 'overlay'; body.className = 'modal-body';
  document.body.append(page, overlay); overlay.append(body); page.inert = true;
  class Today extends Date {constructor(...args) {super(...(args.length ? args : [2024, 1, 29, 12]));}}
  const context = loadFrontend('workbench/date-picker.js', {document, window, innerHeight: height, innerWidth: width, Date: Today});
  const changes = [], validity = [];
  const picker = context.createDatePicker({value, label: '开始日期', onChange: value => changes.push(value), onValidity: message => validity.push(message)});
  body.append(picker.el);
  picker.button.getBoundingClientRect = () => ({top: 790, bottom: 830, left: 990, right: 1130, width: 140});
  const calendar = () => document.querySelector('.wb-date-dialog');
  const action = label => calendar().querySelectorAll('button').find(button => button.getAttribute('aria-label') === label || button.textContent === label);
  const key = async (key, extra = {}) => document.dispatchEvent({type: 'keydown', key, target: document.activeElement, ...extra});
  return {document, window, page, overlay, body, picker, changes, validity, calendar, action, key};
}

test('text input exposes ISO format and rejects impossible dates without emitting a value', async () => {
  const ui = harness();
  assert.equal(ui.picker.input.type, 'text');
  assert.equal(ui.picker.input.value, '2024-02-29');
  const description = ui.document.getElementById(ui.picker.input.getAttribute('aria-describedby').split(' ')[0]);
  assert.match(description.textContent, /YYYY-MM-DD/);
  for (const value of ['2023-02-29', '2024-13-01', '0000-01-01', '2024-02-', 'bad-date']) {
    ui.picker.input.value = value; await ui.picker.input.dispatchEvent('input');
    assert.equal(ui.picker.input.value, value);
    assert.equal(ui.picker.input.getAttribute('aria-invalid'), 'true');
    assert.match(ui.validity.at(-1), /有效日期/);
    assert.equal(ui.changes.length, 0);
  }
  ui.picker.input.value = '2024-03-01'; await ui.picker.input.dispatchEvent('input');
  assert.deepEqual(ui.changes, ['2024-03-01']);
  assert.equal(ui.validity.at(-1), null);
});

test('calendar is a modal body portal with a single focused grid day', async () => {
  const ui = harness(); await ui.picker.button.click();
  assert.equal(ui.calendar().parentNode.parentNode, ui.document.body);
  assert.equal(ui.body.contains(ui.calendar()), false);
  assert.equal(ui.calendar().getAttribute('role'), 'dialog');
  assert.equal(ui.calendar().getAttribute('aria-modal'), 'true');
  assert.equal(ui.overlay.inert, true);
  assert.equal(ui.document.activeElement.getAttribute('data-date'), '2024-02-29');
  assert.equal(ui.calendar().querySelectorAll('[data-date]').filter(day => day.getAttribute('tabindex') === '0').length, 1);
  assert.equal(ui.document.activeElement.closest('td').getAttribute('aria-selected'), 'true');
  assert.ok(Number.parseFloat(ui.calendar().style.top) >= 8);
  assert.ok(Number.parseFloat(ui.calendar().style.left) + Number.parseFloat(ui.calendar().style.width) <= 1136);
});

test('arrows, week boundaries and month/year paging preserve calendar dates across leap years', async () => {
  const ui = harness(); await ui.picker.button.click();
  const expect = value => assert.equal(ui.document.activeElement.getAttribute('data-date'), value);
  await ui.key('ArrowRight'); expect('2024-03-01');
  await ui.key('ArrowUp'); expect('2024-02-23');
  await ui.key('ArrowDown'); expect('2024-03-01');
  await ui.key('Home'); expect('2024-02-26');
  await ui.key('End'); expect('2024-03-03');
  await ui.key('PageUp'); expect('2024-02-03');
  await ui.key('PageDown', {shiftKey: true}); expect('2025-02-03');
  await ui.key('PageUp', {shiftKey: true}); expect('2024-02-03');
  await ui.key('ArrowLeft'); expect('2024-02-02');
  assert.deepEqual(ui.changes, []);
});

test('month and year paging clamps the 31st and leap day to an existing date', async () => {
  const ui = harness('2024-03-31'); await ui.picker.button.click();
  await ui.key('PageUp'); assert.equal(ui.document.activeElement.getAttribute('data-date'), '2024-02-29');
  await ui.key('PageDown', {shiftKey: true}); assert.equal(ui.document.activeElement.getAttribute('data-date'), '2025-02-28');
});

test('Enter selects a day, closes the calendar and returns focus to the named button', async () => {
  const ui = harness(); await ui.picker.button.click(); await ui.key('ArrowRight'); await ui.key('Enter');
  assert.deepEqual(ui.changes, ['2024-03-01']); assert.equal(ui.picker.input.value, '2024-03-01');
  assert.equal(ui.calendar(), null); assert.equal(ui.document.activeElement, ui.picker.button);
  assert.match(ui.picker.button.getAttribute('aria-label'), /2024-03-01/);
  assert.equal(ui.overlay.inert, false); assert.equal(ui.page.inert, true);
});

test('Escape is captured before a parent modal handler and does not apply navigation', async () => {
  const ui = harness(); let parentClosed = false;
  ui.document.addEventListener('keydown', event => {if (event.key === 'Escape') parentClosed = true;});
  await ui.picker.button.click(); await ui.key('ArrowRight'); await ui.key('Escape');
  assert.equal(parentClosed, false); assert.equal(ui.calendar(), null); assert.deepEqual(ui.changes, []);
  assert.equal(ui.picker.input.value, '2024-02-29'); assert.equal(ui.document.activeElement, ui.picker.button);
  await ui.key('Escape'); assert.equal(parentClosed, true);
});

test('Tab and Shift+Tab stay inside the calendar and the grid is one tab stop', async () => {
  const ui = harness(); await ui.picker.button.click();
  const controls = ui.calendar().querySelectorAll('button,input').filter(control => !control.disabled && control.getAttribute('tabindex') !== '-1');
  controls.at(-1).focus(); await ui.key('Tab'); assert.equal(ui.document.activeElement, controls[0]);
  await ui.key('Tab', {shiftKey: true}); assert.equal(ui.document.activeElement, controls.at(-1));
});

test('month/year jump validates both fields before moving and supports the complete four-digit year range', async () => {
  const ui = harness(); await ui.picker.button.click();
  const year = ui.calendar().querySelector('[data-calendar-year]'), month = ui.calendar().querySelector('[data-calendar-month]');
  year.value = '2025'; month.value = '13'; await ui.action('跳转').click();
  assert.match(ui.calendar().querySelector('[role="alert"]').textContent, /月份/);
  assert.equal(month.getAttribute('aria-invalid'), 'true');
  month.value = '2'; await ui.action('跳转').click();
  assert.equal(ui.document.activeElement.getAttribute('data-date'), '2025-02-28');
  year.value = '1'; month.value = '1'; await ui.action('跳转').click();
  assert.equal(ui.document.activeElement.getAttribute('data-date'), '0001-01-28');
  assert.deepEqual(ui.changes, []);
});

test('today chooses the local day and clear emits an absent date', async () => {
  const ui = harness('2020-01-01'); await ui.picker.button.click(); await ui.action('今天').click();
  assert.equal(ui.changes.at(-1), '2024-02-29');
  await ui.picker.button.click(); await ui.action('清空').click();
  assert.equal(ui.changes.at(-1), undefined); assert.equal(ui.picker.input.value, '');
  assert.equal(ui.calendar(), null); assert.equal(ui.validity.at(-1), null);
});

test('invalid text opens the current month but Escape retains the invalid draft', async () => {
  const ui = harness('2024-02-'); await ui.picker.button.click();
  assert.equal(ui.document.activeElement.getAttribute('data-date'), '2024-02-29');
  await ui.key('Escape'); assert.equal(ui.picker.input.value, '2024-02-');
  assert.ok(ui.validity.at(-1)); assert.deepEqual(ui.changes, []);
});

test('destroy removes the portal and listeners without restoring stale parent-modal inert state', async () => {
  const ui = harness(); await ui.picker.button.click();
  ui.overlay.remove(); ui.page.inert = false; ui.picker.destroy();
  assert.equal(ui.calendar(), null); assert.equal(ui.page.inert, false);
  for (const name of ['keydown', 'focusin', 'scroll']) assert.equal(ui.document.listeners.get(name)?.size || 0, 0);
  assert.equal(ui.window.listeners.get('resize')?.size || 0, 0);
});

test('calendar fits a short viewport and closes when its anchor is detached', async () => {
  const ui = harness('2024-02-29', {width: 400, height: 300});
  ui.picker.button.getBoundingClientRect = () => ({top: 230, bottom: 260, left: 300, right: 380, width: 80});
  await ui.picker.button.click();
  assert.ok(Number.parseFloat(ui.calendar().style.maxHeight) <= 284);
  ui.picker.el.remove(); await ui.window.dispatchEvent('resize');
  assert.equal(ui.calendar(), null);
});

test('destroyed input events cannot publish new validity or draft updates', async () => {
  const ui = harness(); const count = ui.validity.length; ui.picker.destroy();
  ui.picker.input.value = 'invalid'; await ui.picker.input.dispatchEvent('input');
  assert.equal(ui.validity.length, count); assert.deepEqual(ui.changes, []);
});

test('focus outside the modal calendar returns to its active grid date', async () => {
  const ui = harness(); await ui.picker.button.click();
  ui.document.activeElement = ui.page;
  await ui.document.dispatchEvent({type: 'focusin', target: ui.page});
  assert.equal(ui.document.activeElement.getAttribute('data-date'), '2024-02-29');
});
