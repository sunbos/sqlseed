// 主工作台（Navicat 主窗口式三栏）：
//   左：连接/表树（含分组标识）
//   中：数据网格（分页 + SQL 控制台折叠）
//   右：元数据面板（行数/列数/外键/索引/映射摘要）

import { h, get, post, clear, msg, table, fmt, store, setConnBadge } from '../api.js';

let current = { table: null };

export function render() {
  const root = h('div', { class: 'browse' });
  root.append(
    h('div', { class: 'browse-left', id: 'browse-left' }, h('div', { class: 'loading' }, '加载连接…')),
    h('div', { class: 'browse-center', id: 'browse-center' },
      h('div', { class: 'muted', style: 'padding:24px' }, '在左侧选择一张表查看数据。')),
    h('div', { class: 'browse-right', id: 'browse-right' },
      h('div', { class: 'muted', style: 'padding:24px' }, '表元数据。')),
  );
  return root;
}

export function mount() {
  loadLeft();
}

async function loadLeft() {
  const left = document.getElementById('browse-left');
  clear(left);
  const conns = await get('/api/connections');
  if (!conns.connections.length) {
    left.append(msg('暂无连接。先在「连接」页打开数据库。', 'warn'));
    return;
  }
  for (const c of conns.connections) {
    const group = c.group_size > 1
      ? h('span', { class: 'pill' }, c.group_index === 1 ? `主 ${c.group_index}/${c.group_size}` : `并 ${c.group_index}/${c.group_size}`)
      : null;
    const connNode = h('div', { class: 'tree-row table-row' },
      h('span', { class: 'tree-icon' }, '🗄'),
      h('span', { class: 'tree-name' }, (c.target || '').split('/').pop()),
      group,
    );
    left.append(connNode);
    for (const t of store.tables) {
      left.append(h('div', {
        class: `tree-row col-row${current.table === t.name ? ' selected' : ''}`,
        onclick: () => selectTable(c.conn_id, t.name),
      },
        h('span', { class: 'tree-arrow' }, ''),
        h('span', { class: 'tree-icon col-icon' }, '▦'),
        h('span', { class: 'tree-name' }, t.name),
        h('span', { class: 'muted tree-count' }, String(t.row_count)),
      ));
    }
  }
}

async function selectTable(connId, tableName) {
  current = { table: tableName };
  store.connId = connId;
  setConnBadge();
  loadLeft();
  const center = document.getElementById('browse-center');
  const right = document.getElementById('browse-right');
  clear(center); clear(right);
  center.append(h('div', { class: 'loading' }, '加载数据…'));

  const [schema, mapping, rows] = await Promise.all([
    get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/schema`),
    get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/mapping`),
    get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/rows?limit=50&offset=0`),
  ]);

  renderCenter(center, tableName, rows);
  renderRight(right, tableName, schema, mapping);
}

function renderCenter(center, tableName, rowsRes) {
  clear(center);
  const cols = Object.keys(rowsRes.rows[0] || { '(空表)': '' });
  center.append(
    h('div', { class: 'row' },
      h('div', { class: 'genform-title' }, tableName),
      h('span', { class: 'muted' }, `共 ${rowsRes.total} 行`),
      h('span', { style: 'flex:1' }),
      h('button', { class: 'small', onclick: () => refresh(tableName) }, '刷新'),
    ),
    h('div', { class: 'table-scroll', id: 'grid' },
      table(cols, rowsRes.rows.map((r) => cols.map((c) => fmt(r[c]))), { monoCols: cols.map((_, i) => i) })),
  );
}

async function refresh(tableName) {
  const center = document.getElementById('browse-center');
  const rows = await get(`/api/connections/${store.connId}/tables/${encodeURIComponent(tableName)}/rows?limit=50&offset=0`);
  renderCenter(center, tableName, rows);
}

function renderRight(right, tableName, schema, mapping) {
  clear(right);
  right.append(
    h('div', { class: 'meta-head' },
      h('div', { class: 'meta-icon' }, '▦'),
      h('div', {},
        h('div', { class: 'genform-title' }, tableName),
        h('div', { class: 'muted' }, '表'),
      ),
    ),
    h('div', { class: 'meta-kv' },
      h('div', {}, h('div', { class: 'muted' }, '行数'), h('div', { class: 'stat' }, schema.row_count)),
      h('div', {}, h('div', { class: 'muted' }, '列数'), h('div', { class: 'stat' }, schema.columns.length)),
      h('div', {}, h('div', { class: 'muted' }, '外键'), h('div', { class: 'stat' }, (schema.foreign_keys || []).length)),
    ),
    h('h3', { class: 'section-title' }, '列映射'),
    ...Object.entries(mapping.mapping).map(([col, spec]) =>
      h('div', { class: 'meta-map-row' },
        h('span', { class: 'mono' }, col),
        h('span', { class: `pill ${spec.generator_name === 'skip' ? 'warn' : 'gen'}` }, spec.generator_name),
      )),
    (schema.foreign_keys || []).length ? h('h3', { class: 'section-title' }, '外键') : null,
    ...(schema.foreign_keys || []).map((fk) =>
      h('div', { class: 'meta-map-row' },
        h('span', { class: 'mono' }, fk.column),
        h('span', { class: 'muted' }, `→ ${fk.ref_table}.${fk.ref_column}`),
      )),
  );
}
