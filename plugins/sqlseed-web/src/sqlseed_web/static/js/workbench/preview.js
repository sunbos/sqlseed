import { tr, joinText, formatNumber, setText, setAttr, errorText, serverText } from '../i18n.js';
import '../i18n/messages/preview.js';
import { h } from '../api.js';
import { createDropdown } from '../dropdown.js';
import { modal, button, valueText } from './ui.js';
import { createPreviewScrollLayout } from './preview-scroll-layout.js';
let nextPreviewId = 0;
const validCount = value => /^\d+$/.test(String(value)) && Number(value) >= 1 && Number(value) <= 100;

/** Readonly preview state stays local; the caller owns configuration and transport. */
export function openDataPreview({
  tables,
  relationships = null,
  currentTable,
  selectedTables,
  initialScope = 'current',
  initialCount = 10,
  generate,
  guard = task => task,
  setControlDisabled = (control, value) => { control.disabled = value; },
  isCurrent = () => true,
  onOptionsChange,
  onResult,
  onError,
  onValidationIssue,
  onUnsupported,
  onCurrentData,
  onColumnAction,
  container = null,
  fixedScope = false,
  initialResult = null,
  initialView = null,
  initialStale = false
}) {
  function showPreviewLoading() {
    if (!result) {
      scrollLayout.setTable(null);
      results.replaceChildren(h('p', {
        class: 'wb-preview-loading'
      }, tr('preview.loading')));
    }
    if (result) {
      if (stale) {
        setText(status, tr('preview.updatingStale'));
      } else {
        setText(status, tr('preview.updating'));
      }
    } else {
      setText(status, tr('preview.loading'));
    }
  }

  const id = `wb-preview-${++nextPreviewId}`;
  const schema = new Map(tables.map(table => [table.name, table]));
  const selected = [...new Set(selectedTables)];
  const relationEdges = structuredClone(relationships?.edges || []);
  const relationNodes = new Map((relationships?.nodes || []).map(node=>[node.id, node]));
  const relationOpen = new Map(Object.entries(initialView?.relationOpen || {}));
  const tableScroll = new Map(Object.entries(initialView?.tableScroll || {}));
  let scope = initialScope === 'selected' ? 'selected' : 'current';
  let count;
  if (validCount(initialView?.count)) {
    count = Number(initialView.count);
  } else if (validCount(initialCount)) {
    count = Number(initialCount);
  } else {
    count = 10;
  }
  let closed = false,
    busy = false,
    sequence = 0,
    scopeControl = null,
    result = null,
    shownTable = initialView?.shownTable || currentTable;
  let selectedColumn = initialView?.column || null,
    stale = initialStale;
  // Changing options clears the cached rows, not the fact that this view has
  // already previewed. Keep the established refresh action while editing.
  let hasPreviewResult = Boolean(initialResult);
  let columnAction = initialView?.columnAction || 'information';
  let scrollLayout = null;
  const unsupported = () => !stale && (result?.issues || []).some(issue => issue.severity === 'error' && issue.code === 'cross_table_cycle');
  const destroy = () => {
    closed = true;
    sequence++;
    scopeControl?.destroy();
    scrollLayout?.destroy();
  };
  let dialog;
  if (container) {
    dialog = {
      el: container,
      body: container,
      close: destroy
    };
  } else {
    dialog = modal(scope === 'selected' ? tr('preview.selectedTitle') : tr('preview.title'), {
      wide: true,
      onClose: destroy
    });
  }
  dialog.el.classList.add('wb-data-preview');
  const help = h('p', {
    id: `${id}-help`,
    class: 'wb-preview-help'
  }, tr('preview.intro'));
  const status = h('p', {
    class: 'wb-preview-status',
    role: 'status',
    'aria-live': 'polite'
  }, tr('preview.initialHint'));
  const error = h('p', {
    id: `${id}-error`,
    class: 'wb-preview-error',
    role: 'alert'
  });
  const corrections = h('div', {class:'wb-preview-corrections'});
  const issues = h('div', {
    class: 'wb-preview-issues'
  });
  const tabs = h('div', {
    class: 'wb-preview-tables',
    role: 'group',
    'aria-label': tr('preview.switchTable')
  });
  const relations = h('section', {class:'wb-preview-relations', 'aria-label':tr('preview.relationsLabel'), hidden:true});
  const results = h('section', {
    class: 'wb-preview-results',
    'aria-label': tr('preview.records')
  });
  scrollLayout = createPreviewScrollLayout({
    dialog,
    results,
    inline: Boolean(container)
  });
  const scopeHolder = h('div', {
    class: 'wb-preview-field'
  }, h('span', {}, tr('preview.scope')));
  const scopeSlot = h('div', {});
  scopeHolder.append(scopeSlot);
  const countInput = h('input', {
    type: 'number',
    min: 1,
    max: 100,
    step: 1,
    value: String(count),
    'aria-label': tr('preview.count'),
    'data-db-action': '',
    'aria-describedby': `${id}-count-help`
  });
  const countField = h('label', {
    class: 'wb-preview-field'
  }, h('span', {}, tr('preview.count')), countInput);
  const controls = h('div', {
    class: 'wb-preview-controls'
  }, ...(fixedScope ? [] : [scopeHolder]), countField);
  function live() {
    return !closed && dialog.el.isConnected && isCurrent();
  }
  function renderScope() {
    scopeControl?.destroy();
    if (fixedScope) {
      return;
    }
    scopeControl = createDropdown({
      label: tr('preview.scope'),
      value: scope,
      options: [{
        value: 'current',
        label: tr('preview.currentTable', {table: currentTable || tr('preview.none')})
      }, {
        value: 'selected',
        label: tr('preview.selectedTables', {count: formatNumber(selected.length)})
      }],
      onChange: value => {
        if (closed || busy) {
          return;
        }
        scope = value;
        shownTable = scope === 'current' ? currentTable : selected[0];
        selectedColumn = null;
        optionsChanged();
      }
    });
    scopeSlot.replaceChildren(scopeControl.el);
  }
  function countValid() {
    if (!validCount(countInput.value)) {
      setAttr(countInput, 'aria-invalid', 'true');
      setAttr(countInput, 'aria-describedby', `${id}-count-help ${id}-error`);
      setText(error, tr('preview.invalidCount'));
      return false;
    }
    countInput.removeAttribute('aria-invalid');
    setAttr(countInput, 'aria-describedby', `${id}-count-help`);
    count = Number(countInput.value);
    return true;
  }
  function optionsChanged() {
    if (closed || busy) {
      return;
    }
    scrollLayout.setTable(null);
    sequence++;
    result = null;
    stale = false;
    tableScroll.clear();
    setText(error, '');
    corrections.replaceChildren();
    results.replaceChildren();
    tabs.replaceChildren();
    relations.replaceChildren();relations.hidden = true;
    issues.replaceChildren();
    setText(status, tr('preview.changed'));
    if (countValid()) {
      onOptionsChange?.({
        scope,
        count
      });
    }
    setBusy(false);
  }
  countInput.addEventListener('input', optionsChanged);
  function setBusy(value) {
    busy = value;
    setControlDisabled(countInput, value || unsupported());
    setControlDisabled(refreshButton, value || unsupported());
    setText(refreshButton, unsupported() ? tr('preview.unsupportedAction') : hasPreviewResult || !container ? tr('preview.refresh') : tr('preview.generate'));
    setAttr(controls, 'aria-busy', String(value));
    setAttr(results, 'aria-busy', String(value));
    for (const tab of tabs.querySelectorAll('button')) {
      tab.disabled = value;
    }
    for (const link of relations.querySelectorAll('button')) link.disabled = value;
    for (const input of results.querySelectorAll('[data-preview-column]')) {
      input.disabled = value;
    }
    if (value) {
      // Close a floating list before disabling it; its options live outside
      // this holder and must not remain interactive during the request.
      scopeControl?.destroy();
      if (scopeControl) {
        scopeControl.el.querySelector('.dropdown-btn').disabled = true;
      }
    } else {
      renderScope();
    }
  }
  function cellText(table, column, row) {
    if (Object.hasOwn(row, column.name)) {
      return {
        text: valueText(row[column.name]),
        placeholder: false
      };
    }
    if (table?.omittedColumns?.[column.name]) {
      return {
        text: table.omittedColumns[column.name],
        placeholder: true
      };
    }
    if (column.is_autoincrement || column.is_rowid_alias) {
      return {
        text: tr('preview.allocated'),
        placeholder: true
      };
    }
    if (column.is_computed) {
      return {
        text: tr('preview.computed'),
        placeholder: true
      };
    }
    return {
      text: tr('preview.unavailable'),
      placeholder: true
    };
  }
  const viewport = node => ({
    left: node.scrollLeft || 0,
    top: node.scrollTop || 0
  });
  const bodyViewport = () => ({
    ...viewport(dialog.body),
    top: scrollLayout.captureVertical()?.bodyTop ?? (dialog.body.scrollTop || 0)
  });
  function rememberTableScroll() {
    const scroll = results.querySelector('.wb-preview-scroll');
    if (scroll) {
      tableScroll.set(shownTable, {
        ...viewport(scroll),
        top: scrollLayout.captureVertical()?.tableTop ?? (scroll.scrollTop || 0)
      });
    }
  }
  function restoreScroll(bodyPosition) {
    const scroll = results.querySelector('.wb-preview-scroll'),
      tablePosition = tableScroll.get(shownTable);
    if (scroll) {
      restoreViewport(scroll, tablePosition);
    }
    restoreViewport(dialog.body, bodyPosition);
    scrollLayout.restoreVertical(tablePosition?.top || 0, bodyPosition?.top || 0);
  }
  function getView() {
    rememberTableScroll();
    return {
      shownTable,
      column: selectedColumn,
      columnAction,
      count,
      scope,
      tableScroll: Object.fromEntries(tableScroll),
      relationOpen: Object.fromEntries(relationOpen),
      bodyScroll: bodyViewport(),
      result,
      stale
    };
  }
  function previewNames() {
    return scope === 'current' ? [currentTable] : [...new Set([...(result?.order || []).filter(name=>selected.includes(name)), ...selected])];
  }
  function selectPreviewTable(name, focus = false) {
    if (!live() || busy || !previewNames().includes(name)) return;
    rememberTableScroll();
    shownTable = name;
    selectedColumn = null;
    for (const item of tabs.querySelectorAll('button')) {
      setAttr(item, 'aria-pressed', String(item.dataset.previewTable === name));
    }
    renderRows();
    if (focus) [...tabs.querySelectorAll('button')].find(item=>item.dataset.previewTable === name)?.focus({preventScroll:true});
  }
  function renderRelations() {
    const incoming=relationEdges.filter(edge=>edge.target===shownTable && edge.source!==shownTable);
    const outgoing=relationEdges.filter(edge=>edge.source===shownTable && edge.target!==shownTable);
    const self=relationEdges.filter(edge=>edge.source===shownTable && edge.target===shownTable);
    const total=incoming.length+outgoing.length+self.length;
    relations.hidden=!total;
    if (!total) {relations.replaceChildren();return;}
    const name=shownTable;
    const facts=[incoming.length ? tr('preview.sourceCount', {count: incoming.length, value: formatNumber(incoming.length)}) : '', outgoing.length ? tr('preview.targetCount', {count: outgoing.length, value: formatNumber(outgoing.length)}) : '', self.length ? tr('preview.selfCount', {count: self.length, value: formatNumber(self.length)}) : ''].filter(Boolean);
    const details=h('details', {open:relationOpen.get(name)===true},
      h('summary', {}, tr('preview.relationSummary', {table: name, facts: joinText(facts, ' · ')})));
    details.addEventListener('toggle', ()=>relationOpen.set(name, details.open));
    function endpoint(table, columns) {
      return joinText([table, ' [', (columns || []).map(column=>JSON.stringify(column)).join(', ') || tr('preview.missingFields'), ']']);
    }
    function relationRow(edge, direction) {
      const other=direction==='incoming' ? edge.source : edge.target;
      const readonly=relationNodes.get(other)?.readonly || !schema.has(other);
      const generating=!readonly && selected.includes(other);
      const hasSample=Array.isArray(result?.samples?.[other]) && result.samples[other].length>0;
      const canNavigate=direction!=='self' && !readonly && scope==='selected' && selected.includes(other) && hasSample;
      let state;
      if (readonly) state=tr('preview.external');
      else if (generating) state=tr('preview.generating');
      else state=direction==='incoming' ? tr('preview.referenceExisting') : tr('preview.excluded');
      if (generating && !hasSample) state=joinText([state, tr('preview.noSamples')]);
      const info=h('div', {}, h('p', {class:'wb-preview-relation-state'}, joinText([other, state], ' · ')),
        h('code', {}, joinText([endpoint(edge.source, edge.sourceColumns), endpoint(edge.target, edge.targetColumns)], ' → ')));
      const row=h('li', {class:'wb-preview-relation-row'}, info);
      if (canNavigate) row.append(button(tr('preview.viewTable', {table: other}), ()=>selectPreviewTable(other, true), {
        small:true, disabled:busy, 'data-preview-related':other
      }));
      return row;
    }
    for (const [title, edges, direction] of [[tr('preview.parentSources'),incoming,'incoming'],[tr('preview.childTargets'),outgoing,'outgoing'],[tr('preview.selfReferences'),self,'self']]) {
      if (!edges.length) continue;
      details.append(h('h4', {}, title), h('ul', {class:'wb-preview-relation-list'}, ...edges.map(edge=>relationRow(edge,direction))));
    }
    details.append(h('p', {class:'wb-preview-relation-note'}, tr('preview.relationHint')));
    relations.replaceChildren(details);
  }
  function columnHeader(table, column) {
    const metadata = [column.type];
    if (column.is_primary_key || table?.primary_key?.includes(column.name)) {
      metadata.push('PK');
    }
    if (table?.foreign_keys?.some(key => key.columns?.includes(column.name))) {
      metadata.push('FK');
    }
    if (typeof column.nullable === 'boolean') {
      metadata.push(column.nullable ? tr('preview.nullable') : 'NOT NULL');
    }
    const label = h('span', {
        class: 'wb-preview-column-name'
      }, column.name),
      details = h('small', {
        class: 'wb-preview-column-meta'
      }, joinText(metadata.filter(Boolean), ' · '));
    if (!onColumnAction) {
      return h('th', {
        scope: 'col'
      }, label, details);
    }
    const activate = action => () => {
      if (!live() || busy) {
        return;
      }
      selectedColumn = column.name;
      columnAction = action;
      for (const input of results.querySelectorAll('[data-preview-column]')) {
        setAttr(input, 'aria-pressed', String(input.dataset.previewColumn === selectedColumn));
      }
      return onColumnAction(action, {
        table: shownTable,
        column: column.name,
        view: getView()
      });
    };
    const attributes = action => ({
      plain: true,
      class: `wb-preview-column-button wb-preview-column-${action}`,
      'data-preview-column': column.name,
      'data-preview-entry': action,
      'aria-pressed': String(column.name === selectedColumn),
      'aria-haspopup': 'dialog',
      disabled: busy
    });
    const name = button('', activate('information'), {
      ...attributes('information'),
      'aria-label': tr('preview.fieldInfo', {table: shownTable, column: column.name}),
      title: tr('preview.viewField')
    });
    name.append(label);
    const rule = table?.ruleSummaries?.[column.name];
    const properties = button(tr('preview.ruleLabel', {rule: rule?.label || tr('preview.valueRule')}), activate('rule'), {
      ...attributes('rule'),
      'aria-label': tr('preview.editRule', {table: shownTable, column: column.name}),
      title: rule?.detail || tr('preview.adjustRule')
    });
    setAttr(details, 'title', tr('preview.structure'));
    return h('th', {
      scope: 'col',
      class: 'wb-preview-interactive-header'
    }, name, details, properties);
  }
  function renderRows() {
    if (!result) {
      return;
    }
    const bodyScroll = bodyViewport();
    renderRelations();
    const name = shownTable;
    const table = schema.get(name);
    const rows = Array.isArray(result.samples?.[name]) ? result.samples[name] : [];
    const summary = h('p', {
      class: 'wb-preview-summary'
    }, tr('preview.rowCount', {table: name, rows: formatNumber(rows.length), limit: formatNumber(count)}));
    if (!rows.length) {
      let empty;
      if (unsupported()) {
        empty = tr('preview.unsupportedEmpty', {table: name});
      } else if (result.preview_complete === false) {
        empty = tr('preview.dependencyNotReady');
      } else if (result.ok === false) {
        empty = tr('preview.incompleteTable');
      } else {
        empty = tr('preview.emptyTable');
      }
      scrollLayout.setTable(null);
      results.replaceChildren(summary, h('p', {
        class: 'wb-preview-empty'
      }, empty));
      if (unsupported() && onCurrentData && schema.has(name)) results.append(button(tr('preview.currentData', {table: name}), () => {
        if (live() && !busy) onCurrentData(name);
      }, {small: true}), h('p', {class: 'wb-preview-help'}, tr('preview.currentDataHelp')));
      restoreViewport(dialog.body, bodyScroll);
      return;
    }
    const columns = table?.columns?.length ? table.columns : [...new Set(rows.flatMap(row => Object.keys(row)))].map(name => ({
      name
    }));
    const data = h('table', {
      class: 'wb-preview-data'
    }, h('caption', {}, tr('preview.caption', {table: name})), h('thead', {}, h('tr', {}, h('th', {
      scope: 'col'
    }, '#'), ...columns.map(column => columnHeader(table, column)))), h('tbody', {}, ...rows.map((row, index) => h('tr', {}, h('th', {
      scope: 'row'
    }, formatNumber(index + 1)), ...columns.map(column => {
      const value = cellText(table, column, row);
      return h('td', {
        class: value.placeholder ? 'wb-preview-placeholder' : ''
      }, value.text);
    })))));
    const scroll = h('div', {
      class: 'wb-preview-scroll',
      tabindex: 0,
      'aria-label': tr('preview.scrollLabel', {table: name})
    }, data);
    results.replaceChildren(summary, scroll);
    scrollLayout.setTable(scroll);
    restoreScroll(bodyScroll);
  }
  function renderResult() {
    const bodyScroll = bodyViewport();
    rememberTableScroll();
    const names = previewNames();
    if (!names.includes(shownTable)) {
      shownTable = names[0];
    }
    tabs.replaceChildren(...(scope === 'selected' ? names.map(name => button(name, () => selectPreviewTable(name), {
      small: true,
      class: 'wb-preview-table-button',
      'data-preview-table':name,
      'aria-pressed': String(name === shownTable)
    })) : []));
    function previewIssueList() {
      if (result.issues?.length) {
        return [h('ul', {}, ...result.issues.map(issue => h('li', {
          class: issue.severity === 'error' ? 'wb-error' : 'wb-preview-warning'
        }, joinText([[issue.table, issue.column].filter(Boolean).join('.'), issue.table || issue.column ? ': ' : '', serverText(issue) || tr('preview.issue')]))))];
      } else {
        return [];
      }
    }
    issues.replaceChildren(...previewIssueList());
    if (unsupported()) {
      const tables = [...new Set(result.issues.filter(issue => issue.code === 'cross_table_cycle').flatMap(issue => issue.tables || []))];
      issues.insertBefore(h('p', {}, tr('preview.unsupported', {tables: tables.join('、')})), issues.firstChild);
      if (onUnsupported) issues.append(button(tr('preview.unsupportedReason'), () => {
        if (live() && !busy) onUnsupported(result);
      }, {small: true}));
    }
    renderRows();
    restoreScroll(bodyScroll);
  }
  const refresh = guard(async () => {
    if (closed || busy || unsupported()) {
      return;
    }
    setText(error, '');
    corrections.replaceChildren();
    if (!live()) {
      setText(error, tr('preview.configChanged'));
      return;
    }
    if (!countValid()) {
      return;
    }
    if (scope === 'selected' && !selected.length) {
      setText(error, tr('preview.selectTables'));
      return;
    }
    if (scope === 'current' && !schema.has(currentTable)) {
      setText(error, tr('preview.selectCurrent'));
      return;
    }
    const request = ++sequence,
      options = {
        scope,
        count,
        table: currentTable
      };
    const stillCurrent = () => live() && request === sequence;
    showPreviewLoading();
    setBusy(true);
    try {
      let response;
      try {
        response = await generate(options);
      } catch (error_) {
        if (stillCurrent()) {
          showPreviewFailure(error_);
        }
        return;
      }
      if (!stillCurrent()) {
        return;
      }
      if (!response) {
        setText(error, tr('preview.expired'));
        setText(status, result ? tr('preview.oldResult') : '');
        return;
      }
      acceptPreview(response);
      return response;
    } finally {
      finishPreviewRequest();
    }
    function showPreviewFailure(error_) {
      const invalidConfiguration = error_?.code === 'workbench_invalid_input';
      setText(error, invalidConfiguration
        ? tr('preview.invalidConfiguration', {count, value: formatNumber(count), detail: errorText(error_)})
        : errorText(error_));
      if (invalidConfiguration && onValidationIssue) {
        corrections.replaceChildren(...(error_.issues || []).filter(issue => issue.kind === 'generation-count' && issue.table).map(issue =>
          button(tr('preview.fixCount', {table: issue.table}), () => {
            if (!stillCurrent() || busy) return;
            dialog.close();
            return onValidationIssue(issue);
          }, {small:true})));
      }
      if (result) {
        if (stale) {
          setText(status, tr('preview.failedStale'));
        } else {
          setText(status, tr('preview.failedPrevious'));
        }
      } else {
        setText(status, invalidConfiguration ? tr('preview.fixConfiguration') : tr('preview.retry'));
      }
      onError?.(error_);
    }
    function finishPreviewRequest() {
      if (!closed && dialog.el.isConnected) {
        if (!result) {
          results.replaceChildren();
        }
        setBusy(false);
        if (!isCurrent()) {
          setText(status, result ? tr('preview.oldConfigChanged') : '');
          setText(error, tr('preview.configChanged'));
        }
      }
    }
    function acceptPreview(response) {
      result = response;
      hasPreviewResult = true;
      stale = false;
      renderResult();
      setText(refreshButton, tr('preview.refresh'));
      if (unsupported()) {
        setText(status, tr('preview.unsupportedStatus'));
      } else if (response.ok === false) {
        setText(status, tr('preview.issueHint'));
      } else if (response.preview_complete === false) {
        setText(status, tr('preview.partial'));
      } else {
        setText(status, tr('preview.updated'));
      }
      onResult?.(response, options);
    }
  });
  const refreshButton = button(container ? tr('preview.generate') : tr('preview.refresh'), refresh, {
    glyph: 'refresh',
    'data-db-action': ''
  });
  controls.append(refreshButton);
  renderScope();
  dialog.body.append(help, controls, h('p', {
    id: `${id}-count-help`,
    class: 'wb-preview-help'
  }, tr('preview.countHint')), status, error, corrections, issues, tabs, relations, results);
  if (initialResult) {
    result = initialResult;
    renderResult();
    setText(refreshButton, tr('preview.refresh'));
    setText(status, stale ? tr('preview.initialStale') : unsupported() ? tr('preview.unsupportedStatus') : tr('preview.initialResult'));
    setBusy(false);
  }
  restoreScroll(initialView?.bodyScroll);
  return {
    dialog,
    refresh,
    destroy,
    getView
  };
}
function restoreViewport(node, position) {
  if (!position) {
    return;
  }
  node.scrollLeft = Math.max(0, Math.min(position.left, (node.scrollWidth || 0) - (node.clientWidth || 0)));
  node.scrollTop = Math.max(0, Math.min(position.top, (node.scrollHeight || 0) - (node.clientHeight || 0)));
}
