const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {harness, plain} = require('./workbench_harness.cjs');
const tick = () => new Promise(resolve => setImmediate(resolve));
const guide = ui => ui.root().querySelector('.wb-next-step');
const redraw = ui => vm.runInContext('drawBody()', ui.context);

test('first-use guidance teaches selection and never starts AI or a database write', async () => {
  const ui=harness();await ui.mount();await tick();
  assert.ok(guide(ui));assert.match(guide(ui).textContent,/先选择要生成的表/);
  assert.ok(ui.button('选择生成表',guide(ui)));
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('guidance AI shortcut uses selected scope and preserves the executable document', async () => {
  const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>({available:true,ready:true,effective:{backend:'ollama',model:'test'}}));
  await ui.mount();await tick();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  const before=plain(m.document);assert.match(guide(ui).textContent,/已选 2 张表 · 计划生成 200 行/);
  await ui.button('用 AI 建议规则',guide(ui)).click();await tick();
  assert.equal(ui.document.querySelector('input[value="selected"]').checked,true);
  assert.deepEqual(plain(m.document),before);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')),false);
});

test('direct preview is optional and stale results return guidance to preview after an edit', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  await ui.button('直接预览',guide(ui)).click();
  assert.match(guide(ui).textContent,/已预览所选 1 张表/);
  assert.ok(ui.button('查看生成计划',guide(ui)));
  await ui.button('字段规则').click();await ui.openRule('amount');await ui.edit('max_value','15');await ui.applyRule();
  assert.match(guide(ui).textContent,/配置已变化，请重新预览/);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('partial preview never claims all selected tables have been previewed', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  await ui.button('预览数据').click();
  assert.match(guide(ui).textContent,/已预览 1\/2 张所选表/);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  ui.routes.set('/api/workbench/preview',()=>({ok:true,preview_complete:false,issues:[],samples:{users:[{amount:3}]}}));
  await ui.button('预览已选范围',guide(ui)).click();
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
});

for(const [target,currentEpoch,expected] of [
  ['audit',true,/已应用 1 条 AI 建议，请预览/],
  ['users',true,/已预览 1\/2 张所选表/],
  ['orders',true,/已预览 1\/2 张所选表/],
  ['audit',false,/已预览 1\/2 张所选表/],
])test(`partial preview prioritizes only pending selected AI targets: ${target}, current epoch ${currentEpoch}`,async()=>{
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);m.toggleTable('audit',true);redraw(ui);
  await ui.button('预览数据').click();
  m.aiApplied={epoch:currentEpoch?m.epoch:m.epoch-1,targets:[{table:target,column:target==='users'?'amount':'event'}]};
  redraw(ui);
  assert.match(guide(ui).textContent,expected);
  assert.equal(ui.button('查看生成计划',guide(ui)),undefined);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('input errors take priority and collapsed guide keeps its preference through redraw', async () => {
  const ui=harness();await ui.mount();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  const input=ui.root().querySelector('input[aria-label="users 生成数量"]');input.value='0';await input.dispatchEvent('input');
  assert.match(guide(ui).textContent,/先修正无效输入/);
  await ui.button('检查输入',guide(ui)).click();assert.equal(ui.document.activeElement,input);
  await ui.button('收起引导',guide(ui)).click();redraw(ui);
  assert.ok(ui.button('展开引导',guide(ui)));assert.notEqual(guide(ui).querySelector('.wb-next-step-body').getAttribute('hidden'),null);
  await ui.button('展开引导',guide(ui)).click();assert.equal(guide(ui).querySelector('.wb-next-step-body').getAttribute('hidden'),null);
});

for(const [config,label] of [[{available:false},'安装 AI 扩展'],[{available:true,ready:false},'配置 AI 助手']]) {
  test(`AI readiness exposes ${label} without preventing manual preview`,async()=>{
    const ui=harness();ui.routes.set('/api/workbench/ai/config',()=>config);await ui.mount();await tick();
    const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
    assert.ok(ui.button(label,guide(ui)));assert.equal(ui.button('直接预览',guide(ui)).disabled,false);
    if(config.available===false)assert.match(guide(ui).textContent,/AI 扩展未安装.*规则建议不可用/);
  });
}

test('broken AI imports request an environment check and keep manual preview available',async()=>{
  const ui=harness();
  ui.routes.set('/api/workbench/ai/config',()=>({available:false,ready:false,availability_status:'import_error'}));
  await ui.mount();await tick();const m=ui.modelState();m.toggleTable('users',true);redraw(ui);
  assert.ok(ui.button('检查 AI 插件',guide(ui)));
  assert.match(guide(ui).textContent,/插件加载异常.*规则建议不可用/);assert.doesNotMatch(guide(ui).textContent,/未安装/);
  assert.equal(ui.button('直接预览',guide(ui)).disabled,false);
  const before=plain(m.document);await ui.button('检查 AI 插件',guide(ui)).click();await tick();
  assert.match(ui.document.querySelector('[aria-label="AI 状态"]').textContent,/AI 插件加载异常/);
  assert.deepEqual(plain(m.document),before);
  assert.equal(ui.requests.some(r=>r.url.endsWith('/suggest')||r.url.endsWith('/runs')),false);
});

test('selection guidance focuses visible search results and falls back to search when empty',async()=>{
  const ui=harness();await ui.mount();const search=ui.root().querySelector('input[aria-label="查找表"]');
  search.value='audit';await search.dispatchEvent('input');await ui.button('选择生成表',guide(ui)).click();
  assert.equal(ui.document.activeElement.getAttribute('aria-label'),'生成 audit');
  search.value='missing';await search.dispatchEvent('input');await ui.button('选择生成表',guide(ui)).click();
  assert.equal(ui.document.activeElement,search);
});
