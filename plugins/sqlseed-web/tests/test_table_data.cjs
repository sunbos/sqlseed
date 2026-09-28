const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};
const pageData = (extra = {}) => ({table:'users',target_key:'target',target_label:'/tmp/app.db',dialect:'sqlite',
  columns:[{name:'id',type:'INTEGER',is_primary_key:true,nullable:false},{name:'name',type:'TEXT',nullable:true}],
  rows:[{id:11,name:'Alice'},{id:12,name:null}],total:102,limit:50,offset:0,order_by:['id'],read_at:'2026-09-10T03:00:00Z',...extra});
function harness(options={}) {
  const document=createDom(); document.createElementNS=(_,tag)=>new Element(tag);
  const requests=[]; let current=true;
  const bindings={document,AbortController,URLSearchParams,fetch:async(url,options)=>{
    requests.push({url,options});
    const body=await (options?.signal?.aborted?Promise.reject(new Error('aborted')):(optionsOverride(url,options)));
    return {ok:true,json:async()=>body};
  }};
  function optionsOverride(url,requestOptions){return options.fetch?options.fetch(url,requestOptions):pageData();}
  const ui=loadFrontend('workbench/ui.js',bindings);
  const component=loadFrontend('workbench/table-data.js',{...bindings,...vm.runInContext('({modal,button,valueText})',ui)});
  const panel=component.openTableData({connId:'conn',table:'users',targetKey:'target',targetLabel:'/tmp/app.db',isCurrent:()=>current,...options.props});
  const find=label=>document.querySelectorAll('button').find(node=>node.textContent===label);
  return {document,panel,requests,find,setCurrent:value=>{current=value;}};
}

test('shows actual database values and types, explicitly separate from preview and run-specific rows',async()=>{
  const t=harness();await t.panel.ready;
  assert.match(t.document.textContent,/数据库当前数据/);
  assert.match(t.document.textContent,/包含.*原有.*本次.*后续/);
  assert.match(t.document.textContent,/Alice/);
  assert.match(t.document.querySelector('thead').textContent,/INTEGER/);
  assert.match(t.document.querySelector('tbody').textContent,/11Alice12NULL/);
  assert.match(t.document.textContent,/2026/);
  assert.equal(t.requests[0].url,'/api/workbench/connections/conn/tables/users/data?limit=50&offset=0');
  assert.ok(t.requests.every(r=>!r.options.method || r.options.method==='GET'));
});

test('paginates with server counts and refreshes the current page',async()=>{
  const t=harness({fetch:url=>pageData({offset:Number(new URL(url,'http://test').searchParams.get('offset'))})});await t.panel.ready;
  assert.equal(t.find('上一页').disabled,true);assert.equal(t.find('下一页').disabled,false);
  await t.find('下一页').click();assert.match(t.requests.at(-1).url,/offset=50/);
  assert.equal(t.find('上一页').disabled,false);
  await t.find('刷新数据').click();assert.match(t.requests.at(-1).url,/offset=50/);
  await t.find('下一页').click();assert.match(t.requests.at(-1).url,/offset=100/);
  assert.equal(t.find('下一页').disabled,true);
});

test('keeps schema headers for empty tables and explains tables without a stable key',async()=>{
  const t=harness({fetch:()=>pageData({rows:[],total:0,order_by:[]})});await t.panel.ready;
  assert.match(t.document.querySelector('thead').textContent,/nameTEXT/);
  assert.match(t.document.textContent,/暂无记录/);
  assert.match(t.document.textContent,/没有主键/);
  assert.equal(t.find('下一页').disabled,true);
});

test('reads only a connection matched to the run and binds every page request to that run',async()=>{
  const t=harness({props:{connId:null,runId:'run-1'},fetch:url=>url.endsWith('/data-connections')?
    {target_key:'target',target_label:'/tmp/app.db',connections:[{conn_id:'matched',target_label:'/tmp/app.db'}]}:pageData()});
  await t.panel.ready;
  assert.equal(t.requests[0].url,'/api/workbench/runs/run-1/data-connections');
  assert.equal(t.requests[1].url,'/api/workbench/connections/matched/tables/users/data?limit=50&offset=0&run_id=run-1');
});

test('a run without a matching connection cannot read from an unrelated active database',async()=>{
  const t=harness({props:{connId:null,runId:'run-1'},fetch:()=>({target_key:'target',target_label:'/tmp/app.db',connections:[]})});
  await t.panel.ready;
  assert.equal(t.requests.length,1);assert.match(t.document.textContent,/连接.*相同数据库/);
  assert.equal(t.document.querySelector('table'),null);
});

test('refresh failures retain old rows with a visible error and allow an explicit retry',async()=>{
  let fails=false;
  const t=harness({fetch:()=>{if(fails)throw new Error('连接忙碌');return pageData();}});await t.panel.ready;
  fails=true;await t.find('刷新数据').click();
  assert.match(t.document.textContent,/Alice/);assert.match(t.document.querySelector('[role="alert"]').textContent,/连接忙碌/);
  assert.equal(t.find('刷新数据').disabled,false);
  fails=false;await t.find('刷新数据').click();assert.equal(t.document.querySelector('[role="alert"]').textContent,'');
});

test('closing cancels the request and prevents a late response from recreating data',async()=>{
  const gate=deferred();const t=harness({fetch:()=>gate.promise});
  t.panel.close();gate.resolve(pageData());await t.panel.ready;
  assert.equal(t.requests[0].options.signal.aborted,true);
  assert.equal(t.document.querySelector('[role="dialog"]'),null);
});

test('read-only data dialog has one explicit close control and cancels from its header',async()=>{
  const gate=deferred();const t=harness({fetch:()=>gate.promise});
  assert.equal(t.find('关闭'),undefined);
  const close=t.document.querySelector('button[aria-label="关闭"]');
  assert.ok(close);
  await close.click();gate.resolve(pageData());await t.panel.ready;
  assert.equal(t.requests[0].options.signal.aborted,true);
  assert.equal(t.document.querySelector('[role="dialog"]'),null);
});

test('typed timestamps use preview ISO spelling and preserve database text in a native disclosure',async()=>{
  const raw='2014-11-05 23:18:40.000000';
  const t=harness({fetch:()=>pageData({columns:[{name:'created_at',type:'DATETIME'}],rows:[{created_at:raw}]})});
  await t.panel.ready;
  const details=t.document.querySelector('tbody details');
  assert.equal(Boolean(details.open),false);
  assert.equal(details.querySelector('summary').textContent,'2014-11-05T23:18:40');
  assert.match(details.querySelector('summary').getAttribute('aria-label'),/查看数据库原值/);
  assert.equal(details.querySelector('pre').textContent,raw);
  assert.equal(t.document.querySelector('tbody').querySelectorAll('details').length,1);
});

test('timestamp precision and timezone survive display normalization without Date conversion',async()=>{
  const values=[
    ['TIMESTAMP(6) WITH TIME ZONE','2026-09-27 01:02:03.123456+08:00','2026-09-27T01:02:03.123456+08:00'],
    ['TIMESTAMP WITHOUT TIME ZONE','2026-09-27T01:02:03.000001','2026-09-27T01:02:03.000001'],
    ['TIME WITH TIME ZONE','01:02:03.000000-00:00','01:02:03-00:00'],
    ['TIME(6)','01:02:03.123456','01:02:03.123456'],
    ['TIMESTAMP','2026-09-27T01:02:03.000000Z','2026-09-27T01:02:03Z'],
    ['TIMESTAMP','2026-09-27 01:02:03.120000+05:30:20.000003','2026-09-27T01:02:03.120000+05:30:20.000003']
  ];
  for(const [type,raw,expected] of values){
    const t=harness({fetch:()=>pageData({columns:[{name:'stamp',type}],rows:[{stamp:raw}]})});await t.panel.ready;
    const cell=t.document.querySelector('tbody td');
    assert.equal(cell.querySelector('summary')?.textContent || cell.textContent,expected,type);
    if(raw!==expected) assert.equal(cell.querySelector('pre').textContent,raw,type);
    t.panel.close();
  }
});

test('date-looking text, unsupported types, NULL and nonstandard database values remain exact',async()=>{
  const values=[
    ['TEXT','2014-11-05 23:18:40.000000'],
    ['VARCHAR(80)','2014-11-05T23:18:40.000000Z'],
    ['JSON',{created_at:'2014-11-05 23:18:40.000000'}],
    ['DATE','2014-11-05'],
    ['DATETIME',null],
    ['DATETIME','infinity'],
    ['DATETIME','2014-11-05 24:00:00.000000'],
    ['TIME',123456],
    ['','2014-11-05 23:18:40.000000']
  ];
  for(const [type,raw] of values){
    const t=harness({fetch:()=>pageData({columns:[{name:'value',type}],rows:[{value:raw}]})});await t.panel.ready;
    const cell=t.document.querySelector('tbody td');
    const expected=raw===null?'NULL':typeof raw==='object'?JSON.stringify(raw):String(raw);
    assert.equal(cell.textContent,expected,type);
    assert.equal(cell.querySelector('details'),null,type);
    t.panel.close();
  }
});

test('long values remain accessible in full and untrusted HTML is only text',async()=>{
  const value='<script>payload</script>'+ '长文本'.repeat(100);
  const t=harness({fetch:()=>pageData({rows:[{id:11,name:value}]})});await t.panel.ready;
  assert.equal(t.document.querySelector('script'),null);
  assert.ok(t.document.querySelector('details').textContent.includes(value));
});

test('a mismatched target response is never displayed',async()=>{
  const t=harness({fetch:()=>pageData({target_key:'other',rows:[{id:99,name:'Wrong database'}]})});await t.panel.ready;
  assert.doesNotMatch(t.document.textContent,/Wrong database/);
  assert.match(t.document.querySelector('[role="alert"]').textContent,/目标/);
});

test('current-data translations preserve row values, timestamp precision and expanded raw-value state', async () => {
  const raw = '2026-09-26 12:34:56.120000+08:00';
  const t = harness({fetch:()=>pageData({columns:[{name:'用户时间',type:'DATETIME'}],rows:[{'用户时间':raw}],total:1,order_by:[]})});
  await t.panel.ready;
  const ui = require('./frontend_helpers.cjs').loadI18n({document:t.document});
  const dialog = t.document.querySelector('[role="dialog"]'), table = t.document.querySelector('table');
  const details = t.document.querySelector('.wb-table-data-temporal'), summary = details.querySelector('summary');
  details.open = true;
  const requests = t.requests.length;
  ui.setLanguage('en');
  assert.equal(t.document.querySelector('[role="dialog"]'), dialog);
  assert.equal(t.document.querySelector('table'), table);
  assert.match(dialog.textContent, /Current database data/);
  assert.match(summary.getAttribute('aria-label'), /expand to view the raw database value/);
  assert.equal(summary.textContent, '2026-09-26T12:34:56.120000+08:00');
  assert.equal(details.querySelector('pre').textContent, raw); assert.equal(details.open, true);
  assert.match(table.querySelector('thead').textContent, /用户时间DATETIME/);
  assert.equal(t.requests.length, requests);
  assert.equal(ui.missingMessages().length, 0);
  t.panel.close();
});
