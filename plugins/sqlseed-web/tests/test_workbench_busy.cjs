const test=require('node:test');
const assert=require('node:assert/strict');
const {harness,deferred}=require('./workbench_harness.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const leavePreview=async(ui,page='字段规则')=>{
  assert.ok(ui.root().querySelector('.wb-table-preview'),'Preview is embedded in the current table');
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  await ui.button(page).click();assert.equal(ui.root().querySelector('.wb-table-preview'),null);
};
const generatePreview=ui=>ui.button('生成预览',ui.root().querySelector('.wb-table-preview')) || ui.button('重新预览',ui.root().querySelector('.wb-table-preview'));

test('remount joins an existing schema refresh and keeps the returned schema',async()=>{
  const ui=harness();await ui.mount();const gate=deferred();
  const {schema}=require('./workbench_harness.cjs');
  ui.routes.set('/api/workbench/connections/A/schema',()=>gate.promise);
  const refreshing=ui.button('重新读取结构').click();await tick();
  ui.leave();const mounting=ui.mount();await tick();
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/connections/A/schema')).length,2,'Initial read plus one shared refresh');
  const next=schema();next.schema_hash='changed-schema';next.tables[0].row_count=123;
  gate.resolve(next);await Promise.all([refreshing,mounting]);
  assert.equal(ui.modelState().schema.schema_hash,'changed-schema');
  assert.equal(ui.modelState().schema.tables[0].row_count,123);
  assert.equal(ui.button('重新读取结构').disabled,false);
});

test('remount during a preview keeps the editable session without queueing a schema read',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState(),gate=deferred();
  m.setColumn('users','amount',{generator:'integer',params:{min_value:4,max_value:9}});
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();ui.leave();await ui.mount();
  assert.equal(ui.modelState(),m);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/connections/A/schema')).length,1);
  assert.equal(ui.button('预览数据').disabled,false,'Viewing a tab does not acquire the database gate');
  assert.equal(generatePreview(ui).disabled,true);
  await leavePreview(ui);
  await ui.selectColumn('amount');assert.ok(ui.document.querySelector('#field-information'));await ui.cancelRule();
  gate.resolve({ok:true,samples:{users:[{amount:7}]},issues:[]});await pending;
  assert.equal(ui.button('预览数据').disabled,false);
});

test('newly opened inspector checks share the active preview guard and recover afterward',async()=>{
  const ui=harness();await ui.mount();ui.modelState().toggleTable('users',true);
  await ui.button('users 的依赖路径').click();
  const gate=deferred();ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  await leavePreview(ui,'关系图');
  await ui.button('依赖检查',ui.root().querySelector('.wb-inspector')).click();
  const local=ui.button('开始检查');assert.equal(local.disabled,true);
  await local.click();assert.equal(ui.requests.filter(r=>r.url.endsWith('/check')).length,0);
  gate.resolve({ok:true,samples:{users:[{amount:7}]},issues:[]});await pending;
  const ready=ui.button('开始检查');assert.equal(ready.disabled,false);await ready.click();
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/check')).length,1);
});

test('parent inclusion and entire-plan checks cannot bypass an in-flight preview',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('orders',true);
  m.acceptCheck({ok:false,config_hash:'checked',order:['orders'],layers:[['orders']],issues:[{code:'missing_parent_source',severity:'error',table:'orders',source_table:'users',message:'缺少users来源'}]},m.epoch,false);
  await ui.button('orders 的依赖路径').click();await ui.button('依赖检查',ui.root().querySelector('.wb-inspector')).click();
  const gate=deferred();ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  await leavePreview(ui,'关系图');
  const include=ui.root().querySelectorAll('button').find(b=>b.textContent.startsWith('加入 users（'));
  const entire=ui.button('整个计划 ↗');assert.equal(include.disabled,true);assert.equal(entire.disabled,true);
  await Promise.all([include.click(),entire.click()]);assert.equal(m.selected('users'),false);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/check')).length,0);
  gate.resolve({ok:true,samples:{orders:[]},issues:[]});await pending;
});

test('connection-busy schema reads preserve an existing editable session with an honest cache notice',async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.setColumn('users','amount',{generator:'integer',params:{min_value:4,max_value:9}});
  const epoch=m.epoch;ui.leave();
  ui.routes.set('/api/workbench/connections/A/schema',()=>{const error=new Error('当前连接有任务正在运行');error.status=409;error.detail={code:'connection_busy'};throw error;});
  await ui.mount();assert.equal(ui.modelState(),m);assert.equal(m.epoch,epoch);
  assert.ok(ui.button('预览数据'));assert.match(ui.root().textContent,/缓存|上次读取/);assert.match(ui.root().textContent,/忙|任务正在运行/);
  await ui.selectColumn('amount');assert.ok(ui.document.querySelector('#field-information'));await ui.cancelRule();
  const next=require('./workbench_harness.cjs').schema();next.tables[0].row_count=42;
  ui.routes.set('/api/workbench/connections/A/schema',()=>next);
  await ui.button('重新读取结构').click();
  assert.equal(m.schema.tables[0].row_count,42);
  assert.equal(ui.root().querySelector('.wb-operation-status').hidden,true);
});

for(const [status,code] of [[404,'not_found'],[500,'request_failed'],[409,'schema_changed']]) {
  test(`cached sessions never hide schema errors ${status}/${code}`,async()=>{
    const ui=harness();await ui.mount();ui.leave();
    ui.routes.set('/api/workbench/connections/A/schema',()=>{const error=new Error('specific schema error');error.status=status;error.detail={code};throw error;});
    await ui.mount();assert.match(ui.root().textContent,/无法打开工作台/);assert.match(ui.root().textContent,/specific schema error/);
  });
}

test('connection-busy without an existing schema still reports the loading failure',async()=>{
  const ui=harness();ui.routes.set('/api/workbench/connections/A/schema',()=>{const error=new Error('busy without cache');error.status=409;error.detail={code:'connection_busy'};throw error;});
  await ui.mount();assert.match(ui.root().textContent,/无法打开工作台/);assert.match(ui.root().textContent,/busy without cache/);
});

test('rapid preview and other database actions share one in-flight operation',async()=>{
  const ui=harness();await ui.mount();const gate=deferred();
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const check=ui.button('依赖检查');
  const first=ui.button('预览数据').click();await tick();
  const preview=generatePreview(ui);
  assert.equal(ui.button('预览数据').disabled,false);
  assert.equal(preview.disabled,true);assert.equal(check.disabled,true);
  assert.match(ui.root().querySelector('.wb-operation-status').textContent,/样例|预览/);
  await Promise.all([preview.click(),check.click(),ui.button('保存配置').click()]);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/preview')).length,1);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/check')).length,0);
  gate.resolve({ok:true,samples:{users:[{amount:8}]},issues:[]});await first;
  await tick();
  assert.equal(preview.disabled,false);assert.equal(check.disabled,false);
  await preview.click();
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/preview')).length,2,'A completed operation can be deliberately repeated');
});

test('returning to a completed table preview reuses its cache until explicitly refreshed',async()=>{
  const ui=harness();await ui.mount();const model=ui.modelState();
  await ui.button('预览数据').click();
  const previewRequests=()=>ui.requests.filter(request=>request.url.endsWith('/preview'));
  assert.equal(previewRequests().length,1);
  assert.equal(JSON.parse(previewRequests()[0].options.body).count,10);
  assert.equal(model.selected('users'),false,'A local preview never selects the table for writing');
  await leavePreview(ui);await ui.button('预览数据').click();
  assert.equal(previewRequests().length,1,'Reopening cached results does not access the database');
  assert.match(ui.root().querySelector('.wb-preview-results').textContent,/users.*实际展示 1 行/);
  assert.equal(ui.root().querySelector('.wb-preview-data').querySelectorAll('tbody')[0].querySelectorAll('tr').length,1);
  await generatePreview(ui).click();
  assert.equal(previewRequests().length,2);
});

test('reentering a pending preview tab does not duplicate work or strand its final result',async()=>{
  const ui=harness();await ui.mount();const gate=deferred();
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  await leavePreview(ui);await ui.button('预览数据').click();
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
  assert.equal(ui.button('预览数据').disabled,false);
  assert.equal(generatePreview(ui).disabled,true);
  gate.resolve({ok:true,samples:{users:[{amount:47}]},issues:[]});await pending;await tick();
  assert.equal(generatePreview(ui).disabled,false);
  assert.match(ui.root().querySelector('.wb-preview-results').textContent,/47/,'The active pane must receive the same current response');
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
});

test('remounting the current preview during its request publishes the accepted result without another request',async()=>{
  const ui=harness();await ui.mount();const model=ui.modelState(),gate=deferred();
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  ui.leave();await ui.mount();
  assert.equal(ui.modelState(),model);
  assert.equal(model.view.page,'preview');
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
  gate.resolve({ok:true,samples:{users:[{amount:48}]},issues:[]});await pending;await tick();
  assert.match(ui.root().querySelector('.wb-preview-results').textContent,/48/);
  assert.equal(generatePreview(ui).disabled,false);
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/connections/A/schema')).length,1);
});

test('reentered preview options stay disabled until the pending request releases their meaning',async()=>{
  const ui=harness();await ui.mount();const gate=deferred();
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  await leavePreview(ui);await ui.button('预览数据').click();
  const count=ui.root().querySelector('[aria-label="每表预览行数"]');
  assert.equal(count.disabled,true,'A recreated preview must not offer editable options for an older in-flight request');
  assert.equal(ui.button('预览数据').disabled,false,'View navigation stays accessible');
  gate.resolve({ok:true,samples:{users:[{amount:49}]},issues:[]});await pending;await tick();
  const ready=ui.root().querySelector('[aria-label="每表预览行数"]');
  assert.equal(ready.disabled,false);
  ready.value='0';await ready.dispatchEvent('input');
  assert.equal(ready.value,'0');
  assert.match(ui.root().querySelector('.wb-preview-error').textContent,/1–100/);
  assert.equal(ui.root().querySelector('.wb-preview-results').textContent,'');
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
});

test('a selected-table preview modal keeps its fixed scope and shares the same database gate',async()=>{
  const ui=harness();await ui.mount();
  for(const name of ['users','orders']){
    const checkbox=ui.root().querySelector(`[data-table="${name}"]`).querySelector('input');
    checkbox.checked=true;await checkbox.dispatchEvent('change');
  }
  const gate=deferred();ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览已选表').click();await tick();
  const dialog=ui.document.querySelector('[role="dialog"]');assert.ok(dialog);
  assert.equal(dialog.getAttribute('aria-label'),'预览已选表');
  assert.equal(dialog.querySelector('[aria-label="预览范围"]'),null,'Batch scope is fixed instead of introducing another scope chooser');
  assert.equal(ui.button('重新预览',dialog).disabled,true);
  assert.equal(ui.button('预览已选表').disabled,true);
  await ui.button('关闭',dialog).click();
  await ui.button('预览数据').click();
  assert.equal(ui.requests.filter(request=>request.url.endsWith('/preview')).length,1);
  const payload=JSON.parse(ui.requests.find(request=>request.url.endsWith('/preview')).options.body);
  assert.deepEqual(payload.document.tables.map(table=>table.name),['users','orders']);
  gate.resolve({ok:true,samples:{users:[{amount:5}],orders:[]},issues:[]});await pending;
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.equal(ui.modelState().view.page,'preview');
  assert.equal(ui.button('预览已选表').disabled,false);
  assert.match(ui.root().querySelector('.wb-preview-results').textContent,/5/,'An accepted batch result also reaches an already-open matching table preview');
});

test('leaving the preview tab permits navigation while its pending request still guards database actions',async()=>{
  const ui=harness();await ui.mount();const gate=deferred();
  ui.routes.set('/api/workbench/preview',()=>gate.promise);
  const pending=ui.button('预览数据').click();await tick();
  await leavePreview(ui);
  await ui.root().querySelector('[data-table="audit"]').querySelector('.table-button').click();
  assert.equal(ui.modelState().view.table,'audit');
  assert.equal(ui.button('预览数据').disabled,false);
  assert.equal(ui.button('依赖检查').disabled,true);
  gate.resolve({ok:true,samples:{users:[{amount:7}]},issues:[]});await pending;
  assert.equal(ui.button('预览数据').disabled,false);
  assert.equal(ui.modelState().view.table,'audit');
});

test('failed operation restores controls and exposes actionable error beside the actions',async()=>{
  const ui=harness();await ui.mount();
  ui.routes.set('/api/workbench/preview',()=>{throw new Error('数据库正在生成数据，请完成后重试');});
  await ui.button('预览数据').click();
  assert.equal(ui.button('预览数据').disabled,false);
  const status=ui.root().querySelector('.wb-operation-status');
  assert.equal(status.hidden,false);assert.match(status.textContent,/正在生成数据/);
});

test('repeated mounting reuses one pending schema read rather than queueing duplicate reads',async()=>{
  const ui=harness();const gate=deferred();
  const {schema}=require('./workbench_harness.cjs');
  ui.routes.set('/api/workbench/connections/A/schema',()=>gate.promise);
  const first=ui.mount();await tick();ui.leave();const second=ui.mount();await tick();
  assert.equal(ui.requests.filter(r=>r.url==='/api/workbench/connections/A/schema').length,1);
  gate.resolve(schema());await Promise.all([first,second]);
  assert.ok(ui.button('预览数据'));
});

test('document parse and export buttons cannot send overlapping work',async()=>{
  const ui=harness();await ui.mount();await ui.button('编辑 YAML').click();const gate=deferred();
  ui.routes.set('/api/workbench/parse',()=>gate.promise);
  const first=ui.button('下载配置',ui.document).click();await tick();
  assert.equal(ui.button('下载配置',ui.document).disabled,true);
  assert.equal(ui.button('应用配置',ui.document).disabled,true);
  await Promise.all([ui.button('下载配置',ui.document).click(),ui.button('应用配置',ui.document).click()]);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/parse')).length,1);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/export')).length,1,'The opening export is complete; none can overlap pending parsing');
  gate.resolve({document:{provider:'base',tables:[]}});await first;
  assert.equal(ui.button('应用配置',ui.document).disabled,false);
  assert.equal(ui.requests.filter(r=>r.url.endsWith('/export')).length,2);
});

test('database generated fields explain their ownership instead of offering AI editing',async()=>{
  const ui=harness();await ui.mount();await ui.selectColumn('id');
  const panel=ui.document.querySelector('#field-information');
  assert.match(panel.textContent,/由数据库自动分配/);
  assert.equal(ui.button('AI 优化此字段',panel),undefined);
  await ui.cancelRule();await ui.selectColumn('amount');
  assert.equal(ui.button('AI 优化此字段',ui.document.querySelector('#field-information')),undefined);
  assert.ok(ui.button('AI 配置助手'));
});
