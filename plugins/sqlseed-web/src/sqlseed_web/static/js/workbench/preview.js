import { h } from '../api.js';
import { createDropdown } from '../dropdown.js';
import { modal, button, valueText } from './ui.js';
import { createPreviewScrollLayout } from './preview-scroll-layout.js';
let nextPreviewId = 0;
const validCount = value => /^\d+$/.test(String(value)) && Number(value) >= 1 && Number(value) <= 100;

/** Readonly preview state stays local; the caller owns configuration and transport. */
export function openDataPreview({
  tables,
  currentTable,
  selectedTables,
  initialScope = 'current',
  initialCount = 10,
  generate,
  guard = task => task,
  isCurrent = () => true,
  onOptionsChange,
  onResult,
  onError,
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
      }, '正在生成预览数据…'));
    }
    if (result) {
      if (stale) {
        status.textContent = '正在更新；规则已改变，当前为旧样例。';
      } else {
        status.textContent = '正在更新，当前为上次结果。';
      }
    } else {
      status.textContent = '正在生成预览数据…';
    }
  }

  const id = `wb-preview-${++nextPreviewId}`;
  const schema = new Map(tables.map(table => [table.name, table]));
  const selected = [...new Set(selectedTables)];
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
  let columnAction = initialView?.columnAction || 'information';
  let scrollLayout = null;
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
    dialog = modal(scope === 'selected' ? '预览已选表' : '预览数据', {
      wide: true,
      onClose: destroy
    });
  }
  dialog.el.classList.add('wb-data-preview');
  const help = h('p', {
    id: `${id}-help`,
    class: 'wb-preview-help'
  }, '按当前规则生成临时记录，不写入数据库。正式生成时会重新取值。');
  const status = h('p', {
    class: 'wb-preview-status',
    role: 'status',
    'aria-live': 'polite'
  }, '点击“生成预览”查看当前规则的效果。');
  const error = h('p', {
    id: `${id}-error`,
    class: 'wb-preview-error',
    role: 'alert'
  });
  const issues = h('div', {
    class: 'wb-preview-issues'
  });
  const tabs = h('div', {
    class: 'wb-preview-tables',
    role: 'group',
    'aria-label': '切换预览表'
  });
  const results = h('section', {
    class: 'wb-preview-results',
    'aria-label': '预览记录'
  });
  scrollLayout = createPreviewScrollLayout({
    dialog,
    results,
    inline: Boolean(container)
  });
  const scopeHolder = h('div', {
    class: 'wb-preview-field'
  }, h('span', {}, '预览范围'));
  const scopeSlot = h('div', {});
  scopeHolder.append(scopeSlot);
  const countInput = h('input', {
    type: 'number',
    min: 1,
    max: 100,
    step: 1,
    value: String(count),
    'aria-label': '每表预览行数',
    'data-db-action': '',
    'aria-describedby': `${id}-count-help ${id}-error`
  });
  const countField = h('label', {
    class: 'wb-preview-field'
  }, h('span', {}, '每表预览行数'), countInput);
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
      label: '预览范围',
      value: scope,
      options: [{
        value: 'current',
        label: `当前表 · ${currentTable || '未选择'}`
      }, {
        value: 'selected',
        label: `已选表 · ${selected.length} 张`
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
      countInput.setAttribute('aria-invalid', 'true');
      error.textContent = '每表预览行数必须是 1–100 之间的整数。';
      return false;
    }
    countInput.removeAttribute('aria-invalid');
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
    error.textContent = '';
    results.replaceChildren();
    tabs.replaceChildren();
    issues.replaceChildren();
    status.textContent = '设置已改变，请重新预览。';
    if (countValid()) {
      onOptionsChange?.({
        scope,
        count
      });
    }
  }
  countInput.addEventListener('input', optionsChanged);
  function setBusy(value) {
    busy = value;
    countInput.disabled = value;
    refreshButton.disabled = value;
    controls.setAttribute('aria-busy', String(value));
    results.setAttribute('aria-busy', String(value));
    for (const tab of tabs.querySelectorAll('button')) {
      tab.disabled = value;
    }
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
        text: '数据库分配',
        placeholder: true
      };
    }
    if (column.is_computed) {
      return {
        text: '数据库计算',
        placeholder: true
      };
    }
    return {
      text: '暂不可预览',
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
      bodyScroll: bodyViewport(),
      result,
      stale
    };
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
      metadata.push(column.nullable ? '允许 NULL' : 'NOT NULL');
    }
    const label = h('span', {
        class: 'wb-preview-column-name'
      }, column.name),
      details = h('small', {
        class: 'wb-preview-column-meta'
      }, metadata.filter(Boolean).join(' · '));
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
        input.setAttribute('aria-pressed', String(input.dataset.previewColumn === selectedColumn));
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
      'aria-label': `查看 ${shownTable}.${column.name} 的字段信息`,
      title: '查看字段信息'
    });
    name.append(label);
    const rule = table?.ruleSummaries?.[column.name];
    const properties = button(`规则：${rule?.label || '取值规则'}`, activate('rule'), {
      ...attributes('rule'),
      'aria-label': `调整 ${shownTable}.${column.name} 的生成规则`,
      title: rule?.detail || '调整生成规则'
    });
    details.title = '数据库结构';
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
    const name = shownTable;
    const table = schema.get(name);
    const rows = Array.isArray(result.samples?.[name]) ? result.samples[name] : [];
    const summary = h('p', {
      class: 'wb-preview-summary'
    }, `${name} · 实际展示 ${rows.length} 行 · 每表最多 ${count} 行`);
    if (!rows.length) {
      let empty;
      if (result.preview_complete === false) {
        empty = '本表暂未返回可预览记录，关联依赖数据可能尚未就绪。请查看依赖检查及上方提示。';
      } else if (result.ok === false) {
        empty = '本表预览未完成，请处理上方提示后重新预览。';
      } else {
        empty = '本表未返回预览记录。';
      }
      scrollLayout.setTable(null);
      results.replaceChildren(summary, h('p', {
        class: 'wb-preview-empty'
      }, empty));
      restoreViewport(dialog.body, bodyScroll);
      return;
    }
    const columns = table?.columns?.length ? table.columns : [...new Set(rows.flatMap(row => Object.keys(row)))].map(name => ({
      name
    }));
    const data = h('table', {
      class: 'wb-preview-data'
    }, h('caption', {}, `${name} · 预览记录`), h('thead', {}, h('tr', {}, h('th', {
      scope: 'col'
    }, '#'), ...columns.map(column => columnHeader(table, column)))), h('tbody', {}, ...rows.map((row, index) => h('tr', {}, h('th', {
      scope: 'row'
    }, String(index + 1)), ...columns.map(column => {
      const value = cellText(table, column, row);
      return h('td', {
        class: value.placeholder ? 'wb-preview-placeholder' : ''
      }, value.text);
    })))));
    const scroll = h('div', {
      class: 'wb-preview-scroll',
      tabindex: 0,
      'aria-label': `${name} 预览数据，可横向滚动`
    }, data);
    results.replaceChildren(summary, scroll);
    scrollLayout.setTable(scroll);
    restoreScroll(bodyScroll);
  }
  function renderResult() {
    const bodyScroll = bodyViewport();
    rememberTableScroll();
    const names = scope === 'current' ? [currentTable] : [...new Set([...(result.order || []).filter(name => selected.includes(name)), ...selected])];
    if (!names.includes(shownTable)) {
      shownTable = names[0];
    }
    tabs.replaceChildren(...(scope === 'selected' ? names.map(name => button(name, () => {
      if (closed || busy) {
        return;
      }
      rememberTableScroll();
      shownTable = name;
      selectedColumn = null;
      for (const item of tabs.querySelectorAll('button')) {
        item.setAttribute('aria-pressed', String(item.textContent === name));
      }
      renderRows();
    }, {
      small: true,
      class: 'wb-preview-table-button',
      'aria-pressed': String(name === shownTable)
    })) : []));
    function previewIssueList() {
      if (result.issues?.length) {
        return [h('ul', {}, ...result.issues.map(issue => h('li', {
          class: issue.severity === 'error' ? 'wb-error' : 'wb-preview-warning'
        }, [issue.table, issue.column].filter(Boolean).join('.') + (issue.table || issue.column ? '：' : '') + String(issue.message || '预览存在待处理项'))))];
      } else {
        return [];
      }
    }
    issues.replaceChildren(...previewIssueList());
    renderRows();
    restoreScroll(bodyScroll);
  }
  const refresh = guard(async () => {
    if (closed || busy) {
      return;
    }
    error.textContent = '';
    if (!live()) {
      error.textContent = '配置已变化，请重新打开预览。';
      return;
    }
    if (!countValid()) {
      return;
    }
    if (scope === 'selected' && !selected.length) {
      error.textContent = '请先勾选需要预览的表，或切换到当前表。';
      return;
    }
    if (scope === 'current' && !schema.has(currentTable)) {
      error.textContent = '请先选择当前表。';
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
        error.textContent = '配置已变化或结果已过期，请重新打开预览。';
        status.textContent = result ? '当前为上次结果，请重新打开预览。' : '';
        return;
      }
      acceptPreview(response);
      return response;
    } finally {
      finishPreviewRequest();
    }
    function showPreviewFailure(error_) {
      error.textContent = error_?.message || String(error_);
      if (result) {
        if (stale) {
          status.textContent = '更新失败；规则已改变，当前为旧样例，请重新预览。';
        } else {
          status.textContent = '更新失败，当前为上次结果，可重新预览。';
        }
      } else {
        status.textContent = '预览未完成，可重试。';
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
          status.textContent = result ? '当前为上次结果，配置已变化。' : '';
          error.textContent = '配置已变化，请重新打开预览。';
        }
      }
    }
    function acceptPreview(response) {
      result = response;
      stale = false;
      renderResult();
      refreshButton.textContent = '重新预览';
      if (response.ok === false) {
        status.textContent = '预览存在待处理项，请查看下方提示。';
      } else if (response.preview_complete === false) {
        status.textContent = '已展示可预览数据；部分关联记录需等待依赖数据就绪。';
      } else {
        status.textContent = '预览数据已更新，数据库未写入。';
      }
      onResult?.(response, options);
    }
  });
  const refreshButton = button(container ? '生成预览' : '重新预览', refresh, {
    glyph: 'refresh',
    'data-db-action': ''
  });
  controls.append(refreshButton);
  renderScope();
  dialog.body.append(help, controls, h('p', {
    id: `${id}-count-help`,
    class: 'wb-preview-help'
  }, '每表最多预览 1–100 行，且不超过该表配置的生成数量；此设置不会修改正式生成行数。'), status, error, issues, tabs, results);
  if (dialog.actions) {
    dialog.actions.append(button('关闭', dialog.close));
  }
  if (initialResult) {
    result = initialResult;
    renderResult();
    refreshButton.textContent = '重新预览';
    status.textContent = stale ? '规则已改变，当前为旧样例，请重新预览。' : '上次预览结果；重新预览可更新取值。';
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
