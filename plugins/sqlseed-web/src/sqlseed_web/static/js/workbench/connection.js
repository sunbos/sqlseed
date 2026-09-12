import { h, get, send, store, rememberConnId, setConnBadge, safeTargetLabel } from '../api.js';
import { lockPageScroll } from './scroll-lock.js';

let activeDialog = null;

/** The same target picker serves first use and connection switching. */
export function openConnectionDialog({onConnected} = {}) {
  activeDialog?.close();
  const previousFocus = document.activeElement;
  const unlockScroll = lockPageScroll();
  const app = document.getElementById('app');
  const previousInert = app?.inert;
  if (app) app.inert = true;
  let closed = false, busy = false, sequence = 0, fileSequence = 0, existingSequence = 0, kind = 'sqlite';
  let pendingOperation = null;
  let connections = [];
  const fields = {};
  const error = h('p', {class: 'connection-error', role: 'alert'});
  const notice = h('p', {class: 'connection-notice', role: 'status', 'aria-live': 'polite'});
  const existing = h('div', {class: 'connection-existing'});
  const controls = h('div', {class: 'connection-fields'});
  const browser = h('section', {class: 'connection-browser', hidden: true, 'aria-label': '选择数据库文件'});
  const subtitle = h('p', {class: 'muted'}, '选择 SQLite 文件或连接 PostgreSQL，开始创建生成配置。');
  const closeButton = h('button', {class: 'close', type: 'button', 'aria-label': '关闭连接窗口', onclick: close}, '×');
  const submit = h('button', {class: 'btn primary', type: 'button', onclick: connect}, '连接数据库');
  const choices = h('div', {class: 'segmented', role: 'group', 'aria-label': '数据库类型'},
    ...['sqlite', 'postgresql'].map(value => h('button', {
      type: 'button', class: value === kind ? 'active' : '', 'aria-pressed': String(value === kind),
      onclick: () => {
        if (busy || kind === value) return;
        clearSecrets(); kind = value; error.textContent = ''; browser.hidden = true; fileSequence++;
        for (const button of choices.querySelectorAll('button')) {
          const selected = button.textContent === (kind === 'sqlite' ? 'SQLite' : 'PostgreSQL');
          button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
        }
        renderFields();
      },
    }, value === 'sqlite' ? 'SQLite' : 'PostgreSQL')));
  const overlay = h('div', {class: 'overlay open connection-overlay', onclick: event => {if (event.target === overlay) close();}},
    h('section', {class: 'modal connection-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': '连接数据库'},
      h('header', {class: 'modal-head'}, h('h2', {}, '连接数据库'), closeButton), subtitle,
      existing, h('h3', {class: 'connection-add-title'}, '添加连接'), choices, controls, browser, error, notice,
      h('footer', {class: 'modal-footer connection-footer'}, h('button', {class: 'btn', type: 'button', onclick: close}, '取消'), submit)));

  function clearSecrets() {
    if (fields.password) fields.password.value = '';
  }
  function close() {
    if (closed) return;
    closed = true; sequence++; fileSequence++; existingSequence++; clearSecrets(); overlay.remove();
    unlockScroll();
    document.removeEventListener('keydown', keydown);
    if (app) app.inert = previousInert;
    previousFocus?.focus?.({preventScroll: true});
    if (activeDialog?.close === close) activeDialog = null;
  }
  function field(name, label, value = '', type = 'text') {
    const input = h('input', {name, value, type, spellcheck: 'false', autocomplete: type === 'password' ? 'current-password' : 'off'});
    fields[name] = input;
    return h('label', {class: 'connection-field'}, h('span', {}, label), input);
  }
  function renderFields() {
    for (const name of Object.keys(fields)) delete fields[name];
    if (kind === 'sqlite') {
      controls.replaceChildren(field('db_path', '数据库文件'),
        h('button', {type: 'button', class: 'btn', onclick: () => {browser.hidden = false; browseFiles();}}, '选择文件'));
      fields.db_path.placeholder = '/path/to/database.sqlite3';
    } else {
      controls.replaceChildren(h('div', {class: 'connection-pair'}, field('host', '主机', 'localhost'), field('port', '端口', '5432', 'number')),
        field('database', '数据库名称'), h('div', {class: 'connection-pair'}, field('user', '用户名'), field('password', '密码', '', 'password')));
    }
  }
  function setBusy(operation = null) {
    const previous = pendingOperation;
    pendingOperation = operation; busy = !!operation;
    submit.disabled = busy; submit.textContent = operation?.kind === 'add' ? '正在添加连接…' : '连接数据库';
    controls.setAttribute('aria-busy', String(busy));
    existing.setAttribute('aria-busy', String(busy));
    if (operation) {
      notice.textContent = operation.message;
      fileSequence++; browser.hidden = true;
    } else if (notice.textContent === previous?.message) notice.textContent = '';
    for (const input of controls.querySelectorAll('input,button')) input.disabled = busy;
    for (const button of choices.querySelectorAll('button')) button.disabled = busy;
    renderExisting();
  }
  function publish(connection) {
    store.connId = connection.conn_id;
    const target = connection.target_label || connection.target;
    store.target = String(target || '').includes('://') ? safeTargetLabel(target) : target;
    store.tables = connection.tables || [];
    rememberConnId(connection.conn_id); setConnBadge(); close();
    window.dispatchEvent(new Event('sqlseed:connection-changed'));
    onConnected?.({conn_id: store.connId, target_label: safeTargetLabel(store.target), tables: store.tables});
  }
  function payload() {
    if (kind === 'sqlite') {
      const dbPath = fields.db_path.value.trim();
      if (!dbPath) throw new Error('请选择或输入数据库文件路径。');
      // A connection is an adapter target. Generator defaults belong to the
      // document; BaseProvider keeps connecting independent of optional extras.
      return {db_path: dbPath, provider: 'base'};
    }
    const hostname = fields.host.value.trim(), database = fields.database.value.trim(), user = fields.user.value.trim();
    const port = fields.port.value.trim();
    if (!hostname || !database || !user) throw new Error('请填写主机、数据库名称和用户名。');
    if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) throw new Error('端口必须是 1 到 65535 之间的整数。');
    const host = hostname.includes(':') && !hostname.startsWith('[') ? `[${hostname}]` : hostname;
    return {url: `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(fields.password.value)}@${host}:${port}/${encodeURIComponent(database)}`, provider: 'base'};
  }
  async function connect() {
    if (closed || busy) return;
    error.textContent = '';
    let data;
    try {data = payload();} catch (failure) {error.textContent = failure.message; return;}
    const expected = ++sequence; setBusy({kind: 'add', message: '正在添加连接，请等待数据库响应…'});
    try {
      const connection = await send('/api/connections', data);
      if (!closed && expected === sequence) publish(connection);
    } catch (failure) {
      if (!closed && expected === sequence) error.textContent = connectionError(failure.message);
    } finally {
      clearSecrets();
      if (!closed && expected === sequence) setBusy();
    }
  }
  async function useConnection(connection) {
    if (closed || busy || connection.conn_id === store.connId) return;
    const expected = ++sequence; error.textContent = '';
    setBusy({kind: 'switch', connId: connection.conn_id,
      message: `正在切换到 ${safeTargetLabel(connection.target_label || connection.target)}，读取表结构…`});
    try {
      const detail = await get(`/api/connections/${encodeURIComponent(connection.conn_id)}/tables`);
      if (!closed && expected === sequence) publish({...detail, conn_id: connection.conn_id});
    } catch (failure) {
      if (!closed && expected === sequence) error.textContent = connectionError(failure.message);
    } finally {
      if (!closed && expected === sequence) setBusy();
    }
  }
  async function disconnect(connection) {
    if (closed || busy) return;
    const expected = ++sequence; existingSequence++; error.textContent = '';
    setBusy({kind: 'disconnect', connId: connection.conn_id,
      message: `正在断开 ${safeTargetLabel(connection.target_label || connection.target)}…`});
    try {
      await send(`/api/connections/${encodeURIComponent(connection.conn_id)}`, undefined, 'DELETE');
      // The server close still took place if the dialog was closed meanwhile.
      // Clear only the removed current session, never a more recent selection.
      if (store.connId === connection.conn_id) {
        store.connId = null; store.target = null; store.tables = [];
        rememberConnId(''); setConnBadge();
        window.dispatchEvent(new Event('sqlseed:connection-changed'));
      }
      if (!closed && expected === sequence) {
        connections = connections.filter(item => item.conn_id !== connection.conn_id);
        notice.textContent = `已断开 ${safeTargetLabel(connection.target_label || connection.target)}，并从本次会话列表移除。数据库文件和数据保持不变。`;
        renderExisting();
      }
    } catch (failure) {
      if (!closed && expected === sequence) error.textContent = connectionError(failure.message);
    } finally {
      if (!closed && expected === sequence) setBusy();
    }
  }
  function renderExisting() {
    if (!connections.length) {existing.replaceChildren(); return;}
    const groups = new Map();
    for (const connection of connections) {
      const key = connection.group_key || connection.target || connection.conn_id;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(connection);
    }
    existing.replaceChildren(h('h3', {class: 'connection-label'}, '已连接的数据库'),
      h('p', {class: 'muted connection-session-help'}, '切换连接后查看对应配置。断开并移除只关闭本次服务会话，不会删除数据库或运行记录。'),
      ...[...groups.values()].map(group => {
        const target = group[0].target_label || group[0].target;
        return h('section', {class: 'connection-group'},
          h('header', {class: 'connection-group-heading'}, h('strong', {}, safeTargetLabel(target)),
            h('small', {}, `${group.length} 个会话`)),
          h('p', {class: 'mono connection-target'}, targetDescription(target)),
          ...group.map((connection, index) => h('div', {class: 'connection-session'},
            h('button', {class: 'connection-card', type: 'button', disabled: busy || connection.conn_id === store.connId,
              onclick: () => useConnection(connection), 'aria-label': `${connection.conn_id === store.connId ? '当前连接' : '切换到'} ${safeTargetLabel(target)} 会话 ${index + 1}`},
              h('span', {}, `会话 ${index + 1}`), h('small', {}, pendingOperation?.kind === 'switch' && pendingOperation.connId === connection.conn_id
                ? '正在切换…' : connection.conn_id === store.connId ? '当前连接' : '切换到此连接')),
            h('button', {class: 'btn small connection-disconnect', type: 'button', disabled: busy,
              'aria-label': `断开并移除 ${safeTargetLabel(target)} 会话 ${index + 1}`,
              onclick: () => disconnect(connection)}, pendingOperation?.kind === 'disconnect' && pendingOperation.connId === connection.conn_id
                ? '正在断开…' : '断开并移除'))));
      }));
  }
  async function loadExisting() {
    const expected = ++existingSequence;
    try {
      const response = await get('/api/connections');
      if (closed || expected !== existingSequence) return;
      connections = response.connections || [];
      renderExisting();
    } catch (failure) {
      if (!closed && expected === existingSequence) existing.replaceChildren(h('p', {class: 'muted'}, `已有连接暂不可用：${connectionError(failure.message)}`));
    }
  }
  async function browseFiles(path) {
    if (closed || busy) return;
    const expected = ++fileSequence;
    browser.replaceChildren(h('p', {role: 'status'}, '正在读取文件列表…'));
    try {
      const response = await get(`/api/fs/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`);
      if (closed || expected !== fileSequence) return;
      const pathInput = h('input', {value: response.path, 'aria-label': '目录路径', spellcheck: 'false'});
      const go = () => browseFiles(pathInput.value.trim());
      pathInput.addEventListener('keydown', event => {if (event.key === 'Enter') {event.preventDefault(); go();}});
      browser.replaceChildren(h('div', {class: 'connection-file-path'}, pathInput,
        h('button', {class: 'btn small', type: 'button', onclick: go}, '转到'),
        h('button', {class: 'btn small', type: 'button', disabled: !response.parent, onclick: () => browseFiles(response.parent)}, '上一级')),
        h('div', {class: 'connection-file-list'}, ...response.entries.map(entry => h('button', {
          type: 'button', class: `connection-file${entry.is_dir ? ' directory' : ''}`,
          onclick: () => {
            if (entry.is_dir) browseFiles(entry.path);
            else {fields.db_path.value = entry.path; browser.hidden = true; fileSequence++; fields.db_path.focus();}
          },
        }, entry.name))),
        ...(response.entries.length ? [] : [h('p', {class: 'muted'}, '此目录没有数据库文件。')]));
    } catch (failure) {
      if (!closed && expected === fileSequence) browser.replaceChildren(h('p', {role: 'alert', class: 'connection-error'}, connectionError(failure.message)),
        h('button', {type: 'button', class: 'btn small', onclick: () => browseFiles()}, '返回主目录'));
    }
  }
  function keydown(event) {
    if (event.key === 'Escape') {event.preventDefault(); close();}
    if (event.key !== 'Tab') return;
    const candidates = [...overlay.querySelectorAll('button,input,a[href]')].filter(element => !element.disabled && !element.closest('[hidden]'));
    const first = candidates[0], last = candidates.at(-1);
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }
  renderFields(); document.body.append(overlay); document.addEventListener('keydown', keydown); closeButton.focus();
  activeDialog = {close}; loadExisting();
  return activeDialog;
}

function targetDescription(target) {
  const text = String(target || '');
  if (!text.includes('://')) return text;
  try {
    const url = new URL(text);
    return `${url.protocol}//${url.host}${decodeURIComponent(url.pathname)}`;
  } catch {return '数据库连接';}
}

function connectionError(message) {
  return String(message || '连接失败，请检查目标及连接参数。')
    .replace(/([\w+.-]+:\/\/)[^\s/@]+@/g, '$1[credentials]@')
    .replace(/((?:password|sslpassword|token|secret|api_key)=)[^&\s'")]+/gi, '$1[redacted]');
}
