const test=require('node:test');
const assert=require('node:assert/strict');
const {harness,plain,deferred}=require('./workbench_harness.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const result=table=>({table,target_key:'target-A',target_label:'A.db',dialect:'sqlite',columns:[{name:'id',type:'INTEGER'}],rows:[{id:123}],total:1,limit:50,offset:0,order_by:['id'],read_at:'2026-09-10T03:00:00Z'});

test('workbench current data reads the displayed unselected table without changing rules or selection',async()=>{
  const ui=harness();await ui.mount();
  const before=plain(ui.modelState().document);
  const path='/api/workbench/connections/A/tables/users/data?limit=50&offset=0';ui.routes.set(path,()=>result('users'));
  const open=ui.button('查看当前数据');assert.ok(open);await open.click();await tick();
  assert.match(ui.document.querySelector('.wb-table-data').textContent,/123/);
  assert.deepEqual(plain(ui.modelState().document),before);
  await ui.button('关闭',ui.document).click();assert.equal(ui.modelState().view.table,'users');
});

test('workbench data entry follows current graph table and leaving ignores late results',async()=>{
  const ui=harness();await ui.mount();
  await ui.button('关系图').click();await ui.document.querySelector('[data-graph-node="orders"]').click();
  const gate=deferred(),path='/api/workbench/connections/A/tables/orders/data?limit=50&offset=0';ui.routes.set(path,()=>gate.promise);
  const open=ui.button('查看当前数据');assert.ok(open);await open.click();await tick();
  assert.ok(ui.requests.some(r=>r.url===path));ui.leave();gate.resolve(result('orders'));await tick();
  assert.equal(ui.document.querySelector('.wb-table-data'),null);
});
