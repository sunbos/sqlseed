import {h, api} from '../api.js';
import {button} from './ui.js';
import {createRuleEditor} from './editor.js';

// Editing owns a suggestion copy, never a WorkbenchDocument or a database write.
export function openSuggestionAdjustment({item, table, column, catalog, host, isCurrent, onCommit, onDone}) {
  let active = true, editor = null, error = null;
  const controller = new AbortController();
  const notice = h('p', {class: 'hint', role: 'status', 'aria-live': 'polite'}, '正在读取字段规则…');
  const body = h('div');
  const save = button('保存调整', () => {
    if (!active || !editor || error || !isCurrent()) {
      if (active && !isCurrent()) notice.textContent = '配置已变化，请取消并重新分析。';
      return;
    }
    const draft = editor.getDraft();
    if (!draft.config || Object.keys(draft.invalidValues || {}).length) return;
    onCommit({...structuredClone(draft.config), name: item.column});
    close();
  }, {primary: true, disabled: true});
  const cancel = button('取消调整', close);
  const el = h('section', {class: 'wb-ai-adjustment', 'aria-label': `调整 ${item.table}.${item.column} 的建议`},
    h('h4', {}, `调整建议 · ${item.table}.${item.column}`),
    h('p', {class: 'hint'}, '只修改待审阅建议。保存后需重新勾选，并在应用前检查；当前配置保持不变。'), body, notice,
    h('div', {class: 'wb-ai-adjustment-actions'}, cancel, save));
  host.append(el);
  load();
  async function load() {
    try {
      const metadata = catalog || await api('/api/workbench/generators', {signal: controller.signal});
      if (!active) return;
      if (!isCurrent()) {notice.textContent = '配置已变化，请取消并重新分析。'; return;}
      editor = createRuleEditor({table, column, rule: structuredClone(item.after), baseline: structuredClone(item.after), catalog: metadata,
        onValidity: message => {error = message; save.disabled = Boolean(message); notice.textContent = message || '调整保留在建议中，最终应用前会重新检查。';}});
      const reset = editor.el.querySelector('.wb-editor-reset');
      if (reset) reset.textContent = '重置为本次调整前的建议';
      body.append(editor.el);
      editor.el.querySelector('input:not([disabled]), textarea:not([disabled]), button:not([disabled])')?.focus({preventScroll: true});
    } catch (failure) {
      if (active && failure.name !== 'AbortError') notice.textContent = '无法读取规则编辑器，请取消后重试。';
    }
  }
  function close() {
    if (!active) return;
    active = false; controller.abort(); editor?.destroy(); el.remove(); onDone?.();
  }
  return {close};
}
