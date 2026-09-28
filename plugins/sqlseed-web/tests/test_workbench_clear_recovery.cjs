const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {harness,plain,deferred,schema}=require('./workbench_harness.cjs');
const {loadFrontend}=require('./frontend_helpers.cjs');
const fixture=require('./complex_business_graph.json');
const helper=loadFrontend('workbench/clear-recovery.js');
const candidate=vm.runInContext('clearScopeCandidate',helper);
const recoveryState=vm.runInContext('clearRecoveryState',helper);
const Model=vm.runInContext('WorkbenchDocument',loadFrontend('workbench/model.js'));
const five=['sales_orders','order_items','payments','shipments','shipment_items'];
const eight=[...five,'addresses','customers','employees'];
const graphSchema=()=>({...schema(),...structuredClone(fixture),tables:fixture.tables.map(table=>({
 ...structuredClone(table),primary_key:[],unique_constraints:[],checks:[],foreign_keys:[],mapping:{},
 columns:table.columns.map(column=>({...column,nullable:true,default:null}))
}))});
const passed=document=>({ok:true,config_hash:'rules',order:document.tables.map(table=>table.name),issues:[],samples:{}});
const plans=ui=>ui.requests.filter(request=>request.url.endsWith('/execution-plan'));
const writes=ui=>ui.requests.filter(request=>request.url==='/api/workbench/runs');
const mutations=ui=>ui.requests.filter(request=>request.options.method==='PUT'||request.url==='/api/workbench/drafts'||request.url==='/api/workbench/runs');
const close=ui=>ui.document.dispatchEvent({type:'keydown',key:'Escape'});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const mode=async ui=>{const input=ui.document.querySelector('[aria-label="清空所选表后生成"]');input.checked=true;await input.dispatchEvent('change');};
const appendMode=async ui=>{const input=ui.document.querySelector('[aria-label="追加数据"]');input.checked=true;await input.dispatchEvent('change');};
const review=ui=>ui.button('补齐关联表，继续重建',ui.document.querySelector('.wb-execution-plan') || ui.root().querySelector('.wb-clear-recovery')).click();
const confirmation=ui=>ui.button('确认范围，查看清空计划',ui.document);
const saveScope=ui=>ui.routes.set('/api/workbench/drafts/saved',options=>({...JSON.parse(options.body),id:'saved',revision:2,target_key:'target-A'}));

test('clear recovery keeps case, numeric suffixes and Unicode names in deterministic UTF-16 order',()=>{
 const names=['表','a2','😀','Z','a10','z','á','Ä','𐀀'];
 const expected=['Z','a10','a2','z','Ä','á','表','𐀀','😀'];
 const data={...schema(),tables:['root',...names].map(name=>({...schema().tables[0],name})),edges:names.map(target=>({source:'root',target}))};
 const m=new Model(data,{provider:'base',locale:'en_US',tables:[{name:'root',count:7,columns:[]}]});
 const before=plain(m.document),result=candidate(m);
 assert.deepEqual(plain(result.added.map(table=>table.name)),expected);
 assert.deepEqual(plain(result.document.tables.map(table=>table.name)),['root',...expected]);
 const state=recoveryState(m,{epoch:m.epoch,lifecycle:m.lifecycleVersion,state:'blocked',issues:[...names,'a2'].map(table=>({table,code:'external_incoming_fk',severity:'error'}))});
 assert.deepEqual(plain(state.externalTables),expected);
 assert.equal(state.count,names.length);
 assert.deepEqual(plain(m.document),before);
});

async function ready(names=five) {
 const ui=harness(),data=graphSchema();ui.routes.set('/api/workbench/connections/A/schema',()=>data);
 ui.routes.set('/api/workbench/check',options=>passed(JSON.parse(options.body).document));
 await ui.mount();for(const name of names)ui.modelState().toggleTable(name,true);
 await ui.button('查看生成计划').click();
 const selected=new Set(names),issues=data.edges.filter(edge=>selected.has(edge.source)&&!selected.has(edge.target)).map(edge=>({
  code:'external_incoming_fk',severity:'error',table:edge.target,message:`${edge.target} 引用了所选范围`
 }));
 ui.routes.set('/api/workbench/execution-plan',()=>({ok:false,atomic:true,clear_tables:names.map(name=>({name,row_count:1})),issues,reset_identity_supported:false,plan_hash:'blocked'}));
 await mode(ui);return ui;
}

test('real business schema closes downstream scope 5→9 and 8→23 without adding unselected ancestors or mutating rules',()=>{
 for(const [selected,size] of [[five,9],[eight,23]]) {
  const m=new Model(graphSchema(),{provider:'base',locale:'en_US',tables:selected.map(name=>({name,count:100,columns:[]}))});
  m.view.tableDrafts.refunds={name:'refunds',count:37,columns:[{name:'amount',generator:'integer',params:{min_value:4}}]};
  const before=plain(m.payload('original')),result=candidate(m);
  assert.equal(result.total,size);assert.equal(result.added.length,size-selected.length);
  assert.equal(result.document.tables.find(table=>table.name==='refunds').count,37);
  assert.deepEqual(plain(m.payload('original')),before);
  if(size===9)assert.equal(result.document.tables.some(table=>['addresses','customers','employees'].includes(table.name)),false);
  else assert.ok(result.document.tables.some(table=>table.name==='departments'));
 }
});

test('confirmation leads with rebuilding scope, counts external tables once and keeps append under an explicit alternative',async()=>{
 const ui=await ready(eight),planArea=ui.document.querySelector('.wb-execution-plan');
 const modal=planArea.closest('.modal');assert.equal(modal.querySelector('.modal-body').firstChild,planArea);
 assert.match(planArea.querySelector('.wb-clear-recovery-status').textContent,/生成规则已通过；清空需处理 9 项/);
 assert.equal(planArea.querySelector('.wb-clear-recovery-tables').querySelectorAll('li').length,9);
 const primary=ui.button('补齐关联表，继续重建',planArea);
 assert.ok(primary.classList.contains('primary'));assert.equal(primary.closest('details'),null);
 const append=ui.button('改为追加，保留现有数据',planArea),alternatives=append.closest('details');
 assert.ok(alternatives);assert.equal(Boolean(alternatives.open),false);
 assert.match(alternatives.querySelector('summary').textContent,/其他处理方式/);
 alternatives.open=true;await append.click();
 assert.equal(ui.document.querySelector('[aria-label="追加数据"]').checked,true);
 assert.equal(ui.document.querySelector('[aria-label="清空所选表后生成"]').checked,false);
 assert.match(planArea.textContent,/不清空表/);assert.equal(writes(ui).length,0);
 await close(ui);assert.equal(ui.root().querySelector('.wb-clear-recovery'),null);
});

test('8→23 candidate displays a real cyclic-check failure and cannot change the current eight-table configuration',async()=>{
 const ui=await ready(eight),before=plain(ui.modelState().document),currentCheck=ui.modelState().check;
 const mutationCount=mutations(ui).length;
 ui.routes.set('/api/workbench/check',()=>({ok:false,issues:fixture.checks.cycles.issues}));
 await review(ui);
 const dialog=ui.document.querySelector('.modal');assert.match(dialog.textContent,/8 张 → 23 张：新增 15 张表/);
 assert.match(dialog.textContent,/employees/);assert.match(dialog.textContent,/departments/);
 assert.match(dialog.textContent,/暂时不能继续清空重建/);
 assert.ok(ui.button('定位 employees',dialog));assert.ok(ui.button('定位 departments',dialog));
 const apply=confirmation(ui);assert.equal(apply.disabled,true);await apply.click();
 assert.deepEqual(plain(ui.modelState().document),before);assert.equal(ui.modelState().check,currentCheck);
 assert.equal(mutations(ui).length,mutationCount);assert.equal(writes(ui).length,0);
});

test('confirming a passing 5→9 review saves the explicit scope and continues to a fresh clear plan without running',async()=>{
 const ui=await ready(),beforeCheck=ui.modelState().check,mutationCount=mutations(ui).length;
 await review(ui);
 const dialog=ui.document.querySelector('.modal');assert.match(dialog.textContent,/5 张 → 9 张：新增 4 张表/);
 assert.match(dialog.textContent,/现有行数（上次读取）/);
 assert.equal(ui.modelState().check,beforeCheck);assert.equal(ui.modelState().document.tables.length,5);
 assert.equal(mutations(ui).length,mutationCount);assert.equal(plans(ui).length,1);assert.equal(writes(ui).length,0);
 saveScope(ui);
 ui.routes.set('/api/workbench/execution-plan',()=>({ok:true,atomic:true,issues:[],clear_tables:[],reset_identity_supported:false,plan_hash:'reviewed-scope'}));
 const apply=confirmation(ui);assert.equal(apply.disabled,false,'Candidate readiness survives releasing the shared busy gate');
 const beforeRequests=ui.requests.length;await apply.click();
 assert.equal(ui.modelState().document.tables.length,9);assert.equal(ui.modelState().check.ok,true);assert.equal(ui.modelState().dirty,false);
 assert.deepEqual(ui.requests.slice(beforeRequests).map(request=>request.url),['/api/workbench/drafts/saved','/api/workbench/check','/api/workbench/execution-plan']);
 const saved=JSON.parse(ui.requests.slice(beforeRequests)[0].options.body);
 assert.equal(saved.document.tables.length,9);assert.equal(saved.document.execution,undefined);
 assert.equal(plans(ui).length,2);assert.equal(JSON.parse(plans(ui)[1].options.body).revision,2);
 assert.deepEqual(JSON.parse(plans(ui)[1].options.body).execution,{mode:'replace_selected',reset_identity:false});
 assert.equal(ui.button('清空并生成',ui.document).disabled,false);assert.equal(writes(ui).length,0);
});

test('cancelled candidate results cannot apply or replace the current model check',async()=>{
 const ui=await ready(),gate=deferred(),before=plain(ui.modelState().document),check=ui.modelState().check;
 ui.routes.set('/api/workbench/check',()=>gate.promise);
 const pending=review(ui);await tick();
 const apply=confirmation(ui);await ui.button('取消',ui.document).click();
 gate.resolve(passed({tables:[]}));await pending;await apply.click();
 assert.equal(ui.document.querySelector('.modal'),null);assert.equal(apply.disabled,true);
 assert.deepEqual(plain(ui.modelState().document),before);assert.equal(ui.modelState().check,check);assert.equal(writes(ui).length,0);
});

test('unknown downstream targets block candidate checks and trigger-only failures do not suggest adding tables',async()=>{
 const ui=await ready();await close(ui);
 ui.modelState().schema.edges.push({source:'sales_orders',target:'missing_table'});
 const checks=ui.requests.filter(request=>request.url.endsWith('/check')).length;
 await review(ui);
 assert.match(ui.document.querySelector('.modal').textContent,/无法定位关联表 missing_table/);
 assert.equal(confirmation(ui).disabled,true);
 assert.equal(ui.requests.filter(request=>request.url.endsWith('/check')).length,checks);await close(ui);
 const trigger=await ready();await appendMode(trigger);
 trigger.routes.set('/api/workbench/execution-plan',()=>({ok:false,atomic:true,issues:[{code:'replacement_trigger_not_supported',table:'sales_orders',severity:'error',message:'sales_orders 存在触发器，请使用追加。'}],clear_tables:[]}));
 await mode(trigger);
 const area=trigger.document.querySelector('.wb-execution-plan');assert.match(area.textContent,/触发器/);
 assert.equal(trigger.button('补齐关联表，继续重建',area),undefined);assert.ok(trigger.button('查看 sales_orders',area));
});

test('a failed execution-plan request has an inline retry and never grants write permission',async()=>{
 const ui=await ready();await appendMode(ui);let calls=0;
 ui.routes.set('/api/workbench/execution-plan',()=>{if(++calls===1)throw new Error('connection lost');return {ok:true,atomic:true,issues:[],clear_tables:[],plan_hash:'retried'};});
 await mode(ui);
 const area=ui.document.querySelector('.wb-execution-plan');assert.match(area.textContent,/connection lost/);
 assert.equal(ui.button('清空并生成',ui.document).disabled,true);
 await ui.button('重新检查清空计划',area).click();
 assert.equal(calls,2);assert.equal(ui.button('清空并生成',ui.document).disabled,false);assert.equal(writes(ui).length,0);
});

test('confirmed scope uses one shared save/check/plan action even after repeated clicks',async()=>{
 const ui=await ready(),gate=deferred();await review(ui);
 ui.routes.set('/api/workbench/drafts/saved',async options=>{await gate.promise;return {...JSON.parse(options.body),id:'saved',revision:2,target_key:'target-A'};});
 ui.routes.set('/api/workbench/execution-plan',()=>({ok:true,atomic:true,issues:[],clear_tables:[],plan_hash:'new-scope'}));
 const apply=confirmation(ui),before=ui.requests.length;
 const pending=apply.click();await tick();
 assert.equal(ui.modelState().document.tables.length,9);
 await apply.dispatchEvent('click');
 await ui.button('查看生成计划').dispatchEvent('click');
 assert.deepEqual(ui.requests.slice(before).map(request=>request.url),['/api/workbench/drafts/saved']);
 gate.resolve();await pending;
 assert.deepEqual(ui.requests.slice(before).map(request=>request.url),['/api/workbench/drafts/saved','/api/workbench/check','/api/workbench/execution-plan']);
 assert.equal(writes(ui).length,0);
});

test('leaving during the confirmed scope save cannot reopen a plan or continue the old check',async()=>{
 const ui=await ready(),gate=deferred();await review(ui);
 ui.routes.set('/api/workbench/drafts/saved',async options=>{await gate.promise;return {...JSON.parse(options.body),id:'saved',revision:2,target_key:'target-A'};});
 const before=ui.requests.length,pending=confirmation(ui).click();await tick();ui.leave();gate.resolve();await pending;
 assert.deepEqual(ui.requests.slice(before).map(request=>request.url),['/api/workbench/drafts/saved']);
 assert.equal(ui.document.querySelector('.modal'),null);assert.equal(writes(ui).length,0);
});

test('a failed confirmed scope save preserves the explicit configuration but never plans or writes automatically',async()=>{
 const ui=await ready();await review(ui);
 ui.routes.set('/api/workbench/drafts/saved',()=>{throw new Error('save unavailable');});
 const before=ui.requests.length;await confirmation(ui).click();
 assert.equal(ui.modelState().document.tables.length,9);assert.equal(ui.modelState().dirty,true);
 assert.deepEqual(ui.requests.slice(before).map(request=>request.url),['/api/workbench/drafts/saved']);
 assert.equal(ui.document.querySelector('.modal'),null);assert.match(ui.root().textContent,/save unavailable/);assert.equal(writes(ui).length,0);
});
