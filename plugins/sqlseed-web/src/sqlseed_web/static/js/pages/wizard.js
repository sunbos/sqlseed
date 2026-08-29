// 数据生成向导（Navicat 式三步工作台）：
//   Step1 目标：连接选择 + 信息面板 + 流程图
//   Step2 对象：左树（勾选表/列）+ 右列属性面板（生成器/参数/预览/NULL/唯一）
//   Step3 生成：表生成顺序 + 逐表预览 + 按序填充
// 底部持久栏：保存配置文件 / 加载配置文件 / 表生成顺序 / 上一步 / 下一步

import { h, get, post, clear, msg, table, fmt } from '../api.js';
import { store } from '../api.js';
import { createTree } from '../tree.js';
import { createGenForm } from '../genform.js';

let step = 1;
let meta = null;
let tablesMeta = []; // [{name, columns, specs, fks, rowCount}]
let connInfo = null;
let tree = null;
let genform = null;
let cfg = new Map(); // table -> Map<col, ColumnConfig>
let aiAvailable = null; // /api/meta/ai 探测结果（决定「AI 一键生成配置」可用性）

export function render() {
  const root = h('div', { class: 'wizard' });
  root.append(renderHeader());
  const body = h('div', { class: 'wizard-body', id: 'wizard-body' });
  root.append(body);
  root.append(renderFooter());
  renderStep(body, root);
  return root;
}

export function mount() {
  if (!store.connId) {
    const body = document.getElementById('wizard-body');
    clear(body);
    body.append(msg('先在「连接」页打开一个数据库，再进入数据生成向导。', 'warn'));
    return;
  }
  loadMeta().then(() => renderStep());
}

function renderHeader() {
  return h('div', { class: 'wizard-header' },
    h('span', { class: 'wizard-db-icon' }, '🗄'),
    h('div', {},
      h('div', { class: 'wizard-db-name' }, store.target || '未连接'),
      h('div', { class: 'muted' }, `步骤 ${step} / 3 — ${['目标', '对象', '生成'][step - 1]}`),
    ),
  );
}

async function loadMeta() {
  if (!store.connId) return;
  meta = await get('/api/meta/generators');
  try {
    aiAvailable = await get('/api/meta/ai');
  } catch {
    aiAvailable = { available: false, reason: '无法探测 AI 插件状态' };
  }
  await loadTablesMeta();
}

async function loadTablesMeta() {
  const conns = await get('/api/connections');
  connInfo = conns.connections.find((c) => c.conn_id === store.connId) || null;
  const names = store.tables.map((t) => t.name);
  tablesMeta = [];
  for (const t of store.tables) {
    const [schema, mapping] = await Promise.all([
      get(`/api/connections/${store.connId}/tables/${encodeURIComponent(t.name)}/schema`),
      get(`/api/connections/${store.connId}/tables/${encodeURIComponent(t.name)}/mapping`),
    ]);
    tablesMeta.push({
      name: t.name,
      columns: schema.columns,
      specs: mapping.mapping,
      fks: new Set((schema.foreign_keys || []).map((fk) => fk.column)),
      rowCount: schema.row_count,
    });
  }
  return names;
}

function renderStep(bodyEl = null, rootEl = null) {
  const body = bodyEl || document.getElementById('wizard-body');
  if (!body) return;
  clear(body);
  if (step === 1) body.append(renderStep1());
  else if (step === 2) body.append(renderStep2());
  else body.append(renderStep3());
  updateFooter(rootEl);
}

// ---- Step 1：目标 -----------------------------------------------------------

function renderStep1() {
  const info = connInfo;
  return h('div', { class: 'step1' },
    h('div', { class: 'step1-left' },
      h('h3', { class: 'section-title' }, '目标'),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, '连接:'),
        h('span', { class: 'pill ok' }, info ? `${info.target}` : '未连接')),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, 'Locale:'),
        h('span', { class: 'pill' }, info?.locale || '—')),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, 'Provider:'),
        h('span', { class: 'pill' }, info?.provider || '—')),
      h('h3', { class: 'section-title', style: 'margin-top:24px' }, '信息'),
      h('div', { class: 'muted', style: 'white-space:pre-line' },
        `数据库类型: SQLite\n文件: ${store.target || '—'}\n表: ${store.tables.length} 张\n总行数: ${store.tables.reduce((n, t) => n + t.row_count, 0)}`),
    ),
    h('div', { class: 'step1-right' }, flowDiagram()),
  );
}

function flowDiagram() {
  return h('div', { class: 'flow' },
    h('div', { class: 'flow-node' }, '▦ 选择要生成数据的表和字段'),
    h('div', { class: 'flow-arrow' }, '↓'),
    h('div', { class: 'flow-node' }, '⚙ 设置属性并创建测试数据'),
    h('div', { class: 'flow-arrow' }, '↓'),
    h('div', { class: 'flow-node' }, '🗄 写入数据库'),
  );
}

// ---- Step 2：对象 -----------------------------------------------------------

function renderStep2() {
  const wrap = h('div', { class: 'step2' });
  const left = h('div', { class: 'step2-left' });
  const right = h('div', { class: 'step2-right' });
  wrap.append(left, right);

  tree = createTree({
    tables: tablesMeta,
    onSelectColumn: (t, c) => {
      const tm = tablesMeta.find((x) => x.name === t);
      const colInfo = tm.columns.find((x) => x.name === c);
      // AI/加载配置优先于零配置推断。cfg 里 null_ratio 是 0–1（后端形状），
      // genform.fromInferred 内部会 *100 转成展示百分比，这里原样透传。
      const aiCfg = cfg.get(t)?.get(c);
      const spec = aiCfg
        ? { generator_name: aiCfg.generator, params: aiCfg.params, null_ratio: aiCfg.null_ratio || 0 }
        : tm.specs[c];
      genform.setColumn(t, c, colInfo, spec);
    },
    onChange: (checked) => {
      // 取消勾选的列从 cfg 移除
      for (const tm of tablesMeta) {
        const colSet = checked.get(tm.name) || new Set();
        const cfgMap = cfg.get(tm.name);
        if (!cfgMap) continue;
        for (const col of [...cfgMap.keys()]) {
          if (!colSet.has(col)) cfgMap.delete(col);
        }
      }
    },
  });
  genform = createGenForm({
    connId: store.connId,
    meta,
    onChange: (t, c, colCfg) => {
      if (!cfg.has(t)) cfg.set(t, new Map());
      cfg.get(t).set(c, colCfg);
    },
  });
  left.append(
    h('h3', { class: 'section-title' }, '数据库对象'),
    renderAiGenBar(),
    tree.el,
  );
  right.append(genform.el);
  return wrap;
}

// 「AI 一键生成配置」：调用 L5 全流程自愈产出 YAML，再映射回本向导的
// 树勾选 + 列级配置，用户只需微调。AI 未安装/未配置时给出引导而非静默。
function renderAiGenBar() {
  const bar = h('div', { class: 'row', style: 'margin-bottom:8px' });
  if (!aiAvailable || !aiAvailable.available) {
    bar.append(h('span', { class: 'muted', style: 'font-size:12px' },
      `AI 一键生成配置不可用：${aiAvailable?.reason || 'sqlseed-ai 未安装'}`));
    return bar;
  }
  bar.append(
    h('button', { class: 'primary small', id: 'btn-ai-gen', onclick: aiGenerateConfig }, 'AI 一键生成配置'),
    h('span', { class: 'muted', id: 'ai-gen-status', style: 'font-size:12px' },
      '由 LLM 分析 schema 生成一版配置，回填到下方供你微调'),
  );
  return bar;
}

async function aiGenerateConfig() {
  const btn = document.getElementById('btn-ai-gen');
  const status = document.getElementById('ai-gen-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = '正在调用 LLM 生成配置（可能需要数十秒）…';
  try {
    const res = await post(`/api/connections/${store.connId}/heal/auto`, { budget_seconds: 300 });
    const job = await pollJob(res.job_id);
    if (job.status !== 'done' || !job.result?.yaml) {
      throw new Error(job.error || '生成失败');
    }
    await applyAiYaml(job.result.yaml);
    if (status) status.textContent = '已回填 AI 生成的配置，可在右侧逐列微调。';
  } catch (e) {
    if (status) status.textContent = `生成失败：${e.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 把 AI 产出的 YAML 解析为结构化 config，映射回树勾选与列级配置。
// 只回填当前连接里真实存在的表/列，忽略 schema 之外的噪声。
async function applyAiYaml(yamlText) {
  const parsed = await post('/api/config/parse', { yaml: yamlText });
  if (!parsed.valid) throw new Error(parsed.error || 'AI 产出的配置无法解析');
  const tables = parsed.config?.tables || [];
  const sel = new Map();
  cfg = new Map();
  for (const tc of tables) {
    const tm = tablesMeta.find((x) => x.name === tc.name);
    if (!tm) continue;
    const colSet = new Set();
    const cfgMap = new Map();
    for (const cc of tc.columns || []) {
      if (!tm.columns.some((x) => x.name === cc.name)) continue;
      colSet.add(cc.name);
      const colCfg = { generator: cc.generator || 'string', params: cc.params || {} };
      if (cc.null_ratio) colCfg.null_ratio = cc.null_ratio;
      if (cc.constraints?.unique) colCfg.constraints = { unique: true };
      cfgMap.set(cc.name, colCfg);
    }
    if (colSet.size) {
      sel.set(tc.name, colSet);
      cfg.set(tc.name, cfgMap);
    }
  }
  if (tree) tree.setSelection(sel);
}

// ---- Step 3：生成 -----------------------------------------------------------

function renderStep3() {
  const wrap = h('div', { class: 'step3' });
  const selectedTables = tablesMeta.filter((t) => (tree?.getSelection().get(t.name)?.size || 0) > 0);
  const order = topoOrderOf(selectedTables.map((t) => t.name));
  wrap.append(h('h3', { class: 'section-title' }, '表生成顺序（外键拓扑）'));
  wrap.append(h('div', { class: 'muted', id: 'topo-out' }, '计算中…'));
  order.then((names) => {
    const out = document.getElementById('topo-out');
    if (out) out.replaceChildren(h('div', { class: 'row' },
      ...names.map((n, i) => h('span', { class: 'pill gen' }, `${i + 1}. ${n}`))));
  });

  wrap.append(h('h3', { class: 'section-title' }, '预览（每表 5 行，不写库）'));
  const previewOut = h('div', { id: 'preview-out' });
  wrap.append(previewOut);
  doPreviews(selectedTables, previewOut);

  wrap.append(h('div', { class: 'row', style: 'margin-top:16px' },
    h('label', { class: 'genform-label' }, '每表行数:'),
    h('input', { type: 'number', id: 'gen-count', value: 50, min: 1 }),
    h('button', { class: 'primary', onclick: () => doGenerate(selectedTables) }, '开始生成'),
  ));
  wrap.append(h('div', { id: 'gen-out' }));
  return wrap;
}

async function topoOrderOf(names) {
  if (!names.length) return [];
  const res = await get(`/api/connections/${store.connId}/topo-order?tables=${names.join(',')}`);
  return res.tables;
}

function buildColumnsFor(tm) {
  const cfgMap = cfg.get(tm.name);
  const cols = {};
  if (cfgMap) {
    for (const [col, colCfg] of cfgMap) cols[col] = colCfg;
  }
  return Object.keys(cols).length ? cols : null;
}

async function doPreviews(selectedTables, out) {
  clear(out);
  for (const tm of selectedTables) {
    try {
      const res = await post(`/api/connections/${store.connId}/preview`, {
        table: tm.name, count: 5, columns: buildColumnsFor(tm),
      });
      const cols = Object.keys(res.rows[0] || {});
      out.append(h('div', { class: 'panel', style: 'margin-bottom:12px' },
        h('h3', { class: 'section-title' }, tm.name),
        h('div', { class: 'table-scroll', style: 'max-height:220px' },
          table(cols, res.rows.map((r) => cols.map((c) => fmt(r[c]))), { monoCols: cols.map((_, i) => i) })),
      ));
    } catch (e) {
      out.append(msg(`${tm.name} 预览失败：${e.message}`));
    }
  }
}

async function doGenerate(selectedTables) {
  const out = document.getElementById('gen-out');
  clear(out);
  const count = +document.getElementById('gen-count').value || 50;
  const names = selectedTables.map((t) => t.name);
  const order = await topoOrderOf(names);
  for (const tname of order) {
    const tm = tablesMeta.find((t) => t.name === tname);
    out.append(h('div', { class: 'muted' }, `生成 ${tname} …`));
    const res = await post(`/api/connections/${store.connId}/fill`, {
      table: tname, count, columns: buildColumnsFor(tm),
    });
    const job = await pollJob(res.job_id);
    const last = out.lastChild;
    if (job.status === 'done') {
      last.replaceChildren(h('span', { class: 'pill ok' }, `${tname}: ${job.rows_inserted} 行`));
    } else {
      last.replaceChildren(msg(`${tname}: ${job.error || '失败'}`));
    }
  }
  out.append(msg('全部完成。可在「数据浏览」页查看结果。', 'ok'));
}

async function pollJob(jobId) {
  for (let i = 0; i < 120; i++) {
    const j = await get(`/api/jobs/${jobId}`);
    if (j.status !== 'running') return j;
    await new Promise((r) => setTimeout(r, 400));
  }
  return { status: 'error', error: '超时' };
}

// ---- 底部持久栏 --------------------------------------------------------------

function renderFooter() {
  return h('div', { class: 'wizard-footer' },
    h('button', { onclick: saveConfig }, '保存配置文件'),
    h('button', { onclick: loadConfig }, '加载配置文件'),
    h('span', { style: 'flex:1' }),
    h('button', { id: 'btn-prev', onclick: () => { if (step > 1) { step--; renderStep(); } } }, '上一步'),
    h('button', { id: 'btn-next', class: 'primary', onclick: () => { if (step < 3) { step++; renderStep(); } } }, '下一步'),
  );
}

function updateFooter(rootEl = null) {
  const scope = rootEl || document;
  const prev = scope.querySelector('#btn-prev');
  const next = scope.querySelector('#btn-next');
  if (prev) prev.disabled = step === 1;
  if (next) next.disabled = step === 3;
}

async function saveConfig() {
  const yaml = buildYaml();
  const blob = new Blob([yaml], { type: 'text/yaml' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sqlseed_config.yaml';
  a.click();
  URL.revokeObjectURL(a.href);
}

function buildYaml() {
  const lines = [`db_path: ${store.target}`, 'tables:'];
  for (const tm of tablesMeta) {
    const sel = tree?.getSelection().get(tm.name);
    if (!sel || sel.size === 0) continue;
    lines.push(`  - name: ${tm.name}`);
    lines.push('    count: 100');
    lines.push('    columns:');
    for (const col of tm.columns) {
      if (!sel.has(col.name)) continue;
      const colCfg = cfg.get(tm.name)?.get(col.name);
      if (colCfg) {
        lines.push(`      - name: ${col.name}`);
        lines.push(`        generator: ${colCfg.generator}`);
        if (colCfg.params && Object.keys(colCfg.params).length) {
          lines.push('        params:');
          for (const [k, v] of Object.entries(colCfg.params)) {
            lines.push(`          ${k}: ${Array.isArray(v) ? JSON.stringify(v) : v}`);
          }
        }
        if (colCfg.null_ratio) lines.push(`        null_ratio: ${colCfg.null_ratio / 100}`);
        if (colCfg.constraints?.unique) lines.push('        constraints: {unique: true}');
      }
    }
  }
  return lines.join('\n') + '\n';
}

async function loadConfig() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.yaml,.yml';
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    const text = await file.text();
    try {
      await applyAiYaml(text);
      const body = document.getElementById('wizard-body');
      if (body) body.append(msg('配置已加载并映射到对象树与列属性，可逐列微调。', 'ok'));
    } catch (e) {
      const body = document.getElementById('wizard-body');
      if (body) body.append(msg(`配置无效：${e.message}`));
    }
  };
  input.click();
}
