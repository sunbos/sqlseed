// 文件选择器：服务器端目录浏览模态框。
// 浏览器安全模型不暴露本地绝对路径，但 UI 服务器就跑在本机，
// 通过 /api/fs/browse 列目录实现真正的"选择文件"按钮。

import { h, get, clear, msg } from './api.js';

/**
 * 打开文件选择模态框。
 * @param {object} opts
 * @param {string} [opts.startPath] 起始目录（默认用户主目录）
 * @param {(path: string) => void} opts.onPick 选中数据库文件后的回调
 */
export function openFilePicker({ startPath, onPick }) {
  const overlay = h('div', { class: 'modal-overlay', onclick: (e) => { if (e.target === overlay) close(); } });
  const listing = h('div', { class: 'file-list' });
  const crumbs = h('div', { class: 'file-crumbs' });
  const statusEl = h('div', { class: 'muted' }, '加载中…');
  const pathInput = h('input', {
    class: 'file-path-input', spellcheck: 'false', placeholder: '目录路径',
    onkeydown: (e) => { if (e.key === 'Enter') load(e.target.value.trim() || null); },
  });
  const showAll = { value: false };
  let current = null;
  let selected = null;

  const dialog = h('div', { class: 'modal' },
    h('h3', {}, '选择数据库文件'),
    h('div', { class: 'row' },
      pathInput,
      h('button', { class: 'small', onclick: () => load(pathInput.value.trim() || null) }, '转到'),
      h('button', { class: 'small', onclick: () => load(null) }, '主目录'),
      h('label', { class: 'muted' },
        h('input', {
          type: 'checkbox',
          onchange: (e) => { showAll.value = e.target.checked; load(current); },
        }), '显示全部文件'),
    ),
    crumbs,
    h('div', { class: 'file-list-wrap' }, listing),
    statusEl,
    h('div', { class: 'row end' },
      h('button', { onclick: close }, '取消'),
      h('button', { class: 'primary', disabled: true, id: 'fp-confirm' }, '选择'),
    ),
  );

  function close() { overlay.remove(); }

  function pick(path, isDb) {
    if (selected) selected.classList.remove('selected');
    if (!isDb) { selected = null; document.getElementById('fp-confirm').disabled = true; return; }
    selected = null;
    onPick(path);
    close();
  }

  function renderCrumbs(path) {
    clear(crumbs);
    const parts = path.split('/').filter(Boolean);
    crumbs.append(h('button', { class: 'small', onclick: () => load('/') }, '/'));
    let acc = '';
    for (const part of parts) {
      acc += `/${part}`;
      const target = acc;
      crumbs.append(h('span', { class: 'muted' }, '›'),
        h('button', { class: 'small', onclick: () => load(target) }, part));
    }
  }

  async function load(path) {
    clear(listing);
    statusEl.textContent = '加载中…';
    try {
      const q = path ? `?path=${encodeURIComponent(path)}` : '';
      const res = await get(`/api/fs/browse${q}${showAll.value ? (q ? '&' : '?') + 'all_files=true' : ''}`);
      current = res.path;
      pathInput.value = res.path;
      renderCrumbs(res.path);
      clear(listing);
      statusEl.textContent = `${res.entries.length} 个条目`;
      if (!res.entries.length) {
        listing.append(h('div', { class: 'muted', style: 'padding:16px' }, '（空目录）'));
      }
      for (const entry of res.entries) {
        listing.append(h('div', {
          class: `file-entry${entry.is_db ? ' db' : ''}${entry.is_dir ? ' dir' : ''}`,
          role: 'button',
          tabindex: '0',
          onclick: () => (entry.is_dir ? load(entry.path) : pick(entry.path, entry.is_db)),
          onkeydown: (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              entry.is_dir ? load(entry.path) : pick(entry.path, entry.is_db);
            }
          },
          title: entry.path,
        },
          h('span', { class: 'file-icon' }, entry.is_dir ? 'DIR' : entry.is_db ? 'DB' : '··'),
          h('span', { class: 'file-name' }, entry.name),
          entry.size !== null ? h('span', { class: 'muted file-size' }, humanSize(entry.size)) : null,
        ));
      }
    } catch (e) {
      statusEl.textContent = '';
      listing.append(msg(`无法浏览：${e.message}`));
    }
  }

  document.body.append(overlay);
  overlay.append(dialog);
  load(startPath || null);
}

function humanSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}
