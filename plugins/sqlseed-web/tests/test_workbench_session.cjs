const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function create(request) {
  const ctx=vm.createContext({structuredClone,JSON,Map,Set});
  for(const file of ['model','session']) vm.runInContext(fs.readFileSync(path.join(__dirname,`../src/sqlseed_web/static/js/workbench/${file}.js`),'utf8').replace(/^import .*;\n/gm,'').replace(/^export /gm,''),ctx);
  ctx.request=request;
  return vm.runInContext(`new WorkbenchSession('connection-A', {schema_hash:'s1',tables:[{name:'users'}]}, request)`,ctx);
}
test('save/check/run bind one immutable revision to the captured connection',async()=>{
  const calls=[];
  const s=create(async(path,body,method)=>{
    calls.push({path,body,method});
    if(path.endsWith('/drafts'))return {...body,id:'draft1',revision:1};
    if(path.endsWith('/check'))return {ok:true,config_hash:'hash1',schema_hash:'s1'};
    return {id:'run1',status:'queued'};
  });
  s.model.toggleTable('users',true);
  await assert.rejects(()=>s.run(),/保存/);
  await s.save('one'); await s.check(); const run=await s.run();
  assert.equal(run.id,'run1');
  assert.deepEqual(JSON.parse(JSON.stringify(calls.at(-1).body)),{conn_id:'connection-A',draft_id:'draft1',revision:1,schema_hash:'s1',config_hash:'hash1'});
  s.model.setCount('users','4');
  await assert.rejects(()=>s.run(),/保存/);
});
test('a preview completing after edit cannot replace current samples or authorize execution',async()=>{
  let resolve;
  const s=create(()=>new Promise(r=>{resolve=r}));
  const pending=s.check(true);
  s.model.setCount('users','22');
  resolve({ok:true,samples:{users:[{id:9}]}});
  assert.equal(await pending,null);
  assert.equal(s.model.check,null);
});
test('opening a draft requires same physical target and latest schema; does not silently rewrite snapshot',()=>{
  const s=create(async()=>({})); s.model.schema.target_key='dbA';
  assert.throws(()=>s.open({target_key:'dbB',document:{tables:[]}}),/数据库/);
  s.open({id:'d',revision:2,target_key:'dbA',schema_hash:'old',document:{tables:[{name:'users',count:4}]}});
  assert.equal(s.model.saved.revision,2);
  assert.equal(s.model.dirty,true);
  assert.equal(s.model.check,null);
});

test('opening an old URI identity cannot authorize another target even if an alias is supplied',()=>{
  const s=create(async()=>({}));
  s.model.schema.target_key='canonical-file';
  s.model.schema.target_key_aliases=['exact-original-uri'];
  const draft={id:'legacy',revision:4,target_key:'exact-original-uri',schema_hash:'s1',document:{tables:[{name:'users',count:4}]}};
  assert.throws(()=>s.open(draft),/数据库/);
  assert.equal(s.model.schema.target_key,'canonical-file');
  assert.equal(s.model.saved,null);
  assert.throws(()=>s.open({...draft,target_key:'different-database'}),/数据库/);
});

test('checks finishing after opening another document cannot authorize its matching epoch', async () => {
  let resolve;
  const session = create(() => new Promise(done => {resolve = done;}));
  const previous = session.model;
  const pending = session.check();
  session.open({id: 'next', name: 'Next', revision: 1, schema_hash: 's1', document: {tables: [{name: 'users', count: 42, columns: []}]}});
  assert.equal(session.model.epoch, previous.epoch);
  resolve({ok: true, config_hash: 'previous-document'});
  assert.equal(await pending, null);
  assert.equal(session.model.check, null);
  assert.equal(session.model.canRun(), false);
});

test('a save finishing after opening another document updates only the original model', async () => {
  let resolve;
  const session = create(() => new Promise(done => {resolve = done;}));
  session.model.toggleTable('users', true);
  const previous = session.model;
  const pending = session.save('Previous');
  session.open({id: 'next', name: 'Next', revision: 3, schema_hash: 's1', document: {tables: [{name: 'users', count: 42, columns: []}]}});
  resolve({id: 'previous', name: 'Previous', revision: 2, document: previous.document});
  await pending;
  assert.equal(session.model.saved.id, 'next');
  assert.equal(session.model.saved.revision, 3);
  assert.equal(session.name, 'Next');
  assert.equal(previous.saved.id, 'previous');
  assert.equal(session.model.table('users').count, 42);
});

test('saving a captured name never overwrites a newer name edit while the request is pending', async () => {
  let resolve;
  const session = create(() => new Promise(done => {resolve = done;}));
  const pending = session.save('Earlier name');
  session.name = 'Newer name'; session.model.touch();
  resolve({id: 'saved', name: 'Earlier name', revision: 1, document: session.model.document});
  await pending;
  assert.equal(session.name, 'Newer name');
  assert.equal(session.model.dirty, true);
});

test('previewing an unselected table sends its complete temporary config without changing selection or authorization', async () => {
  const calls = [];
  const session = create(async (path, body) => {
    calls.push({path, body});
    return {ok: true, config_hash: 'preview-only', samples: {users: [{amount: 7}]}, issues: [{table: 'users', severity: 'warning', message: 'preview warning'}]};
  });
  session.model.schema.tables.push({name: 'orders'});
  session.model.toggleTable('orders', true);
  session.model.document.associations = [{name: 'preserved association'}];
  session.model.setColumn('users', 'amount', {generator: 'integer', params: {min_value: 7, max_value: 7}, constraints: {unique: true}});
  session.model.putTable({...session.model.table('users'), seed: 42, locale: 'zh_CN'});
  const model = session.model, epoch = model.epoch;
  model.markSaved({id: 'saved', revision: 2}, epoch);
  model.acceptCheck({ok: true, config_hash: 'selected-orders-only'}, epoch);
  const check = model.check;
  const before = JSON.stringify(model.payload('before'));
  const result = await session.previewTable('users');
  assert.equal(calls[0].path, '/api/workbench/preview');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].body.document.tables.map(table => table.name))), ['users']);
  const temporary = calls[0].body.document.tables[0];
  assert.equal(temporary.seed, 42); assert.equal(temporary.locale, 'zh_CN');
  assert.equal(temporary.columns[0].params.min_value, 7);
  assert.equal(calls[0].body.document.associations[0].name, 'preserved association');
  assert.equal(JSON.stringify(model.payload('before')), before);
  assert.equal(model.selected('users'), false);
  assert.equal(model.epoch, epoch); assert.equal(model.dirty, false);
  assert.equal(model.check, check); assert.equal(model.canRun(), true);
  assert.equal(model.samples.users[0].amount, 7);
  assert.equal(model.previewIssues[0].message, 'preview warning');
  result.samples.users[0].amount = 999;
  assert.equal(model.samples.users[0].amount, 7, 'samples own an immutable response copy');
});

test('table preview never authorizes execution and edits discard its pending snapshot', async () => {
  let resolve, request;
  const session = create((path, body) => {request = body; return new Promise(done => {resolve = done;});});
  session.model.setColumn('users', 'amount', {generator: 'integer', params: {min_value: 3}});
  const pending = session.previewTable('users');
  session.model.setColumn('users', 'amount', {generator: 'integer', params: {min_value: 9}});
  assert.equal(request.document.tables[0].columns[0].params.min_value, 3);
  resolve({ok: true, config_hash: 'temporary', samples: {users: [{amount: 3}]}, issues: []});
  assert.equal(await pending, null);
  assert.equal(session.model.check, null); assert.equal(session.model.canRun(), false);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.samples)), {});
});

test('table preview results are discarded when a different document opens at the same epoch', async () => {
  let resolve;
  const session = create(() => new Promise(done => {resolve = done;}));
  const pending = session.previewTable('users');
  session.open({id: 'other', revision: 1, schema_hash: 's1', document: {tables: []}});
  resolve({ok: true, samples: {users: [{amount: 3}]}, issues: []});
  assert.equal(await pending, null);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.samples)), {});
  assert.equal(session.model.check, null);
});

test('previewing an already selected table keeps one copy and does not set execution check', async () => {
  let request;
  const session = create(async (path, body) => {request = body; return {ok: true, samples: {users: [{id: 1}]}};});
  session.model.toggleTable('users', true);
  await session.previewTable('users');
  assert.equal(request.document.tables.length, 1);
  assert.equal(session.model.check, null);
  assert.equal(session.model.canRun(), false);
});

test('newer table previews win over older responses from the same document epoch', async () => {
  const resolvers = [];
  const session = create(() => new Promise(resolve => {resolvers.push(resolve);}));
  session.model.schema.tables.push({name: 'orders'});
  const older = session.previewTable('users');
  const newer = session.previewTable('orders');
  resolvers[1]({ok: true, samples: {orders: [{id: 2}]}, issues: []});
  await newer;
  resolvers[0]({ok: true, samples: {users: [{id: 1}]}, issues: []});
  assert.equal(await older, null);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.samples)), {orders: [{id: 2}]});
});

test('checking dependencies after a table preview preserves its values and preview warnings', async () => {
  const session = create(async path => path.endsWith('/preview')
    ? {ok: true, schema_hash: 's1', samples: {users: [{id: 7}]}, issues: [{code: 'preview_requires_parent', severity: 'warning'}]}
    : {ok: true, schema_hash: 's1', config_hash: 'checked', samples: {}, issues: []});
  await session.previewTable('users');
  const before = JSON.stringify({samples: session.model.samples, issues: session.model.previewIssues});
  const check = await session.check(false);
  assert.equal(check.config_hash, 'checked');
  assert.equal(JSON.stringify({samples: session.model.samples, issues: session.model.previewIssues}), before);
});

test('full preview then validation then an empty failing preview uses the operation rather than sample shape', async () => {
  const responses = [
    {ok: true, schema_hash: 's1', samples: {users: [{id: 7}]}, issues: []},
    {ok: true, schema_hash: 's1', config_hash: 'checked', samples: {}, issues: []},
    {ok: false, schema_hash: 's1', samples: {}, issues: [{code: 'generation_invalid', table: 'users'}]},
    {ok: true, schema_hash: 's1', samples: {}, issues: []},
  ];
  const session = create(async () => responses.shift());
  await session.check(true);
  await session.check(false);
  assert.equal(session.model.samples.users[0].id, 7);
  await session.check(true);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.samples)), {});
  assert.equal(session.model.previewIssues[0].code, 'generation_invalid');
  await session.check(true);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.previewIssues)), []);
});

test('a fresh server schema mismatch remains visible and prevents running the saved document', async () => {
  const calls = [];
  const session = create(async (path, body) => {
    calls.push({path, body});
    return {ok: false, schema_hash: 'changed-on-server', samples: {}, issues: [{code: 'schema_changed', severity: 'error'}]};
  });
  session.model.toggleTable('users', true);
  session.model.markSaved({id: 'draft', revision: 1}, session.model.epoch);
  await session.check(false);
  assert.equal(calls[0].body.schema_hash, 's1');
  assert.equal(session.model.check.issues[0].code, 'schema_changed');
  assert.equal(session.model.schema.schema_hash, 's1', 'checking never replaces the inspected schema snapshot');
  await assert.rejects(() => session.run(), /保存当前配置并完成依赖检查/);
  assert.equal(calls.length, 1);
});

test('table preview includes selected ancestors but excludes unrelated tables and merges existing samples',async()=>{
  let request;
  const s=create(async(path,body)=>{request=body;return {ok:true,samples:{orders:[{id:4}]},issues:[]};});
  s.model.schema.tables.push({name:'orders'},{name:'audit'},{name:'tenants'});
  s.model.schema.edges=[{source:'users',target:'orders'},{source:'tenants',target:'users'}];
  for(const name of ['users','audit','tenants'])s.model.toggleTable(name,true);
  s.model.samples={audit:[{event:'preserved'}],orders:[{id:1}]};
  const before=JSON.stringify(s.model.document);
  await s.previewTable('orders');
  assert.deepEqual(JSON.parse(JSON.stringify(request.document.tables.map(t=>t.name))),['users','tenants','orders']);
  assert.equal(JSON.stringify(s.model.document),before);
  assert.equal(s.model.samples.audit[0].event,'preserved');
  assert.equal(s.model.samples.orders[0].id,4);
  assert.equal(s.model.check,null);
});

test('table preview stops execution ancestry at an unselected source even when its ancestor is selected', async () => {
  let request;
  const s=create(async(path,body)=>{request=body;return {ok:true,samples:{orders:[{id:4}]},issues:[]};});
  s.model.schema.tables.push({name:'orders'},{name:'tenants'});
  s.model.schema.edges=[{source:'users',target:'orders'},{source:'tenants',target:'users'}];
  s.model.toggleTable('orders',true);s.model.toggleTable('tenants',true);
  s.model.setColumn('tenants','invalid',{generator:'unknown-generator'});
  const before=JSON.stringify(s.model.document);
  await s.previewTable('orders');
  assert.deepEqual(JSON.parse(JSON.stringify(request.document.tables.map(t=>t.name))),['orders']);
  assert.equal(JSON.stringify(s.model.document),before);
  assert.equal(s.model.selected('users'),false);
  assert.equal(s.model.check,null);
});

test('association ancestry follows selected parents and also stops at an existing-only source', async () => {
  const calls=[];
  const s=create(async(path,body)=>{calls.push(body);return {ok:true,samples:{orders:[{id:4}]},issues:[]};});
  s.model.schema.tables.push({name:'orders'},{name:'tenants'});
  s.model.document.associations=[
    {name:'ownership',source_table:'users',source_column:'id',target_tables:['orders'],column_name:'user_id',strategy:'shared_pool'},
    {name:'tenant',source_table:'tenants',source_column:'id',target_tables:['users'],column_name:'tenant_id',strategy:'shared_pool'},
  ];
  s.model.toggleTable('tenants',true);
  const associations=JSON.stringify(s.model.document.associations);
  await s.previewTable('orders');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].document.tables.map(t=>t.name))),['orders']);
  assert.equal(JSON.stringify(calls[0].document.associations),associations);
  s.model.toggleTable('users',true);
  await s.previewTable('orders');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].document.tables.map(t=>t.name))),['tenants','users','orders']);
  assert.equal(JSON.stringify(calls[1].document.associations),associations);
});

test('a newer selected-table preview supersedes a pending local preview', async () => {
  const resolvers=[];
  const s=create(()=>new Promise(resolve=>resolvers.push(resolve)));
  s.model.toggleTable('users',true);
  const older=s.previewTable('users');
  const newer=s.check(true);
  resolvers[1]({ok:true,config_hash:'newest',samples:{users:[{id:2}]},issues:[]});
  await newer;
  resolvers[0]({ok:true,config_hash:'old-local',samples:{users:[{id:1}]},issues:[]});
  assert.equal(await older,null);
  assert.equal(s.model.samples.users[0].id,2);
  assert.equal(s.model.check.config_hash,'newest');
});

test('a newer local preview supersedes pending selected-table preview without authorizing its temporary document', async () => {
  const resolvers=[];
  const s=create(()=>new Promise(resolve=>resolvers.push(resolve)));
  s.model.toggleTable('users',true);
  const older=s.check(true);
  const newer=s.previewTable('users');
  resolvers[1]({ok:true,config_hash:'local-only',samples:{users:[{id:2}]},issues:[]});
  await newer;
  resolvers[0]({ok:true,config_hash:'old-global',samples:{users:[{id:1}]},issues:[]});
  assert.equal(await older,null);
  assert.equal(s.model.samples.users[0].id,2);
  assert.equal(s.model.check,null);
  assert.equal(s.model.canRun(),false);
});

test('overlapping selected-table previews keep only the newest sample and check result', async () => {
  const resolvers=[];
  const s=create(()=>new Promise(resolve=>resolvers.push(resolve)));
  const older=s.check(true),newer=s.check(true);
  resolvers[1]({ok:true,config_hash:'newest',samples:{users:[{id:2}]},issues:[]});await newer;
  resolvers[0]({ok:false,config_hash:'old',samples:{},issues:[{severity:'error',message:'old failure'}]});
  assert.equal(await older,null);
  assert.equal(s.model.samples.users[0].id,2);
  assert.equal(s.model.check.config_hash,'newest');
});

for(const change of ['delete','rename']) {
  test(`a late save cannot restore ${change==='delete'?'a deleted identity':'an older renamed revision'}`,async()=>{
    let finish;const session=create(()=>new Promise(resolve=>finish=resolve));
    session.model.toggleTable('users',true);session.model.markSaved({id:'draft',name:'Before',revision:1},session.model.epoch);
    session.model.setCount('users','12');const pending=session.save('Before');
    session.model.lifecycleVersion++;
    if(change==='delete'){session.model.saved=null;session.model.savedEpoch=-1;}
    else {session.model.saved={id:'draft',name:'Renamed',revision:3};session.name='Renamed';}
    finish({id:'draft',name:'Before',revision:2});
    await assert.rejects(pending,/删除或重命名/);
    if(change==='delete')assert.equal(session.model.saved,null);
    else {assert.equal(session.model.saved.revision,3);assert.equal(session.name,'Renamed');}
    assert.equal(session.model.dirty,true);assert.equal(session.saving,false);assert.equal(session.model.table('users').count,12);
  });
}

for (const scope of ['current', 'selected']) {
  for (const count of [1, 10, 100]) {
    test(`${scope} preview passes ${count} as a sample limit without changing configured row counts`, async () => {
      let request;
      const session = create(async (path, body) => {
        request = {path, body};
        return {ok: true, samples: {users: [{id: 7}]}, issues: []};
      });
      session.model.schema.tables.push({name: 'orders'});
      session.model.toggleTable('users', true);
      session.model.toggleTable('orders', true);
      session.model.setCount('users', '2');
      session.model.setCount('orders', '250');
      session.model.markSaved({id: 'saved', revision: 3}, session.model.epoch);
      const before = JSON.stringify(session.model.payload('snapshot'));
      const epoch = session.model.epoch;
      if (scope === 'current') await session.previewTable('users', count);
      else await session.check(true, count);
      assert.equal(request.path, '/api/workbench/preview');
      assert.equal(request.body.count, count);
      assert.equal(request.body.document.tables.find(table => table.name === 'users').count, 2);
      if (scope === 'selected') assert.equal(request.body.document.tables.find(table => table.name === 'orders').count, 250);
      assert.equal(JSON.stringify(session.model.payload('snapshot')), before);
      assert.equal(session.model.epoch, epoch);
      assert.equal(session.model.dirty, false);
      assert.equal(session.model.samples.users.length, 1, 'accept only returned rows, without padding to the requested limit');
    });
  }

  test(`${scope} preview rejects invalid sample limits before making a request or replacing samples`, async () => {
    const requests = [];
    const session = create(async (path, body) => {requests.push({path, body}); return {ok: true, samples: {}};});
    session.model.toggleTable('users', true);
    session.model.samples = {users: [{id: 7}]};
    const before = JSON.stringify(session.model.payload('snapshot'));
    for (const count of [0, -1, 101, 1.5, NaN, Infinity, '10', null, true, {}, []]) {
      const action = scope === 'current' ? () => session.previewTable('users', count) : () => session.check(true, count);
      await assert.rejects(action, /1.*100.*整数/);
    }
    assert.equal(requests.length, 0);
    assert.equal(session.previewSequence, 0);
    assert.equal(session.model.samples.users[0].id, 7);
    assert.equal(JSON.stringify(session.model.payload('snapshot')), before);
  });
}

test('existing selected-table preview, current-table preview, and dependency checks keep the default limit of three', async () => {
  const requests = [];
  const session = create(async (path, body) => {requests.push({path, body}); return {ok: true, samples: {}};});
  session.model.toggleTable('users', true);
  await session.check(true);
  await session.previewTable('users');
  await session.check();
  assert.deepEqual(requests.map(({path, body}) => [path, body.count]), [
    ['/api/workbench/preview', 3], ['/api/workbench/preview', 3], ['/api/workbench/check', 3],
  ]);
});

test('changing the preview limit keeps only the newer response at the same document epoch', async () => {
  const requests = [];
  const session = create((path, body) => new Promise(resolve => requests.push({body, resolve})));
  session.model.toggleTable('users', true);
  const older = session.previewTable('users', 100);
  const newer = session.check(true, 1);
  assert.deepEqual(requests.map(({body}) => body.count), [100, 1]);
  requests[1].resolve({ok: true, config_hash: 'latest', samples: {users: [{id: 1}]}});
  await newer;
  requests[0].resolve({ok: true, samples: {users: [{id: 2}, {id: 3}]}});
  assert.equal(await older, null);
  assert.deepEqual(JSON.parse(JSON.stringify(session.model.samples)), {users: [{id: 1}]});
});
