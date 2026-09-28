const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain,schema,deferred}=require('./workbench_harness.cjs');
const fixture=require('./complex_business_graph.json');
const cycle=structuredClone(fixture.checks.cycles.issues[0]);
const scope=['departments','employees','tenants','categories'];
const failed=()=>({ok:false,issues:[structuredClone(cycle)],order:['tenants','categories'],layers:[['tenants','categories']],samples:{}});
const passed=document=>({ok:true,config_hash:'valid',issues:[],order:document.tables.map(table=>table.name),samples:{}});
const close=ui=>ui.document.dispatchEvent({type:'keydown',key:'Escape'});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const writes=ui=>ui.requests.filter(r=>r.url==='/api/workbench/runs');
const plans=ui=>ui.requests.filter(r=>r.url==='/api/workbench/execution-plan');
const clearMode=async ui=>{const input=ui.document.querySelector('[aria-label="清空所选表后生成"]');input.checked=true;await input.dispatchEvent('change');};
function cycleSchema(){return {...schema(),...structuredClone(fixture),tables:fixture.tables.map(table=>({
 ...structuredClone(table),primary_key:[],unique_constraints:[],checks:[],mapping:{},
 columns:table.columns.map(column=>({...column,nullable:true,default:null})),
 foreign_keys:fixture.edges.filter(edge=>edge.target===table.name).map(edge=>({id:edge.id,columns:edge.targetColumns,ref_table:edge.source,ref_columns:edge.sourceColumns,nullable:edge.nullable}))
}))};}
async function cyclic({clear=true}={}) {
 const ui=harness();ui.routes.set('/api/workbench/connections/A/schema',cycleSchema);
 ui.routes.set('/api/workbench/check',failed);await ui.mount();
 for(const name of scope)ui.modelState().toggleTable(name,true);
 if(clear)vm.runInContext("executionChecks.set(session.model,{epoch:session.model.epoch,lifecycle:session.model.lifecycleVersion,state:'pending'})",ui.context);
 await ui.button('查看生成计划').click();return ui;
}

for(const clear of [true,false])test(`known cross-table limitation explains ${clear?'clear':'append'} without retry, strategy escape or writes`,async()=>{
 const ui=await cyclic({clear}),dialog=ui.document.querySelector('.modal'),before=plain(ui.modelState().document);
 const card=dialog.querySelector('.wb-generation-unsupported');
 assert.match(card.textContent,/departments、employees/);assert.match(card.textContent,/不是行数或生成器参数错误/);
 assert.equal(dialog.querySelectorAll('.wb-generation-unsupported').length,1);
 assert.equal(dialog.querySelectorAll('.wb-cycle-help').length,0,'Detailed references open on demand, not duplicated in confirmation');
 assert.deepEqual(dialog.querySelector('.wb-summary-plan').querySelectorAll('button').map(button=>button.textContent),scope);
 assert.match(dialog.textContent,/拟生成范围（当前无法执行）/);
 assert.doesNotMatch(dialog.textContent,/请.*重试|重新检查清空方案|改为追加，保留现有数据/);
 const append=dialog.querySelector('[aria-label="追加数据"]'),replace=dialog.querySelector('[aria-label="清空所选表后生成"]');
 assert.equal(append.disabled,true);assert.equal(replace.disabled,true);
 const reset=dialog.querySelector('[aria-label="重置自增计数"]');assert.equal(reset.disabled,true);
 const reason=dialog.querySelector('#wb-reset-reason');assert.equal(reset.getAttribute('aria-describedby'),reason.id);
 assert.match(reason.textContent,/没有 AUTOINCREMENT 历史序列需要重置/);
 assert.match(reason.textContent,/成功清空且由数据库自动分配时从 1 开始/);assert.match(reason.textContent,/自定义主键规则/);
 assert.match(reason.textContent,/当前不能清空或写入.*重置计数不能解除/);
 const submit=ui.button('当前范围无法生成',dialog);assert.equal(submit.disabled,true);await submit.click();
 await append.dispatchEvent('change');await replace.dispatchEvent('change');await reset.dispatchEvent('change');
 assert.equal(plans(ui).length,0);assert.equal(writes(ui).length,0);
 assert.equal(Boolean(vm.runInContext('executionChecks.has(session.model)',ui.context)),clear);
 await ui.button('返回工作台',dialog).click();
 const guide=ui.root().querySelector('.wb-generation-unsupported');assert.ok(guide);
 assert.equal(guide.querySelectorAll('button').length,1);
 const requests=ui.requests.length;
 await ui.button('查看无法生成的原因',guide).click();
 const detail=ui.document.querySelector('.modal');
 assert.match(detail.textContent,/departments.manager_id 引用 employees.id/);
 assert.match(detail.textContent,/employees.department_id 引用 departments.id/);
 assert.equal(detail.querySelector('.wb-dependency-issues').getAttribute('aria-label'),'无法生成的原因');
 assert.match(detail.textContent,/仅为可排序的部分.*不是完整可执行计划/);
 assert.doesNotMatch(detail.textContent,/请先处理阻断项，再重新检查/);
 const alternative=ui.button('定位需要调整的勾选项',detail).closest('details');
 assert.equal(Boolean(alternative.open),false);
 assert.equal(ui.requests.length,requests,'Viewing the known limitation never rechecks an unchanged scope');
 assert.deepEqual(plain(ui.modelState().document),before);
});

test('editing the scope expires the known limitation and its clear context, then accepts a fresh supported plan',async()=>{
 const ui=await cyclic();await close(ui);
 const oldCheck=ui.modelState().check,oldContext=vm.runInContext('executionChecks.get(session.model)',ui.context);
 const input=ui.root().querySelector('[data-table="departments"]').querySelector('input[type="checkbox"]');
 input.checked=false;await input.dispatchEvent('change');
 assert.equal(ui.modelState().check,null);assert.equal(ui.root().querySelector('.wb-generation-unsupported'),null);
 ui.context.oldCheck=oldCheck;assert.equal(vm.runInContext('generationLimitations(oldCheck).length',ui.context),0);
 assert.ok(vm.runInContext('executionChecks.has(session.model)',ui.context),'The requested clear intent remains');
 assert.equal(vm.runInContext('clearRecoveryState(session.model,executionChecks.get(session.model)).unsupported.length',ui.context),0);
 assert.notEqual(ui.modelState().epoch,oldContext.epoch);
 ui.routes.set('/api/workbench/check',options=>passed(JSON.parse(options.body).document));
 ui.routes.set('/api/workbench/drafts/saved',options=>({...JSON.parse(options.body),id:'saved',revision:2,target_key:'target-A'}));
 ui.routes.set('/api/workbench/execution-plan',()=>({ok:true,atomic:true,clear_tables:[],issues:[],reset_identity_supported:false,plan_hash:'new-scope'}));
 await ui.button('查看生成计划').click();
 assert.equal(plans(ui).length,1);assert.equal(ui.modelState().check.ok,true);
 assert.equal(ui.document.querySelector('.wb-generation-unsupported'),null);
 assert.equal(ui.button('清空并生成',ui.document).disabled,false);assert.equal(writes(ui).length,0);
});

test('an ordinary validation error is not reclassified by cycle-like message text',async()=>{
 const ui=harness();ui.routes.set('/api/workbench/check',()=>({ok:false,issues:[{code:'invalid_generator',severity:'error',table:'users',message:'跨表循环'}],order:[]}));
 await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();
 assert.equal(ui.document.querySelector('.wb-generation-unsupported'),null);
 assert.ok(ui.button('返回调整',ui.document));assert.equal(writes(ui).length,0);
});

test('identity reset explains append, pending, failed and supported clear plans using server capabilities',async()=>{
 const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();
 const reason=()=>ui.document.querySelector('#wb-reset-reason').textContent;
 const reset=()=>ui.document.querySelector('[aria-label="重置自增计数"]');
 assert.match(reason(),/追加会保留现有记录及自增计数/);
 const gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const pending=clearMode(ui);await tick();assert.match(reason(),/正在核对清空计划/);assert.equal(reset().disabled,true);
 gate.resolve({ok:false,atomic:true,issues:[{severity:'error',code:'external_incoming_fk',table:'orders',message:'Existing orders'}],clear_tables:[],reset_identity_supported:true});await pending;
 assert.match(reason(),/当前不能清空或写入/);assert.equal(reset().disabled,true);
 ui.routes.set('/api/workbench/execution-plan',()=>{throw new Error('transport offline');});
 await clearMode(ui);assert.match(reason(),/尚无可用的清空计划/);assert.equal(reset().disabled,true);
 ui.routes.set('/api/workbench/execution-plan',()=>({ok:true,atomic:true,issues:[],clear_tables:[],reset_identity_supported:true,plan_hash:'safe'}));
 await clearMode(ui);assert.equal(reset().disabled,false);assert.match(reason(),/SQLite AUTOINCREMENT/);assert.equal(writes(ui).length,0);
});

test('PostgreSQL explains why identity reset is unavailable without offering a clear plan',async()=>{
 const ui=harness();ui.routes.set('/api/workbench/connections/A/schema',()=>({...schema(),dialect:'postgresql'}));
 await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();
 assert.match(ui.document.querySelector('#wb-reset-reason').textContent,/不支持 PostgreSQL/);
 assert.equal(ui.document.querySelector('[aria-label="重置自增计数"]').disabled,true);
 assert.equal(plans(ui).length,0);assert.equal(writes(ui).length,0);
});

test('selected preview retains its disabled capability state after the shared busy gate and reads another tab through the current-data API',async()=>{
 const ui=harness();ui.routes.set('/api/workbench/connections/A/schema',cycleSchema);
 ui.routes.set('/api/workbench/preview',failed);await ui.mount();
 for(const name of scope) {
  const input=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input[type="checkbox"]');
  input.checked=true;await input.dispatchEvent('change');
 }
 const before=plain(ui.modelState().document),view=ui.modelState().view.table;
 await ui.button('预览已选表').click();
 let preview=ui.document.querySelector('.wb-data-preview');
 const blocked=ui.button('当前范围无法预览',preview);assert.equal(blocked.disabled,true,'Busy release must not restore the previous enabled state');
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,true,'The shared busy gate must also preserve the unsupported count control');
 await blocked.click();assert.equal(ui.requests.filter(r=>r.url==='/api/workbench/preview').length,1);
 assert.match(ui.root().querySelector('.wb-notice').textContent,/当前范围无法生成新样例/);
 await ui.button('employees',preview).click();
 const path='/api/workbench/connections/A/tables/employees/data?limit=50&offset=0';
 ui.routes.set(path,()=>({table:'employees',target_key:'target-A',target_label:'A.db',dialect:'sqlite',columns:[{name:'id',type:'INTEGER'}],rows:[{id:123}],total:1,limit:50,offset:0,order_by:['id'],read_at:'2026-09-10T03:00:00Z'}));
 await ui.button('查看 employees 当前数据',preview).click();await tick();
 assert.equal(ui.document.querySelector('.wb-data-preview'),null);
 assert.match(ui.document.querySelector('.wb-table-data').textContent,/123/);
 assert.equal(ui.requests.find(r=>r.url===path).options.method,undefined);
 assert.equal(ui.modelState().view.table,view,'Reading a preview tab does not change the workbench selection');
 assert.deepEqual(plain(ui.modelState().document),before);assert.equal(writes(ui).length,0);
 await ui.button('关闭',ui.document).click();
 const count=ui.requests.length;await ui.button('预览已选表').click();
 preview=ui.document.querySelector('.wb-data-preview');assert.equal(ui.button('当前范围无法预览',preview).disabled,true);
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,true);
 assert.equal(ui.requests.length,count,'Reopening the same known unsupported selected scope is read-only');
 await close(ui);
 const selection=ui.root().querySelector('[data-table="departments"]').querySelector('input[type="checkbox"]');
 selection.checked=false;await selection.dispatchEvent('change');
 ui.routes.set('/api/workbench/preview',options=>passed(JSON.parse(options.body).document));
 await ui.button('预览已选表').click();preview=ui.document.querySelector('.wb-data-preview');
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,false,'A changed, supported scope restores the count control');
 assert.equal(ui.button('重新预览',preview).disabled,false);
 assert.equal(writes(ui).length,0);
});

test('an independently supported self-referencing table still previews while the full selected scope has a cross-table limitation',async()=>{
 const ui=await cyclic();await close(ui);
 const check=ui.modelState().check;
 ui.routes.set('/api/workbench/preview',options=>{
  const document=JSON.parse(options.body).document;
  assert.deepEqual(document.tables.map(table=>table.name),['categories']);
  return {ok:true,issues:[],samples:{categories:[{id:1,parent_id:null,name:'Supported category'}]}};
 });
 await ui.root().querySelector('[data-table="categories"]').querySelector('.wb-table-name').click();
 await ui.button('预览数据').click();
 const preview=ui.root().querySelector('.wb-table-preview');assert.match(preview.textContent,/Supported category/);
 assert.equal(ui.button('重新预览',preview).disabled,false);
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,false);
 assert.equal(ui.modelState().check,check,'A single-table preview does not approve the unsupported full generation plan');
 assert.equal(writes(ui).length,0);
});

test('a failed selected-scope preview cannot block an independent table, while that table entry retains its own capability result',async()=>{
 const ui=harness();ui.routes.set('/api/workbench/connections/A/schema',cycleSchema);
 const previewScopes=[];
 ui.routes.set('/api/workbench/preview',options=>{
  const names=JSON.parse(options.body).document.tables.map(table=>table.name);previewScopes.push(names);
  return names.length===1 && names[0]==='categories'
   ? {ok:true,issues:[],samples:{categories:[{id:1,parent_id:null,name:'Independent category'}]}}
   : failed();
 });
 await ui.mount();
 for(const name of scope){
  const input=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input[type="checkbox"]');
  input.checked=true;await input.dispatchEvent('change');
 }
 const before=plain(ui.modelState().document);
 await ui.button('预览已选表').click();
 assert.equal(ui.button('当前范围无法预览',ui.document).disabled,true);
 const check=ui.modelState().check;await close(ui);
 const openTable=async name=>{
  await ui.root().querySelector(`[data-table="${name}"]`).querySelector('.wb-table-name').click();
  await ui.button('预览数据').click();return ui.root().querySelector('.wb-table-preview');
 };
 let preview=await openTable('categories');
 assert.match(preview.textContent,/Independent category/);
 assert.equal(ui.button('重新预览',preview).disabled,false);
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,false);
 assert.deepEqual(previewScopes,[scope,['categories']]);
 await openTable('categories');assert.equal(previewScopes.length,2,'The supported table result remains reusable');
 preview=await openTable('departments');
 assert.deepEqual(previewScopes.at(-1),['departments','employees','tenants'],'A table preview still includes its selected prerequisites');
 assert.equal(ui.button('当前范围无法预览',preview).disabled,true);
 assert.equal(preview.querySelector('[aria-label="每表预览行数"]').disabled,true);
 await openTable('departments');assert.equal(previewScopes.length,3,'A capability block from this table entry remains cached');
 assert.equal(ui.modelState().check,check,'Independent preview does not approve the blocked full generation scope');
 await ui.button('预览已选表').click();assert.equal(previewScopes.length,3);
 assert.equal(ui.button('当前范围无法预览',ui.document.querySelector('.modal')).disabled,true);
 assert.deepEqual(plain(ui.modelState().document),before);assert.equal(writes(ui).length,0);
});

test('successful selected-scope samples remain reusable when opening a single table',async()=>{
 const ui=harness();await ui.mount();
 for(const name of ['users','audit']){
  const input=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input[type="checkbox"]');
  input.checked=true;await input.dispatchEvent('change');
 }
 ui.routes.set('/api/workbench/preview',()=>({ok:true,issues:[],samples:{users:[{amount:42}],audit:[{event:'Cached group sample'}]}}));
 const before=plain(ui.modelState().document);
 await ui.button('预览已选表').click();await close(ui);
 await ui.root().querySelector('[data-table="audit"]').querySelector('.wb-table-name').click();
 await ui.button('预览数据').click();
 const preview=ui.root().querySelector('.wb-table-preview');
 assert.match(preview.textContent,/Cached group sample/);assert.equal(ui.button('重新预览',preview).disabled,false);
 assert.equal(ui.requests.filter(request=>request.url==='/api/workbench/preview').length,1);
 assert.deepEqual(plain(ui.modelState().document),before);assert.equal(writes(ui).length,0);
});

test('field-rule notices scope structured cycle and column diagnostics to their tables without an empty prefix',async()=>{
 const ui=await cyclic();await close(ui);
 const m=ui.modelState(),before=plain(m.document);
 m.acceptPreview({...failed(),issues:[cycle,
  {table:'employees',column:'department_id',severity:'error',message:'Local employee field issue'},
  {severity:'warning',message:'Global preview note'}]},m.epoch);
 await ui.root().querySelector('[data-table="categories"]').querySelector('.wb-table-name').click();
 let note=ui.root().querySelector('.wb-preview-notice');
 assert.deepEqual(note.querySelectorAll('p').map(node=>node.textContent),['诊断详情：Global preview note']);
 assert.ok(ui.root().querySelector('.wb-generation-unsupported'),'The full-scope capability explanation stays global');
 await ui.root().querySelector('[data-table="departments"]').querySelector('.wb-table-name').click();
 note=ui.root().querySelector('.wb-preview-notice');
 assert.match(note.querySelector('p').textContent,/^departments、employees: /);
 assert.doesNotMatch(note.textContent,/Local employee field issue/);
 await ui.root().querySelector('[data-table="employees"]').querySelector('.wb-table-name').click();
 note=ui.root().querySelector('.wb-preview-notice');
 assert.match(note.textContent,/employees.department_id: 诊断详情：Local employee field issue/);
 assert.deepEqual(plain(m.document),before);assert.equal(writes(ui).length,0);
});
