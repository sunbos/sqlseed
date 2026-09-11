import { h, api } from '../api.js';
import { button, modal } from './ui.js';

const prefix = '/api/settings/plugins';
const managed = new Set(['ai', 'cli', 'mcp', 'mimesis']);

export function componentImpact(id) {
  return {
    ai:'AI 规则建议与分析不可用；手动配置、预览和生成数据仍可使用。',
    cli:'终端 sqlseed 命令不可用；网页中的手动配置、预览和生成数据仍可使用。',
    mcp:'MCP 客户端调用 sqlseed 的功能不可用；网页工作台仍可使用。',
    mimesis:'使用 Mimesis 的配置暂时无法预览或生成数据；请重新安装，或主动改用其他可用引擎。',
  }[id] || '';
}

export function createPluginManagement({onChange = () => {}, onMode = () => {}, onRestored = () => {}, initialEnabled = false}) {
  let active = true, version = 0, info = {enabled: initialEnabled}, pending = false, error = '', uncertain = false;
  let task = null, taskError = '', polling = false, timer = null, review = null, reconnects = 0, generation = null, syncing = false;
  const controllers = new Set();
  const el = h('section', {class: 'settings-management', 'aria-label': '插件管理'}, h('p', {}, '正在读取插件管理状态…'));
  const current = expected => active && expected === version;
  const automatic = () => info?.automatic_lifecycle === true;
  const maintenance = () => Boolean(info?.enabled) && !automatic();
  const busy = () => pending || Boolean(review) || task?.status === 'running';
  const locked = () => busy() || uncertain || syncing || !info?.token || Boolean(info?.restart_required);
  async function request(path, body) {
    const controller = new AbortController(); controllers.add(controller);
    try {
      return await api(`${prefix}/${path}`, {signal: controller.signal,
        ...(body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Sqlseed-Management-Token': info.token}, body: JSON.stringify(body)} : {})});
    } finally {controllers.delete(controller);}
  }
  function draw() {
    const outputOpen = Boolean(el.querySelector('[data-plugin-output]')?.open) || task?.status === 'failed';
    const environmentOpen = Boolean(el.querySelector('[data-plugin-environment]')?.open);
    el.replaceChildren(h('h3', {}, maintenance() ? '插件维护模式' : '组件管理'),
      h('p', {}, error || (automatic() ? info.reason || '按需安装或卸载可选组件，完成后自动生效。' : maintenance() ? info.reason || '可在此环境中安装或卸载可选组件。' : '此部署暂不支持网页内管理组件，请联系应用管理员。')));
    if (info?.python_executable) {const environment = h('details', {class:'settings-management-environment', 'data-plugin-environment':''}, h('summary', {}, '环境信息'), h('p', {class:'mono'}, info.python_executable)); environment.open = environmentOpen; el.append(environment);}
    if (info?.restart_required && !automatic()) el.append(h('p', {class: 'settings-management-restart', role: 'status'},
      task?.status === 'running' ? '任务结束后，停止 Web 并退出维护模式；重新启动普通模式后验证组件。' : '环境已发生变更。请停止 Web，退出维护模式后重新启动普通模式，再验证组件可用性。'));
    if (pending) el.append(h('p', {class: 'settings-notice', role: 'status'}, '正在处理，请稍候…'));
    if (task) {
      const state = taskError ? automatic() && reconnects < 30 ? '重新连接中' : '状态暂时未知' : {running: '执行中', succeeded: '已完成', failed: '执行失败'}[task.status] || '状态暂时未知';
      const progress = h('section', {class: 'settings-plugin-task', 'aria-label': '插件任务', 'aria-busy': String(task.status === 'running')},
        h('h4', {}, `${task.action === 'uninstall' ? '卸载' : '安装'} ${{ai:'AI',cli:'CLI',mcp:'MCP',mimesis:'Mimesis'}[task.component_id] || task.component_id} · ${state}`),
        h('p', {role: 'status', 'aria-live': 'polite'}, taskError || task.message || state));
      if (automatic() && task.status === 'running') progress.append(h('ol', {class:'settings-plugin-stages', 'aria-label':'处理阶段'},
        ...[['preparing','准备'],['installing','处理组件'],['restoring','恢复服务']].map(([stage,label]) => h('li', {'aria-current':task.stage===stage?'step':'false'}, label))));
      if (task.output?.length) {
        const output = h('details', {'data-plugin-output': ''}, h('summary', {}, '查看执行输出'), h('pre', {class: 'settings-plugin-output'}, task.output.join('\n')));
        output.open = outputOpen; progress.append(output);
      }
      if (Number.isInteger(task.returncode) && !automatic()) progress.append(h('p', {class: 'muted'}, `退出码：${task.returncode}`));
      if (taskError && (!automatic() || reconnects >= 30)) progress.append(button('重新读取任务状态', poll, {small: true, disabled: polling}));
      el.append(progress);
    }
    if (automatic() && info?.phase === 'recovery_failed') el.append(button('重试恢复服务', recover, {small:true, disabled:busy()}));
    if (info?.session_restore?.session_lost) el.append(h('p', {class:'settings-management-restart', role:'status'},
      info.session_restore.message || '服务意外退出，原连接和会话密钥需要重新配置。'));
    if (info?.session_restore?.failed_connections?.length) el.append(h('section', {class:'settings-management-restart', role:'status'},
      h('strong', {}, '部分数据库连接未恢复'),
      ...info.session_restore.failed_connections.map(item => h('p', {}, item.message || '请检查数据库连接后重新连接。'))));
    onChange();
  }
  async function refresh() {
    if (!active || pending || review) return;
    const expected = ++version; pending = true; error = ''; clearTimeout(timer); polling = false;
    for (const controller of controllers) controller.abort();
    draw();
    try {
      const response = await request('management');
      if (!current(expected)) return;
      await receiveManagement(response);
    } catch (failure) {
      if (!current(expected)) return;
      error = `无法读取插件管理状态：${failure.message}。可稍后刷新状态。`;
      if (automatic() && (uncertain || syncing) && ++reconnects < 30) {error = '正在重新连接服务并核对操作结果，不会重复提交。'; timer = setTimeout(refresh, 1000);}
    } finally {if (current(expected)) {pending = false; draw();}}
  }
  async function receiveManagement(response) {
    const nextGeneration = response.automatic_lifecycle ? `${response.instance_id}:${response.service_generation}` : null;
    const restored = generation !== null && nextGeneration !== generation && response.phase === 'ready';
    if (nextGeneration !== null) generation = nextGeneration;
    info = response; uncertain = false; syncing = false; error = ''; taskError = ''; task = null; reconnects = 0; onMode(maintenance());
    if (response.active_task) receiveTask(typeof response.active_task === 'string' ? {task_id: response.active_task, status: 'running'} : response.active_task);
    else if (automatic() && ['preparing', 'installing', 'restoring'].includes(response.phase)) {
      syncing = true; timer = setTimeout(refresh, 1000);
    }
    if (restored) await onRestored(response);
  }
  function allowed(id, action) {
    return active && managed.has(id) && info?.enabled && info.available && !error &&
      Boolean(info.components?.find(value => value.id === id)?.[action === 'install' ? 'can_install' : 'can_uninstall']);
  }
  async function prepare(id, action) {
    if (locked() || !allowed(id, action)) return;
    const expected = version; pending = true; error = ''; draw();
    try {
      const plan = await request('plan', {component_id: id, action});
      if (!current(expected)) return;
      if (!plan.plan_id || plan.component_id !== id || plan.action !== action || !(plan.expires_in > 0)) throw new Error('服务返回的计划与所选操作不一致，请刷新状态。');
      showReview(plan);
    } catch (failure) {if (current(expected)) error = `无法生成操作计划：${failure.message}`;}
    finally {if (current(expected)) {pending = false; draw();}}
  }
  function showReview(plan) {
    const operation = plan.action === 'install' ? '安装' : '卸载';
    const confirmation = {plan, expired: false, expiresAt: Date.now() + plan.expires_in * 1000, dialog: null, timer: null};
    const dialog = modal(`确认${operation}插件`, {onClose: () => {
      clearTimeout(confirmation.timer);
      if (review === confirmation) review = null;
      if (active) draw();
    }});
    confirmation.dialog = dialog; review = confirmation;
    const expiry = h('p', {class: 'muted', role: 'status'}, `此计划 ${Math.ceil(plan.expires_in / 60)} 分钟内有效。`);
    const details = h('dl', {class: 'settings-plugin-plan'}, h('dt', {}, '组件'), h('dd', {class: 'mono'}, plan.distribution),
      h('dt', {}, '版本'), h('dd', {class: 'mono'}, plan.version || '兼容版本'),
      h('dt', {}, '目标环境'), h('dd', {class: 'mono'}, info.python_executable || '当前应用环境'));
    dialog.body.append(h('p', {}, automatic() ? `${operation} ${{ai:'AI',cli:'CLI',mcp:'MCP',mimesis:'Mimesis'}[plan.component_id] || plan.distribution}` : plan.summary),
      ...(plan.action === 'uninstall' && componentImpact(plan.component_id) ? [h('p', {class:'settings-component-impact'}, `卸载后，${componentImpact(plan.component_id)}`)] : []),
      automatic() ? h('details', {class:'settings-management-environment'}, h('summary', {}, '技术信息'), details) : details,
      h('ul', {class: 'settings-plugin-warnings'}, ...(plan.warnings || []).map(warning => h('li', {}, warning))), expiry);
    const confirm = button(`确认${operation}`, () => execute(confirmation), {primary: true, 'data-plugin-confirm': ''});
    dialog.actions.append(button('取消', dialog.close), confirm);
    confirmation.timer = setTimeout(() => {
      if (!active || review !== confirmation) return;
      confirmation.expired = true; confirm.disabled = true; expiry.textContent = '计划已过期。请取消后重新生成并确认计划。';
    }, plan.expires_in * 1000);
  }
  async function execute(confirmation) {
    if (!active || pending || review !== confirmation || confirmation.expired || Date.now() >= confirmation.expiresAt) return;
    const expected = version; pending = true; error = ''; uncertain = true;
    confirmation.dialog.close(); draw();
    try {
      const response = await request('execute', {plan_id: confirmation.plan.plan_id});
      if (!current(expected)) return;
      receiveTask(response); uncertain = false;
    } catch (failure) {
      if (current(expected)) {
        if ([400,403,409,422].includes(failure.status)) {uncertain = false; error = failure.message;}
        else {
          error = `提交结果未知：${failure.message}。正在核对后台状态，不会重复提交。`;
          if (automatic()) timer = setTimeout(refresh, 1000);
        }
      }
    } finally {if (current(expected)) {pending = false; draw();}}
  }
  function receiveTask(response) {
    if (!response?.task_id || !['running', 'succeeded', 'failed'].includes(response.status)) throw new Error('服务未返回有效任务状态');
    task = response; taskError = ''; reconnects = 0; info.restart_required ||= Boolean(task.restart_required);
    clearTimeout(timer);
    if (task.status === 'running') timer = setTimeout(poll, 1000);
  }
  async function poll() {
    if (!active || !task?.task_id || polling) return;
    const expected = version, id = task.task_id; polling = true; clearTimeout(timer);
    try {
      const response = await request(`tasks/${encodeURIComponent(id)}`);
      if (!current(expected) || task?.task_id !== id) return;
      if (response.task_id !== id) throw new Error('服务返回的任务标识不一致');
      receiveTask(response);
      if (automatic() && response.status !== 'running') {syncing = true; await refresh();}
    } catch (failure) {
      if (current(expected) && task?.task_id === id) {
        reconnects++;
        taskError = automatic() && reconnects < 30 ? '正在重新连接服务，后台操作不会重复提交。' : `状态暂时未知：${failure.message}。任务可能仍在执行，请重新读取状态。`;
        if (automatic() && reconnects < 30) timer = setTimeout(poll, 1000);
      }
    } finally {if (current(expected)) {polling = false; draw();}}
  }
  async function recover() {
    if (!active || busy() || !automatic() || info.phase !== 'recovery_failed') return;
    const expected = version; pending = true; error = ''; draw();
    try {const response = await request('recover', {}); if (current(expected)) await receiveManagement(response);}
    catch (failure) {if (current(expected)) {
      error = `恢复结果暂时未知：${failure.message}。正在核对后台状态，不会重复提交。`;
      uncertain = true; timer = setTimeout(refresh, 1000);
    }}
    finally {if (current(expected)) {pending = false; draw();}}
  }
  function controls(item) {
    if (!managed.has(item.id) || !info?.enabled || !info.available) return null;
    const component = info.components?.find(value => value.id === item.id);
    if (!component) return null;
    const action = component.can_install ? 'install' : component.can_uninstall ? 'uninstall' : null;
    const actionButton = action ? button(action === 'install' ? '安装' : '卸载', () => {
      if (actionButton.isConnected) return prepare(item.id, action);
    }, {small: true, disabled: locked() || Boolean(error), 'data-plugin-action': action}) : null;
    return h('div', {class: 'settings-package-management'}, actionButton,
      !action && component.reason ? h('span', {class: 'muted'}, component.reason) : null,
      component.required_by?.length ? h('span', {class: 'muted'}, `依赖此组件：${component.required_by.join('、')}`) : null);
  }
  return {el, refresh, controls, get enabled() {return Boolean(info?.enabled);}, get automatic() {return automatic();}, get maintenance() {return maintenance();}, get busy() {return busy();}, get refreshBlocked() {return pending || Boolean(review);},
    destroy() {active = false; version++; clearTimeout(timer); review?.dialog.close(); for (const controller of controllers) controller.abort();}};
}
