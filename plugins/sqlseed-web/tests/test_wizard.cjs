const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const { loadFrontend } = require('./frontend_helpers.cjs');

function node(...children) {
  return {
    children, value: '2', disabled: false,
    append(...values) { this.children.push(...values.filter((v) => v != null)); },
    replaceChildren(...values) { this.children = values; },
    get lastChild() { return this.children.at(-1); },
    querySelector() { return null; },
  };
}
function textOf(value) {
  return typeof value === 'object' ? (value?.children || []).map(textOf).join(' ') : String(value);
}
function fixture(overrides = {}) {
  const out = node();
  const count = node();
  const store = { connId: 'A', target: '/tmp/A.db', tables: [{ name: 'one' }, { name: 'two' }] };
  const c = loadFrontend('pages/wizard.js', {
    store, document: { getElementById: (id) => id === 'gen-count' ? count : out, querySelector: () => null },
    h: (tag, attrs, ...children) => Object.assign(node(...children), attrs),
    msg: (value, kind) => Object.assign(node(value), { kind }),
    clear: (el) => el.replaceChildren(), table: () => node(), fmt: String,
    get: async (path) => {
      if (path === '/api/meta/generators') return { names: ['integer'], params: {} };
      if (path === '/api/ai/config') return { available: false };
      if (path === '/api/connections') return { connections: [{ conn_id: 'A' }, { conn_id: 'B' }] };
      if (path.endsWith('/schema')) return { columns: [{ name: 'value' }], row_count: 0 };
      if (path.endsWith('/mapping')) return { mapping: { value: { generator_name: 'integer' } } };
      if (path.includes('topo-order')) return { tables: ['one', 'two'] };
      return { status: 'done', rows_inserted: 2 };
    }, post: async () => ({ job_id: 'job' }), ...overrides,
  });
  vm.runInContext(`tablesMeta = ['one', 'two'].map(name => ({name, columns: [{name:'value'}], specs: {value: {generator_name:'integer'}}})); cfg = new Map(tablesMeta.map(t => [t.name, new Map([['value', {generator:'integer', params:{min_value:7,max_value:7}}]])]));`, c);
  return { c, out, store, count, run: (code) => vm.runInContext(code, c) };
}
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
const plain = (value) => value === undefined ? undefined : JSON.parse(JSON.stringify(value));

test('generation freezes connection, selected tables and nested configuration before its first await', async () => {
  const topo = deferred();
  const calls = [];
  const f = fixture({
    get: async (path) => path.includes('topo-order') ? topo.promise : { status: 'done', rows_inserted: 2 },
    post: async (path, payload) => { calls.push({ path, payload: plain(payload) }); return { job_id: 'job' }; },
  });
  const running = f.run('doGenerate(tablesMeta)');
  f.store.connId = 'B';
  f.run(`cfg.get('two').get('value').params.min_value = 999; tablesMeta = [{name:'unrelated'}];`);
  f.count.value = '999';
  topo.resolve({ tables: ['one', 'two'] });
  await assert.doesNotReject(running);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(({ path }) => path === '/api/connections/A/fill'));
  assert.equal(calls[1].payload.columns.value.params.min_value, 7);
  assert.equal(calls[1].payload.count, 2);
});

test('failed fill stops later tables and never reports complete success', async () => {
  const calls = [];
  const f = fixture({
    get: async (path) => path.includes('topo-order') ? { tables: ['one', 'two'] } : { status: 'error', error: 'CHECK failed', rows_inserted: 0 },
    post: async (path) => { calls.push(path); return { job_id: 'bad' }; },
  });
  await f.run('doGenerate(tablesMeta)');
  assert.equal(calls.length, 1);
  assert.match(textOf(f.out), /CHECK failed/);
  assert.doesNotMatch(textOf(f.out), /全部完成/);
});

test('legacy done results containing errors are treated as failures', async () => {
  const calls = [];
  const f = fixture({
    get: async (path) => path.includes('topo-order') ? { tables: ['one', 'two'] } : { status: 'done', rows_inserted: 1, result: { errors: ['invalid row'] } },
    post: async (path) => { calls.push(path); return { job_id: 'partial' }; },
  });
  await f.run('doGenerate(tablesMeta)');
  assert.equal(calls.length, 1);
  assert.match(textOf(f.out), /invalid row/);
  assert.doesNotMatch(textOf(f.out), /全部完成/);
});

test('same connection retains wizard edits, but a new connection resets all connection state', async () => {
  const f = fixture();
  await f.run('loadMeta()');
  f.run(`step=3; cfg.set('one',new Map([['value',{generator:'integer',params:{min_value:666}}]])); treeSelection = new Map([['one',new Set(['value'])]]);`);
  await f.run('loadMeta()');
  assert.equal(f.run('step'), 3);
  assert.equal(f.run(`buildColumnsFor({name:'one'}).value.params.min_value`), 666);
  f.store.connId = 'B';
  await f.run('loadMeta()');
  assert.equal(f.run('step'), 1);
  assert.equal(f.run('cfg.size'), 0);
  assert.equal(f.run('treeSelection'), null);
});

test('late metadata from the prior connection cannot replace current metadata', async () => {
  const oldSchema = deferred();
  const started = deferred();
  const f = fixture({ get: async (path) => {
    if (path === '/api/meta/generators') return { names: [], params: {} };
    if (path === '/api/ai/config') return { available: false };
    if (path === '/api/connections') return { connections: [{ conn_id: 'A' }, { conn_id: 'B' }] };
    if (path.includes('/A/') && path.endsWith('/schema')) { started.resolve(); return oldSchema.promise; }
    if (path.endsWith('/schema')) return { columns: [{ name: 'new_column' }] };
    if (path.endsWith('/mapping')) return { mapping: {} };
  } });
  const oldLoad = f.run('loadMeta()');
  await started.promise;
  f.store.connId = 'B';
  f.store.tables = [{ name: 'new_table' }];
  await f.run('loadMeta()');
  oldSchema.resolve({ columns: [{ name: 'old_column' }] });
  await oldLoad;
  assert.deepEqual(plain(f.run('tablesMeta.map(t=>({name:t.name, columns:t.columns}))')), [{ name: 'new_table', columns: [{ name: 'new_column' }] }]);
  assert.equal(f.run('connInfo.conn_id'), 'B');
});

const config = {
  db_path: '/tmp/A.db', provider: 'base', locale: 'en_US', optimize_pragma: false,
  associations: [{ column_name: 'value', source_table: 'one', target_tables: ['two'] }],
  custom_column_mappings: { exact: { value: { generator: 'integer', params: { min_value: 2 } } } },
  tables: [
    { name: 'one', count: 9, seed: 123, batch_size: 2, clear_before: true, enrich: true, transform: 'value=value+1', columns: [
      { name: 'value', generator: 'weighted_choice', provider: 'faker', null_ratio: 0.5, params: { weighted_choices: { 'yes: #true': 80, pending: 20 } }, constraints: { unique: true, regex: '^1', max_retries: 0 }, faker_method: 'pyint', native_params: { min_value: 1 } },
    ] },
    { name: 'two', count: 13, columns: [{ name: 'value', derive_from: ['x', 'y'], expression: 'row["x"] + ": #" + row["y"]', null_ratio: 0.5, constraints: { max_retries: 0 } }] },
  ],
};

test('import and structured export preserve root/table/column fields and JSON value types', async () => {
  let serialized;
  const f = fixture({ post: async (path, payload) => {
    if (path === '/api/config/parse') return { valid: true, config };
    assert.equal(path, '/api/config/serialize');
    serialized = JSON.parse(payload.yaml);
    return { yaml: 'serialized yaml\n' };
  } });
  await f.run(`applyAiYaml('source yaml')`);
  const yaml = await f.run('buildYaml()');
  assert.equal(yaml, 'serialized yaml\n');
  assert.deepEqual(serialized, config);
  assert.match(textOf(f.out), /关联|映射/);
});

test('column panel receives all constraints and native/provider overrides', () => {
  const f = fixture();
  let captured;
  f.c.capture = (...args) => { captured = args; };
  f.c.cc = config.tables[0].columns[0];
  f.run(`cfg.set('one', new Map([['value', cc]])); genform={setColumn:(...args)=>capture(...args)};showColumnInPanel('one','value');`);
  assert.deepEqual(plain(captured[3].constraints), config.tables[0].columns[0].constraints);
  assert.equal(captured[3].provider, 'faker');
  assert.equal(captured[3].faker_method, 'pyint');
  assert.deepEqual(plain(captured[3].native_params), { min_value: 1 });
});

test('loaded schema supplies complete foreign keys to the panel despite imported generator overrides', async () => {
  const foreignKeys = [
    { column: 'manager_id', ref_table: 'employees', ref_column: 'id' },
    { column: 'department_id', ref_table: 'departments', ref_column: 'code' },
  ];
  let options;
  let shown;
  const f = fixture({
    createTree: () => ({ el: node() }),
    createGenForm: (value) => {
      options = value;
      return { el: node(), setColumn: (...args) => { shown = args; } };
    },
    post: async () => ({ valid: true, config: { tables: [{ name: 'one', columns: [
      { name: 'manager_id', generator: 'string', null_ratio: 0.05 },
      { name: 'department_id', derive_from: 'value', expression: 'value + 1' },
    ] }] } }),
  });
  const normalGet = f.c.get;
  f.c.get = async (path) => path.endsWith('/schema')
    ? { columns: [{ name: 'manager_id' }, { name: 'department_id' }], foreign_keys: foreignKeys }
    : normalGet(path);
  await f.run('loadMeta()');
  await f.run(`applyAiYaml('imported config')`);
  f.run('renderStep2()');
  assert.equal(typeof options.foreignKeysOf, 'function');
  assert.deepEqual(plain(options.foreignKeysOf('one')), foreignKeys);
  assert.deepEqual(plain(f.run('[...tablesMeta[0].fks]')), ['manager_id', 'department_id']);
  f.run(`showColumnInPanel('one', 'manager_id')`);
  assert.equal(shown[3].generator_name, 'string');
  assert.deepEqual(plain(options.foreignKeysOf(shown[0])), foreignKeys);
  f.run(`showColumnInPanel('one', 'department_id')`);
  assert.equal(shown[3].derive_from, 'value');
  assert.deepEqual(plain(options.foreignKeysOf(shown[0])), foreignKeys);
});

test('the panel receives empty foreign-key metadata when schema has no constraint, regardless of column name', async () => {
  let options;
  const f = fixture({
    createTree: () => ({ el: node() }),
    createGenForm: (value) => { options = value; return { el: node() }; },
  });
  const normalGet = f.c.get;
  f.c.get = async (path) => path.endsWith('/schema')
    ? { columns: [{ name: 'manager_id' }, { name: 'order_id' }] }
    : normalGet(path);
  await f.run('loadMeta()');
  f.run('renderStep2()');
  assert.equal(typeof options.foreignKeysOf, 'function');
  assert.deepEqual(plain(options.foreignKeysOf('one')), []);
  assert.deepEqual(plain(options.foreignKeysOf('unknown')), []);
  assert.deepEqual(plain(f.run('[...tablesMeta[0].fks]')), []);
});

test('imported table execution options and counts are preserved by preview and fill', async () => {
  const calls = [];
  const f = fixture({ post: async (path, payload) => {
    if (path === '/api/config/parse') return { valid: true, config };
    calls.push({ path, payload: plain(payload) });
    return path.endsWith('/preview') ? { rows: [] } : { job_id: 'job' };
  } });
  await f.run(`applyAiYaml('source yaml');`);
  await f.run(`doPreviews(tablesMeta, document.getElementById('preview-out'))`);
  await f.run('doGenerate(tablesMeta)');
  const firstPreview = calls.find(x => x.path.endsWith('/preview')).payload;
  const fills = calls.filter(x => x.path.endsWith('/fill')).map(x => x.payload);
  for (const payload of [firstPreview, fills[0]]) {
    for (const key of ['seed', 'batch_size', 'clear_before', 'enrich', 'transform']) assert.equal(payload[key], config.tables[0][key], key);
  }
  assert.equal(firstPreview.count, 5);
  assert.deepEqual(fills.map(x => x.count), [9, 13]);
});

test('an explicit count edit overrides imported table counts', async () => {
  const calls = [];
  const f = fixture({ post: async (path, payload) => {
    if (path === '/api/config/parse') return { valid: true, config };
    if (path.endsWith('/fill')) calls.push(payload.count);
    return path.endsWith('/preview') ? { rows: [] } : { job_id: 'job' };
  } });
  await f.run(`applyAiYaml('source yaml');`);
  const screen = f.run('renderStep3()');
  function find(n) { if (n?.id === 'gen-count') return n; for (const c of n?.children || []) { const hit = find(c); if (hit) return hit; } }
  const input = find(screen);
  input.value = '4';
  if (input.oninput) input.oninput({ target: input });
  f.count.value = '4';
  await f.run('doGenerate(tablesMeta)');
  assert.deepEqual(calls, [4, 4]);
});

test('late imported config cannot overwrite a newly connected database', async () => {
  const parse = deferred();
  const f = fixture({ post: async () => parse.promise });
  const applying = f.run(`applyAiYaml('source yaml')`);
  f.store.connId = 'B';
  await f.run('loadMeta()');
  parse.resolve({ valid: true, config });
  await applying.catch(() => {});
  assert.equal(f.run('cfg.size'), 0);
});

test('AI probe started for A never schedules or applies AI work to B', async () => {
  const probe = deferred();
  const calls = [];
  const f = fixture({ post: async (path) => {
    calls.push(path);
    if (path === '/api/ai/test-connection') return probe.promise;
    return { job_id: 'job' };
  } });
  const running = f.run('aiGenerateConfig()');
  f.store.connId = 'B';
  probe.resolve({ available: true, ok: true, backend: 'local' });
  await running;
  assert.deepEqual(calls, ['/api/ai/test-connection']);
});

test('a returning wizard generation button is re-enabled when its existing run finishes', async () => {
  const job = deferred();
  const started = deferred();
  const oldButton = node();
  const currentButton = node();
  let button = oldButton;
  const f = fixture({ get: async (path) => {
    if (path.includes('topo-order')) return { tables: ['one', 'two'] };
    started.resolve();
    return job.promise;
  } });
  const originalGet = f.c.document.getElementById;
  f.c.document.getElementById = (id) => id === 'btn-generate' ? button : originalGet(id);
  const running = f.run('doGenerate(tablesMeta)');
  await started.promise;
  currentButton.disabled = true;
  button = currentButton;
  job.resolve({ status: 'done', rows_inserted: 2 });
  await running;
  assert.equal(currentButton.disabled, false);
});

test('preview freezes connection and options through later-table requests', async () => {
  const first = deferred();
  const calls = [];
  const f = fixture({ post: async (path, payload) => {
    calls.push({ path, payload: plain(payload) });
    return calls.length === 1 ? first.promise : { rows: [] };
  } });
  const preview = f.run(`doPreviews(tablesMeta, document.getElementById('preview-out'))`);
  f.store.connId = 'B';
  f.run(`cfg.get('two').get('value').params.min_value = 999`);
  first.resolve({ rows: [] });
  await preview;
  assert.ok(calls.every(c => c.path === '/api/connections/A/preview'));
  assert.equal(calls[1].payload.columns.value.params.min_value, 7);
});

test('an imported table using only inferred columns is selected and survives export', async () => {
  const inferred = { db_path: '/tmp/A.db', tables: [{ name: 'one', count: 8, columns: [] }] };
  const f = fixture({ post: async () => ({ valid: true, config: inferred }) });
  await f.run(`applyAiYaml('source yaml')`);
  assert.deepEqual(plain(f.run('buildConfig()')), inferred);
});

test('changing the visible count also changes the saved structured config', async () => {
  const f = fixture({ post: async (path) => path === '/api/config/parse' ? { valid: true, config } : { rows: [] } });
  await f.run(`applyAiYaml('source yaml')`);
  const screen = f.run('renderStep3()');
  const row = screen.children.find(x => x.children?.some(c => c.id === 'gen-count'));
  const input = row.children.find(c => c.id === 'gen-count');
  input.oninput({ target: { value: '17' } });
  assert.deepEqual(plain(f.run('buildConfig().tables.map(t=>t.count)')), [17, 17]);
});

test('import execution-limit notes remain visible after navigating wizard steps', async () => {
  const f = fixture({ post: async () => ({ valid: true, config }) });
  await f.run(`applyAiYaml('source yaml')`);
  f.run('renderStep()');
  assert.match(textOf(f.out), /关联与自定义映射/);
});

test('a stale mount failure does not show an old-connection error in the new wizard', async () => {
  const schema = deferred();
  const reached = deferred();
  const f = fixture();
  const normalGet = f.c.get;
  f.c.get = async (path) => {
    if (path.includes('/A/') && path.endsWith('/schema')) { reached.resolve(); return schema.promise; }
    return normalGet(path);
  };
  const loading = f.run('mount()');
  await reached.promise;
  f.store.connId = 'B';
  await f.run('loadMeta()');
  schema.resolve(Promise.reject(new Error('old A schema failed')));
  await loading;
  assert.doesNotMatch(textOf(f.out), /old A schema failed/);
});

test('an AI result finishing for A does not parse or apply config after switching to B', async () => {
  const job = deferred();
  const reached = deferred();
  const calls = [];
  const f = fixture({
    get: async () => { reached.resolve(); return job.promise; },
    post: async (path) => {
      calls.push(path);
      if (path === '/api/ai/test-connection') return { available: true, ok: true, backend: 'local' };
      return { job_id: 'ai' };
    },
  });
  const running = f.run('aiGenerateConfig()');
  await reached.promise;
  f.store.connId = 'B';
  job.resolve({ status: 'done', result: { yaml: 'old yaml', llm_calls: 0 } });
  await running;
  assert.deepEqual(calls, ['/api/ai/test-connection', '/api/connections/A/heal/auto']);
});

test('next and previous navigation keep the visible header step in sync with the body', async () => {
  const c = loadFrontend('pages/wizard.js');
  const treeContext = loadFrontend('tree.js', { document: c.document });
  const formContext = loadFrontend('genform.js', { document: c.document });
  c.createTree = treeContext.createTree;
  c.createGenForm = formContext.createGenForm;
  c.document.body.append(c.render());
  const header = c.document.querySelector('.wizard-header');
  const body = c.document.getElementById('wizard-body');
  assert.match(header.textContent, /步骤 1 \/ 3 — 目标/);
  await c.document.getElementById('btn-next').click();
  assert.ok(body.querySelector('.step2'));
  assert.match(header.textContent, /步骤 2 \/ 3 — 对象/);
  await c.document.getElementById('btn-next').click();
  assert.ok(body.querySelector('.step3'));
  assert.match(header.textContent, /步骤 3 \/ 3 — 生成/);
  await c.document.getElementById('btn-prev').click();
  assert.ok(body.querySelector('.step2'));
  assert.match(header.textContent, /步骤 2 \/ 3 — 对象/);
});

test('mount updates the wizard target after restoring a connection on refresh', async () => {
  const responses = {
    '/api/meta/generators': { names: [], params: {} },
    '/api/ai/config': { available: false },
    '/api/connections': { connections: [{ conn_id: 'B', target: '/tmp/beta.db' }] },
    '/api/connections/B/tables': { target: '/tmp/beta.db', tables: [] },
  };
  const c = loadFrontend('pages/wizard.js', {
    fetch: async (path) => {
      assert.ok(path in responses, `Unexpected request: ${path}`);
      return { ok: true, json: async () => responses[path] };
    },
  });
  c.document.body.append(c.h('span', { id: 'conn-badge' }), c.render());
  const target = c.document.querySelector('.wizard-db-name');
  assert.equal(target.textContent, '未连接');
  await c.mount();
  assert.equal(c.store.connId, 'B');
  assert.equal(target.textContent, '/tmp/beta.db');
});
