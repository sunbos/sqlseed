// API helpers + shared UI state (connection id survives page switches).

export const store = {
  connId: null,
  target: null,
  tables: [],
};

export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return body;
}

export const post = (path, data) =>
  api(path, { method: 'POST', body: JSON.stringify(data) });
export const get = (path) => api(path);
export const del = (path) => api(path, { method: 'DELETE' });

// ---- tiny DOM helpers -----------------------------------------------------

export const h = (tag, attrs = {}, ...children) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k === 'onclick') el.onclick = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = v;
    else if (typeof v === 'boolean') {
      // 布尔属性（disabled 等）：false 必须移除属性——
      // setAttribute('disabled', false) 会因属性存在而仍判定为禁用。
      if (v) el.setAttribute(k, '');
      else el.removeAttribute(k);
    }
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null) continue;
    el.append(c.nodeType ? c : document.createTextNode(c));
  }
  return el;
};

export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };

export function table(headers, rows, { monoCols = [] } = {}) {
  const thead = h('thead', {}, h('tr', {}, ...headers.map((t) => h('th', {}, t))));
  const tbody = h('tbody');
  for (const row of rows) {
    tbody.append(h('tr', {}, ...row.map((cell, i) =>
      h('td', monoCols.includes(i) ? { class: 'mono' } : {}, cell ?? ''))));
  }
  return h('table', {}, thead, tbody);
}

export function msg(text, kind = 'err') {
  return h('div', { class: `msg ${kind}` }, text);
}

export function fmt(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function setConnBadge() {
  const badge = document.getElementById('conn-badge');
  if (store.connId) {
    badge.className = 'badge ok';
    badge.textContent = store.target || store.connId;
  } else {
    badge.className = 'badge empty';
    badge.textContent = '未连接';
  }
}
