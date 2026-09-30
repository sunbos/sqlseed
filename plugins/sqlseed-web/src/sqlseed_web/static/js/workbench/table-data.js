import {tr, joinText, formatNumber, formatDate, setText, setAttr, appendContent, replaceContent, UserFacingError, errorText} from '../i18n.js';
import '../i18n/messages/components.js';
import { h, api } from '../api.js';
import { modal, button, valueText } from './ui.js';

/** Match preview's ISO spelling without parsing, rounding or shifting a timestamp. */
function temporalText(value, type) {
  if (typeof value !== 'string' || !/^(?:DATETIME|TIMESTAMP|TIME)(?:\(\d+\))?(?: (?:WITH|WITHOUT) TIME ZONE)?$/.test(String(type || '').trim().toUpperCase())) {
    return valueText(value);
  }
  const time = String.raw`(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d`;
  const zone = String.raw`(?:Z|[+-]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?`;
  const isTime = /^TIME(?:\(| |$)/.test(String(type).trim().toUpperCase());
  const pattern = isTime ? String.raw`^(${time})(\.\d+)?(${zone})$` : String.raw`^(\d{4}-\d{2}-\d{2})[ T](${time})(\.\d+)?(${zone})$`;
  const match = new RegExp(pattern).exec(value);
  if (!match) return value;
  const fraction = match[isTime ? 2 : 3] || '';
  const suffix = /^\.0+$/.test(fraction) ? '' : fraction;
  return isTime ? `${match[1]}${suffix}${match[3]}` : `${match[1]}T${match[2]}${suffix}${match[4]}`;
}

/** Read current database rows without changing the active connection or generation document. */
export function openTableData({
  connId = null,
  runId = null,
  table,
  targetKey,
  targetLabel = '',
  isCurrent = () => true,
  returnFocus = null
}) {
  let closed = false,
    busy = false,
    controller = null,
    result = null;
  let connection = runId ? null : connId;
  const limit = 50;
  const dialog = modal(tr('tableData.title'), {
    wide: true,
    returnFocus,
    onClose: () => {
      closed = true;
      controller?.abort();
    }
  });
  dialog.el.classList.add('wb-table-data');
  const target = h('p', {
    class: 'mono wb-table-data-target'
  }, targetLabel);
  const status = h('p', {
    class: 'wb-table-data-status',
    role: 'status',
    'aria-live': 'polite'
  }, tr('tableData.loading'));
  const error = h('p', {
    class: 'wb-table-data-error',
    role: 'alert'
  });
  const records = h('section', {
    class: 'wb-table-data-records',
    'aria-label': tr('tableData.currentRecords', {table})
  });
  const page = h('span', {
    class: 'muted'
  });
  const refreshed = h('p', {
    class: 'muted wb-table-data-read-at'
  });
  const ordering = h('p', {
    class: 'muted wb-table-data-order'
  });
  const refreshButton = button(tr('tableData.refresh'), () => load(result?.offset || 0));
  const previous = button(tr('tableData.previous'), () => load(Math.max(0, (result?.offset || 0) - limit)));
  const next = button(tr('tableData.next'), () => load((result?.offset || 0) + limit));
  appendContent(dialog.body, h('div', {
    class: 'wb-table-data-heading'
  }, h('h3', {
    class: 'mono'
  }, table), refreshButton), target, h('p', {
    class: 'muted'
  }, tr('tableData.hint')), status, error, records, h('div', {
    class: 'wb-table-data-pagination'
  }, page, h('div', {}, previous, next)), refreshed, ordering);
  const live = () => !closed && dialog.el.isConnected && isCurrent();
  function setBusy(value) {
    busy = value;
    refreshButton.disabled = value;
    previous.disabled = value || !result || result.offset === 0;
    next.disabled = value || !result || result.offset + result.limit >= result.total;
    setAttr(records, 'aria-busy', String(value));
  }
  function displayValue(value, column) {
    const raw = valueText(value);
    const text = temporalText(value, column.type);
    if (text !== raw) {
      return h('details', {
        class: 'wb-table-data-value wb-table-data-temporal'
      }, h('summary', {
        title: tr('tableData.viewRaw'),
        'aria-label': tr('tableData.rawAria', {value: text})
      }, text), h('small', {}, tr('tableData.raw')), h('pre', {}, raw));
    }
    return text.length > 160 ? h('details', {
      class: 'wb-table-data-value'
    }, h('summary', {}, tr('tableData.expandValue', {value: text.slice(0, 80)})), h('pre', {}, text)) : text;
  }
  function render(data) {
    function databaseDialectLabel() {
      if (data.dialect === 'postgresql') {
        return 'PostgreSQL';
      } else if (data.dialect === 'sqlite') {
        return 'SQLite';
      } else {
        return data.dialect;
      }
    }
    setText(target, `${databaseDialectLabel()} · ${data.target_label}`);
    const grid = h('table', {}, h('caption', {}, tr('tableData.caption', {table})), h('thead', {}, h('tr', {}, ...data.columns.map(column => h('th', {
      scope: 'col'
    }, h('span', {
      class: 'mono'
    }, column.name), h('small', {}, [column.type, column.is_primary_key ? 'PK' : null].filter(Boolean).join(' · ')))))), h('tbody', {}, ...data.rows.map(row => h('tr', {}, ...data.columns.map(column => h('td', {}, displayValue(row[column.name], column)))))));
    function emptyDataPage() {
      if (data.rows.length) {
        return [];
      } else {
        return [h('p', {
          class: 'wb-table-data-empty'
        }, data.total ? tr('tableData.emptyPage') : tr('tableData.emptyTable'))];
      }
    }
    replaceContent(records, h('div', {
      class: 'wb-table-data-scroll',
      tabindex: 0,
      'aria-label': tr('tableData.scrollAria', {table})
    }, grid), ...emptyDataPage());
    setText(page, tr('tableData.pagination', {range: data.rows.length ? joinText([formatNumber(data.offset + 1), '–', formatNumber(data.offset + data.rows.length)]) : '0', total: formatNumber(data.total), limit: formatNumber(limit)}));
    const date = new Date(data.read_at);
    setText(refreshed, tr('tableData.readTime', {date: Number.isNaN(date.getTime()) ? data.read_at : formatDate(date, {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false})}));
    setText(ordering, data.order_by?.length ? tr('tableData.primaryOrder', {columns: data.order_by.join(', ')}) : tr('tableData.noPrimaryKey'));
  }
  async function load(offset = 0) {
    if (!live() || busy) {
      return;
    }
    controller = new AbortController();
    setBusy(true);
    setText(error, '');
    setText(status, result ? tr('tableData.refreshing') : tr('tableData.loading'));
    try {
      if (!(await ensureConnection())) {
        return;
      }
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset)
      });
      if (runId) {
        params.set('run_id', runId);
      }
      const data = await api(`/api/workbench/connections/${encodeURIComponent(connection)}/tables/${encodeURIComponent(table)}/data?${params}`, {
        signal: controller.signal
      });
      if (!live()) {
        return;
      }
      if (data.target_key !== targetKey || data.table !== table) {
        throw new UserFacingError(tr('tableData.wrongTarget'));
      }
      result = data;
      render(data);
      setText(status, tr('tableData.loaded'));
    } catch (error_) {
      if (!live() || error_.name === 'AbortError') return;
      if (runId && error_.status === 404) connection = null;
      setText(error, tr('tableData.readError', {detail: errorText(error_)}));
      setText(status, result ? tr('tableData.previousRecords') : tr('tableData.notLoaded'));
    } finally {
      if (live()) {
        setBusy(false);
      }
    }
    async function ensureConnection() {
      if (!connection && runId) {
        const matched = await api(`/api/workbench/runs/${encodeURIComponent(runId)}/data-connections`, {
          signal: controller.signal
        });
        if (!live()) {
          return false;
        }
        if (matched.target_key !== targetKey) {
          throw new UserFacingError(tr('tableData.changedTarget'));
        }
        connection = matched.connections?.[0]?.conn_id || null;
        if (!connection) {
          throw new UserFacingError(tr('tableData.connectTarget'));
        }
      }
      if (!connection) {
        throw new UserFacingError(tr('tableData.connectionExpired'));
      }
      return true;
    }
  }
  const ready = load();
  return {
    dialog,
    ready,
    refresh: () => load(result?.offset || 0),
    close: dialog.close
  };
}
