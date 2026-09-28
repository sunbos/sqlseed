const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const key = 'sqlseed.theme.preference';
const tick = () => new Promise(resolve => setImmediate(resolve));
class ThemeEvent {constructor(type, {detail}) {this.type = type; this.detail = detail;}}
function harness({saved, dark = false, readError = false, writeError = false, storageError = false, mediaError = false, legacyMedia = false} = {}) {
  const document = createDom(), window = new Element('window'), media = new Element('media');
  const writes = [], events = [];
  let stored = saved ?? null;
  const storage = {getItem: () => {if (readError) throw Error('storage unavailable'); return stored;}, setItem: (...args) => {if (writeError) throw Error('storage full'); writes.push(args); stored = args[1];}};
  if (storageError) Object.defineProperty(window, 'localStorage', {get() {throw Error('storage denied');}});
  else window.localStorage = storage;
  media.matches = dark;
  if (legacyMedia) {
    media.addListener = listener => Element.prototype.addEventListener.call(media, 'change', listener);
    media.addEventListener = undefined;
  }
  window.matchMedia = () => {if (mediaError) throw Error('media unavailable'); return media;};
  window.addEventListener('sqlseed:theme-changed', event => events.push({...event.detail}));
  loadFrontend('theme.js', {document, window, CustomEvent: ThemeEvent});
  return {document, window, media, writes, events, storage, setStored: value => {stored = value;}, theme: window.sqlseedTheme};
}
function control(t) {
  if (!t.controlModule) {
    const dropdown = loadFrontend('dropdown.js', {document: t.document, window: t.window});
    t.controlModule = loadFrontend('theme-control.js', {document: t.document, window: t.window, createDropdown: dropdown.createDropdown});
  }
  const value = t.controlModule.createThemeControl();
  t.document.body.append(value.el);
  const trigger = value.el.querySelector('[role="combobox"]');
  trigger.focus = () => {t.document.activeElement = trigger;};
  return {...value, trigger};
}
const keyboard = (target, key) => target.dispatchEvent({type: 'keydown', key, stopImmediatePropagation() {}});

test('bootstrap keeps first visits light even on a dark system and applies saved preferences immediately', () => {
  const fresh = harness({dark: true});
  assert.equal(fresh.document.documentElement.dataset.theme, 'light');
  assert.equal(fresh.document.documentElement.dataset.themePreference, 'light');
  assert.equal(fresh.document.documentElement.style.colorScheme, 'light');
  assert.equal(fresh.writes.length, 0);
  for (const saved of ['light', 'dark', 'system']) {
    const t = harness({saved, dark: true});
    assert.equal(t.theme.get().preference, saved);
    assert.equal(t.document.documentElement.dataset.theme, saved === 'light' ? 'light' : 'dark');
  }
});

test('system appearance changes only affect an explicit system preference', async () => {
  const t = harness({saved: 'dark'}); await tick();
  t.media.matches = true; await t.media.dispatchEvent('change');
  assert.equal(t.events.length, 1);
  t.theme.setPreference('system'); await tick();
  assert.equal(t.theme.get().resolved, 'dark');
  t.media.matches = false; await t.media.dispatchEvent('change'); await tick();
  assert.deepEqual({...t.theme.get()}, {preference: 'system', resolved: 'light'});
  assert.deepEqual(t.writes, [[key, 'system']]);
  t.theme.setPreference('light'); await tick();
  const count = t.events.length;
  t.media.matches = true; await t.media.dispatchEvent('change');
  assert.equal(t.events.length, count);
  assert.equal(t.theme.get().resolved, 'light');
});

test('legacy system signals resolve and update system mode', async () => {
  const t = harness({saved: 'system', legacyMedia: true});
  t.media.matches = true; await t.media.dispatchEvent('change');
  assert.equal(t.theme.get().resolved, 'dark');
});

test('storage and media failures leave a working in-memory preference', () => {
  for (const options of [{readError: true}, {storageError: true}, {writeError: true}]) {
    const t = harness(options);
    assert.equal(t.theme.get().preference, 'light');
    t.theme.setPreference('dark');
    assert.equal(t.document.documentElement.dataset.theme, 'dark');
  }
  const t = harness({saved: 'system', mediaError: true});
  assert.equal(t.theme.get().resolved, 'light');
  assert.equal(harness({saved: 'unknown'}).theme.get().preference, 'light');
  assert.throws(() => t.theme.setPreference('unknown'), /Unsupported theme preference/);
  assert.equal(t.theme.get().preference, 'system');
  assert.ok(Object.isFrozen(t.theme));
  assert.ok(Object.isFrozen(t.theme.get()));
});

test('cross-tab changes, removal and storage clearing sync without echo writes', async () => {
  const t = harness({dark: true});
  const storageEvent = (name, value, storageArea = t.storage) => {
    if ((name === key || name === null) && storageArea === t.storage) t.setStored(value);
    return t.window.dispatchEvent({type: 'storage', key: name, newValue: value, storageArea});
  };
  await storageEvent('unrelated', 'dark');
  await storageEvent(key, 'dark', {});
  assert.equal(t.theme.get().preference, 'light');
  await storageEvent(key, 'dark');
  assert.equal(t.theme.get().resolved, 'dark');
  await storageEvent(key, 'system');
  assert.deepEqual({...t.theme.get()}, {preference: 'system', resolved: 'dark'});
  await storageEvent(key, null);
  assert.equal(t.theme.get().preference, 'light');
  await storageEvent(key, 'dark');
  await storageEvent(null, null);
  assert.equal(t.theme.get().preference, 'light');
  await storageEvent(key, 'corrupt');
  assert.equal(t.theme.get().preference, 'light');
  assert.equal(t.writes.length, 0);
});

test('a delayed storage event cannot roll back a newer local or cross-tab selection', async () => {
  const t = harness();
  t.setStored('dark'); // 另一标签页的旧写入，其通知仍在事件队列中。
  t.theme.setPreference('light');
  await t.window.dispatchEvent({type: 'storage', key, newValue: 'dark', storageArea: t.storage});
  assert.equal(t.theme.get().preference, 'light');
  assert.equal(t.document.documentElement.dataset.theme, 'light');
  t.setStored('dark'); // 清空通知到达前，另一页已再次选择深色。
  await t.window.dispatchEvent({type: 'storage', key: null, newValue: null, storageArea: t.storage});
  assert.equal(t.theme.get().preference, 'dark');
  assert.deepEqual(t.writes, [[key, 'light']]);
});

test('a storage event still synchronizes when reading the latest preference is blocked', async () => {
  const t = harness({readError: true});
  await t.window.dispatchEvent({type: 'storage', key, newValue: 'dark', storageArea: t.storage});
  assert.equal(t.theme.get().resolved, 'dark');
  assert.equal(t.writes.length, 0);
});

test('shared controls select by keyboard and synchronize through one theme owner', async () => {
  const t = harness(); const first = control(t), second = control(t);
  first.trigger.focus();
  await keyboard(first.trigger, 'ArrowDown');
  await keyboard(t.document, 'ArrowDown');
  await keyboard(t.document, 'Enter'); await tick();
  assert.equal(t.theme.get().preference, 'dark');
  assert.equal(first.trigger.textContent, '深色');
  assert.equal(second.trigger.textContent, '深色');
  assert.equal(t.document.activeElement, first.trigger);
  assert.equal(first.trigger.getAttribute('aria-expanded'), 'false');
  assert.deepEqual(t.writes, [[key, 'dark']]);
  assert.match(second.el.textContent, /当前使用深色主题/);
  first.destroy(); second.destroy();
});

test('system changes preserve an open menu, its explored option and keyboard focus', async () => {
  const t = harness({saved: 'system'}); const item = control(t);
  item.trigger.focus();
  await item.trigger.click(); await keyboard(t.document, 'Home');
  const active = item.trigger.getAttribute('aria-activedescendant');
  assert.match(t.document.getElementById(active).textContent, /浅色/);
  t.media.matches = true; await t.media.dispatchEvent('change'); await tick();
  assert.equal(item.trigger.getAttribute('aria-expanded'), 'true');
  assert.equal(item.trigger.getAttribute('aria-activedescendant'), active);
  assert.equal(t.document.activeElement, item.trigger);
  assert.match(item.el.textContent, /当前为深色/);
  item.destroy();
});

test('cross-tab changes keep the control and open menu while refreshing its selection', async () => {
  const t = harness(); const item = control(t);
  item.trigger.focus(); await item.trigger.click();
  t.setStored('dark');
  await t.window.dispatchEvent({type: 'storage', key, newValue: 'dark', storageArea: t.storage}); await tick();
  assert.equal(item.el.querySelector('[role="combobox"]'), item.trigger);
  assert.equal(item.trigger.textContent, '深色');
  assert.equal(item.trigger.getAttribute('aria-expanded'), 'true');
  assert.equal(t.document.activeElement, item.trigger);
  const panel = t.document.getElementById(item.trigger.getAttribute('aria-controls'));
  assert.equal(panel.querySelector('[aria-selected="true"]').textContent, '深色');
  item.destroy();
});

test('destroy detaches theme subscribers and dropdown listeners and does not update removed controls', async () => {
  const t = harness(); const before = t.window.listeners.get('sqlseed:theme-changed').size;
  const item = control(t); await item.trigger.click();
  assert.equal(t.window.listeners.get('sqlseed:theme-changed').size, before + 1);
  item.destroy(); item.el.remove();
  assert.equal(t.window.listeners.get('sqlseed:theme-changed').size, before);
  assert.equal(t.document.querySelector('.dropdown-floating'), null);
  t.theme.setPreference('dark'); await tick();
  assert.equal(item.trigger.textContent, '浅色');
});

test('both entry documents synchronously bootstrap theme before their first stylesheet', () => {
  for (const name of ['index.html', 'design-system.html']) {
    const html = fs.readFileSync(path.join(__dirname, '../src/sqlseed_web/static', name), 'utf8');
    const script = html.match(/<script\b[^>]*src="\/static\/js\/theme\.js"[^>]*><\/script>/);
    assert.ok(script, name);
    assert.doesNotMatch(script[0], /\b(async|defer|type)=?/);
    assert.ok(html.indexOf(script[0]) < html.indexOf('rel="stylesheet"'), name);
  }
});
