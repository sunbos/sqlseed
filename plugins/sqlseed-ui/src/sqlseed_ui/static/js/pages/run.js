// 预览 / 填充页：preview_table 即时反馈 + 后台 fill 任务（轮询进度）。

import { h, post, get, store, msg, clear, table, fmt } from '../api.js';
import { createDropdown } from '../dropdown.js';

let form = { table: '', count: 1000, seed: null, clear_before: false, enrich: false, batch_size: 5000 };
let yamlOverride = '';
let pollTimer = null;

const tableDd = createDropdown({
  options: [],
  placeholder: '— 选择 —',
  onChange: (v) => { form.table = v; },
});

export function render() {
  const root = h('div');
  tableDd.setOptions(
    store.tables.map((t) => ({ value: t.name, label: t.name })),
    form.table || '',
  );
  root.append(
    h('h2', {}, '预览与填充'),
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('label', {}, '表'),
        tableDd.el,
        h('label', {}, '行数'),
        h('input', { type: 'number', value: form.count,
          oninput: (e) => { form.count = +e.target.value; } }),
        h('label', {}, '种子'),
        h('input', { placeholder: '可空', value: '',
          oninput: (e) => { form.seed = e.target.value ? +e.target.value : null; } }),
      ),
      h('div', { class: 'row' },
        h('label', {}, 'YAML 覆盖（可选，列级配置）'),
        h('span', { class: 'muted' }, '从编辑器粘贴 tables 段，或留空用默认映射'),
      ),
      h('textarea', {
        id: 'yaml-override', spellcheck: 'false',
        style: 'min-height:140px',
        oninput: (e) => { yamlOverride = e.target.value; },
      }, yamlOverride),
      h('div', { class: 'row' },
        h('label', {}, h('input', { type: 'checkbox',
          onchange: (e) => { form.clear_before = e.target.checked; } }), '填充前清空'),
        h('label', {}, h('input', { type: 'checkbox',
          onchange: (e) => { form.enrich = e.target.checked; } }), '启用增强（枚举检测）'),
        h('button', { onclick: doPreview }, '预览 5 行'),
        h('button', { class: 'primary', onclick: doFill }, '开始填充'),
      ),
    ),
    h('div', { id: 'run-out' }),
  );
  return root;
}

export function mount() {
  if (!store.connId) {
    const out = document.getElementById('run-out');
    clear(out);
    out.append(msg('先在「连接」页打开一个数据库。', 'warn'));
  }
}

function columnsFromYaml() {
  if (!yamlOverride.trim()) return null;
  try {
    const doc = jsYamlLoad(yamlOverride);
    const t = (doc.tables || []).find((t) => !form.table || t.name === form.table) || doc.tables?.[0];
    if (!t) return null;
    const cols = {};
    for (const c of t.columns || []) {
      const { name, ...rest } = c;
      cols[name] = rest;
    }
    return cols;
  } catch {
    return null;
  }
}

// 极简 YAML 子集解析（仅本页覆盖输入需要；完整校验走后端 load_config）。
function jsYamlLoad(text) {
  const rows = [];
  let current = null;
  for (const line of text.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    const indented = line.startsWith(' ');
    const m = line.match(/^(\s*-?\s*)([^:]+):\s*(.*)$/);
    if (!m) continue;
    const key = m[2].trim();
    const val = m[3].trim();
    if (!indented && val === '') { current = { key, value: {} }; rows.push(current); }
    else if (!indented && val !== '') { rows.push({ key, value: val }); }
    else if (current) {
      if (key === 'name' && line.trim().startsWith('- ')) {
        current = { key: 'item', value: { name: val } };
        rows.push(current);
      } else if (line.trim().startsWith('- ')) {
        (current.value.columns = current.value.columns || []).push({ name: val });
      } else {
        current.value[key] = coerce(val);
      }
    }
  }
  const root = {};
  for (const r of rows) root[r.key] = r.value;
  return root;
}

function coerce(v) {
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (/^\d+$/.test(v)) return +v;
  if (/^'.*'$/.test(v) || /^".*"$/.test(v)) return v.slice(1, -1);
  return v;
}

async function doPreview() {
  const out = document.getElementById('run-out');
  clear(out);
  if (!form.table) { out.append(msg('选择一张表。', 'warn')); return; }
  out.append(h('div', { class: 'loading' }, '生成预览…'));
  try {
    const res = await post(`/api/connections/${store.connId}/preview`, {
      table: form.table, count: 5, columns: columnsFromYaml(), seed: form.seed,
    });
    out.replaceChildren(h('div', { class: 'panel' },
      h('h3', {}, `预览 — ${res.table}（未写库）`),
      h('div', { class: 'table-scroll' },
        table(
          Object.keys(res.rows[0] || { '(空)': '' }),
          res.rows.map((r) => Object.values(r).map((v) => fmt(v))),
          { monoCols: Object.keys(res.rows[0] || {}).map((_, i) => i) },
        )),
    ));
  } catch (e) {
    clear(out);
    out.append(msg(`预览失败：${e.message}`));
  }
}

async function doFill() {
  const out = document.getElementById('run-out');
  clear(out);
  if (!form.table) { out.append(msg('选择一张表。', 'warn')); return; }
  try {
    const res = await post(`/api/connections/${store.connId}/fill`, {
      table: form.table,
      count: form.count,
      columns: columnsFromYaml(),
      seed: form.seed,
      clear_before: form.clear_before,
      enrich: form.enrich,
      batch_size: form.batch_size,
    });
    clear(out);
    const barWrap = h('div', { class: 'progress' }, h('div', { class: 'bar', id: 'fill-bar' }));
    out.append(h('div', { class: 'panel' },
      h('h3', {}, `填充任务 ${res.job_id} — ${res.table} × ${res.count}`),
      barWrap,
      h('div', { id: 'fill-status', class: 'muted', style: 'margin-top:8px' }, '已提交…'),
    ));
    pollTimer = setInterval(() => pollJob(res.job_id), 800);
  } catch (e) {
    out.append(msg(`提交失败：${e.message}`));
  }
}

async function pollJob(jobId) {
  try {
    const job = await get(`/api/jobs/${jobId}`);
    const statusEl = document.getElementById('fill-status');
    const bar = document.getElementById('fill-bar');
    if (!statusEl || !bar) { clearInterval(pollTimer); return; }
    if (job.status === 'running') {
      if (job.live_rows !== null && job.live_rows !== undefined) {
        const done = job.live_rows - (job.rows_before || 0);
        const pct = form.count ? Math.min(100, (done / form.count) * 100) : 0;
        bar.style.width = `${pct.toFixed(1)}%`;
        statusEl.textContent = `进行中… 已插入约 ${done} / ${form.count} 行`;
      } else {
        statusEl.textContent = '进行中…';
      }
      return;
    }
    clearInterval(pollTimer);
    bar.style.width = '100%';
    if (job.status === 'error') {
      statusEl.replaceWith(msg(`填充失败：${job.error}`));
    } else {
      const r = job.result || {};
      statusEl.textContent =
        `完成：插入 ${r.rows_inserted ?? job.rows_inserted} 行，表内共 ${r.row_count_after ?? '?'} 行` +
        (r.errors ? `（错误: ${JSON.stringify(r.errors)}）` : '');
      statusEl.className = 'msg ok';
    }
  } catch {
    clearInterval(pollTimer);
  }
}
