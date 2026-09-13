const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {loadFrontend, createDom} = require('./frontend_helpers.cjs');

const plain = value => JSON.parse(JSON.stringify(value));
const parameter = (name, type, defaultValue, required = false) => ({name, type, default: defaultValue, required});
const catalog = {entries: [
  {id: 'integer', params: [parameter('min_value', 'integer', 0), parameter('max_value', 'integer', 999999)]},
  {id: 'string', params: [parameter('min_length', 'integer', 1), parameter('max_length', 'integer', 100)]},
  {id: 'choice', params: [parameter('choices', 'array', null, true)]},
  {id: 'json', params: [parameter('schema', 'object', null)]},
  {id: 'date', params: [parameter('weekdays', 'json', 'all')]},
]};
catalog.names = catalog.entries.map(entry => entry.id);

function harness(options = {}) {
  assert.ok(fs.existsSync(path.join(__dirname, '../src/sqlseed_web/static/js/workbench/editor.js')), 'Rule editor is missing');
  const document = createDom();
  const bindings = {document};
  const dropdown = loadFrontend('dropdown.js', bindings);
  const labels = loadFrontend('labels.js', bindings);
  const calendar = loadFrontend('workbench/date-picker.js', bindings);
  const context = loadFrontend('workbench/editor.js', {
    ...bindings,
    createDatePicker: vm.runInContext('createDatePicker', calendar),
    createDropdown: vm.runInContext('createDropdown', dropdown),
    ...vm.runInContext('({genLabel, paramLabel, genGuide})', labels),
  });
  const changes = [];
  const validity = [];
  const column = {name: 'amount', type: 'INTEGER', nullable: true, ...options.column};
  const table = {name: 'items', columns: [column, {name: 'left'}, {name: 'right'}], primary_key: [], unique_constraints: [], foreign_keys: [], ...options.table};
  context.options = {
    table, column, catalog,
    baseline: {generator_name: 'integer', params: {min_value: 1, max_value: 9}},
    ...options,
    onChange: value => changes.push(plain(value)),
    onValidity: message => validity.push(message),
  };
  context.options.column = column;
  context.options.table = table;
  const editor = vm.runInContext('createRuleEditor(options)', context);
  document.body.append(editor.el);
  const field = name => editor.el.querySelector(`[data-field="${name}"]`);
  async function input(name, value, event = 'input') {
    const node = field(name);
    assert.ok(node, `Missing editor field ${name}`);
    if (typeof value === 'boolean') node.checked = value;
    else node.value = String(value);
    await node.dispatchEvent(event);
    return node;
  }
  async function choose(name, label) {
    const dropdown = field(name);
    assert.ok(dropdown, `Missing dropdown ${name}`);
    if(name==='generator' && dropdown.querySelector('[data-generator-toggle]')) {
      await dropdown.querySelector('[data-generator-toggle]').click();
      const item=dropdown.querySelectorAll('[data-generator]').find(item=>item.textContent.includes(label));
      assert.ok(item,`Missing generator ${label}`);await item.click();return;
    }
    await dropdown.querySelector('.dropdown-btn').click();
    const menus = document.querySelectorAll('.dropdown-floating');
    assert.equal(menus.length, 1, `Expected one open dropdown for ${name}`);
    const item = menus[0].querySelectorAll('.dropdown-item').find(item => item.textContent.includes(label));
    assert.ok(item, `Missing option ${label}`);
    await item.click();
  }
  return {document, editor, changes, validity, field, input, choose};
}

test('parameter edits preserve full ColumnConfig and normalize GeneratorSpec aliases', async () => {
  const rule = {
    generator_name: 'integer', params: {min_value: 2, max_value: 9},
    provider: 'faker', native_faker_method: 'random_int', native_mimesis_method: 'numeric.integer',
    native_params: {start: 2}, constraints: {unique: true, max_retries: 0, regex: '^2'}, null_ratio: 0.125,
    custom_extension: {keep: true},
  };
  const ui = harness({rule});
  assert.equal(ui.changes.length, 0);
  await ui.input('max_value', '12');
  assert.deepEqual(ui.changes.at(-1), {
    name: 'amount', generator: 'integer', params: {min_value: 2, max_value: 12},
    provider: 'faker', faker_method: 'random_int', mimesis_method: 'numeric.integer',
    native_params: {start: 2}, constraints: rule.constraints, null_ratio: 0.125, custom_extension: {keep: true},
  });
  assert.equal(rule.params.max_value, 9);
});

test('invalid JSON stays visible and blocks changes from all controls until repaired', async () => {
  const ui = harness({rule: {generator: 'json', params: {schema: {type: 'integer'}}}});
  const field = await ui.input('schema', '{');
  assert.match(ui.validity.at(-1), /JSON/);
  assert.equal(field.value, '{');
  await ui.input('unique', true, 'change');
  assert.equal(ui.changes.length, 0);
  assert.equal(field.value, '{');
  await ui.input('schema', '{"type":"boolean"}');
  assert.equal(ui.validity.at(-1), null);
  assert.deepEqual(ui.changes.at(-1).params.schema, {type: 'boolean'});
  assert.equal(ui.changes.at(-1).constraints.unique, true);
});

test('required parameters and integral numeric fields reject incomplete drafts', async () => {
  const ui = harness({rule: {generator: 'choice', params: {}}});
  assert.match(ui.validity.at(-1), /候选值|choices/);
  await ui.input('choices', '[1, 2]');
  assert.equal(ui.validity.at(-1), null);
  assert.deepEqual(ui.changes.at(-1).params.choices, [1, 2]);
  await ui.choose('generator', 'integer');
  const count = ui.changes.length;
  await ui.input('min_value', '1.2');
  assert.match(ui.validity.at(-1), /整数/);
  assert.equal(ui.changes.length, count);
  await ui.input('min_value', '2');
  assert.equal(ui.changes.at(-1).params.min_value, 2);
});

test('NOT NULL and single-column uniqueness override drafts while composite PK does not imply unique', async () => {
  const ui = harness({
    column: {nullable: false, is_primary_key: true},
    table: {primary_key: ['amount', 'left']},
    rule: {generator: 'integer', params: {}, null_ratio: 0.7},
  });
  assert.equal(ui.field('nullable'), null);
  assert.equal(ui.field('null_ratio'), null);
  assert.equal(ui.field('unique').checked, false);
  await ui.input('max_value', '20');
  assert.equal(ui.changes.at(-1).null_ratio, undefined);
  assert.equal(ui.changes.at(-1).constraints?.unique, undefined);
  const unique = harness({table: {unique_constraints: [{name: 'u', columns: ['amount']}]}});
  assert.equal(unique.field('unique').checked, true);
  assert.equal(unique.field('unique').disabled, true);
  await unique.input('constraints', '{"unique":false,"max_retries":0}');
  assert.deepEqual(unique.changes.at(-1).constraints, {unique: true, max_retries: 0});
});

test('autoincrement and computed columns are read-only based on schema', () => {
  for (const column of [{is_primary_key: true, is_autoincrement: true}, {is_computed: true}]) {
    const ui = harness({column});
    assert.match(ui.editor.el.textContent, /数据库|自动/);
    assert.equal(ui.editor.el.querySelectorAll('input, textarea, .dropdown').filter(el => !el.disabled).length, 0);
    assert.equal(ui.changes.length, 0);
  }
});

test('schema grouped FK owns its source, sampling and nullable controls', async () => {
  const ui = harness({
    table: {foreign_keys: [{id: 'fk', columns: ['amount', 'left'], ref_table: 'parents', ref_schema: 'public', ref_columns: ['id', 'code'], nullable: true}]},
    rule: {derive_from: ['left'], expression: 'left+1', params: {_ref_values: [99], min_value: 9, strategy: 'coverage'}, constraints: {max_retries: 0}},
  });
  assert.equal(ui.field('generator'), null);
  assert.equal(ui.field('mode'), null);
  assert.match(ui.editor.el.textContent, /parents/);
  assert.match(ui.editor.el.textContent, /复合外键/);
  assert.equal(ui.field('null_ratio').closest('.wb-editor-row').hidden, true);
  await ui.choose('strategy', '随机');
  await ui.input('nullable', true, 'change');
  assert.equal(ui.field('null_ratio').closest('.wb-editor-row').hidden, false);
  await ui.input('null_ratio', '12.5');
  assert.deepEqual(ui.changes.at(-1), {
    name: 'amount', generator: 'foreign_key_or_integer', params: {strategy: 'random'},
    constraints: {max_retries: 0}, null_ratio: 0.125,
  });
});

test('derived editing validates references, preserves constraints and excludes source fields', async () => {
  const ui = harness({rule: {generator: 'integer', params: {min_value: 1}, constraints: {unique: true}}});
  await ui.choose('mode', '派生');
  assert.ok(ui.validity.at(-1));
  await ui.input('derive_from', 'left, right');
  await ui.input('expression', 'row["left"] + row["right"]');
  const cfg = ui.changes.at(-1);
  assert.deepEqual(cfg.derive_from, ['left', 'right']);
  assert.equal(cfg.expression, 'row["left"] + row["right"]');
  assert.equal(cfg.generator, undefined);
  assert.equal(cfg.params, undefined);
  assert.equal(cfg.constraints.unique, true);
  const count = ui.changes.length;
  await ui.input('derive_from', 'missing');
  assert.equal(ui.changes.length, count);
  assert.match(ui.validity.at(-1), /不存在/);
});

test('advanced JSON constraints keep invalid text and accept full constraint options', async () => {
  const ui = harness();
  const node = await ui.input('constraints', '{"regex":"^A","max_retries":0,"min_value":2}');
  assert.deepEqual(ui.changes.at(-1).constraints, {regex: '^A', max_retries: 0, min_value: 2});
  const count = ui.changes.length;
  await ui.input('constraints', '[]');
  assert.equal(node.value, '[]');
  assert.equal(ui.changes.length, count);
  assert.match(ui.validity.at(-1), /JSON 对象/);
});

test('weekday metadata uses semantic controls and retains an explicit selection', async () => {
  const ui = harness({rule: {generator: 'date', params: {weekdays: [0, 2]}}});
  assert.ok(ui.field('weekdays').querySelector('.dropdown-btn'));
  assert.equal(ui.field('weekday-0').checked, true);
  assert.equal(ui.field('weekday-1').checked, false);
  await ui.choose('weekdays', '工作日');
  assert.equal(ui.changes.at(-1).params.weekdays, 'workdays');
  await ui.choose('weekdays', '每天');
  assert.deepEqual(ui.changes.at(-1).params, {weekdays: 'all'});
});

test('reset removes explicit override, restores baseline and cleans open dropdown listeners', async () => {
  const ui = harness({rule: {generator: 'string', params: {min_length: 10}}});
  await ui.field('mode').querySelector('.dropdown-btn').click();
  assert.equal(ui.document.listeners.get('mousedown')?.size, 1);
  const reset = ui.editor.el.querySelectorAll('button').find(button => button.textContent === '重置为推断规则');
  await reset.click();
  assert.equal(ui.changes.at(-1), null);
  assert.ok(ui.field('min_value'));
  assert.equal(ui.document.listeners.get('mousedown')?.size, 0);
  await ui.field('mode').querySelector('.dropdown-btn').click();
  ui.editor.destroy();
  assert.equal(ui.document.listeners.get('mousedown')?.size, 0);
  assert.equal(ui.document.listeners.get('keydown')?.size, 0);
});

test('real GeneratorSpec null defaults normalize to valid ColumnConfig objects', async () => {
  const ui = harness({baseline: {
    generator_name: 'integer', params: {}, null_ratio: 0, provider: null,
    native_faker_method: null, native_mimesis_method: null, native_params: null,
  }});
  await ui.input('min_value', '4');
  assert.notEqual(ui.changes.at(-1).native_params, null, 'ColumnConfig native_params must be an object or omitted');
  assert.deepEqual(ui.changes.at(-1).params, {min_value: 4});
});

test('NULL draft errors survive unrelated edits and clear when NULL is disabled', async () => {
  const ui = harness({rule: {generator: 'integer', params: {}, null_ratio: 0.05}});
  const count = ui.changes.length;
  await ui.input('null_ratio', '120');
  await ui.input('max_value', '30');
  assert.equal(ui.changes.length, count);
  assert.equal(ui.field('null_ratio').value, '120');
  await ui.input('nullable', false, 'change');
  assert.equal(ui.validity.at(-1), null);
  assert.equal(ui.changes.at(-1).null_ratio, undefined);
  assert.equal(ui.changes.at(-1).params.max_value, 30);
  assert.equal(ui.field('null_ratio').closest('.wb-editor-row').hidden, true);
  assert.equal(ui.field('null_ratio').disabled, true);
});

test('switching mode back restores source parameters and destroys open dropdowns', async () => {
  const ui = harness({rule: {generator: 'integer', params: {min_value: 4}}});
  await ui.choose('mode', '派生');
  await ui.input('derive_from', 'left');
  await ui.input('expression', 'value + 1');
  await ui.choose('mode', '生成器');
  assert.equal(ui.changes.at(-1).params.min_value, 4);
  assert.equal(ui.changes.at(-1).expression, undefined);
  assert.equal(ui.changes.at(-1).derive_from, undefined);
  assert.equal(ui.document.listeners.get('mousedown')?.size, 0);
});

test('serialized editor drafts restore invalid JSON text and all accepted field changes', async () => {
  const first = harness({rule: {generator: 'json', params: {schema: {type: 'object'}}, constraints: {max_retries: 5}}});
  await first.input('schema', '{');
  await first.input('unique', true, 'change');
  await first.input('constraints', '[');
  const draft = plain(first.editor.getDraft());
  assert.equal(draft.config.params.schema.type, 'object');
  assert.equal(draft.invalidValues.schema, '{');
  assert.equal(draft.invalidValues.constraints, '[');
  assert.equal(draft.current.constraints.unique, true);
  first.editor.destroy();
  const restored = harness({draft});
  assert.equal(restored.field('schema').value, '{');
  assert.equal(restored.field('constraints').value, '[');
  assert.ok(restored.validity.at(-1));
  assert.equal(restored.changes.length, 0);
  await restored.input('constraints', '{"unique":true,"max_retries":0}');
  assert.equal(restored.changes.length, 0);
  await restored.input('schema', '{"type":"boolean"}');
  assert.equal(restored.validity.at(-1), null);
  assert.deepEqual(restored.changes.at(-1).constraints, {unique: true, max_retries: 0});
  assert.deepEqual(restored.changes.at(-1).params.schema, {type: 'boolean'});
  assert.deepEqual(plain(restored.editor.getDraft()).invalidValues, {});
});

test('unfinished derived mode survives serialization without replacing the last valid source config', async () => {
  const first = harness({rule: {generator: 'integer', params: {min_value: 7}}});
  await first.choose('mode', '派生');
  await first.input('derive_from', 'left');
  const draft = plain(first.editor.getDraft());
  assert.equal(draft.config.generator, 'integer');
  assert.equal(draft.mode, 'derived');
  const restored = harness({draft});
  assert.ok(restored.field('expression'));
  assert.equal(restored.field('derive_from').value, 'left');
  await restored.input('expression', 'value + 1');
  assert.equal(restored.validity.at(-1), null);
  assert.equal(restored.changes.at(-1).derive_from, 'left');
  assert.equal(restored.changes.at(-1).generator, undefined);
});

test('invalid NULL percentages survive draft restoration and can be corrected', async () => {
  const first = harness({rule: {generator: 'integer', params: {}, null_ratio: 0.05}});
  await first.input('null_ratio', '120');
  const restored = harness({draft: plain(first.editor.getDraft())});
  assert.equal(restored.field('null_ratio').value, '120');
  assert.match(restored.validity.at(-1), /百分比/);
  await restored.input('null_ratio', '20');
  assert.equal(restored.validity.at(-1), null);
  assert.equal(restored.changes.at(-1).null_ratio, 0.2);
});

test('an invalid NULL draft after zero remains visible and repairable when reopened', async () => {
  const first = harness({rule: {generator: 'integer', params: {}, null_ratio: 0.05}});
  await first.input('null_ratio', '0');
  await first.input('null_ratio', '120');
  const restored = harness({draft: first.editor.getDraft()});
  assert.equal(restored.field('nullable').checked, true);
  assert.equal(restored.field('null_ratio').disabled, false);
  assert.equal(restored.field('null_ratio').closest('.wb-editor-row').hidden, false);
  assert.equal(restored.field('null_ratio').value, '120');
  assert.match(restored.validity.at(-1), /NULL/);
  await restored.input('null_ratio', '10');
  assert.equal(restored.validity.at(-1), null);
  assert.equal(restored.changes.at(-1).null_ratio, 0.1);
});

test('SQLite rowid aliases start in database-default mode and remain overridable', async () => {
  const ui = harness({
    column: {name: 'id', type: 'INTEGER', nullable: false, default: null, is_primary_key: true, is_autoincrement: false, is_rowid_alias: true},
    table: {primary_key: ['id']}, baseline: {generator_name: 'skip', params: {}},
  });
  assert.equal(ui.validity.at(-1), null);
  assert.match(ui.field('mode').textContent, /数据库自动分配 ID/);
  assert.equal(ui.field('generator'), null);
  await ui.choose('mode', '生成器');
  await ui.choose('generator', 'integer');
  await ui.input('min_value', '100');
  assert.equal(ui.changes.at(-1).generator, 'integer');
  assert.equal(ui.changes.at(-1).params.min_value, 100);
  assert.equal(ui.changes.at(-1).constraints.unique, true);
  assert.equal(ui.validity.at(-1), null);
});

test('explicit rules for rowid aliases can return to database allocation', async () => {
  const ui = harness({
    column: {name: 'id', type: 'INTEGER', nullable: false, default: null, is_primary_key: true, is_autoincrement: false, is_rowid_alias: true},
    table: {primary_key: ['id']}, baseline: {generator_name: 'skip', params: {}},
    rule: {generator: 'integer', params: {min_value: 10, max_value: 20}},
  });
  assert.equal(ui.field('min_value').value, '10');
  await ui.choose('mode', '数据库自动分配 ID');
  assert.equal(ui.changes.at(-1).generator, 'skip');
  assert.deepEqual(ui.changes.at(-1).params, {});
  assert.equal(ui.validity.at(-1), null);
});

const typedCatalog={entries:[
  {id:'integer',label:'整数',output_type:'integer',params:[parameter('min_value','integer',0)]},
  {id:'email',label:'邮箱',output_type:'string',params:[]},
  {id:'decimal_value',label:'小数取值',output_type:'number',params:[]},
  {id:'choice',label:'枚举',output_type:'json',params:[parameter('choices','array',null,true)]},
  {id:'bytes',label:'字节',output_type:'bytes',params:[]},
]};

test('generator catalogue is searchable and conservatively filters real output types', async () => {
  const ui=harness({catalog:typedCatalog});
  const toggle=ui.field('generator').querySelector('[data-generator-toggle]');assert.ok(toggle);
  await toggle.click();
  const options=()=>ui.editor.el.querySelectorAll('[data-generator]').map(node=>node.getAttribute('data-generator'));
  assert.deepEqual(options(),['integer','choice']);
  const search=ui.field('generator-search');assert.ok(search);
  search.value='枚举';await search.dispatchEvent('input');
  assert.deepEqual(options(),['choice']);
  assert.equal(ui.field('generator-search'),search);
  search.value='';await search.dispatchEvent('input');
  const all=ui.field('generator-show-all');all.checked=true;await all.dispatchEvent('change');
  assert.ok(options().includes('email'));assert.ok(options().includes('bytes'));
  await ui.editor.el.querySelector('[data-generator="email"]').click();
  assert.equal(ui.changes.at(-1).generator,'email');
  assert.match(ui.editor.el.textContent,/检查配置|兼容/);
});

test('generator search keeps IME composition intact and unknown outputs available', async () => {
  const ui=harness({catalog:{entries:[...typedCatalog.entries,{id:'extension',label:'扩展测试',params:[]}]}});
  const toggle=ui.field('generator').querySelector('[data-generator-toggle]');assert.ok(toggle);await toggle.click();
  const search=ui.field('generator-search');const before=ui.editor.el.querySelectorAll('[data-generator]');
  await search.dispatchEvent('compositionstart');search.value='kuo';await search.dispatchEvent({type:'input',isComposing:true});
  assert.equal(ui.editor.el.querySelectorAll('[data-generator]')[0],before[0]);
  search.value='扩展';await search.dispatchEvent('compositionend');
  assert.equal(ui.editor.el.querySelectorAll('[data-generator]').length,1);
  assert.equal(ui.editor.el.querySelector('[data-generator]').getAttribute('data-generator'),'extension');
  assert.equal(ui.field('generator-search'),search);
});

test('catalogue changes retain malformed shared constraint text until it is corrected', async () => {
  const ui=harness();await ui.input('constraints','{');
  await ui.choose('generator','string');
  assert.equal(ui.field('constraints').value,'{');
  assert.ok(ui.validity.at(-1));assert.equal(ui.changes.length,0);
  await ui.input('constraints','{"max_retries":0}');
  assert.equal(ui.changes.at(-1).generator,'string');
  assert.equal(ui.changes.at(-1).constraints.max_retries,0);
});

test('shared controls use v8 classes and distinct schema, checklist and derived icons', () => {
  const document=createDom();document.createElementNS=(_,tag)=>document.createElement(tag);
  const context=loadFrontend('workbench/ui.js',{document});
  const ui=vm.runInContext('({button,icon})',context);
  const primary=ui.button('应用',()=>{},{primary:true,small:true,class:'custom-action'});
  for(const name of ['btn','primary','small','wb-button','custom-action'])assert.ok(primary.classList.contains(name),name);
  assert.equal(ui.icon('derive').textContent,'ƒx');
  assert.equal(ui.icon('schema').querySelectorAll('rect').length,3);
  assert.notEqual(ui.icon('check').querySelector('path').getAttribute('d'),ui.icon('schema').querySelector('path').getAttribute('d'));
  assert.notEqual(ui.icon('settings').querySelector('path').getAttribute('d'),ui.icon('fields').querySelector('path').getAttribute('d'));
});

test('plain controls retain their semantic classes without the default button presentation', () => {
  const document=createDom();document.createElementNS=(_,tag)=>document.createElement(tag);
  const context=loadFrontend('workbench/ui.js',{document});
  const button=vm.runInContext('button',context);
  const source=button('数据库',()=>{},{plain:true,primary:true,small:true,class:'source-head'});
  assert.deepEqual(source.className.split(/\s+/).sort(),['source-head','wb-button']);
  assert.equal(source.getAttribute('plain'),null);
});

test('shared modal can host a v8 drawer and restores background interaction when closed', async () => {
  const document=createDom();document.createElementNS=(_,tag)=>document.createElement(tag);
  const page=document.createElement('main');document.body.append(page);
  const context=loadFrontend('workbench/ui.js',{document});
  const modal=vm.runInContext('modal',context);
  const dialog=modal('items.amount',{drawer:true});
  const overlay=document.body.querySelector('.overlay');assert.ok(overlay);
  assert.ok(overlay.classList.contains('open'));assert.ok(overlay.querySelector('.drawer'));
  assert.ok(dialog.actions.classList.contains('drawer-footer'));
  assert.equal(page.inert,true);
  dialog.close();assert.equal(page.inert,false);
  assert.equal(overlay.isConnected,false);
  assert.equal(document.listeners.get('keydown')?.size,0);
});
