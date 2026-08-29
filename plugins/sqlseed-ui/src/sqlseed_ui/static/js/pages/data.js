// 数据页：浏览已生成的数据（分页查询 + 手写 SQL 控制台）。

import { h, get, post, store, msg, clear, table, fmt } from '../api.js';
import { createDropdown } from '../dropdown.js';

let view = { table: '', limit: 50, offset: 0 };
let sqlText = '';

const tableDd = createDropdown({
  options: [],
  placeholder: '— 选择 —',
  onChange: (v) => { view.table = v; view.offset = 0; loadRows(); },
});
const limitDd = createDropdown({
  value: '50',
  options: [20, 50, 100, 200].map((n) => ({ value: String(n), label: String(n) })),
  width: '90px',
  onChange: (v) => { view.limit = +v; view.offset = 0; loadRows(); },
});

export function render() {
  const root = h('div');
  tableDd.setOptions(
    store.tables.map((t) => ({ value: t.name, label: t.name })),
    view.table || '',
  );
  root.append(
    h('h2', {}, '数据浏览'),
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('label', {}, '表'),
        tableDd.el,
        h('label', {}, '每页'),
        limitDd.el,
      ),
    ),
    h('div', { id: 'data-out' }, h('div', { class: 'muted' }, '选择一张表查看数据。')),
    h('div', { class: 'panel' },
      h('h3', {}, 'SQL 控制台（只读 SELECT）'),
      h('textarea', {
        id: 'sql-input', spellcheck: 'false', style: 'min-height:100px',
        oninput: (e) => { sqlText = e.target.value; },
      }, sqlText || 'SELECT * FROM "users" LIMIT 10'),
      h('div', { class: 'row end' },
        h('button', { onclick: runSql }, '执行'),
      ),
      h('div', { id: 'sql-out' }),
    ),
  );
  return root;
}

export function mount() {
  if (view.table) loadRows();
}

async function loadRows() {
  const out = document.getElementById('data-out');
  if (!out || !view.table || !store.connId) return;
  clear(out);
  out.append(h('div', { class: 'loading' }, '查询中…'));
  try {
    const q = `limit=${view.limit}&offset=${view.offset}`;
    const res = await get(
      `/api/connections/${store.connId}/tables/${encodeURIComponent(view.table)}/rows?${q}`);
    clear(out);
    const cols = Object.keys(res.rows[0] || { '(空表)': '' });
    const atFirst = res.offset === 0;
    const atLast = res.offset + res.rows.length >= res.total;
    out.append(
      h('div', { class: 'panel' },
        h('div', { class: 'row' },
          h('span', { class: 'muted' }, `共 ${res.total} 行 · 显示 ${res.offset + 1}–${res.offset + res.rows.length}`),
          h('span', { style: 'flex:1' }),
          h('button', {
            class: 'small', disabled: atFirst,
            onclick: () => { if (!atFirst) { view.offset = Math.max(0, view.offset - view.limit); loadRows(); } },
          }, '← 上一页'),
          h('button', {
            class: 'small', disabled: atLast,
            onclick: () => { if (!atLast) { view.offset += view.limit; loadRows(); } },
          }, '下一页 →'),
        ),
        h('div', { class: 'table-scroll' },
          table(cols, res.rows.map((r) => cols.map((c) => fmt(r[c]))),
            { monoCols: cols.map((_, i) => i) })),
      ),
    );
  } catch (e) {
    clear(out);
    out.append(msg(e.message));
  }
}

async function runSql() {
  const out = document.getElementById('sql-out');
  clear(out);
  if (!store.connId) { out.append(msg('先连接数据库。', 'warn')); return; }
  if (!/^\s*select/i.test(sqlText)) { out.append(msg('仅允许 SELECT 语句。', 'warn')); return; }
  try {
    const res = await post(`/api/connections/${store.connId}/query`, { sql: sqlText });
    const cols = Object.keys(res.rows[0] || { '(无结果)': '' });
    out.append(h('div', { class: 'table-scroll' },
      table(cols, res.rows.map((r) => cols.map((c) => fmt(r[c]))), { monoCols: cols.map((_, i) => i) })));
  } catch (e) {
    out.append(msg(e.message));
  }
}
