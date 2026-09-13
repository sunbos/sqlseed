const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain,schema}=require('./workbench_harness.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function previewControl(ui,name,kind='rule') {
  const entry=ui.document.querySelector(`[data-preview-column="${name}"][data-preview-entry="${kind}"]`);
  assert.ok(entry);return entry;
}
async function openPreviewRule(ui,name) {await previewControl(ui,name).click();}
async function openPreviewAI(ui,name='event') {
  await openPreviewRule(ui,name);
  const ai=ui.button('用 AI 调整',ui.document.querySelector('#field-rule'));
  assert.ok(ai,'AI must belong to the rule panel for the opened field');
  await ai.click();await tick();
}

async function toSettings(ui,label='更改设置'){
  await ui.button(label,ui.document).click();assert.match(ui.location.hash,/^#\/settings\?/);ui.leave();
}
async function fromSettings(ui){
  const hash=ui.handoff.requestAIReturn(ui.store.connId);assert.ok(hash);
  ui.location.hash=hash;ui.handoff.leaveAISettings(hash);await ui.mount();await tick();
}

async function setup(){
  const ui=harness();
  ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'local-test'}}));
  ui.routes.set('/api/workbench/preview',()=>({ok:true,order:['users','audit'],samples:{users:[{amount:3}],audit:[{event:'old event'}]},issues:[]}));
  await ui.mount();ui.modelState().toggleTable('audit',true);ui.modelState().toggleTable('users',true);
  await ui.button('字段规则').click();
  await ui.button('预览已选表').click();
  await ui.button('audit',ui.document.querySelector('.wb-preview-tables')).click();
  return ui;
}

for(const scope of ['inline','batch'])test(`${scope} header opens each exact panel and restores the initiating rule control`,async()=>{
  const ui=scope==='batch'?await setup():harness();
  if(scope==='inline'){await ui.mount();await ui.button('预览数据').click();}
  const column=scope==='batch'?'event':'amount',table=scope==='batch'?'audit':'users';
  const before=plain(ui.modelState().document),reads=ui.requests.length;
  const entry=kind=>ui.document.querySelector(`[data-preview-column="${column}"][data-preview-entry="${kind}"]`);
  await entry('information').click();
  assert.equal(ui.document.querySelector('[role="tab"][aria-controls="field-information"]').getAttribute('aria-selected'),'true');
  assert.match(ui.document.querySelector('.drawer-subtitle').textContent,new RegExp(`${table}.${column}`));
  await ui.cancelRule();await tick();
  assert.equal(Boolean(ui.document.querySelector('.wb-preview-column-actions')),false);
  assert.equal(ui.document.activeElement.getAttribute('data-preview-entry'),'information');
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.length,reads);
  await entry('rule').click();
  assert.equal(ui.document.querySelector('[role="tab"][aria-controls="field-rule"]').getAttribute('aria-selected'),'true');
  await ui.edit(scope==='batch'?'max_length':'max_value','22');await ui.applyRule();await tick();
  assert.equal(ui.modelState().rule(table,column).params[scope==='batch'?'max_length':'max_value'],22);
  assert.equal(ui.document.activeElement.getAttribute('data-preview-entry'),'rule');
  assert.equal(ui.document.activeElement.getAttribute('data-preview-column'),column);
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/runs')),false);
});

test('batch preview opens the shown field editor and cancelling returns to the same table without requests or edits',async()=>{
  const ui=await setup(),before=plain(ui.modelState().document),epoch=ui.modelState().epoch;
  const count=ui.document.querySelector('[aria-label="每表预览行数"]');count.value='7';await count.dispatchEvent('input');await ui.button('重新预览',ui.document).click();
  const requests=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  await openPreviewRule(ui,'event');
  assert.match(ui.document.querySelector('.drawer-subtitle').textContent,/audit.event/);
  await ui.edit('max_length','22');await ui.cancelRule();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'预览已选表');
  assert.equal(ui.button('audit',ui.document.querySelector('.wb-preview-tables')).getAttribute('aria-pressed'),'true');
  assert.equal(ui.document.querySelector('[aria-label="每表预览行数"]').value,'7');
  assert.equal(ui.modelState().view.table,'users');assert.equal(ui.modelState().epoch,epoch);assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,requests);
});

test('applying a preview field rule restores old samples as stale without generating or authorizing execution',async()=>{
  const ui=await setup(),before=plain(ui.modelState().document.tables.map(table=>table.name));
  const requests=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  await openPreviewRule(ui,'event');await ui.edit('max_length','22');await ui.applyRule();await tick();
  assert.equal(ui.modelState().rule('audit','event').params.max_length,22);assert.equal(ui.modelState().check,null);
  assert.deepEqual(plain(ui.modelState().samples),{});assert.deepEqual(plain(ui.modelState().document.tables.map(table=>table.name)),before);
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例.*重新预览/);
  assert.match(ui.document.querySelector('.wb-preview-data').textContent,/old event/);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,requests);
  assert.equal(ui.requests.some(item=>item.url==='/api/workbench/runs'),false);
  await ui.button('重新预览',ui.document).click();
  assert.doesNotMatch(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
});

test('preview AI targets the shown table and column and returns without analyzing automatically',async()=>{
  const ui=await setup();
  await openPreviewAI(ui);
  assert.equal(ui.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'AI 配置助手');
  assert.equal(ui.document.querySelector('[data-ai-column="audit.event"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-column="users.amount"]').checked,false);
  assert.equal(ui.document.querySelector('input[value="columns"]').checked,true);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest')),false);
  await ui.button('取消',ui.document).click();await tick();
  assert.equal(ui.button('audit',ui.document.querySelector('.wb-preview-tables')).getAttribute('aria-pressed'),'true');
  assert.equal(ui.modelState().view.table,'users');
  assert.equal(ui.document.activeElement.getAttribute('data-preview-entry'),'rule');
  assert.equal(ui.document.activeElement.getAttribute('data-preview-column'),'event');
  assert.equal(Boolean(ui.document.querySelector('.wb-preview-column-actions')),false);
});

for(const draft of ['valid','invalid'])test(`preview rule AI preserves an unapplied ${draft} edit and stays unavailable until it is resolved`,async()=>{
  const ui=await setup(),before=plain(ui.modelState().document);
  await openPreviewRule(ui,'event');
  const ai=ui.button('用 AI 调整',ui.document.querySelector('#field-rule'));assert.ok(ai);assert.equal(ai.disabled,false);
  await ui.edit('max_length',draft==='valid'?'22':'not-a-number');
  assert.equal(ai.disabled,true);
  assert.match(ui.document.querySelector('#field-rule').textContent,/先应用或取消/);
  await ai.dispatchEvent('click');await tick();
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'event');
  assert.equal(ui.field('max_length').value,draft==='valid'?'22':'not-a-number');
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest') || item.url.endsWith('/eligibility')),false);
  await ui.cancelRule();await tick();await openPreviewRule(ui,'event');
  assert.equal(ui.button('用 AI 调整',ui.document.querySelector('#field-rule')).disabled,false);
});

test('repeated information and rule visits add no selected-field block to the preview',async()=>{
  const ui=harness();await ui.mount();await ui.button('预览数据').click();
  const blocks=()=>ui.document.querySelector('.wb-table-preview').children.map(node=>node.className);
  const original=blocks(),reads=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  for(const entry of ['information','rule','information','rule']){
    await previewControl(ui,'amount',entry).click();
    assert.equal(Boolean(ui.document.querySelector('[aria-label="所选字段操作"]')),false);
    assert.deepEqual(blocks(),original);
    await ui.cancelRule();await tick();
    assert.deepEqual(blocks(),original);
    assert.equal(ui.document.activeElement.getAttribute('data-preview-entry'),entry);
  }
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,reads);
});

test('leaving during a preview edit cannot reopen the retired preview',async()=>{
  const ui=await setup();await openPreviewRule(ui,'event');
  ui.leave();await ui.mount();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.equal(ui.document.querySelector('.wb-preview-tables'),null);
});

test('inline preview cancels back to the selected column and applies rules without automatically replacing old samples',async()=>{
  const ui=harness();await ui.mount();await ui.button('预览数据').click();
  const requests=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  await previewControl(ui,'amount','information').click();
  assert.match(ui.document.querySelector('#field-information').textContent,/生成规则不会修改表结构/);
  await ui.cancelRule();await tick();
  assert.equal(ui.document.querySelector('[data-preview-column="amount"]').getAttribute('aria-pressed'),'true');
  await openPreviewRule(ui,'amount');await ui.edit('max_value','27');await ui.applyRule();await tick();
  assert.equal(ui.modelState().rule('users','amount').params.max_value,27);
  assert.equal(ui.modelState().selected('users'),false);assert.equal(ui.modelState().view.page,'preview');
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,requests);
  assert.equal(ui.document.activeElement.getAttribute('data-preview-column'),'amount');
});

test('AI review from preview applies only the selected shown field and invalidates returned samples',async()=>{
  const ui=await setup();
  ui.routes.set('/api/workbench/ai/suggest',()=>({schema_hash:'schema-v1',suggestions:[{table:'audit',column:'event',after:{name:'event',generator:'string',params:{max_length:12}},reason:'简洁事件'}]}));
  await openPreviewAI(ui);
  await ui.button('开始分析',ui.document).click();
  const request=JSON.parse(ui.requests.find(item=>item.url.endsWith('/suggest')).options.body);
  assert.deepEqual(request.allowed_targets,[{table:'audit',columns:['event']}]);
  const checkbox=ui.document.querySelector('[data-ai-suggestion="0"]');checkbox.checked=true;await checkbox.dispatchEvent('change');
  await ui.button('应用所选建议',ui.document).click();await tick();
  assert.equal(ui.modelState().rule('audit','event').params.max_length,12);
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
  assert.equal(ui.button('audit',ui.document.querySelector('.wb-preview-tables')).getAttribute('aria-pressed'),'true');
});

test('preview AI preserves protected column rules and keeps DEFAULT eligibility preflight',async()=>{
  const ui=await setup();await ui.button('users',ui.document.querySelector('.wb-preview-tables')).click();
  await openPreviewRule(ui,'id');
  assert.equal(ui.button('用 AI 调整',ui.document).disabled,true);
  await ui.cancelRule();await tick();
  await ui.button('关闭',ui.document).click();
  const m=ui.modelState(),audit=m.schema.tables.find(table=>table.name==='audit');
  audit.columns[0].default="'created'";audit.mapping.event={generator_name:'skip',params:{}};
  m.document.custom_column_mappings={exact:{event:{generator:'string',params:{}}}};m.touch();
  ui.routes.set('/api/workbench/ai/eligibility',()=>({schema_hash:'schema-v1',default_modes:{audit:{event:'string'}}}));
  await ui.button('预览已选表').click();await ui.button('audit',ui.document.querySelector('.wb-preview-tables')).click();
  await openPreviewAI(ui);
  assert.equal(ui.requests.filter(item=>item.url.endsWith('/eligibility')).length,1);
  assert.equal(ui.document.querySelector('[data-ai-column="audit.event"]').checked,true);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest')),false);
  await ui.button('取消',ui.document).click();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'预览已选表');
});

test('first-time AI settings returns to the batch preview with its exact table, column, count and scroll',async()=>{
  const ui=await setup(),m=ui.modelState(),before=plain(m.document),epoch=m.epoch;
  const create=ui.document.createElement;
  ui.document.createElement=tag=>{const node=create(tag);node.scrollWidth=1800;node.scrollHeight=1200;return node;};
  const count=ui.document.querySelector('[aria-label="每表预览行数"]');count.value='7';await count.dispatchEvent('input');await ui.button('重新预览',ui.document).click();
  const scroller=ui.document.querySelector('.wb-preview-scroll'),body=ui.document.querySelector('.wb-modal-body');
  body.scrollWidth=1800;body.scrollHeight=1200;scroller.scrollLeft=240;scroller.scrollTop=90;body.scrollTop=60;
  ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:false,effective:{backend:'ollama',model:''}}));
  const reads=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  await openPreviewAI(ui);await toSettings(ui,'前往设置');
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.deepEqual(plain(ui.handoff.peekAIHandoff('A')),{returnTo:'#/workbench'});
  ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'configured'}}));
  await fromSettings(ui);
  assert.equal(ui.document.querySelector('[data-ai-column="audit.event"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-column="users.amount"]').checked,false);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest')),false);
  await ui.button('取消',ui.document).click();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]')?.getAttribute('aria-label'),'预览已选表');
  assert.equal(ui.button('audit',ui.document.querySelector('.wb-preview-tables')).getAttribute('aria-pressed'),'true');
  assert.equal(ui.document.querySelector('[data-preview-column="event"]').getAttribute('aria-pressed'),'true');
  assert.equal(ui.document.querySelector('[aria-label="每表预览行数"]').value,'7');
  assert.equal(ui.document.querySelector('.wb-preview-scroll').scrollLeft,240);assert.equal(ui.document.querySelector('.wb-preview-scroll').scrollTop,90);
  assert.equal(ui.document.querySelector('.wb-modal-body').scrollTop,60);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,reads);
  assert.equal(m.epoch,epoch);assert.deepEqual(plain(m.document),before);assert.equal(m.view.table,'users');
  assert.equal(ui.document.activeElement.getAttribute('data-preview-column'),'event');
});

test('AI applies after repeated settings trips then returns old batch samples without sending preview rows',async()=>{
  const ui=await setup(),reads=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  ui.routes.set('/api/workbench/ai/suggest',()=>({schema_hash:'schema-v1',suggestions:[{table:'audit',column:'event',after:{name:'event',generator:'string',params:{max_length:17}},reason:'简洁事件'}]}));
  await openPreviewAI(ui);
  await toSettings(ui);await fromSettings(ui);await toSettings(ui);await fromSettings(ui);
  await ui.button('开始分析',ui.document).click();
  const request=JSON.parse(ui.requests.find(item=>item.url.endsWith('/suggest')).options.body);
  assert.deepEqual(request.allowed_targets,[{table:'audit',columns:['event']}]);
  assert.doesNotMatch(JSON.stringify(request),/old event|previewOrigin|previewReturn/);
  const selected=ui.document.querySelector('[data-ai-suggestion="0"]');selected.checked=true;await selected.dispatchEvent('change');
  await ui.button('应用所选建议',ui.document).click();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]')?.getAttribute('aria-label'),'预览已选表');
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
  assert.match(ui.document.querySelector('.wb-preview-data').textContent,/old event/);
  assert.equal(ui.modelState().rule('audit','event').params.max_length,17);
  assert.equal(ui.modelState().check,null);assert.deepEqual(plain(ui.modelState().samples),{});
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,reads);
  assert.equal(ui.requests.some(item=>item.url==='/api/workbench/runs'),false);
  assert.doesNotMatch(JSON.stringify(ui.modelState().document),/old event|previewOrigin|previewReturn/);
});

for(const outcome of ['cancel-stale','apply'])test(`inline preview survives an AI settings trip and ${outcome} without refreshing in the background`,async()=>{
  const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'local-test'}}));
  await ui.mount();await ui.button('预览数据').click();
  if(outcome==='cancel-stale'){
    await openPreviewRule(ui,'amount');await ui.edit('max_value','27');await ui.applyRule();await tick();
  }
  const reads=ui.requests.filter(item=>item.url==='/api/workbench/preview').length;
  await openPreviewAI(ui,'amount');await toSettings(ui);await fromSettings(ui);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,reads);
  if(outcome==='apply'){
    ui.routes.set('/api/workbench/ai/suggest',()=>({schema_hash:'schema-v1',suggestions:[{table:'users',column:'amount',after:{name:'amount',generator:'integer',params:{max_value:19}},reason:'适合当前字段'}]}));
    await ui.button('开始分析',ui.document).click();
    const selected=ui.document.querySelector('[data-ai-suggestion="0"]');selected.checked=true;await selected.dispatchEvent('change');
    await ui.button('应用所选建议',ui.document).click();
  }else await ui.button('取消',ui.document).click();
  await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.equal(ui.modelState().view.page,'preview');assert.equal(ui.modelState().selected('users'),false);
  assert.equal(ui.document.querySelector('[data-preview-column="amount"]').getAttribute('aria-pressed'),'true');
  assert.match(ui.document.querySelector('.wb-preview-status').textContent,/旧样例/);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/preview').length,reads);
  if(outcome==='apply'){
    assert.equal(ui.modelState().rule('users','amount').params.max_value,19);
    assert.equal(ui.modelState().check,null);assert.deepEqual(plain(ui.modelState().samples),{});
  }
});

for(const change of ['epoch','schema','model','lifecycle','connection','target','ordinary-navigation'])test(`AI settings cannot restore a preview after ${change} invalidation`,async()=>{
  const ui=await setup();await openPreviewAI(ui);await toSettings(ui);
  const m=ui.modelState();
  if(change==='epoch')m.touch();
  if(change==='schema')ui.routes.set('/api/workbench/connections/A/schema',()=>({...schema('A'),schema_hash:'changed'}));
  if(change==='model')vm.runInContext('session.model=new WorkbenchSession(session.connId,session.model.schema,send).model',ui.context);
  if(change==='lifecycle')m.lifecycleVersion++;
  if(change==='connection')ui.store.connId='B';
  if(change==='target')ui.routes.set('/api/workbench/connections/A/schema',()=>({...schema('A'),target_key:'changed-target'}));
  const hash=change==='ordinary-navigation'?null:ui.handoff.requestAIReturn(ui.store.connId);
  ui.location.hash=hash || '#/workbench';ui.handoff.leaveAISettings(ui.location.hash);await ui.mount();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);assert.equal(ui.document.querySelector('.wb-preview-tables'),null);
  await ui.button('AI 配置助手').click();await tick();await ui.button('取消',ui.document).click();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
});
