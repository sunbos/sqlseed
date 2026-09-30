import {tr, t, joinText, formatNumber, formatDate, setText, setAttr, appendContent, replaceContent, errorText} from '../i18n.js';
import '../i18n/messages/configurations.js';
import { h, get, api, store, safeTargetLabel } from '../api.js';
import { button, modal, download, icon } from '../workbench/ui.js';
let root, list, notice, count, search, currentFilter, connectionHint, selectAll, selectionLabel, selectionCount, clearSelection, deleteSelection;
let selected = new Map(), bulkPending = false, loading = false;
let records = [],
  query = '',
  onlyCurrent = false,
  scope = null,
  version = 0,
  sequence = 0,
  dialog = null;
let nameDialogSequence = 0;
const draftPath = id => `/api/workbench/drafts/${encodeURIComponent(id)}`;
const workbenchLink = (label, suffix, primary = false, glyph = null) => h('a', {
  href: `#/workbench?${suffix}`,
  class: `btn wb-button${primary ? ' primary' : ''}`
}, glyph ? icon(glyph) : null, label);
export function render() {
  version++;
  records = [];
  selected = new Map();
  bulkPending = false;
  loading = false;
  scope = null;
  query = '';
  onlyCurrent = Boolean(store.connId);
  notice = h('p', {
    class: 'config-notice wb-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  count = h('p', {
    class: 'config-count muted'
  });
  list = h('section', {
    class: 'config-list',
    role: 'list',
    'aria-label': tr('configurations.saved')
  });
  search = h('input', {
    type: 'search',
    value: '',
    'aria-label': tr('configurations.search'),
    placeholder: tr('configurations.searchPlaceholder'),
    oninput: () => {
      query = search.value;
      drawList();
    }
  });
  currentFilter = h('input', {
    type: 'checkbox',
    checked: onlyCurrent,
    'aria-label': tr('configurations.onlyCurrent'),
    onchange: () => {
      onlyCurrent = currentFilter.checked && Boolean(store.connId);
      return refresh();
    }
  });
  connectionHint = h('p', {
    class: 'config-filter-hint muted'
  });
  selectionLabel = h('span', {}, tr('configurations.selectVisible'));
  selectionCount = h('span', {class: 'config-selection-count', role: 'status', 'aria-live': 'polite'});
  selectAll = h('input', {type: 'checkbox', 'aria-label': tr('configurations.selectFiltered'), onchange: () => {
    for (const record of visibleRecords()) {
      if (selectAll.checked) selected.set(record.id, record.revision);
      else selected.delete(record.id);
    }
    updateSelection();
  }});
  clearSelection = button(tr('configurations.clearSelection'), () => {selected.clear(); updateSelection();}, {small: true});
  deleteSelection = button(tr('configurations.deleteSelected'), deleteSelectedConfigs, {class: 'config-delete', disabled: true});
  root = h('div', {
    class: 'page configs-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('h1', {}, tr('configurations.title')), h('p', {
    class: 'subtitle'
  }, tr('configurations.subtitle'))), h('div', {
    class: 'heading-actions'
  }, workbenchLink(tr('configurations.import'), 'new=1&import=1', false, 'upload'), workbenchLink(tr('configurations.new'), 'new=1', true))), h('section', {
    class: 'config-toolbar',
    'aria-label': tr('configurations.searchAndFilter')
  }, h('label', {
    class: 'config-search'
  }, h('span', {}, tr('configurations.search')), search), h('div', {
    class: 'config-scope'
  }, h('label', {
    class: 'config-filter'
  }, currentFilter, tr('configurations.onlyCurrent')), connectionHint), button(tr('configurations.refresh'), () => refresh(), {
    glyph: 'refresh'
  })), notice, h('div', {class: 'config-bulk-toolbar', role: 'group', 'aria-label': tr('configurations.bulkActions')},
    h('label', {class: 'config-filter'}, selectAll, selectionLabel), selectionCount,
    h('div', {class: 'config-bulk-actions'}, clearSelection, deleteSelection)), count, list);
  updateFilter();
  return root;
}
export function mount() {
  window.addEventListener('sqlseed:connection-changed', connectionChanged);
  return refresh();
}
export function unmount() {
  version++;
  sequence++;
  dialog?.close();
  dialog = null;
  window.removeEventListener('sqlseed:connection-changed', connectionChanged);
}
function updateFilter() {
  if (!store.connId) {
    onlyCurrent = false;
  }
  currentFilter.disabled = !store.connId;
  currentFilter.checked = onlyCurrent;
  setText(connectionHint, store.connId ? tr('configurations.currentTarget', {target: safeTargetLabel(store.target)}) : tr('configurations.connectToFilter'));
}
function connectionChanged() {
  updateFilter();
  return refresh();
}
async function refresh(message = '') {
  const expected = version,
    request = ++sequence;
  const target = onlyCurrent && store.connId ? `?conn_id=${encodeURIComponent(store.connId)}` : '';
  if (target !== scope) {
    records = [];
    selected.clear();
    scope = target;
    replaceContent(list, h('p', {
      class: 'config-empty'
    }, tr('configurations.loading')));
  }
  setAttr(list, 'aria-busy', 'true');
  loading = true;
  updateSelection();
  setText(notice, message);
  const current = () => expected === version && request === sequence;
  try {
    const response = await get(`/api/workbench/drafts${target}`);
    if (!current()) {
      return;
    }
    records = Array.isArray(response) ? response : response.drafts || [];
    drawList();
  } catch (error) {
    if (!current()) {
      return;
    }
    setText(notice, tr('configurations.loadError', {detail: errorText(error)}));
    if (!records.length) {
      replaceContent(list, h('p', {
        class: 'config-empty'
      }, tr('configurations.loadUnavailable')));
    }
  } finally {
    if (current()) {
      setAttr(list, 'aria-busy', 'false');
      loading = false;
      updateSelection();
    }
  }
}
function savedTime(value) {
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  if (value == null || value === '' || !Number.isFinite(date.getTime())) {
    return tr('configurations.unknownSavedTime');
  }
  return formatDate(date, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  });
}
function visibleRecords() {
  const term = query.trim().toLocaleLowerCase();
  return records.filter(record => `${record.name} ${record.target_label}`.toLocaleLowerCase().includes(term));
}
function updateSelection() {
  const visible = visibleRecords();
  const eligible = new Map(visible.map(record => [record.id, record.revision]));
  for (const [id, revision] of selected) if (eligible.get(id) !== revision) selected.delete(id);
  selectAll.checked = visible.length > 0 && selected.size === visible.length;
  selectAll.indeterminate = selected.size > 0 && selected.size < visible.length;
  selectAll.disabled = loading || bulkPending || !visible.length;
  setText(selectionLabel, tr('configurations.selectCount', {count: formatNumber(visible.length)}));
  setText(selectionCount, tr('configurations.selectionCount', {count: formatNumber(selected.size), scope: onlyCurrent ? tr('configurations.currentDatabase') : tr('configurations.allDatabases'), search: query.trim() ? tr('configurations.searchTerm', {term: query.trim()}) : ''}));
  clearSelection.disabled = bulkPending || !selected.size;
  deleteSelection.disabled = loading || bulkPending || !selected.size;
  for (const checkbox of list.querySelectorAll('[data-config-select]')) {
    checkbox.checked = selected.has(checkbox.dataset.configSelect);
    checkbox.disabled = loading || bulkPending;
  }
  for (const action of list.querySelectorAll('[data-config-mutation]')) action.disabled = bulkPending;
  for (const card of list.querySelectorAll('[data-config-id]')) card.classList.toggle('config-card-selected', selected.has(card.dataset.configId));
}
function drawList() {
  const term = query.trim().toLocaleLowerCase(), visible = visibleRecords();
  updateSelection();
  setText(count, tr('configurations.resultCount', {count: visible.length, value: formatNumber(visible.length), total: term ? tr('configurations.totalCount', {count: formatNumber(records.length)}) : ''}));
  if (!visible.length) {
    replaceContent(list, h('div', {
      class: 'config-empty'
    }, h('h2', {}, term ? tr('configurations.noMatches') : tr('configurations.empty')), h('p', {}, term ? tr('configurations.searchHint') : tr('configurations.emptyHint')), term ? null : workbenchLink(tr('configurations.new'), 'new=1', true)));
    return;
  }
  replaceContent(list, ...visible.map(record => {
    const document = record.document || {},
      tables = Array.isArray(document.tables) ? document.tables : [];
    const rowCount = tables.every(table => Number.isInteger(table.count) && table.count >= 0) ? tables.reduce((sum, table) => sum + table.count, 0) : null;
    const planned = rowCount === null ? tr('configurations.unknownRows') : tr('configurations.rowCount', {count: rowCount, value: formatNumber(rowCount)});
    const provider = {
      base: 'Base',
      faker: 'Faker',
      mimesis: 'Mimesis'
    }[document.provider] || document.provider || tr('configurations.unset');
    return h('article', {
      class: 'config-card',
      role: 'listitem',
      'data-config-id': record.id
    }, h('input', {type: 'checkbox', checked: selected.has(record.id),
      class: 'config-select', 'data-config-select': record.id, 'aria-label': tr('configurations.selectRecord', {name: record.name}),
      onchange: event => {
        if (event.target.checked) selected.set(record.id, record.revision);
        else selected.delete(record.id);
        updateSelection();
      }}), h('div', {
      class: 'config-card-main'
    }, h('div', {
      class: 'config-card-heading'
    }, h('h2', {}, record.name), h('span', {
      class: 'config-revision'
    }, `v${record.revision}`)), h('p', {
      class: 'config-target'
    }, icon('database'), record.target_label || tr('configurations.unknownTarget')), h('p', {
      class: 'config-facts'
    }, tr('configurations.facts', {count: tables.length, value: formatNumber(tables.length), rows: planned, provider, locale: document.locale || tr('configurations.unsetLocale')})), h('p', {
      class: 'config-updated muted'
    }, tr('configurations.lastSaved', {date: savedTime(record.updated_at)}))), h('div', {
      class: 'config-card-actions',
      role: 'group',
      'aria-label': tr('configurations.recordActions', {name: record.name})
    }, workbenchLink(tr('configurations.open'), `draft=${encodeURIComponent(record.id)}`), button(tr('configurations.copy'), () => editName(record, true), {'data-config-mutation': true}), button(tr('configurations.rename'), () => editName(record, false), {'data-config-mutation': true}), button(tr('configurations.export'), () => exportConfig(record), {
      glyph: 'download'
    }), button(tr('configurations.delete'), () => deleteConfig(record), {
      class: 'config-delete', 'data-config-mutation': true
    })));
  }));
  updateSelection();
}

function deleteSelectedConfigs() {
  if (loading || bulkPending || !selected.size) return;
  const targets = visibleRecords().filter(record => selected.get(record.id) === record.revision)
    .map(({id, name, revision, target_label}) => ({id, name, revision, target_label}));
  if (!targets.length) return;
  const context = createDialog(tr('configurations.bulkDeleteTitle')), {owned} = context;
  const alert = h('p', {role: 'alert', class: 'config-error'});
  const progress = h('p', {role: 'status', 'aria-live': 'polite'});
  const cancel = button(tr('configurations.cancel'), owned.close);
  const confirm = button(tr('configurations.deleteCount', {count: targets.length, value: formatNumber(targets.length)}), submit, {class: 'config-delete-confirm'});
  let pending = false, submitted = false;
  appendContent(owned.body, h('p', {}, tr('configurations.deleteList', {count: targets.length, value: formatNumber(targets.length)})), h('ul', {class: 'config-delete-list'}, ...targets.map(record => h('li', {},
      h('strong', {}, record.name), h('span', {class: 'muted'}, joinText([record.target_label || tr('configurations.unknownTarget'), " · v", record.revision]))))), h('p', {}, tr('configurations.bulkDeleteHint')), progress, alert);
  appendContent(owned.actions, cancel, confirm);
  cancel.focus({preventScroll: true});
  function removeDeletedRecord(record) {
    publish('sqlseed:draft-deleted', {id: record.id, revision: record.revision});
    if (context.pageCurrent()) {
      selected.delete(record.id);
      records = records.filter(item => item.id !== record.id);
    }
  }
  async function deleteReviewedRecord(record, result) {
    try {
      await api(`${draftPath(record.id)}?revision=${record.revision}`, {method: 'DELETE'});
      result.deleted++;
      removeDeletedRecord(record);
    } catch (error) {
      if (error.status === 404) {
        result.missing++;
        removeDeletedRecord(record);
      } else {
        result.failures.push(joinText([record.name, "：", error.status === 409 ? tr('configurations.changedNotDeleted') : tr('configurations.unknownDeletion')]));
        return error.status === 409;
      }
    }
    return true;
  }
  function deletionSummary({deleted, missing, failures}, remaining) {
    return tr('configurations.deletedSummary', {count: formatNumber(deleted), missing: missing ? tr('configurations.missingCount', {count: formatNumber(missing)}) : '', failed: failures.length ? tr('configurations.failedCount', {count: failures.length, value: formatNumber(failures.length)}) : '', remaining: remaining ? tr('configurations.remainingCount', {count: formatNumber(remaining)}) : ''});
  }
  async function* deletionResults(result) {
    let current = 0;
    // Each pull submits one reviewed revision. Cancellation or an unknown
    // outcome must stop the batch before the next mutation is submitted.
    for (const record of targets) {
      if (!context.current()) return;
      current++;
      setText(progress, tr('configurations.deleteProgress', {current: formatNumber(current), total: formatNumber(targets.length), name: record.name}));
      yield deleteReviewedRecord(record, result);
    }
  }
  async function submit() {
    if (pending || submitted || !context.current()) return;
    pending = submitted = bulkPending = true;
    confirm.disabled = true;
    setText(cancel, tr('configurations.stopDeletion'));
    updateSelection();
    let attempted = 0;
    const result = {deleted: 0, missing: 0, failures: []};
    for await (const canContinue of deletionResults(result)) {
      attempted++;
      if (!canContinue) break;
    }
    pending = false;
    if (!context.pageCurrent()) return;
    bulkPending = false;
    const remaining = targets.length - attempted;
    const {failures} = result;
    const summary = deletionSummary(result, remaining);
    drawList();
    if (context.current()) {
      if (!failures.length && !remaining) owned.close();
      else {
        setText(progress, summary);
        setText(alert, tr('configurations.deleteFailures', {details: joinText(failures, '; ')}));
        setText(cancel, tr('configurations.returnList'));
      }
    }
    await refresh(summary);
  }
}
function createDialog(title, dismiss = 'footer') {
  const page = version;
  let closed = false;
  const owned = modal(title, {
    dismiss,
    onClose: () => {
      closed = true;
      if (dialog === owned) {
        dialog = null;
      }
    }
  });
  dialog = owned;
  owned.el.classList.add('config-dialog');
  return {
    owned,
    pageCurrent: () => page === version,
    current: () => page === version && !closed && dialog === owned
  };
}
function publish(type, detail) {
  window.dispatchEvent(new CustomEvent(type, {
    detail
  }));
}
async function mutationFailure(error, context, alert, confirm) {
  if (!context.current()) {
    return;
  }
  if ([404, 409].includes(error.status)) {
    setText(alert, error.status === 409 ? tr('configurations.changedConflict') : tr('configurations.missingConflict'));
    confirm.disabled = true;
    await refresh();
  } else {
    setText(alert, tr('configurations.mutationError', {detail: errorText(error)}));
  }
}
function editName(record, copy) {
  const errorId = `config-name-error-${++nameDialogSequence}`;
  const context = createDialog(copy ? tr('configurations.copyTitle') : tr('configurations.renameTitle')),
    {
      owned
    } = context;
  const input = h('input', {
    type: 'text',
    value: copy ? t('configurations.copyName', {name: record.name.slice(0, 200 - t('configurations.copySuffix').length)}) : record.name,
    maxlength: 200,
    'aria-label': tr('configurations.name'),
    oninput: clearNameError,
    onkeydown: event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        return submit();
      }
    }
  });
  const alert = h('p', {
    role: 'alert',
    class: 'config-error'
  });
  alert.id = errorId;
  const confirm = button(copy ? tr('configurations.createCopy') : tr('configurations.saveName'), submit, {
    primary: true
  });
  let pending = false;
  appendContent(owned.body, h('p', {
    class: 'muted'
  }, copy ? tr('configurations.copyHint') : tr('configurations.renameHint')), h('label', {
    class: 'config-name-field'
  }, h('span', {}, tr('configurations.name')), input), alert);
  appendContent(owned.actions, button(tr('configurations.cancel'), owned.close), confirm);
  input.focus();
  function clearNameError() {
    if (input.getAttribute('aria-invalid') !== 'true') {
      return;
    }
    input.removeAttribute('aria-invalid');
    input.removeAttribute('aria-describedby');
    setText(alert, '');
  }
  function rejectName(message) {
    setAttr(input, 'aria-invalid', 'true');
    setAttr(input, 'aria-describedby', errorId);
    setText(alert, message);
    input.focus({preventScroll: true});
  }
  async function submit() {
    if (pending || confirm.disabled || !context.current()) {
      return;
    }
    const name = input.value.trim();
    if (!name) {
      rejectName(tr('configurations.nameRequired'));
      return;
    }
    if (name.length > 200) {
      rejectName(tr('configurations.nameTooLong'));
      return;
    }
    pending = true;
    confirm.disabled = true;
    input.disabled = true;
    clearNameError();
    setText(alert, '');
    let failed = null;
    try {
      const saved = await api(`${draftPath(record.id)}${copy ? '/copy' : ''}`, {
        method: copy ? 'POST' : 'PATCH',
        body: JSON.stringify({
          revision: record.revision,
          name
        })
      });
      if (!copy) {
        publish('sqlseed:draft-renamed', {
          id: saved.id,
          revision: saved.revision,
          name: saved.name
        });
      }
      if (!context.pageCurrent()) {
        return;
      }
      if (context.current()) {
        owned.close();
      }
      await refresh(copy ? tr('configurations.copied', {name: saved.name}) : tr('configurations.renamed', {name: saved.name}));
    } catch (error) {
      failed = error;
      await mutationFailure(error, context, alert, confirm);
    } finally {
      pending = false;
      if (context.current()) {
        input.disabled = false;
        confirm.disabled = [404, 409].includes(failed?.status);
      }
    }
  }
}
function deleteConfig(record) {
  const context = createDialog(tr('configurations.deleteTitle')),
    {
      owned
    } = context;
  const alert = h('p', {
      role: 'alert',
      class: 'config-error'
    }),
    cancel = button(tr('configurations.cancel'), owned.close);
  let pending = false;
  const confirm = button(tr('configurations.deleteTitle'), async () => {
    if (pending || confirm.disabled || !context.current()) {
      return;
    }
    pending = true;
    confirm.disabled = true;
    setText(alert, '');
    let failed = null;
    try {
      await api(`${draftPath(record.id)}?revision=${record.revision}`, {
        method: 'DELETE'
      });
      publish('sqlseed:draft-deleted', {
        id: record.id,
        revision: record.revision
      });
      if (!context.pageCurrent()) {
        return;
      }
      if (context.current()) {
        owned.close();
      }
      await refresh(tr('configurations.deleted', {name: record.name}));
    } catch (error) {
      failed = error;
      await mutationFailure(error, context, alert, confirm);
    } finally {
      pending = false;
      if (context.current()) {
        confirm.disabled = [404, 409].includes(failed?.status);
      }
    }
  }, {
    class: 'config-delete-confirm'
  });
  appendContent(owned.body, h('p', {}, tr('configurations.deleteQuestion')), h('strong', {
    class: 'config-delete-name'
  }, record.name), h('p', {
    class: 'muted'
  }, tr('configurations.targetRevision', {target: record.target_label, revision: record.revision})), h('p', {}, tr('configurations.deleteHint')), alert);
  appendContent(owned.actions, cancel, confirm);
  cancel.focus();
}
function exportConfig(record) {
  const context = createDialog(tr('configurations.exportTitle'), 'header'),
    {
      owned
    } = context;
  const alert = h('p', {
      role: 'alert',
      class: 'config-error'
    }),
    result = h('p', {
      role: 'status',
      'aria-live': 'polite'
    });
  const actions = ['JSON', 'YAML'].map(format => button(tr('configurations.download', {format}), () => saveFile(format), {
    glyph: 'download'
  }));
  let pending = false;
  appendContent(owned.body, h('strong', {}, record.name), h('p', {}, tr('configurations.exportHint')), alert, result);
  appendContent(owned.actions, ...actions);
  async function saveFile(format) {
    if (pending || !context.current()) {
      return;
    }
    pending = true;
    setText(alert, '');
    actions.forEach(action => {
      action.disabled = true;
    });
    try {
      const saved = await get(`${draftPath(record.id)}/export`);
      if (!context.current()) {
        return;
      }
      const name = String(saved.name || 'sqlseed').replace(/[^\p{L}\p{N}._-]+/gu, '_').slice(0, 80) || 'sqlseed';
      download(`${name}.${format === 'JSON' ? 'json' : 'yaml'}`, format === 'JSON' ? JSON.stringify(saved.json, null, 2) : saved.yaml, format === 'JSON' ? 'application/json' : 'application/yaml');
      setText(result, tr('configurations.exported', {revision: saved.revision, format}));
    } catch (error) {
      if (context.current()) {
        setText(alert, tr('configurations.exportError', {detail: errorText(error)}));
      }
    } finally {
      pending = false;
      if (context.current()) {
        actions.forEach(action => {
          action.disabled = false;
        });
      }
    }
  }
}
