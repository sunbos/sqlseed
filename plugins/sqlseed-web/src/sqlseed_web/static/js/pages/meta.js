// 系统面板：35 生成器 + 参数签名、12 hooks、provider 链、AI 后端状态。
// 验收驾驶舱：这里的计数必须与代码一致（doc-sync 的 UI 版）。

import { h, get, msg, clear, table } from '../api.js';

let data = null;

export function render() {
  const root = h('div');
  root.append(
    h('h2', {}, '系统面板'),
    h('div', { class: 'muted', style: 'margin-bottom:12px; line-height:1.6' },
      '系统面板是 sqlseed 运行时的「体检报告」：展示当前安装的核心能力清单'
      + '（生成器类型及参数、插件 hook、数据 provider 回退链、AI 后端状态）与最近任务记录。'
      + '用于确认环境是否就绪、各计数是否与代码一致——不参与数据生成配置。'),
    h('div', { id: 'meta-out' }, h('div', { class: 'loading' }, '加载中…')),
  );
  return root;
}

export function mount() {
  load();
}

async function load() {
  const out = document.getElementById('meta-out');
  try {
    const [generators, hooks, providers, ai, info, jobs] = await Promise.all([
      get('/api/meta/generators'),
      get('/api/meta/hooks'),
      get('/api/meta/providers'),
      get('/api/meta/ai'),
      get('/api/meta/info'),
      get('/api/jobs'),
    ]);
    data = { generators, hooks, providers, ai, info, jobs };
    clear(out);
    out.append(
      renderStats(generators, hooks, ai, info),
      renderGenerators(generators),
      renderHooks(hooks),
      renderProviders(providers),
      renderJobs(jobs),
    );
  } catch (e) {
    clear(out);
    out.append(msg(e.message));
  }
}

function renderStats(gen, hooks, ai, info) {
  return h('div', { class: 'panel' },
    h('div', { class: 'stats' },
      h('div', {}, h('div', { class: 'stat' }, gen.count), h('div', { class: 'stat-label' }, '生成器类型')),
      h('div', {}, h('div', { class: 'stat' }, hooks.count), h('div', { class: 'stat-label' }, '插件 hooks')),
      h('div', {}, h('div', { class: 'stat' }, info.sqlseed_version || '—'),
        h('div', { class: 'stat-label' }, 'sqlseed 版本')),
    ),
    h('div', { class: 'row' },
      ai.available
        ? h('span', { class: 'pill ok' }, `AI: ${ai.model} @ ${ai.backend}（协议 ${ai.tool_calling_protocol}）`)
        : h('span', { class: 'pill warn' }, `AI 不可用：${ai.reason}`),
    ),
  );
}

function renderGenerators(gen) {
  const paramList = (name) => (gen.params[name] || []).join(', ');
  return h('div', { class: 'panel' },
    h('h3', {}, `生成器清单（${gen.count}）— BaseProvider._gen_* 参数签名`),
    h('div', { class: 'table-scroll' },
      table(['生成器', '参数'],
        gen.names.map((n) => [h('span', { class: 'pill gen' }, n), paramList(n) || '—']),
        { monoCols: [1] })),
  );
}

function renderHooks(hooks) {
  return h('div', { class: 'panel' },
    h('h3', {}, `Hook 清单（${hooks.count}）`),
    h('div', { class: 'table-scroll' },
      table(['hook', 'firstresult'],
        hooks.hooks.map((hk) => [
          hk.name,
          hk.firstresult ? h('span', { class: 'pill ok' }, 'first') : h('span', { class: 'pill' }, 'all'),
        ]),
        { monoCols: [0] })),
  );
}

function renderProviders(providers) {
  return h('div', { class: 'panel' },
    h('h3', {}, 'Provider 回退链'),
    h('div', { class: 'row' },
      ...providers.default_chain.map((p) => h('span', {
        class: `pill ${providers.available.includes(p) ? 'ok' : 'warn'}`,
      }, p)),
      h('span', { class: 'muted' }, '（灰 = 未安装，自动降级）'),
    ),
  );
}

function renderJobs(jobs) {
  if (!jobs.jobs.length) return h('div');
  return h('div', { class: 'panel' },
    h('h3', {}, '最近任务'),
    h('div', { class: 'table-scroll' },
      table(['任务', '类型', '状态', '插入行数', '错误'],
        jobs.jobs.map((j) => [
          j.label,
          j.kind,
          h('span', { class: `pill ${j.status === 'done' ? 'ok' : j.status === 'error' ? 'err' : 'warn'}` }, j.status),
          j.rows_inserted,
          j.error ? j.error.slice(0, 80) : '',
        ]))),
  );
}
