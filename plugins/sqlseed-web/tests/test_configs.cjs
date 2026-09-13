const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const deferred = () => {let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject};};
const plain = value => JSON.parse(JSON.stringify(value));
const config = (id, extra = {}) => ({id, name: `配置 ${id}`, revision: 2, target_key: 'target-A', target_label: 'example.db',
  schema_hash: 'schema-A', updated_at: 1788719235.694131,
  document: {provider: 'faker', locale: 'zh_CN', tables: [{name: 'users', count: 10, columns: []}]}, ...extra});

function harness({records = [config('A'), config('B', {target_label: 'other.db'})], connected = true} = {}) {
  const document = createDom();
  document.createElementNS = (_, tag) => new Element(tag);
  const window = new Element('window'), requests = [], routes = new Map(), downloads = [], events = [];
  const store = {connId: connected ? 'connection-A' : null, target: connected ? 'example.db' : null, tables: []};
  class CustomEvent {constructor(type, {detail} = {}) {this.type = type; this.detail = detail;}}
  class BrowserURL extends URL {static createObjectURL(blob) {downloads.push(blob); return 'blob:export';} static revokeObjectURL() {}}
  const bindings = {document, window, store, CustomEvent, URL: BrowserURL, location: {hash: '#/configs'},
    fetch: async (url, options = {}) => {
      requests.push({url, options});
      const key = `${options.method || 'GET'} ${url}`;
      let result;
      if (routes.has(key)) result = await routes.get(key)(options);
      else if (url.startsWith('/api/workbench/drafts') && (options.method || 'GET') === 'GET' && !url.includes('/export')) result = records;
      else throw new Error(`Unexpected ${key}`);
      return result?.httpError ? {ok: false, status: result.httpError, json: async () => ({detail: {message: result.message}})}
        : {ok: true, json: async () => result};
    },
  };
  document.trackFocus = element => {document.activeElement = element;};
  const oldCreate = document.createElement;
  document.createElement = tag => {const element = oldCreate(tag); element.focus = () => document.trackFocus(element); return element;};
  const ui = loadFrontend('workbench/ui.js', bindings);
  const api = vm.createContext(bindings);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/sqlseed_web/static/js/api.js'), 'utf8').replace(/^export /gm, ''), api);
  const context = loadFrontend('pages/configs.js', {...bindings, ...vm.runInContext('({safeTargetLabel})', api),
    ...vm.runInContext('({button, modal, download, icon})', ui)});
  for (const type of ['sqlseed:draft-deleted', 'sqlseed:draft-renamed']) window.addEventListener(type, event => events.push({type, detail: event.detail}));
  let root;
  const mount = async () => {root = context.render(); document.body.append(root); await context.mount();};
  const leave = () => {context.unmount(); root?.remove();};
  const button = (label, scope = document) => {
    const found = scope.querySelectorAll('button').find(node => node.textContent === label);
    assert.ok(found, `Missing button ${label}`); return found;
  };
  const card = id => root.querySelector(`[data-config-id="${id}"]`);
  const edit = async (label, value) => {const input = document.querySelector(`[aria-label="${label}"]`); assert.ok(input); input.value = value; await input.dispatchEvent('input'); return input;};
  return {document, window, store, requests, routes, downloads, events, context, mount, leave, button, card, edit,
    root: () => root, dialog: () => document.querySelector('[role="dialog"]')};
}

test('configuration page has explicit actions, current-target filter and saved metadata', async () => {
  const ui = harness(); await ui.mount();
  assert.equal(ui.root().querySelector('h1').textContent, '配置管理');
  assert.equal(ui.requests[0].url, '/api/workbench/drafts?conn_id=connection-A');
  assert.equal(ui.root().querySelectorAll('[data-config-id]').length, 2);
  assert.match(ui.card('A').textContent, /example.db/);
  assert.match(ui.card('A').textContent, /Faker.*zh_CN/);
  assert.match(ui.card('A').textContent, /1 张表.*10 行/);
  assert.doesNotMatch(ui.card('A').textContent, /1788719235/);
  assert.equal(ui.card('A').querySelector('a').getAttribute('href'), '#/workbench?draft=A');
  assert.equal(ui.root().querySelectorAll('a').find(a => a.textContent.includes('新建配置')).getAttribute('href'), '#/workbench?new=1');
  assert.equal(ui.root().querySelectorAll('a').find(a => a.textContent.includes('导入配置')).getAttribute('href'), '#/workbench?new=1&import=1');
});

test('search matches configuration names and targets without reloading or changing records', async () => {
  const ui = harness(); await ui.mount(); await ui.edit('查找配置', 'OTHER');
  assert.equal(ui.card('A'), null); assert.ok(ui.card('B'));
  await ui.edit('查找配置', '不存在');
  assert.match(ui.root().textContent, /没有匹配的配置/);
  await ui.edit('查找配置', '');
  assert.equal(ui.root().querySelectorAll('[data-config-id]').length, 2);
  assert.equal(ui.requests.length, 1);
});

test('without a connection configurations remain manageable and current-target filter explains its state', async () => {
  const ui = harness({connected: false}); await ui.mount();
  assert.equal(ui.requests[0].url, '/api/workbench/drafts');
  assert.ok(ui.root().querySelector('[aria-label="仅当前数据库"]').disabled);
  assert.match(ui.root().textContent, /连接数据库后可按当前库筛选/);
  assert.ok(ui.card('A'));
});

test('empty list gives a useful new configuration action', async () => {
  const ui = harness({records: []}); await ui.mount();
  assert.match(ui.root().textContent, /还没有保存的配置/);
  assert.ok(ui.root().querySelector('a[href="#/workbench?new=1"]'));
});

test('delete requires explicit confirmation and initially focuses Cancel', async () => {
  const ui = harness(); await ui.mount(); await ui.button('删除', ui.card('A')).click();
  assert.match(ui.dialog().textContent, /配置 A/);
  assert.match(ui.dialog().textContent, /运行记录.*数据库/);
  assert.equal(ui.document.activeElement, ui.button('取消', ui.dialog()));
  assert.equal(ui.requests.length, 1);
  await ui.button('取消', ui.dialog()).click();
  assert.equal(ui.dialog(), null);
  assert.equal(ui.requests.length, 1);
});

test('successful delete sends CAS revision, removes card and publishes detached-draft event', async () => {
  const records = [config('A'), config('B')], ui = harness({records}); await ui.mount();
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => {records.shift(); return {id: 'A', revision: 2, deleted: true};});
  await ui.button('删除', ui.card('A')).click(); await ui.button('删除配置', ui.dialog()).click();
  assert.equal(ui.dialog(), null); assert.equal(ui.card('A'), null); assert.ok(ui.card('B'));
  assert.deepEqual(plain(ui.events), [{type: 'sqlseed:draft-deleted', detail: {id: 'A', revision: 2}}]);
  assert.match(ui.root().querySelector('[role="status"]').textContent, /已删除.*配置 A/);
});

test('deletion conflict preserves configuration, refreshes latest revision and explains how to retry', async () => {
  const records = [config('A')], ui = harness({records}); await ui.mount();
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => {records[0] = config('A', {revision: 3}); return {httpError: 409, message: 'updated'};});
  await ui.button('删除', ui.card('A')).click(); await ui.button('删除配置', ui.dialog()).click();
  assert.ok(ui.card('A')); assert.equal(ui.events.length, 0);
  assert.match(ui.dialog().querySelector('[role="alert"]').textContent, /配置已被.*更新/);
  assert.ok(ui.button('删除配置', ui.dialog()).disabled);
  assert.match(ui.card('A').textContent, /v3/);
});

test('rename edits only metadata, sends revision and announces the accepted change', async () => {
  const records = [config('A')], ui = harness({records}); await ui.mount();
  ui.routes.set('PATCH /api/workbench/drafts/A', options => {
    assert.deepEqual(JSON.parse(options.body), {revision: 2, name: '新名称'});
    return records[0] = {...records[0], name: '新名称', revision: 3};
  });
  await ui.button('重命名', ui.card('A')).click(); await ui.edit('配置名称', ' 新名称 ');
  await ui.button('保存名称', ui.dialog()).click();
  assert.match(ui.card('A').textContent, /新名称/);
  assert.deepEqual(plain(ui.events), [{type: 'sqlseed:draft-renamed', detail: {id: 'A', revision: 3, name: '新名称'}}]);
});

test('copy creates a new independently named card without overwriting the original', async () => {
  const records = [config('A')], ui = harness({records}); await ui.mount();
  ui.routes.set('POST /api/workbench/drafts/A/copy', options => {
    assert.deepEqual(JSON.parse(options.body), {revision: 2, name: '测试副本'});
    const copy = config('copy', {name: '测试副本', revision: 1}); records.unshift(copy); return copy;
  });
  await ui.button('复制', ui.card('A')).click(); await ui.edit('配置名称', '测试副本');
  await ui.button('创建副本', ui.dialog()).click();
  assert.ok(ui.card('A')); assert.ok(ui.card('copy'));
  assert.equal(ui.card('copy').querySelector('a').getAttribute('href'), '#/workbench?draft=copy');
});

test('empty names are rejected before any request', async () => {
  const ui = harness(); await ui.mount(); await ui.button('重命名', ui.card('A')).click();
  await ui.edit('配置名称', ' '); await ui.button('保存名称', ui.dialog()).click();
  assert.equal(ui.requests.length, 1);
  assert.match(ui.dialog().textContent, /请输入配置名称/);
});

test('keyboard Enter accepts a name and Escape cancels a deletion without sending it', async () => {
  const records = [config('A')], ui = harness({records}); await ui.mount();
  ui.routes.set('PATCH /api/workbench/drafts/A', options => {
    records[0] = {...records[0], name: JSON.parse(options.body).name, revision: 3}; return records[0];
  });
  await ui.button('重命名', ui.card('A')).click(); const input = await ui.edit('配置名称', '键盘修改');
  await input.dispatchEvent({type: 'keydown', key: 'Enter'});
  assert.equal(ui.dialog(), null); assert.match(ui.card('A').textContent, /键盘修改/);
  await ui.button('删除', ui.card('A')).click();
  await ui.document.dispatchEvent({type: 'keydown', key: 'Escape'});
  assert.equal(ui.dialog(), null);
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 0);
});

test('connection change refreshes the active scope and unmount removes the listener', async () => {
  const ui = harness(); await ui.mount();
  ui.store.connId = 'connection-B'; ui.store.target = 'other.db';
  await ui.window.dispatchEvent('sqlseed:connection-changed');
  assert.equal(ui.requests.at(-1).url, '/api/workbench/drafts?conn_id=connection-B');
  assert.match(ui.root().textContent, /当前：other.db/);
  ui.leave(); const before = ui.requests.length;
  await ui.window.dispatchEvent('sqlseed:connection-changed');
  assert.equal(ui.requests.length, before);
});

test('export downloads saved JSON and YAML offline without mutating configuration', async () => {
  const ui = harness({connected: false}); await ui.mount();
  ui.routes.set('GET /api/workbench/drafts/A/export', () => ({...config('A'), json: config('A').document, yaml: 'tables: []\n'}));
  await ui.button('导出', ui.card('A')).click(); await ui.button('下载 JSON', ui.dialog()).click();
  assert.equal(ui.downloads.length, 1); assert.deepEqual(JSON.parse(await ui.downloads[0].text()), config('A').document);
  await ui.button('下载 YAML', ui.dialog()).click();
  assert.equal(await ui.downloads[1].text(), 'tables: []\n');
  assert.ok(ui.requests.every(request => !request.options.method));
});

test('switching filter ignores stale list responses from previous scope', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('GET /api/workbench/drafts?conn_id=connection-A', () => gate.promise);
  const old = ui.button('刷新列表').click();
  ui.root().querySelector('[aria-label="仅当前数据库"]').checked = false;
  await ui.root().querySelector('[aria-label="仅当前数据库"]').dispatchEvent('change');
  gate.resolve([config('stale')]); await old;
  assert.equal(ui.card('stale'), null); assert.ok(ui.card('A'));
});

test('leaving with an accepted delete in flight still publishes lifecycle event but never remounts UI', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => gate.promise);
  await ui.button('删除', ui.card('A')).click(); const pending = ui.button('删除配置', ui.dialog()).click();
  ui.leave(); gate.resolve({id: 'A', revision: 2, deleted: true}); await pending;
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.equal(ui.events.length, 1);
  assert.equal(ui.requests.filter(request => !request.options.method).length, 1);
});

test('closing an export dialog ignores its late response and does not download', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('GET /api/workbench/drafts/A/export', () => gate.promise);
  await ui.button('导出', ui.card('A')).click(); const pending = ui.button('下载 JSON', ui.dialog()).click();
  await ui.button('关闭', ui.dialog()).click();
  gate.resolve({...config('A'), json: config('A').document, yaml: ''}); await pending;
  assert.equal(ui.downloads.length, 0); assert.equal(ui.dialog(), null);
});

test('a late rename failure cannot alter a newer delete confirmation', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('PATCH /api/workbench/drafts/A', () => gate.promise);
  await ui.button('重命名', ui.card('A')).click(); await ui.edit('配置名称', 'First');
  const pending = ui.button('保存名称', ui.dialog()).click(); await ui.button('取消', ui.dialog()).click();
  await ui.button('删除', ui.card('B')).click(); const next = ui.dialog();
  gate.reject(new Error('old failure')); await pending;
  assert.equal(ui.dialog(), next); assert.doesNotMatch(next.textContent, /old failure/);
});
