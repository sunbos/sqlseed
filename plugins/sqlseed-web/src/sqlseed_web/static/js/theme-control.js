import {h} from './api.js';
import {createDropdown} from './dropdown.js';
import {tr, setText} from './i18n.js';
import './i18n/messages/shell.js';

// 设置与组件样板共用同一个主题状态来源。
export function createThemeControl({label = tr('shell.theme')} = {}) {
  const theme = window.sqlseedTheme;
  const control = createDropdown({
    label,
    value: theme?.get().preference || 'light',
    options: [
      {value: 'light', label: tr('shell.light')},
      {value: 'dark', label: tr('shell.dark')},
      {value: 'system', label: tr('shell.system')}
    ],
    onChange: value => theme?.setPreference(value)
  });
  const status = h('p', {class: 'theme-status muted', role: 'status', 'aria-live': 'polite'});
  const update = () => {
    if (!theme) {
      control.el.querySelector('button').disabled = true;
      setText(status, tr('shell.themeUnavailable'));
      return;
    }
    const state = theme.get();
    // 系统明暗变化不能重置已展开菜单中的键盘探索位置。
    if (control.get() !== state.preference) control.set(state.preference);
    const color = tr(state.resolved === 'dark' ? 'shell.dark' : 'shell.light');
    setText(status, tr(state.preference === 'system' ? 'shell.systemTheme' : 'shell.currentTheme', {color}));
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
