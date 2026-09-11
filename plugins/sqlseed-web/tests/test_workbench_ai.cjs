const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve=>setImmediate(resolve));
function harness(overrides={}) {
  const document=createDom(); document.createElementNS=(_,tag)=>new Element(tag);
  const modelContext=loadFrontend('workbench/model.js',{document});
  const Model=vm.runInContext('WorkbenchDocument',modelContext);
  const schema={schema_hash:'current',tables:[{name:'users',columns:[{name:'email',type:'TEXT'}],mapping:{email:{generator_name:'string',params:{}}}},{name:'orders',columns:[{name:'amount',type:'INTEGER'}],mapping:{}}]};
  const model=new Model(schema,{provider:'faker',locale:'zh_CN',tables:[{name:'orders',count:10,columns:[]}]});
  model.view.table='users';
  overrides.setupModel?.(model);
  const calls=[],applied=[];
  const config={available:true,ready:true,backends:[{id:'ollama',label:'Ollama'}],effective:{backend:'ollama',model:'test-model',base_url:'http://localhost:11434/v1',api_key_present:false}};
  const request=async(url,options={})=>{
    calls.push({url,body:options.body?JSON.parse(options.body):null});
    if(overrides.request)return overrides.request(url,options);
    if(url.endsWith('/config'))return config;
    if(url.endsWith('/suggest'))return {schema_hash:'current',suggestions:[{table:'users',column:'email',before:null,after:{name:'email',generator:'email',params:{}},reason:'电子邮箱字段匹配邮箱生成器'}],rejected:[]};
    return {ok:true,message:'connected',models:['test-model']};
  };
  const uiContext=loadFrontend('workbench/ui.js',{document});
  const dropdown=loadFrontend('dropdown.js',{document});
  const labels=loadFrontend('labels.js',{document});
  const eligibility=loadFrontend('workbench/ai-eligibility.js');
  const stream=loadFrontend('workbench/ai-stream.js',{TextDecoder,fetch:async(url,options)=>{
    const body=await request(url,options);
    return {ok:true,headers:new Headers({'Content-Type':'application/json'}),json:async()=>body};
  }});
  const context=loadFrontend('workbench/ai.js',{document,AbortController,api:request,
    requestAISuggestions:vm.runInContext('requestAISuggestions',stream),
    fieldAIEligibility:vm.runInContext('fieldAIEligibility',eligibility),
    ...vm.runInContext('({button,modal})',uiContext),createDropdown:vm.runInContext('createDropdown',dropdown),genLabel:vm.runInContext('genLabel',labels)});
  context.options={model,connId:'connection',isCurrent:()=>true,onApply:items=>applied.push(JSON.parse(JSON.stringify(items))),...overrides.options};
  const ui=vm.runInContext('openAIAssistant(options)',context);
  const find=label=>document.querySelectorAll('button').find(button=>button.textContent===label);
  return {document,model,calls,applied,ui,find,config};
}

test('AI begins with scope disclosure and only applies explicitly selected reviewed patches',async()=>{
  const t=harness();await tick();
  assert.match(t.document.textContent,/仅发送表结构/);
  await t.find('开始分析').click();
  assert.equal(t.applied.length,0);
  assert.match(t.document.textContent,/电子邮箱字段匹配邮箱生成器/);
  assert.match(t.document.textContent,/当前规则/);
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.tables,['users']);
  assert.deepEqual(t.model.document.tables.map(table=>table.name),['orders']);
  await t.find('应用所选建议').click();
  assert.equal(t.applied.length,0,'Nothing is preselected or silently applied');
  const choice=t.document.querySelector('[data-ai-suggestion]');choice.checked=true;await choice.dispatchEvent('change');
  await t.find('应用所选建议').click();
  assert.equal(t.applied[0][0].after.generator,'email');
});

test('one AI configuration assistant explains every scope and starts at the current table',async()=>{
  const t=harness();await tick();
  assert.equal(t.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'AI 配置助手');
  const current=t.document.querySelector('input[value="current"]');assert.equal(current.checked,true);
  assert.match(current.closest('label').textContent,/当前表.*users/);
  const scopes=t.document.querySelector('.wb-ai-scope');
  assert.equal(scopes.querySelectorAll('input[type="radio"]').length,5);
  assert.match(scopes.textContent,/已选表|已选生成表/);assert.match(scopes.textContent,/整库/);
  assert.match(scopes.textContent,/指定表/);assert.match(scopes.textContent,/指定字段/);
  assert.equal(scopes.querySelectorAll('.wb-ai-scope-description').length,5);
  const summary=t.document.querySelector('.wb-ai-scope-summary');
  assert.match(summary.textContent,/当前表.*users/);assert.match(summary.textContent,/1 个字段可优化/);
  assert.match(summary.textContent,/未加入生成范围.*草稿/);
  assert.equal(t.document.querySelector('[aria-label="选择要优化的字段"]').hidden,true);
  t.ui.close();
});

test('scope feedback distinguishes protected context from the actual field targets',async()=>{
  const t=harness({setupModel:model=>model.schema.tables[0].columns.push({name:'id',type:'INTEGER',is_primary_key:true})});await tick();
  let summary=t.document.querySelector('.wb-ai-scope-summary');
  assert.match(summary.textContent,/1 个字段可优化/);assert.match(summary.textContent,/1 个受保护字段/);
  const all=t.document.querySelector('input[value="database"]');all.checked=true;await all.dispatchEvent('change');
  summary=t.document.querySelector('.wb-ai-scope-summary');
  assert.match(summary.textContent,/整库/);assert.match(summary.textContent,/2 个字段可优化/);
  assert.deepEqual(t.model.document.tables.map(table=>table.name),['orders']);
  t.ui.close();
});

test('the unified field picker can limit a same-row relation to its output field',async()=>{
  const t=harness({setupModel:model=>{
    model.schema.tables[0].columns=[{name:'id',type:'INTEGER',is_primary_key:true},{name:'quantity',type:'INTEGER'},{name:'unit_price',type:'REAL'},{name:'total',type:'REAL'}];
    model.schema.tables[0].mapping={};
  }});await tick();
  const fields=t.document.querySelector('input[value="columns"]');fields.checked=true;await fields.dispatchEvent('change');
  const picker=t.document.querySelector('[aria-label="选择要优化的字段"]');assert.equal(picker.hidden,false);
  for(const name of ['quantity','unit_price']){const input=t.document.querySelector(`[data-ai-column="users.${name}"]`);input.checked=false;await input.dispatchEvent('change');}
  assert.equal(t.document.querySelector('[data-ai-column="users.id"]'),null);
  assert.match(t.document.querySelector('[data-ai-protected-column="users.id"]').textContent,/主键/);
  assert.match(t.document.querySelector('.wb-ai-scope-summary').textContent,/1 个字段可优化/);
  assert.match(t.document.querySelector('#ai-scope-help').textContent,/同表.*上下文/);
  const context=t.document.querySelector('[aria-label="业务说明"]');context.value='total = quantity × unit_price';await context.dispatchEvent('input');
  await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.tables,['users']);assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['total']}]);
  assert.equal(payload.business_context,'total = quantity × unit_price');
  assert.deepEqual(payload.document.tables.map(table=>table.name),['orders']);t.ui.close();
});

test('closing AI panel discards late model results',async()=>{
  let finish;
  const result=new Promise(resolve=>finish=resolve);
  const t=harness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:result});await tick();
  const pending=t.find('开始分析').click();t.ui.close();
  finish({schema_hash:'current',suggestions:[],rejected:[]});await pending;
  assert.equal(t.document.querySelectorAll('[role="dialog"]').length,0);assert.equal(t.applied.length,0);
});

test('edited document invalidates already reviewed suggestions',async()=>{
  const t=harness();await tick();await t.find('开始分析').click();
  const choice=t.document.querySelector('[data-ai-suggestion]');choice.checked=true;await choice.dispatchEvent('change');
  t.model.touch();await t.find('应用所选建议').click();
  assert.equal(t.applied.length,0);assert.match(t.document.textContent,/配置已变化/);
});

test('schema mismatch response never becomes applicable',async()=>{
  const t=harness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:{schema_hash:'old',suggestions:[],rejected:[]}});await tick();await t.find('开始分析').click();
  assert.match(t.document.textContent,/结构已变化/);assert.equal(t.document.querySelector('[data-ai-suggestion]'),null);
});

test('missing AI remains honest and cannot start an analysis',async()=>{
  const t=harness({request:async()=>({available:false,ready:true,message:'尚未安装 AI 插件'})});await tick();
  assert.match(t.document.textContent,/AI 扩展未安装.*规则建议与分析不可用/);assert.equal(t.find('开始分析').disabled,true);
  const before=JSON.stringify(t.model.document);
  await t.find('开始分析').dispatchEvent('click');
  assert.equal(t.calls.length,1);assert.equal(JSON.stringify(t.model.document),before);t.ui.close();
});

test('missing AI offers in-app installation and preserves the returning field context',async()=>{
  let transfer;
  const command="/tools/uv pip install --python '/workspace env/bin/python' 'sqlseed-web[ai]'";
  const initialState={scope:'columns',currentTable:'users',columnSelection:{users:['email']},businessContext:'使用中文邮箱域名'};
  const t=harness({options:{initialState,onSettings:value=>{transfer=value;}},request:async()=>({available:false,ready:false,message:'尚未安装 AI 插件',
    installer:{available:true,tool:'uv',shell:'posix',message:'命令针对当前 Web 使用的 Python 解释器'},install_command:command})});await tick();
  const state=t.document.querySelector('[aria-label="AI 状态"]');assert.ok(state);assert.match(state.textContent,/AI 扩展未安装.*规则建议与分析不可用/);
  const install=t.document.querySelector('[aria-label="安装 AI 插件"]');assert.ok(install);assert.equal(install.hidden,false);
  assert.match(install.textContent,/插件与版本.*安装/);
  assert.equal(install.querySelector('code'),null);
  assert.doesNotMatch(install.textContent,/终端|重启|解释器/);
  assert.equal(t.document.querySelector('.wb-ai-analysis').hidden,true);
  assert.equal(t.document.querySelector('.wb-ai-settings'),null);
  assert.equal(t.find('开始分析').hidden,true);
  await t.find('前往插件设置').click();assert.equal(transfer.section,'plugins');
  assert.equal(transfer.context.scope,'columns');assert.equal(transfer.context.businessContext,initialState.businessContext);
  assert.deepEqual(Array.from(transfer.context.columnSelection.users),['email']);
  assert.equal(t.calls.length,1);assert.ok(t.calls[0].url.endsWith('/config'));
});

test('broken AI imports explain unavailable analysis and link to plugin status without reinstall claims',async()=>{
  let transfer;
  const command="& 'C:\\Web Env\\python.exe' '-m' 'pip' 'check'";
  const t=harness({options:{onSettings:value=>{transfer=value;}},request:async()=>({available:false,ready:false,availability_status:'import_error',
    installer:{available:true,shell:'powershell'},install_command:'do not show this install command',repair_command:command})});await tick();
  const state=t.document.querySelector('[aria-label="AI 状态"]');
  assert.match(state.textContent,/AI 插件加载异常/);assert.doesNotMatch(state.textContent,/未安装/);
  assert.match(state.textContent,/规则建议与分析不可用/);
  const repair=t.document.querySelector('[aria-label="修复 AI 插件"]');assert.ok(repair);assert.equal(repair.hidden,false);
  assert.equal(repair.querySelector('code'),null);assert.match(repair.textContent,/插件与版本.*异常/);
  assert.doesNotMatch(repair.textContent,/未安装|do not show/);
  assert.equal(t.document.querySelector('.wb-ai-analysis').hidden,true);
  assert.equal(t.find('开始分析').hidden,true);assert.equal(t.find('开始分析').disabled,true);
  await t.find('查看插件状态').click();
  assert.equal(transfer.section,'plugins');assert.equal(transfer.context.currentTable,'users');
  assert.equal(t.calls.length,1);assert.ok(t.calls[0].url.endsWith('/config'));
});

test('missing installer details never replace the in-app plugin status path',async()=>{
  const t=harness({request:async()=>({available:false,ready:false,availability_status:'not_installed',
    installer:{available:false,python_executable:'/custom env/python',message:'未检测到可用的 pip 或 uv。请使用创建此 Python 环境的工具安装或修复组件。'},
    install_command:'unsafe stale command'})});await tick();
  const install=t.document.querySelector('[aria-label="安装 AI 插件"]');
  assert.ok(t.find('前往插件设置'));
  assert.doesNotMatch(install.textContent,/pip|uv|目标解释器|custom env/);
  assert.equal(install.querySelector('code'),null);assert.doesNotMatch(install.textContent,/unsafe stale command/);
  assert.equal(t.find('开始分析').disabled,true);assert.equal(t.calls.length,1);
});


test('unconfigured AI transfers current scope and business context without credential controls',async()=>{
  let transfer;
  const t=harness({options:{onSettings:value=>{transfer=value;}},request:async()=>({available:true,ready:false,effective:{backend:'ollama',model:''}})});await tick();
  assert.match(t.document.querySelector('[aria-label="AI 状态"]').textContent,/AI 待配置/);
  assert.equal(t.document.querySelector('.wb-ai-analysis').hidden,false);
  assert.equal(t.find('开始分析').disabled,true);
  const scope=t.document.querySelector('input[value="database"]');scope.checked=true;await scope.dispatchEvent('change');
  const business=t.document.querySelector('[aria-label="业务说明"]');business.value='使用中文邮箱域名';
  await t.find('前往设置').click();
  assert.equal(transfer.section,'ai');assert.equal(transfer.context.scope,'database');assert.equal(transfer.context.businessContext,'使用中文邮箱域名');
  assert.equal(t.document.querySelector('[role="dialog"]'),null);
  assert.equal(t.calls.length,1);assert.ok(t.calls[0].url.endsWith('/config'));
});


test('configured AI exposes its readiness without claiming a successful connection or probing automatically',async()=>{
  const t=harness();await tick();
  const state=t.document.querySelector('[aria-label="AI 状态"]');assert.ok(state);
  assert.match(state.textContent,/AI 配置已填写/);assert.doesNotMatch(state.textContent,/已连接|服务可用|连接成功/);
  assert.equal(t.document.querySelector('.wb-ai-settings'),null);assert.ok(t.find('更改设置'));
  assert.equal(t.document.querySelector('.wb-ai-analysis').hidden,false);
  assert.equal(t.document.querySelector('[aria-label="安装 AI 插件"]').hidden,true);
  assert.equal(t.find('开始分析').disabled,false);
  assert.equal(t.calls.length,1);assert.ok(t.calls[0].url.endsWith('/config'));
  t.ui.close();
});

test('an AI settings request error does not pretend the plugin is missing',async()=>{
  const t=harness({request:async()=>{throw new Error('无法读取 AI 设置');}});await tick();
  const state=t.document.querySelector('[aria-label="AI 状态"]');assert.ok(state);
  assert.match(state.textContent,/AI 状态未获取/);assert.match(state.textContent,/无法读取 AI 设置/);
  assert.equal(t.document.querySelector('[aria-label="安装 AI 插件"]').hidden,true);
  assert.equal(t.document.querySelector('.wb-ai-analysis').hidden,true);
  assert.equal(t.calls.length,1);t.ui.close();
});

test('assistant never renders credential input or a service URL from its configuration response',async()=>{
  const t=harness({request:async()=>({available:true,ready:true,effective:{backend:'ollama',model:'test',base_url:'https://user:secret@service/v1?key=secret',api_key:'never-render'}})});await tick();
  assert.equal(t.document.querySelector('.dropdown-btn'),null);
  assert.equal(t.document.querySelector('input[type="password"]'),null);
  assert.doesNotMatch(t.document.textContent,/secret|never-render|user:/);
  t.ui.close();assert.equal(t.document.querySelectorAll('[role="dialog"]').length,0);
});


test('busy analysis disables scope and service controls until it completes',async()=>{
  let finish;
  const result=new Promise(resolve=>finish=resolve);
  const t=harness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:result});await tick();
  const pending=t.find('开始分析').click();
  assert.ok(t.document.querySelectorAll('input[type="radio"]').every(input=>input.disabled));
  assert.equal(t.find('更改设置').disabled,true);
  finish({schema_hash:'current',suggestions:[],rejected:[]});await pending;
  assert.equal(t.find('更改设置').disabled,false);
  t.ui.close();
});

test('review renders before and after inside the same two-column diff',async()=>{
  const t=harness();await tick();await t.find('开始分析').click();
  const diff=t.document.querySelector('.wb-ai-diff');
  assert.equal(diff.children.length,2);
  assert.match(diff.children[0].textContent,/当前规则/);
  assert.match(diff.children[1].textContent,/建议规则/);
  t.ui.close();
});

test('late settings summary cannot reopen a closed AI panel',async()=>{
  let finish;
  const response=new Promise(resolve=>{finish=resolve;});
  const t=harness({request:async()=>response});t.ui.close();
  finish({available:true,ready:true,effective:{backend:'ollama',model:'late-model'}});await tick();
  assert.equal(t.document.querySelectorAll('[role="dialog"]').length,0);assert.doesNotMatch(t.document.textContent,/late-model/);
});






test('database analysis preserves executable selection and sends all unselected drafts intact',async()=>{
  const t=harness();await tick();
  t.model.view.tableDrafts.users={name:'users',count:77,seed:31,columns:[{name:'email',generator:'email',constraints:{unique:true}}]};
  const radio=t.document.querySelector('input[value="database"]');assert.ok(radio);
  radio.checked=true;await radio.dispatchEvent('change');await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.tables,['users','orders']);
  assert.deepEqual(payload.document.tables.map(table=>table.name),['orders']);
  assert.equal(payload.table_drafts[0].count,77);assert.equal(payload.table_drafts[0].seed,31);
  assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['email']},{table:'orders',columns:['amount']}]);
  assert.deepEqual(t.model.document.tables.map(table=>table.name),['orders']);t.ui.close();
});

test('explicit table checkboxes and initial column selection are separate from generation scope',async()=>{
  const t=harness({options:{columns:['email']}});await tick();
  assert.equal(t.document.querySelector('input[value="columns"]').checked,true);
  const description=t.document.querySelector('[aria-label="业务说明"]');assert.ok(description);description.value='姓名应符合中文习惯';
  await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['email']}]);assert.equal(payload.business_context,'姓名应符合中文习惯');
  t.ui.close();
  const b=harness();await tick();const radio=b.document.querySelector('input[value="tables"]');radio.checked=true;await radio.dispatchEvent('change');
  const orders=b.document.querySelector('[data-ai-table="orders"]');orders.checked=false;await orders.dispatchEvent('change');
  assert.equal(b.find('开始分析').disabled,true);
  const users=b.document.querySelector('[data-ai-table="users"]');users.checked=true;await users.dispatchEvent('change');await b.find('开始分析').click();
  assert.deepEqual(b.calls.find(call=>call.url.endsWith('/suggest')).body.tables,['users']);b.ui.close();
});

test('related suggestions share one checkbox and apply as an atomic group with readonly evidence',async()=>{
  const response={schema_hash:'current',suggestions:[
    {table:'users',column:'email',group_id:'relation-1',before:null,after:{name:'email',derive_from:'name',expression:'value'},relation:{template:'copy',sources:['name'],options:{}},reason:'同一行复制',evidence:{message:'只读样例',rows:[{name:'示例',email:'示例'}]}},
    {table:'orders',column:'amount',group_id:'relation-1',before:null,after:{name:'amount',generator:'integer',params:{}},reason:'关联规则'}],rejected:[]};
  const t=harness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:response});await tick();
  const radio=t.document.querySelector('input[value="database"]');radio.checked=true;await radio.dispatchEvent('change');await t.find('开始分析').click();
  assert.equal(t.document.querySelectorAll('[data-ai-suggestion]').length,1);
  assert.match(t.document.textContent,/name → email/);assert.match(t.document.textContent,/只读样例/);
  const input=t.document.querySelector('[data-ai-suggestion]');input.checked=true;await input.dispatchEvent('change');await t.find('应用所选建议').click();
  assert.equal(t.applied[0].length,2);assert.equal(t.applied[0][0].group_id,t.applied[0][1].group_id);
});

test('out-of-scope member discards its complete related group',async()=>{
  const t=harness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:{schema_hash:'current',suggestions:[
    {table:'users',column:'email',group_id:'g',after:{name:'email',generator:'email'}},
    {table:'orders',column:'amount',group_id:'g',after:{name:'amount',generator:'integer'}}]}});await tick();await t.find('开始分析').click();
  assert.equal(t.document.querySelectorAll('[data-ai-suggestion]').length,0);t.ui.close();
});

test('initial configuration loading disables analysis and the settings transition',async()=>{
  let finish;const waiting=new Promise(resolve=>finish=resolve);
  const t=harness({request:async()=>waiting});
  assert.equal(t.find('开始分析').disabled,true);assert.equal(t.find('前往设置').disabled,true);
  assert.equal(t.document.querySelector('[aria-label="模型名称"]'),null);
  finish({available:true,ready:true,effective:{backend:'ollama',model:'loaded'}});await tick();
  assert.equal(t.find('更改设置').disabled,false);assert.equal(t.find('开始分析').disabled,false);t.ui.close();
});


test('column scope explains protected fields, keeps NULL editable and never re-enables managed fields',async()=>{
  const t=harness({options:{columns:['id','email']},setupModel:model=>{
    model.schema.tables[0].columns.push({name:'id',type:'INTEGER',is_primary_key:true,is_autoincrement:true});
    model.setColumn('users','email',{generator:'skip'});
  }});await tick();
  const id=t.document.querySelector('[data-ai-protected-column="users.id"]');
  const email=t.document.querySelector('[data-ai-column="users.email"]');
  assert.ok(id);assert.equal(id.querySelector('input'),null);assert.equal(email.disabled,false);assert.equal(email.checked,true);
  assert.match(id.textContent,/数据库|自动/);
  await t.find('开始分析').click();
  assert.equal(t.document.querySelector('[data-ai-column="users.id"]'),null,'A completed analysis must not make a protected field selectable');
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['email']}]);
  t.ui.close();
});

test('whole-table analysis filters protected mutation targets while retaining that table in context',async()=>{
  const t=harness({setupModel:model=>model.schema.tables[0].columns.push({name:'id',type:'INTEGER',is_primary_key:true})});
  await tick();await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.tables,['users']);assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['email']}]);
  t.ui.close();
});

test('a protected initial column is not replaced by an unrelated editable selection',async()=>{
  const t=harness({options:{columns:['id']},setupModel:model=>model.schema.tables[0].columns.push({name:'id',type:'INTEGER',is_primary_key:true})});
  await tick();assert.equal(t.find('开始分析').disabled,true);
  assert.equal(t.document.querySelector('[data-ai-column="users.email"]').checked,false);
  assert.match(t.document.textContent,/可.*调整|可.*修改/);t.ui.close();
});

test('database analysis keeps fully protected tables as context without allowing their columns to change',async()=>{
  const t=harness({setupModel:model=>{model.schema.tables[1].columns=[{name:'id',type:'INTEGER',is_primary_key:true}];}});
  await tick();const scope=t.document.querySelector('input[value="database"]');scope.checked=true;await scope.dispatchEvent('change');
  await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.tables,['users','orders']);
  assert.deepEqual(payload.allowed_targets,[{table:'users',columns:['email']}]);t.ui.close();
});

function fieldPickerHarness(overrides={}) {
  return harness({...overrides,options:{columns:['email'],...overrides.options},setupModel:model=>{
    model.schema.tables[1].columns=[
      {name:'ordered_at',type:'DATETIME'},
      {name:'promised_at',type:'DATETIME'},
      {name:'total_cents',type:'INTEGER',is_computed:true},
    ];
    overrides.setupModel?.(model);
  }});
}
async function searchFields(t,value) {
  const input=t.document.querySelector('[aria-label="查找表或字段"]');
  assert.ok(input,'Specified-field scope needs a table/field search');
  input.value=value;await input.dispatchEvent('input');return input;
}
const selectFiltered=t=>t.document.querySelector('[data-ai-select-filtered]');

test('qualified field search authorizes only that editable target and preserves document and drafts',async()=>{
  const t=fieldPickerHarness();await tick();
  const before=JSON.stringify({document:t.model.document,drafts:t.model.view.tableDrafts,epoch:t.model.epoch});
  assert.ok(t.find('清空选择'));await t.find('清空选择').click();
  await searchFields(t,' ORDERS.PROMISED_AT ');
  assert.match(selectFiltered(t).textContent,/选择筛选结果.*1/);
  assert.equal(t.document.querySelector('[data-ai-column="orders.ordered_at"]').closest('label').hidden,true);
  await selectFiltered(t).click();
  assert.match(t.document.querySelector('.wb-ai-field-count').textContent,/已选 1 个字段允许修改/);
  const business=t.document.querySelector('[aria-label="业务说明"]');business.value='promised_at 不早于 ordered_at';
  await t.find('开始分析').click();
  const payload=t.calls.find(call=>call.url.endsWith('/suggest')).body;
  assert.deepEqual(payload.allowed_targets,[{table:'orders',columns:['promised_at']}]);
  assert.deepEqual(payload.tables,['orders']);assert.equal(payload.business_context,'promised_at 不早于 ordered_at');
  assert.equal(JSON.stringify({document:t.model.document,drafts:t.model.view.tableDrafts,epoch:t.model.epoch}),before);
  t.ui.close();
});

test('filtering and scope round trips retain hidden field selection and explain whole-range bulk actions',async()=>{
  const t=fieldPickerHarness();await tick();
  const email=t.document.querySelector('[data-ai-column="users.email"]');
  assert.match(selectFiltered(t).textContent,/选择全部可选字段.*3/);
  await searchFields(t,'orders');await selectFiltered(t).click();
  assert.match(t.document.querySelector('.wb-ai-field-count').textContent,/已选 3 个字段允许修改/);
  assert.match(t.document.querySelector('.wb-ai-field-count').textContent,/筛选内 2.*其他 1/);
  await searchFields(t,'promised');
  assert.equal(email.checked,true);assert.equal(email,t.document.querySelector('[data-ai-column="users.email"]'));
  const current=t.document.querySelector('input[value="current"]');current.checked=true;await current.dispatchEvent('change');
  const fields=t.document.querySelector('input[value="columns"]');fields.checked=true;await fields.dispatchEvent('change');
  await searchFields(t,'');assert.equal(email.checked,true);
  await t.find('开始分析').click();
  assert.deepEqual(t.calls.find(call=>call.url.endsWith('/suggest')).body.allowed_targets,[{table:'users',columns:['email']},{table:'orders',columns:['ordered_at','promised_at']}]);
  t.ui.close();
});

test('protected-only and empty searches cannot select protected fields or erase hidden selection',async()=>{
  const t=fieldPickerHarness();await tick();
  await searchFields(t,'orders.total_cents');
  const protectedRow=t.document.querySelector('[data-ai-protected-column="orders.total_cents"]');
  assert.ok(protectedRow);assert.equal(protectedRow.querySelector('input'),null);
  assert.match(protectedRow.textContent,/计算/);assert.equal(selectFiltered(t).disabled,true);
  assert.match(t.document.querySelector('.wb-ai-field-results').textContent,/0 个可选.*1 个受保护/);
  await searchFields(t,'no_such_field');
  assert.equal(selectFiltered(t).disabled,true);assert.equal(t.document.querySelector('.wb-ai-field-empty').hidden,false);
  assert.match(t.document.querySelector('.wb-ai-field-count').textContent,/已选 1.*筛选内 0.*其他 1/);
  await t.find('开始分析').click();
  assert.deepEqual(t.calls.find(call=>call.url.endsWith('/suggest')).body.allowed_targets,[{table:'users',columns:['email']}]);
  await t.find('清空选择').click();assert.equal(t.find('开始分析').disabled,true);
  assert.equal(t.document.querySelector('[data-ai-column="users.email"]').checked,false);
  t.ui.close();
});

test('search alone preserves reviewed suggestions while an actual field-selection change clears them',async()=>{
  const t=fieldPickerHarness();await tick();await t.find('开始分析').click();
  const suggestion=t.document.querySelector('[data-ai-suggestion]');suggestion.checked=true;await suggestion.dispatchEvent('change');
  await searchFields(t,'orders.promised_at');
  assert.equal(t.document.querySelector('[data-ai-suggestion]'),suggestion);
  assert.equal(t.find('应用所选建议').disabled,false);
  await selectFiltered(t).click();
  assert.equal(t.document.querySelector('[data-ai-suggestion]'),null);assert.equal(t.find('应用所选建议').hidden,true);
  t.ui.close();
});

test('field search and bulk selection stay locked during analysis and closed results cannot apply',async context=>{
  let finish;
  const waiting=new Promise(resolve=>finish=resolve);
  const t=fieldPickerHarness({request:async url=>url.endsWith('/config')?{available:true,ready:true,effective:{backend:'ollama',model:'test'}}:waiting});await tick();
  context.after(()=>{t.ui.close();finish({schema_hash:'current',suggestions:[]});});
  const pending=t.find('开始分析').click();
  const search=t.document.querySelector('[aria-label="查找表或字段"]');assert.ok(search);assert.equal(search.disabled,true);
  assert.equal(selectFiltered(t).disabled,true);assert.equal(t.find('清空选择').disabled,true);
  await selectFiltered(t).dispatchEvent('click');await t.find('清空选择').dispatchEvent('click');
  const order=t.document.querySelector('[data-ai-column="orders.promised_at"]');order.checked=true;await order.dispatchEvent('change');
  assert.equal(order.checked,false);assert.match(t.document.querySelector('.wb-ai-field-count').textContent,/已选 1 个字段允许修改/);
  assert.deepEqual(t.calls.find(call=>call.url.endsWith('/suggest')).body.allowed_targets,[{table:'users',columns:['email']}]);
  t.ui.close();finish({schema_hash:'current',suggestions:[{table:'users',column:'email',after:{name:'email',generator:'email'}}]});await pending;
  assert.equal(t.applied.length,0);assert.equal(t.document.querySelector('[role="dialog"]'),null);
});

test('search opens matching groups and restores table and protected-reason disclosure state when cleared',async()=>{
  const t=fieldPickerHarness();await tick();
  const users=t.document.querySelector('[data-ai-field-table="users"]');
  const orders=t.document.querySelector('[data-ai-field-table="orders"]');
  assert.equal(users.open,true);assert.equal(orders.open,false);
  const protectedFields=orders.querySelector('.wb-ai-protected-fields');protectedFields.open=false;
  await searchFields(t,'orders.total_cents');
  assert.equal(users.hidden,true);assert.equal(orders.open,true);assert.equal(protectedFields.open,true);
  await searchFields(t,'');
  assert.equal(users.hidden,false);assert.equal(users.open,true);assert.equal(orders.open,false);assert.equal(protectedFields.open,false);
  t.ui.close();
});
