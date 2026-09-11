const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};
const enabled = () => ({enabled: true, available: true, token: 'management-token', python_executable: '/env/python', restart_required: false, active_task: null,
  components: [{id: 'ai', installed: false, can_install: true}, {id: 'cli', installed: true, can_uninstall: false, reason: '被 mcp-server-sqlseed 依赖', required_by: ['mcp-server-sqlseed']}, {id: 'mimesis', installed: true, can_uninstall: true}]});
const plan = {plan_id: 'plan-1', component_id: 'ai', action: 'install', distribution: 'sqlseed-ai', version: '1.2.3', summary: '安装 sqlseed-ai==1.2.3', warnings: ['安装会更新此 Python 环境，完成后必须重启 Web。'], expires_in: 300};
const running = {task_id: 'task-1', component_id: 'ai', action: 'install', status: 'running', output: ['正在下载 sqlseed-ai'], message: '安装进行中', restart_required: false, returncode: null};

function harness({management = enabled(), request} = {}) {
  const document = createDom(), calls = [], timers = new Map(); let timerId = 0;
  document.createElementNS = (_, tag) => new Element(tag);
  const ui = loadFrontend('workbench/ui.js', {document});
  const api = async (url, options = {}) => {
    const call = {url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null, headers: options.headers, signal: options.signal}; calls.push(call);
    const value = await request?.(call); if (value !== undefined) return value;
    if (url.endsWith('/management')) return management;
    if (url.endsWith('/plan')) return plan;
    if (url.endsWith('/execute') || url.includes('/tasks/')) return running;
    throw new Error(`Unexpected request ${url}`);
  };
  const context = loadFrontend('workbench/plugin-management.js', {document, api, AbortController, ...vm.runInContext('({button, modal})', ui),
    setTimeout: (callback, delay) => {timers.set(++timerId, {callback, delay}); return timerId;}, clearTimeout: id => timers.delete(id)});
  const rows = new Element('div'), modes = [], restored = [];
  const manager = context.createPluginManagement({onRestored: value => restored.push(value), onMode: value => modes.push(value), onChange: () => {
    rows.replaceChildren();
    for (const id of ['core', 'web', 'base', 'faker', 'ai', 'cli', 'mimesis']) {
      const element = manager.controls({id}); if (element) {element.setAttribute('data-component', id); rows.append(element);}
    }
  }, command: value => new Element('code', value)});
  document.body.append(manager.el, rows);
  const mounted = manager.refresh();
  const find = label => document.querySelectorAll('button').find(element => element.textContent === label);
  const action = (id, value) => document.querySelector(`[data-component="${id}"]`)?.querySelector(`[data-plugin-action="${value}"]`);
  const runTimer = async delay => {const item = [...timers].find(([, timer]) => timer.delay === delay); assert.ok(item, `timer ${delay}`); timers.delete(item[0]); await item[1].callback(); await tick();};
  return {document, manager, management, mounted, calls, timers, modes, restored, find, action, runTimer};
}

const automatic = () => ({...enabled(), automatic_lifecycle: true, phase: 'ready', instance_id: 'service-1', service_generation: 1});

test('managed operation keeps normal settings usable and exposes no command-line setup', async () => {
  const t = harness({management: automatic()}); await t.mounted;
  assert.equal(t.modes.at(-1), false);
  assert.equal(t.manager.maintenance, false);
  assert.ok(t.action('ai', 'install'));
  assert.doesNotMatch(t.document.textContent, /先停止|重启 Web|目标解释器/);
  assert.match(t.document.textContent, /自动/);
  t.manager.destroy();
});

test('managed task reconnects after a worker switch, refreshes capabilities and never repeats execute', async () => {
  let polls = 0, complete = false;
  const t = harness({management: automatic(), request: call => {
    if (call.url.includes('/tasks/')) {
      if (++polls === 1) throw new Error('connection reset during worker replacement');
      complete = true;
      return {...running, status: 'succeeded', stage: 'ready', service_ready: true, message: '已安装，服务已恢复。'};
    }
    if (call.url.endsWith('/management') && complete) return {...automatic(), service_generation: 2, components: [{id: 'ai', installed: true, can_uninstall: true}]};
  }}); await t.mounted; await t.action('ai', 'install').click(); await t.find('确认安装').click();
  await t.runTimer(1000); assert.match(t.document.textContent, /重新连接/);
  assert.equal(t.action('ai', 'install').disabled, true);
  await t.runTimer(1000); await tick();
  assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
  assert.equal(t.action('ai', 'install'), null); assert.ok(t.action('ai', 'uninstall'));
  assert.equal(t.restored.length, 1); assert.equal(t.timers.size, 0);
  t.manager.destroy();
});

test('a rejected busy operation reports the reason without pretending the result is unknown', async () => {
  const t = harness({management: automatic(), request: call => {
    if (call.url.endsWith('/execute')) throw Object.assign(new Error('当前有 1 项数据生成任务，请完成后重试。'), {status: 409, detail: {code: 'plugin_management_busy'}});
  }}); await t.mounted; await t.action('ai', 'install').click(); await t.find('确认安装').click();
  assert.match(t.document.textContent, /1 项数据生成任务/);
  assert.doesNotMatch(t.document.textContent, /提交结果未知/);
  assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
  t.manager.destroy();
});

test('uninstall review explains the affected Mimesis feature before any execution', async () => {
  const t=harness({management:automatic(),request:call=>call.url.endsWith('/plan')?{...plan,component_id:'mimesis',action:'uninstall',distribution:'mimesis'}:undefined}); await t.mounted;
  await t.action('mimesis','uninstall').click();
  const dialog=t.document.querySelector('[role="dialog"]');
  assert.match(dialog.textContent,/卸载后.*Mimesis.*预览或生成/);
  assert.match(dialog.textContent,/重新安装|其他.*引擎/);
  assert.equal(t.calls.some(call=>call.url.endsWith('/execute')),false);
  await t.find('取消').click(); t.manager.destroy();
});

test('managed completion retries a disconnected capability refresh without repeating the operation', async () => {
  let completed = false, snapshots = 0;
  const t = harness({management: automatic(), request: call => {
    if (call.url.includes('/tasks/')) {completed = true; return {...running, status: 'succeeded', service_ready: true};}
    if (call.url.endsWith('/management') && completed) {
      if (++snapshots === 1) throw new Error('temporary reconnect');
      return {...automatic(), service_generation: 2, components: [{id: 'ai', can_uninstall: true}]};
    }
  }}); await t.mounted; await t.action('ai', 'install').click(); await t.find('确认安装').click();
  await t.runTimer(1000); await t.runTimer(1000);
  assert.ok(t.action('ai', 'uninstall')); assert.equal(t.restored.length, 1);
  assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
  assert.equal(t.timers.size, 0); t.manager.destroy();
});

test('recovery accepts the management snapshot and follows service restoration without rerunning installation', async () => {
  let restored = false;
  const t = harness({management: {...automatic(), phase: 'recovery_failed', active_task: {...running, status: 'failed'}}, request: call => {
    if (call.url.endsWith('/recover')) return {...automatic(), phase: 'restoring', active_task: {...running, stage: 'restoring'}};
    if (call.url.includes('/tasks/')) {restored = true; return {...running, status: 'succeeded', service_ready: true};}
    if (call.url.endsWith('/management') && restored) return {...automatic(), service_generation: 2};
  }}); await t.mounted; await t.find('重试恢复服务').click();
  assert.doesNotMatch(t.document.textContent, /恢复结果暂时未知/);
  await t.runTimer(1000);
  assert.equal(t.restored.length, 1);
  assert.equal(t.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(t.calls.filter(call => call.url.endsWith('/recover')).length, 1);
  assert.equal(t.timers.size, 0); t.manager.destroy();
});

test('recovery without a package task polls management until ready and discloses the lost session', async () => {
  let recovering = false, snapshots = 0;
  const lost = {session_lost: true, message: '原有连接与会话密钥需要重新配置。'};
  const t = harness({management: {...automatic(), phase: 'recovery_failed', session_restore: lost}, request: call => {
    if (call.url.endsWith('/recover')) {recovering = true; return {...automatic(), phase: 'restoring', session_restore: lost};}
    if (call.url.endsWith('/management') && recovering) {
      if (++snapshots === 1) throw new Error('worker reconnect');
      return {...automatic(), service_generation: 2, session_restore: lost};
    }
  }}); await t.mounted; await t.find('重试恢复服务').click();
  await t.runTimer(1000); await t.runTimer(1000);
  assert.match(t.document.textContent, /原有连接与会话密钥需要重新配置/);
  assert.equal(t.restored.length, 1); assert.equal(t.timers.size, 0);
  assert.equal(t.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(t.calls.some(call => call.url.includes('/tasks/')), false); t.manager.destroy();
});

test('an unmanaged deployment explains unavailable controls without making commands the user workflow', async () => {
  const t = harness({management: {enabled: false, available: false, maintenance_command: "'/Web Env/python' -m sqlseed_web --plugin-maintenance"}}); await t.mounted;
  assert.equal(t.document.querySelector('code'), null);
  assert.equal(t.document.querySelector('[data-plugin-action]'), null);
  assert.match(t.document.textContent, /联系应用管理员/);
  assert.doesNotMatch(t.document.textContent, /--plugin-maintenance|先停止 Web/);
  assert.equal(t.calls.length, 1); t.manager.destroy();
});

test('a concrete plan is reviewed before exactly one token-bound execution and truthful restart', async () => {
  const gate = deferred();
  const t = harness({request: call => call.url.endsWith('/execute') ? gate.promise : call.url.includes('/tasks/') ? {...running, status: 'succeeded', output: ['Successfully installed sqlseed-ai-1.2.3'], message: '安装完成', restart_required: true, returncode: 0} : undefined}); await t.mounted;
  await t.action('ai', 'install').click();
  assert.equal(t.calls.some(call => call.url.endsWith('/execute')), false);
  const dialog = t.document.querySelector('[role="dialog"]'); assert.ok(dialog);
  assert.match(dialog.textContent, /sqlseed-ai.*1.2.3/); assert.match(dialog.textContent, /\/env\/python/); assert.match(dialog.textContent, /重启 Web/);
  const confirm = t.find('确认安装'), pending = confirm.click(); await tick();
  await confirm.dispatchEvent('click');
  const posts = t.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[0].body, {component_id: 'ai', action: 'install'});
  assert.deepEqual(posts[1].body, {plan_id: 'plan-1'});
  for (const call of posts) {assert.equal(call.headers['X-Sqlseed-Management-Token'], 'management-token'); assert.equal(call.headers['Content-Type'], 'application/json');}
  gate.resolve(running); await pending;
  assert.match(t.document.textContent, /正在下载 sqlseed-ai/); assert.equal(t.action('mimesis', 'uninstall').disabled, true);
  await t.runTimer(1000);
  assert.match(t.document.textContent, /安装完成/); assert.match(t.document.textContent, /退出维护模式/);
  assert.equal(t.action('ai', 'install').disabled, true);
  assert.equal(t.timers.size, 0); t.manager.destroy();
});

test('server capability flags, required dependencies, and token absence restrict actions', async () => {
  const t = harness(); await t.mounted;
  assert.equal(t.action('cli', 'uninstall'), null); assert.match(t.document.textContent, /mcp-server-sqlseed/);
  for (const id of ['core', 'web', 'base', 'faker']) assert.equal(t.document.querySelector(`[data-component="${id}"]`), null);
  t.management.token = ''; await t.manager.refresh();
  assert.equal(t.action('ai', 'install')?.disabled ?? true, true); t.manager.destroy();
});

test('a plan expires without executing or automatically refreshing its authorization', async () => {
  const t = harness(); await t.mounted; await t.action('ai', 'install').click();
  await t.runTimer(300000);
  assert.match(t.document.querySelector('[role="dialog"]').textContent, /已过期/);
  assert.equal(t.find('确认安装').disabled, true);
  await t.find('确认安装').dispatchEvent('click');
  assert.equal(t.calls.some(call => call.url.endsWith('/execute')), false);
  await t.find('取消').click(); assert.equal(t.manager.busy, false); t.manager.destroy();
});

test('closing review makes its detached confirmation inert', async () => {
  const t = harness(); await t.mounted; await t.action('ai', 'install').click();
  const confirm = t.find('确认安装'); await t.find('取消').click();
  await confirm.dispatchEvent('click'); assert.equal(t.calls.some(call => call.url.endsWith('/execute')), false);
  assert.equal(t.manager.busy, false); assert.equal(t.timers.size, 0); t.manager.destroy();
});

test('late planning after leaving cannot open a dialog or mutate a new page', async () => {
  const gate = deferred(); const t = harness({request: call => call.url.endsWith('/plan') ? gate.promise : undefined}); await t.mounted;
  const pending = t.action('ai', 'install').click(); await tick(); t.manager.destroy();
  const before = t.document.textContent; gate.resolve(plan); await pending;
  assert.equal(t.document.querySelector('[role="dialog"]'), null); assert.equal(t.document.textContent, before);
});

test('leaving cancels polling and rejects late task results', async () => {
  const gate = deferred(); const t = harness({management: {...enabled(), active_task: running}, request: call => call.url.includes('/tasks/') ? gate.promise : undefined}); await t.mounted;
  assert.match(t.document.textContent, /正在下载/);
  const poll = t.runTimer(1000); await tick(); t.manager.destroy(); const before = t.document.textContent;
  gate.resolve({...running, status: 'succeeded', message: 'late-success', restart_required: true}); await poll;
  assert.equal(t.document.textContent, before); assert.equal(t.timers.size, 0);
});

test('polling failure preserves running output and offers a read-only status retry', async () => {
  let broken = true;
  const t = harness({management: {...enabled(), active_task: running}, request: call => {
    if (call.url.includes('/tasks/')) {if (broken) throw new Error('网络断开'); return {...running, status: 'failed', message: 'pip 安装失败', restart_required: true, output: ['Error: no matching distribution'], returncode: 1};}
  }}); await t.mounted; await t.runTimer(1000);
  assert.match(t.document.textContent, /状态暂时未知/); assert.match(t.document.textContent, /正在下载/);
  assert.equal(t.action('ai', 'install').disabled, true); assert.equal(t.timers.size, 0);
  broken = false; await t.find('重新读取任务状态').click();
  assert.match(t.document.textContent, /pip 安装失败/); assert.match(t.document.textContent, /no matching distribution/);
  assert.equal(t.calls.some(call => call.method === 'POST'), false); t.manager.destroy();
});

test('an uncertain execute response never retries and requires a status refresh before further operations', async () => {
  const t = harness({request: call => {if (call.url.endsWith('/execute')) throw new Error('connection closed');}}); await t.mounted;
  await t.action('ai', 'install').click(); await t.find('确认安装').click();
  assert.match(t.document.textContent, /提交结果未知/);
  assert.equal(t.action('mimesis', 'uninstall').disabled, true);
  assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
  t.management.active_task = running; await t.manager.refresh();
  assert.match(t.document.textContent, /正在下载/); assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
  t.manager.destroy(); assert.equal(t.timers.size, 0);
});

test('an older server keeps guidance available with a clear unavailable management status', async () => {
  const t = harness({request: call => {if (call.url.endsWith('/management')) throw new Error('HTTP 404');}}); await t.mounted;
  assert.match(t.document.textContent, /无法读取插件管理状态.*404/);
  assert.equal(t.document.querySelector('[data-plugin-action]'), null); assert.equal(t.manager.enabled, false); t.manager.destroy();
});

test('an expanded task output stays open across progress polling', async () => {
  const t = harness({management: {...enabled(), active_task: running}}); await t.mounted;
  t.document.querySelector('[data-plugin-output]').open = true;
  await t.runTimer(1000);
  assert.equal(t.document.querySelector('[data-plugin-output]').open, true); t.manager.destroy();
});

test('an execution finishing after leaving cannot update the detached page or start polling', async () => {
  const gate = deferred(); const t = harness({request: call => call.url.endsWith('/execute') ? gate.promise : undefined}); await t.mounted;
  await t.action('ai', 'install').click(); const pending = t.find('确认安装').click(); await tick();
  t.manager.destroy(); const before = t.document.textContent;
  gate.resolve(running); await pending;
  assert.equal(t.document.textContent, before); assert.equal(t.timers.size, 0);
  assert.equal(t.calls.filter(call => call.url.endsWith('/execute')).length, 1);
});

test('a missing old task after a service restart recovers through a fresh management snapshot', async () => {
  const t = harness({management: {...enabled(), active_task: running}, request: call => {if (call.url.includes('/tasks/')) throw new Error('HTTP 404');}}); await t.mounted;
  await t.runTimer(1000); assert.match(t.document.textContent, /状态暂时未知/);
  t.management.active_task = null; t.management.token = 'new-token'; await t.manager.refresh();
  assert.doesNotMatch(t.document.textContent, /状态暂时未知/);
  assert.equal(t.action('ai', 'install').disabled, false);
  assert.equal(t.calls.some(call => call.method === 'POST'), false); t.manager.destroy();
});
