const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain}=require('./workbench_harness.cjs');

test('generation is the primary action and global settings are visible without a modal',async()=>{
  const ui=harness();await ui.mount();
  assert.ok(ui.button('生成数据').classList.contains('primary'));
  assert.equal(ui.button('预览数据').classList.contains('primary'),false);
  assert.match(ui.root().querySelector('.wb-generation-settings').textContent,/数据生成引擎.*数据语言与地区/);
  const context=ui.root().querySelector('.wb-config-context');assert.ok(context);
  assert.ok(context.querySelector('.wb-generation-settings'));
  assert.ok(context.querySelector('.wb-config-tools'));
});

test('field names show schema information and rules open the editor',async()=>{
  const ui=harness();await ui.mount();await ui.selectColumn('amount');
  assert.equal(ui.document.querySelector('.drawer').querySelector('[role="tab"][aria-selected="true"]').textContent,'字段信息');
  assert.equal(ui.document.querySelector('.wb-rule-editor'),null);
  await ui.cancelRule();
  await ui.root().querySelectorAll('.wb-rule-button')[1].click();
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'amount');
  assert.equal(ui.modelState().document.tables.length,0);
});

test('table dependency explanation excludes unrelated selected tables and shows existing upstream sources',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();
  m.schema.tables.find(t=>t.name==='users').row_count=12;
  m.toggleTable('orders',true);m.toggleTable('audit',true);
  m.acceptCheck({ok:true,issues:[],order:['orders','audit'],layers:[['orders','audit']],sources:[{table:'orders',column:'user_id',source_table:'users',source_columns:['id'],has_values:true,row_count:12,selected:false,nullable:false}]},m.epoch);
  await ui.root().querySelector('[data-table="orders"]').querySelector('.wb-table-graph').click();
  await ui.root().querySelector('.inspector-tabs').querySelectorAll('button')[1].click();
  const panel=ui.root().querySelector('.wb-inspector-body');
  assert.match(panel.textContent,/orders.*全部上游来源/);
  assert.match(panel.textContent,/users.*已有.*12.*仅引用/s);
  assert.equal(panel.querySelectorAll('.execution-table').some(b=>b.textContent==='audit'),false);
  assert.match(panel.textContent,/其他表|整个计划/);
});

test('a table without dependencies is not described as depending on other selected tables',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('audit',true);m.toggleTable('orders',true);
  m.acceptCheck({ok:true,issues:[],order:['orders','audit'],layers:[['orders','audit']]},m.epoch);
  await ui.root().querySelector('[data-table="audit"]').querySelector('.wb-table-graph').click();
  await ui.root().querySelector('.inspector-tabs').querySelectorAll('button')[1].click();
  const panel=ui.root().querySelector('.wb-inspector-body');
  assert.match(panel.textContent,/没有上游/);
  assert.equal(panel.querySelectorAll('.execution-table').some(b=>b.textContent==='orders'),false);
});

test('late global dependency checks never dismiss newer rule edits',async()=>{
  const {deferred}=require('./workbench_harness.cjs');const ui=harness();await ui.mount();
  ui.modelState().toggleTable('orders',true);const gate=deferred();ui.routes.set('/api/workbench/check',()=>gate.promise);
  const pending=ui.button('依赖检查').click();await new Promise(resolve=>setImmediate(resolve));
  await ui.openRule('amount');await ui.edit('max_value','77');
  gate.resolve({ok:true,issues:[],layers:[['orders']],order:['orders']});await pending;
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'amount');
  assert.equal(ui.field('max_value').value,'77');
});

test('adding a required parent updates the currently open global check',async()=>{
  const ui=harness();await ui.mount();ui.modelState().toggleTable('orders',true);
  ui.routes.set('/api/workbench/check',()=>ui.modelState().selected('users')?{ok:true,issues:[],order:['users','orders'],layers:[['users'],['orders']]}:
    {ok:false,issues:[{severity:'error',code:'missing_parent_source',table:'orders',column:'user_id',source_table:'users',message:'缺少父表记录'}],order:['orders'],layers:[['orders']]});
  await ui.button('依赖检查').click();
  await ui.button('加入 users（100 行）',ui.document).click();
  assert.equal(ui.document.querySelector('.modal-body').textContent.includes('缺少父表记录'),false);
  assert.match(ui.document.querySelector('.modal-body').textContent,/检查通过/);
});

test('unselected table never borrows another table validation success',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('audit',true);m.acceptCheck({ok:true,issues:[],layers:[['audit']],order:['audit']},m.epoch);
  await ui.root().querySelector('[data-table="orders"]').querySelector('.wb-table-graph').click();
  await ui.root().querySelector('.inspector-tabs').querySelectorAll('button')[1].click();
  const text=ui.root().querySelector('.wb-inspector-body').textContent;
  assert.match(text,/当前表未.*检查范围/);assert.doesNotMatch(text,/规则检查通过/);
});

for(const change of ['delete','rename']) {
  test(`configuration ${change} lifecycle event defeats a late save response in the real page`,async()=>{
    const {deferred}=require('./workbench_harness.cjs');const ui=harness();await ui.mount();const m=ui.modelState();
    m.toggleTable('users',true);m.markSaved({id:'identity',revision:1,name:'Before'},m.epoch);m.setCount('users','14');
    const gate=deferred();ui.routes.set('/api/workbench/drafts/identity',()=>gate.promise);
    const pending=ui.button('保存配置').click();await new Promise(resolve=>setImmediate(resolve));
    await ui.context.window.dispatchEvent({type:`sqlseed:draft-${change==='delete'?'deleted':'renamed'}`,detail:{id:'identity',revision:3,name:'Renamed'}});
    gate.resolve({id:'identity',revision:2,name:'Before'});await pending;
    if(change==='delete')assert.equal(m.saved,null);
    else {assert.equal(m.saved.revision,3);assert.equal(vm.runInContext('session.name',ui.context),'Renamed');}
    assert.equal(m.dirty,true);assert.equal(m.table('users').count,14);
    assert.match(ui.root().querySelector('.wb-notice').textContent,/删除或重命名/);
  });
}

for(const change of ['table','rule']) {
  test(`leaving the preview tab prevents late results from replacing the ${change} view`,async()=>{
    const {deferred}=require('./workbench_harness.cjs');const ui=harness();await ui.mount();const gate=deferred();
    ui.routes.set('/api/workbench/preview',()=>gate.promise);
    const pending=ui.button('预览数据').click();await new Promise(resolve=>setImmediate(resolve));
    assert.ok(ui.root().querySelector('.wb-table-preview'));
    assert.equal(ui.document.querySelector('[role="dialog"]'),null);
    if(change==='table')await ui.root().querySelector('[data-table="audit"]').querySelector('.table-button').click();
    else {await ui.button('字段规则',ui.root().querySelector('[role="tablist"]')).click();await ui.openRule('amount');await ui.edit('max_value','77');}
    gate.resolve({ok:true,preview_complete:true,samples:{users:[{amount:8}]},issues:[]});await pending;
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(ui.modelState().samples.users[0].amount,8,'The requested table may keep its own readonly cache');
    assert.doesNotMatch(ui.root().querySelector('.wb-notice').textContent,/样例已更新|预览已更新/);
    if(change==='table'){
      assert.equal(ui.modelState().view.table,'audit');assert.equal(ui.modelState().samples.audit,undefined);
      assert.equal(ui.document.querySelector('[role="dialog"]'),null);
    } else {
      assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'amount');
      assert.equal(ui.field('max_value').value,'77');
      assert.equal(ui.document.querySelectorAll('[role="dialog"]').length,1);
    }
  });
}
