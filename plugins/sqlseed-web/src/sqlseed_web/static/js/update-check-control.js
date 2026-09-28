import {tr, joinText, formatNumber, setText, replaceContent, serverText} from './i18n.js';
import './i18n/messages/components.js';
import {h, api} from './api.js';
import {button} from './workbench/ui.js';

const labels = {update_available: tr('updates.available'), current: tr('updates.current'), ahead: tr('updates.ahead'), not_installed: tr('updates.notInstalled'), unknown: tr('updates.unknown'), failed: tr('updates.failed')};
export function createUpdateCheckControl({management} = {}) {
  let destroyed = false, busy = false, disabled = false, controller = null, generation = 0;
  let actions = [];
  const notice = h('p', {class: 'settings-notice', role: 'status', 'aria-live': 'polite'}, tr('updates.hint'));
  const results = h('div', {class: 'settings-update-results'});
  const check = button(tr('updates.check'), run, {glyph: 'refresh'});
  const el = h('section', {class: 'settings-updates', 'aria-label': tr('updates.title')}, h('div', {class: 'settings-panel-head'}, h('h3', {}, tr('updates.title')), check), notice, results);
  async function run() {
    if (busy || disabled || destroyed) return;
    busy = true; check.disabled = true; controller = new AbortController();
    const expected = ++generation;
    setText(notice, tr('updates.loading'));
    try {
      const data = await api('/api/settings/updates', {method: 'POST', signal: controller.signal});
      if (destroyed || disabled || expected !== generation) return;
      const components = data.components || [];
      actions.forEach(action => action.destroy()); actions = [];
      replaceContent(results, ...components.map(item => {
        const action = management?.updateControls(item);
        if (action) {actions.push(action); action.setDisabled(disabled);}
        return h('div', {class: 'settings-update-row', 'data-update-id': item.id},
          h('strong', {}, serverText(item, 'label')), h('span', {class: 'settings-update-version'}, tr('updates.installedVersion', {version: item.current || tr('updates.notInstalled')})),
          h('span', {class: 'settings-update-version'}, tr('updates.latestVersion', {version: item.latest || tr('updates.unavailable')})),
          h('span', {class: 'settings-update-status', 'data-state': item.status}, labels[item.status] || tr('updates.failed')),
          action?.el || (item.status === 'update_available' && ['core', 'web', 'faker'].includes(item.id) ? h('span', {class: 'muted'}, tr('updates.requiredHint')) : null));
      }));
      const failures = components.filter(item => item.status === 'failed').length;
      const resultNotice = failures ? tr('updates.partialFailure', {count: failures, value: formatNumber(failures)}) : tr('updates.complete');
      setText(notice, joinText([resultNotice, components.some(item => item.cached) ? tr('updates.cached') : '']));
    } catch (error) {
      if (!destroyed && !disabled && expected === generation && error.name !== 'AbortError') setText(notice, tr('updates.networkError'));
    } finally {busy = false; if (!destroyed) check.disabled = disabled;}
  }
  return {el, setDisabled(value) {disabled = Boolean(value); check.disabled = disabled || busy; actions.forEach(action => action.setDisabled(disabled)); if (disabled) {generation++; controller?.abort();}}, destroy() {destroyed = true; generation++; controller?.abort(); actions.forEach(action => action.destroy()); actions = [];}};
}
