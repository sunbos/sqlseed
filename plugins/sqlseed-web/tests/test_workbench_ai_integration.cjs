const test = require('node:test');
const assert = require('node:assert/strict');
const {harness, plain, deferred} = require('./workbench_harness.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const config = {available:true, ready:true, effective:{backend:'ollama',model:'local-test',base_url:'http://localhost:11434/v1'}};
const suggestion = {table:'users',column:'amount',before:null,
  after:{name:'amount',generator:'integer',params:{min_value:5,max_value:50}},reason:'数量应使用有界整数'};
const response = {schema_hash:'schema-v1',suggestions:[suggestion],rejected:[]};
async function ready(ui) {
  ui.routes.set('/api/workbench/ai/config', () => config);
  ui.routes.set('/api/workbench/ai/suggest', () => response);
  await ui.mount();
}
async function openAI(ui) {
  const entry = ui.button('AI 配置助手'); assert.ok(entry, 'AI must be reachable from the real workbench header');
  await entry.click(); await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]').getAttribute('aria-label'), 'AI 配置助手');
  assert.equal(ui.button('开始分析',ui.document).disabled,false);
}
async function select(ui,index=0) {
  const box = ui.document.querySelector(`[data-ai-suggestion="${index}"]`); assert.ok(box);
  box.checked=true; await box.dispatchEvent('change');
}
function assertNoWriteRequests(ui) {
  assert.equal(ui.requests.some(item=>item.url==='/api/workbench/runs' || /\/fill$/.test(item.url)),false);
}

test('header AI review applies a column to an unselected table draft while preserving scope and invalidating check',async()=>{
  const ui=harness();await ready(ui);
  const model=ui.modelState();model.toggleTable('audit',true);
  model.acceptCheck({ok:true,config_hash:'checked',samples:{audit:[{event:'old'}]},issues:[],order:['audit'],layers:[['audit']]},model.epoch);
  const before=plain(model.document);
  await openAI(ui);await ui.button('开始分析',ui.document).click();
  const request=JSON.parse(ui.requests.find(item=>item.url==='/api/workbench/ai/suggest').options.body);
  assert.equal(request.conn_id,'A');assert.equal(request.schema_hash,'schema-v1');assert.deepEqual(request.tables,['users']);
  assert.deepEqual(request.document.tables.map(item=>item.name),['audit']);
  assert.deepEqual(request.table_drafts,[]);
  assert.deepEqual(request.allowed_targets.map(item=>item.table),['users']);
  assert.ok(request.allowed_targets[0].columns.includes('amount'));
  assert.deepEqual(plain(model.document),before,'Analysis itself must not select the current table or change its rules');
  assert.equal(model.check.config_hash,'checked');
  assert.equal(ui.button('应用所选建议',ui.document).disabled,true);
  await select(ui);await ui.button('应用所选建议',ui.document).click();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.deepEqual(plain(model.document),before,'AI rule edits on an unselected table stay in its draft');
  assert.deepEqual(plain(model.rule('users','amount')),suggestion.after);
  assert.deepEqual(plain(model.view.tableDrafts.users.columns),[suggestion.after]);
  assert.equal(model.check,null);assert.deepEqual(plain(model.samples),{});assert.equal(model.canRun(),false);
  assert.match(ui.root().querySelector('.wb-notice').textContent,/已应用 1 条 AI 建议/);
  assertNoWriteRequests(ui);
  await ui.openRule('amount');assert.equal(ui.field('min_value').value,'5');assert.equal(ui.field('max_value').value,'50');
  assert.equal(ui.button('应用规则',ui.document).disabled,false);await ui.cancelRule();
});

test('whole-database AI review preserves every unselected advanced draft and applies one atomic revision',async()=>{
  const ui=harness();await ready(ui);const model=ui.modelState();
  model.toggleTable('audit',true);
  model.putTable({name:'users',count:77,seed:51,columns:[{name:'amount',generator:'integer',params:{min_value:1,max_value:9},constraints:{unique:true}}]});
  const draftBefore=plain(model.view.tableDrafts.users),scopeBefore=plain(model.document.tables);
  await openAI(ui);const scope=ui.document.querySelector('input[value="database"]');scope.checked=true;await scope.dispatchEvent('change');
  await ui.button('开始分析',ui.document).click();
  const request=JSON.parse(ui.requests.find(item=>item.url.endsWith('/suggest')).options.body);
  assert.deepEqual(request.document.tables,scopeBefore);assert.deepEqual(request.table_drafts,[draftBefore]);
  const epoch=model.epoch;await select(ui);await ui.button('应用所选建议',ui.document).click();
  assert.equal(model.epoch,epoch+1);assert.equal(model.view.tableDrafts.users.count,77);assert.equal(model.view.tableDrafts.users.seed,51);
  assert.deepEqual(plain(model.document.tables),scopeBefore);assertNoWriteRequests(ui);
});

test('AI selected-table analysis applies only checked suggestions and keeps counts and selection unchanged',async()=>{
  const ui=harness();await ready(ui);const model=ui.modelState();model.toggleTable('users',true);model.setCount('users','42');model.toggleTable('audit',true);
  const other={table:'audit',column:'event',after:{name:'event',generator:'string',params:{max_length:15}},reason:'事件文本'};
  ui.routes.set('/api/workbench/ai/suggest',()=>({...response,suggestions:[suggestion,other]}));
  await openAI(ui);
  const scope=ui.document.querySelectorAll('input[type="radio"]').find(input=>input.value==='selected');assert.ok(scope);scope.checked=true;await scope.dispatchEvent('change');
  await ui.button('开始分析',ui.document).click();
  assert.deepEqual(JSON.parse(ui.requests.find(item=>item.url.endsWith('/suggest')).options.body).tables,['users','audit']);
  const beforeAudit=plain(model.rule('audit','event'));
  await select(ui,0);await ui.button('应用所选建议',ui.document).click();
  assert.deepEqual(plain(model.document.tables.map(table=>table.name)),['users','audit']);assert.equal(model.table('users').count,42);
  assert.deepEqual(plain(model.rule('users','amount')),suggestion.after);assert.deepEqual(plain(model.rule('audit','event')),beforeAudit);
  assert.equal(model.document.tables[0].columns[0].params.max_value,50);assertNoWriteRequests(ui);
});

for (const destination of ['close','leave-remount']) {
  test(`late AI suggestions cannot apply after ${destination}`,async()=>{
    const ui=harness();await ready(ui);await openAI(ui);
    const gate=deferred();ui.routes.set('/api/workbench/ai/suggest',()=>gate.promise);
    const pending=ui.button('开始分析',ui.document).click();await tick();
    assert.ok(ui.requests.some(item=>item.url==='/api/workbench/ai/suggest'));
    if(destination==='close')await ui.button('取消',ui.document).click();
    else {ui.leave();await ui.mount();}
    await ui.openRule('amount');await ui.edit('max_value','76');await ui.applyRule();
    const before=plain(ui.modelState().payload('current'));
    gate.resolve(response);await pending;
    assert.deepEqual(plain(ui.modelState().payload('current')),before);assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);
    assert.equal(ui.document.querySelector('[role="dialog"]'),null);assertNoWriteRequests(ui);
  });
}

for(const phase of ['pending','reviewed']) {
  test(`opening a different saved configuration invalidates ${phase} AI suggestions`,async()=>{
    const ui=harness();await ready(ui);await openAI(ui);const oldModel=ui.modelState();
    const gate=deferred();if(phase==='pending')ui.routes.set('/api/workbench/ai/suggest',()=>gate.promise);
    const analysis=ui.button('开始分析',ui.document).click();let staleApply;
    if(phase==='reviewed'){await analysis;await select(ui);staleApply=ui.button('应用所选建议',ui.document);}
    else await tick();
    ui.routes.set('/api/workbench/drafts?conn_id=A',()=>({drafts:[{id:'new',name:'New config',revision:3}]}));
    ui.routes.set('/api/workbench/drafts/new',()=>({id:'new',name:'New config',revision:3,target_key:'target-A',schema_hash:'schema-v1',
      document:{provider:'base',locale:'en_US',tables:[{name:'audit',count:25,columns:[{name:'event',generator:'string',params:{max_length:7}}]}]},view_state:{}}));
    await ui.button('打开配置').click();await ui.document.querySelector('.wb-draft-card').click();
    const newModel=ui.modelState();assert.notEqual(newModel,oldModel);assert.equal(newModel.table('audit').count,25);
    const snapshot=plain(newModel.payload('current'));
    if(phase==='pending'){gate.resolve(response);await analysis;}else await staleApply.click();
    assert.deepEqual(plain(newModel.payload('current')),snapshot);assert.equal(newModel.view.tableDrafts.users,undefined);
    assert.equal(newModel.rule('users','amount').params.max_value,9);assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);
    assertNoWriteRequests(ui);
  });
}

test('applied AI suggestions guide the current selected configuration to preview',async()=>{
  const ui=harness();await ready(ui);const m=ui.modelState();m.toggleTable('users',true);
  await openAI(ui);await ui.button('开始分析',ui.document).click();await select(ui);
  await ui.button('应用所选建议',ui.document).click();
  assert.match(ui.root().querySelector('.wb-next-step').textContent,/已应用 1 条 AI 建议，请预览/);
  m.setCount('users','35');await ui.button('字段规则').click();
  assert.doesNotMatch(ui.root().querySelector('.wb-next-step').textContent,/已应用 1 条 AI 建议，请预览/);
  assertNoWriteRequests(ui);
});

test('applying AI from another table preview keeps the AI next step until its targets are previewed',async()=>{
  const ui=harness();await ready(ui);const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);
  ui.routes.set('/api/workbench/preview',options=>{
    const names=JSON.parse(options.body).document.tables.map(table=>table.name);
    return {ok:true,preview_complete:true,issues:[],samples:Object.fromEntries(names.map(name=>[name,[name==='users'?{amount:5}:{event:'created'}]]))};
  });
  await ui.root().querySelector('[data-table="audit"]').querySelector('.wb-table-name').click();
  await ui.button('预览数据').click();
  await openAI(ui);
  const scope=ui.document.querySelector('input[value="selected"]');scope.checked=true;await scope.dispatchEvent('change');
  await ui.button('开始分析',ui.document).click();await select(ui);
  await ui.button('应用所选建议',ui.document).click();await tick();
  const previews=ui.requests.filter(item=>item.url==='/api/workbench/preview');
  assert.equal(previews.length,2,'Applying AI refreshes the active table preview');
  assert.deepEqual(JSON.parse(previews[1].options.body).document.tables.map(table=>table.name),['audit']);
  assert.equal(m.view.page,'preview');assert.equal(m.view.table,'audit');
  assert.deepEqual(plain(m.rule('users','amount')),suggestion.after);
  assert.match(ui.root().querySelector('.wb-next-step').textContent,/已应用 1 条 AI 建议，请预览/);
  await ui.button('预览 AI 调整结果').click();
  assert.match(ui.root().querySelector('.wb-next-step').textContent,/已预览所选 2 张表/);
  assert.ok(ui.button('查看生成计划'));
  assertNoWriteRequests(ui);
});

async function customDefault(ui) {
  await ready(ui);const m=ui.modelState(),table=m.schema.tables[0];
  table.columns.find(column=>column.name==='metadata').default='0';
  table.mapping.metadata={generator_name:'skip'};
  m.document.custom_column_mappings={exact:{metadata:{generator:'integer',params:{min_value:1,max_value:5}}}};
  m.toggleTable('audit',true);m.putTable({name:'users',count:9,enrich:true,columns:[]});
  return m;
}

test('AI entry resolves custom DEFAULT modes with the full candidate before choosing editable fields',async()=>{
  const ui=harness(),m=await customDefault(ui),before=plain(m.payload('current'));
  ui.routes.set('/api/workbench/ai/eligibility',()=>({schema_hash:'schema-v1',default_modes:{users:{metadata:'integer'}}}));
  await openAI(ui);
  assert.ok(ui.document.querySelector('input[data-ai-column="users.metadata"]'));
  const sent=JSON.parse(ui.requests.find(item=>item.url.endsWith('/eligibility')).options.body);
  assert.deepEqual(sent.document,before.document);assert.deepEqual(sent.table_drafts,[before.view_state.tableDrafts.users]);
  assert.deepEqual(plain(m.payload('current')),before);assertNoWriteRequests(ui);
});

for(const destination of ['close','edit','leave-remount'])test(`late DEFAULT mode resolution cannot reopen AI after ${destination}`,async()=>{
  const ui=harness(),m=await customDefault(ui),gate=deferred();
  ui.routes.set('/api/workbench/ai/eligibility',()=>gate.promise);
  const pending=ui.button('AI 配置助手').click();await tick();
  assert.match(ui.document.querySelector('[role="dialog"]').textContent,/正在解析/);
  assert.equal(ui.button('开始分析',ui.document),undefined);
  if(destination==='close')await ui.button('取消',ui.document).click();
  else if(destination==='edit')m.setCount('users','12');
  else {ui.leave();await ui.mount();}
  gate.resolve({schema_hash:'schema-v1',default_modes:{users:{metadata:'integer'}}});await pending;
  assert.equal(ui.button('开始分析',ui.document),undefined);assertNoWriteRequests(ui);
});

test('ordinary AI entry makes no extra DEFAULT mode request',async()=>{
  const ui=harness();await ready(ui);await openAI(ui);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/eligibility')),false);
});

test('server DEFAULT omission overrides the reflected active generator in AI scope',async()=>{
  const ui=harness(),m=await customDefault(ui);m.schema.tables[0].mapping.metadata={generator_name:'integer'};
  m.document.custom_column_mappings.exact.metadata={generator:'skip'};
  ui.routes.set('/api/workbench/ai/eligibility',()=>({schema_hash:'schema-v1',default_modes:{users:{metadata:'skip'}}}));
  await openAI(ui);
  assert.equal(ui.document.querySelector('input[data-ai-column="users.metadata"]'),null);
  assert.match(ui.document.querySelector('[data-ai-protected-column="users.metadata"]').textContent,/当前使用数据库 DEFAULT/);
});

test('unselected enriched DEFAULT columns also resolve without custom mappings',async()=>{
  const ui=harness(),m=await customDefault(ui);delete m.document.custom_column_mappings;
  ui.routes.set('/api/workbench/ai/eligibility',()=>({schema_hash:'schema-v1',default_modes:{users:{metadata:'choice'}}}));
  await openAI(ui);assert.ok(ui.document.querySelector('input[data-ai-column="users.metadata"]'));
  assert.ok(ui.requests.some(item=>item.url.endsWith('/eligibility')));
});

test('custom mappings without DEFAULT columns need no eligibility request',async()=>{
  const ui=harness();await ready(ui);ui.modelState().document.custom_column_mappings={exact:{amount:{generator:'integer'}}};
  await openAI(ui);assert.equal(ui.requests.some(item=>item.url.endsWith('/eligibility')),false);
});

for(const response of [null,{schema_hash:'stale',default_modes:{}}])test(`DEFAULT resolution failure stays non-actionable: ${JSON.stringify(response)}`,async()=>{
  const ui=harness();await customDefault(ui);
  ui.routes.set('/api/workbench/ai/eligibility',()=>{if(!response)throw new Error('规则解析失败');return response;});
  await ui.button('AI 配置助手').click();
  assert.ok(ui.document.querySelector('[role="alert"]'));assert.equal(ui.button('开始分析',ui.document),undefined);
  assertNoWriteRequests(ui);
});

for(const availability of ['not_installed','import_error'])test(`DEFAULT preflight ${availability} opens plugin settings with the field context and never bypasses protection`,async()=>{
  const ui=harness(),m=await customDefault(ui),before=plain(m.payload('current'));
  ui.routes.set('/api/workbench/ai/eligibility',()=>new Response(JSON.stringify({detail:{code:'ai_unavailable',availability_status:availability,message:'AI 扩展不可用'}}),{status:503}));
  await ui.openRule('metadata');await ui.document.querySelector('[data-rule-ai]').click();
  const dialog=ui.document.querySelector('[role="dialog"]');
  assert.match(dialog.textContent,availability==='import_error'?/加载异常.*规则建议与分析不可用/:/未安装.*规则建议与分析不可用/);
  assert.equal(ui.button('开始分析',dialog),undefined);assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest')),false);
  await ui.button('前往插件设置',dialog).click();
  assert.equal(ui.location.hash,'#/settings?section=plugins');
  assert.deepEqual(plain(m.payload('current')),before);ui.leave();
  ui.routes.set('/api/workbench/connections/A/schema',()=>m.schema);
  ui.routes.set('/api/workbench/ai/eligibility',()=>({schema_hash:'schema-v1',default_modes:{users:{metadata:'skip'}}}));
  ui.location.hash=ui.handoff.requestAIReturn('A');ui.handoff.leaveAISettings(ui.location.hash);await ui.mount();await tick();
  assert.equal(ui.requests.filter(item=>item.url.endsWith('/eligibility')).length,2);
  assert.equal(ui.document.querySelector('input[value="columns"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-column="users.metadata"]'),null);
  assert.equal(ui.document.querySelector('[data-ai-column="users.amount"]').checked,false);
  assert.equal(ui.button('开始分析',ui.document).disabled,true);
  assert.deepEqual(plain(m.payload('current')),before);assertNoWriteRequests(ui);ui.leave();
});
