const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};
function harness({request, config, handoff = null, clipboard, maintenanceShell = false} = {}) {
  const document = createDom(), window = new Element('window');
  document.documentElement = {dataset: {pluginMaintenance: String(maintenanceShell)}};
  document.createElementNS = (_, tag) => new Element(tag);
  const location = {hash: '#/settings?section=ai'}, calls = [], returned = [];
  const settings = config || {available: true, ready: true, effective: {backend: 'ollama', model: 'demo', base_url: 'http://localhost:11434/v1', api_key_present: true}, sources: {api_key: 'session'}, storage: {fields: ['backend', 'model', 'base_url']}};
  const environment = {python: {version: '3.12.0', implementation: 'CPython'}, packages: [{id: 'core', name: 'sqlseed', version: '1.2.3', installed: true, available: true, message: '核心测试数据生成库'}], providers: [{id: 'base', name: 'Base', version: null, installed: true, available: true, status: 'builtin', message: '内置基础引擎'}]};
  const ui = loadFrontend('workbench/ui.js', {document});
  const dropdown = loadFrontend('dropdown.js', {document});
  const requestApi = async (url, options = {}) => {
    const call = {url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null, headers: options.headers}; calls.push(call);
    const custom = await request?.(call); if (custom !== undefined) return custom;
    if (url.endsWith('/management')) return {enabled: false, available: false};
    if (url.endsWith('/environment')) return environment;
    if (url.endsWith('/config')) return settings;
    if (url.endsWith('/test')) return {ok: true, models: ['other-model'], message: '服务连接成功，仅验证模型列表。', checked_at: '2026-09-09T10:00:00Z'};
    throw new Error(`Unexpected request ${url}`);
  };
  const pluginManagement = loadFrontend('workbench/plugin-management.js', {document, AbortController, api: requestApi, ...vm.runInContext('({button,modal})', ui)});
  const context = loadFrontend('pages/settings.js', {document, window, location, navigator: {clipboard}, URLSearchParams, AbortController, Event: class {constructor(type) {this.type = type;}},
    store: {connId: 'connection'}, ...vm.runInContext('({button,icon})', ui), createDropdown: vm.runInContext('createDropdown', dropdown),
    peekAIHandoff: () => handoff, requestAIReturn: () => handoff?.returnTo || null,
    leaveAISettings: hash => returned.push(hash), ...vm.runInContext('({createPluginManagement,componentImpact})', pluginManagement), api: requestApi});
  document.body.append(context.render());
  const mounted = context.mount();
  const find = text => document.querySelectorAll('button').find(el => el.textContent === text);
  const input = label => document.querySelector(`[aria-label="${label}"]`);
  return {document, window, location, context, calls, returned, mounted, find, input, settings};
}

test('settings can load without a database and shows independent environment and AI sections', async () => {
  const t = harness(); await t.mounted;
  assert.equal(t.input('模型名称').value, 'demo');
  assert.equal(t.input('API Key').value, '');
  assert.match(t.document.textContent, /本次服务/);
  await t.find('插件与版本').click();
  assert.match(t.document.querySelector('#settings-plugins').textContent, /sqlseed.*1.2.3/);
  assert.match(t.document.querySelector('#settings-plugins').textContent, /数据生成引擎/);
  assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('managed plugin controls keep AI settings available and hide terminal setup for missing extensions', async () => {
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:1, instance_id:'app', available:true, token:'token', components:[{id:'ai', can_install:true}]};
    if (call.url.endsWith('/environment')) return optionalEnvironment();
  }}); await t.mounted;
  assert.equal(t.find('AI 服务').disabled, false);
  assert.equal(t.input('模型名称').value, 'demo');
  const row = t.document.querySelector('[data-package-id="ai"]');
  assert.ok(row.querySelector('[data-plugin-action="install"]'));
  const guide = row.querySelector('.settings-package-help');
  assert.ok(!guide || guide.hidden);
  const edited = t.input('模型名称'); edited.value = 'managed-model'; await edited.dispatchEvent('input');
  await t.find('保存设置').click();
  assert.equal(t.calls.filter(call => call.method === 'POST' && call.url.endsWith('/config')).length, 1);
  assert.match(t.document.textContent, /设置已保存/);
  t.context.unmount();
});

test('worker recovery refreshes only the selected connection and preserves unsaved AI edits', async () => {
  let generation = 1;
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.url === '/api/connections') return {connections:[{conn_id:'other'},{conn_id:'connection'}]};
    if (call.url.endsWith('/connection/tables')) return {tables:['restored-table']};
  }}); await t.mounted;
  const edited = t.input('模型名称'); edited.value = 'unsaved-model'; await edited.dispatchEvent('input');
  generation++; await t.find('刷新状态').click();
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  assert.equal(t.calls.filter(call=>call.url.endsWith('/connection/tables')).length, 1);
  assert.equal(t.calls.some(call=>call.url.endsWith('/other/tables')), false);
  assert.equal(t.calls.filter(call=>call.url.endsWith('/config')).length, 2);
  assert.deepEqual(Array.from(vm.runInContext('store.tables',t.context)), ['restored-table']);
  t.context.unmount();
});

test('uninstalling AI refreshes availability with a pending draft and reinstalling restores its controls', async () => {
  let generation = 1, installed = true;
  const effective = {backend:'ollama', model:'saved-model', base_url:'http://localhost:11434/v1'};
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.url.endsWith('/config')) return {available:installed, ready:installed, availability_status:installed?'available':'not_installed', effective};
    if (call.url === '/api/connections') return {connections:[]};
  }}); await t.mounted;
  t.input('模型名称').value = 'unsaved-model'; await t.input('模型名称').dispatchEvent('input');
  installed=false; generation++; await t.find('刷新状态').click();
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  assert.equal(t.find('检测连接').disabled, true);
  const hint=t.document.querySelector('[data-ai-install]');
  assert.equal(hint.hidden, false); assert.match(hint.textContent, /未安装.*规则建议与分析不可用/);
  await t.find('前往安装').click(); assert.equal(t.document.querySelector('#settings-plugins').hidden, false);
  installed=true; generation++; await t.find('刷新状态').click();
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  assert.equal(t.find('保存设置').disabled, false);
  assert.equal(t.calls.some(call=>call.method==='POST'), false);
  t.context.unmount();
});

test('worker recovery replaces an in-flight initial AI read and rejects its late available response', async () => {
  let generation = 1, reads = 0;
  const old = deferred(), effective = {backend:'ollama', model:'retained-model'};
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.url.endsWith('/config')) return ++reads === 1 ? old.promise : {available:false, ready:false, availability_status:'not_installed', effective};
    if (call.url === '/api/connections') return {connections:[]};
  }});
  await tick(); generation++;
  const refreshed = t.find('刷新状态').click(); await tick();
  old.resolve({available:true, ready:true, effective:{...effective, model:'old-worker-model'}});
  await Promise.all([t.mounted, refreshed]);
  assert.equal(t.find('检测连接').disabled, true);
  assert.equal(t.document.querySelector('[data-ai-install]').hidden, false);
  assert.equal(t.input('模型名称').value, 'retained-model');
  assert.equal(reads, 2);
  t.context.unmount();
});

for (const operation of ['test', 'config']) test(`worker recovery preserves a draft and rejects a late AI ${operation} response`, async () => {
  let generation = 1;
  const old = deferred(), effective = {backend:'ollama', model:'saved-model'};
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.method === 'POST') return old.promise;
    if (call.url.endsWith('/config')) return {available:generation === 1, ready:generation === 1, availability_status:generation === 1?'available':'not_installed', effective};
    if (call.url === '/api/connections') return {connections:[]};
  }}); await t.mounted;
  t.input('模型名称').value = 'unsaved-model'; await t.input('模型名称').dispatchEvent('input');
  const pending = t.find(operation === 'test' ? '检测连接' : '保存设置').click(); await tick();
  generation++; await t.find('刷新状态').click();
  old.resolve({available:true, ready:true, effective:{...effective, model:'old-worker-model'}, ok:true, models:['late-model'], message:'late-success'});
  await pending;
  assert.equal(t.find('检测连接').disabled, true);
  assert.equal(t.document.querySelector('[data-ai-install]').hidden, false);
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  assert.doesNotMatch(t.document.textContent, /late-model|late-success|设置已保存/);
  assert.equal(t.calls.filter(call => call.method === 'POST').length, 1);
  t.context.unmount();
});

test('a failed capability refresh keeps AI disabled and preserves its draft when retried', async () => {
  let generation = 1, reads = 0;
  const effective = {backend:'ollama', model:'saved-model'};
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.url.endsWith('/config')) {
      if (++reads === 2) throw new Error('temporary capability failure');
      return {available:generation === 1, ready:generation === 1, availability_status:generation === 1?'available':'not_installed', effective};
    }
    if (call.url === '/api/connections') return {connections:[]};
  }}); await t.mounted;
  t.input('模型名称').value = 'unsaved-model'; await t.input('模型名称').dispatchEvent('input');
  generation++; await t.find('刷新状态').click();
  assert.equal(t.find('检测连接').disabled, true);
  assert.match(t.document.querySelector('[data-settings-notice]').textContent, /无法读取 AI 设置/);
  await t.find('重试读取').click();
  assert.equal(t.document.querySelector('[data-ai-install]').hidden, false);
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  t.context.unmount();
});

test('AI reinstall read failure exposes retry outside the hidden form and retains the draft', async () => {
  let generation = 1, reads = 0;
  const effective = {backend:'ollama', model:'saved-model'};
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, phase:'ready', service_generation:generation, instance_id:'app', available:true, token:'token', components:[]};
    if (call.url.endsWith('/config')) {
      if (++reads === 3) throw new Error('temporary reinstall read failure');
      return {available:generation !== 2, ready:generation !== 2, availability_status:generation === 2?'not_installed':'available', effective};
    }
    if (call.url === '/api/connections') return {connections:[]};
  }}); await t.mounted;
  t.input('模型名称').value = 'unsaved-model'; await t.input('模型名称').dispatchEvent('input');
  generation++; await t.find('刷新状态').click();
  assert.equal(t.document.querySelector('.settings-form').hidden, true);
  generation++; await t.find('刷新状态').click();
  const retry = t.find('重试读取'); assert.ok(retry);
  for (let node = retry; node; node = node.parentElement) assert.notEqual(node.hidden, true, 'retry must remain visible');
  await retry.click();
  assert.equal(t.document.querySelector('[data-ai-install]').hidden, true);
  assert.equal(t.find('检测连接').disabled, false);
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  t.context.unmount();
});

test('worker recovery replaces an in-flight environment read and rejects old component availability', async () => {
  let refreshing = false, environmentReads = 0;
  const old = deferred(), recovered = deferred(), missing = optionalEnvironment();
  const installed = structuredClone(missing);
  for (const item of [...installed.packages, ...installed.providers]) Object.assign(item, {installed:true, available:true, status:'available'});
  const management = generation => ({enabled:true, automatic_lifecycle:true, available:true, phase:'ready', instance_id:'app', service_generation:generation, token:'token', components:[{id:'ai', can_install:generation === 2}]});
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return refreshing ? recovered.promise : management(1);
    if (call.url.endsWith('/environment')) return ++environmentReads === 2 ? old.promise : refreshing ? missing : installed;
    if (call.url === '/api/connections') return {connections:[]};
  }}); await t.mounted;
  refreshing = true; const pending = t.find('刷新状态').click(); await tick();
  recovered.resolve(management(2)); await tick();
  old.resolve(installed); await pending;
  for (const id of ['ai', 'cli', 'mcp', 'mimesis']) {
    const row = t.document.querySelector(`[data-package-id="${id}"]`);
    assert.match(row.querySelector('.settings-badge').textContent, /未安装/, id);
    assert.ok(row.querySelector('[data-component-impact]'), id);
  }
  assert.equal(environmentReads, 3);
  assert.equal(t.find('刷新状态').disabled, false);
  t.context.unmount();
});

test('missing optional components explain their specific functional impact beside their status', async () => {
  const t = harness({request:call=>call.url.endsWith('/environment')?optionalEnvironment():undefined}); await t.mounted;
  for (const [id, pattern] of [['ai',/规则建议与分析不可用/],['cli',/终端.*不可用/],['mcp',/MCP 客户端.*不可用/],['mimesis',/Mimesis.*预览或生成/]]) {
    const row=t.document.querySelector(`[data-package-id="${id}"]`);
    const impact=row.querySelector('[data-component-impact]'); assert.ok(impact,id); assert.match(impact.textContent,pattern,id);
    assert.equal(impact.closest('details'), null);
  }
  t.context.unmount();
});

test('unsupported automatic management keeps recovery guidance reachable for missing components', async () => {
  const t = harness({config:{available:false, ready:false, availability_status:'not_installed', effective:{}}, request:call => {
    if (call.url.endsWith('/management')) return {enabled:true, automatic_lifecycle:true, available:false, phase:'ready', instance_id:'app', service_generation:1, reason:'当前环境使用共享 site-packages，无法在网页中管理组件。', components:[]};
    if (call.url.endsWith('/environment')) return optionalEnvironment();
  }}); await t.mounted;
  const checkGuidance = () => {
    for (const id of ['cli', 'mcp', 'ai', 'mimesis']) {
      const row = t.document.querySelector(`[data-package-id="${id}"]`);
      assert.equal(row.querySelector('[data-plugin-action="install"]'), null);
      const help = row.querySelector('.settings-package-help');
      assert.ok(help, id); assert.equal(help.hidden, false, id);
      assert.match(help.textContent, /安装|环境/);
    }
    assert.ok(t.document.querySelector('[data-ai-install]').querySelector('.settings-package-help'));
  };
  checkGuidance(); await t.find('刷新状态').click(); checkGuidance();
  t.context.unmount();
});

test('maintenance settings skip AI imports and show only allowed package actions', async () => {
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled: true, available: true, token: 'session-token', python_executable: '/env/python', components: [{id: 'core', can_uninstall: true}, {id: 'ai', can_install: true}]};
    if (call.url.endsWith('/environment')) return {...optionalEnvironment(), packages: [{id: 'core', name: 'sqlseed', installed: true, available: true}, {id: 'ai', name: 'AI', installed: false, available: false}]};
  }}); await t.mounted;
  assert.equal(t.calls.some(call => call.url.startsWith('/api/workbench/ai')), false);
  assert.equal(t.document.querySelector('#settings-ai').hidden, true);
  assert.equal(t.find('AI 服务').disabled, true);
  assert.match(t.document.querySelector('#settings-plugins').textContent, /维护模式/);
  assert.ok(t.document.querySelector('[data-package-id="ai"]').querySelector('[data-plugin-action="install"]'));
  assert.equal(t.document.querySelector('[data-package-id="core"]').querySelector('[data-plugin-action]'), null);
  t.context.unmount();
});

test('management detection must finish before an AI settings request can begin', async () => {
  const gate = deferred();
  const t = harness({request: call => call.url.endsWith('/management') ? gate.promise : undefined});
  await tick();
  assert.equal(t.calls.some(call => call.url.startsWith('/api/workbench/ai')), false);
  t.context.unmount();
  gate.resolve({enabled: false, available: false}); await t.mounted;
  assert.equal(t.calls.some(call => call.url.startsWith('/api/workbench/ai')), false);
});

test('maintenance metadata reports installed packages as unverified rather than broken', async () => {
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled: true, available: true, token: 'token', components: []};
    if (call.url.endsWith('/environment')) return {inspection: 'metadata_only', packages: [{id: 'ai', name: 'AI', installed: true, available: false, status: 'installed', version: '1.2.3'}], providers: [{id: 'base', name: 'Base', installed: true, available: false, requirement: 'builtin'}]};
  }}); await t.mounted;
  const row = t.document.querySelector('[data-package-id="ai"]');
  assert.match(row.textContent, /已安装.*待验证/); assert.doesNotMatch(row.textContent, /加载异常|修复指引/);
  assert.equal(row.querySelector('details'), null);
  assert.doesNotMatch(t.document.querySelector('[data-package-id="base"]').textContent, /缺失|异常|修复/);
  t.context.unmount();
});

test('maintenance detected during an AI read discards that read even if abort is ignored', async () => {
  const gate = deferred(); let maintenance = false;
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled: maintenance, available: false};
    if (call.url.endsWith('/config')) return gate.promise;
  }}); await tick(); maintenance = true;
  await t.find('刷新状态').click();
  gate.resolve({...t.settings, effective: {...t.settings.effective, model: 'stale-model'}}); await t.mounted;
  assert.notEqual(t.input('模型名称').value, 'stale-model');
  assert.equal(t.document.querySelector('#settings-ai').hidden, true); t.context.unmount();
});

test('a known maintenance shell remains isolated when management status cannot be read', async () => {
  const t = harness({maintenanceShell: true, request: call => {if (call.url.endsWith('/management')) throw new Error('network unavailable');}}); await t.mounted;
  assert.equal(t.calls.some(call => call.url.startsWith('/api/workbench/ai')), false);
  assert.equal(t.document.querySelector('#settings-ai').hidden, true);
  assert.equal(t.find('AI 服务').disabled, true);
  assert.match(t.document.querySelector('#settings-plugins').textContent, /无法读取插件管理状态/); t.context.unmount();
});

test('a running plugin task still permits full status refresh after a service restart', async () => {
  let reads = 0;
  const t = harness({request: call => {
    if (call.url.endsWith('/management')) return {enabled: true, available: true, token: ++reads === 1 ? 'old-token' : 'new-token', components: [{id: 'ai', can_install: true}],
      active_task: reads === 1 ? {task_id: 'old-task', component_id: 'ai', action: 'install', status: 'running', message: '执行中', output: []} : null};
    if (call.url.endsWith('/environment')) return optionalEnvironment();
  }}); await t.mounted;
  assert.equal(t.find('刷新状态').disabled, false);
  assert.equal(t.document.querySelector('[data-package-id="ai"]').querySelector('[data-plugin-action]').disabled, true);
  await t.find('刷新状态').click();
  assert.equal(reads, 2);
  assert.equal(t.document.querySelector('[data-package-id="ai"]').querySelector('[data-plugin-action]').disabled, false);
  assert.equal(t.calls.some(call => call.method === 'POST'), false); t.context.unmount();
});

test('testing uses the edited draft, never saves it, and editing invalidates model discovery', async () => {
  const t = harness(); await t.mounted;
  t.input('AI 服务地址').value = 'https://example.test/v1'; await t.input('AI 服务地址').dispatchEvent('input');
  t.input('API Key').value = 'temporary-key'; await t.input('API Key').dispatchEvent('input');
  await t.find('检测连接').click();
  const mutations = t.calls.filter(call => call.method === 'POST');
  assert.deepEqual(mutations.map(call => call.url), ['/api/workbench/ai/test']);
  assert.equal(mutations[0].body.base_url, 'https://example.test/v1');
  assert.equal(mutations[0].body.api_key, 'temporary-key');
  assert.match(t.document.querySelector('[data-settings-test]').textContent, /仅验证模型列表/);
  assert.ok(t.find('other-model'));
  t.input('模型名称').value = 'changed'; await t.input('模型名称').dispatchEvent('input');
  assert.match(t.document.querySelector('[data-settings-test]').textContent, /重新检测/);
  assert.equal(t.find('other-model'), undefined);
  t.context.unmount();
});

test('save persists ordinary settings through the API and clears credentials on success', async () => {
  const t = harness(); await t.mounted;
  t.input('模型名称').value = 'new-model'; await t.input('模型名称').dispatchEvent('input');
  t.input('API Key').value = 'test-secret'; await t.input('API Key').dispatchEvent('input');
  t.settings.effective.model = 'new-model';
  await t.find('保存设置').click();
  const call = t.calls.find(call => call.method === 'POST');
  assert.equal(call.url, '/api/workbench/ai/config'); assert.equal(call.body.model, 'new-model');
  assert.equal(t.input('API Key').value, '');
  assert.match(t.document.querySelector('[data-settings-notice]').textContent, /已保存/);
  assert.doesNotMatch(t.document.textContent, /test-secret/);
  t.context.unmount();
});

test('an in-flight test freezes draft controls, ignores duplicate clicks, and cannot publish after leaving', async () => {
  const gate = deferred();
  const t = harness({request: call => call.url.endsWith('/test') ? gate.promise : undefined}); await t.mounted;
  const pending = t.find('检测连接').click(); await tick();
  assert.equal(t.input('模型名称').disabled, true); assert.equal(t.find('保存设置').disabled, true);
  await t.find('检测中…').click(); assert.equal(t.calls.filter(call => call.url.endsWith('/test')).length, 1);
  t.context.unmount(); gate.resolve({ok: true, models: ['late-model'], message: 'late'}); await pending;
  assert.equal(t.find('late-model'), undefined);
  assert.equal(t.input('API Key').value, '');
});

test('missing optional AI still exposes package information and actionable installation instructions', async () => {
  const t = harness({config: {available: false, ready: false, message: '尚未安装 AI 插件', install_command: '/service/python -m pip install sqlseed-web[ai]', installer: {available: true, shell: 'posix', message: '在终端运行'}}}); await t.mounted;
  assert.equal(t.find('保存设置').disabled, true);
  assert.match(t.document.textContent, /sqlseed-web\[ai\]/);
  await t.find('插件与版本').click();
  assert.equal(t.document.querySelector('#settings-plugins').hidden, false);
  t.context.unmount();
});

test('returning to AI uses the in-memory destination and requires an explicit choice for unsaved edits', async () => {
  const t = harness({handoff: {returnTo: '#/workbench?draft=keep'}}); await t.mounted;
  t.input('模型名称').value = 'draft'; await t.input('模型名称').dispatchEvent('input');
  await t.find('返回 AI 助手').click(); assert.equal(t.location.hash, '#/settings?section=ai');
  await t.find('放弃修改并返回').click(); assert.equal(t.location.hash, '#/workbench?draft=keep');
  t.context.unmount(); assert.deepEqual(t.returned, ['#/workbench?draft=keep']);
});

test('a failed environment refresh preserves the previous package list and explains failure', async () => {
  let fail = false;
  const t = harness({request: call => {if (fail && call.url.endsWith('/environment')) throw new Error('service unavailable');}}); await t.mounted;
  await t.find('插件与版本').click(); fail = true; await t.find('刷新状态').click();
  const panel = t.document.querySelector('#settings-plugins');
  assert.match(panel.textContent, /1.2.3/); assert.match(panel.textContent, /无法刷新/);
  t.context.unmount();
});

test('a late save cannot hydrate a remounted settings page or leave credentials in the detached page', async () => {
  const gate = deferred();
  const t = harness({request: call => call.method === 'POST' && call.url.endsWith('/config') ? gate.promise : undefined}); await t.mounted;
  t.input('API Key').value = 'temporary-secret'; await t.input('API Key').dispatchEvent('input');
  const oldInput = t.input('API Key'); const pending = t.find('保存设置').click(); await tick();
  assert.equal(t.input('模型名称').disabled, true); assert.equal(t.find('检测连接').disabled, true);
  t.context.unmount(); t.document.body.replaceChildren(t.context.render()); await t.context.mount();
  gate.resolve({available: true, ready: true, effective: {backend: 'ollama', model: 'late-model'}}); await pending;
  assert.equal(oldInput.value, ''); assert.equal(t.input('模型名称').value, 'demo');
  assert.doesNotMatch(t.document.textContent, /late-model|temporary-secret/);
  t.context.unmount();
});

test('switching settings sections retains unsaved form values without issuing model or save requests', async () => {
  const t = harness(); await t.mounted;
  t.input('模型名称').value = 'unsaved-model'; await t.input('模型名称').dispatchEvent('input');
  await t.find('插件与版本').click(); await t.find('AI 服务').click();
  assert.equal(t.input('模型名称').value, 'unsaved-model');
  assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('double-clicking read retry issues one request and cannot overwrite subsequent edits', async () => {
  let reads = 0; const first = deferred(), late = deferred();
  const t = harness({request: call => {
    if (call.url.endsWith('/config') && call.method === 'GET') {
      reads++; if (reads === 1) throw new Error('temporarily unavailable');
      return reads === 2 ? first.promise : late.promise;
    }
  }}); await t.mounted;
  const retry = t.find('重试读取'); const pending = retry.click(); await tick();
  const duplicate = retry.click(); await tick();
  first.resolve(t.settings); await pending;
  t.input('模型名称').value = 'my-new-edit'; await t.input('模型名称').dispatchEvent('input');
  late.resolve({...t.settings, effective: {...t.settings.effective, model: 'late-model'}}); await duplicate;
  assert.equal(reads, 2); assert.equal(t.input('模型名称').value, 'my-new-edit');
  t.context.unmount();
});

test('an unchanged configuration explains disabled save and an empty local key does not prevent saving edits', async () => {
  const config = {available: true, ready: true, effective: {backend: 'ollama', model: 'demo', base_url: 'http://localhost:11434/v1', api_key_present: false}, sources: {api_key: 'none'}};
  const t = harness({config}); await t.mounted;
  assert.equal(t.find('保存设置').disabled, true);
  assert.match(t.document.querySelector('[data-settings-save-state]')?.textContent || '', /没有待保存的更改/);
  t.input('模型名称').value = 'local-model'; await t.input('模型名称').dispatchEvent('input');
  assert.equal(t.find('保存设置').disabled, false);
  await t.find('保存设置').click();
  assert.equal(t.calls.find(call => call.method === 'POST').body.api_key, '');
  t.context.unmount();
});

test('changing service clears stale credential instructions and updates optional authentication guidance', async () => {
  const t = harness(); await t.mounted;
  assert.match(t.document.querySelector('.settings-key-hint').textContent, /本次服务/);
  vm.runInContext("backend.set('openai_compat')", t.context);
  t.input('AI 服务地址').value = 'https://new.example.test/v1'; await t.input('AI 服务地址').dispatchEvent('input');
  assert.doesNotMatch(t.document.querySelector('.settings-key-hint').textContent, /本次服务中有效/);
  assert.match(t.document.querySelector('[data-settings-key-label]').textContent, /按服务要求/);
  assert.equal(t.input('停用已配置密钥').closest('label').hidden, true);
  vm.runInContext("backend.set('ollama')", t.context);
  t.input('AI 服务地址').value = 'http://localhost:11434/v1'; await t.input('AI 服务地址').dispatchEvent('input');
  assert.match(t.document.querySelector('[data-settings-key-label]').textContent, /通常无需填写/);
  t.context.unmount();
});

test('installed AI with broken imports shows repair guidance rather than a missing plugin installation prompt', async () => {
  const t = harness({config: {available: false, ready: false, availability_status: 'import_error', message: 'AI 插件已安装，但加载失败；请检查依赖。'}}); await t.mounted;
  assert.equal(t.find('保存设置').disabled, true);
  assert.match(t.document.querySelector('[data-ai-install]').textContent, /加载异常|加载失败/);
  assert.doesNotMatch(t.document.querySelector('[data-ai-install]').textContent, /安装可选的 AI 扩展|pip install/);
  t.context.unmount();
});

test('package groups distinguish built-in, required and optional dependencies with actionable missing states', async () => {
  const t = harness({request: call => call.url.endsWith('/environment') ? {python: {implementation: 'CPython', version: '3.13.4'}, packages: [
    {id: 'core', name: 'Core', category: 'application', requirement: 'required', available: true, installed: true, version: '2.0'},
    {id: 'ai', name: 'AI', category: 'extension', requirement: 'optional', available: false, installed: false, description: '规则分析', guidance: '安装时同时安装 CLI', install_command: 'python -m pip install "sqlseed-web[ai]"'}
  ], providers: [
    {id: 'base', name: 'Base', category: 'provider', requirement: 'builtin', available: true, installed: true, version: '2.0'},
    {id: 'faker', name: 'Faker', category: 'provider', requirement: 'required', available: false, installed: false, guidance: '必需依赖缺失，请修复环境'},
    {id: 'mimesis', name: 'Mimesis', category: 'provider', requirement: 'optional', available: false, installed: false, install_command: 'python -m pip install "sqlseed[mimesis]"'}
  ]} : undefined}); await t.mounted;
  const panel = t.document.querySelector('#settings-plugins');
  assert.match(panel.textContent, /当前应用/); assert.match(panel.textContent, /可选扩展/);
  assert.match(panel.textContent, /内置/); assert.match(panel.textContent, /必需依赖缺失/);
  assert.match(panel.querySelector('[data-package-id="faker"]').textContent, /随 sqlseed 安装/);
  assert.match(panel.querySelector('[data-package-id="mimesis"]').textContent, /按需安装/);
  assert.match(panel.textContent, /sqlseed\[mimesis\]/); assert.match(panel.textContent, /同时安装 CLI/);
  assert.match(panel.textContent, /3.13.4/); assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('installation instructions use the detected environment command and identify the required shell', async () => {
  const command = "& 'C:\\Python Env\\python.exe' '-m' 'pip' 'install' 'sqlseed-web[ai]'";
  const config = {available: false, availability_status: 'not_installed', install_command: command, installer: {available: true, shell: 'powershell', message: '命令针对当前 Web 解释器'}};
  const t = harness({config}); await t.mounted;
  const panel = t.document.querySelector('[data-ai-install]');
  assert.equal(panel.querySelector('code').textContent, command);
  assert.match(panel.textContent, /PowerShell/);
  assert.doesNotMatch(t.document.querySelector('#settings-plugins').textContent, /动态读取/);
  assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('missing installer shows manual guidance without fabricating a runnable pip command', async () => {
  const config = {available: false, availability_status: 'not_installed', install_command: null, installer: {available: false, shell: 'posix', message: '未检测到可用 pip 或 uv，请使用创建该环境的工具安装'}};
  const t = harness({config}); await t.mounted;
  const panel = t.document.querySelector('[data-ai-install]');
  assert.equal(Boolean(panel.querySelector('code')), false);assert.match(panel.textContent, /未检测到可用 pip 或 uv/);
  assert.doesNotMatch(panel.textContent, /python -m pip/);
  t.context.unmount();
});

test('broken packages offer the environment check command without suggesting an installation repair', async () => {
  const check = '/service/python -m pip check';
  const config = {available: false, availability_status: 'import_error', message: 'AI 插件加载异常', repair_command: check, installer: {available: true, shell: 'posix'}};
  const t = harness({config, request: call => call.url.endsWith('/environment') ? {installer: config.installer, packages: [{id: 'ai', name: 'AI', available: false, installed: true, requirement: 'optional', repair_command: check, install_command: '/service/python -m pip install sqlseed-web[ai]'}], providers: []} : undefined}); await t.mounted;
  assert.equal(t.document.querySelector('[data-ai-install]').querySelector('code').textContent, check);
  assert.equal(t.document.querySelector('[data-package-id="ai"]').querySelector('code').textContent, check);
  t.context.unmount();
});

test('equivalent local service addresses retain existing credential controls and default-address guidance', async () => {
  const t=harness(); await t.mounted;
  for (const address of ['http://LOCALHOST:11434/v1/', '']) {
    t.input('AI 服务地址').value=address; await t.input('AI 服务地址').dispatchEvent('input');
    assert.equal(t.input('停用已配置密钥').closest('label').hidden,false, address || 'default address');
    assert.match(t.document.querySelector('.settings-key-hint').textContent,/本次服务中有效/);
  }
  t.input('AI 服务地址').value='http://localhost:11434/v2'; await t.input('AI 服务地址').dispatchEvent('input');
  assert.equal(t.input('停用已配置密钥').closest('label').hidden,true);
  t.context.unmount();
});

function optionalEnvironment() {
  const installed = id => ({id, name: id === 'faker' ? 'Faker' : id.toUpperCase(), available: true, installed: true, version: '2.0'});
  const missing = (id, distribution) => ({id, name: id.toUpperCase(), available: false, installed: false, requirement: 'optional', install_command: `'/Web Env/python' -m pip install '${distribution}'`});
  return {
    python: {implementation: 'CPython', version: '3.13.4'}, installer: {available: true, shell: 'posix'},
    packages: [installed('core'), installed('web'), missing('ai', 'sqlseed-web[ai]'), missing('cli', 'sqlseed-cli'), missing('mcp', 'mcp-server-sqlseed')],
    providers: [{...installed('base'), requirement: 'builtin'}, installed('faker'), missing('mimesis', 'sqlseed[mimesis]')],
  };
}
const packagePanel = (t, id = 'ai') => t.document.querySelector(`[data-package-id="${id}"]`);
const copyButton = panel => panel.querySelector('[data-install-copy]');
const copyFeedback = panel => panel.querySelector('[data-install-copy-status]');

test('unmanaged missing packages keep administrator commands collapsed while required components stay compact', async () => {
  const environment = optionalEnvironment();
  const t = harness({request: call => call.url.endsWith('/environment') ? environment : undefined}); await t.mounted;
  await t.find('插件与版本').click();
  for (const id of ['ai', 'cli', 'mcp', 'mimesis']) {
    const panel = packagePanel(t, id), guide = panel.querySelector('details');
    assert.equal(guide.getAttribute('open'), null, `${id} administrator details should be collapsed`);
    assert.equal(copyButton(panel)?.textContent, '复制命令', id);
    assert.equal(panel.querySelector('code').textContent, [...environment.packages, ...environment.providers].find(item => item.id === id).install_command);
  }
  for (const id of ['core', 'web', 'faker', 'base']) {
    assert.equal(packagePanel(t, id).querySelector('details'), null, id);
    assert.equal(copyButton(packagePanel(t, id)), null, id);
  }
  assert.match(t.document.querySelector('#settings-plugins').textContent, /运行 Web 的设备终端/);
  assert.match(t.document.querySelector('#settings-plugins').textContent, /重启.*刷新/);
  assert.equal(t.document.querySelector('[data-plugin-action="uninstall"]'), null);
  assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('copying preserves server command quotes and whitespace and only reports completed writes', async () => {
  const environment = optionalEnvironment(), gate = deferred(), copied = [];
  const command = "  & 'C:\\Python Env\\python.exe' '-m' 'pip' 'install' 'sqlseed-web[ai]'\n";
  environment.packages.find(item => item.id === 'ai').install_command = command;
  environment.installer.shell = 'powershell';
  const t = harness({clipboard: {writeText: text => {copied.push(text); return gate.promise;}}, request: call => call.url.endsWith('/environment') ? environment : undefined}); await t.mounted;
  await t.find('插件与版本').click();
  const panel = packagePanel(t), copy = copyButton(panel);
  assert.ok(copy, 'copy command is available beside the command');
  const pending = copy.click(); await tick();
  assert.equal(copy.disabled, true); assert.equal(copy.textContent, '复制中…');
  assert.doesNotMatch(copyFeedback(panel).textContent, /已复制/);
  await copy.dispatchEvent('click'); assert.deepEqual(copied, [command]);
  gate.resolve(); await pending;
  assert.equal(panel.querySelector('code').textContent, command);
  assert.match(copyFeedback(panel).textContent, /已复制/);
  assert.equal(copyFeedback(panel).getAttribute('role'), 'status');
  assert.equal(copy.disabled, false);
  assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
  t.context.unmount();
});

test('AI activation and broken package guidance share copying of the server repair command', async () => {
  const check = "'/Web Env/python' -m pip check", copied = [], environment = optionalEnvironment();
  Object.assign(environment.packages.find(item => item.id === 'ai'), {installed: true, repair_command: check});
  const t = harness({config: {available: false, availability_status: 'import_error', repair_command: check, installer: environment.installer},
    clipboard: {writeText: async text => {copied.push(text);}}, request: call => call.url.endsWith('/environment') ? environment : undefined}); await t.mounted;
  const activation = t.document.querySelector('[data-ai-install]');
  assert.ok(copyButton(activation), 'AI activation exposes the shared copy action');
  await copyButton(activation).click(); assert.match(copyFeedback(activation).textContent, /已复制/);
  await t.find('插件与版本').click();
  const panel = packagePanel(t);
  assert.equal(panel.querySelector('details').getAttribute('open'), null);
  assert.match(panel.querySelector('summary').textContent, /修复指引/);
  await copyButton(panel).click();
  assert.deepEqual(copied, [check, check]); assert.equal(panel.querySelector('code').textContent, check);
  t.context.unmount();
});

test('a denied clipboard write keeps the command available with manual-copy recovery', async () => {
  const command = "'/Web Env/python' -m pip install 'sqlseed-web[ai]'";
  const t = harness({config: {available: false, install_command: command}, clipboard: {writeText: async () => {throw new Error('permission denied');}}}); await t.mounted;
  const panel = t.document.querySelector('[data-ai-install]'), copy = copyButton(panel);
  assert.ok(copy); await copy.click();
  assert.match(copyFeedback(panel).textContent, /复制失败.*手动/);
  assert.doesNotMatch(copyFeedback(panel).textContent, /已复制/);
  assert.equal(panel.querySelector('code').textContent, command); assert.equal(copy.disabled, false);
  t.context.unmount();
});

test('missing clipboard and writeText APIs offer manual copying without fabricating success', async () => {
  for (const clipboard of [undefined, {}]) {
    const command = "'/Web Env/python' -m pip install 'sqlseed-web[ai]'";
    const t = harness({config: {available: false, install_command: command}, clipboard}); await t.mounted;
    const panel = t.document.querySelector('[data-ai-install]'), copy = copyButton(panel);
    assert.ok(copy); await copy.click();
    assert.match(copyFeedback(panel).textContent, /无法自动复制.*手动/);
    assert.doesNotMatch(copyFeedback(panel).textContent, /已复制/);
    assert.equal(panel.querySelector('code').textContent, command); assert.equal(copy.disabled, false);
    assert.doesNotMatch(panel.textContent, /\bnull\b/);
    assert.equal(t.calls.filter(call => call.method !== 'GET').length, 0);
    t.context.unmount();
  }
});

test('manual installer guidance has no copy action when no runnable command was supplied', async () => {
  const t = harness({config: {available: false, install_command: null, installer: {available: false, message: '请使用创建该环境的工具安装'}}}); await t.mounted;
  const panel = t.document.querySelector('[data-ai-install]');
  assert.equal(copyButton(panel), null); assert.equal(panel.querySelector('code'), null);
  assert.match(panel.textContent, /创建该环境的工具安装/);
  t.context.unmount();
});

test('refresh invalidates pending copy feedback and leaves the old command retryable after failure', async () => {
  const gate = deferred(), refresh = deferred(), environment = optionalEnvironment(); let reads = 0, writes = 0;
  const t = harness({clipboard: {writeText: () => ++writes === 1 ? gate.promise : Promise.resolve()}, request: async call => {
    if (call.url.endsWith('/environment')) {if (++reads === 1) return environment; await refresh.promise; throw new Error('temporarily unavailable');}
  }}); await t.mounted;
  await t.find('插件与版本').click();
  const panel = packagePanel(t), copy = copyButton(panel);
  assert.ok(copy);
  const pending = copy.click(); await tick();
  const refreshing = t.find('刷新状态').click(); await tick();
  const before = copyFeedback(panel).textContent;
  gate.resolve(); await pending;
  assert.equal(copyFeedback(panel).textContent, before); assert.equal(copy.disabled, false);
  refresh.resolve(); await refreshing;
  assert.match(t.document.querySelector('#settings-plugins').textContent, /无法刷新/);
  await copy.click(); assert.match(copyFeedback(panel).textContent, /已复制/); assert.equal(writes, 2);
  t.context.unmount();
});

test('a late old command copy cannot publish into a refreshed package list', async () => {
  const gate = deferred(), environment = optionalEnvironment(); let writes = 0;
  const t = harness({clipboard: {writeText: () => ++writes === 1 ? gate.promise : Promise.resolve()}, request: call => call.url.endsWith('/environment') ? environment : undefined}); await t.mounted;
  await t.find('插件与版本').click();
  const oldPanel = packagePanel(t), oldCopy = copyButton(oldPanel);
  assert.ok(oldCopy);
  const pending = oldCopy.click(); await tick();
  environment.packages.find(item => item.id === 'ai').install_command = "'/New Env/python' -m pip install 'sqlseed-web[ai]'";
  await t.find('刷新状态').click();
  const newPanel = packagePanel(t);
  assert.notEqual(newPanel, oldPanel);
  assert.equal(newPanel.querySelector('code').textContent, environment.packages.find(item => item.id === 'ai').install_command);
  await copyButton(newPanel).click();
  const oldText = oldPanel.textContent, newText = newPanel.textContent;
  gate.resolve(); await pending;
  assert.equal(oldPanel.textContent, oldText); assert.equal(newPanel.textContent, newText);
  t.context.unmount();
});

test('editing settings invalidates pending copy feedback without leaving its button disabled', async () => {
  const gate = deferred(), environment = optionalEnvironment();
  const t = harness({clipboard: {writeText: () => gate.promise}, request: call => call.url.endsWith('/environment') ? environment : undefined}); await t.mounted;
  await t.find('插件与版本').click();
  const panel = packagePanel(t), copy = copyButton(panel);
  assert.ok(copy);
  const pending = copy.click(); await tick();
  t.input('模型名称').value = 'changed'; await t.input('模型名称').dispatchEvent('input');
  const before = copyFeedback(panel).textContent;
  gate.resolve(); await pending;
  assert.equal(copyFeedback(panel).textContent, before); assert.equal(copy.disabled, false);
  assert.equal(t.input('模型名称').value, 'changed');
  assert.doesNotMatch(copyFeedback(panel).textContent, /已复制/);
  t.context.unmount();
});

test('leaving and remounting settings blocks late copy results and detached button actions', async () => {
  const gate = deferred(), command = "'/Web Env/python' -m pip install 'sqlseed-web[ai]'"; let writes = 0;
  const t = harness({config: {available: false, install_command: command}, clipboard: {writeText: () => {writes++; return gate.promise;}}}); await t.mounted;
  const oldPanel = t.document.querySelector('[data-ai-install]'), oldCopy = copyButton(oldPanel);
  assert.ok(oldCopy);
  const pending = oldCopy.click(); await tick();
  t.context.unmount(); t.document.body.replaceChildren(t.context.render()); await t.context.mount();
  const oldText = oldPanel.textContent, currentText = t.document.textContent;
  gate.resolve(); await pending;
  assert.equal(oldPanel.textContent, oldText); assert.equal(t.document.textContent, currentText);
  await oldCopy.dispatchEvent('click'); assert.equal(writes, 1);
  assert.doesNotMatch(copyFeedback(t.document.querySelector('[data-ai-install]')).textContent, /已复制/);
  t.context.unmount();
});

test('section changes, edits, and refresh start cannot release an unfinished clipboard write', async () => {
  for (const boundary of ['section', 'edit', 'refresh']) {
    const gate = deferred(), refreshed = deferred(), environment = optionalEnvironment(); let reads = 0, writes = 0;
    const t = harness({clipboard: {writeText: () => {writes++; return gate.promise;}}, request: call => {
      if (call.url.endsWith('/environment')) return ++reads === 1 ? environment : refreshed.promise;
    }}); await t.mounted;
    await t.find('插件与版本').click();
    const panel = packagePanel(t), copy = copyButton(panel);
    const pending = copy.click(); await tick();
    let refreshing;
    if (boundary === 'section') {await t.find('AI 服务').click(); await t.find('插件与版本').click();}
    if (boundary === 'edit') {t.input('模型名称').value = 'edited'; await t.input('模型名称').dispatchEvent('input');}
    if (boundary === 'refresh') {refreshing = t.find('刷新状态').click(); await tick();}
    assert.equal(copy.disabled, true, boundary);
    await copy.dispatchEvent('click'); assert.equal(writes, 1, boundary);
    gate.resolve(); await pending;
    assert.equal(copy.disabled, false); assert.doesNotMatch(copyFeedback(panel).textContent, /已复制/);
    await copy.click(); assert.equal(writes, 2);
    if (refreshing) {refreshed.resolve(environment); await refreshing;}
    t.context.unmount();
  }
});
