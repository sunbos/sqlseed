const test=require('node:test');
const assert=require('node:assert/strict');
const {harness,plain}=require('./workbench_harness.cjs');

test('global actions, table views and generation results have distinct locations',async()=>{
  const ui=harness();await ui.mount();
  const global=ui.root().querySelector('.heading-actions');
  assert.deepEqual(global.querySelectorAll('button').map(button=>button.textContent),['AI 配置助手','依赖检查','生成数据']);
  const tabs=ui.root().querySelector('[role="tablist"]');assert.ok(tabs);
  assert.deepEqual(tabs.querySelectorAll('[role="tab"]').map(button=>button.textContent),['字段规则','预览数据','关系图']);
  const headers=ui.root().querySelector('.field-table').querySelector('thead').querySelectorAll('th').map(th=>th.textContent);
  assert.deepEqual(headers,['字段','取值规则']);
  assert.equal(ui.root().querySelector('.col-sample'),null);
  assert.equal(ui.button('预览数据',global),undefined);
  assert.ok(ui.button('编辑 YAML'));assert.equal(ui.button('编辑 YAML').closest('details'),null);
});

test('table preview uses an accessible tab panel and leaves formal counts and selection intact',async()=>{
  const ui=harness();await ui.mount();const model=ui.modelState(),before=plain(model.document);
  const preview=ui.root().querySelector('[role="tablist"]').querySelectorAll('[role="tab"]').find(tab=>tab.textContent==='预览数据');
  await preview.click();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  const panel=ui.root().querySelector('.wb-table-preview');assert.ok(panel);
  assert.match(panel.textContent,/users/);assert.ok(panel.querySelector('.wb-preview-data'));
  const active=ui.root().querySelector('[role="tab"][aria-selected="true"]');
  assert.equal(active.textContent,'预览数据');assert.equal(active.getAttribute('tabindex'),'0');
  const associated=ui.document.getElementById(active.getAttribute('aria-controls'));assert.ok(associated);
  assert.equal(associated.getAttribute('role'),'tabpanel');
  assert.equal(associated.getAttribute('aria-labelledby'),active.id);
  const request=JSON.parse(ui.requests.find(item=>item.url==='/api/workbench/preview').options.body);
  assert.equal(request.count,10);assert.deepEqual(request.document.tables.map(table=>table.name),['users']);
  assert.deepEqual(plain(model.document),before);
  await ui.button('字段规则',ui.root().querySelector('[role="tablist"]')).click();
  assert.equal(ui.root().querySelector('.wb-preview-data'),null);
  assert.deepEqual(plain(model.document),before);
});

test('table view arrow keys move focus without issuing a preview until the tab is activated',async()=>{
  const ui=harness();await ui.mount();const tabs=ui.root().querySelector('[role="tablist"]');
  const fields=ui.button('字段规则',tabs),preview=ui.button('预览数据',tabs);
  fields.focus();await fields.dispatchEvent({type:'keydown',key:'ArrowRight',currentTarget:fields,preventDefault(){}});
  assert.equal(ui.document.activeElement,preview);assert.equal(preview.getAttribute('tabindex'),'0');
  assert.equal(fields.getAttribute('tabindex'),'-1');assert.equal(ui.modelState().view.page,'fields');
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,0);
  await preview.click();assert.equal(ui.modelState().view.page,'preview');
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,1);
});

test('cached table previews never exceed a newer limit chosen on another table',async()=>{
  const ui=harness();await ui.mount();const model=ui.modelState(),before=plain(model.document);
  ui.routes.set('/api/workbench/preview',options=>{
    const request=JSON.parse(options.body);
    return {ok:true,samples:Object.fromEntries(request.document.tables.map(table=>[table.name,Array.from({length:request.count},(_,i)=>table.name==='users'?{amount:i}:{event:`event ${i}`})])),issues:[]};
  });
  await ui.button('预览数据').click();
  let limit=ui.document.querySelector('[aria-label="每表预览行数"]');limit.value='100';await limit.dispatchEvent('input');await ui.button('重新预览').click();
  assert.equal(ui.root().querySelector('.wb-preview-data').querySelector('tbody').querySelectorAll('tr').length,100);
  await ui.root().querySelector('[data-table="audit"]').querySelector('.table-button').click();await ui.button('预览数据').click();
  limit=ui.document.querySelector('[aria-label="每表预览行数"]');limit.value='3';await limit.dispatchEvent('input');await ui.button('重新预览').click();
  await ui.root().querySelector('[data-table="users"]').querySelector('.table-button').click();await ui.button('预览数据').click();
  const last=JSON.parse(ui.requests.filter(item=>item.url==='/api/workbench/preview').at(-1).options.body);
  assert.deepEqual(last.document.tables.map(table=>table.name),['users']);assert.equal(last.count,3);
  assert.equal(ui.document.querySelector('[aria-label="每表预览行数"]').value,'3');
  assert.equal(ui.root().querySelector('.wb-preview-data').querySelector('tbody').querySelectorAll('tr').length,3);
  assert.match(ui.root().querySelector('.wb-preview-summary').textContent,/实际展示 3 行.*最多 3 行/);
  assert.deepEqual(plain(model.document),before);
});

for(const status of ['partial','failed']) {
  test(`cached ${status} previews retain their outcome and issues when the tab is reopened`,async()=>{
    const ui=harness();await ui.mount();
    ui.routes.set('/api/workbench/preview',()=>({ok:status==='partial',preview_complete:status!=='partial',samples:{users:[]},issues:[{table:'users',severity:status==='failed'?'error':'warning',message:'请处理来源字段'}]}));
    await ui.button('预览数据').click();await ui.button('字段规则',ui.root().querySelector('[role="tablist"]')).click();await ui.button('预览数据').click();
    assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,1,'The same count and epoch reuse the complete result');
    const preview=ui.root().querySelector('.wb-table-preview');assert.match(preview.textContent,/请处理来源字段/);
    assert.match(preview.querySelector('.wb-preview-empty').textContent,status==='partial'?/依赖.*就绪/:/预览未完成/);
    assert.deepEqual(plain(ui.modelState().document.tables),[]);
  });
}

test('the selected-table preview is a fixed group operation from the sidebar',async()=>{
  const ui=harness();await ui.mount();
  for(const name of ['users','audit']){
    const checkbox=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input');
    checkbox.checked=true;await checkbox.dispatchEvent('change');
  }
  const before=plain(ui.modelState().document),sidebar=ui.root().querySelector('.wb-sidebar');
  const entry=ui.button('预览已选表',sidebar);assert.ok(entry);await entry.click();
  const dialog=ui.document.querySelector('.wb-data-preview');assert.ok(dialog);
  assert.equal(dialog.querySelector('[aria-label="预览范围"]'),null);
  const request=JSON.parse(ui.requests.find(item=>item.url==='/api/workbench/preview').options.body);
  assert.deepEqual(request.document.tables.map(table=>table.name),['users','audit']);
  assert.equal(request.count,10);assert.deepEqual(plain(ui.modelState().document),before);
  await ui.button('关闭',dialog).click();assert.equal(ui.modelState().view.table,'users');
});

test('structure tools keep their open state across table browsing and generation selection redraws',async()=>{
  const ui=harness();await ui.mount();
  let menu=ui.root().querySelector('.wb-structure-menu');assert.ok(menu);
  menu.open=true;await menu.dispatchEvent({type:'toggle',currentTarget:menu});
  await ui.root().querySelector('[data-table="audit"]').querySelector('.table-button').click();
  menu=ui.root().querySelector('.wb-structure-menu');assert.notEqual(menu.getAttribute('open'),null);
  // This minimal DOM does not reflect the details open attribute to its property.
  menu.open=true;
  const checkbox=ui.root().querySelector('[data-table="audit"]').querySelector('input');
  checkbox.checked=true;await checkbox.dispatchEvent('change');
  menu=ui.root().querySelector('.wb-structure-menu');assert.notEqual(menu.getAttribute('open'),null);
  menu.open=false;await menu.dispatchEvent({type:'toggle',currentTarget:menu});
  await ui.root().querySelector('[data-table="users"]').querySelector('.table-button').click();
  assert.equal(ui.root().querySelector('.wb-structure-menu').getAttribute('open'),null);
});

test('table search narrows navigation without changing generation scope and survives redraw',async()=>{
  const ui=harness();await ui.mount();const model=ui.modelState();model.toggleTable('users',true);
  const before=plain(model.document);
  let input=ui.root().querySelector('[aria-label="查找表"]');assert.ok(input);
  input.value='audit';await input.dispatchEvent('input');
  const rows=ui.root().querySelectorAll('.wb-table-entry').filter(row=>!row.hidden);
  assert.deepEqual(rows.map(row=>row.getAttribute('data-table')),['audit']);
  await rows[0].querySelector('.table-button').click();
  input=ui.root().querySelector('[aria-label="查找表"]');assert.equal(input.value,'audit');
  assert.equal(model.view.table,'audit');assert.deepEqual(plain(model.document),before);
  input.value='';await input.dispatchEvent('input');
  assert.equal(ui.root().querySelectorAll('.wb-table-entry').filter(row=>!row.hidden).length,3);
  assert.deepEqual(plain(model.document),before);
});

test('field AI opens from its rule context with only that column selected and keeps protected fields blocked',async()=>{
  const ui=harness();
  ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'local-test',base_url:'http://localhost:11434/v1'}}));
  ui.routes.set('/api/workbench/ai/suggest',()=>({schema_hash:'schema-v1',suggestions:[],rejected:[]}));
  await ui.mount();const before=plain(ui.modelState().document);await ui.selectColumn('amount');
  const drawer=ui.document.querySelector('.drawer');assert.ok(drawer);
  const information=drawer.querySelector('#field-information'),rules=drawer.querySelector('#field-rule');
  assert.equal(information.hidden,false);assert.equal(rules.hidden,true);
  assert.equal(information.querySelector('[data-rule-ai]'),null);
  const fieldAI=rules.querySelector('[data-rule-ai]');assert.ok(fieldAI);assert.equal(fieldAI.disabled,false);
  assert.equal(ui.root().querySelector('.heading-actions').querySelectorAll('button').filter(button=>button.textContent==='AI 配置助手').length,1);
  await ui.button('编辑取值规则',drawer).click();assert.equal(rules.hidden,false);
  await fieldAI.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'AI 配置助手');
  await ui.button('开始分析',ui.document).click();
  const requests=ui.requests.filter(item=>item.url==='/api/workbench/ai/suggest');assert.equal(requests.length,1);
  const request=JSON.parse(requests[0].options.body);
  assert.deepEqual(request.allowed_targets,[{table:'users',columns:['amount']}]);
  assert.deepEqual(plain(ui.modelState().document),before);
  await ui.button('取消',ui.document).click();await ui.selectColumn('id');
  assert.match(ui.document.querySelector('#field-information').textContent,/数据库自动分配|由数据库.*分配/);
  await ui.button('编辑取值规则',ui.document).click();
  const protectedAI=ui.document.querySelector('#field-rule').querySelector('[data-rule-ai]');
  assert.equal(protectedAI.disabled,true);await protectedAI.dispatchEvent('click');
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'id');
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/ai/suggest').length,1);
  await ui.cancelRule();ui.leave();
});

test('dependency blockers precede source details and cannot start generation',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('orders',true);
  m.schema.edges=Array.from({length:38},(_,i)=>({id:`relation-${i}`,source:'users',target:'orders',sourceColumns:['id'],targetColumns:['user_id']}));
  const before=plain(m.document);
  ui.routes.set('/api/workbench/check',()=>({ok:false,issues:[
    {severity:'warning',table:'orders',message:'可空引用提醒'},
    {severity:'error',table:'orders',column:'user_id',message:'无法生成：引用来源不可用'},
  ],layers:[['orders']],order:['orders']}));
  await ui.button('依赖检查').click();
  const body=ui.document.querySelector('.modal-body'),text=body.textContent;
  assert.ok(text.indexOf('无法生成：引用来源不可用')<text.indexOf('users.id → orders.user_id'));
  assert.ok(text.indexOf('无法生成：引用来源不可用')<text.indexOf('可空引用提醒'));
  assert.match(body.querySelector('.wb-dependency-summary').textContent,/1 项阻断.*1 项提醒/);
  assert.match(body.querySelector('.execution-heading').textContent,/依赖分组参考/);
  assert.match(body.textContent,/尚未形成可执行计划/);
  const sources=body.querySelector('.wb-dependency-sources');assert.ok(sources);
  assert.equal(sources.getAttribute('open'),null);assert.equal(sources.querySelectorAll('.wb-source-card').length,38);
  assert.equal(ui.button('生成数据',ui.document.querySelector('.modal-footer')).disabled,true);
  await ui.button('定位 user_id',body).click();
  assert.equal(m.view.table,'orders');assert.deepEqual(plain(m.document),before);
});

test('a failed dependency check enables generation only after the current problem is fixed',async()=>{
  const ui=harness();await ui.mount();ui.modelState().toggleTable('orders',true);
  ui.routes.set('/api/workbench/check',()=>ui.modelState().selected('users')?{ok:true,issues:[],order:['users','orders'],layers:[['users'],['orders']]}:
    {ok:false,issues:[{severity:'error',code:'missing_parent_source',table:'orders',column:'user_id',source_table:'users',message:'缺少父表记录'}],order:['orders'],layers:[['orders']]});
  await ui.button('依赖检查').click();
  const dialog=ui.document.querySelector('.modal');
  assert.equal(ui.button('生成数据',dialog.querySelector('.modal-footer')).disabled,true);
  await ui.button('加入 users（100 行）',dialog).click();
  assert.equal(ui.button('生成数据',dialog.querySelector('.modal-footer')).disabled,false);
  assert.match(dialog.querySelector('.wb-dependency-summary').textContent,/检查通过/);
});
