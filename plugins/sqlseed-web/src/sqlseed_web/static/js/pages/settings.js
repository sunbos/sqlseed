import { h, api, store } from '../api.js';
import { button } from '../workbench/ui.js';
import { createDropdown } from '../dropdown.js';
import { createThemeControl } from '../theme-control.js';
import { createGenerationDefaultsControl } from '../generation-defaults-control.js';
import { createUpdateCheckControl } from '../update-check-control.js';
import { peekAIHandoff, requestAIReturn, leaveAISettings } from '../workbench/ai-handoff.js';
import { createPluginManagement, componentImpact } from '../workbench/plugin-management.js';
const prefix = '/api/workbench/ai';
const backends = [{
  value: 'ollama',
  label: 'Ollama'
}, {
  value: 'lm_studio',
  label: 'LM Studio'
}, {
  value: 'openai_compat',
  label: 'OpenAI 兼容服务'
}, {
  value: 'google_ai_studio',
  label: 'Google AI Studio'
}];
const defaults = {
  ollama: 'http://localhost:11434/v1',
  lm_studio: 'http://localhost:1234/v1',
  google_ai_studio: 'https://generativelanguage.googleapis.com/v1beta/openai'
};
const keySources = {
  session: '密钥仅在本次服务中有效，重启后需重新填写。',
  environment: '密钥来自服务环境变量。',
  none: '尚未配置密钥。'
};
const descriptions = {
  core: '离线生成、约束处理与数据库写入',
  cli: '在终端配置、预览和生成数据',
  web: '当前浏览器工作台',
  ai: '根据表结构与业务说明提出规则建议',
  mcp: '供 MCP 客户端调用生成能力',
  base: '内置基础数据与语义占位值',
  faker: '姓名、地址等本地化测试数据',
  mimesis: '另一种本地化数据实现，可按场景选择'
};
let root, aiPanel, pluginsPanel, appearancePanel, themeControl, sections, form, backend, endpoint, modelInput, key, clearKey;
let notice, saveState, badge, currentService, readinessNote, keyLabel, keyHint, serviceHint, testNotice, models, save, probe, reset, returnButton, returnPrompt, storageInfo;
let config = null,
  loaded = false,
  busy = false,
  version = 0,
  configController = null;
let settingsVersion = 0,
  settingsStale = false;
let environmentList,
  environmentNotice,
  environmentSummary,
  refreshButton,
  environmentController = null,
  environmentVersion = 0;
let installationVersion = 0;
let commandGroupSequence = 0;
let currentSection = 'ai';
let generationPanel, generationControl, updateControl;
let generationAllowed = false;
let management,
  environmentInfo = null,
  environmentLoading = false;
  generationAllowed = false;
const field = (label, input, help) => h('label', {
  class: 'settings-field'
}, h('span', {}, label), input, help ? h('small', {
  class: 'muted'
}, help) : null);
const currentDraft = () => ({
  backend: backend.get(),
  model: modelInput.value.trim(),
  base_url: endpoint.value.trim(),
  api_key: key.value,
  clear_api_key: clearKey.checked
});
function dirty() {
  if (!loaded || !config) {
    return false;
  }
  const effective = config.effective || {},
    draft = currentDraft();
  return Boolean(draft.api_key || draft.clear_api_key || ['backend', 'model', 'base_url'].some(name => draft[name] !== (effective[name] || (name === 'backend' ? 'ollama' : ''))));
}
function setNotice(element, text, state = '') {
  element.textContent = text;
  element.dataset.state = state;
}
export function render() {
  management?.destroy();
  themeControl?.destroy();
  generationControl?.destroy();
  updateControl?.destroy();
  invalidateInstallationCopies();
  version++;
  loaded = false;
  busy = false;
  config = null;
  settingsStale = false;
  environmentInfo = null;
  environmentLoading = false;
  const requestedSection = new URLSearchParams(location.hash.split('?')[1] || '').get('section');
  currentSection = ['plugins', 'generation', 'appearance'].includes(requestedSection) ? requestedSection : 'ai';
  notice = h('p', {
    class: 'settings-notice',
    role: 'status',
    'aria-live': 'polite',
    'data-settings-notice': ''
  }, '正在读取设置…');
  saveState = h('p', {
    class: 'settings-save-state muted',
    role: 'status',
    'data-settings-save-state': ''
  });
  badge = h('span', {
    class: 'settings-badge'
  }, '读取中');
  currentService = h('p', {
    class: 'settings-current-model'
  }, '正在读取当前服务…');
  readinessNote = h('p', {
    class: 'settings-readiness muted'
  });
  keyLabel = h('span', {
    'data-settings-key-label': ''
  }, 'API Key');
  keyHint = h('p', {
    class: 'muted settings-key-hint'
  });
  serviceHint = h('p', {
    class: 'settings-service-hint muted'
  });
  testNotice = h('p', {
    class: 'settings-test-notice',
    role: 'status',
    'aria-live': 'polite',
    'data-settings-test': ''
  });
  models = h('div', {
    class: 'settings-models',
    'aria-label': '服务中的模型'
  });
  modelInput = h('input', {
    type: 'text',
    'aria-label': '模型名称',
    placeholder: '填写服务提供的完整模型 ID',
    maxlength: 200,
    autocomplete: 'off',
    oninput: changed
  });
  endpoint = h('input', {
    type: 'url',
    'aria-label': 'AI 服务地址',
    placeholder: 'https://example.com/v1',
    maxlength: 2000,
    autocomplete: 'off',
    oninput: changed
  });
  key = h('input', {
    type: 'password',
    'aria-label': 'API Key',
    value: '',
    placeholder: '输入新密钥',
    maxlength: 4000,
    autocomplete: 'new-password',
    oninput: () => {
      if (key.value) {
        clearKey.checked = false;
      }
      changed();
    }
  });
  clearKey = h('input', {
    type: 'checkbox',
    'aria-label': '停用已配置密钥',
    onchange: () => {
      if (clearKey.checked) {
        key.value = '';
      }
      changed();
    }
  });
  backend = createDropdown({
    label: 'AI 服务',
    value: 'ollama',
    options: backends,
    onChange: value => {
      endpoint.value = defaults[value] || '';
      modelInput.value = '';
      key.value = '';
      clearKey.checked = false;
      changed();
    }
  });
  save = button('保存设置', () => submit(false), {
    primary: true
  });
  probe = button('检测连接', () => submit(true));
  reset = button('撤销修改', () => {
    if (!busy && config) {
      populate();
      setNotice(testNotice, '');
      models.replaceChildren();
      setNotice(notice, '已恢复当前生效的设置。');
    }
  });
  storageInfo = h('details', {
    class: 'settings-storage'
  }, h('summary', {}, '保存范围与有效期'));
  form = h('div', {
    class: 'settings-form'
  }, h('div', {
    class: 'settings-fields'
  }, field('AI 服务', backend.el), field('服务地址', endpoint)), serviceHint, field('默认模型', modelInput, '检测连接可读取服务中的模型列表；不会自动开始分析。'), testNotice, models, h('div', {
    class: 'settings-key'
  }, field(keyLabel, key), keyHint, h('label', {
    class: 'settings-clear-key'
  }, clearKey, '停用本次服务的密钥')), h('div', {
    class: 'settings-actions'
  }, save, probe, reset), saveState, storageInfo);
  const installation = h('section', {
    class: 'settings-install',
    'data-ai-install': '',
    hidden: true
  });
  aiPanel = h('section', {
    id: 'settings-ai',
    class: 'settings-panel',
    role: 'tabpanel',
    'aria-labelledby': 'settings-tab-ai'
  }, h('header', {
    class: 'settings-panel-head'
  }, h('div', {}, h('h2', {}, 'AI 服务'), h('p', {
    class: 'muted'
  }, '配置默认服务，供工作台的 AI 配置助手使用。')), badge), h('section', {
    class: 'settings-current',
    'aria-label': '当前使用的 AI 服务'
  }, h('span', {
    class: 'muted'
  }, '当前使用'), currentService, readinessNote), installation, form, notice);
  environmentNotice = h('p', {
    class: 'settings-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  environmentSummary = h('p', {
    class: 'muted'
  }, '正在读取运行环境…');
  environmentList = h('div', {
    class: 'settings-environment'
  });
  refreshButton = button('刷新状态', refreshPlugins, {
    glyph: 'refresh'
  });
  management = createPluginManagement({
    initialEnabled: document.documentElement?.dataset.pluginMaintenance === 'true',
    onChange: () => {
      updatePluginControls();
      refreshButton.disabled = environmentLoading || management.refreshBlocked;
    },
    onMode: setMaintenanceMode,
    onRestored: async () => {
      const expected = version,
        preserveDraft = dirty();
      const request = ++settingsVersion;
      settingsStale = true;
      configController?.abort();
      busy = false;
      probe.textContent = '检测连接';
      save.textContent = '保存设置';
      setNotice(testNotice, '');
      models.replaceChildren();
      update();
      await Promise.all([refreshEnvironment({
        replace: true
      }), refreshCurrentConnection(expected)]);
      if (expected !== version || request !== settingsVersion) {
        return;
      }
      await loadSettings({
        preserveDraft
      });
      if (expected === version && request === settingsVersion) {
        generationAllowed = true;
        window.dispatchEvent(new Event('sqlseed:plugins-changed'));
      }
    }
  });
  updateControl = createUpdateCheckControl({management});
  pluginsPanel = h('section', {
    id: 'settings-plugins',
    class: 'settings-panel',
    role: 'tabpanel',
    'aria-labelledby': 'settings-tab-plugins'
  }, h('header', {
    class: 'settings-panel-head'
  }, h('div', {}, h('h2', {}, '插件与版本'), h('p', {
    class: 'muted'
  }, '查看当前 Web 服务所在 Python 环境中的组件。')), refreshButton), management.el, updateControl.el, environmentSummary, environmentNotice, environmentList);
  generationControl = createGenerationDefaultsControl();
  generationPanel = h('section', {id: 'settings-generation', class: 'settings-panel', role: 'tabpanel', 'aria-labelledby': 'settings-tab-generation'},
    h('header', {class: 'settings-panel-head'}, h('div', {}, h('h2', {}, '新建配置偏好'), h('p', {class: 'muted'}, '设置新配置的常用起点；已有配置保持原值。'))), generationControl.el);
  themeControl = createThemeControl();
  appearancePanel = h('section', {
    id: 'settings-appearance',
    class: 'settings-panel',
    role: 'tabpanel',
    'aria-labelledby': 'settings-tab-appearance'
  }, h('header', {
    class: 'settings-panel-head'
  }, h('div', {}, h('h2', {}, '外观'), h('p', {
    class: 'muted'
  }, '选择适合当前环境的界面明暗。'))), themeControl.el, h('p', {
    class: 'muted'
  }, '立即生效，仅保存在当前浏览器。不改变 AI 服务设置或生成配置；跟随系统会自动响应系统的明暗变化。'));
  sections = [];
  for (const [id, label] of [['ai', 'AI 服务'], ['plugins', '插件与版本'], ['generation', '新建配置偏好'], ['appearance', '外观']]) {
    const tab = button(label, () => selectSection(id), {
      id: `settings-tab-${id}`,
      role: 'tab',
      'aria-controls': `settings-${id}`
    });
    tab.onkeydown = event => {
      const enabled = sections.filter(item => !item.button.disabled);
      const index = enabled.findIndex(item => item.id === id);
      if (index < 0) return;
      let target;
      if (event.key === 'Home') {
        target = 0;
      } else if (event.key === 'End') {
        target = enabled.length - 1;
      } else if (['ArrowDown', 'ArrowRight'].includes(event.key)) {
        target = (index + 1) % enabled.length;
      } else if (['ArrowUp', 'ArrowLeft'].includes(event.key)) {
        target = (index + enabled.length - 1) % enabled.length;
      } else {
        target = null;
      }
      if (target !== null) {
        event.preventDefault();
        selectSection(enabled[target].id);
        enabled[target].button.focus();
      }
    };
    sections.push({
      id,
      button: tab
    });
  }
  const returnInfo = peekAIHandoff(store.connId);
  returnButton = button('返回 AI 助手', goBack, {
    hidden: !returnInfo
  });
  returnPrompt = h('div', {
    class: 'settings-return-prompt',
    hidden: true,
    role: 'alert'
  }, h('p', {}, 'AI 服务设置尚未保存。可以继续编辑并保存，或放弃修改后返回。'), h('div', {
    class: 'settings-actions'
  }, button('继续编辑', () => {
    returnPrompt.hidden = true;
    modelInput.focus();
  }), button('放弃修改并返回', returnToAssistant)));
  root = h('div', {
    class: 'page settings-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('h1', {}, '设置'), h('p', {
    class: 'subtitle'
  }, '管理新建配置偏好、界面外观、AI 服务和扩展能力。')), returnButton), returnPrompt, h('div', {
    class: 'settings-layout'
  }, h('div', {
    class: 'settings-tabs',
    role: 'tablist',
    'aria-label': '设置分类',
    'aria-orientation': 'vertical'
  }, ...sections.map(item => item.button)), h('div', {
    class: 'settings-panels'
  }, aiPanel, pluginsPanel, generationPanel, appearancePanel)));
  selectSection(currentSection);
  setMaintenanceMode(management.maintenance);
  update();
  return root;
}
export async function mount() {
  const expected = version,
    current = management;
  await Promise.all([current.refresh(), refreshEnvironment()]);
  if (expected === version && !current.maintenance) {
    generationAllowed = true;
    if (currentSection === 'generation') generationControl.load();
    await loadSettings();
  }
}
export function unmount() {
  management?.destroy();
  themeControl?.destroy();
  generationControl?.destroy();
  updateControl?.destroy();
  invalidateInstallationCopies();
  version++;
  environmentVersion++;
  configController?.abort();
  environmentController?.abort();
  backend?.destroy();
  if (key) {
    key.value = '';
  }
  leaveAISettings(location.hash);
}
function selectSection(id) {
  if (id !== 'plugins' && management?.maintenance) {
    return;
  }
  if (currentSection !== id) {
    invalidateInstallationCopies();
  }
  const panels = {ai: aiPanel, plugins: pluginsPanel, generation: generationPanel, appearance: appearancePanel};
  const moveFocus = Object.entries(panels).some(([name, panel]) => name !== id && panel.contains(document.activeElement));
  // 浮层挂在 body；隐藏所属分区时须单独关闭，不能遗留可操作菜单。
  if (id !== 'ai') backend.close();
  if (id !== 'appearance') themeControl.close();
  if (id !== 'generation') generationControl.close();
  else if (generationAllowed) generationControl.load();
  currentSection = id;
  aiPanel.hidden = id !== 'ai';
  pluginsPanel.hidden = id !== 'plugins';
  appearancePanel.hidden = id !== 'appearance';
  generationPanel.hidden = id !== 'generation';
  for (const item of sections) {
    item.button.setAttribute('aria-selected', String(item.id === id));
    item.button.setAttribute('tabindex', item.id === id ? '0' : '-1');
  }
  if (moveFocus) sections.find(item => item.id === id).button.focus({preventScroll: true});
}
function setMaintenanceMode(enabled) {
  const generationTab = sections.find(item => item.id === 'generation');
  generationTab.button.disabled = enabled;
  updateControl.setDisabled(enabled);
  const aiTab = sections.find(item => item.id === 'ai');
  aiTab.button.disabled = enabled;
  aiTab.button.title = enabled ? '维护模式仅提供插件管理，重启普通模式后可配置 AI。' : '';
  const appearanceTab = sections.find(item => item.id === 'appearance');
  appearanceTab.button.disabled = enabled;
  appearanceTab.button.title = enabled ? '维护模式仅提供插件管理，恢复服务后可调整外观。' : '';
  if (enabled) {
    generationAllowed = false;
    configController?.abort();
    loaded = false;
    config = null;
    busy = false;
    key.value = '';
    selectSection('plugins');
    update();
    returnButton.hidden = true;
  }
}
function goBack() {
  if (busy) {
    return;
  }
  if (dirty()) {
    returnPrompt.hidden = false;
  } else {
    returnToAssistant();
  }
}
function returnToAssistant() {
  if (busy) {
    return;
  }
  const destination = requestAIReturn(store.connId);
  if (destination) {
    location.hash = destination;
  } else {
    returnPrompt.hidden = true;
    setNotice(notice, '原来的分析上下文已失效，请从工作台重新打开 AI 助手。', 'warning');
  }
}
function changed() {
  invalidateInstallationCopies();
  if (testNotice.textContent) {
    setNotice(testNotice, '设置已变化，请重新检测。');
  }
  models.replaceChildren();
  setNotice(notice, '');
  update();
}
function update() {
  const disabled = busy || settingsStale || !loaded || !config?.available;
  for (const input of [endpoint, modelInput, key, clearKey]) {
    input.disabled = disabled;
  }
  backend.el.querySelector('button').disabled = disabled;
  save.disabled = disabled || !dirty();
  probe.disabled = disabled;
  reset.disabled = disabled || !dirty();
  if (disabled) {
    saveState.textContent = '';
  } else if (dirty()) {
    saveState.textContent = '有未保存的修改；检测连接不会保存。';
  } else {
    saveState.textContent = '没有待保存的更改。可直接检测连接。';
  }
  save.title = !disabled && !dirty() ? '当前表单与生效设置一致，无需重复保存' : '';
  returnButton.disabled = busy;
  for (const option of models.querySelectorAll('button')) {
    option.disabled = disabled;
  }
  form.setAttribute('aria-busy', String(busy));
  updateConfigurationBadge();
  if (backend.get() === 'ollama') {
    serviceHint.textContent = 'Ollama 可连接本地或云端模型；本机服务地址不代表模型一定在本机运行。';
  } else if (backend.get() === 'lm_studio') {
    serviceHint.textContent = '填写 LM Studio 服务地址，并在服务中加载需要使用的模型。';
  } else {
    serviceHint.textContent = '使用提供方公布的 API 地址和模型 ID。OpenAI 兼容服务地址通常以 /v1 结尾。';
  }
  updateAuthenticationHint();
  function updateConfigurationBadge() {
    badge.dataset.state = !busy && loaded && (!config || config.availability_status === 'import_error') ? 'error' :
      !busy && loaded && (settingsStale || !config.available) ? 'warning' : '';
    if (settingsStale) {
      if (busy) {
        badge.textContent = '读取中';
      } else {
        badge.textContent = '待重新读取';
      }
    } else if (!loaded) {
      badge.textContent = '读取中';
    } else if (!config) {
      badge.textContent = '读取失败';
    } else if (!config.available) {
      if (config.availability_status === 'import_error') {
        badge.textContent = '加载异常';
      } else {
        badge.textContent = '未安装';
      }
    } else if (dirty()) {
      badge.textContent = '未保存';
    } else if (config.ready) {
      badge.textContent = '配置已填写';
    } else {
      badge.textContent = '待配置';
    }
  }
}
function updateAuthenticationHint() {
  const effective = config?.effective || {};
  const target = serviceIdentity(backend.get(), endpoint.value);
  const sameService = Boolean(target) && target === serviceIdentity(effective.backend, effective.base_url || '');
  const hasKey = sameService && effective.api_key_present;
  const local = ['ollama', 'lm_studio'].includes(backend.get());
  keyLabel.textContent = local ? 'API Key（通常无需填写）' : 'API Key（按服务要求填写）';
  if (hasKey) {
    key.placeholder = '留空保留同一服务的已配置密钥';
  } else if (local) {
    key.placeholder = '服务启用了认证时填写';
  } else {
    key.placeholder = '填写此服务的密钥';
  }
  if (hasKey) {
    keyHint.textContent = keySources[config.sources?.api_key] || keySources.session;
  } else if (local) {
    keyHint.textContent = '默认本地服务无需密钥，修改地址或模型后即可保存；启用认证时按服务要求填写。';
  } else {
    keyHint.textContent = '按提供方要求配置认证；不同服务之间不会沿用已配置的密钥。';
  }
  clearKey.closest('label').hidden = !hasKey;
}
function serviceIdentity(service, address) {
  let raw = address.trim() || defaults[service] || '';
  let end = raw.length;
  while (raw[end - 1] === '/') {
    end--;
  }
  raw = raw.slice(0, end);
  try {
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || /[\s\\]/.test(raw)) {
      return '';
    }
    // Keep the configured path: URL normalizes dot segments, while the server
    // binds credentials to the complete configured endpoint.
    const path = raw.match(/^https?:\/\/[^/]*(\/.*)?$/i)?.[1] || '';
    return JSON.stringify([service, url.protocol, url.hostname, url.port || (url.protocol === 'https:' ? '443' : '80'), path]);
  } catch {
    return '';
  }
}
function populate({
  preserveDraft = false
} = {}) {
  const effective = config.effective || {};
  if (!preserveDraft) {
    backend.set(effective.backend || 'ollama');
    endpoint.value = effective.base_url || '';
    modelInput.value = effective.model || '';
    key.value = '';
    clearKey.checked = false;
  }
  currentService.textContent = effective.model ? `${backends.find(item => item.value === effective.backend)?.label || effective.backend} · ${effective.model}` : '尚未选择默认模型';
  const serviceCard = currentService.closest('.settings-current');
  serviceCard.querySelector('span').textContent = config.available ? '当前使用' : '已保存的服务配置';
  serviceCard.setAttribute('aria-label', config.available ? '当前使用的 AI 服务' : '已保存的 AI 服务');
  readinessNote.textContent = config.available ? config.message || '配置状态与服务连通性分别检查。' : '';
  storageInfo.replaceChildren(h('summary', {}, '保存范围与有效期'), h('p', {}, '服务类型、地址和模型保存在运行 Web 的设备上，重启后仍保留。同一 Web 服务的浏览器共享这些设置；修改后用于下一次分析。'), h('p', {}, '界面填写的密钥仅在本次服务中有效；如需重启后继续使用，可在启动环境中配置。密钥不写入生成配置或运行记录。'), ...(config.storage?.path ? [h('div', {
    class: 'settings-storage-location'
  }, h('strong', {}, '当前 Web 服务的配置文件位置'), h('p', {
    class: 'mono'
  }, config.storage.path), h('p', {}, '按启动 Web 的用户和操作系统自动选择；也可通过 SQLSEED_WEB_SETTINGS_PATH 指定。远程访问时，这里是服务器上的位置。'))] : []));
  const installation = aiPanel.querySelector('[data-ai-install]');
  installation.hidden = Boolean(config.available);
  if (!config.available) {
    const broken = config.availability_status === 'import_error';
    const installationHelp = () => {
      if (!managedInstallAvailable(management?.controls({
        id: 'ai'
      })) || broken) {
        return [h('details', {
          class: 'settings-package-help'
        }, h('summary', {}, '管理员排查信息'), ...installationInstructions(config.installer, broken ? config.repair_command : config.install_command, broken ? config.repair_commands : config.install_commands))];
      } else {
        return [];
      }
    };
    installation.replaceChildren(h('h3', {}, broken ? 'AI 插件加载异常' : 'AI 扩展未安装'), h('p', {}, `${componentImpact('ai')} 已保存的服务设置会保留。`), ...(broken ? [h('p', {}, config.message || 'AI 插件已安装，但加载失败，请检查运行 Web 的环境依赖。')] : []), button(broken ? '查看插件状态' : '前往安装', () => selectSection('plugins'), {
      primary: true
    }), ...installationHelp());
  }
  form.hidden = !config.available;
  update();
}
async function loadSettings({
  preserveDraft = false
} = {}) {
  if (busy || management?.maintenance) {
    return;
  }
  preserveDraft ||= settingsStale && dirty();
  const expected = version,
    request = settingsVersion;
  const current = () => expected === version && request === settingsVersion;
  busy = true;
  configController = new AbortController();
  update();
  try {
    const response = await api(`${prefix}/config`, {
      signal: configController.signal
    });
    if (!current() || management?.maintenance) {
      return;
    }
    config = structuredClone(response);
    loaded = true;
    settingsStale = false;
    populate({
      preserveDraft
    });
    setNotice(notice, '');
  } catch (error) {
    if (current()) {
      loaded = true;
      notice.replaceChildren(`无法读取 AI 设置：${error.message} `, button('重试读取', loadSettings));
      notice.dataset.state = 'error';
    }
  } finally {
    if (current()) {
      busy = false;
      update();
    }
  }
}
async function submit(testOnly) {
  if (busy || settingsStale || management?.maintenance || !loaded || !config?.available || !testOnly && !dirty()) {
    return;
  }
  const expected = version,
    request = settingsVersion,
    snapshot = currentDraft();
  const current = () => expected === version && request === settingsVersion;
  busy = true;
  configController = new AbortController();
  update();
  showSubmissionProgress();
  try {
    const response = await api(`${prefix}/${testOnly ? 'test' : 'config'}`, {
      method: 'POST',
      body: JSON.stringify(snapshot),
      signal: configController.signal
    });
    if (!current() || management?.maintenance) {
      return;
    }
    applySettingsResponse(response);
  } catch (error) {
    if (current()) {
      setNotice(testOnly ? testNotice : notice, `${testOnly ? '检测' : '保存'}失败：${error.message}`, 'error');
    }
  } finally {
    snapshot.api_key = '';
    if (current()) {
      busy = false;
      probe.textContent = '检测连接';
      save.textContent = '保存设置';
      update();
    }
  }
  function showSubmissionProgress() {
    probe.textContent = testOnly ? '检测中…' : '检测连接';
    save.textContent = testOnly ? '保存设置' : '保存中…';
    if (testOnly) {
      setNotice(testNotice, '正在检测服务连接…');
      models.replaceChildren();
    } else {
      setNotice(notice, '正在保存设置…');
    }
  }
  function applySettingsResponse(response) {
    if (testOnly) {
      showConnectionProbe(response);
    } else {
      config = structuredClone(response);
      populate();
      returnPrompt.hidden = true;
      setNotice(notice, '设置已保存，下一次 AI 分析将使用此配置。', 'success');
      window.dispatchEvent(new Event('sqlseed:ai-settings-changed'));
    }
  }
}
async function refreshPlugins() {
  if (refreshButton.disabled) {
    return;
  }
  return Promise.all([management.refresh(), refreshEnvironment()]);
}
async function refreshCurrentConnection(expected) {
  const id = store.connId;
  if (!id) {
    return;
  }
  try {
    const response = await api('/api/connections');
    if (expected !== version || store.connId !== id || !response.connections?.some(item => item.conn_id === id)) {
      return;
    }
    const detail = await api(`/api/connections/${encodeURIComponent(id)}/tables`);
    if (expected === version && store.connId === id) {
      store.tables = detail.tables || [];
    }
  } catch {
    // Keep the selected target and its in-memory draft; never pick another database.
    if (expected === version) {
      setNotice(environmentNotice, '组件状态已刷新；当前数据库连接信息暂时无法更新。', 'warning');
    }
  }
}
async function refreshEnvironment({
  replace = false
} = {}) {
  if (environmentLoading && !replace) {
    return;
  }
  environmentController?.abort();
  invalidateInstallationCopies();
  const expected = version,
    request = ++environmentVersion;
  environmentController = new AbortController();
  environmentLoading = true;
  refreshButton.disabled = true;
  setNotice(environmentNotice, '正在读取组件状态…');
  try {
    const info = await api('/api/settings/environment', {
      signal: environmentController.signal
    });
    if (expected !== version || request !== environmentVersion) {
      return;
    }
    environmentInfo = info;
    renderEnvironment();
    setNotice(environmentNotice, '状态已更新。', 'success');
  } catch (error) {
    if (expected === version && request === environmentVersion) {
      setNotice(environmentNotice, `无法刷新组件状态：${error.message}`, 'error');
    }
  } finally {
    if (expected === version && request === environmentVersion) {
      environmentLoading = false;
      refreshButton.disabled = management.refreshBlocked;
    }
  }
}
function renderEnvironment() {
  if (!environmentInfo) {
    return;
  }
  const info = environmentInfo,
    packages = info.packages || [];
  environmentSummary.textContent = `${info.python?.implementation || 'Python'} ${info.python?.version || '版本未知'} · 当前 Web 服务环境`;
  const application = item => item.category ? item.category === 'application' : ['core', 'web'].includes(item.id);
  const group = (title, items) => h('section', {
    class: 'settings-package-group'
  }, h('h3', {}, title), ...items.map(item => packageRow(item, info.installer)));
  environmentList.replaceChildren(group('当前应用', packages.filter(application)), group('可选扩展', packages.filter(item => !application(item))), group('数据生成引擎', info.providers || []), h('p', {
    class: 'muted'
  }, management?.maintenance ? '版本来自当前安装环境；维护模式不加载组件。安装或卸载后需重启普通模式，再验证组件可用性。' : '版本来自当前安装环境，不表示最新发布版本。“可用”表示组件可加载；AI 服务需单独检测。生成引擎在工作台选择，可选扩展按需安装。'));
}
function updatePluginControls() {
  const items = [...(environmentInfo?.packages || []), ...(environmentInfo?.providers || [])];
  for (const row of environmentList.querySelectorAll('[data-package-id]')) {
    const item = items.find(value => value.id === row.dataset.packageId);
    const holder = row.querySelector('[data-plugin-controls]');
    const controls = item && management.controls(item);
    holder.replaceChildren(...(controls ? [controls] : []));
    const guide = row.querySelector('.settings-package-help');
    if (guide) {
      guide.hidden = !item?.installed && managedInstallAvailable(controls);
    }
  }
}
function managedInstallAvailable(controls) {
  return Boolean(management?.automatic && controls?.querySelector('[data-plugin-action="install"]'));
}
function installationInstructions(installer, command, variants = []) {
  const usable = installer?.available !== false && typeof command === 'string' && command;
  const message = installer?.message || (!usable ? '未提供可直接执行的命令。请使用创建此 Python 环境的工具安装或修复组件。' : '');
  return [...(message ? [h('p', {
    class: 'muted'
  }, message)] : []), ...(!usable && installer?.python_executable ? [h('p', {
    class: 'mono muted'
  }, `目标解释器：${installer.python_executable}`)] : []), h('p', {
    class: 'muted'
  }, `在运行 Web 的设备终端${installer?.shell === 'powershell' && (!Array.isArray(variants) || variants.length < 2) ? '（PowerShell）' : ''}操作，完成后重启 Web 并刷新状态。`), ...(usable ? [commandChoices(command, variants)] : [])];
}
function commandChoices(command, variants) {
  const choices = Array.isArray(variants) ? variants.filter(item => item && typeof item.command === 'string' && item.command && typeof item.shell === 'string' && item.label) : [];
  if (choices.length < 2) {
    return copyableCommand(command);
  }
  const current = choices.find(item => item.command === command) || choices[0];
  const name = `install-command-${++commandGroupSequence}`;
  const copyState = {copying: false, button: null};
  const hint = h('p', {class: 'muted'}, current.note || '');
  const output = h('div', {}, copyableCommand(current.command, copyState));
  const group = h('fieldset', {class: 'settings-command-options'}, h('legend', {}, '命令格式'));
  for (const item of choices) {
    const input = h('input', {type: 'radio', name, value: item.shell, checked: item === current,
      onchange: () => {
        if (!input.checked) return;
        hint.textContent = item.note || '';
        // Replacing the command also detaches any pending clipboard feedback.
        output.replaceChildren(copyableCommand(item.command, copyState));
      }});
    group.append(h('label', {}, input, h('span', {}, item.label)));
  }
  return h('div', {'data-command-choices': ''}, group, hint, output);
}
function invalidateInstallationCopies() {
  installationVersion++;
  for (const status of root?.querySelectorAll('[data-install-copy-status]') || []) {
    status.textContent = '';
  }
}
function copyableCommand(command, sharedCopyState) {
  const copyState = sharedCopyState ?? {copying: false, button: null};
  const ownerVersion = version;
  const status = h('span', {
    class: 'settings-copy-status muted',
    role: 'status',
    'aria-live': 'polite',
    'data-install-copy-status': ''
  });
  const copy = button('复制命令', async () => {
    if (copyState.copying || ownerVersion !== version || !container.isConnected) {
      return;
    }
    const expected = installationVersion;
    const current = () => ownerVersion === version && expected === installationVersion && container.isConnected;
    copyState.copying = true;
    copy.disabled = true;
    copy.textContent = '复制中…';
    status.textContent = '';
    try {
      const clipboard = globalThis.navigator?.clipboard;
      if (typeof clipboard?.writeText !== 'function') {
        status.textContent = '当前浏览器无法自动复制，请手动选择并复制上方命令。';
        return;
      }
      await clipboard.writeText(command);
      if (current()) {
        status.textContent = '已复制命令。';
      }
    } catch {
      if (current()) {
        status.textContent = '复制失败，请手动选择并复制上方命令。';
      }
    } finally {
      copyState.copying = false;
      if (ownerVersion === version && copyState.button?.isConnected) {
        copyState.button.disabled = false;
        copyState.button.textContent = '复制命令';
      }
    }
  }, {
    small: true,
    'data-install-copy': ''
  });
  copyState.button = copy;
  copy.disabled = copyState.copying;
  if (copyState.copying) copy.textContent = '复制中…';
  const container = h('div', {
    class: 'settings-command'
  }, h('code', {}, command), h('div', {
    class: 'settings-command-actions'
  }, copy, status));
  return container;
}
function packageRow(item, installer) {
  function defaultRequirement() {
    if (item.id === 'base') {
      return 'builtin';
    } else if (['core', 'web', 'faker'].includes(item.id)) {
      return 'required';
    } else {
      return 'optional';
    }
  }
  const requirement = item.requirement || defaultRequirement();
  const metadataOnly = environmentInfo?.inspection === 'metadata_only';
  const broken = !metadataOnly && !item.available && (item.installed || requirement === 'required' || requirement === 'builtin');
  const state = packageStateLabel();
  const requirementLabels = {
    builtin: '内置',
    required: '必需',
    optional: '可选'
  };
  const requirementLabel = {
    base: '内置',
    faker: '随 sqlseed 安装',
    mimesis: '按需安装'
  }[item.id] || requirementLabels[requirement];
  const controls = management?.controls(item);
  function packageBadgeClass() {
    if (broken) {
      return ' settings-badge-warning';
    } else if (!item.available) {
      return ' settings-badge-neutral';
    } else {
      return '';
    }
  }
  const row = h('article', {
    class: 'settings-package',
    'data-package-id': item.id
  }, h('div', {
    class: 'settings-package-info'
  }, h('div', {
    class: 'settings-package-name'
  }, h('strong', {}, item.name), h('span', {
    class: 'settings-requirement'
  }, requirementLabel)), item.distribution && requirement !== 'builtin' ? h('small', {
    class: 'settings-distribution mono'
  }, item.distribution) : null, h('p', {
    class: 'muted'
  }, item.description || descriptions[item.id] || item.message || ''), item.available && item.guidance ? h('p', {
    class: 'settings-dependency'
  }, item.guidance) : null, !metadataOnly && !item.available && componentImpact(item.id) ? h('p', {
    class: 'settings-component-impact',
    'data-component-impact': ''
  }, componentImpact(item.id)) : null), h('span', {
    class: 'mono settings-version'
  }, requirement === 'builtin' ? '随 sqlseed 提供' : item.version || '—'), h('div', {
    class: 'settings-package-status'
  }, h('span', {
    class: `settings-badge${packageBadgeClass()}`
  }, state)));
  if (!item.available && (!metadataOnly || !item.installed && requirement !== 'builtin')) {
    renderPackageHelp();
  }
  row.append(h('div', {
    'data-plugin-controls': ''
  }, controls));
  return row;
  function packageStateLabel() {
    let state;
    if (metadataOnly && requirement === 'builtin') {
      state = '内置';
    } else if (metadataOnly && item.installed) {
      state = '已安装（待验证）';
    } else if (item.available) {
      state = '可用';
    } else if (item.installed) {
      state = '加载异常';
    } else if (requirement === 'optional') {
      state = '未安装';
    } else {
      state = '必需依赖缺失';
    }
    return state;
  }
  function renderPackageHelp() {
    row.append(h('details', {
      class: 'settings-package-help',
      hidden: !item.installed && managedInstallAvailable(controls)
    }, h('summary', {}, broken ? '修复指引' : '管理员安装信息'), h('p', {}, item.guidance || item.message || '请在运行 Web 的 Python 环境中检查此组件。'), ...installationInstructions(installer, item.installed || requirement === 'builtin' ? item.repair_command : item.install_command, item.installed || requirement === 'builtin' ? item.repair_commands : item.install_commands)));
  }
}
function showConnectionProbe(response) {
  setNotice(testNotice, response.message || (response.ok ? '服务连接成功，仅验证模型列表。' : '连接检测失败。'), response.ok ? 'success' : 'error');
  if (response.ok) {
    for (const name of (response.models || []).slice(0, 30)) {
      models.append(button(name, () => {
        if (!busy) {
          modelInput.value = name;
          changed();
        }
      }, {
        small: true
      }));
    }
  }
}
