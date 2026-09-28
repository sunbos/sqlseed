const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
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
  const api = loadFrontend('api.js', bindings);
  const context = loadFrontend('pages/configs.js', {...bindings, ...vm.runInContext('({safeTargetLabel})', api),
    ...vm.runInContext('({button, modal, download, icon})', ui)});
  for (const type of ['sqlseed:draft-deleted', 'sqlseed:draft-renamed']) window.addEventListener(type, event => events.push({type, detail: event.detail}));
  let root;
  const mount = async () => {root = context.render(); document.body.append(root); await context.mount();};
  const leave = () => {context.unmount(); root?.remove();};
  const button = (label, scope = document) => {
    const found = scope.querySelectorAll('button').find(node => node.textContent === label || node.getAttribute('aria-label') === label);
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

for (const [operation, confirmLabel, method, suffix] of [
  ['重命名', '保存名称', 'PATCH', ''], ['复制', '创建副本', 'POST', '/copy'],
]) {
  test(`${operation} associates local validation with the input and clears it on editing`, async () => {
    const records = [config('A')], ui = harness({records}); await ui.mount();
    await ui.button(operation, ui.card('A')).click();
    const input = await ui.edit('配置名称', ' ');
    const confirm = ui.button(confirmLabel, ui.dialog());
    await confirm.click();
    assert.equal(ui.requests.length, 1);
    assert.equal(input.getAttribute('aria-invalid'), 'true');
    const error = ui.document.getElementById(input.getAttribute('aria-describedby'));
    assert.ok(error && ui.dialog().contains(error));
    assert.equal(error.getAttribute('role'), 'alert');
    assert.match(error.textContent, /请输入配置名称/);
    assert.equal(ui.document.activeElement, input);
    await ui.edit('配置名称', '长'.repeat(201));
    assert.equal(input.getAttribute('aria-invalid'), null);
    assert.equal(input.getAttribute('aria-describedby'), null);
    assert.equal(error.textContent, '');
    await confirm.click();
    assert.equal(input.getAttribute('aria-invalid'), 'true');
    assert.equal(ui.document.getElementById(input.getAttribute('aria-describedby')), error);
    assert.match(error.textContent, /不能超过 200 个字符/);
    assert.equal(ui.document.activeElement, input);
    assert.equal(ui.requests.length, 1);
    const validName = '名'.repeat(200);
    await ui.edit('配置名称', validName);
    assert.equal(input.getAttribute('aria-invalid'), null);
    assert.equal(error.textContent, '');
    ui.routes.set(`${method} /api/workbench/drafts/A${suffix}`, options => {
      assert.deepEqual(JSON.parse(options.body), {revision: 2, name: validName});
      return config(operation === '复制' ? 'copy' : 'A', {name: validName, revision: 3});
    });
    await confirm.click();
    assert.equal(ui.dialog(), null);
    assert.equal(ui.requests.filter(request => request.options.method === method).length, 1);
  });

  for (const status of [503, 409]) {
    test(`${operation} retains service failure ${status} when editing the name`, async () => {
      const ui = harness(); await ui.mount();
      ui.routes.set(`${method} /api/workbench/drafts/A${suffix}`, () => ({httpError: status, message: '服务暂不可用'}));
      await ui.button(operation, ui.card('A')).click();
      const input = await ui.edit('配置名称', '有效名称');
      const confirm = ui.button(confirmLabel, ui.dialog());
      await confirm.click();
      const error = ui.dialog().querySelector('[role="alert"]');
      const message = error.textContent;
      assert.match(message, status === 409 ? /配置已被其他操作更新/ : /未能确认操作结果.*服务暂不可用/);
      assert.equal(input.getAttribute('aria-invalid'), null);
      await ui.edit('配置名称', '另一有效名称');
      assert.equal(error.textContent, message);
      assert.equal(confirm.disabled, status === 409);
      assert.equal(ui.requests.filter(request => request.options.method === method).length, 1);
    });
  }
}

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

async function selectConfig(ui, id, checked = true) {
  const checkbox = ui.card(id).querySelector('[data-config-select]');
  checkbox.checked = checked;
  await checkbox.dispatchEvent('change');
  return checkbox;
}

async function selectVisible(ui) {
  const checkbox = ui.root().querySelector('[aria-label="全选当前筛选结果"]');
  checkbox.checked = true;
  await checkbox.dispatchEvent('change');
}

test('bulk selection keeps checkbox focus and selects only current filtered results', async () => {
  const ui = harness(); await ui.mount();
  const first = await selectConfig(ui, 'A'); first.focus();
  assert.equal(ui.card('A').querySelector('[data-config-select]'), first);
  assert.equal(ui.document.activeElement, first);
  const all = ui.root().querySelector('[aria-label="全选当前筛选结果"]');
  assert.equal(all.indeterminate, true);
  await ui.edit('查找配置', 'other.db');
  assert.match(ui.root().querySelector('.config-selection-count').textContent, /已选 0 份/);
  await selectVisible(ui);
  assert.equal(all.checked, true);
  await ui.button('删除所选').click();
  assert.match(ui.dialog().querySelector('.config-delete-list').textContent, /配置 B.*other.db.*v2/);
  assert.doesNotMatch(ui.dialog().querySelector('.config-delete-list').textContent, /配置 A/);
  assert.equal(ui.dialog().querySelectorAll('button').length, 2, 'Only cancel and confirmed deletion are shown');
  assert.equal(ui.document.activeElement, ui.button('取消', ui.dialog()));
  await ui.button('取消', ui.dialog()).click();
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 0);
});

test('bulk deletion sends only confirmed IDs and revisions and announces every successful removal', async () => {
  const records = [config('A'), config('B'), config('C')], ui = harness({records}); await ui.mount();
  await selectConfig(ui, 'A'); await selectConfig(ui, 'B');
  for (const id of ['A', 'B']) ui.routes.set(`DELETE /api/workbench/drafts/${id}?revision=2`, () => {
    records.splice(records.findIndex(record => record.id === id), 1); return {deleted: true};
  });
  await ui.button('删除所选').click();
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 0);
  await ui.button('删除 2 份配置', ui.dialog()).click();
  assert.equal(ui.dialog(), null);
  assert.equal(ui.card('A'), null); assert.equal(ui.card('B'), null); assert.ok(ui.card('C'));
  assert.deepEqual(ui.requests.filter(request => request.options.method === 'DELETE').map(request => request.url),
    ['/api/workbench/drafts/A?revision=2', '/api/workbench/drafts/B?revision=2']);
  assert.deepEqual(plain(ui.events).map(event => event.detail), [{id: 'A', revision: 2}, {id: 'B', revision: 2}]);
  assert.match(ui.root().querySelector('.config-notice').textContent, /已删除 2 份.*运行记录和数据库数据均保留/);
  assert.equal(ui.button('删除所选').disabled, true);
});

test('bulk deletion preserves conflicts, reports already-missing items and never retries updated versions', async () => {
  const records = [config('A'), config('B'), config('C'), config('D')], ui = harness({records}); await ui.mount();
  await selectVisible(ui);
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => {records.shift(); return {deleted: true};});
  ui.routes.set('DELETE /api/workbench/drafts/B?revision=2', () => {
    records[0] = config('B', {revision: 3}); return {httpError: 409, message: 'changed'};
  });
  ui.routes.set('DELETE /api/workbench/drafts/C?revision=2', () => {
    records.splice(records.findIndex(record => record.id === 'C'), 1); return {httpError: 404, message: 'gone'};
  });
  ui.routes.set('DELETE /api/workbench/drafts/D?revision=2', () => {records.pop(); return {deleted: true};});
  await ui.button('删除所选').click(); await ui.button('删除 4 份配置', ui.dialog()).click();
  assert.match(ui.dialog().textContent, /已删除 2 份.*1 份已不存在.*1 份需核对/);
  assert.match(ui.dialog().querySelector('[role="alert"]').textContent, /配置 B：已被更新，本次未删除/);
  assert.equal(ui.button('删除 4 份配置', ui.dialog()).disabled, true);
  assert.match(ui.card('B').textContent, /v3/);
  assert.equal(ui.card('B').querySelector('[data-config-select]').checked, false);
  assert.deepEqual(ui.requests.filter(request => request.options.method === 'DELETE').map(request => request.url),
    ['A', 'B', 'C', 'D'].map(id => `/api/workbench/drafts/${id}?revision=2`));
  assert.deepEqual(plain(ui.events).map(event => event.detail.id), ['A', 'C', 'D']);
});

test('an unknown bulk deletion result stops further requests and requires explicit fresh review', async () => {
  const records = [config('A'), config('B'), config('C')], ui = harness({records}); await ui.mount();
  await selectVisible(ui);
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => {records.shift(); return {deleted: true};});
  ui.routes.set('DELETE /api/workbench/drafts/B?revision=2', () => {throw new Error('connection lost');});
  await ui.button('删除所选').click(); await ui.button('删除 3 份配置', ui.dialog()).click();
  assert.match(ui.dialog().textContent, /已删除 1 份.*1 份需核对.*1 份未处理/);
  assert.match(ui.dialog().querySelector('[role="alert"]').textContent, /未能确认删除结果/);
  assert.ok(ui.card('B')); assert.ok(ui.card('C'));
  await ui.button('删除 3 份配置', ui.dialog()).click();
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 2);
});

test('stopping a pending batch allows its accepted request to finish but starts no further deletion', async () => {
  const records = [config('A'), config('B')], ui = harness({records}); await ui.mount();
  const gate = deferred(); await selectVisible(ui);
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => gate.promise);
  await ui.button('删除所选').click();
  const confirm = ui.button('删除 2 份配置', ui.dialog()), pending = confirm.click();
  await confirm.click();
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 1);
  await ui.button('停止后续删除', ui.dialog()).click();
  assert.equal(ui.button('删除所选').disabled, true, 'Another batch cannot overlap the accepted request');
  records.shift(); gate.resolve({deleted: true}); await pending;
  assert.equal(ui.dialog(), null); assert.ok(ui.card('B'));
  assert.match(ui.root().querySelector('.config-notice').textContent, /已删除 1 份.*1 份未处理/);
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 1);
});

test('leaving a pending batch publishes its accepted deletion without continuing or touching a new page', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred(); await selectVisible(ui);
  ui.routes.set('DELETE /api/workbench/drafts/A?revision=2', () => gate.promise);
  await ui.button('删除所选').click(); const pending = ui.button('删除 2 份配置', ui.dialog()).click();
  ui.leave(); await ui.mount(); await selectConfig(ui, 'B');
  gate.resolve({deleted: true}); await pending;
  assert.equal(ui.requests.filter(request => request.options.method === 'DELETE').length, 1);
  assert.equal(ui.events.length, 1);
  assert.equal(ui.card('B').querySelector('[data-config-select]').checked, true);
  assert.equal(ui.button('删除所选').disabled, false);
});

test('refreshing updated revisions and changing database scope clear obsolete bulk selections', async () => {
  const records = [config('A')], ui = harness({records}); await ui.mount(); await selectVisible(ui);
  records[0] = config('A', {revision: 3}); await ui.button('刷新列表').click();
  assert.equal(ui.card('A').querySelector('[data-config-select]').checked, false);
  await selectVisible(ui); ui.store.connId = 'connection-B';
  await ui.window.dispatchEvent('sqlseed:connection-changed');
  assert.equal(ui.card('A').querySelector('[data-config-select]').checked, false);
  assert.equal(ui.button('删除所选').disabled, true);
});

test('language switching preserves configuration selection, filters and an open duplicate form', async () => {
  const record = config('用户配置', {name: '订单 · 用户名称'}), ui = harness({records: [record]});
  await ui.mount();
  const search = await ui.edit('查找配置', '订单');
  const selection = ui.card(record.id).querySelector('[data-config-select]');
  selection.checked = true; await selection.dispatchEvent('change');
  const requests = ui.requests.length;
  ui.context.setLanguage('en');
  assert.equal(ui.root().querySelector('h1').textContent, 'Configurations');
  assert.equal(search.getAttribute('placeholder'), 'Configuration name or database');
  assert.equal(search.value, '订单');
  assert.equal(ui.card(record.id).querySelector('[data-config-select]'), selection);
  assert.equal(selection.checked, true);
  assert.equal(selection.getAttribute('aria-label'), 'Select configuration: 订单 · 用户名称');
  assert.match(ui.root().textContent, /1 selected.*Search: “订单”/);
  await ui.button('Duplicate', ui.card(record.id)).click();
  const dialog = ui.dialog(), input = dialog.querySelector('input');
  assert.equal(input.value, '订单 · 用户名称 copy');
  input.value = '我的未保存副本'; input.selectionStart = 3; input.focus();
  ui.context.setLanguage('zh-CN');
  assert.equal(ui.dialog(), dialog);
  assert.equal(input.value, '我的未保存副本');
  assert.equal(input.selectionStart, 3);
  assert.equal(ui.document.activeElement, input);
  assert.equal(input.getAttribute('aria-label'), '配置名称');
  assert.equal(ui.requests.length, requests, 'language changes and opening the form perform no request');
  assert.equal(record.name, '订单 · 用户名称');
  assert.equal(ui.context.missingMessages().length, 0);
  ui.leave();
});

test('configuration table and row counts pluralize independently and retain formatted large values', async () => {
  const single = config('single', {document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 1}]}});
  const multiple = config('multiple', {document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 999}, {name: 'orders', count: 1}]}});
  const ui = harness({records: [single, multiple]});
  await ui.mount();
  const calls = ui.requests.length;
  ui.context.setLanguage('en');
  assert.equal(ui.card('single').querySelector('.config-facts').textContent, '1 table · 1 row · Base · en_US');
  assert.equal(ui.card('multiple').querySelector('.config-facts').textContent, '2 tables · 1,000 rows · Base · en_US');
  ui.context.setLanguage('zh-CN');
  assert.equal(ui.card('single').querySelector('.config-facts').textContent, '1 张表 · 1 行 · Base · en_US');
  assert.equal(ui.requests.length, calls);
  assert.equal(single.document.tables[0].count, 1);
  assert.equal(multiple.document.tables[0].count, 999);
  ui.leave();
});
