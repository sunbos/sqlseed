const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain,deferred,schema}=require('./workbench_harness.cjs');

const cycleIssue={severity:'error',code:'cross_table_cycle',message:'跨表循环需要处理',
  tables:['users','orders'],edge_ids:['orders-user','users-order']};
const checked=issues=>({ok:!issues.length,config_hash:'checked',order:issues.length?[]:['users','orders'],layers:[],samples:{},issues});
const topCheck=ui=>ui.root().querySelector('[data-dependency-count]').closest('button');
const control=(ui,name)=>ui.root().querySelector(`[data-graph-action="${name}"]`);
const view=ui=>plain(vm.runInContext('graph.getView()',ui.context));

async function ready() {
  const ui=harness(),data=schema();
  data.edges.push({id:'users-order',source:'orders',target:'users',sourceColumns:['user_id'],targetColumns:['amount']});
  ui.routes.set('/api/workbench/connections/A/schema',()=>data);
  await ui.mount();
  for(const table of ['users','orders']) {
    const input=ui.root().querySelector(`[data-table="${table}"]`).querySelector('input[type="checkbox"]');
    input.checked=true;await input.dispatchEvent('change');
  }
  await ui.root().querySelector('[data-table="orders"]').querySelector('.wb-table-graph').click();
  return ui;
}

test('the real top-level check immediately refreshes graph issues and preserves its complete view',async()=>{
  const ui=await ready(),beforeDocument=plain(ui.modelState().document);
  assert.equal(Boolean(control(ui,'issues').disabled),false);
  assert.equal(control(ui,'issues').textContent,'检查问题');
  await control(ui,'readable').click();await control(ui,'zoom-in').click();
  await control(ui,'expand').click();
  const labels=ui.root().querySelector('[data-graph-label-toggle]');labels.checked=true;await labels.dispatchEvent('change');
  await ui.root().querySelector('[data-graph-edge="orders-user"]').click();
  const canvas=ui.root().querySelector('[data-graph-canvas]');canvas.scrollLeft=59;canvas.scrollTop=37;
  const before=view(ui), heading=ui.root().querySelector('.table-heading'), scope=ui.root().querySelector('.wb-graph-section').parentElement;
  const opener=topCheck(ui);
  ui.routes.set('/api/workbench/check',()=>checked([cycleIssue]));
  await opener.click();
  assert.equal(control(ui,'issues').textContent,'检查问题 · 1','The result must reach the visible graph without switching tabs');
  assert.deepEqual(view(ui),before,'Scope, path anchor, focused table/edge, labels, zoom, pan and expansion survive');
  assert.equal(ui.root().querySelector('.table-heading'),heading);
  assert.equal(ui.root().querySelector('.wb-graph-section').parentElement,scope);
  assert.equal(topCheck(ui),opener,'The modal opener remains connected for focus restoration');
  assert.ok(ui.root().querySelector('.wb-graph-workspace').classList.contains('expanded'));
  assert.equal(ui.root().querySelector('[data-graph-edge="orders-user"]').getAttribute('data-issue'),'true');
  assert.deepEqual(plain(ui.modelState().document),beforeDocument);
  await ui.document.querySelector('.modal-head').querySelector('.close').click();
  await control(ui,'issues').click();
  assert.deepEqual(ui.root().querySelectorAll('[data-graph-node]').map(node=>node.dataset.graphNode).sort(),['orders','users']);
});

test('a subsequent successful top-level check removes stale graph issue styling in place',async()=>{
  const ui=await ready();ui.routes.set('/api/workbench/check',()=>checked([cycleIssue]));
  await topCheck(ui).click();await ui.document.querySelector('.modal-head').querySelector('.close').click();
  await control(ui,'all').click();
  ui.routes.set('/api/workbench/check',()=>checked([]));
  await topCheck(ui).click();
  assert.equal(Boolean(control(ui,'issues').disabled),false);
  assert.equal(control(ui,'issues').textContent,'检查问题');
  assert.equal(view(ui).mode,'all');
  assert.ok(ui.root().querySelectorAll('[data-graph-edge]').every(edge=>edge.getAttribute('data-issue')==='false'));
  await ui.document.querySelector('.modal-head').querySelector('.close').click();
  await control(ui,'issues').click();
  assert.match(ui.root().querySelector('.graph-empty').textContent,/当前检查没有发现问题.*清空范围/);
});

test('a stale check cannot refresh the graph or reopen its result after the document changes',async()=>{
  const ui=await ready(),gate=deferred();ui.routes.set('/api/workbench/check',()=>gate.promise);
  const pending=topCheck(ui).click();await new Promise(resolve=>setImmediate(resolve));
  const count=ui.root().querySelector('[aria-label="orders 生成数量"]');count.value='101';await count.dispatchEvent('input');
  const currentGraph=ui.root().querySelector('.wb-graph-section');
  gate.resolve(checked([cycleIssue]));await pending;
  assert.equal(ui.root().querySelector('.wb-graph-section'),currentGraph);
  assert.equal(Boolean(control(ui,'issues').disabled),false);
  assert.equal(control(ui,'issues').textContent,'检查问题');
  assert.equal(ui.modelState().check,null);
  assert.equal(ui.document.querySelector('.modal'),null);
  await control(ui,'issues').click();
  assert.match(ui.root().querySelector('.graph-empty').textContent,/运行依赖检查后/);
});

test('a structured multi-table issue names the cycle members and locates each without changing generation scope',async()=>{
  const ui=await ready();ui.routes.set('/api/workbench/check',()=>checked([cycleIssue]));
  const before=plain(ui.modelState().document);
  await topCheck(ui).click();
  const card=ui.document.querySelector('.modal').querySelector('.dependency-card');
  assert.match(card.textContent,/users、orders/);
  assert.equal(card.querySelectorAll('button').length,2);
  assert.equal(ui.document.querySelector('.modal').querySelectorAll('button').find(button=>button.textContent==='查看生成计划').disabled,true);
  await card.querySelectorAll('button').find(button=>button.textContent==='定位 users').click();
  assert.equal(ui.document.querySelector('.modal'),null);
  assert.equal(ui.modelState().view.table,'users');assert.equal(ui.modelState().view.page,'graph');
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.modelState().check.ok,false);
  // A distinct selected table without a path into the cycle must not inherit
  // the cycle as its own local blocker; the full-plan notice remains visible.
  ui.modelState().toggleTable('audit',true);
  ui.modelState().check=checked([cycleIssue]);
  await ui.root().querySelector('[data-table="audit"]').querySelector('.wb-table-graph').click();
  const local=ui.root().querySelector('.wb-inspector');
  assert.ok(local);
  assert.equal(local.querySelector('.dependency-card'),null);
  assert.match(local.textContent,/整个计划仍有待处理项/);
});
