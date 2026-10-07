const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {harness, plain} = require('./workbench_harness.cjs');
const redraw = ui => vm.runInContext('drawBody()', ui.context);

async function compactWorkbench() {
  const ui = harness();
  ui.context.innerWidth = 390;
  await ui.mount();
  return ui;
}

test('compact directory distinguishes browsing from generation and keeps independent real controls', async () => {
  const ui = await compactWorkbench(), m = ui.modelState();
  let directory = ui.root().querySelector('.wb-table-directory');
  assert.ok(directory, 'mobile table controls must be a disclosure');
  assert.equal(directory.open, false);
  assert.match(directory.querySelector('summary').textContent, /当前查看：users.*已选 0 张表/);
  directory.open = true; await directory.dispatchEvent({type:'toggle', currentTarget:directory});
  const row = directory.querySelector('[data-table="orders"]');
  const label = row.querySelector('.wb-table-select');
  assert.equal(label.tagName, 'LABEL');
  assert.ok(label.querySelector('input[type="checkbox"]'));
  assert.equal(label.querySelector('.wb-table-name'), null);
  assert.equal(label.querySelector('.wb-table-graph'), null);
  const input = label.querySelector('input');input.checked = true;await input.dispatchEvent('change');
  assert.equal(m.selected('orders'), true);assert.equal(m.view.table, 'users');
  assert.equal(ui.root().querySelector('.wb-table-directory').open, true);
  const before = plain(m.document);
  await ui.root().querySelector('[data-table="audit"]').querySelector('.table-button').click();
  directory = ui.root().querySelector('.wb-table-directory');
  assert.equal(directory.open, false);assert.equal(m.view.table, 'audit');assert.equal(m.view.page, 'fields');
  assert.deepEqual(plain(m.document), before);
  assert.match(directory.querySelector('summary').textContent, /当前查看：audit.*已选 1 张表/);
  assert.equal(ui.document.activeElement, ui.root().querySelector('.table-heading h2'));
  const requests = ui.requests.length;ui.context.setLanguage('en');
  assert.match(directory.querySelector('summary').textContent, /Viewing: audit.*1 table selected/);
  assert.equal(ui.requests.length, requests);
});

test('selection and invalid-count navigation open the compact directory without changing generation scope', async () => {
  const ui = await compactWorkbench(), m = ui.modelState();
  await ui.button('选择生成表').click();
  assert.equal(ui.root().querySelector('.wb-table-directory')?.open, true);
  assert.equal(ui.document.activeElement.getAttribute('aria-label'), '生成 users');
  assert.equal(m.document.tables.length, 0);
  m.toggleTable('users',true);
  m.restoreView({tableDrafts:{orders:{name:'orders', count:1e21, columns:[]}}});redraw(ui);
  const directory = ui.root().querySelector('.wb-table-directory');directory.open=false;
  await directory.dispatchEvent({type:'toggle', currentTarget:directory});
  await ui.button('检查输入').click();
  assert.equal(ui.root().querySelector('.wb-table-directory').open, true);
  assert.equal(ui.document.activeElement.getAttribute('aria-label'), 'orders 生成数量');
  assert.equal(m.selected('orders'), false);assert.equal(String(ui.document.activeElement.value), '1e+21');
});

test('directory breakpoint changes preserve compact preference and detach listeners on leave', async () => {
  const ui = harness();let onChange;
  const media = {matches:true, addEventListener(type, callback) {onChange=callback;}, removeEventListener(type, callback) {if(onChange===callback)onChange=null;}};
  ui.context.window.matchMedia = query => query === '(max-width: 760px)' ? media : {matches:false, addEventListener() {}, removeEventListener() {}};
  await ui.mount();const directory = ui.root().querySelector('.wb-table-directory');assert.ok(directory);
  assert.equal(directory.open, false);
  media.matches=false;onChange();assert.equal(directory.open, true);
  media.matches=true;onChange();assert.equal(directory.open, false);
  directory.open=true;await directory.dispatchEvent({type:'toggle', currentTarget:directory});
  media.matches=false;onChange();media.matches=true;onChange();assert.equal(directory.open,true);
  ui.leave();assert.equal(onChange,null);
});

test('collapsed guidance keeps the current stage and a working next action outside the hidden details', async () => {
  const ui = await compactWorkbench(), guide = ui.root().querySelector('.wb-next-step');
  const body = guide.querySelector('.wb-next-step-body');
  assert.equal(body.hidden, true);
  const next = guide.querySelector('[data-guide-action="next"]');
  assert.equal(body.contains(next),false);
  assert.match(guide.querySelector('.wb-guide-current').textContent,/1.*设定规则/);
  await next.click();assert.equal(ui.document.activeElement.getAttribute('aria-label'),'生成 users');
  await ui.button('展开引导',guide).click();
  assert.equal(body.hidden,false);
  const stages = guide.querySelector('.wb-guide-stages');
  await stages.querySelector('[data-guide-action="stage-2"]').click();
  assert.match(guide.querySelector('.wb-guide-current').textContent,/2.*预览样例/);
  assert.equal(ui.modelState().document.tables.length,0);
  await ui.button('收起引导',guide).click();redraw(ui);
  assert.equal(body.hidden,true);assert.equal(guide.querySelector('.wb-guide-stages'),stages);
  assert.equal(ui.requests.some(request=>request.url.endsWith('/runs')),false);
});

test('collapsed guidance keeps all three stage controls reachable and performs real navigation with stable controls', async () => {
  const ui=await compactWorkbench(),m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  const guide=ui.root().querySelector('.wb-next-step'),body=guide.querySelector('.wb-next-step-body');
  const stages=guide.querySelector('.wb-guide-stages'),controls=stages.querySelectorAll('button');
  const marker=stages.querySelector('.segment-indicator');
  const reachable=control=>{
    for(let node=control;node && node!==guide;node=node.parentNode) {
      if(node.hidden || node.getAttribute('hidden')!==null) return false;
    }
    return true;
  };
  assert.equal(body.hidden,true);
  assert.equal(controls.length,3);assert.ok(controls.every(reachable),'collapsed guide must retain accessible stage navigation');
  assert.ok(controls.every(control=>control.querySelector('small').hidden),'stage descriptions follow the details disclosure');
  const before=plain(m.document);
  await controls[1].click();assert.equal(m.view.page,'preview');
  assert.ok(ui.requests.some(request=>request.url.endsWith('/preview')));
  await controls[0].click();assert.equal(m.view.page,'fields');
  await controls[2].click();assert.ok(ui.document.querySelector('.modal'));
  assert.equal(ui.requests.some(request=>request.url.endsWith('/runs')),false);
  await ui.button('返回调整',ui.document.querySelector('.modal')).click();
  assert.deepEqual(plain(m.document),before);
  await ui.button('展开引导',guide).click();
  assert.equal(body.hidden,false);assert.ok(controls.every(control=>!control.querySelector('small').hidden));
  await ui.button('收起引导',guide).click();
  assert.ok(controls.every(reachable));assert.deepEqual(stages.querySelectorAll('button'),controls);
  assert.equal(stages.querySelector('.segment-indicator'),marker);
  ui.context.setLanguage('en');assert.ok(controls.every(reachable));
  assert.deepEqual(stages.querySelectorAll('button'),controls);
  assert.deepEqual(controls.map(control=>control.querySelector('strong').textContent),['Rules','Preview','Confirm']);
});

for (const saved of ['true', 'false']) {
  test(`guidance restores ${saved} collapse preference and persists changes without editing the document`, async () => {
    const values = new Map([['sqlseed.workbench.guide.collapsed',saved]]);
    const localStorage = {getItem:key=>values.get(key) ?? null, setItem:(key,value)=>values.set(key,value), removeItem:key=>values.delete(key)};
    const ui=harness({timers:{localStorage}});await ui.mount();
    const guide=ui.root().querySelector('.wb-next-step'),body=guide.querySelector('.wb-next-step-body'),before=plain(ui.modelState().document);
    assert.equal(body.hidden,saved==='true');
    await guide.querySelector('[data-guide-action="toggle"]').click();redraw(ui);
    assert.equal(values.get('sqlseed.workbench.guide.collapsed'),String(saved!=='true'));
    assert.equal(body.hidden,saved!=='true');assert.deepEqual(plain(ui.modelState().document),before);
    assert.ok(guide.querySelector('[data-guide-action="next"]'));
  });
}

for (const value of ['', '0', '-1', '1.5', '1e3', '9007199254740992']) {
  test(`compact count steppers preserve invalid draft ${JSON.stringify(value)}`, async () => {
    const ui=await compactWorkbench(),m=ui.modelState();m.toggleTable('users',true);redraw(ui);
    const input=ui.root().querySelector('[aria-label="users 生成数量"]');input.value=value;await input.dispatchEvent('input');
    const before=plain(m.document),epoch=m.epoch;
    await ui.root().querySelector('[aria-label="users 增加 1 行"]').click();
    await ui.root().querySelector('[aria-label="users 减少 1 行"]').click();
    assert.equal(input.value,value);assert.deepEqual(plain(m.document),before);assert.equal(m.epoch,epoch);
    assert.equal(ui.document.activeElement,input);
  });
}
