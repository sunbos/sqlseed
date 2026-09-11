const test = require('node:test');
const assert = require('node:assert/strict');
const {harness,plain} = require('./workbench_harness.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const config={available:true,ready:true,effective:{backend:'ollama',model:'local-test'}};
const result={schema_hash:'schema-v1',suggestions:[{table:'users',column:'amount',after:{name:'amount',generator:'integer',params:{min_value:1,max_value:9}},reason:'业务范围'}],rejected:[]};
function stream(){
  let controller;const encoder=new TextEncoder();
  const response=new Response(new ReadableStream({start(value){controller=value;}}),{headers:{'Content-Type':'application/x-ndjson'}});
  return {response,push:event=>controller.enqueue(encoder.encode(JSON.stringify(event)+'\n')),close:()=>{try{controller.close();}catch{}}};
}
async function ready(options){
  const ui=harness(options);ui.routes.set('/api/workbench/ai/config',()=>config);await ui.mount();
  await ui.button('AI 配置助手').click();await tick();return ui;
}
const feedback=ui=>ui.document.querySelector('.wb-ai-progress');
const analyze=ui=>ui.button('开始分析',ui.document);
function clock(){
  let now=0,next=0;const tasks=new Map();
  return {timers:{Date:class extends Date{static now(){return now;}},setTimeout:(fn,ms)=>{const id=++next;tasks.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>tasks.delete(id)},
    advance(ms){const until=now+ms;while(true){const task=[...tasks].filter(([,item])=>item.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!task)break;now=task[1].at;tasks.delete(task[0]);task[1].fn();}now=until;},tasks};
}

test('real streamed stages and elapsed time stay in the footer until review without applying rules',async()=>{
  const time=clock(),ui=await ready({timers:time.timers}),feed=stream(),before=plain(ui.modelState().document);
  ui.routes.set('/api/workbench/ai/suggest',()=>feed.response);
  const pending=analyze(ui).click();await tick();
  feed.push({type:'progress',stage:'model',message:'正在等待三表联合建议'});await tick();
  time.advance(2100);
  const snapshot=feedback(ui)?.textContent,footer=feedback(ui)?.closest('.modal-footer');
  feed.push({type:'result',result});feed.close();await pending;
  assert.ok(footer,'Progress must remain outside the scrolling body');
  assert.match(snapshot,/正在等待三表联合建议/);assert.match(snapshot,/已耗时 2 秒/);assert.doesNotMatch(snapshot,/%/);
  assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.button('应用所选建议',ui.document).disabled,true);
  assert.match(feedback(ui).textContent,/分析完成/);
  assert.equal(ui.requests.find(item=>item.url.endsWith('/suggest')).options.headers.Accept,'application/x-ndjson');
  await ui.button('取消',ui.document).click();assert.equal(time.tasks.size,0);
});

test('candidate validation failure exposes concrete issues and rejected reasons without making suggestions applicable',async()=>{
  const ui=await ready();ui.routes.set('/api/workbench/ai/suggest',()=>({...result,suggestions:[],rejected:['order_no 的值域不足以生成不同值'],validation:{ok:false,message:'候选配置未通过只读检查',issues:[{table:'orders',column:'order_no',message:'生成第 2 行时无法满足 UNIQUE'}]}}));
  await analyze(ui).click();
  const details=ui.document.querySelector('.wb-ai-diagnostics');
  assert.ok(details);assert.equal(details.open,true);assert.match(details.textContent,/orders.*order_no.*第 2 行.*UNIQUE/);assert.match(details.textContent,/值域不足/);
  assert.match(feedback(ui)?.textContent || '',/候选检查未通过/);
  const locate=ui.button('查看问题',feedback(ui));assert.ok(locate);await locate.click();assert.equal(ui.document.activeElement,details);
  assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);
  await ui.button('取消',ui.document).click();
});

test('stream failure keeps its actual phase and re-enables explicit retry',async()=>{
  const ui=await ready(),feed=stream();ui.routes.set('/api/workbench/ai/suggest',()=>feed.response);
  const pending=analyze(ui).click();await tick();feed.push({type:'progress',stage:'preview',message:'正在检查 orders 的只读样例'});feed.push({type:'error',message:'order_no 无法满足 UNIQUE',code:'candidate_failed'});feed.close();await pending;
  assert.match(feedback(ui)?.textContent || '',/只读样例.*失败.*order_no.*UNIQUE/);assert.equal(analyze(ui).disabled,false);
  assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);await ui.button('取消',ui.document).click();
});

test('candidate rejection retains the reported validation stage and scope edits clear its old feedback',async()=>{
  const ui=await ready(),feed=stream();ui.routes.set('/api/workbench/ai/suggest',()=>feed.response);
  const pending=analyze(ui).click();await tick();
  feed.push({type:'progress',stage:'validation',message:'正在检查字段依赖'});
  feed.push({type:'result',result:{...result,suggestions:[],validation:{ok:false,message:'字段依赖存在循环'},rejected:['users.amount：来源存在循环']}});feed.close();await pending;
  assert.match(feedback(ui).textContent,/校验建议规则未通过/);
  const scope=ui.document.querySelector('input[value="selected"]');
  const business=ui.document.querySelector('textarea[aria-label="业务说明"]');business.value='调整数量范围';await business.dispatchEvent('input');
  assert.equal(feedback(ui).hidden,true);assert.equal(ui.document.querySelector('.wb-ai-diagnostics'),null);
  assert.equal(scope.disabled,true,'No selected generation tables were added by AI');await ui.button('取消',ui.document).click();
});

test('a connection removed during model work receives the same reconnection explanation',async()=>{
  const ui=await ready(),feed=stream();ui.routes.set('/api/workbench/ai/suggest',()=>feed.response);
  const pending=analyze(ui).click();await tick();feed.push({type:'progress',stage:'model',message:'等待模型'});
  feed.push({type:'error',code:'not_found',message:'unknown connection: A'});feed.close();await pending;
  assert.match(feedback(ui).textContent,/连接已失效.*重启.*重新连接/);assert.equal(ui.store.connId,'A');await ui.button('取消',ui.document).click();
});

test('unknown connection explains restart and reconnection without selecting a different target',async()=>{
  const ui=await ready(),before=plain(ui.modelState().document);
  ui.routes.set('/api/workbench/ai/suggest',()=>new Response(JSON.stringify({detail:{code:'not_found',message:'unknown connection: A'}}),{status:404,headers:{'Content-Type':'application/json'}}));
  await analyze(ui).click();
  assert.match(feedback(ui)?.textContent || '',/连接已失效.*重启.*重新连接/);assert.equal(ui.store.connId,'A');assert.deepEqual(plain(ui.modelState().document),before);
  assert.equal(ui.requests.some(item=>item.url==='/api/connections'),false);await ui.button('取消',ui.document).click();
});

for(const destination of ['close','edit','leave-remount'])test(`late stream events cannot affect ${destination}`,async()=>{
  const ui=await ready(),feed=stream();let signal;
  ui.routes.set('/api/workbench/ai/suggest',options=>{signal=options.signal;return feed.response;});
  const pending=analyze(ui).click();await tick();await analyze(ui).click();
  assert.equal(ui.requests.filter(item=>item.url.endsWith('/suggest')).length,1);
  if(destination==='close')await ui.button('取消',ui.document).click();
  else if(destination==='edit')ui.modelState().setCount('users','7');
  else {ui.leave();await ui.mount();}
  const before=plain(ui.modelState().payload('current'));
  try{feed.push({type:'progress',stage:'preview',message:'stale-progress'});feed.push({type:'result',result});}catch{}
  feed.close();await pending;
  assert.deepEqual(plain(ui.modelState().payload('current')),before);assert.doesNotMatch(ui.document.textContent,/stale-progress/);assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);
  if(destination!=='edit')assert.equal(signal.aborted,true);
  ui.document.querySelector('[role="dialog"]')?.querySelector('button[aria-label="关闭"]')?.click();
});

test('the whole operation times out at 180 seconds and old stream completion cannot replace a retry',async()=>{
  const time=clock(),ui=await ready({timers:time.timers}),feed=stream();let signal;
  ui.routes.set('/api/workbench/ai/suggest',options=>{signal=options.signal;return feed.response;});
  const pending=analyze(ui).click();await tick();
  feed.push({type:'progress',stage:'preview',message:'正在检查只读样例'});await tick();
  time.advance(179999);const stillBusy=analyze(ui).disabled;
  time.advance(1);const expired=feedback(ui)?.textContent;
  ui.routes.set('/api/workbench/ai/suggest',()=>({...result,suggestions:[]}));await analyze(ui).click();
  try{feed.push({type:'result',result});}catch{}feed.close();await pending;
  assert.equal(stillBusy,true);assert.equal(signal.aborted,true);assert.match(expired,/只读样例.*超时/);assert.match(expired,/180 秒/);
  assert.equal(ui.document.querySelector('[data-ai-suggestion]'),null);assert.doesNotMatch(feedback(ui).textContent,/超时/);
  await ui.button('取消',ui.document).click();assert.equal(time.tasks.size,0);
});
