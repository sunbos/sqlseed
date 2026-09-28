import { setConnBadge, store } from './api.js';
import { openConnectionDialog } from './workbench/connection.js';
import './tab-motion.js';
import {createDropdown} from './dropdown.js';
import {tr, t, setText, setAttr, getLanguage, setLanguage, onLanguageChange, loadBackendMessages, errorText} from './i18n.js';
import './i18n/messages/shell.js';

const languageHost = document.getElementById('language-control');
if (languageHost) {
  const control = createDropdown({label: tr('shell.language'), value: getLanguage(),
    options: [{value: 'zh-CN', label: '简体中文'}, {value: 'en', label: 'English'}],
    onChange: value => setLanguage(value)});
  languageHost.append(control.el);
  onLanguageChange(value => { if (control.get() !== value) control.set(value); });
}
setAttr(document.getElementById('nav'), 'aria-label', tr('shell.navigation'));
document.querySelectorAll('#nav button').forEach(button => {
  let caption = button.querySelector('[data-nav-label]');
  if (!caption) {
    caption = document.createElement('span');
    caption.setAttribute('data-nav-label', '');
    button.append(caption);
  }
  setText(caption, tr(`shell.${button.dataset.page}`));
});

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
let routeConnectionId = store.connId;
const maintenance = document.documentElement?.dataset.pluginMaintenance === 'true';
const initialRecovery = document.documentElement?.dataset.pluginSupervisedMaintenance === 'true';
let titlePage = 'workbench';
function updateTitle() {
  document.title = `sqlseed · ${t(maintenance ? 'shell.maintenance' : `shell.${titlePage}`)}`;
}
onLanguageChange(updateTitle);
updateTitle();
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
  titlePage = page;
  updateTitle();
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
      routeConnectionId = store.connId;
      setConnBadge();
    }
  } catch (error) {
    if (version === routeVersion) {
      setText(main, tr('shell.loadingFailed', {detail: errorText(error)}));
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
// Bind the initial shell before language assets or connection recovery finish.
setConnBadge();
connectionButton.onclick = () => {
  if (!maintenance) {
    openConnectionDialog({});
  }
};
window.addEventListener('hashchange', render);
window.addEventListener('sqlseed:connection-changed', event => {
  if (!maintenance) {
    if (routeConnectionId === store.connId) return;
    routeConnectionId = store.connId;
    // Document links belong to the previously selected target. Only the
    // explicit mismatch-recovery picker may continue the exact pending link.
    const keepRequest = store.connId && event.detail?.workbenchRequest === location.hash;
    if (location.hash.split('?')[0] === '#/workbench' && !keepRequest) {
      history.replaceState(history.state, '', '#/workbench');
    }
    setConnBadge();
    render();
  }
});
await loadBackendMessages();
await render();
