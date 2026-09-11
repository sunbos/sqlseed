const test=require('node:test');
const assert=require('node:assert/strict');
const {harness,deferred}=require('./workbench_harness.cjs');
async function ready(){const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);await ui.button('生成数据').click();return ui;}
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
  ui.modelState().toggleTable('users',true); await ui.button('生成数据').click();
  const card=ui.document.querySelector('[aria-label="写入目标"]');
  assert.ok(card, 'confirmation must clearly identify the write target');
  assert.ok(card.textContent.includes(label)); assert.ok(card.textContent.includes(target));
  assert.equal(ui.document.querySelector('[aria-label="清空所选表后生成"]').disabled,dialect!=='sqlite');
  assert.equal(ui.requests.some(r=>r.url==='/api/workbench/runs'),false);
 });
}
