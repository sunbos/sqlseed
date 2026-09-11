const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const staticRoot = path.join(__dirname, '../src/sqlseed_web/static');
const read = name => fs.readFileSync(path.join(staticRoot, name), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};

test('the product has one stylesheet and four approved navigation destinations including settings', () => {
  const html = read('index.html');
  assert.deepEqual([...html.matchAll(/<link\b[^>]*href="([^"]+)"/g)].map(match => match[1]), ['/static/style.css']);
  assert.deepEqual([...html.matchAll(/data-page="([^"]+)"/g)].map(match => match[1]), ['workbench', 'runs', 'configs', 'settings']);
  assert.match(html, /id="connection-button"/);
  assert.match(html, /brand-mark/);
  assert.doesNotMatch(html, /数据库连接<|配置助手|系统信息|设计样稿|离线示例/);
});

test('the sole design baseline uses v8 tokens without the retired Material theme switch', () => {
  const css = read('style.css');
  assert.match(css, /--canvas:\s*#eef3f5/);
  assert.match(css, /--teal:\s*#167765/);
  assert.match(css, /height:\s*67px/);
  assert.doesNotMatch(css, /--md-|workbench-mode/);
});

test('every reachable product module resolves without the retired page and form modules', () => {
  const visited = new Set();
  function walk(file) {
    if (visited.has(file)) return;
    visited.add(file);
    const source = fs.readFileSync(file, 'utf8');
    for (const match of source.matchAll(/(?:from\s*|import\s*\(|import\s*)['"](\.[^'"]+)['"]/g)) {
      const dependency = path.resolve(path.dirname(file), match[1]);
      assert.ok(fs.existsSync(dependency), `Missing module: ${dependency}`);
      walk(dependency);
    }
  }
  walk(path.join(staticRoot, 'js/app.js'));
  assert.ok(visited.size > 3);
  assert.ok([...visited].every(file => !/pages\/(connect|wizard|browse|heal|meta)\.js$|\/(genform|tree)\.js$/.test(file)));
  // The DOM harness strips imports and injects bindings. A file-existence
  // check cannot catch a renamed/missing export, which breaks browser startup.
  // Link the unchanged source with the native ESM engine, including the
  // literal dynamic routes discovered above. Do not evaluate DOM or fetch code.
  execFileSync(process.execPath, ['--experimental-vm-modules', '--input-type=module', '--eval', `
    import fs from 'node:fs';
    import path from 'node:path';
    import vm from 'node:vm';
    const context = vm.createContext({}), modules = new Map();
    function load(file) {
      if (!modules.has(file)) modules.set(file, new vm.SourceTextModule(
        fs.readFileSync(file, 'utf8'), {context, identifier: file}));
      return modules.get(file);
    }
    for (const file of process.argv.slice(1)) {
      const module = load(file);
      if (module.status === 'unlinked') await module.link((name, parent) =>
        load(path.resolve(path.dirname(parent.identifier), name)));
    }
  `, '--', ...visited], {encoding: 'utf8', stdio: 'pipe'});
});

function routerHarness(hash = '', maintenance = false, supervisedMaintenance = false) {
  const document = createDom(), window = new Element('window');
  document.documentElement = new Element('html');
  if (maintenance) document.documentElement.setAttribute('data-plugin-maintenance', 'true');
  if (supervisedMaintenance) document.documentElement.setAttribute('data-plugin-supervised-maintenance', 'true');
  document.body.append(new Element('main'));
  document.body.firstChild.setAttribute('id', 'app');
  const nav = new Element('nav'); nav.setAttribute('id', 'nav'); document.body.append(nav);
  for (const name of ['workbench', 'configs', 'runs', 'settings']) {const button = new Element('button'); button.setAttribute('data-page', name); nav.append(button);}
  const connection = new Element('button'); connection.setAttribute('id', 'connection-button'); document.body.append(connection);
  const store = {connId: null, target: null, tables: []};
  const events = [], loads = [], modules = new Map();
  const location = {hash};
  const bindings = {document, window, location, store, Event: class {constructor(type) {this.type = type;}},
    openConnectionDialog: () => events.push('connect'), setConnBadge: () => {},
    __loadPage: async file => {
      loads.push(file);
      if (modules.has(file)) return modules.get(file);
      return {render: () => new Element('section', file), mount: () => events.push(`mount:${file}`), unmount: () => events.push(`unmount:${file}`)};
    },
  };
  const context = vm.createContext(bindings);
  const code = read('js/app.js').replace(/^import[^\n]+\n/gm, '').replace(/import\((['"][^'"]+['"])\)/g, '__loadPage($1)');
  vm.runInContext(code, context);
  return {document, window, location, store, events, loads, modules, connection, context};
}

test('empty and retired routes open the workbench and never load retired page modules', async () => {
  for (const hash of ['', '#/connect', '#/wizard', '#/browse', '#/heal', '#/meta']) {
    const ui = routerHarness(hash); await flush();
    assert.deepEqual(ui.loads, ['./pages/workbench.js']);
    assert.equal(ui.document.getElementById('app').textContent, './pages/workbench.js');
  }
});

test('settings is a first-class route with the shared application shell', async () => {
  const ui = routerHarness('#/settings?section=ai'); await flush();
  assert.deepEqual(ui.loads, ['./pages/settings.js']);
  assert.equal(ui.document.title, 'sqlseed · 设置');
});

test('maintenance shell opens settings only and cannot open operational pages or a connection', async () => {
  const ui = routerHarness('#/workbench', true); await flush();
  assert.deepEqual(ui.loads, ['./pages/settings.js']);
  assert.equal(ui.location.hash, '#/settings?section=plugins');
  assert.equal(ui.document.title, 'sqlseed · 插件维护');
  for (const button of ui.document.querySelectorAll('#nav button')) {
    assert.equal(button.hidden, button.dataset.page !== 'settings');
    assert.equal(button.disabled, button.dataset.page !== 'settings');
  }
  await ui.connection.dispatchEvent('click');
  assert.equal(ui.events.includes('connect'), false);
  ui.location.hash = '#/runs?id=old'; await ui.window.dispatchEvent('hashchange'); await flush();
  assert.ok(ui.loads.every(file => file === './pages/settings.js'));
  assert.equal(ui.location.hash, '#/settings?section=plugins');
});

test('opening during automatic recovery shows plugin status first without permanently locking navigation', async () => {
  const ui = routerHarness('#/workbench', false, true); await flush();
  assert.equal(ui.loads.at(-1), './pages/settings.js');
  assert.equal(ui.location.hash, '#/settings?section=plugins');
  for (const button of ui.document.querySelectorAll('#nav button')) {assert.equal(button.hidden, false); assert.equal(button.disabled, false);}
  ui.location.hash = '#/workbench'; await ui.window.dispatchEvent('hashchange'); await flush();
  assert.equal(ui.loads.at(-1), './pages/workbench.js');
});

test('connection changes remount the active product page and the topbar opens the shared dialog', async () => {
  const ui = routerHarness(); await flush();
  await ui.connection.click(); assert.deepEqual(ui.events.slice(-1), ['connect']);
  await ui.window.dispatchEvent('sqlseed:connection-changed'); await flush();
  assert.deepEqual(ui.loads, ['./pages/workbench.js', './pages/workbench.js']);
  assert.ok(ui.events.includes('unmount:./pages/workbench.js'));
});

test('a slower prior route cannot replace the latest page', async () => {
  const ui = routerHarness(); await flush();
  const gate = deferred(); ui.modules.set('./pages/workbench.js', gate.promise);
  await ui.window.dispatchEvent('sqlseed:connection-changed');
  ui.location.hash = '#/runs'; await ui.window.dispatchEvent('hashchange'); await flush();
  gate.resolve({render: () => new Element('div', 'obsolete')}); await flush();
  assert.equal(ui.document.getElementById('app').textContent, './pages/runs.js');
});

function connectionHarness(routes = {}) {
  const document = createDom(), window = new Element('window');
  const store = {connId: null, target: null, tables: []}, requests = [], remembered = [], changes = [];
  const invoke = async (url, data, method = 'GET') => {
    requests.push({url, data, method});
    if (routes[url]) return routes[url](data, method);
    if (url === '/api/connections' && method === 'GET') return {connections: []};
    throw new Error(`Unexpected request ${url}`);
  };
  window.addEventListener('sqlseed:connection-changed', () => changes.push(store.connId));
  const context = loadFrontend('workbench/connection.js', {document, window, store, URL,
    Event: class {constructor(type) {this.type = type;}}, get: url => invoke(url),
    send: (url, data, method = 'POST') => invoke(url, data, method),
    rememberConnId: id => remembered.push(id), setConnBadge: () => {},
    safeTargetLabel: value => value.includes('://') ? new URL(value).hostname + new URL(value).pathname : value.split('/').at(-1),
  });
  const dialog = context.openConnectionDialog({onConnected: () => {}});
  const input = (name, value) => {const el = document.querySelector(`[name="${name}"]`); assert.ok(el, name); el.value = value; return el;};
  const button = label => document.querySelectorAll('button').find(el => el.textContent === label);
  return {document, store, requests, remembered, changes, dialog, input, button};
}

test('the inline connection dialog submits one SQLite target and publishes only a successful connection', async () => {
  const ui = connectionHarness({'/api/connections': (data, method) => method === 'GET' ? {connections: []} : {conn_id: 'A', target: data.db_path, tables: [{name: 'users'}]}});
  await flush();
  assert.equal(ui.button('SQLite').getAttribute('aria-pressed'), 'true');
  assert.equal(ui.button('PostgreSQL').getAttribute('aria-pressed'), 'false');
  ui.input('db_path', '/temporary/example.db');
  await ui.button('连接数据库').click(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(ui.requests.find(request => request.method === 'POST').data)), {db_path: '/temporary/example.db', provider: 'base'});
  assert.equal(ui.store.connId, 'A'); assert.equal(ui.store.target, '/temporary/example.db');
  assert.deepEqual(ui.remembered, ['A']); assert.deepEqual(ui.changes, ['A']);
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.ok(ui.requests.every(request => !/preview|\/rows|sample/.test(request.url)));
});

test('closing the dialog ignores a late connection response and clears sensitive input', async () => {
  const gate = deferred();
  const ui = connectionHarness({'/api/connections': (_, method) => method === 'GET' ? {connections: []} : gate.promise});
  await flush(); await ui.button('PostgreSQL').click();
  ui.input('host', 'localhost'); ui.input('user', 'alice'); ui.input('database', 'test'); const secret = ui.input('password', 'temporary secret');
  const pending = ui.button('连接数据库').click(); await flush(); ui.dialog.close();
  gate.resolve({conn_id: 'A', target: 'postgresql://alice:temporary%20secret@localhost/test', tables: []}); await pending;
  assert.equal(ui.store.connId, null); assert.deepEqual(ui.changes, []); assert.equal(secret.value, '');
});

test('file browsing lists server paths and selects a file without connecting or reading records', async () => {
  const ui = connectionHarness({'/api/fs/browse': () => ({path: '/temporary', parent: '/', entries: [{name: 'example.db', path: '/temporary/example.db', is_dir: false, is_db: true}]})});
  await flush(); await ui.button('选择文件').click(); await flush(); await ui.button('example.db').click();
  assert.equal(ui.document.querySelector('[name="db_path"]').value, '/temporary/example.db');
  assert.deepEqual(ui.requests.map(request => request.url), ['/api/connections', '/api/fs/browse']);
});

test('an existing connection is selected with its own table list and target', async () => {
  const ui = connectionHarness({
    '/api/connections': () => ({connections: [{conn_id: 'B', target: '/temporary/other.db'}]}),
    '/api/connections/B/tables': () => ({target: '/temporary/other.db', tables: [{name: 'events'}]}),
  });
  await flush(); await ui.document.querySelector('.connection-card').click(); await flush();
  assert.equal(ui.store.connId, 'B'); assert.equal(ui.store.target, '/temporary/other.db');
  assert.deepEqual(ui.store.tables, [{name: 'events'}]); assert.deepEqual(ui.changes, ['B']);
});

test('PostgreSQL connects with encoded credentials and does not publish their URL', async () => {
  const ui = connectionHarness({'/api/connections': (data, method) => method === 'GET' ? {connections: []} : {conn_id: 'P', target: data.url, tables: []}});
  await flush(); await ui.button('PostgreSQL').click();
  ui.input('user', 'a@b'); ui.input('database', 'a/b'); const password = ui.input('password', 'p:@?#');
  await ui.button('连接数据库').click(); await flush();
  const target = new URL(ui.requests.find(request => request.method === 'POST').data.url);
  assert.equal(decodeURIComponent(target.username), 'a@b'); assert.equal(decodeURIComponent(target.password), 'p:@?#');
  assert.equal(decodeURIComponent(target.pathname), '/a/b');
  assert.doesNotMatch(ui.store.target, /p:|a%40|postgresql:\/\//); assert.equal(password.value, '');
});

test('invalid targets stay editable and do not issue a connection request', async () => {
  const ui = connectionHarness(); await flush();
  await ui.button('连接数据库').click();
  assert.match(ui.document.querySelector('[role="alert"]').textContent, /文件路径/);
  await ui.button('PostgreSQL').click();
  ui.input('user', 'alice'); ui.input('database', 'test'); ui.input('port', '99999');
  await ui.button('连接数据库').click();
  assert.match(ui.document.querySelector('[role="alert"]').textContent, /65535/);
  assert.ok(ui.requests.every(request => request.method === 'GET')); assert.deepEqual(ui.changes, []);
});

test('connection failure keeps the form open and redacts credentials in errors', async () => {
  const ui = connectionHarness({'/api/connections': (_, method) => {
    if (method === 'GET') return {connections: []};
    throw new Error('postgresql://alice:secret@host/db?sslpassword=private failed');
  }});
  await flush(); ui.input('db_path', '/temporary/fail.db'); await ui.button('连接数据库').click();
  const error = ui.document.querySelector('[role="alert"]').textContent;
  assert.doesNotMatch(error, /secret|private/);
  assert.equal(ui.button('连接数据库').disabled, false); assert.equal(ui.store.connId, null);
});

test('late startup restoration cannot replace a newer explicit connection', async () => {
  const gate = deferred();
  const context = vm.createContext({console, URL, document: createDom(),
    localStorage: {getItem: () => 'A', removeItem() {}},
    fetch: async url => ({ok: true, json: async () => url === '/api/connections' ? {connections: [{conn_id: 'A'}]} : gate.promise}),
  });
  vm.runInContext(read('js/api.js').replace(/^export /gm, ''), context);
  const pending = vm.runInContext('restoreConnection()', context); await flush();
  vm.runInContext("store.connId='B';store.target='new.db';store.tables=[{name:'new'}]", context);
  gate.resolve({target: '/temporary/old.db', tables: [{name: 'old'}]}); await pending;
  assert.equal(vm.runInContext('store.connId', context), 'B');
  assert.equal(vm.runInContext('store.target', context), 'new.db');
});
