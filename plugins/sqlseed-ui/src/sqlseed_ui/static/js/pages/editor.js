// 配置编辑器：YAML ⇄ 结构化双向编辑，带 core load_config 校验。

import { h, get, post, store, msg, clear, table } from '../api.js';

let yamlText = '';
let parsed = null;

export function render() {
  const root = h('div');
  root.append(
    h('h2', {}, '配置编辑器（YAML 双向）'),
    h('div', { class: 'grid2' },
      h('div', { class: 'panel' },
        h('h3', {}, 'YAML'),
        h('textarea', {
          id: 'yaml-input',
          spellcheck: 'false',
          oninput: (e) => { yamlText = e.target.value; },
        }, yamlText),
        h('div', { class: 'row end' },
          h('button', { onclick: doValidate }, '校验（load_config）'),
          h('button', { onclick: loadFromMapping }, '从表映射导入'),
          h('button', { class: 'primary', onclick: () => { location.hash = '#/run'; } }, '去预览/填充 →'),
        ),
      ),
      h('div', { class: 'panel' },
        h('h3', {}, '解析结果'),
        h('div', { id: 'parse-out' }, h('div', { class: 'muted' }, '点击「校验」用核心 load_config 验证 YAML。')),
      ),
    ),
  );
  return root;
}

export function mount() {
  const ta = document.getElementById('yaml-input');
  if (ta && yamlText) ta.value = yamlText;
}

async function doValidate() {
  const out = document.getElementById('parse-out');
  clear(out);
  out.append(h('div', { class: 'loading' }, '校验中…'));
  try {
    const res = await post('/api/config/parse', { yaml: yamlText });
    clear(out);
    if (!res.valid) {
      out.append(msg(`配置无效：${res.error}`, 'err'));
      return;
    }
    parsed = res.config;
    out.append(msg('配置有效（通过 GeneratorConfig 校验）', 'ok'));
    out.append(renderConfig(res.config));
  } catch (e) {
    clear(out);
    out.append(msg(e.message));
  }
}

function renderConfig(config) {
  const tables = config.tables || [];
  return h('div', {},
    h('div', { class: 'stats' },
      h('div', {}, h('div', { class: 'stat' }, tables.length), h('div', { class: 'stat-label' }, '表')),
      h('div', {}, h('div', { class: 'stat' }, tables.reduce((n, t) => n + (t.columns || []).length, 0)),
        h('div', { class: 'stat-label' }, '列配置')),
    ),
    ...tables.map((t) => h('details', { open: '' },
      h('summary', {}, `${t.name}（count=${t.count ?? '默认'}）`),
      table(
        ['列', '生成器', '参数', 'null_ratio', '约束', '派生'],
        (t.columns || []).map((c) => [
          c.name,
          h('span', { class: 'pill gen' }, c.generator || c.derive_from ? c.generator || 'derive' : '—'),
          c.params ? h('code', {}, JSON.stringify(c.params)) : '',
          c.null_ratio ?? '—',
          c.constraints ? h('code', {}, JSON.stringify(c.constraints)) : '',
          c.derive_from ? `${c.derive_from} = ${c.expression}` : '',
        ]),
        { monoCols: [0] },
      )),
    )),
  );
}

async function loadFromMapping() {
  if (!store.connId || !store.tables.length) {
    const out = document.getElementById('parse-out');
    clear(out);
    out.append(msg('先连接数据库。', 'warn'));
    return;
  }
  const table = store.tables[0].name;
  try {
    const res = await get(
      `/api/connections/${store.connId}/tables/${encodeURIComponent(table)}/yaml-template`);
    yamlText = res.yaml;
    const ta = document.getElementById('yaml-input');
    if (ta) ta.value = yamlText;
    doValidate();
  } catch (e) {
    const out = document.getElementById('parse-out');
    clear(out);
    out.append(msg(e.message));
  }
}
