const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const file = path.join(__dirname, '../src/sqlseed_web/static/js/workbench/model.js');
function model(document) {
  const context = vm.createContext({structuredClone, JSON, Map, Set});
  vm.runInContext(fs.readFileSync(file, 'utf8').replace(/^export /gm, '') + '\nglobalThis.Model = WorkbenchDocument;', context);
  return new context.Model({schema_hash:'s1',provider:'faker',locale:'zh_CN',tables:[{name:'users'},{name:'orders'}]}, document);
}
const plain = value => JSON.parse(JSON.stringify(value));
test('table navigation never changes selection; unselect and reselect retains complete table config', () => {
  const m = model({tables:[{name:'users',count:8,seed:42,columns:[{name:'email',generator:'email'}]}],associations:[{name:'kept'}]});
  m.selectTable('orders', 'graph');
  assert.deepEqual(plain(m.document.tables.map(t=>t.name)), ['users']);
  m.toggleTable('users',false); m.toggleTable('users',true);
  assert.equal(m.document.tables[0].seed,42);
  assert.equal(m.document.tables[0].columns[0].generator,'email');
  assert.deepEqual(plain(m.document.associations),[{name:'kept'}]);
});
test('unselected table edits persist in view state and become executable only after selecting', () => {
  const m=model(); m.setColumn('orders','amount',{generator:'integer',params:{min_value:7,max_value:7}});
  assert.equal(m.document.tables.length,0);
  const saved=m.payload('draft');
  const restored=model(saved.document); restored.restoreView(saved.view_state);
  restored.toggleTable('orders',true);
  assert.equal(restored.document.tables[0].columns[0].params.min_value,7);
});
test('stale checks cannot authorize a changed config; invalid input blocks payload', () => {
  const m=model(); m.toggleTable('users',true);
  const receipt=m.epoch;
  m.setCount('users','9');
  assert.equal(m.acceptCheck({ok:true,config_hash:'old'},receipt),false);
  assert.equal(m.check,null);
  m.setCount('users','1.2');
  assert.throws(()=>m.payload('x'),/整数/);
  m.setCount('users','12');
  assert.equal(m.payload('x').document.tables[0].count,12);
});
test('saved snapshots are immutable and later edits cannot run under an old check', () => {
  const m=model(); m.toggleTable('users',true);
  const epoch=m.epoch; const payload=m.payload('x');
  m.markSaved({...payload,id:'d',revision:1},epoch);
  m.acceptCheck({ok:true,config_hash:'c'},epoch);
  assert.equal(m.canRun(),true);
  m.setColumn('users','name',{generator:'choice',params:{choices:['A']}});
  assert.equal(m.canRun(),false);
  assert.equal(m.saved.document.tables[0].columns.length,0);
  assert.equal(m.dirty,true);
});
test('configuration import preserves advanced fields and refuses embedded connection credentials', () => {
  const m=model();
  assert.throws(()=>m.replaceDocument({url:'postgresql://secret',tables:[]}),/连接/);
  m.replaceDocument({provider:'faker',locale:'en_US',tables:[{name:'orders',count:2,transform:{x:1},columns:[{name:'a',derive_from:'b',expression:'b+1',constraints:{unique:true}}]}],custom_column_mappings:{x:'integer'}});
  assert.deepEqual(plain(m.document.tables[0].transform),{x:1});
  assert.deepEqual(plain(m.document.custom_column_mappings),{x:'integer'});
});

test('accepted checks copy samples and edits invalidate samples and preview issues', () => {
  const m = model();
  const result = {ok: true, config_hash: 'current', samples: {users: [{name: 'sample'}]}};
  m.acceptCheck(result, m.epoch);
  assert.deepEqual(plain(m.samples), result.samples);
  result.samples.users[0].name = 'mutated response';
  assert.equal(m.samples.users[0].name, 'sample');
  m.previewIssues = [{table: 'users', message: 'previous preview'}];
  m.setCount('users', '12');
  assert.deepEqual(plain(m.samples), {});
  assert.deepEqual(plain(m.previewIssues), []);
});

test('inferred rules prefer checked effective values without persisting runtime reference values', () => {
  const m = model();
  m.schema.tables[0].mapping = {amount: {generator_name: 'integer', params: {min_value: 0}}, parent_id: {
    generator_name: 'foreign_key', params: {strategy: 'coverage', _ref_values: [1, 2]},
  }};
  m.acceptCheck({ok: true, effective_rules: {users: {amount: {generator_name: 'integer', params: {min_value: 7, _ref_values: [99]}}}}}, m.epoch);
  assert.deepEqual(plain(m.rule('users', 'amount').params), {min_value: 7});
  assert.deepEqual(plain(m.rule('users', 'parent_id').params), {strategy: 'coverage'});
  assert.equal(m.schema.tables[0].mapping.parent_id.params._ref_values.length, 2, 'schema snapshots remain untouched');
  m.setColumn('users', 'amount', {generator: 'integer', params: {min_value: 11}, constraints: {unique: true}});
  m.acceptCheck({ok: true, effective_rules: {users: {amount: {generator_name: 'integer', params: {min_value: 7}}}}}, m.epoch);
  assert.deepEqual(plain(m.rule('users', 'amount')), {name: 'amount', generator: 'integer', params: {min_value: 11}, constraints: {unique: true}});
});

test('validation-only results retain the current preview and its issues even when samples is empty', () => {
  const m = model();
  const preview = {samples: {users: [{name: 'known preview'}]}, issues: [{code: 'preview_requires_parent', severity: 'warning', table: 'orders'}]};
  m.acceptPreview(preview, m.epoch);
  const samples = m.samples, issues = m.previewIssues;
  assert.equal(m.acceptCheck({ok: true, samples: {}, issues: [], config_hash: 'validated'}, m.epoch, false), true);
  assert.equal(m.samples, samples); assert.equal(m.previewIssues, issues);
  assert.equal(m.check.config_hash, 'validated');
  assert.equal(m.acceptCheck({ok: false, samples: {}, issues: [{code: 'missing_source'}]}, m.epoch, false), true);
  assert.equal(m.samples, samples); assert.equal(m.previewIssues, issues);
  assert.equal(m.check.ok, false);
});

test('an explicit full preview replaces samples and preview issues including empty and error responses', () => {
  const m = model();
  m.acceptPreview({samples: {users: [{name: 'old'}]}, issues: [{code: 'old_warning'}]}, m.epoch);
  const failed = {ok: false, samples: {}, issues: [{code: 'generation_invalid', message: 'Cannot generate'}]};
  m.acceptCheck(failed, m.epoch, true);
  assert.deepEqual(plain(m.samples), {});
  assert.deepEqual(plain(m.previewIssues), failed.issues);
  failed.issues[0].message = 'mutated';
  assert.equal(m.previewIssues[0].message, 'Cannot generate');
  m.acceptCheck({ok: true, samples: {}, issues: []}, m.epoch, true);
  assert.deepEqual(plain(m.previewIssues), []);
});

test('validation and preview handling reject earlier epochs and cannot restore samples after schema invalidation', () => {
  const m = model(); const previous = m.epoch;
  m.acceptPreview({samples: {users: [{name: 'old schema'}]}, issues: []}, previous);
  m.schema = {...m.schema, schema_hash: 'new-schema'}; m.touch();
  for (const preview of [false, true]) {
    assert.equal(m.acceptCheck({ok: true, schema_hash: 's1', samples: {users: [{name: 'late'}]}}, previous, preview), false);
  }
  assert.deepEqual(plain(m.samples), {}); assert.equal(m.check, null);
});


test('AI patch groups apply atomically without selecting unselected tables',()=>{
  const m=model();m.schema.tables[0].columns=[{name:'price'},{name:'total'}];m.schema.tables[1].columns=[{name:'amount'}];
  m.toggleTable('users',true);const epoch=m.epoch;
  const patches=[{table:'users',column:'price',after:{generator:'integer'}},{table:'orders',column:'amount',after:{generator:'decimal'}}];
  assert.throws(()=>m.applyPatches([...patches,{table:'users',column:'missing',after:{generator:'string'}}]),/字段/);
  assert.equal(m.epoch,epoch);assert.equal(m.table('users').columns.length,0);
  m.applyPatches(patches);assert.equal(m.epoch,epoch+1);assert.equal(m.selected('orders'),false);
  assert.equal(m.view.tableDrafts.orders.columns[0].generator,'decimal');
});
