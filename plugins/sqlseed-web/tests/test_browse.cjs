const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {loadFrontend} = require('./frontend_helpers.cjs');

function setup(override) {
  const saved = new Map();
  const requests = [];
  const connections = [{conn_id: 'A', target: '/tmp/a.db'}, {conn_id: 'B', target: '/tmp/b.db'}];
  const get = async (url) => {
    requests.push(url);
    if (override) {
      const value = override(url);
      if (value !== undefined) return value;
    }
    if (url === '/api/connections') return {connections};
    const id = url.split('/')[3];
    if (url.endsWith('/tables')) return {target: `/tmp/${id.toLowerCase()}.db`, tables: [{name: id === 'A' ? 'alpha' : 'beta', row_count: 1}]};
    if (url.endsWith('/schema')) return {row_count: 1, columns: [{name: 'value'}], foreign_keys: []};
    if (url.endsWith('/mapping')) return {mapping: {value: {generator_name: 'string'}}};
    if (url.includes('/rows?')) return {rows: [{value: id}], total: 1};
    throw new Error(`Unexpected URL: ${url}`);
  };
  const context = loadFrontend('pages/browse.js', {get, localStorage: {
    getItem: (key) => saved.get(key), setItem: (key, val) => saved.set(key, val), removeItem: (key) => saved.delete(key),
  }});
  context.document.body.append(context.h('span', {id: 'conn-badge'}));
  context.document.body.append(context.render());
  return {context, saved, requests};
}

test('each connection has its own table list, including after a browser refresh', async () => {
  const {context} = setup();
  await vm.runInContext('loadLeft()', context);
  const names = context.document.getElementById('browse-left').querySelectorAll('.col-row').map((row) => row.textContent);
  assert.equal(names.length, 2);
  assert.match(names[0], /alpha/);
  assert.match(names[1], /beta/);
});

test('selecting another connection synchronizes its target, tables and remembered ID', async () => {
  const {context, saved} = setup();
  await vm.runInContext("selectTable('B', 'beta')", context);
  assert.equal(context.store.connId, 'B');
  assert.equal(context.store.target, '/tmp/b.db');
  assert.equal(context.store.tables[0].name, 'beta');
  assert.equal(saved.get('sqlseed.connId'), 'B');
  assert.match(context.document.getElementById('browse-center').textContent, /beta.*B/);
  assert.doesNotMatch(context.document.getElementById('browse-right').textContent, /null/);
});

test('failed selection displays an error instead of leaving the loading indicator', async () => {
  const {context} = setup((url) => url.endsWith('/schema') ? Promise.reject(new Error('table no longer exists')) : undefined);
  await vm.runInContext("selectTable('A', 'alpha')", context);
  const center = context.document.getElementById('browse-center');
  assert.match(center.textContent, /table no longer exists/);
  assert.equal(center.querySelector('.loading'), null);
});

test('a slower previous selection cannot replace the new connection or grid', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const {context} = setup((url) => url === '/api/connections/A/tables' ? gate : undefined);
  const first = vm.runInContext("selectTable('A', 'alpha')", context);
  const second = vm.runInContext("selectTable('B', 'beta')", context);
  await new Promise(setImmediate);
  release({target: '/tmp/a.db', tables: [{name: 'alpha', row_count: 1}]});
  await Promise.all([first, second]);
  assert.equal(context.store.connId, 'B');
  assert.equal(context.store.target, '/tmp/b.db');
  assert.match(context.document.getElementById('browse-center').textContent, /beta.*B/);
});

test('a broken connection does not hide healthy connections', async () => {
  const {context} = setup((url) => url === '/api/connections/A/tables' ? Promise.reject(new Error('database unavailable')) : undefined);
  await vm.runInContext('loadLeft()', context);
  const left = context.document.getElementById('browse-left');
  assert.match(left.textContent, /database unavailable/);
  assert.match(left.textContent, /beta/);
});

test('switching pages ignores an in-flight selection', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const {context} = setup((url) => url.endsWith('/schema') ? gate : undefined);
  const first = vm.runInContext("selectTable('A', 'alpha')", context);
  await new Promise(setImmediate);
  context.document.querySelector('.browse').remove();
  context.document.body.append(context.render());
  release({row_count: 1, columns: [], foreign_keys: []});
  await first;
  assert.match(context.document.getElementById('browse-center').textContent, /在左侧选择/);
});
