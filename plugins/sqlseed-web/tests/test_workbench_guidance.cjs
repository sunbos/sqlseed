const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {harness, plain} = require('./workbench_harness.cjs');
const tick = () => new Promise(resolve => setImmediate(resolve));
const guide = ui => ui.root().querySelector('.wb-next-step');
const redraw = ui => vm.runInContext('drawBody()', ui.context);

test('empty-plan stages explain prerequisites and focus selection without execution requests',async()=>{
  const ui=harness();await ui.mount();
  for(const stage of [2,3,1]) {
    await guide(ui).querySelector(`[data-guide-action="stage-${stage}"]`).click();
    assert.equal(guide(ui).querySelector('[aria-current="step"]').getAttribute('data-guide-action'),`stage-${stage}`);
    assert.match(guide(ui).textContent,/先选择要生成的表/);
    assert.equal(ui.document.activeElement.getAttribute('aria-label'),'生成 users');
  }
  assert.equal(ui.requests.some(r=>r.url.endsWith('/preview')||r.url.endsWith('/check')||r.url.endsWith('/runs')),false);
});

test('guide navigation returns to rules without resetting previews and never writes directly', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  await guide(ui).querySelector('[data-guide-action="stage-2"]').click();
  const before=plain(m.document), epoch=m.epoch;
  assert.equal(m.view.page,'preview');
  await guide(ui).querySelector('[data-guide-action="stage-1"]').click();
  assert.equal(m.view.page,'fields');assert.equal(m.epoch,epoch);assert.deepEqual(plain(m.document),before);
  assert.match(guide(ui).textContent,/调整表与字段规则/);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/runs')),false);
  const input=ui.root().querySelector('input[aria-label="users 生成数量"]');
  input.value='0';await input.dispatchEvent('input');
  assert.equal(guide(ui).querySelector('[data-guide-action="stage-2"]').disabled,false);
  assert.equal(guide(ui).querySelector('[data-guide-action="stage-3"]').disabled,false);
  await guide(ui).querySelector('[data-guide-action="stage-1"]').click();assert.equal(ui.document.activeElement,input);
});

test('the themed count stepper keeps the existing validation and preview invalidation', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();
  assert.equal(ui.root().querySelector('[aria-label="users 增加 1 行"]').disabled,true);
  m.toggleTable('users',true);redraw(ui);await ui.button('预览数据').click();
  await ui.root().querySelector('[aria-label="users 增加 1 行"]').click();
  assert.equal(m.table('users').count,101);assert.match(guide(ui).textContent,/配置已变化/);
  await ui.root().querySelector('[aria-label="users 减少 1 行"]').click();assert.equal(m.table('users').count,100);
  const input=ui.root().querySelector('input[aria-label="users 生成数量"]');input.value='0';await input.dispatchEvent('input');
  await ui.root().querySelector('[aria-label="users 增加 1 行"]').click();
  assert.equal(input.value,'0');assert.ok(m.errors.size);assert.equal(m.table('users').count,100);
  input.value='1';await input.dispatchEvent('input');const epoch=m.epoch;
  await ui.root().querySelector('[aria-label="users 减少 1 行"]').click();
  assert.equal(m.epoch,epoch);assert.equal(m.table('users').count,1);
});

test('an oversized generation draft identifies its table in ten-row preview and repairs the original count without saving or running',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();
  m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  const input=ui.root().querySelector('[aria-label="users 生成数量"]');
  input.value='1000000000000000';await input.dispatchEvent('input');
  input.value='10000000000000000';await input.dispatchEvent('input');
  assert.match(guide(ui).textContent,/生成数量待修正/);
  assert.doesNotMatch(guide(ui).textContent,/计划生成 1000000000000100/);
  assert.equal(m.table('users').count,1000000000000000);
  assert.equal(m.view.invalidCounts.users,'10000000000000000');
  await ui.button('预览已选表').click();
  const previewCount=ui.document.querySelector('[aria-label="每表预览行数"]');
  assert.equal(previewCount.value,'10');assert.equal(previewCount.getAttribute('aria-invalid'),null);
  assert.match(ui.document.querySelector('.wb-preview-error').textContent,/预览 10 行符合.*正式生成配置.*users.*9,007,199,254,740,991/);
  assert.match(ui.root().querySelector('.wb-operation-status').textContent,/users.*生成数量/);
  assert.equal(ui.root().querySelector('.wb-operation-status').hidden,false);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/preview')),false);
  await ui.button('修正 users 生成数量',ui.document).click();
  assert.equal(ui.document.querySelector('.modal'),null);assert.equal(ui.document.activeElement,input);
  input.value='1000000';await input.dispatchEvent('input');
  assert.equal(m.errors.size,0);assert.equal(m.view.invalidCounts.users,undefined);
  assert.equal(ui.root().querySelector('.wb-operation-status').hidden,true);
  assert.equal(ui.root().querySelector('.wb-operation-status').textContent,'');
  assert.equal(ui.root().querySelector('.wb-notice').textContent,'');
  assert.equal(ui.root().querySelector('.wb-notice').classList.contains('wb-error'),false);
  assert.match(guide(ui).textContent,/计划生成 1,000,100 行/);
  await ui.button('预览已选表').click();
  const requests=ui.requests.filter(request=>request.url.endsWith('/preview'));
  assert.equal(requests.length,1);
  const payload=JSON.parse(requests[0].options.body);
  assert.equal(payload.count,10);assert.equal(payload.document.tables.find(table=>table.name==='users').count,1000000);
  assert.equal(m.table('users').count,1000000);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/runs')||request.url.includes('/drafts')&&['POST','PUT'].includes(request.options.method)),false);
});

test('restored inline preview clears its formal-count error notices only after the invalid count is repaired',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);
  m.restoreView({table:'users',page:'preview',invalidCounts:{users:'10000000000000000'}});
  await redraw(ui);
  assert.match(ui.root().querySelector('.wb-preview-error').textContent,/预览 10 行符合.*正式生成配置.*users/);
  assert.equal(ui.document.querySelector('.modal'),null);
  const banner=ui.root().querySelector('.wb-operation-status');
  assert.equal(banner.hidden,false);assert.match(banner.textContent,/users.*生成数量/);
  await ui.button('修正 users 生成数量').click();
  const input=ui.root().querySelector('[aria-label="users 生成数量"]');
  assert.equal(ui.document.activeElement,input);
  input.value='0';await input.dispatchEvent('input');
  assert.ok(m.errors.has('count:users'));assert.equal(banner.hidden,false);
  input.value='100';await input.dispatchEvent('input');
  assert.equal(m.errors.size,0);assert.equal(banner.hidden,true);assert.equal(banner.textContent,'');
  assert.equal(ui.root().querySelector('.wb-notice').textContent,'');
  assert.equal(ui.root().querySelector('.wb-notice').classList.contains('wb-error'),false);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/preview')||request.url.endsWith('/runs')||request.url.includes('/drafts')&&['POST','PUT'].includes(request.options.method)),false);
});

test('guidance locates an invalid unselected table count and repairs its draft without adding it to generation',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);
  m.restoreView({tableDrafts:{orders:{name:'orders',count:1e21,columns:[]}}});redraw(ui);
  const selected=plain(m.document.tables),epoch=m.epoch;
  assert.equal(m.view.table,'users');assert.equal(m.selected('orders'),false);
  await ui.button('检查输入',guide(ui)).click();
  assert.equal(m.view.table,'orders');assert.equal(m.view.page,'fields');assert.equal(m.epoch,epoch);
  const input=ui.root().querySelector('[aria-label="orders 生成数量"]');
  assert.equal(input.disabled,false);assert.equal(input.getAttribute('aria-invalid'),'true');
  assert.equal(ui.document.activeElement,input);assert.equal(m.selected('orders'),false);
  input.value='37';await input.dispatchEvent('input');
  assert.equal(m.errors.size,0);assert.equal(m.view.invalidCounts.orders,undefined);
  assert.equal(m.view.tableDrafts.orders.count,37);assert.equal(m.selected('orders'),false);
  assert.deepEqual(plain(m.document.tables),selected);
  assert.doesNotMatch(guide(ui).textContent,/生成数量待修正|超出工作台/);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/preview')||request.url.endsWith('/check')||request.url.endsWith('/runs')||request.url.includes('/drafts')&&['POST','PUT'].includes(request.options.method)),false);
});

test('guidance totals safe per-table counts exactly even when their sum exceeds number precision',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();
  for(const name of ['users','orders','audit'])m.toggleTable(name,true);
  m.setCount('users',String(Number.MAX_SAFE_INTEGER));m.setCount('orders',String(Number.MAX_SAFE_INTEGER));m.setCount('audit','1');
  redraw(ui);assert.equal(m.errors.size,0);
  assert.match(guide(ui).textContent,/计划生成 18,014,398,509,481,983 行/);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/preview')||request.url.endsWith('/runs')),false);
});

test('browser generation defaults seed new documents but never loaded or imported ones', async () => {
  const ui=harness({generationDefaults:{provider:'faker',locale:'zh_CN',count:250,seed:42,previewCount:25}});await ui.mount();
  let m=ui.modelState();m.toggleTable('users',true);
  assert.equal(m.document.provider,'faker');assert.equal(m.document.locale,'zh_CN');assert.equal(m.table('users').count,250);
  assert.equal(m.table('users').seed,42);assert.equal(m.view.previewCount,25);assert.deepEqual(plain(m.view.tableDrafts),{});
  m.replaceDocument({provider:'base',locale:'en_US',tables:[{name:'users',count:7,columns:[]}]});
  assert.equal(m.document.provider,'base');assert.equal(m.table('users').count,7);assert.equal(m.table('orders').count,100);
  assert.equal(m.table('orders').seed,undefined);
  ui.routes.set('/api/workbench/drafts/existing',()=>({id:'existing',revision:1,name:'Existing',target_key:'target-A',schema_hash:'schema-v1',document:{provider:'base',locale:'en_US',tables:[{name:'users',count:9,columns:[]}]}}));
  ui.context.location.hash='#/workbench?draft=existing';await ui.mount();m=ui.modelState();
  assert.equal(m.document.provider,'base');assert.equal(m.table('users').count,9);assert.equal(m.table('orders').count,100);
});

test('first-use guidance teaches selection and never starts AI or a database write', async () => {
  const ui=harness();await ui.mount();await tick();
  assert.ok(guide(ui));assert.match(guide(ui).textContent,/先选择要生成的表/);
  assert.ok(ui.button('选择生成表',guide(ui)));
  assert.match(guide(ui).querySelector('[aria-current="step"]').textContent, /设定规则/);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('guidance AI shortcut uses selected scope and preserves the executable document', async () => {
  const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'test'}}));
  await ui.mount();await tick();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  const before=plain(m.document);assert.match(guide(ui).textContent,/已选 2 张表 · 计划生成 200 行/);
  await ui.button('AI 配置助手').click();await tick();
  assert.equal(ui.document.querySelector('input[value="selected"]').checked,true);
  assert.deepEqual(plain(m.document),before);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')),false);
});

test('direct preview is optional and stale results return guidance to preview after an edit', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  await ui.button('直接预览',guide(ui)).click();
  assert.match(guide(ui).textContent,/已预览所选 1 张表/);
  assert.ok(ui.button('查看生成计划',guide(ui)));
  assert.match(guide(ui).querySelector('[aria-current="step"]').textContent, /确认写入/);
  await ui.button('字段规则').click();await ui.openRule('amount');await ui.edit('max_value','15');await ui.applyRule();
  assert.match(guide(ui).textContent,/配置已变化，请重新预览/);
  assert.match(guide(ui).querySelector('[aria-current="step"]').textContent, /预览样例/);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('partial preview never claims all selected tables have been previewed', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  await ui.button('预览数据').click();
  assert.match(guide(ui).textContent,/已预览 1\/2 张所选表/);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  ui.routes.set('/api/workbench/preview',()=>({ok:true,preview_complete:false,issues:[],samples:{users:[{amount:3}]}}));
  await ui.button('预览已选范围',guide(ui)).click();
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
});

for(const [target,currentEpoch,expected] of [
  ['audit',true,/已应用 1 条 AI 建议，请预览/],
  ['users',true,/已预览 1\/2 张所选表/],
  ['orders',true,/已预览 1\/2 张所选表/],
  ['audit',false,/已预览 1\/2 张所选表/],
])test(`partial preview prioritizes only pending selected AI targets: ${target}, current epoch ${currentEpoch}`,async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  await ui.button('预览数据').click();
  m.aiApplied={epoch:currentEpoch?m.epoch:m.epoch-1,targets:[{table:target,column:target==='users'?'amount':'event'}]};
  redraw(ui);
  assert.match(guide(ui).textContent,expected);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('input errors take priority and collapsed guide keeps its preference through redraw', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  const input=ui.root().querySelector('input[aria-label="users 生成数量"]');input.value='0';await input.dispatchEvent('input');
  assert.match(guide(ui).textContent,/先修正无效输入/);
  await ui.button('检查输入',guide(ui)).click();assert.equal(ui.document.activeElement,input);
  await ui.button('收起引导',guide(ui)).click();redraw(ui);
  assert.ok(ui.button('展开引导',guide(ui)));assert.notEqual(guide(ui).querySelector('.wb-next-step-body').getAttribute('hidden'),null);
  await ui.button('展开引导',guide(ui)).click();assert.equal(guide(ui).querySelector('.wb-next-step-body').getAttribute('hidden'),null);
});

for(const [config,label] of [[{available:false},'安装 AI 扩展'],[{available:true,ready:false},'配置 AI 助手']]) {
  test(`AI readiness exposes ${label} without preventing manual preview`,async()=>{
    const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>config);await ui.mount();await tick();
    const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
    assert.ok(ui.button('AI 配置助手'));assert.equal(ui.button('直接预览',guide(ui)).disabled,false);
    assert.equal(guide(ui).querySelector('.wb-next-step-ai'),null);
  });
}

test('broken AI imports request an environment check and keep manual preview available',async()=>{
  const ui=harness();
  ui.routes.set('/api/workbench/ai/config',()=>({available:false,ready:false,availability_status:'import_error'}));
  await ui.mount();await tick();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  assert.ok(ui.button('AI 配置助手'));
  assert.equal(ui.button('直接预览',guide(ui)).disabled,false);
  const before=plain(m.document);await ui.button('AI 配置助手').click();await tick();
  assert.match(ui.document.querySelector('[aria-label="AI 状态"]').textContent,/AI 插件加载异常/);
  assert.deepEqual(plain(m.document),before);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('selection guidance focuses visible search results and falls back to search when empty',async()=>{
  const ui=harness();await ui.mount();const search=ui.root().querySelector('input[aria-label="查找表"]');
  search.value='audit';await search.dispatchEvent('input');await ui.button('选择生成表',guide(ui)).click();
  assert.equal(ui.document.activeElement.getAttribute('aria-label'),'生成 audit');
  search.value='missing';await search.dispatchEvent('input');await ui.button('选择生成表',guide(ui)).click();
  assert.equal(ui.document.activeElement,search);
});
