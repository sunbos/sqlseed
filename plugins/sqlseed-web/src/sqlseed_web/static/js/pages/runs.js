import {tr, joinText, formatNumber, formatDate, setText, setAttr, replaceContent, errorText, serverText, serverMessages, isLocalized} from '../i18n.js';
import '../i18n/messages/runs.js';
import { h, get } from '../api.js';
import { download, valueText } from '../workbench/ui.js';
import { remainingRun } from '../workbench/recovery.js';
import { openTableData } from '../workbench/table-data.js';
const labels = {
  queued: tr('runs.queued'),
  running: tr('runs.running'),
  done: tr('runs.done'),
  error: tr('runs.error'),
  interrupted: tr('runs.interrupted'),
  not_run: tr('runs.notRun')
};
let root,
  workspace,
  list,
  detail,
  notice,
  version = 0,
  requestSequence = 0,
  timer = null,
  selectedId = null;
let dataViewer = null;
const snapshotStates = new Map();
const action = (label, handler, attrs = {}) => h('button', {
  type: 'button',
  class: 'btn',
  onclick: handler,
  ...attrs
}, label);
export function render() {
  version++;
  snapshotStates.clear();
  selectedId = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
  notice = h('p', {
    class: 'run-notice wb-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  list = h('aside', {
    class: 'run-list',
    'aria-label': tr('runs.list')
  });
  detail = h('section', {
    class: 'run-detail wb-run-detail'
  }, h('p', {
    class: 'empty'
  }, tr('runs.selectRun')));
  workspace = h('div', {
    class: 'runs-workspace'
  }, list, detail);
  root = h('div', {
    class: 'page runs-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('h1', {}, tr('runs.title')), h('p', {
    class: 'subtitle'
  }, tr('runs.subtitle'))), h('div', {
    class: 'heading-actions'
  }, h('a', {
    href: '#/workbench',
    class: 'btn'
  }, tr('runs.workbench')), action(tr('runs.refresh'), () => refresh(version)))), notice, workspace);
  return root;
}
export function mount() {
  return refresh(version);
}
export function unmount() {
  version++;
  clearTimeout(timer);
  timer = null;
  dataViewer?.close();
  dataViewer = null;
}
async function refresh(expected) {
  const sequence = ++requestSequence;
  const current = () => expected === version && sequence === requestSequence;
  clearTimeout(timer);
  timer = null;
  try {
    const response = await get('/api/workbench/runs');
    if (!current()) return;
    const runs = Array.isArray(response) ? response : response.runs || [];
    if (!runs.length) {
      selectedId = null;
      replaceContent(workspace, h('section', {
        class: 'run-empty',
        role: 'status'
      }, h('h2', {}, tr('runs.empty')), h('p', {}, tr('runs.emptyHint')), h('a', {
        href: '#/workbench',
        class: 'btn primary'
      }, tr('runs.workbench'))));
      setText(notice, '');
      return;
    }
    if (workspace.firstChild !== list) replaceContent(workspace, list, detail);
    if (!selectedId && runs.length) selectedId = runs[0].id;
    drawList(runs);
    if (selectedId) {
      const run = await get(`/api/workbench/runs/${encodeURIComponent(selectedId)}`);
      if (!current()) return;
      drawRun(run);
    }
    setText(notice, '');
    if (runs.some(run => ['queued', 'running'].includes(run.status))) timer = setTimeout(() => refresh(expected), 1200);
  } catch (error) {
    if (!current()) return;
    setText(notice, tr('runs.loadError', {detail: errorText(error)}));
    timer = setTimeout(() => refresh(expected), 5000);
  }
}
function drawList(runs) {
  const previousCards = new Map([...list.children].map(card => [card.dataset.runId, card]));
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  const cards = runs.map(run => {
    const card = previousCards.get(String(run.id)) || action('', () => {
      selectedId = run.id;
      dataViewer?.close();
      dataViewer = null;
      refresh(version);
    });
    card.dataset.runId = run.id;
    card.className = `run-card wb-run-card${run.id === selectedId ? ' active' : ''}`;
    setAttr(card, 'aria-pressed', String(run.id === selectedId));
    replaceContent(card, h('strong', {}, run.name || run.id), status(run.status), h('small', {}, runTime(run.created_at ?? run.started_at)), h('small', {}, run.target_label));
    return card;
  });
  // 轮询更新状态而不是反复卸载整列；记录插入或重排也保留原有键盘位置。
  cards.forEach((card, index) => {
    if (list.children[index] !== card) list.insertBefore(card, list.children[index] || null);
  });
  const retained = new Set(cards);
  for (const card of previousCards.values()) if (!retained.has(card)) card.remove();
  if (focused?.isConnected && document.activeElement !== focused) focused.focus({preventScroll: true});
}
function status(value) {
  return h('span', {
    class: `run-status ${value}`
  }, labels[value] || value || tr('runs.unknownStatus'));
}
function runTime(value) {
  if (value === undefined || value === null || value === '') return h('span', {}, tr('runs.unknownTime'));
  const timestamp = typeof value === 'number' ? value * 1000 : value;
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return h('span', {}, tr('runs.unknownTime'));
  return h('time', {
    datetime: date.toISOString()
  }, formatDate(date, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }));
}
function errorMessages(...values) {
  const items = values.flatMap(value => Array.isArray(value) ? value : [value])
    .filter(value => value !== undefined && value !== null && value !== '')
    .map(value => isLocalized(value) ? value : errorText({message: valueText(value)}));
  return [...new Map(items.map(value => [String(value), value])).values()];
}
function recordedErrors(record) {
  // Historical runs stored a single diagnostic string instead of an array.
  return errorMessages(Array.isArray(record.errors) ? serverMessages(record, 'errors') : record.errors,
    serverText(record, 'error'));
}
function knownCount(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
function tableResult(table) {
  const errors = recordedErrors(table);
  if (errors.length) return joinText(errors, '; ');
  const descriptions = {
    done: tr('runs.tableDone'),
    error: tr('runs.tableError'),
    queued: tr('runs.tableQueued'),
    running: tr('runs.tableRunning'),
    not_run: tr('runs.tableNotRun'),
    interrupted: tr('runs.tableInterrupted')
  };
  return descriptions[table.status] || tr('runs.unknownResult');
}
function viewTable(run, table) {
  if (selectedId !== run.id || !root?.isConnected) return;
  const expected = version;
  const current = () => version === expected && selectedId === run.id && Boolean(root?.isConnected);
  dataViewer?.close();
  dataViewer = openTableData({
    runId: run.id,
    table: table.name,
    targetKey: run.target_key,
    targetLabel: run.target_label,
    isCurrent: current,
    // Polling replaces the detail controls while this reader is open. Resolve
    // the current action by identity only when its original page/run survives.
    returnFocus: () => current() && detail.dataset.runId === String(run.id)
      ? [...detail.querySelectorAll('[data-run-focus]')].find(element => element.dataset.runFocus === `table:${table.name}`)
      : null
  });
}
function captureRunView(run) {
  const previousSnapshot = detail.querySelector('.run-snapshot');
  if (previousSnapshot && detail.dataset.runId) {
    const code = previousSnapshot.querySelector('pre');
    snapshotStates.set(detail.dataset.runId, {open: previousSnapshot.open, top: code.scrollTop, left: code.scrollLeft});
  }
  const active = document.activeElement;
  return detail.dataset.runId === String(run.id) && detail.contains(active) ? active.dataset.runFocus : null;
}
function restoreRunView(run, content, focusedKey) {
  const snapshot = content.find(element => element?.classList.contains('run-snapshot'));
  const saved = snapshotStates.get(String(run.id));
  if (saved) snapshot.open = saved.open;
  replaceContent(detail, ...content.filter(element => element !== null));
  detail.dataset.runId = run.id;
  if (saved) {
    const code = snapshot.querySelector('pre');
    code.scrollTop = saved.top;
    code.scrollLeft = saved.left;
  }
  if (focusedKey) {
    const target = [...detail.querySelectorAll('[data-run-focus]')].find(element => element.dataset.runFocus === focusedKey);
    if (target && !target.disabled) target.focus({preventScroll: true});
  }
}
function plannedRunCounts(run, tables) {
  const configured = Array.isArray(run.document?.tables) ? run.document.tables : [];
  const plannedCount = table => table.requested_count ?? table.count ?? configured.find(item => item.name === table.name)?.count;
  const planned = tables.length && tables.every(table => knownCount(plannedCount(table))) ? tables.reduce((total, table) => total + plannedCount(table), 0) : null;
  return {plannedCount, planned};
}
function drawRun(run) {
  const focusedKey = captureRunView(run);
  const recovery = remainingRun(run);
  const count = run.rows_inserted;
  const replacement = run.execution?.mode === 'replace_selected';
  const exact = knownCount(count) && run.row_counts_exact !== false && run.count_complete !== false;
  const errors = recordedErrors(run);
  const tables = Array.isArray(run.tables) ? run.tables : [];
  const {plannedCount, planned} = plannedRunCounts(run, tables);
  function executionDescription() {
    if (replacement) {
      return tr('runs.replaceMode', {identity: run.execution.reset_identity ? tr('runs.reset') : tr('runs.keep')});
    } else {
      return tr('runs.appendMode');
    }
  }
  function committedCountMetric() {
    if (knownCount(count)) {
      return h('div', {}, h('strong', {}, joinText([exact ? '' : tr('runs.atLeast'), formatNumber(count)])), ['queued', 'running'].includes(run.status) ? tr('runs.confirmedRows') : tr('runs.committedRows'));
    } else {
      return h('div', {
        class: 'run-metric-unknown'
      }, tr('runs.unknownCount'));
    }
  }
  function tableCommittedCount(table) {
    if (table.status === 'running') {
      return tr('runs.counting');
    } else if (knownCount(table.rows_inserted)) {
      return formatNumber(table.rows_inserted);
    } else {
      return tr('runs.verify');
    }
  }
  function runRecoveryCard() {
    if (run.status === 'error') {
      return h('section', {
        class: 'run-recovery wb-source-card',
        'aria-label': tr('runs.failureNext')
      }, h('h3', {}, tr('runs.nextSteps')), h('p', {}, recovery.ok ? tr('runs.recoveryHint') : recovery.reason), ...(recovery.ok ? [h('p', {
        class: 'muted'
      }, tr('runs.recoveryCaveat')), h('a', {
        href: `#/workbench?run=${encodeURIComponent(run.id)}&recover=remaining`,
        'data-run-focus': 'remaining-config',
        class: 'btn primary'
      }, tr('runs.recover'))] : []));
    } else {
      return null;
    }
  }
  const content = [h('div', {
    class: 'run-heading'
  }, h('h2', {}, run.name || tr('runs.generationTask')), status(run.status)), h('p', {
    class: 'mono run-target'
  }, run.target_label), h('p', {
    class: 'muted run-identity'
  }, tr('runs.identity', {revision: run.revision ?? '—', id: run.id})), h('p', {
    class: 'run-execution'
  }, executionDescription()), run.result?.rolled_back ? h('p', {
    class: 'run-rollback',
    role: 'status'
  }, tr('runs.rolledBack')) : null, replacement && run.status === 'running' ? h('p', {
    class: 'muted'
  }, tr('runs.atomicInProgress')) : null, h('div', {
    class: 'run-metrics'
  }, h('div', {
    class: 'run-total run-planned'
  }, h('span', {
    class: 'run-metric-label'
  }, tr('runs.planned')), h('div', {}, h('strong', {}, planned === null ? tr('runs.notRecorded') : formatNumber(planned)), planned === null ? '' : tr('runs.rows'))), h('div', {
    class: 'run-total run-committed'
  }, h('span', {
    class: 'run-metric-label'
  }, tr('runs.committed')), committedCountMetric())), h('p', {
    class: 'muted run-count-explanation'
  }, tr('runs.countHint')), !exact ? h('p', {
    class: 'run-warning'
  }, tr('runs.uncertainCount')) : null, h('div', {
    class: 'run-table-scroll'
  }, h('table', {
    class: 'run-table'
  }, h('thead', {}, h('tr', {}, ...[tr('runs.table'), tr('runs.status'), tr('runs.plannedRows'), tr('runs.committedColumn'), tr('runs.result')].map(text => h('th', {}, text)))), h('tbody', {}, ...tables.map(table => h('tr', {}, h('td', {
    class: 'run-table-name'
  }, table.name), h('td', {}, status(table.status)), h('td', {}, knownCount(plannedCount(table)) ? formatNumber(plannedCount(table)) : tr('runs.notRecorded')), h('td', {}, tableCommittedCount(table)), h('td', {
    class: table.status === 'error' ? 'run-error' : ''
  }, h('div', {
    class: 'run-result-content'
  }, h('span', {}, tableResult(table)), action(tr('runs.viewData'), () => viewTable(run, table), {
    class: 'btn run-view-data',
    'data-run-focus': `table:${table.name}`,
    disabled: ['queued', 'running'].includes(run.status),
    title: ['queued', 'running'].includes(run.status) ? tr('runs.viewAfterRun') : tr('runs.viewActualData')
  })))))))), errors.length ? h('div', {
    class: 'run-error',
    role: 'alert'
  }, ...errors.map(error => h('p', {}, error))) : null, runRecoveryCard(), h('details', {
    class: 'run-snapshot'
  }, h('summary', {'data-run-focus': 'snapshot'}, tr('runs.snapshot')), h('p', {
    class: 'muted'
  }, tr('runs.snapshotHint')), h('pre', {}, JSON.stringify(run.document, null, 2)), action(tr('runs.exportSnapshot'), () => download(`sqlseed-run-${run.id}.json`, JSON.stringify({
    target_key: run.target_key,
    schema_hash: run.schema_hash,
    document: run.document,
    execution: run.execution || {
      mode: 'append',
      reset_identity: false
    },
    plan_hash: run.plan_hash
  }, null, 2)), {'data-run-focus': 'export-snapshot'})), h('div', {
    class: 'run-actions'
  }, h('a', {
    href: `#/workbench?run=${encodeURIComponent(run.id)}`,
    'data-run-focus': 'new-config',
    class: 'btn'
  }, tr('runs.newFromSnapshot'))), run.status === 'error' ? h('p', {
    class: 'muted'
  }, tr('runs.fullSnapshotHint')) : null, replacement ? h('p', {
    class: 'muted'
  }, tr('runs.replacementSnapshotHint')) : null, ['queued', 'running'].includes(run.status) ? h('p', {
    class: 'muted'
  }, tr('runs.serverRunning')) : null];
  restoreRunView(run, content, focusedKey);
}
