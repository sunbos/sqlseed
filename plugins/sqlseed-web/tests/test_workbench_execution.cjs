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

function blurWhenDisabled(ui, opener) {
 let disabled=opener.disabled;
 // Browsers blur a focused button when disabled; the general DOM fixture does not.
 Object.defineProperty(opener,'disabled',{configurable:true,get:()=>disabled,set:value=>{
  disabled=value;
  if(value && ui.document.activeElement===opener)ui.document.activeElement=ui.document.body;
 }});
}

for (const close of ['返回调整', 'Escape']) {
 test(`confirmation restores its opener after the native busy blur on ${close}`, async () => {
  const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);
  const opener=ui.button('查看生成计划');blurWhenDisabled(ui,opener);
  opener.focus();await opener.click();
  assert.equal(opener.disabled,false);
  assert.equal(ui.document.querySelector('.wb-execution-feedback').dataset.state,'ready');
  if(close==='Escape')await dismiss(ui);else await ui.button(close,ui.document).click();
  assert.equal(ui.document.querySelector('.modal'),null);
  assert.equal(ui.document.activeElement===opener,true,'closing must return to the plan entry, not BODY');
  assert.equal(written(ui).length,0);
 });
}

test('confirmation restores the guide stage or its recreated next-action entry', async () => {
 const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);
 const stage=ui.root().querySelector('[data-guide-action="stage-3"]');blurWhenDisabled(ui,stage);
 stage.focus();await stage.click();await dismiss(ui);
 assert.equal(ui.document.activeElement===stage,true);
 const opener=ui.root().querySelector('[data-guide-action="next"]');blurWhenDisabled(ui,opener);
 opener.focus();await opener.click();await dismiss(ui);
 const replacement=ui.root().querySelector('[data-guide-action="next"]');
 assert.notEqual(replacement,opener,'the next action is redrawn when check status updates');
 assert.equal(ui.document.activeElement===replacement,true);
 assert.equal(replacement.disabled,false);assert.equal(written(ui).length,0);
});

test('confirmation restores the capability reason when its first check hides the plan entry',async()=>{
 const ui=harness();await ui.mount();
 ui.modelState().toggleTable('users',true);ui.modelState().toggleTable('orders',true);
 const opener=ui.button('查看生成计划');blurWhenDisabled(ui,opener);
 assert.equal(ui.root().querySelector('.wb-generation-unsupported'),null);
 ui.routes.set('/api/workbench/check',()=>({ok:false,config_hash:'blocked',order:[],issues:[{
  severity:'error',code:'cross_table_cycle',tables:['users','orders'],edge_ids:[],message:'cycle blocked'
 }]}));
 opener.focus();await opener.click();assert.equal(opener.hidden,true);
 assert.equal(ui.button('当前范围无法生成',ui.document.querySelector('.modal')).disabled,true);
 ui.document.activeElement=ui.document.body; // Native removal of a focused overlay clears focus.
 await dismiss(ui);
 const reason=ui.button('查看无法生成的原因',ui.root().querySelector('.wb-generation-unsupported'));
 assert.equal(ui.document.activeElement===reason,true,'the replacement capability entry must receive focus');
 assert.equal(reason.disabled,false);assert.equal(ui.document.querySelector('.modal'),null);
 assert.deepEqual(plain(ui.modelState().document.tables.map(table=>table.name)),['users','orders']);
 assert.equal(written(ui).length,0);
});

for(const destination of ['body','another control','another page']) {
 test(`closing pending confirmation restores focus without overriding ${destination}`,async()=>{
  const ui=await ready();ui.routes.set('/api/workbench/execution-plan',()=>plan);
  await setMode(ui);await dismiss(ui);
  const gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
  const opener=ui.root().querySelector('.wb-clear-recovery-actions').querySelector('button');
  blurWhenDisabled(ui,opener);opener.focus();
  const pending=opener.click();await nextTurn();
  assert.equal(ui.document.querySelector('.wb-execution-feedback').dataset.state,'checking');
  ui.document.activeElement=ui.document.body; // Native removal of a focused overlay clears focus.
  await dismiss(ui);
  let expected=ui.document.body;
  if(destination==='another page')ui.leave();
  else if(destination==='another control'){
   expected=ui.root().querySelector('.count-setting input');expected.focus();
  }
  gate.resolve(plan);await pending;
  if(destination==='body')expected=ui.root().querySelector('.wb-clear-recovery-actions').querySelector('button');
  assert.equal(ui.document.activeElement===expected,true,'late completion must respect the current focus and page');
  assert.equal(ui.document.querySelector('.modal'),null);assert.equal(written(ui).length,0);
 });
}

test('confirmation footer reports checking and blocked state without moving focus, and details are user activated',async()=>{
 const ui=await ready(),gate=deferred();
 const footer=ui.document.querySelector('.modal-footer');
 const feedback=footer.querySelector('.wb-execution-feedback');
 assert.ok(feedback,'write actions need an adjacent state summary');
 const status=feedback.querySelector('[role="status"]'),details=ui.document.querySelector('.wb-execution-plan');
 const submit=ui.button('写入数据库',footer);
 assert.equal(submit.getAttribute('aria-describedby'),status.id);
 assert.equal(feedback.dataset.state,'ready');
 ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const pending=setMode(ui);await nextTurn();
 assert.equal(feedback.dataset.state,'checking');assert.match(status.textContent,/正在核对/);
 const back=ui.button('返回调整',footer);back.focus();let scrolled=0;
 details.scrollIntoView=()=>{scrolled++;};
 gate.resolve(blockedPlan);await pending;
 assert.equal(feedback.dataset.state,'blocked');assert.match(status.textContent,/暂不能写入/);
 assert.equal(submit.disabled,true);assert.equal(ui.document.activeElement,back);assert.equal(scrolled,0);
 const show=ui.button('查看原因',feedback);assert.ok(show);assert.equal(show.hidden,false);
 assert.equal(show.getAttribute('aria-controls'),details.id);
 await show.click();assert.equal(scrolled,1);assert.equal(ui.document.activeElement,details);
 assert.match(details.textContent,/未选表 orders 引用了 users/);
 const requests=ui.requests.length;ui.context.setLanguage('en');
 assert.match(status.textContent,/Writing is blocked/);assert.ok(ui.button('View reasons',feedback));
 assert.equal(ui.requests.length,requests);assert.equal(written(ui).length,0);
});

test('footer retains checking while an abandoned clear request finishes and then shows ready append state',async()=>{
 const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/execution-plan',()=>gate.promise);
 const pending=setMode(ui);await nextTurn();
 const append=ui.document.querySelector('[aria-label="追加数据"]');append.checked=true;await append.dispatchEvent('change');
 const feedback=ui.document.querySelector('.wb-execution-feedback');assert.ok(feedback);
 assert.equal(feedback.dataset.state,'checking');assert.equal(ui.button('写入数据库',ui.document).disabled,true);
 gate.resolve(blockedPlan);await pending;
 assert.equal(feedback.dataset.state,'ready');assert.equal(ui.button('写入数据库',ui.document).disabled,false);
 assert.equal(feedback.querySelector('button').hidden,true);assert.equal(written(ui).length,0);
});

test('footer exposes plan failures and recovers only after a fresh successful plan',async()=>{
 const ui=await ready();ui.routes.set('/api/workbench/execution-plan',()=>{throw new Error('plan unavailable');});
 await setMode(ui);
 const feedback=ui.document.querySelector('.wb-execution-feedback');assert.ok(feedback);
 assert.equal(feedback.dataset.state,'failure');assert.match(feedback.textContent,/未能完成/);
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/plan unavailable/);
 assert.equal(ui.button('清空并生成',ui.document).disabled,true);
 ui.routes.set('/api/workbench/execution-plan',()=>plan);
 await ui.button('重新检查清空计划',ui.document.querySelector('.wb-execution-plan')).click();
 assert.equal(feedback.dataset.state,'ready');assert.equal(ui.button('清空并生成',ui.document).disabled,false);
 assert.equal(written(ui).length,0);
});

test('footer reports writing and failed submission without a duplicate write or focus jump',async()=>{
 const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/runs',async()=>{await gate.promise;throw new Error('write unavailable');});
 const submit=ui.button('写入数据库',ui.document);submit.focus();
 const pending=submit.click();await nextTurn();
 const feedback=ui.document.querySelector('.wb-execution-feedback');assert.ok(feedback);
 assert.equal(feedback.dataset.state,'busy');assert.match(feedback.textContent,/正在提交/);
 await submit.click();assert.equal(written(ui).length,1);
 gate.resolve();await pending;
 assert.equal(feedback.dataset.state,'failure');assert.equal(ui.document.activeElement,submit);
 assert.match(ui.document.querySelector('.wb-execution-plan').textContent,/write unavailable/);
 assert.equal(written(ui).length,1);
});

test('blocked append status directs the user to complete generation diagnostics',async()=>{
 const ui=harness();ui.routes.set('/api/workbench/check',()=>({ok:false,config_hash:'invalid',order:['users'],issues:[
  {severity:'error',table:'users',code:'invalid_rule',message:'Invalid amount range'}]}));
 await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('查看生成计划').click();
 const feedback=ui.document.querySelector('.wb-execution-feedback'),details=ui.document.querySelector('.wb-execution-plan');
 assert.equal(feedback.dataset.state,'blocked');assert.equal(ui.button('写入数据库',ui.document).disabled,true);
 await ui.button('查看原因',feedback).click();
 assert.equal(ui.document.activeElement,details);assert.match(details.textContent,/users.*Invalid amount range/);
 assert.equal(written(ui).length,0);
});

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
