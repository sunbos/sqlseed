// 数据生成向导（参考工具 式三步工作台）：
//   Step1 目标：连接选择 + 信息面板 + 流程图
//   Step2 对象：左树（勾选表/列）+ 右列属性面板（生成器/参数/预览/NULL/唯一）
//   Step3 生成：表生成顺序 + 逐表预览 + 按序填充
// 底部持久栏：保存配置文件 / 加载配置文件 / 表生成顺序 / 上一步 / 下一步

import { h, get, post, clear, msg, table, fmt } from '../api.js';
import { store, restoreConnection } from '../api.js';
import { createTree } from '../tree.js';
import { createGenForm } from '../genform.js';

let step = 1;
let meta = null;
let tablesMeta = []; // [{name, columns, specs, fks, foreignKeys, rowCount}]
let connInfo = null;
let tree = null;
let genform = null;
let cfg = new Map(); // table -> Map<col, ColumnConfig>（后端形状：null_ratio 0–1）
let treeSelection = null; // 树勾选跨步骤持久化（AI 选择不被步骤切换重置）
let aiCfg = null; // /api/ai/config 响应（会话覆盖已合并）——AI 就绪门控用
let stateConnId = null;
let stateRevision = 0;
let metaRequest = 0;
let configRequest = 0;
let importedConfig = null;
let tableConfigs = new Map();
let countOverride = null;
const runningConnections = new Set();

// 配置均来自 JSON API；深拷贝避免用户编辑嵌套参数改变已提交任务。
function copyConfig(value) {
  return JSON.parse(JSON.stringify(value));
}

function syncConnectionState() {
  if (stateConnId === store.connId) return;
  stateConnId = store.connId;
  stateRevision++;
  step = 1;
  meta = null;
  tablesMeta = [];
  connInfo = null;
  tree = null;
  genform = null;
  cfg = new Map();
  treeSelection = null;
  aiCfg = null;
  importedConfig = null;
  tableConfigs = new Map();
  countOverride = null;
}

function isCurrentConnection(connId, revision) {
  return store.connId === connId && stateRevision === revision;
}

function selection() {
  return tree?.getSelection() || treeSelection
    || new Map(tablesMeta.map((tm) => [tm.name, new Set(tm.columns.map((c) => c.name))]));
}

export function render() {
  syncConnectionState();
  const root = h('div', { class: 'wizard' });
  root.append(renderHeader());
  const body = h('div', { class: 'wizard-body', id: 'wizard-body' });
  root.append(body);
  root.append(renderFooter());
  renderStep(body, root);
  return root;
}

export async function mount() {
  if (!store.connId) {
    // 页面刷新会清空模块级 store，但服务端的连接对象仍然活着——
    // 先尝试按 localStorage 记录（或主连接）恢复，失败才提示去连接页。
    const ok = await restoreConnection();
    if (!ok) {
      const body = document.getElementById('wizard-body');
      clear(body);
      body.append(msg('先在「数据库连接」页打开一个数据库，再进入数据生成向导。', 'warn'));
      return;
    }
  }
  // 「配置助手」页的「送到数据生成向导」：导入其产出的 YAML 并直达 Step 2。
  syncConnectionState();
  const connId = store.connId;
  const revision = stateRevision;
  const pending = store.aiYaml;
  delete store.aiYaml;
  try {
    if (!await loadMeta()) return;
    if (pending) step = 2;
    renderStep();
    if (pending) {
      const { tables, cols } = await applyAiYaml(pending);
      document.getElementById('wizard-body')?.append(
        msg(`已导入 AI 生成的配置（${tables} 张表 / ${cols} 列），可逐列微调。`, 'ok'));
    }
  } catch (e) {
    if (isCurrentConnection(connId, revision)) {
      document.getElementById('wizard-body')?.append(msg(`加载向导失败：${e.message}`));
    }
  }
}

function renderHeader() {
  return h('div', { class: 'wizard-header' },
    h('span', { class: 'wizard-db-icon' }, '🗄'),
    h('div', {},
      h('div', { class: 'wizard-db-name', id: 'wizard-db-target' }, store.target || '未连接'),
      h('div', { class: 'muted', id: 'wizard-step-label' }, `步骤 ${step} / 3 — ${['目标', '对象', '生成'][step - 1]}`),
    ),
  );
}

async function loadMeta() {
  syncConnectionState();
  const connId = store.connId;
  if (!connId) return false;
  const revision = stateRevision;
  const request = ++metaRequest;
  const names = store.tables.map((t) => t.name);
  const [nextMeta, nextAiCfg, snapshot] = await Promise.all([
    get('/api/meta/generators'),
    get('/api/ai/config').catch(() => null),
    loadTablesMeta(connId, names),
  ]);
  if (!isCurrentConnection(connId, revision) || request !== metaRequest) return false;
  meta = nextMeta;
  aiCfg = nextAiCfg;
  connInfo = snapshot.connInfo;
  tablesMeta = snapshot.tables;
  return true;
}

async function loadTablesMeta(connId, names) {
  const conns = await get('/api/connections');
  const tables = await Promise.all(names.map(async (name) => {
    const [schema, mapping] = await Promise.all([
      get(`/api/connections/${connId}/tables/${encodeURIComponent(name)}/schema`),
      get(`/api/connections/${connId}/tables/${encodeURIComponent(name)}/mapping`),
    ]);
    return {
      name,
      columns: schema.columns,
      specs: mapping.mapping,
      fks: new Set((schema.foreign_keys || []).map((fk) => fk.column)),
      foreignKeys: schema.foreign_keys || [],
      uniqueColumns: new Set(schema.unique_columns || []),
      rowCount: schema.row_count,
    };
  }));
  return { connInfo: conns.connections.find((c) => c.conn_id === connId) || null, tables };
}

function renderStep(bodyEl = null, rootEl = null) {
  const body = bodyEl || document.getElementById('wizard-body');
  if (!body) return;
  clear(body);
  if (step === 1) body.append(renderStep1());
  else if (step === 2) body.append(renderStep2());
  else body.append(renderStep3());
  const targetLabel = (rootEl || document).querySelector('#wizard-db-target');
  if (targetLabel) targetLabel.textContent = store.target || '未连接';
  const stepLabel = (rootEl || document).querySelector('#wizard-step-label');
  if (stepLabel) stepLabel.textContent = `步骤 ${step} / 3 — ${['目标', '对象', '生成'][step - 1]}`;
  updateFooter(rootEl);
  showImportNotes(body);
}

// ---- Step 1：目标 -----------------------------------------------------------

function renderStep1() {
  const info = connInfo;
  const ready = aiReadiness();
  return h('div', { class: 'step1' },
    h('div', { class: 'step1-left' },
      h('h3', { class: 'section-title' }, '目标'),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, '连接:'),
        h('span', { class: 'pill ok' }, info ? `${info.target}` : '未连接')),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, '数据语言与地区:'),
        h('span', { class: 'pill' }, info?.locale || '—')),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, '数据生成引擎:'),
        h('span', { class: 'pill' }, info?.provider || '—')),
      h('div', { class: 'genform-row' }, h('label', { class: 'genform-label' }, 'AI 状态:'),
        ready.ok
          ? h('span', { class: 'pill ok' }, `已就绪（${ready.backend} · ${ready.model}）`)
          : h('span', { class: 'pill warn' }, `未就绪 — ${ready.reason}`)),
      h('h3', { class: 'section-title', style: 'margin-top:24px' }, '信息'),
      h('div', { class: 'muted', style: 'white-space:pre-line' },
        `数据库类型: SQLite\n文件: ${store.target || '—'}\n表: ${store.tables.length} 张\n总行数: ${store.tables.reduce((n, t) => n + t.row_count, 0)}\n\nAI 状态决定 Step 2 是否可用「AI 一键生成配置」；未就绪时仍可手动配置生成器。`),
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
  const connId = store.connId;
  const revision = stateRevision;
  const wrap = h('div', { class: 'step2' });
  const left = h('div', { class: 'step2-left' });
  const right = h('div', { class: 'step2-right' });
  wrap.append(left, right);

  tree = createTree({
    tables: tablesMeta,
    // 树标注优先反映 AI/加载的列级配置（实时反馈），否则用零配置推断
    specResolver: (t, c) => {
      const cc = cfg.get(t)?.get(c);
      if (cc) return { generator_name: cc.generator };
      const tm = tablesMeta.find((x) => x.name === t);
      return tm?.specs?.[c];
    },
    initialSelection: treeSelection,
    onSelectColumn: showColumnInPanel,
    onChange: (checked) => {
      if (!isCurrentConnection(connId, revision)) return;
      // 勾选状态持久化 + 取消勾选的列从 cfg 移除
      treeSelection = new Map([...checked].map(([k, v]) => [k, new Set(v)]));
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
    // 数据库唯一约束列（主键/唯一索引）——属性面板据此锁定「设置唯一」。
    uniqueColumnsOf: (t) => tablesMeta.find((x) => x.name === t)?.uniqueColumns,
    // 外键来自 schema，不能被导入配置中的 generator 或派生表达式覆盖。
    foreignKeysOf: (t) => tablesMeta.find((x) => x.name === t)?.foreignKeys || [],
    onChange: (t, c, colCfg) => {
      if (!isCurrentConnection(connId, revision)) return;
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
// 就绪 = 已安装 sqlseed-ai 且（本地后端 或 在线后端已配 Key）。
function aiReadiness() {
  if (!aiCfg || !aiCfg.available) {
    return { ok: false, reason: aiCfg?.reason || 'sqlseed-ai 未安装（pip install -e ./plugins/sqlseed-web[ai]）' };
  }
  const eff = aiCfg.effective;
  const isLocal = eff.backend === 'ollama' || eff.backend === 'lm_studio';
  if (!isLocal && !eff.api_key_present) {
    return { ok: false, reason: `当前后端 ${eff.backend} 需要 API 密钥，请到「配置助手」页填写，或切换到本地模型（Ollama / LM Studio 无需密钥）` };
  }
  return { ok: true, backend: eff.backend, model: eff.model };
}

function renderAiGenBar() {
  const bar = h('div', { class: 'row', style: 'margin-bottom:8px' });
  const ready = aiReadiness();
  if (!ready.ok) {
    bar.append(h('span', { class: 'muted', style: 'font-size:12px' },
      `AI 一键生成配置未就绪：${ready.reason}`));
    return bar;
  }
  bar.append(
    h('button', { class: 'primary small', id: 'btn-ai-gen', onclick: aiGenerateConfig }, 'AI 一键生成配置'),
    h('span', { class: 'muted', id: 'ai-gen-status', style: 'font-size:12px' },
      `由 ${ready.backend} 分析 schema 生成一版配置并回填（替换当前列级配置，不写库），你可在右侧逐列微调`),
  );
  return bar;
}

async function aiGenerateConfig() {
  const connId = store.connId;
  const revision = stateRevision;
  const btn = document.getElementById('btn-ai-gen');
  const status = document.getElementById('ai-gen-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = '正在探测 AI 后端…';
  try {
    // 先探测后端可达性：失败直接给友好提示（如 Ollama 未启动），
    // 不发起注定失败的 LLM 任务。
    const probe = await post('/api/ai/test-connection', {});
    if (!isCurrentConnection(connId, revision)) return;
    if (!probe.available || !probe.ok) {
      throw new Error(probe.message || probe.reason || 'AI 后端不可用');
    }
    if (status) status.textContent = `后端 ${probe.backend} 可达，正在按约束生成配置（确定性校验/修复优先，仅在需要语义决策时调用 LLM）…`;
    const res = await post(`/api/connections/${connId}/heal/auto`, { budget_seconds: 300 });
    const job = await pollJob(res.job_id, 900);
    if (!isCurrentConnection(connId, revision)) return;
    if (job.status !== 'done' || !job.result?.yaml) {
      throw new Error(job.error || '生成失败');
    }
    const { tables, cols } = await applyAiYaml(job.result.yaml);
    const n = job.result.llm_calls;
    const llmNote = n === 0
      ? '本次未调用 LLM —— schema 无语义违规，全部由确定性校验/修复完成（这正是 AI 插件的契约驱动设计：LLM 只在必要时介入）'
      : `LLM 调用 ${n} 次`;
    if (status) status.textContent = `已回填 AI 配置（${tables} 张表 / ${cols} 列，${llmNote}）——点击列即可微调。`;
  } catch (e) {
    if (status) status.textContent = `AI 生成未执行：${e.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 把 AI 产出的 YAML 解析为结构化 config，映射回树勾选与列级配置。
// 只回填当前连接里真实存在的表/列，忽略 schema 之外的噪声。
// 返回回填的表/列数量；树标注与右侧面板同步刷新。
async function applyAiYaml(yamlText, connId = store.connId, revision = stateRevision) {
  const request = ++configRequest;
  const parsed = await post('/api/config/parse', { yaml: yamlText });
  if (!isCurrentConnection(connId, revision) || request !== configRequest) {
    throw new Error('连接或配置已更新，已忽略旧配置结果');
  }
  if (!parsed.valid) throw new Error(parsed.error || 'AI 产出的配置无法解析');
  importedConfig = copyConfig(parsed.config || {});
  tableConfigs = new Map();
  countOverride = null;
  const tables = importedConfig.tables || [];
  const sel = new Map();
  cfg = new Map();
  for (const tc of tables) {
    const tm = tablesMeta.find((x) => x.name === tc.name);
    if (!tm) continue;
    const tableCfg = copyConfig(tc);
    delete tableCfg.columns;
    tableConfigs.set(tc.name, tableCfg);
    const colSet = new Set();
    const cfgMap = new Map();
    for (const cc of tc.columns || []) {
      if (!tm.columns.some((x) => x.name === cc.name)) continue;
      colSet.add(cc.name);
      const colCfg = copyConfig(cc);
      delete colCfg.name;
      cfgMap.set(cc.name, colCfg);
    }
    // 空 columns 表示整表使用推断规则，仍保留该表的选择与执行参数。
    if (!(tc.columns || []).length) tm.columns.forEach((c) => colSet.add(c.name));
    if (colSet.size) {
      sel.set(tc.name, colSet);
      cfg.set(tc.name, cfgMap);
    }
  }
  treeSelection = new Map([...sel].map(([k, v]) => [k, new Set(v)]));
  if (tree) {
    tree.setSelection(sel); // 触发重渲染：标注即时反映 AI 选择
  }
  // 右侧属性面板同步：当前选中列若在 AI 配置内则展示 AI 值
  const selCol = tree?.getSelectedColumn();
  if (selCol?.table && selCol?.col) showColumnInPanel(selCol.table, selCol.col);
  showImportNotes();
  const colCount = [...sel.values()].reduce((n, s) => n + s.size, 0);
  return { tables: sel.size, cols: colCount };
}

// 在右侧属性面板展示某列：AI/加载配置优先于零配置推断。
// cfg 里 null_ratio 是 0–1（后端形状），genform.fromInferred 内部会
// *100 转成展示百分比，这里原样透传。
function showColumnInPanel(t, c) {
  if (!genform) return;
  const tm = tablesMeta.find((x) => x.name === t);
  if (!tm) return;
  const colInfo = tm.columns.find((x) => x.name === c);
  if (!colInfo) return;
  const cc = cfg.get(t)?.get(c);
  const spec = cc ? { ...copyConfig(cc), generator_name: cc.generator } : tm.specs[c];
  // tm.specs[c] 是零配置推断结果，作为属性面板「重置属性」的回落基线。
  genform.setColumn(t, c, colInfo, spec, tm.specs[c]);
}

// ---- Step 3：生成 -----------------------------------------------------------

function renderStep3() {
  const wrap = h('div', { class: 'step3' });
  const selected = selection();
  const selectedTables = tablesMeta.filter((t) => (selected.get(t.name)?.size || 0) > 0);
  const order = topoOrderOf(selectedTables.map((t) => t.name));
  wrap.append(h('h3', { class: 'section-title' }, '表生成顺序（外键拓扑）'));
  const topoOut = h('div', { class: 'muted', id: 'topo-out' }, '计算中…');
  wrap.append(topoOut);
  order.then((names) => {
    topoOut.replaceChildren(h('div', { class: 'row' },
      ...names.map((n, i) => h('span', { class: 'pill gen' }, `${i + 1}. ${n}`))));
  }).catch((e) => topoOut.replaceChildren(msg(`生成顺序读取失败：${e.message}`)));

  wrap.append(h('h3', { class: 'section-title' }, '预览（每表 5 行，不写库）'));
  const previewOut = h('div', { id: 'preview-out' });
  wrap.append(previewOut);
  doPreviews(selectedTables, previewOut);

  wrap.append(h('div', { class: 'row', style: 'margin-top:16px' },
    h('label', { class: 'genform-label' }, tableConfigs.size ? '每表行数（修改后覆盖配置）:' : '每表行数:'),
    h('input', { type: 'number', id: 'gen-count', value: countOverride ?? (tableConfigs.size ? '' : 50), min: 1,
      placeholder: tableConfigs.size ? '保留各表配置行数' : '',
      oninput: (e) => { countOverride = e.target.value === '' ? null : +e.target.value; },
    }),
    h('button', { class: 'primary', id: 'btn-generate', disabled: runningConnections.has(store.connId),
      onclick: () => doGenerate(selectedTables) }, '开始生成'),
  ));
  wrap.append(h('div', { id: 'gen-out' }));
  return wrap;
}

async function topoOrderOf(names, connId = store.connId) {
  if (!names.length) return [];
  const res = await get(`/api/connections/${connId}/topo-order?tables=${encodeURIComponent(names.join(','))}`);
  return res.tables;
}

function buildColumnsFor(tm) {
  const cfgMap = cfg.get(tm.name);
  const cols = {};
  if (cfgMap) {
    for (const [col, colCfg] of cfgMap) cols[col] = copyConfig(colCfg);
  }
  return Object.keys(cols).length ? cols : null;
}

function tableRequest(tm, count) {
  const options = copyConfig(tableConfigs.get(tm.name) || {});
  delete options.name;
  return { ...options, table: tm.name, count, columns: buildColumnsFor(tm) };
}

async function doPreviews(selectedTables, out) {
  const connId = store.connId;
  const requests = selectedTables.map((tm) => tableRequest(tm, 5));
  clear(out);
  for (const request of requests) {
    try {
      const res = await post(`/api/connections/${connId}/preview`, request);
      const cols = Object.keys(res.rows[0] || {});
      out.append(h('div', { class: 'panel', style: 'margin-bottom:12px' },
        h('h3', { class: 'section-title' }, request.table),
        h('div', { class: 'table-scroll', style: 'max-height:220px' },
          table(cols, res.rows.map((r) => cols.map((c) => fmt(r[c]))), { monoCols: cols.map((_, i) => i) })),
      ));
    } catch (e) {
      out.append(msg(`${request.table} 预览失败：${e.message}`));
    }
  }
}

async function doGenerate(selectedTables) {
  const connId = store.connId;
  if (runningConnections.has(connId)) return;
  const out = document.getElementById('gen-out');
  const btn = document.getElementById('btn-generate');
  clear(out);
  // 所有可编辑输入必须在第一次 await 前冻结，包括对象内嵌套的 params。
  const defaultCount = +document.getElementById('gen-count').value || 50;
  const requests = new Map(selectedTables.map((tm) => {
    const count = countOverride ?? tableConfigs.get(tm.name)?.count ?? defaultCount;
    return [tm.name, tableRequest(tm, count)];
  }));
  if (!requests.size) {
    out.append(msg('请先选择要生成数据的表。', 'warn'));
    return;
  }
  if ([...requests.values()].some((r) => !Number.isInteger(r.count) || r.count < 1)) {
    out.append(msg('生成行数必须为正整数。'));
    return;
  }
  runningConnections.add(connId);
  if (btn) btn.disabled = true;
  try {
    const names = [...requests.keys()];
    const order = await topoOrderOf(names, connId);
    if (order.length !== names.length || new Set(order).size !== names.length || order.some((n) => !requests.has(n))) {
      throw new Error('返回的表生成顺序与所选表不一致，请重新加载向导');
    }
    for (const tname of order) {
      const progress = h('div', { class: 'muted' }, `生成 ${tname} …`);
      out.append(progress);
      const res = await post(`/api/connections/${connId}/fill`, requests.get(tname));
      const job = await pollJob(res.job_id);
      const errors = job.result?.errors;
      if (job.status !== 'done' || errors?.length) {
        const details = job.error || (Array.isArray(errors) ? errors.join('; ') : errors) || '失败';
        progress.replaceChildren(msg(`${tname}: ${details}（已写入 ${job.rows_inserted || 0} 行）`));
        out.append(msg('生成已停止，后续表未执行。', 'warn'));
        return;
      }
      progress.replaceChildren(h('span', { class: 'pill ok' }, `${tname}: ${job.rows_inserted} 行`));
    }
    out.append(msg('全部完成。可在「数据浏览」页查看结果。', 'ok'));
  } catch (e) {
    out.append(msg(`生成已停止：${e.message}`));
  } finally {
    runningConnections.delete(connId);
    if (btn) btn.disabled = false;
    if (store.connId === connId) {
      const currentButton = document.getElementById('btn-generate');
      if (currentButton) currentButton.disabled = false;
    }
  }
}

async function pollJob(jobId, maxTries = 120) {
  // 默认 120*400ms=48s 足够 fill；AI 全流程自愈可能要几分钟，调用方传更大 maxTries。
  for (let i = 0; i < maxTries; i++) {
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
  let yaml;
  try {
    yaml = await buildYaml();
  } catch (e) {
    document.getElementById('wizard-body')?.append(msg(`保存配置失败：${e.message}`));
    return;
  }
  const blob = new Blob([yaml], { type: 'text/yaml' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sqlseed_config.yaml';
  a.click();
  URL.revokeObjectURL(a.href);
}

function buildConfig() {
  const result = importedConfig ? copyConfig(importedConfig) : {
    ...(String(store.target).includes('://') ? { url: store.target } : { db_path: store.target }),
    ...(connInfo?.provider ? { provider: connInfo.provider } : {}),
    ...(connInfo?.locale ? { locale: connInfo.locale } : {}),
  };
  const selected = selection();
  result.tables = tablesMeta.filter((tm) => selected.get(tm.name)?.size).map((tm) => {
    const options = copyConfig(tableConfigs.get(tm.name) || { name: tm.name, count: 50 });
    if (countOverride !== null) options.count = countOverride;
    options.columns = tm.columns.filter((c) => selected.get(tm.name).has(c.name) && cfg.get(tm.name)?.has(c.name))
      .map((c) => ({ name: c.name, ...copyConfig(cfg.get(tm.name).get(c.name)) }));
    return options;
  });
  return result;
}

async function buildYaml() {
  const res = await post('/api/config/serialize', { yaml: JSON.stringify(buildConfig()) });
  return res.yaml;
}

function showImportNotes(body = document.getElementById('wizard-body')) {
  if (!importedConfig) return;
  const notes = [];
  if (importedConfig.associations?.length || importedConfig.custom_column_mappings) {
    notes.push('关联与自定义映射已保留在配置中；这些根设置需使用导出的配置执行。');
  }
  const target = importedConfig.url || importedConfig.db_path;
  if ((target && target !== store.target)
      || (connInfo?.provider && importedConfig.provider && connInfo.provider !== importedConfig.provider)
      || (connInfo?.locale && importedConfig.locale && connInfo.locale !== importedConfig.locale)) {
    notes.push('配置中的数据库、数据生成引擎或数据语言与地区与当前连接不同；向导生成使用当前连接，导出保留原设置。');
  }
  if (notes.length) body?.append(msg(notes.join(' '), 'warn'));
}

async function loadConfig() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.yaml,.yml,.json';
  const connId = store.connId;
  const revision = stateRevision;
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    const text = await file.text();
    try {
      await applyAiYaml(text, connId, revision);
      const body = document.getElementById('wizard-body');
      if (body) body.append(msg('配置已加载并映射到对象树与列属性，可逐列微调。', 'ok'));
    } catch (e) {
      const body = document.getElementById('wizard-body');
      if (body) body.append(msg(`配置无效：${e.message}`));
    }
  };
  input.click();
}
