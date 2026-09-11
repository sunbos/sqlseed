const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element,createDom,loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tables = [
  {name:'orders',count:5,columns:[{name:'id',is_autoincrement:true},{name:'code',is_primary_key:true},{name:'amount'},{name:'active'},{name:'extra'}],omittedColumns:{extra:'数据库默认值'}},
  {name:'users',count:20,columns:[{name:'id',is_primary_key:true},{name:'name'}]},
];
function harness(options={}) {
  const document=createDom(),window=new Element('window');
  document.createElement=tag=>{
    const element=new Element(tag);element.scrollTop=0;element.scrollLeft=0;
    for(const dimension of ['clientHeight','clientWidth','scrollHeight','scrollWidth']) {
      Object.defineProperty(element,dimension,{get:()=>options.layout?.(element)?.[dimension] ?? 0});
    }
    return element;
  };
  document.createElementNS=(_,tag)=>new Element(tag);
  const ui=loadFrontend('workbench/ui.js',{document,window});
  const dropdown=loadFrontend('dropdown.js',{document,window});
  const context=loadFrontend('workbench/preview.js',{document,window,...options.browser,
    ...vm.runInContext('({modal,button,valueText})',ui),createDropdown:vm.runInContext('createDropdown',dropdown)});
  const requests=[],results=[],resultOptions=[],changes=[],errors=[];let current=true,guardBusy=false;
  const component=context.openDataPreview({tables,currentTable:'orders',selectedTables:['orders','users'],
    generate:async request=>{requests.push(JSON.parse(JSON.stringify(request)));return options.generate?options.generate(request):{ok:true,samples:{orders:[{code:'A',amount:0,active:false},{code:'B',amount:null,active:true}]},issues:[]};},
    guard:task=>async(...args)=>{if(guardBusy)return;guardBusy=true;try{return await task(...args);}finally{guardBusy=false;}},
    isCurrent:()=>current,onResult:(result,options)=>{results.push(result);resultOptions.push(JSON.parse(JSON.stringify(options)));},
    onError:error=>errors.push(error),onOptionsChange:value=>changes.push(JSON.parse(JSON.stringify(value))),
    ...options.props});
  const find=label=>document.querySelectorAll('button').find(node=>node.textContent===label);
  const scope=async label=>{await document.querySelector('[aria-label="预览范围"]').click();
    await document.querySelector('.dropdown-floating').querySelectorAll('[role="option"]').find(node=>node.textContent===label).click();};
  return {document,context,component,requests,results,resultOptions,changes,errors,find,scope,setCurrent:value=>{current=value;},count:()=>document.querySelector('[aria-label="每表预览行数"]')};
}

test('creates the modal immediately and generates only when its guarded refresh is called',async()=>{
  const t=harness();
  assert.equal(t.document.querySelector('[role="dialog"]').getAttribute('aria-label'),'预览数据');
  assert.equal(t.component.dialog.el.classList.contains('wb-data-preview'),true);
  assert.equal(t.requests.length,0);assert.equal(t.count().value,'10');
  assert.match(t.document.textContent,/临时.*不写入数据库/);
  assert.match(t.document.textContent,/正式生成.*重新取值/);
  await t.component.refresh();
  assert.deepEqual(t.requests,[{scope:'current',count:10,table:'orders'}]);
  assert.equal(t.results.length,1);
  assert.deepEqual(t.resultOptions,[{scope:'current',count:10,table:'orders'}]);
});

test('inline previews keep ten actual rows natural and limit only longer results',async()=>{
  for(const size of [10,100,3]) {
    const container=new Element('section');container._connected=true;
    const t=harness({props:{container,initialCount:100},generate:()=>({ok:true,
      samples:{orders:Array.from({length:size},(_,index)=>({code:`row ${index}`}))},issues:[]})});
    await t.component.refresh();
    const scroll=container.querySelector('.wb-preview-scroll');
    assert.equal(scroll.classList.contains('wb-preview-long'),size>10);
    assert.equal(scroll.querySelector('tbody').children.length,size);
    t.component.destroy();
  }
});

test('column name and generation rule are separate direct actions with exact return context',async()=>{
  const actions=[];
  const t=harness({props:{tables:[{name:'orders',columns:[{name:'code',type:'TEXT',nullable:false}],
    ruleSummaries:{code:{label:'字符串',detail:'最大长度 16'}}}],
    onColumnAction:(action,context)=>actions.push({action,context})}});
  await t.component.refresh();
  const name=t.document.querySelector('[data-preview-column="code"][data-preview-entry="information"]');
  const rule=t.document.querySelector('[data-preview-column="code"][data-preview-entry="rule"]');
  assert.ok(name);assert.ok(rule);
  assert.equal(name.tagName,'BUTTON');assert.equal(rule.tagName,'BUTTON');
  assert.equal(name.parentNode,rule.parentNode);
  assert.equal(name.parentNode.querySelectorAll('button').length,2);
  assert.match(rule.textContent,/规则.*字符串/);
  assert.match(name.parentNode.querySelector('.wb-preview-column-meta').textContent,/TEXT.*NOT NULL/);
  assert.doesNotMatch(rule.textContent,/TEXT|NOT NULL/);
  const blocks=t.component.dialog.body.children.map(node=>node.className);
  await name.click();await rule.click();
  assert.equal(t.document.querySelector('.wb-preview-column-actions'),null);
  assert.equal(t.document.querySelector('[aria-label="所选字段操作"]'),null);
  assert.deepEqual(t.component.dialog.body.children.map(node=>node.className),blocks);
  assert.deepEqual(actions.map(({action,context})=>({action,table:context.table,column:context.column,entry:context.view.columnAction})),[
    {action:'information',table:'orders',column:'code',entry:'information'},
    {action:'rule',table:'orders',column:'code',entry:'rule'},
  ]);
  assert.equal(t.requests.length,1);
});

test('direct header actions are disabled while refreshing and reject detached interactions',async()=>{
  const pending=deferred();let edits=0;
  const t=harness({props:{initialResult:{ok:true,samples:{orders:[{code:'old'}]}},onColumnAction:()=>edits++},generate:()=>pending.promise});
  const name=t.document.querySelector('[data-preview-column="code"][data-preview-entry="information"]');
  const rule=t.document.querySelector('[data-preview-column="code"][data-preview-entry="rule"]');
  assert.ok(name);assert.ok(rule);
  const running=t.component.refresh();await tick();
  assert.equal(name.disabled,true);assert.equal(rule.disabled,true);
  await name.dispatchEvent('click');await rule.dispatchEvent('click');assert.equal(edits,0);
  t.component.dialog.close();pending.resolve({ok:true,samples:{orders:[{code:'new'}]}});await running;
  await rule.dispatchEvent('click');assert.equal(edits,0);
});

test('preview headers show real metadata and column actions target the displayed table',async()=>{
  const actions=[];
  const source=[{name:'users',primary_key:['id'],foreign_keys:[],columns:[{name:'id',type:'INTEGER',nullable:false,is_primary_key:true}]},
    {name:'orders',primary_key:[],foreign_keys:[{columns:['user_id'],ref_table:'users',ref_columns:['id']}],columns:[{name:'user_id',type:'BIGINT',nullable:false},{name:'note',type:'TEXT',nullable:true}]}];
  const t=harness({props:{tables:source,currentTable:'users',initialScope:'selected',onColumnAction:(action,context)=>actions.push({action,context})},
    generate:()=>({ok:true,order:['users','orders'],samples:{users:[{id:1}],orders:[{user_id:1,note:'example'}]},issues:[]})});
  await t.component.refresh();await t.find('orders').click();
  const header=t.document.querySelector('[data-preview-column="user_id"]');assert.ok(header);
  assert.match(header.parentNode.textContent,/BIGINT.*FK.*NOT NULL/);
  await header.click();
  assert.equal(t.document.querySelector('.wb-preview-column-actions'),null);
  assert.equal(actions[0].action,'information');assert.equal(actions[0].context.table,'orders');assert.equal(actions[0].context.column,'user_id');
  assert.equal(actions[0].context.view.shownTable,'orders');
  assert.equal(header.getAttribute('aria-pressed'),'true');
});

test('batch table labels use execution order and retain unsorted error tables without mutating selection',async()=>{
  const selected=['orders','users','failed'];
  const t=harness({props:{initialScope:'selected',selectedTables:selected},generate:()=>({ok:false,order:['users','users','outside','orders'],samples:{},issues:[]})});
  await t.component.refresh();
  assert.deepEqual(t.document.querySelector('.wb-preview-tables').querySelectorAll('button').map(node=>node.textContent),['users','orders','failed']);
  assert.deepEqual(selected,['orders','users','failed']);
});

test('preview view snapshots retain selected column, count and scroll while stale samples require a new preview',async()=>{
  const layout=()=>({clientWidth:300,scrollWidth:900,clientHeight:120,scrollHeight:650});
  const t=harness({layout,props:{initialScope:'selected',initialCount:7,onColumnAction:()=>{}},generate:()=>({ok:true,samples:{orders:[{code:'old'}],users:[{id:1,name:'old name'}]},issues:[]})});
  await t.component.refresh();await t.find('users').click();
  const column=t.document.querySelector('[data-preview-column="name"]');assert.ok(column);await column.click();
  const scroller=t.document.querySelector('.wb-preview-scroll');scroller.scrollLeft=230;scroller.scrollTop=75;t.component.dialog.body.scrollTop=45;
  const view=t.component.getView();t.component.dialog.close();
  const next=harness({layout,props:{initialScope:'selected',initialView:view,initialResult:view.result,initialStale:true,onColumnAction:()=>{}}});
  assert.equal(next.find('users').getAttribute('aria-pressed'),'true');assert.equal(next.count().value,'7');
  assert.equal(next.document.querySelector('[data-preview-column="name"]').getAttribute('aria-pressed'),'true');
  assert.equal(next.document.querySelector('.wb-preview-scroll').scrollLeft,230);assert.equal(next.document.querySelector('.wb-preview-scroll').scrollTop,75);
  assert.equal(next.component.dialog.body.scrollTop,45);assert.match(next.document.querySelector('.wb-preview-status').textContent,/规则已改变.*旧样例.*重新预览/);
  assert.equal(next.requests.length,0);
});

test('renders rows as records, preserves typed values and uses omission reasons only for absent cells',async()=>{
  const t=harness();await t.component.refresh();
  const table=t.document.querySelector('.wb-preview-data');
  assert.equal(table.querySelector('caption').textContent,'orders · 预览记录');
  assert.deepEqual(table.querySelector('thead').querySelectorAll('.wb-preview-column-name').map(node=>node.textContent),['id','code','amount','active','extra']);
  const rows=table.querySelector('tbody').querySelectorAll('tr');
  assert.equal(rows.length,2);
  assert.deepEqual(rows[0].querySelectorAll('td').map(node=>node.textContent),['数据库分配','A','0','false','数据库默认值']);
  assert.equal(rows[1].querySelectorAll('td')[3].textContent,'true');
  assert.match(t.document.querySelector('.wb-preview-summary').textContent,/实际展示 2 行/);
  assert.match(t.document.querySelector('.wb-preview-summary').textContent,/最多 10 行/);
});

test('actual null and explicit IDs override metadata placeholders, and ordinary missing PK is not allocated',async()=>{
  const t=harness({generate:async()=>({ok:true,samples:{orders:[{id:42,code:null,amount:1,extra:null}]},issues:[]})});
  await t.component.refresh();
  assert.deepEqual(t.document.querySelector('tbody').querySelectorAll('td').map(node=>node.textContent),['42','NULL','1','暂不可预览','NULL']);
  const missing=harness({generate:async()=>({ok:true,samples:{orders:[{amount:1}]},issues:[]})});await missing.component.refresh();
  assert.equal(missing.document.querySelector('tbody').querySelectorAll('td')[1].textContent,'暂不可预览');
});

test('table names, fields, records and issue text render as text instead of HTML',async()=>{
  const payload='<img src=x onerror=alert(1)>';
  const name='<h1>orders</h1>',field='<b>code</b>';
  const t=harness({props:{tables:[{name,columns:[{name:field},{name:'amount'}]}],currentTable:name,selectedTables:[name]},
    generate:async()=>({ok:false,samples:{[name]:[{[field]:payload,amount:{nested:'<script>'}}]},issues:[{severity:'error',table:name,column:field,message:payload}]})});
  await t.component.refresh();
  assert.match(t.document.textContent,/<img src=x onerror=alert\(1\)>/);
  assert.match(t.document.textContent,/\{"nested":"<script>"\}/);
  assert.equal(t.document.querySelector('img'),null);assert.equal(t.document.querySelector('script'),null);
  assert.equal(t.document.querySelector('h1'),null);assert.equal(t.document.querySelector('b'),null);
});

test('current scope hides upstream samples while selected scope retains tables with no result',async()=>{
  const t=harness({generate:async()=>({ok:true,preview_complete:false,samples:{users:[{id:4,name:'Anna'}]},issues:[{severity:'warning',table:'orders',message:'订单依赖用户数据。'}]})});
  await t.component.refresh();
  assert.equal(t.document.querySelector('.wb-preview-data'),null);
  assert.match(t.document.querySelector('.wb-preview-empty').textContent,/依赖/);
  assert.doesNotMatch(t.document.querySelector('.wb-preview-results').textContent,/Anna/);
  await t.scope('已选表 · 2 张');
  assert.equal(t.document.querySelector('.wb-preview-data'),null);
  assert.match(t.document.querySelector('.wb-preview-status').textContent,/重新预览/);
  await t.component.refresh();
  assert.equal(t.document.querySelector('.wb-preview-tables').querySelectorAll('button').length,2);
  await t.find('users').click();
  assert.match(t.document.querySelector('.wb-preview-results').textContent,/Anna/);
  await t.find('orders').click();assert.match(t.document.querySelector('.wb-preview-empty').textContent,/依赖/);
  assert.match(t.document.querySelector('.wb-preview-issues').textContent,/订单依赖用户数据/);
});

test('empty selected scope makes no request and points to table selection',async()=>{
  const t=harness({props:{selectedTables:[],initialScope:'selected'}});await t.component.refresh();
  assert.equal(t.requests.length,0);assert.match(t.document.querySelector('.wb-preview-error').textContent,/勾选/);
});

test('preview count validates 1 through 100, keeps invalid drafts and clears old rows when options change',async()=>{
  const t=harness();await t.component.refresh();
  for(const value of ['','0','101','1.5','abc']){
    t.count().value=value;await t.count().dispatchEvent('input');await t.component.refresh();
    assert.equal(t.count().value,value);assert.equal(t.count().getAttribute('aria-invalid'),'true');
    assert.equal(t.requests.length,1);assert.equal(t.document.querySelector('.wb-preview-data'),null);
  }
  for(const value of ['1','100']){
    t.count().value=value;await t.count().dispatchEvent('input');await t.component.refresh();
    assert.equal(t.requests.at(-1).count,Number(value));assert.equal(t.count().getAttribute('aria-invalid'),null);
    assert.equal(t.changes.at(-1).count,Number(value));
  }
  assert.deepEqual(tables.map(table=>table.count),[5,20]);
});

test('loading disables options and duplicate refresh while close remains available',async()=>{
  const gate=deferred();const t=harness({generate:()=>gate.promise});
  const pending=t.component.refresh();await tick();
  assert.equal(t.count().disabled,true);assert.equal(t.document.querySelector('[aria-label="预览范围"]').disabled,true);
  assert.equal(t.find('重新预览').disabled,true);assert.equal(t.find('关闭').disabled,false);
  await t.component.refresh();assert.equal(t.requests.length,1);
  gate.resolve({ok:true,samples:{orders:[]},issues:[]});await pending;
  assert.equal(t.count().disabled,false);assert.equal(t.find('重新预览').disabled,false);
});

test('first loading shows a compact placeholder until real records arrive',async()=>{
  const gate=deferred(),t=harness({generate:()=>gate.promise});
  const pending=t.component.refresh();await tick();
  assert.match(t.document.querySelector('.wb-preview-loading')?.textContent || '',/正在生成/);
  assert.equal(t.document.querySelector('.wb-preview-data'),null);
  gate.resolve({ok:true,samples:{orders:[{code:'ready'}]},issues:[]});await pending;
  assert.equal(t.document.querySelector('.wb-preview-loading'),null);
  assert.match(t.document.querySelector('.wb-preview-data').textContent,/ready/);
});

test('delayed refresh retains records, issues, selected table and viewport until the new response',async()=>{
  const gate=deferred();let attempts=0;
  const t=harness({props:{initialScope:'selected'},layout:()=>({clientWidth:300,scrollWidth:1000,clientHeight:100,scrollHeight:600}),
    generate:()=>attempts++?gate.promise:{ok:true,samples:{orders:[{code:'first'}],users:[{id:1,name:'old user'}]},
      issues:[{severity:'warning',table:'orders',message:'上次关联提示'}]}});
  await t.component.refresh();await t.find('users').click();
  const scroller=t.document.querySelector('.wb-preview-scroll'),oldTable=t.document.querySelector('.wb-preview-data');
  const oldTabs=t.document.querySelector('.wb-preview-tables').children.slice();
  scroller.scrollLeft=260;scroller.scrollTop=170;t.component.dialog.body.scrollTop=60;
  const pending=t.component.refresh();await tick();
  assert.equal(t.document.querySelector('.wb-preview-data'),oldTable);
  assert.deepEqual(t.document.querySelector('.wb-preview-tables').children,oldTabs);
  assert.match(t.document.querySelector('.wb-preview-issues').textContent,/上次关联提示/);
  assert.match(t.document.querySelector('.wb-preview-status').textContent,/正在更新.*上次结果/);
  assert.equal(scroller.scrollLeft,260);assert.equal(scroller.scrollTop,170);
  assert.equal(t.find('users').getAttribute('aria-pressed'),'true');
  assert.equal(t.find('重新预览').disabled,true);assert.equal(t.find('关闭').disabled,false);
  await t.component.refresh();assert.equal(t.requests.length,2);
  // Reading and scrolling the old result while waiting must survive publication too.
  scroller.scrollLeft=280;scroller.scrollTop=190;t.component.dialog.body.scrollTop=80;
  gate.resolve({ok:true,samples:{orders:[{code:'second'}],users:[{id:2,name:'updated user'}]},issues:[]});await pending;
  const updated=t.document.querySelector('.wb-preview-scroll');
  assert.notEqual(t.document.querySelector('.wb-preview-data'),oldTable);
  assert.match(updated.textContent,/updated user/);assert.doesNotMatch(updated.textContent,/old user/);
  assert.equal(updated.scrollLeft,280);assert.equal(updated.scrollTop,190);
  assert.equal(t.component.dialog.body.scrollTop,80);
  assert.equal(t.find('users').getAttribute('aria-pressed'),'true');
  assert.equal(t.document.querySelector('.wb-preview-issues').textContent,'');
  assert.equal(t.document.querySelector('.wb-preview-results').getAttribute('aria-busy'),'false');
});

test('failed refresh retains previous records and marks them old until a successful retry',async()=>{
  const gate=deferred();let attempts=0;
  const t=harness({generate:()=>{
    attempts++;
    if(attempts===2)return gate.promise;
    return {ok:true,samples:{orders:[{code:attempts===1?'last result':'retry result'}]},issues:[]};
  }});
  await t.component.refresh();const oldTable=t.document.querySelector('.wb-preview-data');
  const pending=t.component.refresh();await tick();gate.reject(new Error('数据库暂时忙碌'));await pending;
  assert.equal(t.document.querySelector('.wb-preview-data'),oldTable);
  assert.match(t.document.querySelector('.wb-preview-status').textContent,/更新失败.*上次结果/);
  assert.match(t.document.querySelector('.wb-preview-error').textContent,/数据库暂时忙碌/);
  assert.equal(t.find('重新预览').disabled,false);assert.equal(t.count().disabled,false);assert.equal(t.errors.length,1);
  await t.component.refresh();
  assert.match(t.document.querySelector('.wb-preview-data').textContent,/retry result/);
  assert.doesNotMatch(t.document.querySelector('.wb-preview-status').textContent,/上次结果|失败/);
  assert.equal(t.document.querySelector('.wb-preview-error').textContent,'');
});

test('refresh keeps changed-rule samples visibly stale and blocks column edits until a successful retry',async()=>{
  const gate=deferred();let attempts=0,edits=0;
  const t=harness({props:{initialStale:true,onColumnAction:()=>edits++,
    initialView:{column:'code'},initialResult:{ok:true,samples:{orders:[{code:'old rule result'}]},issues:[]}},
    generate:()=>attempts++?{ok:true,samples:{orders:[{code:'new rule result'}]},issues:[]}:gate.promise});
  const pending=t.component.refresh();await tick();
  assert.match(t.document.querySelector('.wb-preview-status').textContent,/规则已改变.*旧样例/);
  assert.equal(t.document.querySelector('[data-preview-column="code"]').disabled,true);
  const rule=t.document.querySelector('[data-preview-column="code"][data-preview-entry="rule"]');
  assert.equal(rule.disabled,true);
  await rule.click();assert.equal(edits,0);
  gate.reject(new Error('temporarily unavailable'));await pending;
  assert.match(t.document.querySelector('.wb-preview-status').textContent,/更新失败.*规则已改变.*旧样例/);
  assert.equal(t.component.getView().stale,true);
  assert.equal(rule.disabled,false);
  await t.component.refresh();
  assert.equal(t.component.getView().stale,false);
  assert.doesNotMatch(t.document.querySelector('.wb-preview-status').textContent,/旧样例/);
});

test('switching tables restores independent scroll positions and clamps after fewer refreshed rows',async()=>{
  let shorter=false;
  const rows=row=>Array.from({length:shorter?4:20},(_,index)=>({...row,id:index}));
  const t=harness({props:{initialScope:'selected',initialCount:100},layout:element=>element.classList.contains('wb-preview-scroll')
    ?{clientWidth:300,scrollWidth:shorter?400:1100,clientHeight:100,scrollHeight:element.querySelector('tbody').children.length*40}:null,
    generate:()=>({ok:true,samples:{orders:rows({code:shorter?'short':'long'}),users:rows({name:'user'})},issues:[]})});
  await t.component.refresh();let viewport=t.document.querySelector('.wb-preview-scroll');
  viewport.scrollLeft=500;viewport.scrollTop=300;
  await t.find('users').click();viewport=t.document.querySelector('.wb-preview-scroll');
  assert.equal(viewport.scrollLeft,0);assert.equal(viewport.scrollTop,0);
  viewport.scrollLeft=120;viewport.scrollTop=80;
  await t.find('orders').click();viewport=t.document.querySelector('.wb-preview-scroll');
  assert.equal(viewport.scrollLeft,500);assert.equal(viewport.scrollTop,300);
  await t.find('users').click();viewport=t.document.querySelector('.wb-preview-scroll');
  assert.equal(viewport.scrollLeft,120);assert.equal(viewport.scrollTop,80);
  shorter=true;await t.component.refresh();viewport=t.document.querySelector('.wb-preview-scroll');
  assert.equal(viewport.scrollLeft,100);assert.equal(viewport.scrollTop,60);
  await t.find('orders').click();viewport=t.document.querySelector('.wb-preview-scroll');
  assert.equal(viewport.scrollLeft,100);assert.equal(viewport.scrollTop,60);
});

test('body-scroll fallback remembers each table independently without counting its offset twice',async()=>{
  const t=harness({props:{initialScope:'selected',initialCount:100},
    browser:{innerWidth:390,getComputedStyle:()=>({maxHeight:'800px'})},
    layout:element=>element.classList.contains('wb-modal-body')
      ?{clientHeight:600,scrollHeight:4300}:element.classList.contains('wb-preview-scroll')
        ?{clientWidth:300,scrollWidth:1100,clientHeight:4000,scrollHeight:4000}:null,
    generate:()=>({ok:true,samples:{orders:Array.from({length:100},()=>({code:'order'})),
      users:Array.from({length:100},()=>({name:'user'}))},issues:[]})});
  await t.component.refresh();
  t.component.dialog.body.scrollTop=320;
  const saved=t.component.getView();
  assert.equal(saved.tableScroll.orders.top,320);
  assert.equal(saved.bodyScroll.top,0);
  await t.find('users').click();assert.equal(t.component.dialog.body.scrollTop,0);
  t.component.dialog.body.scrollTop=80;
  await t.find('orders').click();assert.equal(t.component.dialog.body.scrollTop,320);
  await t.find('users').click();assert.equal(t.component.dialog.body.scrollTop,80);
  t.component.dialog.close();
});

test('a refresh invalidated by configuration or session expiry cannot replace retained results',async()=>{
  for(const outcome of ['changed-success','changed-failure','expired']) {
    const gate=deferred();let attempt=0;
    const t=harness({generate:()=>attempt++?gate.promise:{ok:true,samples:{orders:[{code:'last valid result'}]},issues:[]}});
    await t.component.refresh();const oldTable=t.document.querySelector('.wb-preview-data');
    const pending=t.component.refresh();await tick();
    if(outcome.startsWith('changed'))t.setCurrent(false);
    if(outcome==='changed-failure')gate.reject(new Error('obsolete failure'));
    else gate.resolve(outcome==='expired'?null:{ok:true,samples:{orders:[{code:'obsolete result'}]},issues:[]});
    await pending;
    assert.equal(t.document.querySelector('.wb-preview-data'),oldTable);
    assert.match(t.document.querySelector('.wb-preview-status').textContent,/上次结果/);
    assert.match(t.document.querySelector('.wb-preview-error').textContent,/变化|过期/);
    assert.doesNotMatch(t.document.textContent,/obsolete/);
    assert.equal(t.results.length,1);assert.equal(t.errors.length,0);
    assert.equal(t.find('重新预览').disabled,false);assert.equal(t.count().disabled,false);
    assert.equal(t.document.querySelector('.wb-preview-results').getAttribute('aria-busy'),'false');
  }
});

test('closing a refreshing dialog with cached rows keeps late responses from reopening it',async()=>{
  const gate=deferred();const t=harness({generate:()=>gate.promise,props:{initialScope:'selected',
    initialResult:{ok:true,samples:{orders:[{code:'cached'}],users:[{name:'cached user'}]},issues:[]}}});
  await t.find('users').click();const pending=t.component.refresh();await tick();
  assert.match(t.document.querySelector('.wb-preview-data').textContent,/cached user/);
  await t.find('关闭').click();gate.resolve({ok:true,samples:{users:[{name:'late'}]},issues:[]});await pending;
  assert.equal(t.document.querySelector('[role="dialog"]'),null);assert.equal(t.results.length,0);
  assert.equal(t.document.listeners.get('keydown')?.size||0,0);
});

test('closing the modal destroys a floating selector and ignores late result callbacks',async()=>{
  const gate=deferred();const t=harness({generate:()=>gate.promise});
  await t.document.querySelector('[aria-label="预览范围"]').click();
  assert.ok(t.document.querySelector('.dropdown-floating'));
  const pending=t.component.refresh();await tick();
  assert.equal(t.document.querySelector('.dropdown-floating'),null);
  t.component.dialog.close();gate.resolve({ok:true,samples:{orders:[{code:'late'}]},issues:[]});await pending;
  assert.equal(t.document.querySelector('[role="dialog"]'),null);assert.equal(t.results.length,0);
  assert.equal(t.document.listeners.get('keydown')?.size||0,0);
});

test('a changed document or null session result cannot publish stale data',async()=>{
  const gate=deferred();const t=harness({generate:()=>gate.promise});
  const pending=t.component.refresh();await tick();t.setCurrent(false);
  gate.resolve({ok:true,samples:{orders:[{code:'old'}]},issues:[]});await pending;
  assert.equal(t.results.length,0);assert.equal(t.document.querySelector('.wb-preview-data'),null);
  assert.equal(t.find('重新预览').disabled,false);
  const empty=harness({generate:async()=>null});await empty.component.refresh();
  assert.equal(empty.results.length,0);assert.match(empty.document.querySelector('.wb-preview-error').textContent,/变化|过期/);
});

test('network failures stay in the modal and controls recover for a successful retry',async()=>{
  let attempts=0;const t=harness({generate:async()=>{if(!attempts++)throw new Error('数据库暂时忙碌');return {ok:true,samples:{orders:[{code:'retry'}]},issues:[]};}});
  await t.component.refresh();assert.match(t.document.querySelector('.wb-preview-error').textContent,/数据库暂时忙碌/);
  assert.equal(t.errors.length,1);assert.equal(t.errors[0].message,'数据库暂时忙碌');
  assert.equal(t.find('重新预览').disabled,false);assert.equal(t.count().disabled,false);
  await t.component.refresh();assert.equal(t.document.querySelector('.wb-preview-error').textContent,'');
  assert.match(t.document.querySelector('.wb-preview-data').textContent,/retry/);
  assert.equal(t.errors.length,1);
});

test('invalid controls and result issues never call the network-failure callback',async()=>{
  const t=harness({generate:async()=>({ok:false,samples:{},issues:[{table:'orders',severity:'error',message:'规则尚待完善'}]})});
  t.count().value='0';await t.count().dispatchEvent('input');await t.component.refresh();
  assert.equal(t.errors.length,0);assert.equal(t.requests.length,0);
  t.count().value='10';await t.count().dispatchEvent('input');await t.component.refresh();
  assert.equal(t.errors.length,0);assert.equal(t.results.length,1);
});

test('reopening a preview makes the old pending result unable to overwrite the new dialog',async()=>{
  const gate=deferred();const t=harness({generate:()=>gate.promise});const pending=t.component.refresh();await tick();
  const newer=t.context.openDataPreview({tables,currentTable:'orders',selectedTables:['orders'],generate:async()=>({ok:true,samples:{orders:[{code:'new'}]},issues:[]})});
  await newer.refresh();gate.resolve({ok:true,samples:{orders:[{code:'old'}]},issues:[]});await pending;
  assert.equal(t.document.querySelectorAll('[role="dialog"]').length,1);
  assert.match(t.document.querySelector('.wb-preview-data').textContent,/new/);
  assert.doesNotMatch(t.document.querySelector('.wb-preview-data').textContent,/old/);
  assert.equal(t.results.length,0);
});

test('late rejection after closing or changing context never publishes a root error',async()=>{
  for(const end of ['close','change']) {
    const gate=deferred();const t=harness({generate:()=>gate.promise});const pending=t.component.refresh();await tick();
    if(end==='close')t.component.dialog.close();else t.setCurrent(false);
    gate.reject(new Error('late request failure'));await pending;
    assert.equal(t.errors.length,0);assert.equal(t.results.length,0);
    assert.doesNotMatch(t.document.textContent,/late request failure/);
  }
});

test('embedded preview stays inside its table, has a fixed scope and discards results on destroy',async()=>{
  const document=createDom(),window=new Element('window');document.createElementNS=(_,tag)=>new Element(tag);
  const ui=loadFrontend('workbench/ui.js',{document,window});
  const dropdown=loadFrontend('dropdown.js',{document,window});
  const context=loadFrontend('workbench/preview.js',{document,window,...vm.runInContext('({modal,button,valueText})',ui),createDropdown:vm.runInContext('createDropdown',dropdown)});
  const container=new Element('section');document.body.append(container);
  const gate=deferred();let calls=0;
  const preview=context.openDataPreview({tables,currentTable:'orders',selectedTables:['orders'],container,fixedScope:true,
    generate:()=>gate.promise,onResult:()=>calls++});
  assert.equal(document.querySelector('[role="dialog"]'),null);
  assert.equal(document.querySelector('[aria-label="预览范围"]'),null);
  const pending=preview.refresh();await tick();preview.destroy();
  gate.resolve({ok:true,samples:{orders:[{code:'late'}]},issues:[]});await pending;
  assert.equal(calls,0);assert.equal(container.querySelector('.wb-preview-data'),null);
});
