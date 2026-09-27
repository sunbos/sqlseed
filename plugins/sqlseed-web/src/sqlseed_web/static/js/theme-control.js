import {h} from './api.js';
import {createDropdown} from './dropdown.js';

// 设置与组件样板共用同一个主题状态来源。
export function createThemeControl({label = '外观主题'} = {}) {
  const theme = window.sqlseedTheme;
  const control = createDropdown({
    label,
    value: theme?.get().preference || 'light',
    options: [
      {value: 'light', label: '浅色'},
      {value: 'dark', label: '深色'},
      {value: 'system', label: '跟随系统'}
    ],
    onChange: value => theme?.setPreference(value)
  });
  const status = h('p', {class: 'theme-status muted', role: 'status', 'aria-live': 'polite'});
  const update = () => {
    if (!theme) {
      control.el.querySelector('button').disabled = true;
      status.textContent = '主题设置暂不可用，请刷新页面。';
      return;
    }
    const state = theme.get();
    // 系统明暗变化不能重置已展开菜单中的键盘探索位置。
    if (control.get() !== state.preference) control.set(state.preference);
    const color = state.resolved === 'dark' ? '深色' : '浅色';
    status.textContent = state.preference === 'system' ? `跟随系统 · 当前为${color}` : `当前使用${color}主题`;
  };
  window.addEventListener('sqlseed:theme-changed', update);
  update();
  return {
    el: h('div', {class: 'theme-control'}, h('span', {class: 'theme-control-label'}, label), control.el, status),
    close: () => control.close(),
    destroy() {
      window.removeEventListener('sqlseed:theme-changed', update);
      control.destroy();
    }
  };
}
