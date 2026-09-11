const test = require('node:test');
const assert = require('node:assert/strict');
const {harness, plain, deferred} = require('./workbench_harness.cjs');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function settings(available = ['base', 'faker']) {
  const ui = harness();
  ui.routes.set('/api/meta/providers', () => ({available}));
  ui.routes.set('/api/meta/locales', () => ({locales: [{code: 'en_US', label: 'English (US)'}, {code: 'zh_CN', label: '简体中文（中国）'}]}));
  await ui.mount();
  return ui;
}

async function choose(ui, provider) {
  await ui.document.querySelector('[role="combobox"][aria-label="数据生成引擎"]').click();
  const option = ui.document.querySelector('.dropdown-floating').querySelectorAll('[role="option"]')
    .find(node => node.textContent.toLowerCase().startsWith(provider.toLowerCase()));
  assert.ok(option, `${provider} remains discoverable even when unavailable`);
  await option.click();
}

test('missing Mimesis links to plugin management and cannot alter the configuration', async () => {
  const ui = await settings();
  const before = plain(ui.modelState().document);
  await ui.button('设置数据生成引擎').click();
  await choose(ui, 'Mimesis');
  const guide = ui.document.querySelector('.wb-provider-guide');
  assert.match(guide.textContent, /未安装/);
  const installation = guide.querySelectorAll('a').find(link => link.textContent === '管理插件');
  assert.ok(installation);
  assert.equal(installation.getAttribute('href'), '#/settings?section=plugins');
  assert.doesNotMatch(guide.textContent, /python -m pip|pip install|重启 Web/);
  assert.match(guide.textContent, /在插件与版本中安装后，返回选择此引擎/);
  const apply = ui.button('应用设置', ui.document);
  assert.equal(apply.disabled, true);
  await apply.click();
  assert.deepEqual(plain(ui.modelState().document), before);
  await installation.click();
  assert.equal(ui.document.querySelector('[role="dialog"]'), null);
  assert.deepEqual(plain(ui.modelState().document), before);
});

test('an existing unavailable provider stays selected without silently falling back', async () => {
  const ui = await settings();
  ui.modelState().document.provider = 'mimesis';
  await ui.button('设置数据生成引擎').click();
  assert.match(ui.document.querySelector('[role="combobox"][aria-label="数据生成引擎"]').textContent, /Mimesis.*未安装/);
  assert.equal(ui.button('应用设置', ui.document).disabled, true);
  await ui.button('取消', ui.document).click();
  assert.equal(ui.modelState().document.provider, 'mimesis');
});

test('available Mimesis can be applied and saved while keeping existing table rules', async () => {
  const ui = await settings(['base', 'faker', 'mimesis']);
  ui.modelState().toggleTable('users', true);
  const tables = plain(ui.modelState().document.tables);
  await ui.button('设置数据生成引擎').click();
  await choose(ui, 'Mimesis');
  const guide = ui.document.querySelector('.wb-provider-guide');
  assert.match(guide.textContent, /已安装/);
  assert.doesNotMatch(guide.textContent, /需要安装|pip install/);
  assert.match(guide.textContent, /高性能/);
  assert.equal(guide.querySelector('details').getAttribute('open'), null);
  assert.ok(guide.querySelector('details').querySelector('.wb-provider-example'));
  assert.equal(ui.button('应用设置', ui.document).disabled, false);
  await ui.button('应用设置', ui.document).click();
  assert.equal(ui.modelState().document.provider, 'mimesis');
  assert.deepEqual(plain(ui.modelState().document.tables), tables);
  await ui.button('保存配置').click();
  const saved = ui.requests.find(request => request.url === '/api/workbench/drafts');
  assert.equal(JSON.parse(saved.options.body).document.provider, 'mimesis');
  assert.deepEqual(JSON.parse(saved.options.body).document.tables, tables);
});

test('built-in and required providers explain their availability and choosing another guide is only a draft', async () => {
  const ui = await settings();
  await ui.button('设置数据生成引擎').click();
  assert.match(ui.document.querySelector('.wb-provider-guide').textContent, /内置可用/);
  await choose(ui, 'Faker');
  assert.match(ui.document.querySelector('.wb-provider-guide').textContent, /随 sqlseed 安装/);
  assert.equal(ui.modelState().document.provider, 'base');
  await ui.button('取消', ui.document).click();
  assert.equal(ui.modelState().document.provider, 'base');
});

test('engine choices retain the requested Base, Faker, Mimesis order', async () => {
  const ui=await settings();await ui.button('设置数据生成引擎').click();
  await ui.document.querySelector('[role="combobox"][aria-label="数据生成引擎"]').click();
  assert.deepEqual(ui.document.querySelector('.dropdown-floating').querySelectorAll('[role="option"]').map(node=>node.textContent.split(' · ')[0]),['Base','Faker','Mimesis']);
  ui.leave();
});

for(const [state,description] of [['not_installed','未安装'],['import_error','加载异常']])test(`an existing Mimesis configuration explains ${state} and refreshes after returning`,async()=>{
  const ui=await settings();let available=false;
  ui.routes.set('/api/meta/providers',()=>({available:available?['base','faker','mimesis']:['base','faker'],statuses:{mimesis:{available,status:available?'available':state}}}));
  ui.modelState().document.provider='mimesis';const before=plain(ui.modelState().document);
  ui.leave();await ui.mount();await tick();
  const warning=ui.root().querySelector('[data-provider-warning]');assert.ok(warning);assert.equal(warning.hidden,false);
  assert.match(warning.textContent,new RegExp(`Mimesis.*${description}.*预览.*生成`));assert.ok(ui.button('管理插件',warning));
  await ui.button('更改引擎',warning).click();
  const guide=ui.document.querySelector('.wb-provider-guide');assert.match(guide.textContent,new RegExp(description));
  if(state==='import_error')assert.doesNotMatch(guide.textContent,/未安装|中安装后/);
  await ui.button('取消',ui.document).click();assert.deepEqual(plain(ui.modelState().document),before);
  available=true;ui.leave();await ui.mount();await tick();
  assert.equal(ui.root().querySelector('[data-provider-warning]').hidden,true);assert.deepEqual(plain(ui.modelState().document),before);ui.leave();
});

test('a missing column-level Mimesis dependency identifies its field without changing the global engine',async()=>{
  const ui=await settings();ui.modelState().setColumn('users','amount',{name:'amount',generator:'integer',provider:'mimesis'});
  const before=plain(ui.modelState().payload('current'));ui.leave();await ui.mount();await tick();
  const warning=ui.root().querySelector('[data-provider-warning]');assert.equal(warning.hidden,false);assert.match(warning.textContent,/users.amount/);
  await ui.button('更改引擎',warning).click();
  assert.equal(ui.document.querySelector('.drawer').getAttribute('aria-label'),'amount');await ui.cancelRule();
  assert.deepEqual(plain(ui.modelState().payload('current')),before);ui.leave();
});

test('late provider metadata from an old mount cannot hide the current missing-engine warning',async()=>{
  const ui=await settings(),old=deferred();ui.modelState().document.provider='mimesis';
  ui.routes.set('/api/meta/providers',()=>old.promise);ui.leave();await ui.mount();
  ui.routes.set('/api/meta/providers',()=>({available:['base','faker']}));ui.leave();await ui.mount();await tick();
  old.resolve({available:['base','faker','mimesis']});await tick();
  assert.equal(ui.root().querySelector('[data-provider-warning]').hidden,false);ui.leave();
});
