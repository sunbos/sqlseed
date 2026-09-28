const assert = require('node:assert/strict');
const test = require('node:test');
const {harness, plain, deferred, schema} = require('./workbench_harness.cjs');

test('render and mount use actual schema rows, and disconnected mount provides a connection entry', async () => {
  const ui = harness();
  const root = await ui.mount();
  assert.equal(root.querySelectorAll('.wb-table-entry').length, 3);
  assert.equal(root.querySelectorAll('.wb-field-name').length, 3);
  assert.match(root.textContent, /A\.db/);
  assert.equal(root.querySelector('.wb-table-name').textContent, 'users未加入生成');
  assert.deepEqual(ui.requests.map(request => request.url), ['/api/workbench/connections/A/schema', '/api/workbench/generators', '/api/meta/providers']);
  const none = harness({connected: false}); await none.mount();
  assert.match(none.root().textContent, /先连接一个数据库/);
  assert.equal(none.requests.length, 0);
});

test('ordinary rule cells never render the text null from an absent icon', async () => {
  const ui = harness(); await ui.mount();
  const buttons = ui.root().querySelectorAll('.wb-rule-button');
  assert.ok(buttons.length);
  assert.ok(buttons.every(button => !button.childNodes.some(node => node.nodeType === 3 && node.textContent === 'null')));
});

test('a nullable self-reference applies fractional NULL probability only after confirmation and sends it in the real preview request',async()=>{
  const ui=harness(),data=schema();
  const id={...data.tables[0].columns[0],is_autoincrement:false,is_rowid_alias:true};
  const parent={...data.tables[1].columns[0],name:'parent_id',nullable:true};
  const name={...data.tables[2].columns[0],name:'name'};
  data.tables=[{name:'categories',row_count:1,columns:[id,parent,name],primary_key:['id'],unique_constraints:[],checks:[],
    foreign_keys:[{id:'category-parent',columns:['parent_id'],ref_table:'categories',ref_columns:['id'],nullable:true}],
    mapping:{id:{generator_name:'skip',params:{}},parent_id:{generator_name:'foreign_key_or_integer',params:{strategy:'random'}},name:{generator_name:'string',params:{}}}}];
  data.nodes=[{id:'categories'}];data.edges=[{id:'category-parent',source:'categories',target:'categories',sourceColumns:['id'],targetColumns:['parent_id'],nullable:true}];
  ui.routes.set('/api/workbench/connections/A/schema',()=>data);
  ui.routes.set('/api/workbench/preview',()=>({ok:true,samples:{categories:[{parent_id:1,name:'Sample'}]},issues:[]}));
  await ui.mount();const selected=ui.root().querySelector('[data-table="categories"]').querySelector('input[type="checkbox"]');
  selected.checked=true;await selected.dispatchEvent('change');
  const before=plain(ui.modelState().document);await ui.openRule('parent_id');
  const requestCount=ui.requests.length,checkbox=ui.field('nullable');
  checkbox.checked=true;await checkbox.dispatchEvent('change');
  assert.equal(checkbox.checked,true);assert.equal(ui.field('null_ratio').disabled,false);assert.equal(ui.field('null_ratio').value,'5');
  await ui.edit('null_ratio','12.5');
  assert.deepEqual(plain(ui.modelState().document),before,'Editor changes stay local until Apply');
  assert.equal(ui.requests.length,requestCount);await ui.applyRule();
  assert.equal(ui.modelState().rule('categories','parent_id').null_ratio,0.125);
  await ui.openRule('parent_id');assert.equal(ui.field('nullable').checked,true);assert.equal(ui.field('null_ratio').value,'12.5');
  ui.field('nullable').checked=false;await ui.field('nullable').dispatchEvent('change');await ui.cancelRule();
  assert.equal(ui.modelState().rule('categories','parent_id').null_ratio,0.125,'Cancelling a toggle retains the applied configuration');
  await ui.button('预览数据').click();
  let request=JSON.parse(ui.requests.filter(item=>item.url==='/api/workbench/preview').at(-1).options.body);
  let rule=request.document.tables[0].columns.find(column=>column.name==='parent_id');
  assert.equal(rule.null_ratio,0.125);assert.equal(rule.generator,'foreign_key_or_integer');
  assert.deepEqual(rule.params,{strategy:'random'});
  await ui.button('字段规则').click();await ui.openRule('parent_id');
  ui.field('nullable').checked=false;await ui.field('nullable').dispatchEvent('change');await ui.applyRule();
  assert.equal(ui.modelState().rule('categories','parent_id').null_ratio,undefined);
  await ui.button('预览数据').click();
  request=JSON.parse(ui.requests.filter(item=>item.url==='/api/workbench/preview').at(-1).options.body);
  rule=request.document.tables[0].columns.find(column=>column.name==='parent_id');
  assert.equal(Object.hasOwn(rule,'null_ratio'),false);
  assert.equal(ui.requests.some(item=>item.url==='/api/workbench/runs'),false);
});

test('a reversed float range keeps the real rule drawer open and never changes the executable configuration',async()=>{
  const ui=harness(),data=schema();
  data.tables[0].mapping.amount={generator_name:'float',params:{min_value:1,max_value:10}};
  ui.routes.set('/api/workbench/connections/A/schema',()=>data);
  ui.routes.set('/api/workbench/generators',()=>({names:['float'],entries:[{id:'float',params:[
    {name:'min_value',type:'number',default:0},{name:'max_value',type:'number',default:100}]}]}));
  await ui.mount();ui.modelState().toggleTable('users',true);
  const before=plain(ui.modelState().document);await ui.openRule('amount');
  await ui.edit('min_value','20');
  const apply=ui.button('应用规则',ui.document);
  assert.equal(apply.disabled,true);assert.match(ui.document.querySelector('.wb-editor-error').textContent,/不能大于/);
  await apply.click();assert.ok(ui.document.querySelector('.drawer'));
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.some(request=>request.options.method==='POST'),false);
  await ui.edit('max_value','20');assert.equal(apply.disabled,false);
  await ui.applyRule();
  assert.deepEqual(plain(ui.modelState().rule('users','amount').params),{min_value:20,max_value:20});
  ui.leave();
});

test('table names open fields and right-side icons open complete dependency paths without selecting tables', async () => {
  const ui = harness(); await ui.mount();
  const entry = ui.root().querySelector('[data-table="orders"]');
  await entry.querySelector('.wb-table-graph').click();
  assert.equal(ui.modelState().view.page, 'graph');
  assert.equal(ui.modelState().view.graphMode, 'paths');
  assert.deepEqual(ui.root().querySelectorAll('[data-graph-node]').map(node => node.getAttribute('data-graph-node')).sort(), ['orders', 'users']);
  assert.equal(ui.modelState().document.tables.length, 0);
  await ui.root().querySelector('[data-table="orders"]').querySelector('.wb-table-name').click();
  assert.equal(ui.modelState().view.page, 'fields');
  assert.deepEqual(ui.root().querySelectorAll('.wb-field-name').map(node => node.textContent), ['user_id']);
  assert.equal(ui.modelState().document.tables.length, 0);
});

test('the rule drawer serializes actual GeneratorSpec defaults only when applied', async () => {
  const ui = harness(); await ui.mount();
  const before = plain(ui.modelState().rule('users', 'amount'));
  await ui.openRule('amount');
  assert.ok(ui.document.querySelector('.wb-rule-editor'));
  await ui.edit('max_value', '22');
  assert.deepEqual(plain(ui.modelState().rule('users', 'amount')), before);
  await ui.applyRule();
  const config = plain(ui.modelState().rule('users', 'amount'));
  assert.equal(config.name, 'amount'); assert.equal(config.generator, 'integer');
  assert.equal(config.params.max_value, 22);
  assert.notEqual(config.native_params, null);
  assert.equal(ui.modelState().errors.size, 0);
  await ui.openRule('metadata');
  assert.equal(ui.field('schema').tagName, 'TEXTAREA');
  await ui.cancelRule();
});

for (const selection of ['checkbox', '全选', '清空选择']) {
  test(`${selection} remains available after cancelling invalid JSON without polluting rules`, async () => {
    const ui = harness(); await ui.mount();
    const before = plain(ui.modelState().rule('users', 'metadata'));
    await ui.openRule('metadata');
    const input = await ui.edit('schema', '{');
    const apply = ui.button('应用规则', ui.document);
    assert.equal(apply.disabled, true);
    await apply.click();
    assert.equal(ui.field('schema'), input);
    assert.equal(input.value, '{');
    assert.equal(ui.modelState().errors.size, 0, 'invalid unsubmitted editor state stays local');
    assert.deepEqual(plain(ui.modelState().rule('users', 'metadata')), before);
    await ui.cancelRule();
    if (selection === 'checkbox') {
      const checkbox = ui.root().querySelector('[data-table="orders"]').querySelector('input');
      checkbox.checked = true; await checkbox.dispatchEvent('change');
    } else await ui.button(selection).click();
    const selected = ui.modelState().document.tables.map(table => table.name).sort();
    assert.deepEqual(plain(selected), selection === 'checkbox' ? ['orders'] : selection === '全选' ? ['audit', 'orders', 'users'] : []);
    assert.deepEqual(plain(ui.modelState().rule('users', 'metadata')), before);
    await ui.openRule('metadata');
    assert.deepEqual(JSON.parse(ui.field('schema').value), {type: 'object'});
    await ui.edit('schema', '{"type":"integer"}');
    await ui.applyRule();
    assert.equal(ui.modelState().errors.size, 0);
    assert.deepEqual(plain(ui.modelState().rule('users', 'metadata').params.schema), {type: 'integer'});
  });
}

test('invalid JSON can be repaired in the drawer and applied before navigating to another field', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('metadata');
  const input = await ui.edit('schema', '{');
  assert.equal(ui.button('应用规则', ui.document).disabled, true);
  await ui.button('应用规则', ui.document).click();
  assert.equal(ui.field('schema'), input);
  assert.equal(input.value, '{');
  assert.deepEqual(plain(ui.modelState().rule('users', 'metadata').params.schema), {type: 'object'});
  await ui.edit('schema', '{"type":"integer"}');
  assert.equal(ui.button('应用规则', ui.document).disabled, false);
  await ui.applyRule();
  assert.deepEqual(plain(ui.modelState().rule('users', 'metadata').params.schema), {type: 'integer'});
  await ui.openRule('amount');
  assert.ok(ui.field('max_value'));
  assert.equal(ui.modelState().errors.size, 0);
  await ui.cancelRule();
});

test('schema arriving after unmount cannot replace a later page', async () => {
  const ui = harness(); const gate = deferred();
  ui.routes.set('/api/workbench/connections/A/schema', () => gate.promise);
  const pending = ui.mount();
  ui.leave(); ui.store.connId = 'B';
  await ui.mount();
  gate.resolve(schema('A')); await pending;
  assert.equal(ui.modelState().schema.target_key, 'target-B');
  assert.match(ui.root().textContent, /B\.db/);
});

test('late draft listing cannot open a dialog after leaving the workbench', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('/api/workbench/drafts?conn_id=A', () => gate.promise);
  const pending = ui.button('打开配置').click();
  ui.leave();
  gate.resolve({drafts: []}); await pending;
  assert.equal(Boolean(ui.document.querySelector('[role="dialog"]')), false);
});

test('late config export cannot open a dialog after leaving the workbench', async () => {
  const ui = harness(); await ui.mount(); const gate = deferred();
  ui.routes.set('/api/workbench/export', () => gate.promise);
  const pending = ui.button('编辑 YAML').click();
  ui.leave();
  gate.resolve({yaml: 'tables: []', json: {tables: []}}); await pending;
  assert.equal(Boolean(ui.document.querySelector('[role="dialog"]')), false);
});

test('an imported config resolving after leave and remount does not overwrite the current session', async () => {
  const ui = harness(); await ui.mount();
  await ui.button('编辑 YAML').click();
  const gate = deferred(); ui.routes.set('/api/workbench/parse', () => gate.promise);
  const pending = ui.button('应用配置', ui.document).click();
  ui.leave(); await ui.mount();
  await ui.openRule('amount'); await ui.edit('max_value', '37'); await ui.applyRule();
  const before = plain(ui.modelState().payload('current'));
  gate.resolve({document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 999, columns: []}]}});
  await pending;
  assert.deepEqual(plain(ui.modelState().payload('current')), before);
  await ui.openRule('amount');
  assert.equal(ui.field('max_value').value, '37');
  await ui.cancelRule();
});

test('an old draft fetch resolving after remount cannot reopen over newer edits', async () => {
  const ui = harness(); await ui.mount();
  ui.routes.set('/api/workbench/drafts?conn_id=A', () => ({drafts: [{id: 'old', name: 'Saved config', revision: 1, updated_at: 'today'}]}));
  await ui.button('打开配置').click();
  const gate = deferred(); ui.routes.set('/api/workbench/drafts/old', () => gate.promise);
  const pending = ui.document.querySelector('.wb-draft-card').click();
  ui.leave(); await ui.mount();
  await ui.openRule('amount'); await ui.edit('max_value', '51'); await ui.applyRule();
  const before = plain(ui.modelState().payload('current'));
  gate.resolve({id: 'old', name: 'Saved config', revision: 1, schema_hash: 'schema-v1', target_key: 'target-A',
    document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 400, columns: []}]}, view_state: {}});
  await pending;
  assert.deepEqual(plain(ui.modelState().payload('current')), before);
});

test('leaving cancels the unapplied drawer while returning preserves the last applied rule', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('metadata');
  await ui.edit('schema', '{"type":"boolean"}'); await ui.applyRule();
  const applied = plain(ui.modelState().rule('users', 'metadata'));
  await ui.openRule('metadata');
  await ui.edit('schema', '{');
  assert.equal(ui.button('应用规则', ui.document).disabled, true);
  ui.leave();
  assert.equal(ui.document.querySelector('.drawer'), null);
  await ui.mount();
  assert.equal(ui.modelState().errors.size, 0);
  assert.deepEqual(plain(ui.modelState().rule('users', 'metadata')), applied);
  await ui.openRule('metadata');
  assert.deepEqual(JSON.parse(ui.field('schema').value), {type: 'boolean'});
  await ui.cancelRule();
});

test('closing the config dialog while parsing prevents the stale import from replacing edits', async () => {
  const ui = harness(); await ui.mount(); await ui.button('编辑 YAML').click();
  const gate = deferred(); ui.routes.set('/api/workbench/parse', () => gate.promise);
  const pending = ui.button('应用配置', ui.document).click();
  await ui.button('取消', ui.document).click();
  await ui.openRule('amount'); await ui.edit('max_value', '62'); await ui.applyRule();
  const before = plain(ui.modelState().payload('current'));
  gate.resolve({document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 800, columns: []}]}});
  await pending;
  assert.deepEqual(plain(ui.modelState().payload('current')), before);
});

test('opening a saved draft first saves valid edits made to unselected tables', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('amount'); await ui.edit('max_value', '81'); await ui.applyRule();
  ui.routes.set('/api/workbench/drafts?conn_id=A', () => ({drafts: [{id: 'other', name: 'Other', revision: 1}]}));
  ui.routes.set('/api/workbench/drafts/other', () => ({id: 'other', name: 'Other', revision: 1,
    target_key: 'target-A', schema_hash: 'schema-v1', document: {provider: 'base', locale: 'en_US', tables: []}}));
  await ui.button('打开配置').click();
  await ui.document.querySelector('.wb-draft-card').click();
  const saves = ui.requests.filter(request => request.url === '/api/workbench/drafts' && request.options.method === 'POST');
  assert.equal(saves.length, 1, 'unselected table rules are still edits that must be saved before reopening');
  const saved = JSON.parse(saves[0].options.body);
  assert.equal(saved.view_state.tableDrafts.users.columns[0].params.max_value, 81);
});

test('an old dependency check cannot attach to a newly opened draft with the same epoch', async () => {
  const ui = harness(); await ui.mount();
  ui.modelState().toggleTable('users', true);
  const checkedEpoch = ui.modelState().epoch;
  const gate = deferred(); ui.routes.set('/api/workbench/check', () => gate.promise);
  const pending = ui.root().querySelector('[data-dependency-count]').closest('button').click();
  ui.routes.set('/api/workbench/drafts?conn_id=A', () => ({drafts: [{id: 'other', name: 'Other', revision: 1}]}));
  ui.routes.set('/api/workbench/drafts/other', () => ({id: 'other', name: 'Other', revision: 1,
    target_key: 'target-A', schema_hash: 'schema-v1', document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 42, columns: []}]}}));
  await ui.button('打开配置').click(); await ui.document.querySelector('.wb-draft-card').click();
  const current = ui.modelState(); assert.equal(current.table('users').count, 42);
  const count = ui.root().querySelector('input[aria-label="users 生成数量"]');
  count.value = '43'; await count.dispatchEvent('input');
  assert.equal(current.epoch, checkedEpoch, 'The new document has the same epoch as the old check request');
  gate.resolve({ok: true, config_hash: 'old-config', order: ['users'], layers: [['users']], issues: []}); await pending;
  assert.equal(current.check, null, 'a check belongs to the document object that initiated it');
});

test('opening a run snapshot discards invalid inputs cached for the previous document', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('metadata');
  await ui.edit('schema', '{'); ui.leave();
  ui.routes.set('/api/workbench/runs/snapshot', () => ({id: 'snapshot', name: 'Snapshot', target_key: 'target-A',
    document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 8, columns: [{name: 'metadata', generator: 'json', params: {schema: {type: 'array'}}}]}]}}));
  ui.location.hash = '#/workbench?run=snapshot';
  await ui.mount();
  assert.equal(ui.modelState().errors.size, 0);
  assert.equal(ui.modelState().saved, null, 'run snapshots open as a new editable configuration');
  assert.equal(ui.modelState().table('users').count, 8);
  await ui.openRule('metadata');
  assert.deepEqual(JSON.parse(ui.field('schema').value), {type: 'array'});
  await ui.cancelRule();
});

test('previewing an unselected table shows its real response without changing generation scope', async () => {
  const ui=harness();await ui.mount();await ui.openRule('amount');await ui.edit('max_value','81');await ui.applyRule();
  await ui.button('预览数据').click();
  const request=ui.requests.find(item=>item.url==='/api/workbench/preview');
  const payload=JSON.parse(request.options.body);
  assert.equal(payload.document.tables[0].name,'users');
  assert.equal(payload.document.tables[0].columns[0].params.max_value,81);
  assert.equal(ui.modelState().document.tables.length,0);
  assert.equal(ui.modelState().samples.users[0].amount,3);
  assert.equal(ui.modelState().check,null);
});

test('previewing selected tables includes only their rules and preserves unselected drafts', async () => {
  const ui = harness(); await ui.mount(); await ui.openRule('amount');
  await ui.edit('max_value', '81'); await ui.applyRule();
  const userRule = plain(ui.modelState().rule('users', 'amount'));
  for(const name of ['orders','audit']){
    const checkbox=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input');
    checkbox.checked=true;await checkbox.dispatchEvent('change');
  }
  ui.routes.set('/api/workbench/preview', options => {
    const names=JSON.parse(options.body).document.tables.map(table=>table.name);
    return {ok:true,schema_hash:'schema-v1',config_hash:'preview-config',order:names,layers:[names],
      samples:Object.fromEntries(names.map(name=>[name,name==='audit'?[{event:'generated event'}]:[{user_id:11}]])),issues:[]};
  });
  await ui.button('预览已选表').click();
  const dialog=ui.document.querySelector('.wb-data-preview');assert.ok(dialog);
  assert.equal(dialog.querySelector('[aria-label="预览范围"]'),null);
  const request = ui.requests.filter(item => item.url === '/api/workbench/preview').at(-1);
  assert.ok(request);
  assert.deepEqual(JSON.parse(request.options.body).document.tables.map(table => table.name), ['orders','audit']);
  assert.equal(JSON.parse(request.options.body).count,10);
  assert.deepEqual(plain(ui.modelState().document.tables.map(table => table.name)), ['orders','audit']);
  assert.deepEqual(plain(ui.modelState().rule('users', 'amount')), userRule);
  assert.deepEqual(plain(ui.modelState().samples), {orders:[{user_id:11}],audit: [{event: 'generated event'}]});
  assert.equal(ui.modelState().view.table, 'users', 'global refresh does not navigate to a selected table');
});

test('two completed modal requests cannot stack two dialogs',async()=>{
  const ui=harness();await ui.mount();
  const first=deferred(),second=deferred();let calls=0;
  ui.routes.set('/api/workbench/export',()=>++calls===1?first.promise:second.promise);
  const a=ui.button('编辑 YAML').click(),b=ui.button('编辑 YAML').click();
  first.resolve({yaml:'tables: []',json:'{}'});await a;
  second.resolve({yaml:'tables: []',json:'{}'});await b;
  assert.equal(ui.document.querySelectorAll('.wb-overlay').length,1);
  ui.leave();assert.equal(ui.document.querySelectorAll('.wb-overlay').length,0);
});

test('remaining run route opens only uncommitted work and does not write',async()=>{
  const ui=harness();await ui.mount();ui.leave();
  const run={id:'partial',name:'Partial',status:'error',target_key:'target-A',row_counts_exact:true,rows_inserted:13,
    execution:{mode:'append'},document:{provider:'base',tables:[{name:'users',count:10,columns:[]},{name:'audit',count:10,columns:[]}]},
    tables:[{name:'users',status:'done',requested_count:10,rows_inserted:10},{name:'audit',status:'error',requested_count:10,rows_inserted:3}]};
  ui.routes.set('/api/workbench/runs/partial',()=>run);ui.location.hash='#/workbench?run=partial&recover=remaining';await ui.mount();
  assert.deepEqual(plain(ui.modelState().document.tables.map(t=>[t.name,t.count])),[['audit',7]]);
  assert.equal(ui.modelState().view.tableDrafts.users.count,10);assert.equal(ui.modelState().saved,null);
  assert.equal(ui.requests.some(r=>r.url==='/api/workbench/runs'),false);
});
