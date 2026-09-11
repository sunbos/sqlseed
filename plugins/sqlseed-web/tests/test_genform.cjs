const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const { loadFrontend, createDom } = require('./frontend_helpers.cjs');

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function harness(foreignKeys = []) {
  const dom = { document: createDom() };
  const changes = [];
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  const bindings = {
    ...dom,
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ rows: [{ value: 4 }] }) };
    },
  };
  const dropdown = loadFrontend('dropdown.js', bindings);
  const labels = loadFrontend('labels.js', bindings);
  const context = loadFrontend('genform.js', {
    ...bindings,
    createDropdown: vm.runInContext('createDropdown', dropdown),
    ...vm.runInContext('({genLabel, paramLabel, groupGenerators, PENDING_GROUP_HINT})', labels),
  });
  context.change = (...args) => changes.push(plain(args[2]));
  context.foreignKeys = foreignKeys;
  const panel = vm.runInContext(`createGenForm({
    connId: 'connection-A',
    meta: {
      names: ['integer', 'choice', 'weighted_choice', 'bytes', 'string', 'json'],
      params: {
        integer: ['min_value', 'max_value'], choice: ['choices'],
        bytes: ['width', 'height', 'image_format', 'folder', 'extensions'],
        string: ['min_length', 'max_length'],
        json: ['schema'], weighted_choice: ['choices', 'weighted_choices'],
      },
    },
    uniqueColumnsOf: () => new Set(['db_unique']),
    foreignKeysOf: () => foreignKeys,
    onChange: change,
  })`, context);
  dom.document.body.append(panel.el);
  const baseline = { generator_name: 'integer', params: { min_value: 1, max_value: 9 } };
  function select(spec, col = 'value', colInfo = {}, zero = baseline) {
    panel.setColumn('items', col, { type: 'INTEGER', nullable: true, ...colInfo }, spec, zero);
  }
  function row(label) {
    return [...panel.el.querySelectorAll('.genform-row')]
      .find((node) => node.querySelector('label')?.textContent === `${label}:`);
  }
  async function changeInput(node, value, event = 'input') {
    assert.ok(node, 'expected an editable control');
    if (typeof value === 'boolean') node.checked = value;
    else node.value = String(value);
    await node.dispatchEvent({ type: event, target: node });
  }
  async function switchGenerator(name) {
    await panel.el.querySelector('.dropdown-btn').click();
    const menus = dom.document.querySelectorAll('.dropdown-floating');
    assert.equal(menus.length, 1, 'expected one open dropdown menu');
    const button = [...menus[0].querySelectorAll('.dropdown-item')]
      .find((node) => node.textContent.includes(`（${name}）`));
    assert.ok(button, `generator ${name} should be available`);
    await button.click();
  }
  async function reset() {
    await [...panel.el.querySelectorAll('button')].find((node) => node.textContent === '重置属性').click();
  }
  return { ...dom, panel, changes, requests, select, row, changeInput, switchGenerator, reset, timers };
}

test('reselecting a manually unique column preserves unique while editing its parameters', async () => {
  const ui = harness();
  ui.select({ generator_name: 'integer', params: { min_value: 1, max_value: 9 } });
  await ui.changeInput(ui.row('设置唯一').querySelector('input'), true, 'change');
  const saved = ui.changes.at(-1);
  ui.select({ generator_name: 'string', params: {} }, 'another');
  ui.select({ ...saved, generator_name: saved.generator });
  assert.equal(ui.row('设置唯一').querySelector('input').checked, true);
  await ui.changeInput(ui.row('最大值').querySelector('input'), 12);
  assert.equal(ui.changes.at(-1).constraints.unique, true);
  assert.equal(ui.changes.at(-1).params.max_value, 12);
});

test('parameter edits preserve all other column options and unique can be unchecked', async () => {
  const ui = harness();
  const spec = {
    generator_name: 'integer', params: { min_value: 1, max_value: 9 },
    constraints: { unique: true, min_value: 2, max_value: 20, regex: '^1', max_retries: 0 },
    provider: 'faker', faker_method: 'random_int', mimesis_method: 'numeric.integer',
    native_params: { start: 1, end: 9 }, null_ratio: 0.125,
  };
  ui.select(spec);
  await ui.changeInput(ui.row('最大值').querySelector('input'), 12);
  assert.deepEqual(ui.changes.at(-1), {
    generator: 'integer', params: { min_value: 1, max_value: 12 },
    constraints: spec.constraints, provider: spec.provider, faker_method: spec.faker_method,
    mimesis_method: spec.mimesis_method, native_params: spec.native_params, null_ratio: 0.125,
  });
  await ui.changeInput(ui.row('设置唯一').querySelector('input'), false, 'change');
  const next = ui.changes.at(-1);
  assert.equal(Boolean(next.constraints.unique), false);
  assert.equal(next.constraints.max_retries, 0);
  assert.equal(next.constraints.regex, '^1');
  assert.equal(spec.constraints.unique, true, 'editing must not mutate the source config');
});

for (const source of ['choice', 'bytes']) {
  test(`switching ${source} to integer rebuilds preview and unique controls`, async () => {
    const ui = harness();
    ui.select({ generator_name: source, params: {} });
    assert.equal(ui.row('设置唯一'), undefined);
    await ui.switchGenerator('integer');
    assert.ok(ui.row('设置唯一'));
    assert.ok(ui.panel.el.querySelector('.genform-preview'));
    assert.ok(ui.row('最小值'));
    assert.ok(ui.row('最大值'));
    assert.equal(ui.panel.el.querySelectorAll('.genform-params').length, 1);
    assert.equal(ui.panel.el.querySelectorAll('.dropdown').length, 1);
    assert.equal(ui.timers.size, 1, 'generator changes should debounce one preview');
    assert.deepEqual(ui.changes.at(-1), { generator: 'integer', params: {} });
    const callbacks = [...ui.timers.values()];
    ui.timers.clear();
    for (const callback of callbacks) callback();
    assert.deepEqual(ui.requests.at(-1).body.columns.value, ui.changes.at(-1));
  });
}

test('changing generator clears incompatible params and native overrides', async () => {
  const ui = harness();
  ui.select({
    generator_name: 'integer', params: { min_value: 1, max_value: 9 },
    provider: 'faker', faker_method: 'random_int', mimesis_method: 'numeric.integer',
    native_params: { start: 1, end: 9 }, constraints: { unique: true, max_retries: 0 },
  });
  await ui.switchGenerator('choice');
  const cfg = ui.changes.at(-1);
  assert.equal(cfg.generator, 'choice');
  assert.deepEqual(cfg.params, {});
  assert.equal(cfg.provider, 'faker');
  assert.equal(cfg.faker_method, undefined);
  assert.equal(cfg.mimesis_method, undefined);
  assert.equal(cfg.native_params, undefined);
  assert.equal(Boolean(cfg.constraints.unique), false);
  assert.equal(cfg.constraints.max_retries, 0);
});

test('database constraints override imported NULL and unique settings', async () => {
  const ui = harness();
  ui.select({
    generator_name: 'choice', params: { choices: ['a', 'b'] }, null_ratio: 0.5,
    constraints: { unique: false, regex: '[ab]', max_retries: 0 },
  }, 'db_unique', { nullable: false });
  const unique = ui.row('设置唯一').querySelector('input');
  const nullable = ui.row('包含 NULL 值').querySelector('input');
  assert.equal(unique.checked, true);
  assert.equal(unique.disabled, true);
  assert.equal(nullable.checked, false);
  assert.equal(nullable.disabled, true);
  assert.equal(ui.row('百分比').querySelector('input').disabled, true);
  await ui.changeInput(ui.row('候选值').querySelector('textarea'), 'a\nb\nc');
  assert.deepEqual(ui.changes.at(-1).constraints, { unique: true, regex: '[ab]', max_retries: 0 });
  assert.equal(ui.changes.at(-1).null_ratio, undefined);
});

test('reset restores zero config instead of the current imported source config', async () => {
  const ui = harness();
  ui.select({
    generator_name: 'string', params: { min_length: 8 },
    provider: 'faker', faker_method: 'word', constraints: { unique: true },
  });
  await ui.reset();
  assert.deepEqual(ui.changes.at(-1), { generator: 'integer', params: { min_value: 1, max_value: 9 } });
  assert.ok(ui.row('最小值'));
});

test('derived preview preserves dependencies and constraints then resets to source mode', async () => {
  const ui = harness();
  ui.select({
    derive_from: ['left', 'right'], expression: 'row["left"] + row["right"]',
    null_ratio: 0.2, constraints: { unique: true, max_retries: 0 },
  });
  assert.equal(ui.row('生成器'), undefined);
  await Promise.resolve();
  const cfg = ui.requests.at(-1).body.columns.value;
  assert.deepEqual(cfg, {
    derive_from: ['left', 'right'], expression: 'row["left"] + row["right"]',
    null_ratio: 0.2, constraints: { unique: true, max_retries: 0 },
  });
  assert.equal(cfg.generator, undefined);
  assert.equal(cfg.params, undefined);
  await ui.reset();
  assert.deepEqual(ui.changes.at(-1), { generator: 'integer', params: { min_value: 1, max_value: 9 } });
});

test('rebuilding a panel removes document listeners of open dropdowns', async () => {
  const ui = harness();
  ui.select({ generator_name: 'bytes', params: {} });
  const formatDropdown = ui.panel.el.querySelectorAll('.dropdown')[1];
  await formatDropdown.querySelector('.dropdown-btn').click();
  assert.equal(ui.document.listeners.get('mousedown')?.size || 0, 1);
  const folderRadio = ui.panel.el.querySelectorAll('input[type="radio"]')[1];
  await ui.changeInput(folderRadio, true, 'change');
  assert.equal(ui.document.listeners.get('mousedown')?.size || 0, 0);
  assert.equal(ui.document.listeners.get('keydown')?.size || 0, 0);
  assert.equal(ui.document.listeners.get('scroll')?.size || 0, 0);
  assert.equal(formatDropdown.isConnected, false);
  await ui.panel.el.querySelector('.dropdown-btn').click();
  assert.equal(ui.document.listeners.get('mousedown')?.size || 0, 1);
  ui.select({ generator_name: 'integer', params: {} });
  assert.equal(ui.document.listeners.get('mousedown')?.size || 0, 0);
  assert.equal(ui.panel.el.querySelectorAll('.dropdown').length, 1);
});

test('JSON schema editor displays and submits structured JSON objects', async () => {
  const ui = harness();
  const schema = { type: 'object', properties: { name: { type: 'string' } } };
  ui.select({ generator_name: 'json', params: { schema } });
  const input = ui.row('JSON 结构').querySelector('textarea');
  assert.equal(input.textContent, JSON.stringify(schema, null, 2));
  const updated = { type: 'object', properties: { age: { type: 'integer' } } };
  await ui.changeInput(input, JSON.stringify(updated));
  assert.deepEqual(ui.changes.at(-1), { generator: 'json', params: { schema: updated } });
  assert.equal(ui.row('JSON 结构').querySelector('[role="alert"]').textContent, '');
  const callbacks = [...ui.timers.values()];
  ui.timers.clear();
  for (const callback of callbacks) callback();
  assert.deepEqual(ui.requests.at(-1).body.columns.value.params.schema, updated);
});

test('invalid JSON edits retain the last valid schema and block automatic and manual preview', async () => {
  const ui = harness();
  const schema = { type: 'integer' };
  ui.select({ generator_name: 'json', params: { schema } });
  const input = ui.row('JSON 结构').querySelector('textarea');
  await ui.changeInput(input, JSON.stringify(schema));
  const validChangeCount = ui.changes.length;
  const requestCount = ui.requests.length;
  for (const invalid of ['{', '[]', 'null', '42', '"text"']) {
    await ui.changeInput(input, invalid);
    assert.equal(ui.changes.length, validChangeCount, 'invalid drafts must not replace valid config');
    assert.deepEqual(ui.changes.at(-1).params.schema, schema);
    assert.match(ui.row('JSON 结构').querySelector('[role="alert"]').textContent, /JSON 对象/);
    assert.equal(input.getAttribute('aria-invalid'), 'true');
    assert.equal(ui.timers.size, 0, 'invalid input cancels any pending automatic preview');
    const refresh = [...ui.panel.el.querySelectorAll('button')].find((node) => node.textContent === '刷新');
    await refresh.click();
    assert.equal(ui.requests.length, requestCount, 'manual refresh must also avoid invalid input');
  }
  await ui.changeInput(input, '{"type":"boolean"}');
  assert.deepEqual(ui.changes.at(-1).params.schema, { type: 'boolean' });
  assert.equal(input.getAttribute('aria-invalid'), null);
  assert.equal(ui.row('JSON 结构').querySelector('[role="alert"]').textContent, '');
  assert.equal(ui.timers.size, 1);
});

test('clearing JSON schema restores generator defaults and changing generators discards draft errors', async () => {
  const ui = harness();
  ui.select({ generator_name: 'json', params: { schema: { type: 'integer' } } });
  const input = ui.row('JSON 结构').querySelector('textarea');
  await ui.changeInput(input, '  ');
  assert.deepEqual(ui.changes.at(-1), { generator: 'json', params: {} });
  await ui.changeInput(input, '{');
  assert.equal(ui.timers.size, 0);
  await ui.switchGenerator('integer');
  const callbacks = [...ui.timers.values()];
  ui.timers.clear();
  for (const callback of callbacks) callback();
  assert.deepEqual(ui.requests.at(-1).body.columns.value, { generator: 'integer', params: {} });
});

test('weighted choice object parameters stay structured when displayed and edited', async () => {
  const ui = harness();
  ui.select({ generator_name: 'weighted_choice', params: { weighted_choices: { active: 80, pending: 20 } } });
  const input = ui.row('加权候选值').querySelector('textarea');
  assert.equal(input.textContent, 'active:80\npending:20');
  await ui.changeInput(input, 'active:60\npending:40');
  assert.deepEqual(ui.changes.at(-1), {
    generator: 'weighted_choice', params: { weighted_choices: { active: 60, pending: 40 } },
  });
});

const parentFk = { column: 'parent_id', ref_table: 'items', ref_column: 'id' };
const parentSpec = { generator_name: 'foreign_key', params: { ref_table: 'items', ref_column: 'id', strategy: 'random' }, null_ratio: 0 };

test('schema foreign key remains managed after imported string configuration', async () => {
  const ui = harness([parentFk]);
  ui.select({ generator_name: 'string', params: { min_length: 1, max_length: 100 }, null_ratio: 0.05 }, 'parent_id', {}, parentSpec);
  assert.equal(ui.panel.el.querySelector('.dropdown'), null);
  assert.equal(ui.panel.el.querySelector('.genform-params'), null);
  assert.match(ui.panel.el.textContent, /items\.id/);
  assert.match(ui.panel.el.textContent, /自引用/);
  assert.ok(ui.panel.el.querySelector('.genform-preview'));
  assert.equal(ui.row('包含 NULL 值').querySelector('input').checked, true);
  await Promise.resolve();
  const cfg = ui.requests.at(-1).body.columns.parent_id;
  assert.equal(cfg.generator, 'foreign_key_or_integer');
  assert.equal(cfg.null_ratio, 0.05);
  assert.equal(cfg.params.min_length, undefined);
});

test('editing foreign-key NULL ratio preserves its source through reselect and reset', async () => {
  const ui = harness([parentFk]);
  ui.select({ generator_name: 'foreign_key_or_integer', params: { strategy: 'coverage' }, constraints: { unique: true }, null_ratio: 1 }, 'parent_id', {}, parentSpec);
  await ui.changeInput(ui.row('百分比').querySelector('input'), 12.5);
  const saved = ui.changes.at(-1);
  assert.deepEqual(saved, { generator: 'foreign_key_or_integer', params: { strategy: 'coverage' }, null_ratio: 0.125, constraints: { unique: true } });
  ui.select({ generator_name: 'integer', params: {} });
  ui.select({ ...saved, generator_name: saved.generator }, 'parent_id', {}, parentSpec);
  assert.equal(ui.panel.el.querySelector('.dropdown'), null);
  await ui.reset();
  assert.equal(ui.changes.at(-1).generator, 'foreign_key_or_integer');
  assert.equal(ui.changes.at(-1).null_ratio, undefined);
  assert.equal(ui.row('百分比').querySelector('input').disabled, true);
});

test('NOT NULL foreign key has no arbitrary generator or NULL controls', async () => {
  const ui = harness([{ column: 'order_id', ref_table: 'orders', ref_column: 'id' }]);
  ui.select({ generator_name: 'foreign_key_or_integer', null_ratio: 0.5 }, 'order_id', { nullable: false, is_primary_key: true, is_autoincrement: false });
  assert.equal(ui.panel.el.querySelector('.dropdown'), null);
  assert.equal(ui.row('包含 NULL 值'), undefined);
  assert.equal(ui.row('设置唯一'), undefined, 'a composite primary-key member is not individually unique');
  assert.match(ui.panel.el.textContent, /orders\.id/);
  assert.match(ui.panel.el.textContent, /NOT NULL/);
  await Promise.resolve();
  assert.equal(ui.requests.at(-1).body.columns.order_id.null_ratio, undefined);
  assert.equal(ui.requests.at(-1).body.columns.order_id.constraints?.unique, undefined,
    'a composite primary-key member must not become individually unique in preview');
});

test('schema foreign key takes precedence over an imported derived expression', async () => {
  const ui = harness([parentFk]);
  ui.select({ derive_from: ['value'], expression: 'value + 1000', null_ratio: 0.2 }, 'parent_id', {}, parentSpec);
  assert.equal(ui.row('派生自'), undefined);
  assert.match(ui.panel.el.textContent, /items\.id/);
  await Promise.resolve();
  const cfg = ui.requests.at(-1).body.columns.parent_id;
  assert.equal(cfg.generator, 'foreign_key_or_integer');
  assert.equal(cfg.derive_from, undefined);
  assert.equal(cfg.expression, undefined);
});

test('an id-like column without a database foreign key stays editable', () => {
  const ui = harness([]);
  ui.select({ generator_name: 'integer', params: { min_value: 1 } }, 'parent_id');
  assert.ok(ui.panel.el.querySelector('.dropdown'));
  assert.ok(ui.row('最小值'));
});
