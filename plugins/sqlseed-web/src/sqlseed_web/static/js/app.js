// Router: hash-based navigation, lazy page module loading.
// Navicat-style IA: 连接 → 数据生成向导（三步工作台）→ 数据浏览（三栏）
// → 自愈实验室 → 系统面板。

import { setConnBadge } from './api.js';

const pages = {
  connect: () => import('./pages/connect.js'),
  wizard: () => import('./pages/wizard.js'),
  browse: () => import('./pages/browse.js'),
  heal: () => import('./pages/heal.js'),
  meta: () => import('./pages/meta.js'),
};

async function render() {
  const hash = location.hash || '#/connect';
  const page = hash.replace('#/', '').split('?')[0] || 'connect';
  const main = document.getElementById('main');
  document.querySelectorAll('#nav a').forEach((a) => {
    a.classList.toggle('active', a.dataset.page === page);
  });
  if (!pages[page]) {
    main.textContent = `未知页面: ${page}`;
    return;
  }
  const mod = await pages[page]();
  main.replaceChildren(mod.render());
  if (mod.mount) mod.mount();
}

window.addEventListener('hashchange', render);
setConnBadge();
render();
