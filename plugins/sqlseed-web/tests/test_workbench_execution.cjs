const test=require('node:test');
const assert=require('node:assert/strict');
const {harness,deferred,plain}=require('./workbench_harness.cjs');
async function ready(){const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();return ui;}
const setMode=async(ui)=>{const input=ui.document.querySelector('[aria-label="清空所选表后生成"]');input.checked=true;await input.dispatchEvent('change');};
const plan={ok:true,atomic:true,clear_tables:[{name:'users',row_count:12}],issues:[],reset_identity_supported:true,plan_hash:'clear-plan'};
test('generation defaults to append and resetting IDs is disabled until clear is chosen',async()=>{
 const ui=await ready();assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,true);
 assert.equal(ui.document.querySelector('[aria-label="重置自增计数"]').disabled,true);
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/不清空表/);
 assert.equal(ui.requests.some(r=>r.url.endsWith('/execution-plan')),false);
});
test('clear confirmation binds reviewed scope and reset selection to the immutable execution request',async()=>{
 const ui=await ready();ui.routes.set('/api/workbench/execution-plan',()=>plan);
 ui.routes.set('/api/workbench/runs',()=>({id:'run'}));await setMode(ui);
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/12 行现有记录/);
 const reset=ui.document.querySelector('[aria-label="重置自增计数"]');reset.checked=true;await reset.dispatchEvent('change');
 await ui.button('清空并生成',ui.document).click();
 const request=JSON.parse(ui.requests.find(r=>r.url==='/api/workbench/runs').options.body);
 assert.deepEqual(request.execution,{mode:'replace_selected',reset_identity:true});assert.equal(request.plan_hash,'clear-plan');
 assert.equal(ui.location.hash,'#/runs?id=run');
});
test('blocked clear plans cannot submit database writes',async()=>{
 const ui=await ready();ui.routes.set('/api/workbench/execution-plan',()=>({...plan,ok:false,issues:[{severity:'error',message:'未选表 orders 引用了 users'}]}));
 await setMode(ui);assert.equal(ui.button('清空并生成',ui.document).disabled,true);assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/orders/);
 assert.match(ui.root().querySelector('.scope-summary').textContent,/生成规则已通过；清空需处理 1 项/);
 assert.ok(ui.button('改为追加，保留现有数据',ui.document.querySelector('.wb-execution-plan')));
 await ui.button('返回调整',ui.document).click();
 assert.match(ui.root().querySelector('.scope-summary').textContent,/生成规则已通过；清空需处理 1 项/);
 assert.ok(ui.root().querySelector('.dependency-summary').classList.contains('needs-attention'));
 assert.match(ui.root().querySelector('.wb-notice').textContent,/生成规则已通过；清空需处理 1 项/);
 assert.equal(ui.requests.some(r=>r.url==='/api/workbench/runs'),false);
});
test('late clear preflight cannot overwrite a subsequent append choice',async()=>{
 const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const pending=setMode(ui);await new Promise(resolve=>setImmediate(resolve));
 const append=ui.document.querySelector('[aria-label="追加数据"]');append.checked=true;await append.dispatchEvent('change');
 gate.resolve(plan);await pending;
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/不清空表/);assert.ok(ui.button('写入数据库',ui.document));
});
test('clear preflight does not queue duplicate requests or allow submitting before the active read finishes',async()=>{
 const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const pending=setMode(ui);await new Promise(resolve=>setImmediate(resolve));
 const replace=ui.document.querySelector('[aria-label="清空所选表后生成"]');
 const reset=ui.document.querySelector('[aria-label="重置自增计数"]');
 assert.equal(replace.disabled,true);assert.equal(reset.disabled,true);
 await replace.dispatchEvent('change');await reset.dispatchEvent('change');
 assert.equal(ui.requests.filter(r=>r.url.endsWith('/execution-plan')).length,1);
 const append=ui.document.querySelector('[aria-label="追加数据"]');append.checked=true;await append.dispatchEvent('change');
 assert.equal(ui.button('写入数据库',ui.document).disabled,true);
 gate.resolve(plan);await pending;
 assert.equal(ui.button('写入数据库',ui.document).disabled,false);
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/不清空表/);
});

for (const [dialect, label, target] of [['sqlite', 'SQLite', '/tmp/example & orders.db'], ['postgresql', 'PostgreSQL', 'postgresql://db.example.test:5432/shop']]) {
 test(`write confirmation identifies the active ${dialect} target without changing execution`, async () => {
  const ui=harness(); await ui.mount();
  ui.modelState().schema.dialect=dialect; ui.modelState().schema.target_label=target;
  ui.modelState().toggleTable('users',true); await ui.button('查看生成计划').click();
  const card=ui.document.querySelector('[aria-label="写入目标"]');
  assert.ok(card, 'confirmation must clearly identify the write target');
  assert.ok(card.textContent.includes(label)); assert.ok(card.textContent.includes(target));
  assert.equal(ui.document.querySelector('[aria-label="清空所选表后生成"]').disabled,dialect!=='sqlite');
  assert.equal(ui.requests.some(r=>r.url==='/api/workbench/runs'),false);
 });
}

const blockedPlan={...plan,ok:false,issues:[{code:'external_incoming_fk',table:'orders',severity:'error',message:'未选表 orders 引用了 users'}]};
const executionRequests=ui=>ui.requests.filter(request=>request.url.endsWith('/execution-plan'));
const written=ui=>ui.requests.filter(request=>request.url==='/api/workbench/runs');
const dismiss=ui=>ui.document.dispatchEvent({type:'keydown',key:'Escape'});
const nextTurn=()=>new Promise(resolve=>setImmediate(resolve));
const saveRevisions=ui=>ui.routes.set('/api/workbench/drafts/saved',options=>({
 ...JSON.parse(options.body),id:'saved',revision:2,target_key:'target-A'
}));

for(const close of ['返回调整','Escape']) {
 test(`a blocked clear flow survives ${close} and repeats preflight before an explicit write`,async()=>{
  const ui=await ready(),before=plain(ui.modelState().document);let checks=0;
  ui.routes.set('/api/workbench/execution-plan',()=>++checks===1?blockedPlan:{...plan,plan_hash:'fresh-plan'});
  ui.routes.set('/api/workbench/runs',()=>({id:'fresh-run'}));
  await setMode(ui);
  if(close==='Escape')await dismiss(ui);else await ui.button(close,ui.document).click();
  assert.equal(ui.document.querySelector('.modal'),null);
  assert.match(ui.root().querySelector('.dependency-summary').textContent,/生成规则已通过；清空需处理 1 项/);
  assert.match(ui.root().querySelector('.wb-notice').textContent,/生成规则已通过；清空需处理 1 项/);
  await ui.button('查看生成计划').click();
  assert.equal(ui.document.querySelector('[aria-label="清空所选表后生成"]').checked,true);
  assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,false);
  assert.equal(executionRequests(ui).length,2);
  assert.equal(written(ui).length,0);
  assert.deepEqual(plain(ui.modelState().document),before,'Execution intent is never added to the document');
  await ui.button('清空并生成',ui.document).click();
  assert.equal(JSON.parse(written(ui)[0].options.body).plan_hash,'fresh-plan');
 });
}

test('an edit changes a blocked clear flow to pending and an append-only global check cannot clear it',async()=>{
 const ui=await ready();saveRevisions(ui);
 ui.routes.set('/api/workbench/execution-plan',()=>blockedPlan);await setMode(ui);await dismiss(ui);
 const input=ui.root().querySelector('[aria-label="users 生成数量"]');input.value='123';await input.dispatchEvent('input');
 assert.match(ui.root().querySelector('.dependency-summary').textContent,/清空方案待重新检查/);
 assert.match(ui.root().querySelector('.wb-notice').textContent,/清空方案待重新检查/);
 await ui.root().querySelector('[data-dependency-count]').closest('button').click();
 assert.equal(ui.modelState().check.ok,true);
 assert.match(ui.root().querySelector('.dependency-summary').textContent,/清空方案待重新检查/);
 assert.match(ui.root().querySelector('.wb-notice').textContent,/清空方案待重新检查/);
 assert.equal(ui.root().querySelector('.dependency-summary').classList.contains('needs-attention'),false);
 await dismiss(ui);await ui.button('查看生成计划').click();
 const request=JSON.parse(executionRequests(ui)[1].options.body);
 assert.equal(request.revision,2);assert.deepEqual(request.execution,{mode:'replace_selected',reset_identity:false});
 assert.equal(ui.modelState().table('users').count,123);
 assert.equal(written(ui).length,0);
});

test('closing an approved plan discards its hash and reset option and blocks writes until the next plan resolves',async()=>{
 const ui=await ready(),gate=deferred();let calls=0;
 ui.routes.set('/api/workbench/execution-plan',()=>++calls<=2?plan:gate.promise);
 ui.routes.set('/api/workbench/runs',()=>({id:'new-plan-run'}));await setMode(ui);
 const reset=ui.document.querySelector('[aria-label="重置自增计数"]');reset.checked=true;await reset.dispatchEvent('change');
 await dismiss(ui);assert.match(ui.root().querySelector('.dependency-summary').textContent,/清空范围已核对，写入前会再次核对/);
 assert.equal(ui.root().querySelector('.dependency-summary').classList.contains('needs-attention'),false);
 const reopening=ui.button('查看生成计划').click();await nextTurn();
 assert.equal(ui.document.querySelector('[aria-label="重置自增计数"]').checked,false);
 assert.deepEqual(JSON.parse(executionRequests(ui)[2].options.body).execution,{mode:'replace_selected',reset_identity:false});
 const submit=ui.button('清空并生成',ui.document);assert.equal(submit.disabled,true);await submit.click();assert.equal(written(ui).length,0);
 gate.resolve({...plan,plan_hash:'renewed-plan'});await reopening;
 await submit.click();const request=JSON.parse(written(ui)[0].options.body);
 assert.equal(request.plan_hash,'renewed-plan');assert.equal(request.execution.reset_identity,false);
});

test('a late closed-dialog plan cannot overwrite a newer blocked clear result',async()=>{
 const ui=await ready(),gate=deferred();let calls=0;
 ui.routes.set('/api/workbench/execution-plan',()=>++calls===1?gate.promise:blockedPlan);
 const old=setMode(ui);await nextTurn();await dismiss(ui);
 assert.match(ui.root().querySelector('.dependency-summary').textContent,/清空方案待重新检查/);
 await ui.button('查看生成计划').click();assert.equal(executionRequests(ui).length,2);
 gate.resolve(plan);await old;
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/生成规则已通过；清空需处理 1 项/);
 assert.match(ui.root().querySelector('.dependency-summary').textContent,/生成规则已通过；清空需处理 1 项/);
 assert.equal(ui.button('清空并生成',ui.document).disabled,true);assert.equal(written(ui).length,0);
});

test('explicit append exits clear intent and later confirmations use append without a clear preflight',async()=>{
 const ui=await ready();ui.routes.set('/api/workbench/execution-plan',()=>blockedPlan);
 await setMode(ui);const append=ui.document.querySelector('[aria-label="追加数据"]');append.checked=true;await append.dispatchEvent('change');
 await dismiss(ui);assert.match(ui.root().querySelector('.dependency-summary').textContent,/追加生成检查通过/);
 assert.match(ui.root().querySelector('.wb-notice').textContent,/追加生成/);
 await ui.button('查看生成计划').click();assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,true);
 assert.equal(executionRequests(ui).length,1);assert.equal(written(ui).length,0);
});

for(const state of ['blocked','checking','ok']) {
 test(`leaving the workbench clears ${state} intent even when the same cached document returns`,async()=>{
  const ui=await ready(),gate=deferred(),original=ui.modelState();
  ui.routes.set('/api/workbench/execution-plan',()=>state==='checking'?gate.promise:state==='blocked'?blockedPlan:plan);
  const checking=setMode(ui);if(state==='checking')await nextTurn();else await checking;
  ui.leave();await ui.mount();assert.equal(ui.modelState(),original);
  if(state==='checking'){gate.resolve(plan);await checking;}
  await ui.button('查看生成计划').click();
  assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,true);
  assert.equal(executionRequests(ui).length,1);assert.equal(written(ui).length,0);
 });
}

test('importing a replacement document ends the old clear adjustment flow without changing persisted rules',async()=>{
 const ui=await ready();saveRevisions(ui);const document=plain(ui.modelState().document);
 ui.routes.set('/api/workbench/execution-plan',()=>blockedPlan);await setMode(ui);await dismiss(ui);
 ui.routes.set('/api/workbench/parse',()=>({document}));await ui.button('编辑 YAML').click();
 await ui.button('应用配置',ui.document).click();await ui.button('查看生成计划').click();
 assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,true);
 assert.equal(executionRequests(ui).length,1);assert.deepEqual(plain(ui.modelState().document),document);
 assert.equal(written(ui).length,0);
});

test('a lifecycle change invalidates an in-flight execution plan and makes its status pending',async()=>{
 const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const checking=setMode(ui);await nextTurn();
 await ui.context.window.dispatchEvent({type:'sqlseed:draft-renamed',detail:{id:'saved',revision:2,name:'renamed'}});
 gate.resolve(plan);await checking;await dismiss(ui);
 assert.match(ui.root().querySelector('.dependency-summary').textContent,/清空方案待重新检查/);
 assert.equal(written(ui).length,0);
});


test('existing-source cycle append confirmation consistently describes atomic writes in both languages',async()=>{
 const ui=harness();
 ui.routes.set('/api/workbench/check',()=>({ok:true,config_hash:'cycle-rules',order:['users'],issues:[],samples:{},
  existing_cycle_sources:[{table:'users',column:'id',target_table:'orders',target_columns:['user_id']}]}));
 await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();
 const dialog=ui.document.querySelector('.modal'),planArea=dialog.querySelector('.wb-execution-plan');
 assert.match(planArea.textContent,/不清空表.*运行开始前已有的父键.*全部所选表在同一事务中追加.*回滚本次新增记录/);
 assert.doesNotMatch(dialog.textContent,/已经提交的数据保留|按此顺序逐表写入/);
 assert.equal(ui.button('写入数据库',dialog).disabled,false);
 const requests=ui.requests.length;ui.context.setLanguage('en');
 assert.match(planArea.textContent,/without clearing tables.*before this run.*All selected tables append in one transaction.*rolls back the new rows/);
 assert.doesNotMatch(dialog.textContent,/committed data is retained|Tables are written in this order/);
 assert.equal(ui.requests.length,requests);
 ui.context.setLanguage('zh-CN');
 ui.routes.set('/api/workbench/execution-plan',()=>({...plan,ok:false,issues:[{severity:'error',code:'replacement_cycle_not_supported',message:'清空会删除循环所需的已有父键'}]}));
 await setMode(ui);
 assert.match(planArea.textContent,/清空会删除循环所需的已有父键/);
 assert.doesNotMatch(dialog.textContent,/全部所选表在同一事务中追加/);
 assert.equal(ui.button('清空并生成',dialog).disabled,true);
 const append=dialog.querySelector('[aria-label="追加数据"]');append.checked=true;await append.dispatchEvent('change');
 assert.match(planArea.textContent,/全部所选表在同一事务中追加/);
 assert.doesNotMatch(dialog.textContent,/已经提交的数据保留/);
 assert.equal(ui.requests.some(request=>request.url==='/api/workbench/runs'),false);
});
