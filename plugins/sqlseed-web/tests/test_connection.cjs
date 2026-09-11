const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};
const connection = (id, target = '/temporary/example.db', group = target) => ({conn_id: id, target, group_key: group});

function harness({connections = [connection('A')], current = 'A', remove, listed, add, select, browse} = {}) {
  const document = createDom(), window = new Element('window'), requests = [], remembered = [], changes = [];
  const store = {connId: current, target: current ? '/temporary/example.db' : null, tables: current ? [{name: 'users'}] : []};
  const invoke = async (url, data, method = 'GET') => {
    requests.push({url, data, method});
    if (method === 'POST') return add ? add(data) : {...connection('new', data.db_path), tables: []};
    if (url.startsWith('/api/fs/browse')) return browse ? browse(url) : {path:'/temporary',parent:null,entries:[]};
    if (method === 'DELETE') {
      if (remove) await remove(url);
      const index = connections.findIndex(item => url.endsWith('/' + item.conn_id));
      if (index >= 0) connections.splice(index, 1);
      return {closed: url.split('/').at(-1)};
    }
    if (url === '/api/connections') return listed ? listed() : {connections};
    const item = connections.find(item => url === `/api/connections/${item.conn_id}/tables`);
    if (item) return select ? select(item) : {...item, tables: [{name: 'other'}]};
    throw new Error(`Unexpected request ${method} ${url}`);
  };
  window.addEventListener('sqlseed:connection-changed', () => changes.push(store.connId));
  const context = loadFrontend('workbench/connection.js', {document, window, store,
    Event: class {constructor(type) {this.type = type;}}, get: url => invoke(url),
    send: (url, data, method = 'POST') => invoke(url, data, method),
    rememberConnId: id => remembered.push(id), setConnBadge: () => {},
    safeTargetLabel: value => value.includes('://') ? new URL(value).hostname + new URL(value).pathname : value.split('/').at(-1),
  });
  const dialog = context.openConnectionDialog();
  return {document, store, requests, remembered, changes, dialog,
    buttons: label => document.querySelectorAll('button').filter(el => el.textContent === label)};
}

test('same-target live sessions are grouped and identified without repeating an ambiguous database list', async () => {
  const ui = harness({connections: [connection('A'), connection('B'), connection('C', '/another/example.db')]});
  await flush();
  const groups = ui.document.querySelectorAll('.connection-group');
  assert.equal(groups.length, 2);
  assert.match(groups[0].textContent, /2 个会话/);
  assert.match(groups[0].textContent, /当前连接/);
  assert.match(groups[0].textContent, /会话 2/);
  assert.match(groups[0].textContent, /\/temporary\/example.db/);
  assert.match(groups[1].textContent, /\/another\/example.db/);
  assert.equal(ui.buttons('断开并移除').length, 3);
  assert.match(ui.document.textContent, /添加连接/);
  assert.match(ui.document.textContent, /不会删除数据库/);
});

test('disconnecting the current session releases only that server session and clears the selected target', async () => {
  const ui = harness(); await flush();
  await ui.buttons('断开并移除')[0].click(); await flush();
  assert.deepEqual(ui.requests.filter(request => request.method === 'DELETE'), [{url: '/api/connections/A', data: undefined, method: 'DELETE'}]);
  assert.equal(ui.store.connId, null); assert.equal(ui.store.target, null); assert.equal(ui.store.tables.length, 0);
  assert.deepEqual(ui.remembered, ['']); assert.deepEqual(ui.changes, [null]);
  assert.equal(ui.document.querySelectorAll('.connection-session').length, 0);
  assert.match(ui.document.textContent, /已断开/);
});

test('removing an unused parallel session preserves the current target and does not remount it', async () => {
  const ui = harness({connections: [connection('A'), connection('B')]}); await flush();
  await ui.buttons('断开并移除')[1].click(); await flush();
  assert.equal(ui.store.connId, 'A'); assert.equal(ui.store.tables[0].name, 'users');
  assert.deepEqual(ui.remembered, []); assert.deepEqual(ui.changes, []);
  assert.equal(ui.document.querySelectorAll('.connection-session').length, 1);
});

test('a busy server connection remains selected and preserves the specific server reason', async () => {
  const ui = harness({remove: () => {const error = new Error('当前连接正在处理请求，请等待完成后重试。'); error.status = 409; throw error;}});
  await flush(); await ui.buttons('断开并移除')[0].click(); await flush();
  assert.equal(ui.store.connId, 'A'); assert.equal(ui.document.querySelectorAll('.connection-session').length, 1);
  assert.match(ui.document.querySelector('[role="alert"]').textContent, /正在处理请求/);
  assert.deepEqual(ui.changes, []); assert.equal(ui.buttons('断开并移除')[0].disabled, false);
});

test('an in-flight disconnect cannot clear a newer connection selected elsewhere', async () => {
  const gate = deferred(); const ui = harness({remove: () => gate.promise}); await flush();
  const pending = ui.buttons('断开并移除')[0].click(); await flush();
  ui.store.connId = 'C'; ui.store.target = 'new.db'; ui.store.tables = [{name: 'new'}];
  gate.resolve(); await pending; await flush();
  assert.equal(ui.store.connId, 'C'); assert.equal(ui.store.target, 'new.db'); assert.deepEqual(ui.changes, []);
});

test('connection target descriptions omit PostgreSQL credentials and query secrets', async () => {
  const target = 'postgresql://alice:secret@host:5432/app?sslpassword=hidden';
  const ui = harness({connections: [connection('A', target)], current: null}); await flush();
  assert.doesNotMatch(ui.document.textContent, /alice|secret|hidden|sslpassword/);
  assert.match(ui.document.textContent, /host:5432\/app/);
});

test('an explicitly disconnected workspace does not silently restore another live session after refresh', async () => {
  const requests = [];
  const context = loadFrontend('api.js', {
    localStorage: {getItem: () => '', setItem() {}, removeItem() {}},
    fetch: async url => {requests.push(url); return {ok: true, json: async () => url === '/api/connections'
      ? {connections: [connection('B')]} : {target: '/temporary/example.db', tables: []}};},
  });
  const restored = await vm.runInContext('restoreConnection()', context);
  assert.equal(restored, false); assert.equal(vm.runInContext('store.connId', context), null);
  assert.deepEqual(requests, []);
});

test('explicit disconnect wins over a pending automatic restore even while the selected id is still null', async () => {
  const gate = deferred(); let remembered = null;
  const context = loadFrontend('api.js', {
    localStorage: {getItem: () => remembered, setItem: (_, value) => {remembered = value;}, removeItem() {}},
    fetch: async url => ({ok: true, json: async () => url === '/api/connections' ? gate.promise : {target: 'other.db', tables: []}}),
  });
  const pending = vm.runInContext('restoreConnection()', context); await flush();
  vm.runInContext("rememberConnId('')", context);
  gate.resolve({connections: [connection('B')]}); await pending;
  assert.equal(vm.runInContext('store.connId', context), null);
});

test('explicit disconnect remains effective within the page when browser persistence is unavailable', async () => {
  const context = loadFrontend('api.js', {
    localStorage: {getItem: () => null, setItem: () => {throw new Error('disabled');}, removeItem() {}},
    fetch: async url => ({ok: true, json: async () => url === '/api/connections'
      ? {connections: [connection('B')]} : {target: 'other.db', tables: []}}),
  });
  vm.runInContext("rememberConnId('')", context);
  assert.equal(await vm.runInContext('restoreConnection()', context), false);
  assert.equal(vm.runInContext('store.connId', context), null);
});

test('closing the dialog during disconnection still clears an actually removed current server session', async () => {
  const gate = deferred(); const ui = harness({remove: () => gate.promise}); await flush();
  const pending = ui.buttons('断开并移除')[0].click(); await flush(); ui.dialog.close();
  gate.resolve(); await pending;
  assert.equal(ui.store.connId, null); assert.deepEqual(ui.changes, [null]);
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
});

test('nonempty directory results do not append a literal null node and selecting a file fills its path', async () => {
  const ui = harness({current:null, browse: () => ({path:'/temporary',parent:null,entries:[{name:'demo.db',path:'/temporary/demo.db',is_dir:false}]})});
  await flush(); await ui.buttons('选择文件')[0].click(); await flush();
  const browser = ui.document.querySelector('.connection-browser');
  assert.doesNotMatch(browser.textContent, /null|undefined/);
  assert.equal(ui.buttons('上一级')[0].disabled, true);
  await ui.buttons('demo.db')[0].click();
  assert.equal(ui.document.querySelector('[name="db_path"]').value, '/temporary/demo.db');
  assert.equal(browser.hidden, true);
});

test('adding a connection has operation-specific feedback and guards every action during the request', async () => {
  const gate = deferred(); const ui = harness({add: () => gate.promise}); await flush();
  const path = ui.document.querySelector('[name="db_path"]'); path.value = '/temporary/new.db';
  const submit = ui.buttons('连接数据库')[0]; const pending = submit.click(); await flush();
  assert.match(ui.document.querySelector('.connection-notice').textContent, /正在添加连接/);
  assert.equal(ui.document.querySelector('.connection-fields').getAttribute('aria-busy'), 'true');
  assert.equal(ui.buttons('选择文件')[0].disabled, true);
  await submit.click(); await ui.buttons('断开并移除')[0].click(); await ui.buttons('选择文件')[0].click();
  assert.equal(ui.requests.filter(request => request.method === 'POST').length, 1);
  assert.equal(ui.requests.filter(request => request.method === 'DELETE').length, 0);
  assert.equal(ui.requests.filter(request => request.url.startsWith('/api/fs')).length, 0);
  gate.resolve({...connection('N','/temporary/new.db'),tables:[{name:'items'}]}); await pending;
  assert.equal(ui.store.connId, 'N'); assert.equal(ui.store.tables[0].name, 'items');
  assert.deepEqual(ui.changes, ['N']);
});

test('switching and disconnecting identify their pending operation without showing a false connecting state', async () => {
  const gate = deferred(); const ui = harness({connections:[connection('A'),connection('B')],select: () => gate.promise}); await flush();
  const other = ui.document.querySelectorAll('.connection-card')[1];
  const pending = other.click(); await flush();
  assert.match(ui.document.querySelector('.connection-notice').textContent, /正在切换.*example.db/);
  assert.match(ui.document.querySelectorAll('.connection-card')[1].textContent, /正在切换/);
  assert.equal(ui.buttons('连接数据库')[0].disabled, true);
  await other.click(); assert.equal(ui.requests.filter(request => request.url.endsWith('/B/tables')).length, 1);
  gate.resolve({...connection('B'),tables:[]}); await pending;
  assert.equal(ui.store.connId, 'B');

  const removal = deferred(); const second = harness({remove: () => removal.promise}); await flush();
  const disconnect = second.buttons('断开并移除')[0]; const removing = disconnect.click(); await flush();
  assert.match(second.document.querySelector('.connection-notice').textContent, /正在断开.*example.db/);
  assert.equal(second.buttons('正在断开…').length, 1);
  assert.equal(second.buttons('连接数据库')[0].disabled, true);
  await disconnect.click(); assert.equal(second.requests.filter(request => request.method === 'DELETE').length, 1);
  removal.resolve(); await removing;
  assert.match(second.document.querySelector('.connection-notice').textContent, /已断开/);
  assert.equal(second.buttons('连接数据库')[0].disabled, false);
});

test('closing during an add never selects its late response', async () => {
  const gate = deferred(); const ui = harness({add: () => gate.promise}); await flush();
  ui.document.querySelector('[name="db_path"]').value = '/temporary/new.db';
  const pending = ui.buttons('连接数据库')[0].click(); await flush(); ui.dialog.close();
  gate.resolve({...connection('N'),tables:[]}); await pending;
  assert.equal(ui.store.connId, 'A'); assert.deepEqual(ui.changes, []);
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
});

test('a file response arriving during connection mutation cannot replace the disabled file controls', async () => {
  const files = deferred(), addition = deferred();
  const ui = harness({browse: () => files.promise, add: () => addition.promise}); await flush();
  ui.document.querySelector('[name="db_path"]').value = '/temporary/new.db';
  await ui.buttons('选择文件')[0].click();
  const pending = ui.buttons('连接数据库')[0].click(); await flush();
  files.resolve({path:'/temporary',parent:null,entries:[{name:'late.db',path:'/temporary/late.db',is_dir:false}]}); await flush();
  assert.equal(ui.document.querySelector('.connection-browser').hidden, true);
  assert.equal(ui.buttons('late.db').length, 0);
  addition.resolve({...connection('N'),tables:[]}); await pending;
});
