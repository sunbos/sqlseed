// 可勾选数据库对象树（Navicat Step2 左栏）：表→列两级，
// 列节点带语义标注（外键/序列/生成器语义），点击选中列驱动右侧属性面板。

import { h, clear } from './api.js';
import { colAnnotation } from './labels.js';

/**
 * @param {object} opts
 * @param {Array} opts.tables - [{name, columns: ColumnInfo[], specs, fks}]
 * @param {(table: string, col: string) => void} opts.onSelectColumn
 * @param {(sel: Map<string, Set<string>>) => void} opts.onChange
 */
export function createTree({ tables, onSelectColumn, onChange }) {
  const expanded = new Set(tables.map((t) => t.name)); // 默认全展开
  const checked = new Map(tables.map((t) => [t.name, new Set(t.columns.map((c) => c.name))]));
  const selected = { table: null, col: null };
  const el = h('div', { class: 'tree' });

  function emit() {
    if (onChange) onChange(checked);
  }

  function render() {
    clear(el);
    for (const t of tables) {
      const tChecked = checked.get(t.name);
      const allChecked = tChecked.size === t.columns.length;
      const isOpen = expanded.has(t.name);
      const tRow = h('div', {
        class: 'tree-row table-row',
        onclick: () => {
          if (isOpen) expanded.delete(t.name); else expanded.add(t.name);
          render();
        },
      },
        h('span', { class: 'tree-arrow' }, isOpen ? '▾' : '▸'),
        h('input', {
          type: 'checkbox', checked: allChecked,
          onclick: (e) => {
            e.stopPropagation();
            const next = e.target.checked ? new Set(t.columns.map((c) => c.name)) : new Set();
            checked.set(t.name, next);
            emit(); render();
          },
        }),
        h('span', { class: 'tree-icon' }, '▦'),
        h('span', { class: 'tree-name' }, t.name),
        h('span', { class: 'muted tree-count' }, `${tChecked.size}/${t.columns.length}`),
      );
      el.append(tRow);
      if (!isOpen) continue;
      for (const col of t.columns) {
        const spec = t.specs?.[col.name];
        const anno = colAnnotation(col, spec, t.fks);
        const isSel = selected.table === t.name && selected.col === col.name;
        el.append(h('div', {
          class: `tree-row col-row${isSel ? ' selected' : ''}`,
          onclick: (e) => {
            e.stopPropagation();
            selected.table = t.name;
            selected.col = col.name;
            render();
            if (onSelectColumn) onSelectColumn(t.name, col.name);
          },
        },
          h('span', { class: 'tree-arrow' }, ''),
          h('input', {
            type: 'checkbox', checked: tChecked.has(col.name),
            onclick: (e) => {
              e.stopPropagation();
              if (e.target.checked) tChecked.add(col.name); else tChecked.delete(col.name);
              emit(); render();
            },
          }),
          h('span', { class: 'tree-icon col-icon' }, '▤'),
          h('span', { class: 'tree-name' }, col.name),
          anno ? h('span', { class: 'muted tree-anno' }, `(${anno})`) : null,
        ));
      }
    }
  }

  render();
  return {
    el,
    getSelection: () => checked,
    getSelectedColumn: () => selected,
    refresh: render,
  };
}
