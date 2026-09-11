const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain,schema}=require('./workbench_harness.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const config={available:true,ready:true,effective:{backend:'ollama',model:'local-test',base_url:'http://user:secret@localhost:11434/v1?api_key=secret',api_key:'never-show'}};
async function setup({draft=false}={}){
  const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>config);
  ui.routes.set('/api/workbench/ai/suggest',()=>({schema_hash:'schema-v1',suggestions:[{table:'users',column:'amount',after:{name:'amount',generator:'integer',params:{min_value:1,max_value:5}}}],rejected:[]}));
  if(draft){
    ui.location.hash='#/workbench?draft=original';
    ui.routes.set('/api/workbench/drafts/original',()=>({id:'original',name:'Original',revision:1,target_key:'target-A',schema_hash:'schema-v1',document:{provider:'base',locale:'en_US',tables:[{name:'users',count:10,columns:[]}]}}));
  }
  await ui.mount();await ui.button('AI 配置助手').click();await tick();return ui;
}
async function transfer(ui){
  const settings=ui.button('更改设置',ui.document);assert.ok(settings,'assistant must link to the independent settings page');
  await settings.click();assert.equal(ui.location.hash,'#/settings?section=ai');ui.leave();
}
async function returnFromSettings(ui){
  const hash=ui.handoff.requestAIReturn(ui.store.connId);assert.ok(hash);
  ui.location.hash=hash;ui.handoff.leaveAISettings(hash);await ui.mount();await tick();
}

test('assistant only displays a credential-free service summary and settings link',async()=>{
  const ui=await setup();
  assert.ok(ui.button('更改设置',ui.document));
  assert.match(ui.document.querySelector('[aria-label="AI 服务摘要"]').textContent,/Ollama.*local-test/);
  assert.equal(ui.document.querySelector('input[type="password"]'),null);
  assert.equal(ui.document.querySelector('[aria-label="模型名称"]'),null);
  assert.equal(ui.document.querySelector('[aria-label="AI 服务地址"]'),null);
  assert.doesNotMatch(ui.document.textContent,/never-show|secret|user:|api_key/);
  assert.equal(ui.button('开始分析',ui.document).disabled,false);ui.leave();
});

test('settings return restores field scope and business context once without reopening a saved draft or old review',async()=>{
  const ui=await setup({draft:true}),model=ui.modelState();
  const radio=ui.document.querySelector('input[value="columns"]');radio.checked=true;await radio.dispatchEvent('change');
  const metadata=ui.document.querySelector('[data-ai-column="users.metadata"]');metadata.checked=false;await metadata.dispatchEvent('change');
  const audit=ui.document.querySelector('[data-ai-column="audit.event"]');audit.checked=true;await audit.dispatchEvent('change');
  const business=ui.document.querySelector('[aria-label="业务说明"]');business.value='订单按工作日完成（仅内存）';await business.dispatchEvent('input');
  await ui.button('开始分析',ui.document).click();assert.ok(ui.document.querySelector('[data-ai-suggestion]'));
  const before=plain(model.document),draftReads=ui.requests.filter(item=>item.url==='/api/workbench/drafts/original').length;
  await transfer(ui);assert.deepEqual(plain(ui.handoff.peekAIHandoff('A')),{returnTo:'#/workbench?draft=original'});
  assert.doesNotMatch(ui.location.hash,/订单|business|columns/);
  ui.routes.set('/api/workbench/ai/config',()=>({...config,effective:{backend:'ollama',model:'updated-model'}}));
  await returnFromSettings(ui);
  assert.match(ui.document.querySelector('[aria-label="AI 服务摘要"]').textContent,/updated-model/);
  assert.equal(ui.modelState(),model);assert.deepEqual(plain(model.document),before);
  assert.equal(ui.requests.filter(item=>item.url==='/api/workbench/drafts/original').length,draftReads);
  assert.equal(ui.document.querySelector('input[value="columns"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-column="users.amount"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-column="users.metadata"]').checked,false);
  assert.equal(ui.document.querySelector('[data-ai-column="audit.event"]').checked,true);
  assert.equal(ui.document.querySelector('[aria-label="业务说明"]').value,'订单按工作日完成（仅内存）');
  assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);
  assert.equal(ui.requests.filter(item=>item.url.endsWith('/suggest')).length,1);
  assert.equal(ui.handoff.peekAIHandoff('A'),null);ui.leave();
});

test('table scope preserves exact selected tables across settings',async()=>{
  const ui=await setup(),radio=ui.document.querySelector('input[value="tables"]');radio.checked=true;await radio.dispatchEvent('change');
  const audit=ui.document.querySelector('[data-ai-table="audit"]');audit.checked=true;await audit.dispatchEvent('change');
  await transfer(ui);await returnFromSettings(ui);
  assert.equal(ui.document.querySelector('input[value="tables"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-table="audit"]').checked,true);
  assert.equal(ui.document.querySelector('[data-ai-table="users"]').checked,false);ui.leave();
});

for(const change of ['epoch','schema','model','deleted','connection'])test(`settings handoff rejects a stale ${change}`,async()=>{
  const ui=await setup();if(change==='deleted')ui.modelState().saved={id:'deleted-draft'};
  await transfer(ui);const m=ui.modelState();
  if(change==='epoch')m.touch();
  if(change==='schema')ui.routes.set('/api/workbench/connections/A/schema',()=>({...schema('A'),schema_hash:'schema-v2'}));
  if(change==='model')vm.runInContext('session.model=new WorkbenchSession(session.connId,session.model.schema,send).model',ui.context);
  if(change==='deleted')await ui.context.window.dispatchEvent({type:'sqlseed:draft-deleted',detail:{id:'deleted-draft'}});
  if(change==='connection')ui.store.connId='B';
  const hash=ui.handoff.requestAIReturn(ui.store.connId);
  ui.location.hash=hash || '#/workbench';ui.handoff.leaveAISettings(ui.location.hash);await ui.mount();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  assert.equal(ui.requests.some(item=>item.url.endsWith('/suggest')),false);ui.leave();
});

test('ordinary navigation or closing the assistant cannot implicitly restore it',async()=>{
  const ui=await setup();await transfer(ui);
  ui.location.hash='#/workbench';ui.handoff.leaveAISettings(ui.location.hash);await ui.mount();await tick();
  assert.equal(ui.document.querySelector('[role="dialog"]'),null);
  await ui.button('AI 配置助手').click();await tick();await ui.button('取消',ui.document).click();
  ui.leave();await ui.mount();await tick();assert.equal(ui.document.querySelector('[role="dialog"]'),null);ui.leave();
});
