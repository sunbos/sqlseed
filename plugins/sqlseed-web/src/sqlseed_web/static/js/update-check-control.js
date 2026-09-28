import {h, api} from './api.js';
import {button} from './workbench/ui.js';

const labels = {update_available: '可更新', current: '已是最新稳定版', ahead: '当前版本高于稳定版', not_installed: '未安装', unknown: '当前版本无法比较', failed: '检查失败'};
export function createUpdateCheckControl({management} = {}) {
  let destroyed = false, busy = false, disabled = false, controller = null, generation = 0;
  let actions = [];
  const notice = h('p', {class: 'settings-notice', role: 'status', 'aria-live': 'polite'}, '点击后仅查询 PyPI 官方版本信息，不会自动安装或升级。结果缓存 15 分钟。');
  const results = h('div', {class: 'settings-update-results'});
  const check = button('检查更新', run, {glyph: 'refresh'});
  const el = h('section', {class: 'settings-updates', 'aria-label': '组件更新'}, h('div', {class: 'settings-panel-head'}, h('h3', {}, '组件更新'), check), notice, results);
  async function run() {
    if (busy || disabled || destroyed) return;
    busy = true; check.disabled = true; controller = new AbortController();
    const expected = ++generation;
    notice.textContent = '正在查询 PyPI 最新稳定版…';
    try {
      const data = await api('/api/settings/updates', {method: 'POST', signal: controller.signal});
      if (destroyed || disabled || expected !== generation) return;
      const components = data.components || [];
      actions.forEach(action => action.destroy()); actions = [];
      results.replaceChildren(...components.map(item => {
        const action = management?.updateControls(item);
        if (action) {actions.push(action); action.setDisabled(disabled);}
        return h('div', {class: 'settings-update-row', 'data-update-id': item.id},
          h('strong', {}, item.label), h('span', {class: 'settings-update-version'}, `当前：${item.current || '未安装'}`),
          h('span', {class: 'settings-update-version'}, `最新稳定版：${item.latest || '暂不可用'}`),
          h('span', {class: 'settings-update-status', 'data-state': item.status}, labels[item.status] || '检查失败'),
          action?.el || (item.status === 'update_available' && ['core', 'web', 'faker'].includes(item.id) ? h('span', {class: 'muted'}, '应用必需组件，请使用原环境管理工具成组更新。') : null));
      }));
      const failures = components.filter(item => item.status === 'failed').length;
      notice.textContent = failures ? `${failures} 个组件暂时无法检查，稍后可重试；其他结果仍可查看。` : '检查完成，未执行升级。可选组件可查看兼容性计划，确认后才更新；需联动调整依赖时会明确阻止。';
      if (components.some(item => item.cached)) notice.textContent += ' 部分结果来自最近 15 分钟的缓存。';
    } catch (error) {
      if (!destroyed && !disabled && expected === generation && error.name !== 'AbortError') notice.textContent = '无法完成版本检查，请检查网络后重试。';
    } finally {busy = false; if (!destroyed) check.disabled = disabled;}
  }
  return {el, setDisabled(value) {disabled = Boolean(value); check.disabled = disabled || busy; actions.forEach(action => action.setDisabled(disabled)); if (disabled) {generation++; controller?.abort();}}, destroy() {destroyed = true; generation++; controller?.abort(); actions.forEach(action => action.destroy()); actions = [];}};
}
