// AI 分析与修复：L2 validate → L3 repair → L5 auto-heal，逐层可视。
// 这是缺陷收敛的主战场：贴 YAML，看违规、看修复、看最终产物。
// 未安装 sqlseed-ai 时展示 onboarding 引导卡（安装命令 + 能力说明）。

import { h, post, get, store, msg, clear, table, fmt } from '../api.js';
import { createDropdown } from '../dropdown.js';

let yamlText = '';
let healTimer = null;

const templateTableDd = createDropdown({
  options: [],
  placeholder: '— 选择表 —',
  onChange: () => {},
});

export function render() {
  const root = h('div');
  templateTableDd.setOptions(
    store.tables.map((t) => ({ value: t.name, label: t.name })),
    store.tables[0]?.name || '',
  );
  root.append(
    h('h2', {}, 'AI 分析与修复（Layers 2 / 3 / 5）'),
    renderAiPanel(),
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('span', { class: 'pill gen' }, 'L2 FastValidator'),
        h('span', { class: 'pill gen' }, 'L3 RepairPipeline'),
        h('span', { class: 'pill gen' }, 'L5 AutoHealOrchestrator'),
        h('span', { style: 'flex:1' }),
      ),
      h('div', { class: 'row' },
        h('label', {}, '模板表'),
        templateTableDd.el,
        h('button', { onclick: loadTemplate }, '导入该表配置模板'),
      ),
      h('textarea', {
        id: 'heal-yaml', spellcheck: 'false',
        oninput: (e) => { yamlText = e.target.value; },
      }, yamlText),
      h('div', { class: 'row end' },
        h('button', { onclick: doValidate }, '① 校验（L2）'),
        h('button', { onclick: doRepair }, '② 修复（L3）'),
        h('button', { class: 'primary', onclick: doAutoHeal }, '③ 全流程自愈（L5，需 LLM）'),
      ),
    ),
    h('div', { id: 'heal-out' }),
  );
  const ta = document.getElementById('heal-yaml');
  if (ta && yamlText) ta.value = yamlText;
  return root;
}

export function mount() {
  if (!store.connId) {
    const out = document.getElementById('heal-out');
    clear(out);
    out.append(msg('AI 分析与修复需要先连接数据库（SchemaSnapshot 从连接读取 schema）。', 'warn'));
  }
}

// ---- AI 配置面板（在线/本地大模型，会话级，免重启切换） ----------------------

let aiState = null; // /api/ai/config 响应

async function loadAiConfig() {
  try {
    aiState = await get('/api/ai/config');
  } catch {
    aiState = null;
  }
  const holder = document.getElementById('ai-panel-body');
  if (holder) renderAiBody(holder);
}

function renderAiPanel() {
  const body = h('div', { id: 'ai-panel-body' }, h('div', { class: 'loading' }, '加载 AI 配置…'));
  loadAiConfig().then(() => renderAiBody(body));
  return h('div', { class: 'panel' },
    h('div', { class: 'row' },
      h('span', { class: 'pill gen' }, 'AI 配置'),
      h('span', { class: 'muted' }, '全流程自愈 / 一键生成配置使用的 LLM 后端（会话级，免重启切换）'),
    ),
    body,
  );
}

// 未安装 sqlseed-ai 时的 onboarding 引导卡：说清楚缺了什么、怎么装、
// 不装还能用什么（数据生成/浏览不依赖 AI）。
function renderOnboarding(holder, reason) {
  holder.append(
    h('div', { class: 'msg warn' }, reason || 'sqlseed-ai 未安装'),
    h('div', { class: 'muted', style: 'margin:8px 0; line-height:1.7' },
      'sqlseed-ai 是可选插件，提供：① 契约校验（L2）与确定性修复（L3）；'
      + '② LLM 全流程自愈（L5）；③ 数据生成向导里的「AI 一键生成配置」。'
      + '未安装时，连接、数据生成、数据浏览功能完全不受影响。'),
    h('div', { class: 'row' },
      h('label', {}, '安装命令'),
      h('code', {}, 'pip install -e ./plugins/sqlseed-web[ai]'),
    ),
    h('div', { class: 'muted', style: 'margin-top:6px' },
      '安装后刷新本页即可。本地模型（Ollama / LM Studio）无需 API Key；在线模型需要 Key。'),
  );
}

function renderAiBody(holder) {
  clear(holder);
  if (!aiState || !aiState.available) {
    renderOnboarding(holder, aiState?.reason);
    return;
  }
  const eff = aiState.effective;
  const ov = aiState.override || {};
  const backendDd = createDropdown({
    value: ov.backend || eff.backend,
    options: aiState.backends.map((b) => ({ value: b.id, label: b.label })),
    onChange: (v) => {
      const b = aiState.backends.find((x) => x.id === v);
      const keyInput = document.getElementById('ai-key');
      const urlInput = document.getElementById('ai-url');
      if (b && keyInput && urlInput) {
        keyInput.disabled = b.needs_key === '0';
        urlInput.disabled = b.needs_url === '0';
      }
    },
  });
  holder.append(
    h('div', { class: 'row' },
      h('label', {}, '后端'),
      backendDd.el,
      h('label', {}, '模型'),
      h('input', { id: 'ai-model', placeholder: '留空=自动（如 gemma4:e4b / gemma-4-26b-a4b-it）', value: ov.model || '' }),
    ),
    h('div', { class: 'row' },
      h('label', {}, 'API Key'),
      h('input', { id: 'ai-key', type: 'password', placeholder: '在线后端需要；本地后端无需密钥', value: ov.api_key || '' }),
      h('label', {}, 'Base URL'),
      h('input', { id: 'ai-url', placeholder: 'OpenAI 兼容服务需要；其余留空', value: ov.base_url || '' }),
    ),
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: () => saveAiConfig(backendDd) }, '应用配置'),
      h('button', { onclick: testConnection }, '测试连接'),
      h('span', { class: 'muted', id: 'ai-effective' },
        (eff.backend === 'ollama' || eff.backend === 'lm_studio')
          ? `当前生效：${eff.backend} · ${eff.model} · 本地后端无需 Key`
          : `当前生效：${eff.backend} · ${eff.model} · key ${eff.api_key_present ? '已配置' : '未配置'}`),
    ),
    h('div', { id: 'ai-test-out' }),
  );
  // 初始化输入框禁用态
  const initB = aiState.backends.find((x) => x.id === backendDd.get());
  if (initB) {
    document.getElementById('ai-key').disabled = initB.needs_key === '0';
    document.getElementById('ai-url').disabled = initB.needs_url === '0';
  }
}

async function testConnection() {
  const out = document.getElementById('ai-test-out');
  clear(out);
  out.append(h('div', { class: 'loading' }, '探测后端连接…'));
  try {
    const res = await post('/api/ai/test-connection', {});
    clear(out);
    if (!res.available) { out.append(msg(res.reason || 'sqlseed-ai 未安装', 'warn')); return; }
    out.append(msg(res.message, res.ok ? 'ok' : 'warn'));
  } catch (e) {
    clear(out);
    out.append(msg(`测试失败：${e.message}`));
  }
}

async function saveAiConfig(backendDd) {
  const payload = {
    backend: backendDd.get(),
    model: document.getElementById('ai-model').value.trim() || null,
    api_key: document.getElementById('ai-key').value.trim() || null,
    base_url: document.getElementById('ai-url').value.trim() || null,
  };
  try {
    aiState = await post('/api/ai/config', payload);
    const holder = document.getElementById('ai-panel-body');
    renderAiBody(holder);
    holder.append(msg('AI 配置已应用（本会话生效）。', 'ok'));
  } catch (e) {
    const holder = document.getElementById('ai-panel-body');
    holder.append(msg(`保存失败：${e.message}`));
  }
}

async function loadTemplate() {
  if (!store.connId || !store.tables.length) return;
  const t = templateTableDd.get() || store.tables[0].name;
  try {
    const res = await get(
      `/api/connections/${store.connId}/tables/${encodeURIComponent(t)}/yaml-template`);
    yamlText = res.yaml;
    const ta = document.getElementById('heal-yaml');
    if (ta) ta.value = yamlText;
  } catch (e) {
    const out = document.getElementById('heal-out');
    out.append(msg(e.message));
  }
}

function basePayload() {
  return { yaml: yamlText };
}

async function doValidate() {
  const out = document.getElementById('heal-out');
  clear(out);
  out.append(h('div', { class: 'loading' }, 'L2 校验中…'));
  try {
    const res = await post(`/api/connections/${store.connId}/heal/validate`, basePayload());
    clear(out);
    if (!res.ok) { out.append(msg(`校验器异常：${res.error}`)); return; }
    // renderViolations 返回数组：必须 spread，否则 append 把数组当单个参数
    // 字符串化成 "[object HTMLDivElement]"（P0 渲染 bug，实测发现）。
    out.append(...renderViolations(res));
  } catch (e) {
    clear(out);
    out.append(msg(e.message));
  }
}

function renderViolations(res) {
  const parts = [];
  parts.push(h('div', { class: 'panel' },
    h('h3', {}, `L2 校验结果 — schema_hash ${res.schema_hash?.slice(0, 12)}`),
    res.is_clean
      ? msg('配置干净：无违规。', 'ok')
      : msg(`发现 ${res.violation_count} 处违规：`, 'warn'),
  ));
  if (res.violations?.length) {
    parts.push(h('div', { class: 'panel' },
      h('h3', {}, 'ViolationReport 列表'),
      h('div', { class: 'table-scroll' },
        table(
          ['severity', 'table', 'columns', '类型', 'fix_hint', 'message'],
          res.violations.map((v) => [
            h('span', {
              class: `pill ${v.severity === 'crash' ? 'err' : v.severity === 'semantic_error' ? 'warn' : 'ok'}`,
            }, v.severity),
            v.table,
            fmt(v.columns),
            v.constraint_type,
            v.fix_hint || '—',
            v.message || '',
          ]),
          { monoCols: [1] },
        )),
    ));
  }
  if (res.column_groups?.length) {
    parts.push(h('div', { class: 'panel' },
      h('h3', {}, '复合 FK 协同组（ColumnGroup）'),
      h('div', { class: 'table-scroll' },
        table(['group_id', 'columns', 'parent_table', 'parent_columns'],
          res.column_groups.map((g) => [g.group_id, fmt(g.columns), g.parent_table, fmt(g.parent_columns)]),
          { monoCols: [0] })),
    ));
  }
  return parts;
}

async function doRepair() {
  const out = document.getElementById('heal-out');
  clear(out);
  out.append(h('div', { class: 'loading' }, 'L3 修复中…'));
  try {
    const res = await post(`/api/connections/${store.connId}/heal/repair`, basePayload());
    clear(out);
    if (!res.ok) { out.append(msg(`修复器异常：${res.error}`)); return; }
    out.append(h('div', { class: 'panel' },
      h('h3', {}, `L3 修复结果 — ${res.fix_count} 处已修`),
      res.applied_fixes?.length ?
        h('div', { class: 'table-scroll' },
          table(['策略', 'table', 'columns', 'before', 'after'],
            res.applied_fixes.map((f) => [
              h('span', { class: 'pill gen' }, f.fix_strategy),
              f.table, fmt(f.columns),
              h('code', {}, JSON.stringify(f.before)),
              h('code', {}, JSON.stringify(f.after)),
            ]),
            { monoCols: [1] }))
        : h('div', { class: 'muted' }, '无需修复。'),
      res.unfixable?.length ? msg(`不可自动修复 ${res.unfixable.length} 处，见 L2 视图。`, 'warn') : null,
    ));
    if (res.repaired_yaml) {
      const pre = h('pre', {}, res.repaired_yaml);
      out.append(h('div', { class: 'panel' },
        h('h3', {}, '修复后 YAML'),
        pre,
        h('div', { class: 'row end' },
          h('button', {
            onclick: () => {
              yamlText = res.repaired_yaml;
              document.getElementById('heal-yaml').value = yamlText;
            },
          }, '回填到编辑区'),
        ),
      ));
    }
  } catch (e) {
    clear(out);
    out.append(msg(e.message));
  }
}

async function doAutoHeal() {
  const out = document.getElementById('heal-out');
  clear(out);
  const status = h('div', { class: 'muted' }, '提交 L5 全流程任务（schema 快照 → 子图拆分 → 分层校验/修复/LLM 治愈 → 乐观锁 → YAML）…');
  out.append(h('div', { class: 'panel' }, h('h3', {}, 'L5 AutoHeal'), status));
  try {
    const res = await post(`/api/connections/${store.connId}/heal/auto`, { budget_seconds: 300 });
    healTimer = setInterval(async () => {
      try {
        const job = await get(`/api/jobs/${res.job_id}`);
        if (job.status === 'running') return;
        clearInterval(healTimer);
        if (job.status === 'error') {
          status.replaceWith(msg(`自愈失败：${job.error}`));
        } else {
          status.replaceWith(
            h('div', {},
              msg(`完成（模型 ${job.result.model} @ ${job.result.backend}）`, 'ok'),
              h('pre', {}, job.result.yaml),
              h('div', { class: 'row end' },
                h('button', {
                  onclick: () => {
                    yamlText = job.result.yaml;
                    document.getElementById('heal-yaml').value = yamlText;
                  },
                }, '回填到编辑区'),
                h('button', { class: 'primary', onclick: () => { location.hash = '#/run'; } }, '去填充 →'),
              ),
            ),
          );
        }
      } catch { clearInterval(healTimer); }
    }, 1000);
  } catch (e) {
    status.replaceWith(msg(e.message));
  }
}
