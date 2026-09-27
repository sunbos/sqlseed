const test = require('node:test');
const assert = require('node:assert/strict');
const {harness, plain, deferred, schema} = require('./workbench_harness.cjs');
const flush = () => new Promise(resolve => setImmediate(resolve));
const record = (target, count = 23) => ({id:'linked', name:'Linked configuration', revision:3,
  target_key:`target-${target}`, schema_hash:'schema-v1',
  document:{provider:'base',locale:'en_US',tables:[{name:'users',count,columns:[]}]},view_state:{}});
const writes = ui => ui.requests.filter(({options})=>['POST','PUT','DELETE'].includes(options.method));
async function navigate(ui, connId, hash = '#/workbench') {
  ui.leave();ui.store.connId=connId;ui.location.hash=hash;await ui.mount();
}

test('switching away and back restores each connection including unselected and invalid unsaved table drafts',async()=>{
  const ui=harness();await ui.mount();const first=ui.modelState();
  first.setCount('orders','111100');first.setCount('users','10000000000000000');
  const original={document:plain(first.document),view:plain(first.view),errors:[...first.errors]};
  await navigate(ui,'B');const second=ui.modelState();second.toggleTable('audit',true);second.setCount('audit','57');
  await navigate(ui,'A');
  assert.equal(ui.modelState(),first);assert.deepEqual(plain(first.document),original.document);
  assert.deepEqual(plain(first.view),original.view);assert.deepEqual([...first.errors],original.errors);
  assert.equal(first.selected('orders'),false);assert.equal(first.view.tableDrafts.orders.count,111100);
  await navigate(ui,'B');assert.equal(ui.modelState(),second);assert.equal(second.table('audit').count,57);
  assert.deepEqual(writes(ui),[]);
});

for(const kind of ['draft','run']) {
  test(`a foreign ${kind} link is rejected before saving and returning restores the exact current dirty session`,async()=>{
    const ui=harness();await ui.mount();const original=ui.modelState();original.setCount('orders','111100');
    const before={document:plain(original.document),view:plain(original.view),epoch:original.epoch};
    ui.routes.set(`/api/workbench/${kind==='draft'?'drafts':'runs'}/linked`,()=>record('B'));
    await navigate(ui,'A',`#/workbench?${kind}=linked`);
    assert.match(ui.root().textContent,/配置与当前数据库不匹配/);
    assert.match(ui.root().textContent,/当前数据库连接可用/);
    assert.equal(ui.button('重试'),undefined);
    assert.ok(ui.button('返回当前数据库').classList.contains('primary'));
    assert.ok(ui.root().querySelector('.wb-welcome-actions').contains(ui.button('选择对应数据库')));
    assert.equal(ui.modelState(),original);assert.deepEqual(writes(ui),[]);
    await ui.button('返回当前数据库').click();assert.equal(ui.location.hash,'#/workbench');
    await navigate(ui,'A',ui.location.hash);
    assert.equal(ui.modelState(),original);assert.deepEqual(plain(original.document),before.document);
    assert.deepEqual(plain(original.view),before.view);assert.equal(original.epoch,before.epoch);
    assert.equal(original.saved,null);assert.deepEqual(writes(ui),[]);
  });
}

test('explicit mismatch recovery keeps the link through the real picker and opens it only on the matching target',async()=>{
  const ui=harness();await ui.mount();const original=ui.modelState();original.setCount('orders','111100');
  const requested='#/workbench?draft=linked';
  ui.routes.set('/api/workbench/drafts/linked',()=>record('B'));
  ui.routes.set('/api/connections',()=>({connections:[{conn_id:'A',target:'A.db'},{conn_id:'B',target:'B.db'}]}));
  ui.routes.set('/api/connections/B/tables',()=>({target:'B.db',tables:[{name:'users'}]}));
  await navigate(ui,'A',requested);
  const events=[];ui.window.addEventListener('sqlseed:connection-changed',event=>events.push(event.detail));
  await ui.button('选择对应数据库').click();await flush();
  await ui.document.querySelectorAll('.connection-card')[1].click();
  assert.equal(ui.store.connId,'B');assert.equal(events[0].workbenchRequest,requested);
  assert.equal(ui.location.hash,requested);await navigate(ui,'B',requested);
  assert.equal(ui.modelState().schema.target_key,'target-B');assert.equal(ui.modelState().saved.id,'linked');
  assert.equal(ui.modelState().table('users').count,23);assert.deepEqual(writes(ui),[]);
  await navigate(ui,'A');assert.equal(ui.modelState(),original);assert.equal(original.view.tableDrafts.orders.count,111100);
  assert.equal(original.saved,null);assert.deepEqual(writes(ui),[]);
});

test('the first-use connection action preserves a direct document link until its matching database is selected',async()=>{
  const ui=harness({connected:false}),requested='#/workbench?draft=linked';ui.location.hash=requested;
  ui.routes.set('/api/connections',()=>({connections:[{conn_id:'B',target:'B.db'}]}));
  ui.routes.set('/api/connections/B/tables',()=>({target:'B.db',tables:[{name:'users'}]}));
  ui.routes.set('/api/workbench/drafts/linked',()=>record('B'));
  await ui.mount();assert.match(ui.root().textContent,/从数据库结构开始/);
  assert.ok(ui.root().querySelector('.wb-welcome-actions').contains(ui.button('连接数据库')));
  const events=[];ui.window.addEventListener('sqlseed:connection-changed',event=>events.push(event.detail));
  await ui.button('连接数据库').click();await flush();await ui.document.querySelector('.connection-card').click();
  assert.equal(events[0].workbenchRequest,requested);assert.equal(ui.store.connId,'B');
  await navigate(ui,'B',requested);assert.equal(ui.modelState().saved.id,'linked');assert.deepEqual(writes(ui),[]);
});

test('a correct-target document is loaded and validated before the existing dirty document is saved and replaced',async()=>{
  const ui=harness();await ui.mount();ui.modelState().setCount('orders','111100');
  const start=ui.requests.length;ui.routes.set('/api/workbench/drafts/linked',()=>record('A'));
  await navigate(ui,'A','#/workbench?draft=linked');
  const requests=ui.requests.slice(start);
  const loaded=requests.findIndex(request=>request.url==='/api/workbench/drafts/linked');
  const saved=requests.findIndex(request=>request.url==='/api/workbench/drafts'&&request.options.method==='POST');
  assert.ok(loaded>=0 && saved>loaded);assert.equal(writes(ui).length,1);
  const payload=JSON.parse(requests[saved].options.body);
  assert.equal(payload.conn_id,'A');assert.equal(payload.view_state.tableDrafts.orders.count,111100);
  assert.equal(ui.modelState().saved.id,'linked');assert.equal(ui.modelState().table('users').count,23);
});

test('a late direct-link fetch cannot save or replace either connection after switching',async()=>{
  const ui=harness();await ui.mount();const original=ui.modelState();original.setCount('orders','111100');
  const gate=deferred();ui.routes.set('/api/workbench/drafts/linked',()=>gate.promise);
  ui.leave();ui.location.hash='#/workbench?draft=linked';const pending=ui.mount();await flush();
  await navigate(ui,'B');const second=ui.modelState();second.setCount('orders','77');
  gate.resolve(record('A'));await pending;
  assert.equal(ui.modelState(),second);assert.equal(second.view.tableDrafts.orders.count,77);
  assert.doesNotMatch(ui.root().textContent,/不匹配|无法打开/);assert.deepEqual(writes(ui),[]);
  await navigate(ui,'A');assert.equal(ui.modelState(),original);assert.equal(original.saved,null);
  assert.equal(original.view.tableDrafts.orders.count,111100);
});

test('a repeated mount supersedes a pending draft response without reverting the newer loaded revision',async()=>{
  const ui=harness(),gate=deferred();let calls=0;
  ui.routes.set('/api/workbench/drafts/linked',()=>++calls===1?gate.promise:{...record('A',29),revision:4});
  ui.location.hash='#/workbench?draft=linked';const pending=ui.mount();await flush();
  await ui.context.mount();const newer=ui.modelState();
  gate.resolve(record('A',23));await pending;
  assert.equal(ui.modelState(),newer);assert.equal(newer.table('users').count,29);assert.equal(newer.saved.revision,4);
  assert.deepEqual(writes(ui),[]);
});

test('a real schema failure offers retry and recovers without creating or saving a configuration',async()=>{
  const ui=harness();let failed=true;
  ui.routes.set('/api/workbench/connections/A/schema',()=>{if(failed)throw new Error('structure unavailable');return schema('A');});
  await ui.mount();assert.match(ui.root().textContent,/无法打开工作台.*structure unavailable/);
  const actions=ui.root().querySelector('.wb-welcome-actions');
  assert.ok(actions.contains(ui.button('重试')));assert.ok(actions.contains(ui.button('选择数据库')));
  failed=false;await ui.button('重试').click();
  assert.equal(ui.root().querySelectorAll('.wb-table-entry').length,3);assert.deepEqual(writes(ui),[]);
});
