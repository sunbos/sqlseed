// 主工作台（参考工具 主窗口式三栏）：
//   左：连接/表树（含分组标识）
//   中：数据网格（分页 + SQL 控制台折叠）
//   右：元数据面板（行数/列数/外键/索引/映射摘要）

import { h, get, clear, msg, table, fmt, store, setConnBadge, rememberConnId } from '../api.js';
let current = {
  connId: null,
  table: null
};
let selectionVersion = 0;
let treeVersion = 0;
export function render() {
  selectionVersion++;
  treeVersion++;
  const root = h('div', {
    class: 'browse'
  });
  root.append(h('div', {
    class: 'browse-left',
    id: 'browse-left'
  }, h('div', {
    class: 'loading'
  }, '加载连接…')), h('div', {
    class: 'browse-center',
    id: 'browse-center'
  }, h('div', {
    class: 'muted',
    style: 'padding:24px'
  }, '在左侧选择一张表查看数据。')), h('div', {
    class: 'browse-right',
    id: 'browse-right'
  }, h('div', {
    class: 'muted',
    style: 'padding:24px'
  }, '表元数据。')));
  return root;
}
export async function mount() {
  await loadLeft();
}
async function loadLeft() {
  const left = document.getElementById('browse-left');
  if (!left) return;
  const version = ++treeVersion;
  const isCurrent = () => version === treeVersion && left.isConnected;
  let conns;
  try {
    conns = await get('/api/connections');
  } catch (error) {
    if (isCurrent()) {
      clear(left);
      left.append(msg(error.message));
    }
    return;
  }
  if (!isCurrent()) return;
  clear(left);
  if (!conns.connections.length) {
    left.append(msg('暂无连接。先在「数据库连接」页打开数据库。', 'warn'));
    return;
  }
  for (const c of conns.connections) {
    let group;
    if (c.group_size > 1) {
      group = h('span', {
        class: 'pill'
      }, c.group_index === 1 ? `主 ${c.group_index}/${c.group_size}` : `并 ${c.group_index}/${c.group_size}`);
    } else {
      group = null;
    }
    const connNode = h('div', {
      class: 'tree-row table-row'
    }, h('span', {
      class: 'tree-icon'
    }, '🗄'), h('span', {
      class: 'tree-name'
    }, (c.target || '').split('/').pop()), group);
    const tablesNode = h('div', {}, h('div', {
      class: 'loading'
    }, '加载表…'));
    left.append(connNode, tablesNode);
    c.tablesNode = tablesNode;
  }
  await Promise.all(conns.connections.map(async c => {
    try {
      const detail = await get(`/api/connections/${c.conn_id}/tables`);
      if (!isCurrent()) return;
      clear(c.tablesNode);
      for (const t of detail.tables) {
        c.tablesNode.append(h('div', {
          class: `tree-row col-row${current.connId === c.conn_id && current.table === t.name ? ' selected' : ''}`,
          onclick: () => selectTable(c.conn_id, t.name)
        }, h('span', {
          class: 'tree-arrow'
        }, ''), h('span', {
          class: 'tree-icon col-icon'
        }, '▦'), h('span', {
          class: 'tree-name'
        }, t.name), h('span', {
          class: 'muted tree-count'
        }, String(t.row_count))));
      }
    } catch (error) {
      if (isCurrent()) {
        clear(c.tablesNode);
        c.tablesNode.append(msg(error.message));
      }
    }
  }));
}
async function selectTable(connId, tableName) {
  const center = document.getElementById('browse-center');
  const right = document.getElementById('browse-right');
  if (!center || !right) return;
  const version = ++selectionVersion;
  const isCurrent = () => version === selectionVersion && center.isConnected && right.isConnected;
  clear(center);
  clear(right);
  center.append(h('div', {
    class: 'loading'
  }, '加载数据…'));
  try {
    const [detail, schema, mapping, rows] = await Promise.all([get(`/api/connections/${connId}/tables`), get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/schema`), get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/mapping`), get(`/api/connections/${connId}/tables/${encodeURIComponent(tableName)}/rows?limit=50&offset=0`)]);
    if (!isCurrent()) return;
    current = {
      connId,
      table: tableName
    };
    store.connId = connId;
    store.target = detail.target;
    store.tables = detail.tables;
    rememberConnId(connId);
    setConnBadge();
    renderCenter(center, connId, tableName, rows);
    renderRight(right, tableName, schema, mapping);
    await loadLeft();
  } catch (error) {
    if (isCurrent()) {
      clear(center);
      center.append(msg(error.message));
    }
  }
}
function renderCenter(center, connId, tableName, rowsRes) {
  clear(center);
  const cols = Object.keys(rowsRes.rows[0] || {
    '(空表)': ''
  });
  center.append(h('div', {
    class: 'row'
  }, h('div', {
    class: 'genform-title'
  }, tableName), h('span', {
    class: 'muted'
  }, `共 ${rowsRes.total} 行`), h('span', {
    style: 'flex:1'
  }), h('button', {
    class: 'small',
    onclick: () => selectTable(connId, tableName)
  }, '刷新')), h('div', {
    class: 'table-scroll',
    id: 'grid'
  }, table(cols, rowsRes.rows.map(r => cols.map(c => fmt(r[c]))), {
    monoCols: cols.map((_, i) => i)
  })));
}
function renderRight(right, tableName, schema, mapping) {
  clear(right);
  right.append(h('div', {
    class: 'meta-head'
  }, h('div', {
    class: 'meta-icon'
  }, '▦'), h('div', {}, h('div', {
    class: 'genform-title'
  }, tableName), h('div', {
    class: 'muted'
  }, '表'))), h('div', {
    class: 'meta-kv'
  }, h('div', {}, h('div', {
    class: 'muted'
  }, '行数'), h('div', {
    class: 'stat'
  }, schema.row_count)), h('div', {}, h('div', {
    class: 'muted'
  }, '列数'), h('div', {
    class: 'stat'
  }, schema.columns.length)), h('div', {}, h('div', {
    class: 'muted'
  }, '外键'), h('div', {
    class: 'stat'
  }, (schema.foreign_keys || []).length))), h('h3', {
    class: 'section-title'
  }, '列映射'), ...Object.entries(mapping.mapping).map(([col, spec]) => h('div', {
    class: 'meta-map-row'
  }, h('span', {
    class: 'mono'
  }, col), h('span', {
    class: `pill ${spec.generator_name === 'skip' ? 'warn' : 'gen'}`
  }, spec.generator_name))), ...((schema.foreign_keys || []).length ? [h('h3', {
    class: 'section-title'
  }, '外键')] : []), ...(schema.foreign_keys || []).map(fk => h('div', {
    class: 'meta-map-row'
  }, h('span', {
    class: 'mono'
  }, fk.column), h('span', {
    class: 'muted'
  }, `→ ${fk.ref_table}.${fk.ref_column}`))));
}
