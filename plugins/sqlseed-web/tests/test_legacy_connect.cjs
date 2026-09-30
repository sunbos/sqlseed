const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(get, remove = async () => {}) {
  const document = createDom(), store = {connId:'current',target:'current.db',tables:[]};
  const removals = [], reloads = [];
  const dropdown = loadFrontend('dropdown.js', {document});
  const context = loadFrontend('pages/connect.js', {document, store, get,
    createDropdown:dropdown.createDropdown, location:{reload:() => reloads.push(true)},
    del:async url => {removals.push(url); return remove();}});
  return {document, store, context, removals, reloads, render:() => {
    const root = context.render(); document.body.append(root); return root;
  }};
}

test('legacy initial failures report both unavailable resources and retain a usable locale', async () => {
  const calls = [];
  const ui = harness(async url => {calls.push(url); throw new Error('service unavailable');});
  const before = JSON.stringify(ui.store), root = ui.render(); await tick();
  assert.match(root.textContent, /无法读取语言列表，保留当前语言与地区：service unavailable/);
  assert.match(root.textContent, /无法读取已有连接：service unavailable/);
  assert.equal(vm.runInContext('form.locale', ui.context), 'zh_CN');
  assert.equal(vm.runInContext('localeDd.get()', ui.context), 'zh_CN');
  assert.doesNotMatch(root.textContent, /加载中/);
  assert.equal(JSON.stringify(ui.store), before);
  assert.deepEqual(calls, ['/api/meta/locales','/api/connections']);
});

function connectionResponse(url) {
  if (url === '/api/meta/locales') return {default:'en_US',locales:[{code:'en_US',label:'English'}]};
  return {connections:[{conn_id:'current',target:'current.db',provider:'base',locale:'en_US'}]};
}

test('legacy disconnect rejection preserves the current connection and shows its cause locally', async () => {
  const ui = harness(connectionResponse, () => {throw new Error('connection busy');});
  const root = ui.render(); await tick();
  const before = JSON.stringify(ui.store);
  await root.querySelectorAll('button').find(button => button.textContent === '断开').click();
  assert.match(root.textContent, /无法断开连接：connection busy/);
  assert.equal(JSON.stringify(ui.store), before);
  assert.deepEqual(ui.reloads, []);
  assert.deepEqual(ui.removals, ['/api/connections/current']);
});

for (const failed of [false, true]) test(`late legacy disconnect cannot reload or overwrite the new page (failure=${failed})`, async () => {
  let finish;
  const gate = new Promise(resolve => {finish = resolve;});
  const ui = harness(connectionResponse, async () => {await gate; if (failed) throw new Error('obsolete disconnect failure');});
  const old = ui.render(); await tick();
  const pending = old.querySelectorAll('button').find(button => button.textContent === '断开').click();
  old.remove();
  ui.store.connId = 'new'; ui.store.target = 'new.db';
  const current = ui.render(); await tick();
  const snapshot = current.textContent;
  finish(); await pending;
  assert.equal(current.textContent, snapshot);
  assert.doesNotMatch(old.textContent, /obsolete disconnect failure/);
  assert.equal(ui.store.connId, 'new');
  assert.equal(ui.store.target, 'new.db');
  assert.deepEqual(ui.reloads, []);
  assert.deepEqual(ui.removals, ['/api/connections/current']);
});

for (const failed of [false, true]) test(`late legacy startup result cannot change a new render (failure=${failed})`, async () => {
  let release, generation = 1;
  const gate = new Promise(resolve => {release = resolve;});
  const ui = harness(async url => {
    const old = generation === 1;
    if (old) {
      await gate;
      if (failed) throw new Error('obsolete request failure');
    }
    if (url === '/api/meta/locales') {
      const locale = old ? 'zh_CN' : 'en_US';
      return {default:locale,locales:[{code:locale,label:locale}]};
    }
    return {connections:[{conn_id:old ? 'old' : 'new',target:old ? 'old.db' : 'new.db',provider:'base',locale:'en_US'}]};
  });
  const old = ui.render(); old.remove(); generation = 2;
  const current = ui.render(); await tick();
  const snapshot = current.textContent;
  assert.match(snapshot, /new.db/);
  release(); await tick();
  assert.equal(current.textContent, snapshot);
  assert.doesNotMatch(current.textContent, /old.db|obsolete request/);
  assert.equal(vm.runInContext('form.locale', ui.context), 'en_US');
  assert.equal(vm.runInContext('localeDd.get()', ui.context), 'en_US');
  assert.equal(ui.store.connId, 'current');
});
