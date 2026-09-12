// API helpers + shared UI state (connection id survives page switches).

export const store = {
  connId: null,
  target: null,
  tables: []
};
export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json'
    },
    ...options
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail;
    const message = httpErrorMessage(detail, res.status, true);
    const error = new Error(message);
    error.status = res.status;
    error.detail = detail;
    throw error;
  }
  return body;
}
export const post = (path, data) => api(path, {
  method: 'POST',
  body: JSON.stringify(data)
});
export const send = (path, data, method = 'POST') => api(path, {
  method,
  body: JSON.stringify(data)
});
export const get = path => api(path);
export const del = path => api(path, {
  method: 'DELETE'
});

// ---- tiny DOM helpers -----------------------------------------------------

export const h = (tag, attrs = {}, ...children) => {
  const el = document.createElement(tag);
  applyAttributes(el, attrs);
  for (const c of children.flat(Infinity)) {
    if (c == null) {
      continue;
    }
    el.append(c.nodeType ? c : document.createTextNode(c));
  }
  return el;
};
export const clear = el => {
  while (el.firstChild) {
    el.firstChild.remove();
  }
};
export function table(headers, rows, {
  monoCols = []
} = {}) {
  const thead = h('thead', {}, h('tr', {}, ...headers.map(t => h('th', {}, t))));
  const tbody = h('tbody');
  for (const row of rows) {
    tbody.append(h('tr', {}, ...row.map((cell, i) => h('td', monoCols.includes(i) ? {
      class: 'mono'
    } : {}, cell ?? ''))));
  }
  return h('table', {}, thead, tbody);
}
export function msg(text, kind = 'err') {
  return h('div', {
    class: `msg ${kind}`
  }, text);
}
export function fmt(v) {
  if (v === null || v === undefined) {
    return '';
  }
  if (typeof v === 'object') {
    return JSON.stringify(v);
  }
  return String(v);
}
export function setConnBadge() {
  const label = document.getElementById('connection-label');
  if (label) {
    label.textContent = store.connId ? safeTargetLabel(store.target) : '连接数据库';
  }
  const badge = document.getElementById('conn-badge');
  if (!badge) {
    return;
  }
  if (store.connId) {
    badge.className = 'badge ok';
    badge.textContent = store.target || store.connId;
  } else {
    badge.className = 'badge empty';
    badge.textContent = '未连接';
  }
}

/** Display identity only; omit URL userinfo and query parameters. */
export function safeTargetLabel(target) {
  if (!target) {
    return '已连接数据库';
  }
  const text = String(target);
  if (text.includes('://')) {
    try {
      const url = new URL(text);
      return `${url.hostname}${url.port ? ":" + url.port : ''}${decodeURIComponent(url.pathname)}`;
    } catch {
      return '已连接数据库';
    }
  }
  return /^(?:[\\/]|[A-Za-z]:[\\/])/.test(text) ? text.split(/[\\/]/).findLast(Boolean) || text : text;
}

// ---- 跨刷新恢复 ------------------------------------------------------------
// store 是模块级内存状态，浏览器一刷新就清空；但服务端的连接对象仍然活着。
// 用 localStorage 记住上次用的 connId，恢复时先找它，找不到再回退到主连接
// （group_index 1）。服务重启导致连接全丢时，恢复失败并清除记录。

const CONN_KEY = 'sqlseed.connId';
let connectionChoiceVersion = 0;
let explicitlyDisconnected = false;
export function rememberConnId(connId) {
  connectionChoiceVersion++;
  explicitlyDisconnected = connId === '';
  try {
    localStorage.setItem(CONN_KEY, connId);
  } catch {
    /* 隐私模式等下 localStorage 不可用——恢复失败也只是退回手动连接，不值得报错 */
  }
}
export function forgetConnId() {
  connectionChoiceVersion++;
  explicitlyDisconnected = false;
  try {
    localStorage.removeItem(CONN_KEY);
  } catch {
    /* 同上 */
  }
}

/**
 * 尝试把上次会话的连接恢复进 store。
 * @returns {Promise<boolean>} 恢复成功与否（失败时 store 保持原样）
 */
export async function restoreConnection() {
  if (explicitlyDisconnected) {
    return false;
  }
  const originalConnection = store.connId;
  const originalChoiceVersion = connectionChoiceVersion;
  const current = () => store.connId === originalConnection && connectionChoiceVersion === originalChoiceVersion;
  let remembered = null;
  try {
    remembered = localStorage.getItem(CONN_KEY);
  } catch {
    return false;
  }
  // An empty stored id is an explicit user disconnect, not a missing history.
  // Preserve that choice even when other server-side sessions remain open.
  if (remembered === '') {
    return false;
  }
  try {
    const res = await get('/api/connections');
    if (!current()) {
      return Boolean(store.connId);
    }
    const list = res.connections || [];
    const pick = list.find(c => c.conn_id === remembered) || list.find(c => c.group_index === 1) || list[0];
    if (!pick) {
      forgetConnId();
      return false;
    }
    const detail = await get(`/api/connections/${pick.conn_id}/tables`);
    if (!current()) {
      return Boolean(store.connId);
    }
    store.connId = pick.conn_id;
    store.target = String(detail.target || '').includes('://') ? safeTargetLabel(detail.target) : detail.target;
    store.tables = detail.tables;
    setConnBadge();
    return true;
  } catch {
    if (!current()) {
      return Boolean(store.connId);
    }
    forgetConnId();
    return false;
  }
}
function applyAttributes(el, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') {
      el.className = v;
    } else if (k === 'onclick') {
      el.onclick = v;
    } else if (k.startsWith('on')) {
      el.addEventListener(k.slice(2), v);
    } else if (k === 'value') {
      el.value = v;
    } else if (k === 'checked') {
      el.checked = v;
    } else if (typeof v === 'boolean') {
      // 布尔属性（disabled 等）：false 必须移除属性——
      // setAttribute('disabled', false) 会因属性存在而仍判定为禁用。
      if (v) {
        el.setAttribute(k, '');
      } else {
        el.removeAttribute(k);
      }
    } else {
      el.setAttribute(k, v);
    }
  }
}
export function httpErrorMessage(detail, status, stringifyUnknown = false) {
  if (typeof detail === 'string') { return detail; }
  if (Array.isArray(detail)) {
    return detail.map(item => `${(item.loc || []).join('.')}: ${item.msg || JSON.stringify(item)}`).join('；');
  }
  if (detail?.message) { return detail.message; }
  if (stringifyUnknown && detail) { return JSON.stringify(detail); }
  return `HTTP ${status}`;
}
