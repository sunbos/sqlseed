const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => {resolve = done; reject = fail;});
  return {promise, resolve, reject};
};
const flush = () => new Promise(resolve => setImmediate(resolve));
const record = (id, status = 'done', extra = {}) => ({id, name: `Run ${id}`, status,
  target_key: 'target', target_label: 'example.db', revision: 2, schema_hash: 'schema', rows_inserted: 7,
  row_counts_exact: true, tables: [{name: 'users', status, requested_count: 10, rows_inserted: 7, errors: []}],
  document: {provider: 'base', locale: 'en_US', tables: [{name: 'users', count: 10, columns: []}]}, ...extra});

function harness({hash = '#/runs', runs = [record('A', 'running'), record('B')]} = {}) {
  const document = createDom();
  document.createElementNS = (_, tag) => new Element(tag);
  const requests = [], routes = new Map(), timers = new Map(), downloads = [];
  let timerId = 0;
  const location = {hash};
  class BrowserURL extends URL {
    static createObjectURL(blob) {downloads.push(blob); return `blob:export-${downloads.length}`;}
    static revokeObjectURL() {}
  }
  const bindings = {
    document, location, URLSearchParams, URL: BrowserURL, AbortController,
    setTimeout(callback, delay) {const id = ++timerId; timers.set(id, {callback, delay}); return id;},
    clearTimeout(id) {timers.delete(id);},
    fetch: async url => {
      requests.push(url);
      let result;
      if (routes.has(url)) result = await routes.get(url)();
      else if (url === '/api/workbench/runs') result = {runs};
      else result = runs.find(run => url === `/api/workbench/runs/${encodeURIComponent(run.id)}`);
      if (!result) throw new Error(`Unexpected request ${url}`);
      return {ok: true, json: async () => result};
    },
  };
  const ui = loadFrontend('workbench/ui.js', bindings);
  const recovery=loadFrontend('workbench/recovery.js',bindings);
  const tableData=loadFrontend('workbench/table-data.js',{...bindings,...vm.runInContext('({modal,button,valueText})',ui)});
  const context = loadFrontend('pages/runs.js', {...bindings,
    ...vm.runInContext('({button, download, valueText})', ui),
    ...vm.runInContext('({remainingRun})',recovery),
    ...vm.runInContext('({openTableData})',tableData),
  });
  let root;
  const mount = async () => {root = context.render(); document.body.append(root); await context.mount();};
  const leave = () => {context.unmount(); root?.remove();};
  const refresh = () => root.querySelectorAll('button').find(button => button.textContent === '刷新').click();
  const select = async id => {
    const card = root.querySelectorAll('.wb-run-card').find(card => card.querySelector('strong').textContent === `Run ${id}`);
    assert.ok(card); await card.click(); await flush();
  };
  const fire = async () => {
    assert.equal(timers.size, 1, 'expected exactly one polling timer');
    const [id, timer] = timers.entries().next().value; timers.delete(id);
    await timer.callback();
  };
  return {document, location, requests, routes, timers, downloads, mount, leave, refresh, select, fire, root: () => root,
    title: () => root.querySelector('.wb-run-detail').querySelector('h2')?.textContent};
}

test('mount renders actual run totals, table outcomes and immutable snapshot links', async () => {
  const ui = harness({hash: '#/runs?id=B'}); await ui.mount();
  assert.equal(ui.title(), 'Run B');
  assert.equal(ui.root().querySelectorAll('.wb-run-card').length, 2);
  assert.match(ui.root().querySelector('.wb-run-detail').textContent, /7 行已提交/);
  assert.match(ui.root().querySelector('pre').textContent, /"count": 10/);
  assert.equal(ui.root().querySelectorAll('a').find(anchor => anchor.textContent === '从此快照新建配置').getAttribute('href'), '#/workbench?run=B');
  assert.equal([...ui.timers.values()][0].delay, 1200);
  assert.ok(ui.root().classList.contains('page'));
  assert.equal(ui.root().querySelector('h1').textContent, '运行记录');
});

test('incomplete counting is presented as confirmed minimum even without a server restart', async () => {
  const run = record('A', 'error', {count_complete: false, tables: [
    {name: 'users', status: 'error', requested_count: 10, rows_inserted: null, errors: ['connection lost']},
  ]});
  const ui = harness({runs: [run]}); await ui.mount();
  const detail = ui.root().querySelector('.wb-run-detail').textContent;
  assert.match(detail, /至少 7/);
  assert.match(detail, /无法确认最后一批/);
  assert.doesNotMatch(detail, /服务中断后/);
});

test('no records produces an empty state and no polling loop', async () => {
  const ui = harness({runs: []}); await ui.mount();
  assert.match(ui.root().textContent, /还没有运行记录/);
  assert.equal(ui.root().querySelectorAll('.wb-run-card').length, 0);
  assert.equal(ui.timers.size, 0);
  const empty = ui.root().querySelector('.run-empty');
  assert.ok(empty);
  assert.match(empty.textContent, /生成后会在这里保留配置版本、执行结果与实际写入数量/);
  assert.equal(empty.querySelector('a').getAttribute('href'), '#/workbench');
  assert.equal(empty.querySelector('a').textContent, '返回工作台');
  assert.equal(ui.root().querySelector('.runs-workspace').children.length, 1);
  assert.equal(ui.root().querySelector('.run-list'), null);
  assert.equal(ui.root().querySelector('.wb-run-detail'), null);
  assert.doesNotMatch(ui.root().textContent, /选择一条运行记录/);
});

test('refreshing the empty history restores both columns when a record becomes available', async () => {
  const ui = harness({runs: []}); await ui.mount();
  const run = record('new');
  ui.routes.set('/api/workbench/runs', () => [run]);
  ui.routes.set('/api/workbench/runs/new', () => run);
  await ui.refresh();
  assert.equal(ui.root().querySelector('.run-empty'), null);
  assert.ok(ui.root().querySelector('.run-list'));
  assert.equal(ui.title(), 'Run new');
  assert.equal(ui.root().querySelector('.runs-workspace').children.length, 2);
  ui.routes.set('/api/workbench/runs', () => []);
  await ui.refresh();
  assert.ok(ui.root().querySelector('.run-empty'));
  assert.equal(ui.root().querySelector('.wb-run-detail'), null);
});

test('network failure retains the last result and retries without reporting task failure', async () => {
  const ui = harness(); await ui.mount();
  ui.routes.set('/api/workbench/runs', () => {throw new Error('offline');});
  await ui.fire();
  assert.equal(ui.title(), 'Run A');
  assert.match(ui.root().querySelector('.wb-notice').textContent, /不代表任务已失败/);
  assert.equal([...ui.timers.values()][0].delay, 5000);
  ui.routes.delete('/api/workbench/runs');
  await ui.fire();
  assert.equal(ui.root().querySelector('.wb-notice').textContent, '');
  assert.equal(ui.timers.size, 1);
});

test('unmount stops polling and ignores a detail response already in flight', async () => {
  const ui = harness(); await ui.mount();
  const gate = deferred(); ui.routes.set('/api/workbench/runs/A', () => gate.promise);
  const pending = ui.refresh(); await flush();
  ui.leave();
  gate.resolve(record('A', 'done', {name: 'Late A'})); await pending;
  assert.equal(ui.title(), 'Run A');
  assert.equal(ui.timers.size, 0);
});

test('switching selected run ignores the previous run detail response', async () => {
  const ui = harness(); await ui.mount();
  const gate = deferred(); ui.routes.set('/api/workbench/runs/A', () => gate.promise);
  const pending = ui.refresh(); await flush();
  await ui.select('B'); assert.equal(ui.title(), 'Run B');
  gate.resolve(record('A', 'done')); await pending;
  assert.equal(ui.title(), 'Run B');
  assert.equal(ui.root().querySelector('.wb-run-card.active').querySelector('strong').textContent, 'Run B');
  assert.equal(ui.timers.size, 1);
});

test('an older selection failure cannot display an error or add a second polling timer', async () => {
  const ui = harness(); await ui.mount();
  const gate = deferred(); ui.routes.set('/api/workbench/runs/A', () => gate.promise);
  const pending = ui.refresh(); await flush();
  await ui.select('B');
  gate.reject(new Error('old A failed')); await pending;
  assert.equal(ui.title(), 'Run B');
  assert.equal(ui.root().querySelector('.wb-notice').textContent, '');
  assert.equal(ui.timers.size, 1);
});

test('overlapping list refreshes keep the newest response and one timer', async () => {
  const ui = harness(); await ui.mount();
  const gate = deferred(); let count = 0;
  ui.routes.set('/api/workbench/runs', () => ++count === 1 ? gate.promise : {runs: [record('B')]});
  const older = ui.refresh(); await flush();
  const newer = ui.refresh(); await newer;
  gate.resolve({runs: [record('A', 'running')]}); await older;
  assert.equal(ui.root().querySelectorAll('.wb-run-card').map(card => card.querySelector('strong').textContent).join(','), 'Run B');
  assert.equal(ui.timers.size, 0);
});

test('interrupted totals identify uncertain commits and leave later tables unexecuted', async () => {
  const run = record('A', 'interrupted', {row_counts_exact: false, error: 'Process interrupted', tables: [
    {name: 'users', status: 'error', requested_count: 10, rows_inserted: 7, errors: ['constraint failed']},
    {name: 'orders', status: 'not_run', requested_count: 10, rows_inserted: 0, errors: []},
  ]});
  const ui = harness({runs: [run]}); await ui.mount();
  const detail = ui.root().querySelector('.wb-run-detail').textContent;
  assert.match(detail, /至少 7/); assert.match(detail, /无法确认最后一批/);
  assert.match(detail, /constraint failed/); assert.match(detail, /前序任务未完成/);
  assert.equal(ui.timers.size, 0);
});

test('server strings and snapshot content are text nodes, and exported JSON retains the snapshot', async () => {
  const run = record('A', 'error', {name: '<img src=x onerror=alert(1)>', error: '<script>unsafe()</script>'});
  run.document.tables[0].columns = [{name: 'name', generator: 'choice', params: {choices: ['<script>text()</script>']}}];
  const ui = harness({runs: [run]}); await ui.mount();
  assert.equal(ui.root().querySelectorAll('script, img').length, 0);
  assert.equal(ui.title(), run.name);
  const exportButton = ui.root().querySelectorAll('button').find(button => button.textContent === '导出快照 JSON');
  await exportButton.click();
  const exported = JSON.parse(await ui.downloads[0].text());
  assert.deepEqual(exported.document, run.document);
  assert.equal(exported.target_key, run.target_key);
});

test('a queued run failing before its first table displays the persisted terminal errors array', async () => {
  // execute_run publishes errors (plural) when queue-time validation fails;
  // no table was running yet, so there is no per-table error to display.
  const message = '排队期间配置来源或 schema 已变化，运行未开始';
  const run = record('A', 'error', {
    errors: [message], rows_inserted: 0, elapsed: 0.01, finished_at: 123,
    row_counts_exact: true,
    tables: [{name: 'users', status: 'not_run', requested_count: 10, rows_inserted: 0, errors: []}],
  });
  assert.equal(run.error, undefined);
  const ui = harness({runs: [run]}); await ui.mount();
  const detail = ui.root().querySelector('.wb-run-detail');
  assert.match(detail.textContent, /0 行已提交/);
  assert.ok(detail.querySelector('[role="alert"]').textContent.includes(message));
  assert.match(detail.textContent, /前序任务未完成/);
});

test('terminal error and errors formats are combined without duplicating the same reason', async () => {
  const run = record('A', 'error', {errors: ['database unavailable', '<script>details</script>'], error: 'database unavailable'});
  const ui = harness({runs: [run]}); await ui.mount();
  const alert = ui.root().querySelector('[role="alert"]');
  assert.equal(alert.textContent.split('database unavailable').length - 1, 1);
  assert.ok(alert.textContent.includes('<script>details</script>'));
  assert.equal(alert.querySelectorAll('script').length, 0);
});

test('each execution state has a readable result instead of a blank dash', async () => {
  const states = ['done', 'error', 'queued', 'running', 'not_run', 'interrupted'];
  const run = record('A', 'error', {tables: states.map((status, index) => ({name: `table_${index}`, status,
    requested_count: 10, rows_inserted: status === 'done' ? 10 : 0, errors: []}))});
  const ui = harness({runs: [run]}); await ui.mount();
  const rows = ui.root().querySelector('tbody').querySelectorAll('tr');
  for (let i = 0; i < states.length; i++) {
    assert.notEqual(rows[i].children.at(-1).textContent, '—', states[i]);
    assert.ok(rows[i].children.at(-1).textContent.length > 2, states[i]);
  }
  assert.match(rows[0].textContent, /生成成功/);
  assert.match(rows[1].textContent, /生成失败/);
  assert.match(rows[4].textContent, /前序任务未完成/);
});

test('the result summary distinguishes the frozen plan from actual committed records', async () => {
  const ui = harness({runs: [record('A', 'error', {tables: [
    {name: 'users', status: 'done', requested_count: 120, rows_inserted: 7, errors: []},
    {name: 'orders', status: 'not_run', requested_count: 80, rows_inserted: 0, errors: []},
  ]})]}); await ui.mount();
  const metrics = ui.root().querySelector('.run-metrics');
  assert.match(metrics.textContent, /计划生成200 行/);
  assert.match(metrics.textContent, /实际已提交7 行已提交/);
  assert.match(ui.root().querySelector('.run-count-explanation').textContent, /本次新增/);
  assert.match(ui.root().querySelector('.run-count-explanation').textContent, /不包含数据库中原有/);
});

test('unavailable historical count data is not presented as a known zero', async () => {
  const ui = harness({runs: [record('A', 'interrupted', {rows_inserted: null, row_counts_exact: false, tables: [
    {name: 'users', status: 'interrupted', rows_inserted: null, errors: []},
  ], document: {tables: []}})]}); await ui.mount();
  const detail = ui.root().querySelector('.wb-run-detail').textContent;
  assert.match(detail, /提交数量待核对/);
  assert.doesNotMatch(detail, /0 行已提交/);
});

test('historical error strings remain readable without crashing the run details', async () => {
  const ui = harness({runs: [record('A', 'error', {errors: 'Run failed', tables: [
    {name: 'users', status: 'error', requested_count: 10, rows_inserted: 0, errors: 'Constraint failed'},
  ]})]}); await ui.mount();
  assert.match(ui.root().querySelector('tbody').textContent, /Constraint failed/);
  assert.match(ui.root().querySelector('[role="alert"]').textContent, /Run failed/);
  assert.equal(ui.root().querySelector('.run-notice').textContent, '');
});

test('run cards turn Unix seconds into readable local dates without changing stored timestamps', async () => {
  const run = record('A', 'done', {created_at: 1788719235.694131});
  const ui = harness({runs: [run]}); await ui.mount();
  const card = ui.root().querySelector('.wb-run-card');
  assert.doesNotMatch(card.textContent, /1788719235/);
  assert.match(card.textContent, /2026/);
  const time = card.querySelector('time');
  assert.equal(time.getAttribute('datetime'), '2026-09-06T18:27:15.694Z');
  assert.equal(run.created_at, 1788719235.694131);
});

test('run cards accept historical ISO timestamps and use a readable fallback for invalid dates', async () => {
  const runs = [record('A', 'done', {created_at: '2025-06-15T11:30:00Z'}),
    record('B', 'done', {created_at: 'invalid date'}), record('C')];
  const ui = harness({runs}); await ui.mount();
  const cards = ui.root().querySelectorAll('.wb-run-card');
  assert.match(cards[0].textContent, /2025/);
  assert.equal(cards[0].querySelector('time').getAttribute('datetime'), '2025-06-15T11:30:00.000Z');
  for (const card of cards.slice(1)) {
    assert.match(card.textContent, /时间未知/);
    assert.doesNotMatch(card.textContent, /Invalid Date|invalid date/);
  }
});

test('replacement failures distinguish rollback from committed rows and export the execution strategy',async()=>{
 const run=record('R','error',{rows_inserted:0,execution:{mode:'replace_selected',reset_identity:true},plan_hash:'reviewed',result:{atomic:true,committed:false,rolled_back:true},tables:[{name:'users',status:'error',requested_count:10,rows_inserted:0,errors:[]}]});
 const ui=harness({runs:[run]});await ui.mount();
 assert.match(ui.root().textContent,/清空所选表后生成/);assert.match(ui.root().textContent,/已回滚.*原有数据/);
 assert.match(ui.root().textContent,/0 行已提交/);
 await ui.root().querySelectorAll('button').find(b=>b.textContent==='导出快照 JSON').click();
 const exported=JSON.parse(await ui.downloads[0].text());assert.deepEqual(exported.execution,run.execution);assert.equal(exported.plan_hash,'reviewed');
});

test('exact append failure offers a remaining-only plan and explains committed rows',async()=>{
  const ui=harness({runs:[record('failed','error')]});await ui.mount();
  const link=ui.root().querySelectorAll('a').find(a=>a.textContent==='修正并生成剩余数据');
  assert.ok(link);assert.equal(link.getAttribute('href'),'#/workbench?run=failed&recover=remaining');
  assert.match(ui.root().textContent,/已提交的数据会保留/);
});

test('uncertain failure cannot offer automatic remaining quantities',async()=>{
  const ui=harness({runs:[record('failed','error',{row_counts_exact:false})]});await ui.mount();
  assert.equal(ui.root().querySelectorAll('a').some(a=>a.textContent==='修正并生成剩余数据'),false);
  assert.match(ui.root().textContent,/不能自动计算剩余数量/);
});

test('completed and partly failed runs open current data bound to their historical target',async()=>{
  const ui=harness({runs:[record('A','error')]});await ui.mount();
  ui.routes.set('/api/workbench/runs/A/data-connections',()=>({target_key:'target',target_label:'example.db',connections:[{conn_id:'matching'}]}));
  const path='/api/workbench/connections/matching/tables/users/data?limit=50&offset=0&run_id=A';
  ui.routes.set(path,()=>({table:'users',target_key:'target',target_label:'example.db',dialect:'sqlite',columns:[{name:'id',type:'INTEGER'}],
    rows:[{id:101}],limit:50,offset:0,total:1,order_by:['id'],read_at:'2026-09-10T03:00:00Z'}));
  const view=ui.root().querySelectorAll('button').find(b=>b.textContent==='查看当前数据');assert.ok(view);
  await view.click();await flush();
  assert.match(ui.document.querySelector('.wb-table-data').textContent,/101/);
  assert.ok(ui.requests.includes(path));
  ui.leave();assert.equal(ui.document.querySelector('.wb-table-data'),null);
});

test('switching run closes its data viewer and ignores its pending connection lookup',async()=>{
  const ui=harness({runs:[record('A'),record('B')]});await ui.mount();
  const gate=deferred();ui.routes.set('/api/workbench/runs/A/data-connections',()=>gate.promise);
  await ui.root().querySelectorAll('button').find(b=>b.textContent==='查看当前数据').click();
  await ui.select('B');gate.resolve({target_key:'target',connections:[{conn_id:'old'}]});await flush();
  assert.equal(ui.document.querySelector('.wb-table-data'),null);
  assert.equal(ui.requests.some(p=>p.includes('/connections/old/')),false);
});

test('old run detail cannot open a data viewer while the selected run is loading',async()=>{
  const ui=harness({runs:[record('A'),record('B')]});await ui.mount();
  const gate=deferred();ui.routes.set('/api/workbench/runs/B',()=>gate.promise);
  await ui.select('B');await flush();
  await ui.root().querySelectorAll('button').find(b=>b.textContent==='查看当前数据').click();
  assert.equal(ui.document.querySelector('.wb-table-data'),null);
  gate.resolve(record('B'));await flush();
});
