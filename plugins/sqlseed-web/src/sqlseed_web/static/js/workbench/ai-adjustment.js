import {tr, setText, appendContent} from '../i18n.js';
import '../i18n/messages/assistant.js';
import {h, api} from '../api.js';
import {button} from './ui.js';
import {createRuleEditor} from './editor.js';

// Editing owns a suggestion copy, never a WorkbenchDocument or a database write.
export function openSuggestionAdjustment({item, table, column, catalog, host, isCurrent, onCommit, onDone}) {
  let active = true, editor = null, error = null;
  const controller = new AbortController();
  const notice = h('p', {class: 'hint', role: 'status', 'aria-live': 'polite'}, tr("assistant.adjustment.loading"));
  const body = h('div');
  const save = button(tr("assistant.adjustment.save"), () => {
    if (!active || !editor || error || !isCurrent()) {
      if (active && !isCurrent()) setText(notice, tr("assistant.adjustment.stale"));
      return;
    }
    const draft = editor.getDraft();
    if (!draft.config || Object.keys(draft.invalidValues || {}).length) return;
    onCommit({...structuredClone(draft.config), name: item.column});
    close();
  }, {primary: true, disabled: true});
  const cancel = button(tr("assistant.adjustment.cancel"), close);
  const el = h('section', {class: 'wb-ai-adjustment', 'aria-label': tr("assistant.adjustment.aria", {table: item.table, column: item.column})},
    h('h4', {}, tr("assistant.adjustment.title", {table: item.table, column: item.column})),
    h('p', {class: 'hint'}, tr("assistant.adjustment.help")), body, notice,
    h('div', {class: 'wb-ai-adjustment-actions'}, cancel, save));
  appendContent(host, el);
  load().catch(error_ => {
    if (active && error_?.name !== 'AbortError') {
      save.disabled = true;
      setText(notice, isCurrent() ? tr("assistant.adjustment.loadFailed") : tr("assistant.adjustment.stale"));
    }
  });
  async function load() {
    const metadata = catalog || await api('/api/workbench/generators', {signal: controller.signal});
    if (!active) return;
    if (!isCurrent()) {setText(notice, tr("assistant.adjustment.stale")); return;}
    editor = createRuleEditor({table, column, rule: structuredClone(item.after), baseline: structuredClone(item.after), catalog: metadata,
      onValidity: message => {error = message; save.disabled = Boolean(message); setText(notice, message || tr("assistant.adjustment.saved"));}});
    const reset = editor.el.querySelector('.wb-editor-reset');
    if (reset) setText(reset, tr("assistant.adjustment.reset"));
    appendContent(body, editor.el);
    editor.el.querySelector('input:not([disabled]), textarea:not([disabled]), button:not([disabled])')?.focus({preventScroll: true});
  }
  function close() {
    if (!active) return;
    active = false; controller.abort(); editor?.destroy(); el.remove(); onDone?.();
  }
  return {close};
}
