const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Element, createDom} = require('./frontend_helpers.cjs');

const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
};

function harness(hash = '#/workbench') {
  const document = createDom(), window = new Element('window');
  const main = new Element('main'), nav = new Element('nav'), connection = new Element('button');
  main.setAttribute('id', 'app'); nav.setAttribute('id', 'nav'); connection.setAttribute('id', 'connection-button');
  for (const name of ['workbench', 'runs', 'configs', 'settings']) {
    const button = new Element('button', name); button.setAttribute('data-page', name); nav.append(button);
  }
  document.body.append(nav, connection, main);
  // The shared DOM substitute does not parse descendant selectors.
  const queryAll = document.querySelectorAll.bind(document);
  document.querySelectorAll = selector => selector === '#nav button' ? nav.children : queryAll(selector);
  const location = {hash}, events = [], modules = new Map(), imports = new Map(), roots = new Map();
  let badges = 0;
  const page = (name, mountGate = null) => ({
    render() {
      events.push(`render:${name}`);
      const root = new Element('section', name); roots.set(name, root); return root;
    },
    mount() {events.push(`mount:${name}`); return mountGate?.promise;},
    unmount() {events.push(`unmount:${name}`);},
  });
  for (const name of ['workbench', 'runs', 'configs', 'settings']) modules.set(name, page(name));
  const context = vm.createContext({document, window, location,
    openConnectionDialog() {}, setConnBadge() {badges++;},
    setTimeout() {throw new Error('Navigation must not wait for an animation timer');},
    requestAnimationFrame() {throw new Error('Navigation must not wait for an animation frame');},
    __loadPage: async file => {
      const name = path.basename(file, '.js'); events.push(`import:${name}`);
      return imports.get(name)?.promise || modules.get(name);
    },
  });
  const source = fs.readFileSync(path.join(__dirname, '../src/sqlseed_web/static/js/app.js'), 'utf8')
    .replace(/^import[^\n]+\n/gm, '').replace(/import\((['"][^'"]+['"])\)/g, '__loadPage($1)');
  vm.runInContext(source, context);
  const navigate = hash => {location.hash = hash; return window.dispatchEvent('hashchange');};
  return {document, main, nav, window, location, events, modules, imports, roots, page, navigate,
    badgeCount: () => badges};
}

test('only a different committed top-level page enters, without waiting for animation', async () => {
  const ui = harness(); await flush();
  const original = ui.main.firstChild;
  assert.equal(original.classList.contains('page-enter'), false);
  await ui.navigate('#/runs');
  assert.equal(original.isConnected, false);
  assert.equal(ui.main.children.length, 1);
  assert.equal(ui.main.firstChild.textContent, 'runs');
  assert.equal(ui.main.firstChild.classList.contains('page-enter'), true);
  assert.deepEqual(ui.events, ['import:workbench', 'render:workbench', 'mount:workbench',
    'unmount:workbench', 'import:runs', 'render:runs', 'mount:runs']);
  assert.equal(ui.nav.children.find(node => node.dataset.page === 'runs').getAttribute('aria-current'), 'page');
});

test('same-page queries and connection remounts preserve lifecycle without replaying entry', async () => {
  const ui = harness(); await flush(); await ui.navigate('#/settings?section=ai');
  assert.equal(ui.main.firstChild.classList.contains('page-enter'), true);
  const firstSettings = ui.main.firstChild;
  await ui.navigate('#/settings?section=plugins');
  assert.notEqual(ui.main.firstChild, firstSettings);
  assert.equal(ui.main.firstChild.classList.contains('page-enter'), false);
  await ui.window.dispatchEvent('sqlseed:connection-changed'); await flush();
  assert.equal(ui.main.firstChild.classList.contains('page-enter'), false);
  assert.equal(ui.events.filter(event => event === 'mount:settings').length, 3);
  assert.equal(ui.events.filter(event => event === 'unmount:settings').length, 2);
});

test('a superseded import cannot enter or become the previous committed page', async () => {
  const ui = harness(); await flush();
  const gate = deferred(); ui.imports.set('runs', gate);
  const oldNavigation = ui.navigate('#/runs'); await flush();
  assert.equal(ui.events.at(-1), 'import:runs');
  await ui.navigate('#/workbench?table=users');
  const current = ui.main.firstChild;
  assert.equal(current.classList.contains('page-enter'), false);
  gate.resolve(ui.modules.get('runs')); await oldNavigation;
  assert.equal(ui.main.firstChild, current);
  assert.equal(ui.events.includes('render:runs'), false);
  assert.equal(ui.events.includes('mount:runs'), false);
  await ui.navigate('#/configs');
  assert.equal(ui.main.firstChild.classList.contains('page-enter'), true);
});

test('a pending page mount starts immediately and its late completion cannot affect the next route', async () => {
  const ui = harness(); await flush();
  const gate = deferred(); ui.modules.set('runs', ui.page('runs', gate));
  const oldNavigation = ui.navigate('#/runs'); await flush();
  const retired = ui.main.firstChild;
  assert.equal(retired.classList.contains('page-enter'), true);
  assert.equal(ui.events.at(-1), 'mount:runs');
  await ui.navigate('#/settings');
  const current = ui.main.firstChild, badges = ui.badgeCount();
  assert.equal(retired.isConnected, false);
  assert.equal(current.classList.contains('page-enter'), true);
  gate.resolve(); await oldNavigation;
  assert.equal(ui.main.firstChild, current);
  assert.equal(ui.badgeCount(), badges);
  assert.equal(ui.events.filter(event => event === 'render:runs').length, 1);
  assert.equal(ui.events.filter(event => event === 'unmount:runs').length, 1);
});
