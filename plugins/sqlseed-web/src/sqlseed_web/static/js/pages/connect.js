// 连接页：三种连接方式（本地数据库文件 / PostgreSQL / 自定义 URL），
// 文件选择用服务器端目录浏览模态框（filepicker.js），
// 下拉统一用自定义 dropdown 组件（原生 select 弹层在嵌入式 WebView 中定位错乱）。

import { h, post, get, del, store, setConnBadge, table, msg, clear } from '../api.js';
import { openFilePicker } from '../filepicker.js';
import { createDropdown } from '../dropdown.js';

const form = {
  kind: 'sqlite',
  db_path: '',
  url: '',
  pg: { host: 'localhost', port: 5432, user: '', password: '', database: '' },
  provider: 'mimesis',
  locale: 'zh_CN',
};
let locales = null;

// 下拉组件为模块级实例：状态跨页面切换保留，render() 重建时重新挂载 el。
const kindDd = createDropdown({
  value: form.kind,
  options: [
    { value: 'sqlite', label: '本地数据库文件（SQLite）' },
    { value: 'postgresql', label: 'PostgreSQL' },
    { value: 'url', label: '自定义 URL' },
  ],
  onChange: (v) => { form.kind = v; renderKind(); },
});
const providerDd = createDropdown({
  value: form.provider,
  options: [
    { value: 'mimesis', label: 'mimesis（高性能，可选）' },
    { value: 'faker', label: 'faker（标准）' },
    { value: 'base', label: 'base（零依赖）' },
  ],
  onChange: (v) => { form.provider = v; },
});
const localeDd = createDropdown({
  value: form.locale,
  options: [],
  placeholder: '加载中…',
  onChange: (v) => { form.locale = v; },
});

export function render() {
  const root = h('div');
  root.append(
    h('h2', {}, '连接数据库'),
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('label', {}, '数据库类型'),
        kindDd.el,
        h('span', { class: 'muted', id: 'kind-hint' }, 'SQLite 文件（.db / .sqlite / .sqlite3）'),
      ),
      (() => { const el = h('div', { id: 'kind-body' }); renderKind(el); return el; })(),
      h('div', { class: 'row' },
        h('label', {}, '数据引擎 Provider'),
        providerDd.el,
        h('label', {}, '数据 Locale'),
        localeDd.el,
        h('button', { class: 'primary', onclick: doConnect }, '连接'),
      ),
    ),
    h('div', { id: 'tables-out' }),
  );
  loadLocales();
  refreshExisting();
  return root;
}

function renderKind(mountedBody) {
  const body = mountedBody || document.getElementById('kind-body');
  const hint = document.getElementById('kind-hint');
  if (!body) return;
  const setHint = (text) => { if (hint) hint.textContent = text; };
  clear(body);
  if (form.kind === 'sqlite') {
    setHint('SQLite 文件（.db / .sqlite / .sqlite3）');
    body.append(
      h('div', { class: 'row' },
        h('label', {}, '数据库文件'),
        h('input', {
          id: 'db-path-input', class: 'grow', spellcheck: 'false',
          placeholder: '点击右侧「浏览…」选择，或直接输入绝对路径',
          value: form.db_path,
          oninput: (e) => { form.db_path = e.target.value; },
        }),
        h('button', { onclick: () => openFilePicker({
          startPath: form.db_path ? form.db_path.replace(/\/[^/]*$/, '') : undefined,
          onPick: (p) => { form.db_path = p; document.getElementById('db-path-input').value = p; },
        }) }, '浏览…'),
      ),
    );
  } else if (form.kind === 'postgresql') {
    setHint('字段化填写连接参数（拼接为 postgresql:// URL）');
    body.append(
      h('div', { class: 'row' },
        h('label', {}, '主机'), h('input', { value: form.pg.host, oninput: (e) => { form.pg.host = e.target.value; } }),
        h('label', {}, '端口'), h('input', { type: 'number', value: form.pg.port, style: 'min-width:90px', oninput: (e) => { form.pg.port = +e.target.value; } }),
      ),
      h('div', { class: 'row' },
        h('label', {}, '用户'), h('input', { value: form.pg.user, placeholder: 'postgres', oninput: (e) => { form.pg.user = e.target.value; } }),
        h('label', {}, '密码'), h('input', { type: 'password', value: form.pg.password, oninput: (e) => { form.pg.password = e.target.value; } }),
        h('label', {}, '数据库'), h('input', { value: form.pg.database, placeholder: 'mydb', oninput: (e) => { form.pg.database = e.target.value; } }),
      ),
      h('div', { class: 'muted' }, '需安装 psycopg（sqlseed[postgresql]），数据库需可达。'),
    );
  } else {
    setHint('任意 SQLAlchemy URL（为未来支持的数据库预留）');
    body.append(
      h('div', { class: 'row' },
        h('label', {}, '连接 URL'),
        h('input', {
          class: 'grow', spellcheck: 'false',
          placeholder: 'postgresql://user:pass@host:5432/db',
          value: form.url,
          oninput: (e) => { form.url = e.target.value; },
        }),
      ),
    );
  }
}

async function loadLocales() {
  try {
    const res = await get('/api/meta/locales');
    locales = res.locales;
    localeDd.setOptions(
      res.locales.map((l) => ({ value: l.code, label: `${l.label}（${l.code}）` })),
      res.default,
    );
    form.locale = res.default;
  } catch { /* keep the loading placeholder; connection still works */ }
}

function buildPayload() {
  if (form.kind === 'sqlite') {
    return { db_path: form.db_path || null, url: null, provider: form.provider, locale: form.locale };
  }
  if (form.kind === 'postgresql') {
    const { host, port, user, password, database } = form.pg;
    const auth = user ? `${encodeURIComponent(user)}${password ? `:${encodeURIComponent(password)}` : ''}@` : '';
    const url = `postgresql://${auth}${host}:${port}/${database}`;
    return { db_path: null, url, provider: form.provider, locale: form.locale };
  }
  return { db_path: null, url: form.url || null, provider: form.provider, locale: form.locale };
}

async function doConnect() {
  const out = document.getElementById('tables-out');
  clear(out);
  const payload = buildPayload();
  if (!payload.db_path && !payload.url) {
    out.append(msg(form.kind === 'sqlite' ? '请选择或输入数据库文件路径。' : '请填写连接信息。', 'warn'));
    return;
  }
  try {
    const res = await post('/api/connections', payload);
    store.connId = res.conn_id;
    store.target = res.target;
    store.tables = res.tables;
    setConnBadge();
    renderTables(out, res);
  } catch (e) {
    out.append(msg(`连接失败：${e.message}`));
  }
}

function renderTables(out, res) {
  out.append(
    h('div', { class: 'msg ok' }, `已连接 ${res.conn_id}（${res.tables.length} 张表）`),
    h('div', { class: 'table-scroll' },
      table(
        ['表名', '行数', '列数', '外键数'],
        res.tables.map((t) => [t.name, t.row_count, t.column_count, t.foreign_keys]),
        { monoCols: [0] },
      )),
  );
}

async function refreshExisting() {
  try {
    const res = await get('/api/connections');
    if (!res.connections.length) return;
    const out = document.getElementById('tables-out');
    if (!out || out.children.length) return;
    out.append(
      h('h3', {}, '已有连接'),
      h('div', { class: 'table-scroll' },
        table(
          ['连接 ID', '目标', '分组', 'Provider', 'Locale', ''],
          res.connections.map((c) => [
            c.conn_id,
            c.target,
            groupBadge(c),
            c.provider,
            c.locale,
            h('button', {
              class: 'small',
              onclick: async () => {
                await del(`/api/connections/${c.conn_id}`);
                if (store.connId === c.conn_id) { store.connId = null; setConnBadge(); }
                location.reload();
              },
            }, '断开'),
          ]),
        )),
    );
  } catch { /* server not reachable — ignore */ }
}

// 同一物理数据库的多个连接（合法且支持并发写，见 state.py 归一化说明）：
// 第 1 个标记「主」，后续标记「并行 N」；同组同色，颜色由 group_key 哈希决定。
const GROUP_HUES = [212, 152, 38, 274, 350, 190]; // 与现有 accent 配色协调

function groupBadge(c) {
  if (!c.group_key) return '—';
  const idx = c.group_index ?? 1;
  const size = c.group_size ?? 1;
  if (size <= 1) return h('span', { class: 'pill' }, '唯一');
  const hue = GROUP_HUES[hashStr(c.group_key) % GROUP_HUES.length];
  const label = idx === 1 ? `主连接 · 1/${size}` : `并行 ${idx} · ${idx}/${size}`;
  return h('span', {
    class: 'pill group-badge',
    style: `color: hsl(${hue} 70% 65%); border-color: hsl(${hue} 70% 45% / 0.55);`,
  }, label);
}

function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; }
  return Math.abs(h);
}
