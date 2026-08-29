// Schema / 映射页：列结构 + 9 级映射链输出的对照视图（核心验收页）。

import { h, get, store, table, msg, clear, fmt } from '../api.js';
import { createDropdown } from '../dropdown.js';

let selected = null;
let cache = { schema: null, mapping: null };

const tableDd = createDropdown({
  options: [],
  placeholder: '— 选择 —',
  onChange: (v) => load(v),
});

export function render() {
  const root = h('div');
  tableDd.setOptions(
    store.tables.map((t) => ({ value: t.name, label: `${t.name} (${t.row_count} 行)` })),
    selected || '',
  );
  root.append(
    h('h2', {}, 'Schema 与列映射'),
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('label', {}, '选择表'),
        tableDd.el,
        h('button', { onclick: () => load(selected) }, '刷新'),
      ),
    ),
    h('div', { id: 'schema-out' }, h('div', { class: 'loading' }, '选择一张表后展示列结构、约束与映射结果。')),
  );
  return root;
}

export function mount() {
  if (!store.connId) {
    const out = document.getElementById('schema-out');
    clear(out);
    out.append(msg('先在「连接」页打开一个数据库。', 'warn'));
  } else if (selected) {
    load(selected);
  }
}

async function load(table) {
  selected = table;
  const out = document.getElementById('schema-out');
  if (!table || !store.connId) return;
  clear(out);
  out.append(h('div', { class: 'loading' }, '加载中…'));
  try {
    const [schema, mapping] = await Promise.all([
      get(`/api/connections/${store.connId}/tables/${encodeURIComponent(table)}/schema`),
      get(`/api/connections/${store.connId}/tables/${encodeURIComponent(table)}/mapping`),
    ]);
    cache = { schema, mapping };
    clear(out);
    out.append(renderSchema(schema), renderMapping(mapping));
  } catch (e) {
    clear(out);
    out.append(msg(`加载失败：${e.message}`));
  }
}

function renderSchema(schema) {
  const skip = new Set(schema.skippable || []);
  return h('div', { class: 'panel' },
    h('h3', {}, `列结构 — ${schema.table}（现有 ${schema.row_count} 行）`),
    h('div', { class: 'table-scroll' },
      table(
        ['列名', '类型', '可空', 'PK', '默认值', '跳过'],
        schema.columns.map((c) => [
          c.name,
          c.type,
          c.nullable ? 'NULL' : 'NOT NULL',
          c.is_primary_key ? 'PK' : '',
          fmt(c.default),
          skip.has(c.name) ? h('span', { class: 'pill warn' }, 'skip') : '',
        ]),
        { monoCols: [0, 1] },
      )),
    (schema.foreign_keys || []).length ? h('h3', {}, '外键') : null,
    (schema.foreign_keys || []).length ?
      table(
        ['列', '引用表', '引用列'],
        // ForeignKeyInfo 字段是单数：column / ref_table / ref_column
        schema.foreign_keys.map((fk) => [fmt(fk.column ?? fk.columns), fmt(fk.ref_table), fmt(fk.ref_column ?? fk.ref_columns)]),
      ) : null,
  );
}

function renderMapping(mapping) {
  const rows = Object.entries(mapping.mapping).map(([col, spec]) => [
    col,
    spec.generator_name === 'skip'
      ? h('span', { class: 'pill warn' }, 'skip')
      : h('span', { class: 'pill gen' }, spec.generator_name),
    spec.null_ratio ? `${(spec.null_ratio * 100).toFixed(0)}%` : '—',
    spec.params && Object.keys(spec.params).length
      ? h('code', {}, JSON.stringify(spec.params))
      : '—',
    spec.provider || '—',
  ]);
  return h('div', { class: 'panel' },
    h('h3', {}, '列映射（9 级策略链输出 → GeneratorSpec）'),
    h('div', { class: 'table-scroll' }, table(
      ['列名', '生成器', 'null_ratio', '参数', 'Provider'],
      rows,
      { monoCols: [0] },
    )),
    h('div', { class: 'row', style: 'margin-top:12px' },
      h('button', {
        onclick: async () => {
          const res = await get(
            `/api/connections/${store.connId}/tables/${encodeURIComponent(mapping.table)}/yaml-template`);
          const w = window.open('', '_blank');
          w.document.write(`<pre>${res.yaml.replace(/</g, '&lt;')}</pre>`);
        },
      }, '生成 YAML 模板'),
      h('span', { class: 'muted' }, '在新窗口打开基于当前映射的可用配置骨架'),
    ),
  );
}
