import { setConnBadge } from './api.js';
import { openConnectionDialog } from './workbench/connection.js';

// Retired connect/wizard/browse/heal/meta modules remain historical source only.
// Product navigation mounts the unified workbench or durable run history.
const pages = {
  workbench: () => import('./pages/workbench.js'),
  configs: () => import('./pages/configs.js'),
  runs: () => import('./pages/runs.js'),
  settings: () => import('./pages/settings.js')
};
let currentModule = null;
let routeVersion = 0;
let committedPage = null;
const maintenance = document.documentElement?.dataset.pluginMaintenance === 'true';
const initialRecovery = document.documentElement?.dataset.pluginSupervisedMaintenance === 'true';
async function render() {
  const version = ++routeVersion;
  currentModule?.unmount?.();
  currentModule = null;
  const requested = location.hash.replace('#/', '').split('?')[0];
  const recovering = initialRecovery && committedPage === null;
  let page;
  if (maintenance || recovering) {
    page = 'settings';
  } else if (Object.hasOwn(pages, requested)) {
    page = requested;
  } else {
    page = 'workbench';
  }
  if ((maintenance || recovering) && location.hash !== '#/settings?section=plugins') {
    location.hash = '#/settings?section=plugins';
  }
  document.title = maintenance ? 'sqlseed · 插件维护' : `sqlseed · ${{
    workbench: '工作台',
    configs: '配置管理',
    runs: '运行记录',
    settings: '设置'
  }[page]}`;
  const main = document.getElementById('app');
  document.querySelectorAll('#nav button').forEach(button => {
    const active = button.dataset.page === page;
    button.classList.toggle('active', active);
    if (active) {
      button.setAttribute('aria-current', 'page');
    } else {
      button.removeAttribute('aria-current');
    }
  });
  try {
    const module = await pages[page]();
    if (version !== routeVersion) {
      return;
    }
    currentModule = module;
    const content = module.render();
    if (committedPage !== null && committedPage !== page) {
      content.classList.add('page-enter');
    }
    main.replaceChildren(content);
    committedPage = page;
    await module.mount?.();
    if (version === routeVersion && !maintenance) {
      setConnBadge();
    }
  } catch (error) {
    if (version === routeVersion) {
      main.textContent = `页面加载失败：${error.message}`;
    }
  }
}
document.querySelectorAll('#nav button').forEach(button => {
  const unavailable = maintenance && button.dataset.page !== 'settings';
  button.hidden = unavailable;
  button.disabled = unavailable;
  button.onclick = () => {
    if (!unavailable) {
      location.hash = maintenance ? '#/settings?section=plugins' : `#/${button.dataset.page}`;
    }
  };
});
const connectionButton = document.getElementById('connection-button');
connectionButton.hidden = maintenance;
connectionButton.disabled = maintenance;
connectionButton.onclick = () => {
  if (!maintenance) {
    openConnectionDialog({});
  }
};
window.addEventListener('hashchange', render);
window.addEventListener('sqlseed:connection-changed', () => {
  if (!maintenance) {
    setConnBadge();
    render();
  }
});
await render();
