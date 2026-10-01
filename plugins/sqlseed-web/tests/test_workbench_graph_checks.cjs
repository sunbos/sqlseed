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
  assert.ok(card.querySelectorAll('button').find(button=>button.textContent==='定位 users'));
  assert.ok(card.querySelectorAll('button').find(button=>button.textContent==='定位 orders'));
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

for(const legacy of [false,true])for(const dialect of ['sqlite','postgresql'])test(`issue scope explains the real department cycle from ${legacy?'legacy edge IDs':'structured references'} on ${dialect} while viewing tenants`,async()=>{
  const ui=harness(),fixture=require('./complex_business_graph.json');
  const data={...schema(),...structuredClone(fixture),dialect,tables:fixture.tables.map(table=>({
    ...structuredClone(table),primary_key:[],unique_constraints:[],checks:[],mapping:{},
    columns:table.columns.map(column=>({...column,nullable:true,default:null})),
    foreign_keys:fixture.edges.filter(edge=>edge.target===table.name).map(edge=>({
      id:edge.id,columns:edge.targetColumns,ref_table:edge.source,ref_columns:edge.sourceColumns,nullable:edge.nullable
    }))
  }))};
  const issue=structuredClone(fixture.checks.cycles.issues[0]);
  if(legacy)delete issue.references;
  ui.routes.set('/api/workbench/connections/A/schema',()=>data);
  ui.routes.set('/api/workbench/check',()=>checked([issue]));
  await ui.mount();
  for(const name of ['addresses','departments','employees','tenants'])ui.modelState().toggleTable(name,true);
  vm.runInContext("executionChecks.set(session.model,{epoch:session.model.epoch,lifecycle:session.model.lifecycleVersion,state:'pending'})",ui.context);
  const clearIntent=plain(vm.runInContext('executionChecks.get(session.model)',ui.context));
  await ui.root().querySelector('[data-table="tenants"]').querySelector('.wb-table-graph').click();
  const before=plain(ui.modelState().document);
  await topCheck(ui).click();await ui.document.querySelector('.modal-head').querySelector('.close').click();
  const requestCount=ui.requests.length;
  await control(ui,'issues').click();
  const panel=ui.root().querySelector('.wb-inspector'),card=panel.querySelector('.dependency-card');
  assert.ok(card,'Check issues shows overall blockers, not the unrelated current-table zero count');
  assert.match(card.textContent,/departments\.manager_id 引用 employees\.id/);
  assert.match(card.textContent,/employees\.department_id 引用 departments\.id/);
  assert.match(card.textContent,/取消勾选：departments、employees、tenants/);
  assert.match(card.textContent,/当前工作台无法从空表重建这个循环/);
  assert.match(card.textContent,/SQLite 已有父键满足检查时可保留记录并追加/);
  assert.match(card.textContent,dialect==='sqlite' ? /核对其余表的清空计划.*新的规则与清空检查结果为准/ : /PostgreSQL.*仅支持追加.*清空重建需要数据库工具/);
  assert.doesNotMatch(card.textContent,/其余表仍可选择清空后生成/);
  assert.notEqual(panel.querySelector('.inspector-actions').getAttribute('hidden'),null);
  assert.equal(ui.modelState().view.table,'tenants');
  assert.equal(ui.requests.length,requestCount);
  ui.context.setLanguage('en');
  assert.match(card.textContent,/departments\.manager_id references employees\.id/);
  assert.match(card.textContent,/does not change the scope/);
  assert.match(card.textContent,/cannot rebuild this cycle from empty tables/);
  assert.match(card.textContent,/SQLite append can retain existing records when parent-key checks pass/);
  assert.match(card.textContent,dialect==='sqlite' ? /Execution still requires.*checks to pass/ : /append only for PostgreSQL.*will not be switched automatically/);
  ui.context.setLanguage('zh-CN');
  await ui.button('查看 departments.manager_id 字段信息',card).click();
  assert.equal(ui.modelState().view.table,'departments');
  const field=ui.document.querySelector('.drawer');
  assert.match(field.textContent,/departments\.manager_id/);
  assert.equal(field.querySelector('[role="tab"][aria-selected="true"]').textContent,'字段信息');
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.modelState().check.ok,false);
  await ui.document.dispatchEvent({type:'keydown',key:'Escape'});
  await control(ui,'issues').click();
  const search=ui.root().querySelector('.wb-table-search').querySelector('input');
  search.value='tenants';await search.dispatchEvent('input');
  assert.equal(ui.root().querySelector('[data-table="departments"]').hidden,true);
  assert.equal(vm.runInContext('sidebarViews.get(session.model).query',ui.context),'tenants');
  const locateScope=ui.button('定位需要调整的勾选项',ui.root().querySelector('.wb-inspector'));
  const alternatives=locateScope.closest('details');assert.equal(Boolean(alternatives.open),false);alternatives.open=true;
  await locateScope.click();
  const target=ui.root().querySelector('[data-table="departments"]'),selection=target.querySelector('input[type="checkbox"]');
  assert.equal(target.hidden,false);
  assert.equal(ui.root().querySelector('.wb-table-search').querySelector('input').value,'');
  assert.equal(vm.runInContext('sidebarViews.get(session.model).query',ui.context),'');
  assert.equal(ui.document.activeElement,selection);assert.equal(selection.checked,true);
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.length,requestCount);
  assert.deepEqual(plain(vm.runInContext('executionChecks.get(session.model)',ui.context)),clearIntent);
  assert.deepEqual(Array.from(ui.context.missingMessages()),[]);
});
