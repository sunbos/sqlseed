// 列属性面板（Navicat Step2 右栏）：生成器下拉 + 动态参数表单 +
// 单列实时预览 + NULL 百分比 / 唯一 / 重置。

import { h, clear, post, msg } from './api.js';
import { createDropdown } from './dropdown.js';
import { genLabel, paramLabel, groupGenerators } from './labels.js';

/**
 * @param {object} opts
 * @param {string} opts.connId
 * @param {object} opts.meta - /api/meta/generators 响应（names + params）
 * @param {(table: string, col: string, cfg: object|null) => void} opts.onChange
 *   cfg 为该列的 ColumnConfig 形状（generator/params/null_ratio/constraints），
 *   null 表示跟随零配置推断。
 */
export function createGenForm({ connId, meta, onChange }) {
  const el = h('div', { class: 'genform' });
  let current = null; // {table, col, colInfo, inferred}
  let form = {};      // {generator, params: {}, null_ratio, unique}
  let previewBox = null; // 当前预览容器（render() 时更新）
  let previewTimer = null;

  // 防抖自动预览：生成器/参数/NULL/唯一任一变化后 400ms 刷新例值。
  // 之前只在选中列和手动「刷新」时预览，改参数后一直显示旧值（实测发现）。
  function schedulePreview() {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      previewTimer = null;
      if (current && previewBox && previewBox.isConnected) doPreview(previewBox);
    }, 400);
  }

  function cleanParams() {
    const out = {};
    for (const [k, v] of Object.entries(form.params)) {
      if (v === undefined || v === null || v === '') continue;
      out[k] = v;
    }
    return out;
  }

  function emit() {
    if (!current || !onChange) return;
    const cfg = {
      generator: form.generator,
      params: cleanParams(),
    };
    // form.null_ratio 是 0–100 百分比；核心 ColumnConfig.null_ratio 是 0–1
    // 小数（le=1.0）——发送前必须除以 100，否则 preview/fill 直接 422。
    if (form.null_ratio > 0) cfg.null_ratio = form.null_ratio / 100;
    if (form.unique) cfg.constraints = { unique: true };
    onChange(current.table, current.col, cfg);
  }

  function render() {
    clear(el);
    if (!current) {
      el.append(h('div', { class: 'muted', style: 'padding:24px' }, '在左侧树中选择一列以配置生成器。'));
      return;
    }
    const { col, colInfo, inferred } = current;
    el.append(
      h('div', { class: 'genform-head' },
        h('div', { class: 'genform-title' }, col),
        h('div', { class: 'muted' }, `${colInfo.type}${colInfo.nullable ? '' : ' NOT NULL'}${colInfo.is_primary_key ? ' · PK' : ''}`),
      ),
    );

    // 生成器下拉：Navicat 式分类分组（通用/个人/商业/位置/网络与文件）
    const genOpts = [];
    for (const grp of groupGenerators(meta.names)) {
      for (const name of grp.names) {
        genOpts.push({ value: name, label: `${genLabel(name)}（${name}）`, group: grp.title });
      }
    }
    const genSel = createDropdown({
      value: form.generator,
      options: genOpts,
      width: '260px',
      onChange: (v) => { form.generator = v; form.params = {}; renderParams(); emit(); schedulePreview(); },
    });
    el.append(formRow('生成器', genSel.el));

    // 外键提示
    if (inferred?.generator_name === 'foreign_key' || inferred?.generator_name === 'foreign_key_or_integer') {
      el.append(h('div', { class: 'msg warn', style: 'margin:8px 0' },
        '该列是外键：生成值将从父表采样（策略 random），属性由系统管理。'));
    }

    renderParams();

    // NULL / 唯一
    el.append(
      h('div', { class: 'genform-section' },
        h('label', { class: 'genform-check' },
          h('input', {
            type: 'checkbox', checked: form.null_ratio > 0,
            onchange: (e) => { form.null_ratio = e.target.checked ? 5 : 0; renderNull(); emit(); schedulePreview(); },
          }), '包含 NULL 值'),
        formRow('百分比', h('input', {
          type: 'number', class: 'num-input', value: form.null_ratio || 5, min: 0, max: 100,
          oninput: (e) => { form.null_ratio = +e.target.value; emit(); schedulePreview(); },
        })),
        h('label', { class: 'genform-check' },
          h('input', {
            type: 'checkbox', checked: !!form.unique,
            onchange: (e) => { form.unique = e.target.checked; emit(); schedulePreview(); },
          }), '设置唯一'),
      ),
    );

    // 预览 + 重置
    const previewOut = h('div', { class: 'genform-preview' });
    previewBox = previewOut;
    el.append(
      h('div', { class: 'genform-section' },
        formRow('预览', h('div', {}, previewOut)),
        h('div', { class: 'row' },
          h('button', { class: 'small', onclick: () => doPreview(previewOut) }, '刷新'),
          h('button', { class: 'small', onclick: reset }, '重置属性'),
        ),
      ),
    );
    doPreview(previewOut);
  }

  function renderNull() { /* 百分比输入框在 section 里直接渲染，无需单独刷新 */ }

  function renderParams() {
    const holder = el.querySelector('.genform-params');
    if (holder) holder.remove();
    const wrap = h('div', { class: 'genform-params' });
    const paramNames = meta.params?.[form.generator] || [];
    for (const p of paramNames) {
      wrap.append(formRow(paramLabel(p), paramInput(p)));
    }
    // 插在 NULL section 之前
    const section = el.querySelector('.genform-section');
    el.insertBefore(wrap, section);
  }

  function paramInput(name) {
    const val = form.params[name] ?? '';
    const commit = (v) => { form.params[name] = v; emit(); schedulePreview(); };
    if (name === 'choices' || name === 'weighted_choices') {
      // Navicat 式：每行一个值；加权枚举支持每行「值:权重」。
      let text;
      if (Array.isArray(val)) {
        text = val.join('\n');
      } else if (val && typeof val === 'object') {
        text = Object.entries(val).map(([k, w]) => `${k}:${w}`).join('\n');
      } else {
        text = typeof val === 'string' ? val : '';
      }
      return h('textarea', {
        class: 'grow', rows: '4', spellcheck: 'false',
        placeholder: name === 'choices' ? '每行一个值，如:\nengineer\nmanager' : '每行一个「值:权重」，如:\nactive:80\nsuspended:15',
        oninput: (e) => {
          const lines = e.target.value.split('\n').map((s) => s.trim()).filter(Boolean);
          if (name === 'choices') {
            commit(lines);
          } else {
            const obj = {};
            for (const line of lines) {
              const idx = line.lastIndexOf(':');
              if (idx > 0) obj[line.slice(0, idx)] = Number(line.slice(idx + 1)) || 0;
              else obj[line] = 1;
            }
            commit(obj);
          }
        },
      });
    }
    if (/min|max|length|value|count/.test(name)) {
      return h('input', {
        type: 'number', class: 'num-input', value: val,
        oninput: (e) => commit(e.target.value === '' ? undefined : +e.target.value),
      });
    }
    return h('input', {
      class: 'grow', value: val, placeholder: name === 'regex' ? '[0-9]{11}' : '',
      oninput: (e) => commit(e.target.value),
    });
  }

  function formRow(labelText, control) {
    return h('div', { class: 'genform-row' },
      h('label', { class: 'genform-label' }, `${labelText}:`),
      control,
    );
  }

  async function doPreview(out) {
    if (!current) return;
    clear(out);
    out.append(h('span', { class: 'muted' }, '…'));
    try {
      const cfg = { generator: form.generator, params: cleanParams() };
      // 预览必须带 NULL/唯一，否则勾选后预览永远显示不出空值（实测发现）。
      if (form.null_ratio > 0) cfg.null_ratio = form.null_ratio / 100;
      if (form.unique) cfg.constraints = { unique: true };
      const res = await post(`/api/connections/${connId}/preview`, {
        table: current.table, count: 3, columns: { [current.col]: cfg },
      });
      clear(out);
      const vals = res.rows.map((r) => r[current.col]);
      out.append(h('span', { class: 'genform-preview-val' }, vals.map(String).join('、') || '（空）'));
    } catch (e) {
      clear(out);
      out.append(msg(`预览失败：${e.message}`));
    }
  }

  function reset() {
    if (!current) return;
    form = fromInferred(current.inferred);
    render();
    emit();
  }

  function fromInferred(spec) {
    if (!spec || spec.generator_name === 'skip' || spec.generator_name === 'foreign_key'
      || spec.generator_name === 'foreign_key_or_integer' || spec.generator_name === '__enrich__') {
      return { generator: 'string', params: {}, null_ratio: 0, unique: false };
    }
    return {
      generator: spec.generator_name,
      params: { ...(spec.params || {}) },
      // 核心返回 0–1 小数，UI 展示 0–100 百分比
      null_ratio: Math.round((spec.null_ratio || 0) * 100),
      unique: false,
    };
  }

  return {
    el,
    /** 选中一列：colInfo 为 ColumnInfo，inferred 为零配置推断的 GeneratorSpec */
    setColumn(table, col, colInfo, inferred) {
      current = { table, col, colInfo, inferred };
      form = fromInferred(inferred);
      render();
    },
  };
}
