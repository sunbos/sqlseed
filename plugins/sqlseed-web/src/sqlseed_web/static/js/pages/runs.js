import { h, get } from '../api.js';
import { download, valueText } from '../workbench/ui.js';
import { remainingRun } from '../workbench/recovery.js';
import { openTableData } from '../workbench/table-data.js';
const labels = {
  queued: '等待执行',
  running: '生成中',
  done: '生成成功',
  error: '生成失败',
  interrupted: '服务中断',
  not_run: '未执行'
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
const action = (label, handler, attrs = {}) => h('button', {
  type: 'button',
  class: 'btn',
  onclick: handler,
  ...attrs
}, label);
export function render() {
  version++;
  selectedId = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
  notice = h('p', {
    class: 'run-notice wb-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  list = h('aside', {
    class: 'run-list',
    'aria-label': '运行列表'
  });
  detail = h('section', {
    class: 'run-detail wb-run-detail'
  }, h('p', {
    class: 'empty'
  }, '选择一条运行记录查看结果。'));
  workspace = h('div', {
    class: 'runs-workspace'
  }, list, detail);
  root = h('div', {
    class: 'page runs-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('div', {
    class: 'crumb'
  }, 'sqlseed'), h('h1', {}, '运行记录'), h('p', {
    class: 'subtitle'
  }, '查看已提交的配置版本与逐表结果。')), h('div', {
    class: 'heading-actions'
  }, h('a', {
    href: '#/workbench',
    class: 'btn'
  }, '返回工作台'), action('刷新', () => refresh(version)))), notice, workspace);
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
      workspace.replaceChildren(h('section', {
        class: 'run-empty',
        role: 'status'
      }, h('h2', {}, '还没有运行记录'), h('p', {}, '生成后会在这里保留配置版本、执行结果与实际写入数量'), h('a', {
        href: '#/workbench',
        class: 'btn primary'
      }, '返回工作台')));
      notice.textContent = '';
      return;
    }
    workspace.replaceChildren(list, detail);
    if (!selectedId && runs.length) selectedId = runs[0].id;
    list.replaceChildren(...runs.map(run => action('', () => {
      dataViewer?.close();
      dataViewer = null;
      selectedId = run.id;
      refresh(version);
    }, {
      class: `run-card wb-run-card${run.id === selectedId ? ' active' : ''}`,
      'aria-pressed': String(run.id === selectedId)
    })));
    [...list.querySelectorAll('.wb-run-card')].forEach((card, i) => card.append(h('strong', {}, runs[i].name || runs[i].id), status(runs[i].status), h('small', {}, runTime(runs[i].created_at ?? runs[i].started_at)), h('small', {}, runs[i].target_label)));
    if (selectedId) {
      const run = await get(`/api/workbench/runs/${encodeURIComponent(selectedId)}`);
      if (!current()) return;
      drawRun(run);
    }
    notice.textContent = '';
    if (runs.some(run => ['queued', 'running'].includes(run.status))) timer = setTimeout(() => refresh(expected), 1200);
  } catch (error) {
    if (!current()) return;
    notice.textContent = `暂时无法读取记录：${error.message}。这不代表任务已失败。`;
    timer = setTimeout(() => refresh(expected), 5000);
  }
}
function status(value) {
  return h('span', {
    class: `run-status ${value}`
  }, labels[value] || value || '状态待确认');
}
function runTime(value) {
  if (value === undefined || value === null || value === '') return h('span', {}, '时间未知');
  const timestamp = typeof value === 'number' ? value * 1000 : value;
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return h('span', {}, '时间未知');
  return h('time', {
    datetime: date.toISOString()
  }, date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }));
}
function errorMessages(...values) {
  return [...new Set(values.flatMap(value => Array.isArray(value) ? value : [value]).filter(value => value !== undefined && value !== null && value !== '').map(valueText))];
}
function knownCount(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
function tableResult(table) {
  const errors = errorMessages(table.errors, table.error);
  if (errors.length) return errors.join('；');
  const descriptions = {
    done: '生成成功，数据已提交',
    error: '生成失败，请查看本次运行的错误详情',
    queued: '等待前序表完成后执行',
    running: '正在生成，提交数量统计中',
    not_run: '前序任务未完成，本表未执行',
    interrupted: '执行被中断，提交情况待核对'
  };
  return descriptions[table.status] || '结果待确认';
}
function viewTable(run, table) {
  if (selectedId !== run.id || !root?.isConnected) return;
  const expected = version;
  dataViewer?.close();
  dataViewer = openTableData({
    runId: run.id,
    table: table.name,
    targetKey: run.target_key,
    targetLabel: run.target_label,
    isCurrent: () => version === expected && selectedId === run.id && Boolean(root?.isConnected)
  });
}
function drawRun(run) {
  const recovery = remainingRun(run);
  const count = run.rows_inserted;
  const replacement = run.execution?.mode === 'replace_selected';
  const exact = knownCount(count) && run.row_counts_exact !== false && run.count_complete !== false;
  const errors = errorMessages(run.errors, run.error);
  const tables = Array.isArray(run.tables) ? run.tables : [];
  const configured = Array.isArray(run.document?.tables) ? run.document.tables : [];
  const plannedCount = table => table.requested_count ?? table.count ?? configured.find(item => item.name === table.name)?.count;
  const planned = tables.length && tables.every(table => knownCount(plannedCount(table))) ? tables.reduce((total, table) => total + plannedCount(table), 0) : null;
  function executionDescription() {
    if (replacement) {
      return `清空所选表后生成 · 自增计数${run.execution.reset_identity ? '重置' : '保留'}`;
    } else {
      return '追加数据 · 保留已有记录';
    }
  }
  function committedCountMetric() {
    if (knownCount(count)) {
      return h('div', {}, h('strong', {}, `${exact ? '' : '至少 '}${count.toLocaleString()}`), ['queued', 'running'].includes(run.status) ? ' 行已确认提交' : ' 行已提交');
    } else {
      return h('div', {
        class: 'run-metric-unknown'
      }, '提交数量待核对');
    }
  }
  function tableCommittedCount(table) {
    if (table.status === 'running') {
      return '统计中';
    } else if (knownCount(table.rows_inserted)) {
      return table.rows_inserted;
    } else {
      return '待核对';
    }
  }
  function runRecoveryCard() {
    if (run.status === 'error') {
      return h('section', {
        class: 'run-recovery wb-source-card',
        'aria-label': '失败后的下一步'
      }, h('h3', {}, '接下来怎么处理'), h('p', {}, recovery.ok ? '已提交的数据会保留。新配置只包含未完成表的剩余行数；先修正规则、预览并检查依赖，再确认追加。' : recovery.reason), ...(recovery.ok ? [h('p', {
        class: 'muted'
      }, '已完成的父表改为引用已有数据。剩余配置不保证延续上次随机序列，也不能自动修复业务关系。'), h('a', {
        href: `#/workbench?run=${encodeURIComponent(run.id)}&recover=remaining`,
        class: 'btn primary'
      }, '修正并生成剩余数据')] : []));
    } else {
      return null;
    }
  }
  const content = [h('div', {
    class: 'run-heading'
  }, h('h2', {}, run.name || '生成任务'), status(run.status)), h('p', {
    class: 'mono run-target'
  }, run.target_label), h('p', {
    class: 'muted run-identity'
  }, `配置 v${run.revision ?? '—'} · ${run.id}`), h('p', {
    class: 'run-execution'
  }, executionDescription()), run.result?.rolled_back ? h('p', {
    class: 'run-rollback',
    role: 'status'
  }, '本次清空和生成已回滚，原有数据已保留；本次没有新增已提交记录。') : null, replacement && run.status === 'running' ? h('p', {
    class: 'muted'
  }, '正在同一事务中清空和生成，全部成功后才确认提交。') : null, h('div', {
    class: 'run-metrics'
  }, h('div', {
    class: 'run-total run-planned'
  }, h('span', {
    class: 'run-metric-label'
  }, '计划生成'), h('div', {}, h('strong', {}, planned === null ? '未记录' : planned.toLocaleString()), planned === null ? '' : ' 行')), h('div', {
    class: 'run-total run-committed'
  }, h('span', {
    class: 'run-metric-label'
  }, '实际已提交'), committedCountMetric())), h('p', {
    class: 'muted run-count-explanation'
  }, '计划行数来自本次配置；已提交是本次新增并确认写入的记录，不包含数据库中原有的数据。'), !exact ? h('p', {
    class: 'run-warning'
  }, '无法确认最后一批的提交状态。这里保留已知数量，请核对数据库后再决定是否重新生成。') : null, h('div', {
    class: 'run-table-scroll'
  }, h('table', {
    class: 'run-table'
  }, h('thead', {}, h('tr', {}, ...['表', '状态', '计划行数', '已提交', '结果'].map(text => h('th', {}, text)))), h('tbody', {}, ...tables.map(table => h('tr', {}, h('td', {
    class: 'mono'
  }, table.name), h('td', {}, status(table.status)), h('td', {}, plannedCount(table) ?? '未记录'), h('td', {}, tableCommittedCount(table)), h('td', {
    class: table.status === 'error' ? 'run-error' : ''
  }, h('div', {
    class: 'run-result-content'
  }, h('span', {}, tableResult(table)), action('查看当前数据', () => viewTable(run, table), {
    class: 'btn run-view-data',
    disabled: ['queued', 'running'].includes(run.status),
    title: ['queued', 'running'].includes(run.status) ? '运行结束后可查看数据库当前数据' : '查看数据库当前记录，包含已有数据'
  })))))))), errors.length ? h('div', {
    class: 'run-error',
    role: 'alert'
  }, ...errors.map(error => h('p', {}, error))) : null, runRecoveryCard(), h('details', {
    class: 'run-snapshot'
  }, h('summary', {}, '本次配置快照'), h('p', {
    class: 'muted'
  }, '这是提交时的固定版本，后续编辑不会改变本次运行。'), h('pre', {}, JSON.stringify(run.document, null, 2)), action('导出快照 JSON', () => download(`sqlseed-run-${run.id}.json`, JSON.stringify({
    target_key: run.target_key,
    schema_hash: run.schema_hash,
    document: run.document,
    execution: run.execution || {
      mode: 'append',
      reset_identity: false
    },
    plan_hash: run.plan_hash
  }, null, 2)))), h('div', {
    class: 'run-actions'
  }, h('a', {
    href: `#/workbench?run=${encodeURIComponent(run.id)}`,
    class: 'btn'
  }, '从此快照新建配置')), run.status === 'error' ? h('p', {
    class: 'muted'
  }, '从完整快照新建会复用全部计划行数，可能再次生成已经提交的数据。') : null, replacement ? h('p', {
    class: 'muted'
  }, '从快照新建只复用生成规则，默认追加；清空需在生成前重新选择并确认。') : null, ['queued', 'running'].includes(run.status) ? h('p', {
    class: 'muted'
  }, '任务由服务端执行，离开此页面不影响生成。') : null];
  detail.replaceChildren(...content.filter(element => element !== null));
}
