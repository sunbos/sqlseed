import {tr, joinText, setText, setAttr, appendContent, replaceContent, errorText, serverText} from '../i18n.js';
import '../i18n/messages/settings.js';
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
  label: tr('settings.openaiCompatible')
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
  session: tr('settings.sessionKey'),
  environment: tr('settings.environmentKey'),
  none: tr('settings.noKey')
};
const descriptions = {
  core: tr('settings.coreDescription'),
  cli: tr('settings.cliDescription'),
  web: tr('settings.webDescription'),
  ai: tr('settings.aiDescription'),
  mcp: tr('settings.mcpDescription'),
  base: tr('settings.baseDescription'),
  faker: tr('settings.fakerDescription'),
  mimesis: tr('settings.mimesisDescription')
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
  setText(element, text);
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
  }, tr('settings.loadingSettings'));
  saveState = h('p', {
    class: 'settings-save-state muted',
    role: 'status',
    'data-settings-save-state': ''
  });
  badge = h('span', {
    class: 'settings-badge'
  }, tr('settings.loading'));
  currentService = h('p', {
    class: 'settings-current-model'
  }, tr('settings.loadingService'));
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
    'aria-label': tr('settings.serviceModels')
  });
  modelInput = h('input', {
    type: 'text',
    'aria-label': tr('settings.modelName'),
    placeholder: tr('settings.modelPlaceholder'),
    maxlength: 200,
    autocomplete: 'off',
    oninput: changed
  });
  endpoint = h('input', {
    type: 'url',
    'aria-label': tr('settings.aiAddress'),
    placeholder: 'https://example.com/v1',
    maxlength: 2000,
    autocomplete: 'off',
    oninput: changed
  });
  key = h('input', {
    type: 'password',
    'aria-label': 'API Key',
    value: '',
    placeholder: tr('settings.newKey'),
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
    'aria-label': tr('settings.disableKey'),
    onchange: () => {
      if (clearKey.checked) {
        key.value = '';
      }
      changed();
    }
  });
  backend = createDropdown({
    label: tr('settings.aiService'),
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
  save = button(tr('settings.saveSettings'), () => submit(false), {
    primary: true
  });
  probe = button(tr('settings.probe'), () => submit(true));
  reset = button(tr('settings.revert'), () => {
    if (!busy && config) {
      populate();
      setNotice(testNotice, '');
      replaceContent(models);
      setNotice(notice, tr('settings.reverted'));
    }
  });
  storageInfo = h('details', {
    class: 'settings-storage'
  }, h('summary', {}, tr('settings.storageScope')));
  form = h('div', {
    class: 'settings-form'
  }, h('div', {
    class: 'settings-fields'
  }, field(tr('settings.aiService'), backend.el), field(tr('settings.serviceAddress'), endpoint)), serviceHint, field(tr('settings.defaultModel'), modelInput, tr('settings.probeHint')), testNotice, models, h('div', {
    class: 'settings-key'
  }, field(keyLabel, key), keyHint, h('label', {
    class: 'settings-clear-key'
  }, clearKey, tr('settings.disableSessionKey'))), h('div', {
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
  }, h('div', {}, h('h2', {}, tr('settings.aiService')), h('p', {
    class: 'muted'
  }, tr('settings.aiSubtitle'))), badge), h('section', {
    class: 'settings-current',
    'aria-label': tr('settings.currentAI')
  }, h('span', {
    class: 'muted'
  }, tr('settings.current')), currentService, readinessNote), installation, form, notice);
  environmentNotice = h('p', {
    class: 'settings-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  environmentSummary = h('p', {
    class: 'muted'
  }, tr('settings.loadingEnvironment'));
  environmentList = h('div', {
    class: 'settings-environment'
  });
  refreshButton = button(tr('settings.refreshStatus'), refreshPlugins, {
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
      setText(probe, tr('settings.probe'));
      setText(save, tr('settings.saveSettings'));
      setNotice(testNotice, '');
      replaceContent(models);
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
  }, h('div', {}, h('h2', {}, tr('settings.plugins')), h('p', {
    class: 'muted'
  }, tr('settings.pluginsSubtitle'))), refreshButton), management.el, updateControl.el, environmentSummary, environmentNotice, environmentList);
  generationControl = createGenerationDefaultsControl();
  generationPanel = h('section', {id: 'settings-generation', class: 'settings-panel', role: 'tabpanel', 'aria-labelledby': 'settings-tab-generation'},
    h('header', {class: 'settings-panel-head'}, h('div', {}, h('h2', {}, tr('settings.generation')), h('p', {class: 'muted'}, tr('settings.generationSubtitle')))), generationControl.el);
  themeControl = createThemeControl();
  appearancePanel = h('section', {
    id: 'settings-appearance',
    class: 'settings-panel',
    role: 'tabpanel',
    'aria-labelledby': 'settings-tab-appearance'
  }, h('header', {
    class: 'settings-panel-head'
  }, h('div', {}, h('h2', {}, tr('settings.appearance')), h('p', {
    class: 'muted'
  }, tr('settings.appearanceSubtitle')))), themeControl.el, h('p', {
    class: 'muted'
  }, tr('settings.appearanceHint')));
  sections = [];
  for (const [id, label] of [['ai', tr('settings.aiService')], ['plugins', tr('settings.plugins')], ['generation', tr('settings.generation')], ['appearance', tr('settings.appearance')]]) {
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
  returnButton = button(tr('settings.returnAI'), goBack, {
    hidden: !returnInfo
  });
  returnPrompt = h('div', {
    class: 'settings-return-prompt',
    hidden: true,
    role: 'alert'
  }, h('p', {}, tr('settings.unsavedReturn')), h('div', {
    class: 'settings-actions'
  }, button(tr('settings.continueEditing'), () => {
    returnPrompt.hidden = true;
    modelInput.focus();
  }), button(tr('settings.discardReturn'), returnToAssistant)));
  root = h('div', {
    class: 'page settings-page'
  }, h('header', {
    class: 'heading'
  }, h('div', {}, h('h1', {}, tr('settings.title')), h('p', {
    class: 'subtitle'
  }, tr('settings.subtitle'))), returnButton), returnPrompt, h('div', {
    class: 'settings-layout'
  }, h('div', {
    class: 'settings-tabs',
    role: 'tablist',
    'aria-label': tr('settings.categories'),
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
    setAttr(item.button, 'aria-selected', String(item.id === id));
    setAttr(item.button, 'tabindex', item.id === id ? '0' : '-1');
  }
  if (moveFocus) sections.find(item => item.id === id).button.focus({preventScroll: true});
}
function setMaintenanceMode(enabled) {
  const generationTab = sections.find(item => item.id === 'generation');
  generationTab.button.disabled = enabled;
  updateControl.setDisabled(enabled);
  const aiTab = sections.find(item => item.id === 'ai');
  aiTab.button.disabled = enabled;
  setAttr(aiTab.button, 'title', enabled ? tr('settings.maintenanceAI') : '');
  const appearanceTab = sections.find(item => item.id === 'appearance');
  appearanceTab.button.disabled = enabled;
  setAttr(appearanceTab.button, 'title', enabled ? tr('settings.maintenanceAppearance') : '');
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
    setNotice(notice, tr('settings.expiredContext'), 'warning');
  }
}
function changed() {
  invalidateInstallationCopies();
  if (testNotice.textContent) {
    setNotice(testNotice, tr('settings.retest'));
  }
  replaceContent(models);
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
    setText(saveState, '');
  } else if (dirty()) {
    setText(saveState, tr('settings.unsaved'));
  } else {
    setText(saveState, tr('settings.noChanges'));
  }
  setAttr(save, 'title', !disabled && !dirty() ? tr('settings.alreadySaved') : '');
  returnButton.disabled = busy;
  for (const option of models.querySelectorAll('button')) {
    option.disabled = disabled;
  }
  setAttr(form, 'aria-busy', String(busy));
  updateConfigurationBadge();
  if (backend.get() === 'ollama') {
    setText(serviceHint, tr('settings.ollamaHint'));
  } else if (backend.get() === 'lm_studio') {
    setText(serviceHint, tr('settings.lmStudioHint'));
  } else {
    setText(serviceHint, tr('settings.compatibleHint'));
  }
  updateAuthenticationHint();
  function updateConfigurationBadge() {
    badge.dataset.state = !busy && loaded && (!config || config.availability_status === 'import_error') ? 'error' :
      !busy && loaded && (settingsStale || !config.available) ? 'warning' : '';
    if (settingsStale) {
      if (busy) {
        setText(badge, tr('settings.loading'));
      } else {
        setText(badge, tr('settings.reloadNeeded'));
      }
    } else if (!loaded) {
      setText(badge, tr('settings.loading'));
    } else if (!config) {
      setText(badge, tr('settings.loadFailed'));
    } else if (!config.available) {
      if (config.availability_status === 'import_error') {
        setText(badge, tr('settings.importError'));
      } else {
        setText(badge, tr('settings.notInstalled'));
      }
    } else if (dirty()) {
      setText(badge, tr('settings.unsavedBadge'));
    } else if (config.ready) {
      setText(badge, tr('settings.configured'));
    } else {
      setText(badge, tr('settings.notConfigured'));
    }
  }
}
function updateAuthenticationHint() {
  const effective = config?.effective || {};
  const target = serviceIdentity(backend.get(), endpoint.value);
  const sameService = Boolean(target) && target === serviceIdentity(effective.backend, effective.base_url || '');
  const hasKey = sameService && effective.api_key_present;
  const local = ['ollama', 'lm_studio'].includes(backend.get());
  setText(keyLabel, local ? tr('settings.localKey') : tr('settings.serviceKey'));
  if (hasKey) {
    setAttr(key, 'placeholder', tr('settings.keepKey'));
  } else if (local) {
    setAttr(key, 'placeholder', tr('settings.authKey'));
  } else {
    setAttr(key, 'placeholder', tr('settings.enterServiceKey'));
  }
  if (hasKey) {
    setText(keyHint, keySources[config.sources?.api_key] || keySources.session);
  } else if (local) {
    setText(keyHint, tr('settings.localAuthHint'));
  } else {
    setText(keyHint, tr('settings.remoteAuthHint'));
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
  setText(currentService, effective.model ? joinText([backends.find(item => item.value === effective.backend)?.label || effective.backend, " · ", effective.model]) : tr('settings.noDefaultModel'));
  const serviceCard = currentService.closest('.settings-current');
  setText(serviceCard.querySelector('span'), config.available ? tr('settings.current') : tr('settings.savedService'));
  setAttr(serviceCard, 'aria-label', config.available ? tr('settings.currentAI') : tr('settings.savedAI'));
  setText(readinessNote, config.available ? serverText(config) || tr('settings.readinessHint') : '');
  replaceContent(storageInfo, h('summary', {}, tr('settings.storageScope')), h('p', {}, tr('settings.sharedSettings')), h('p', {}, tr('settings.keyStorage')), ...(config.storage?.path ? [h('div', {
    class: 'settings-storage-location'
  }, h('strong', {}, tr('settings.settingsPath')), h('p', {
    class: 'mono'
  }, config.storage.path), h('p', {}, tr('settings.settingsPathHint')))] : []));
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
        }, h('summary', {}, tr('settings.adminDiagnostics')), ...installationInstructions(config.installer, broken ? config.repair_command : config.install_command, broken ? config.repair_commands : config.install_commands))];
      } else {
        return [];
      }
    };
    replaceContent(installation, h('h3', {}, broken ? tr('settings.aiImportError') : tr('settings.aiMissing')), h('p', {}, tr('settings.retainedSettings', {impact: componentImpact('ai')})), ...(broken ? [h('p', {}, serverText(config) || tr('settings.aiDependencyHint'))] : []), button(broken ? tr('settings.viewPluginStatus') : tr('settings.installAction'), () => selectSection('plugins'), {
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
      replaceContent(notice, tr('settings.loadError', {detail: errorText(error)}), button(tr('settings.retryLoad'), loadSettings));
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
      setNotice(testOnly ? testNotice : notice, tr('settings.submitError', {operation: testOnly ? tr('settings.testVerb') : tr('settings.saveVerb'), detail: errorText(error)}), 'error');
    }
  } finally {
    snapshot.api_key = '';
    if (current()) {
      busy = false;
      setText(probe, tr('settings.probe'));
      setText(save, tr('settings.saveSettings'));
      update();
    }
  }
  function showSubmissionProgress() {
    setText(probe, testOnly ? tr('settings.testing') : tr('settings.probe'));
    setText(save, testOnly ? tr('settings.saveSettings') : tr('settings.saving'));
    if (testOnly) {
      setNotice(testNotice, tr('settings.testingConnection'));
      replaceContent(models);
    } else {
      setNotice(notice, tr('settings.savingSettings'));
    }
  }
  function applySettingsResponse(response) {
    if (testOnly) {
      showConnectionProbe(response);
    } else {
      config = structuredClone(response);
      populate();
      returnPrompt.hidden = true;
      setNotice(notice, tr('settings.saved'), 'success');
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
      setNotice(environmentNotice, tr('settings.connectionRefreshFailed'), 'warning');
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
  setNotice(environmentNotice, tr('settings.loadingComponents'));
  try {
    const info = await api('/api/settings/environment', {
      signal: environmentController.signal
    });
    if (expected !== version || request !== environmentVersion) {
      return;
    }
    environmentInfo = info;
    renderEnvironment();
    setNotice(environmentNotice, tr('settings.statusUpdated'), 'success');
  } catch (error) {
    if (expected === version && request === environmentVersion) {
      setNotice(environmentNotice, tr('settings.refreshError', {detail: errorText(error)}), 'error');
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
  setText(environmentSummary, tr('settings.environmentSummary', {implementation: info.python?.implementation || 'Python', version: info.python?.version || tr('settings.unknownVersion')}));
  const application = item => item.category ? item.category === 'application' : ['core', 'web'].includes(item.id);
  const group = (title, items) => h('section', {
    class: 'settings-package-group'
  }, h('h3', {}, title), ...items.map(item => packageRow(item, info.installer)));
  replaceContent(environmentList, group(tr('settings.application'), packages.filter(application)), group(tr('settings.optionalExtensions'), packages.filter(item => !application(item))), group(tr('settings.engines'), info.providers || []), h('p', {
    class: 'muted'
  }, management?.maintenance ? tr('settings.maintenanceVersions') : tr('settings.installedVersions')));
}
function updatePluginControls() {
  const items = [...(environmentInfo?.packages || []), ...(environmentInfo?.providers || [])];
  for (const row of environmentList.querySelectorAll('[data-package-id]')) {
    const item = items.find(value => value.id === row.dataset.packageId);
    const holder = row.querySelector('[data-plugin-controls]');
    const controls = item && management.controls(item);
    replaceContent(holder, ...(controls ? [controls] : []));
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
  const message = serverText(installer) || (!usable ? tr('settings.noInstallCommand') : '');
  return [...(message ? [h('p', {
    class: 'muted'
  }, message)] : []), ...(!usable && installer?.python_executable ? [h('p', {
    class: 'mono muted'
  }, tr('settings.targetInterpreter', {interpreter: installer.python_executable}))] : []), h('p', {
    class: 'muted'
  }, tr('settings.terminalInstructions', {shell: installer?.shell === 'powershell' && (!Array.isArray(variants) || variants.length < 2) ? ' (PowerShell)' : ''})), ...(usable ? [commandChoices(command, variants)] : [])];
}
function commandChoices(command, variants) {
  const choices = Array.isArray(variants) ? variants.filter(item => item && typeof item.command === 'string' && item.command && typeof item.shell === 'string' && item.label) : [];
  if (choices.length < 2) {
    return copyableCommand(command);
  }
  const current = choices.find(item => item.command === command) || choices[0];
  const name = `install-command-${++commandGroupSequence}`;
  const copyState = {copying: false, button: null};
  const hint = h('p', {class: 'muted'}, serverText(current, 'note') || '');
  const output = h('div', {}, copyableCommand(current.command, copyState));
  const group = h('fieldset', {class: 'settings-command-options'}, h('legend', {}, tr('settings.commandFormat')));
  for (const item of choices) {
    const input = h('input', {type: 'radio', name, value: item.shell, checked: item === current,
      onchange: () => {
        if (!input.checked) return;
        setText(hint, serverText(item, 'note') || '');
        // Replacing the command also detaches any pending clipboard feedback.
        replaceContent(output, copyableCommand(item.command, copyState));
      }});
    appendContent(group, h('label', {}, input, h('span', {}, serverText(item, 'label'))));
  }
  return h('div', {'data-command-choices': ''}, group, hint, output);
}
function invalidateInstallationCopies() {
  installationVersion++;
  for (const status of root?.querySelectorAll('[data-install-copy-status]') || []) {
    setText(status, '');
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
  const copy = button(tr('settings.copyCommand'), async () => {
    if (copyState.copying || ownerVersion !== version || !container.isConnected) {
      return;
    }
    const expected = installationVersion;
    const current = () => ownerVersion === version && expected === installationVersion && container.isConnected;
    copyState.copying = true;
    copy.disabled = true;
    setText(copy, tr('settings.copying'));
    setText(status, '');
    try {
      const clipboard = globalThis.navigator?.clipboard;
      if (typeof clipboard?.writeText !== 'function') {
        setText(status, tr('settings.copyUnavailable'));
        return;
      }
      await clipboard.writeText(command);
      if (current()) {
        setText(status, tr('settings.commandCopied'));
      }
    } catch {
      if (current()) {
        setText(status, tr('settings.copyFailed'));
      }
    } finally {
      copyState.copying = false;
      if (ownerVersion === version && copyState.button?.isConnected) {
        copyState.button.disabled = false;
        setText(copyState.button, tr('settings.copyCommand'));
      }
    }
  }, {
    small: true,
    'data-install-copy': ''
  });
  copyState.button = copy;
  copy.disabled = copyState.copying;
  if (copyState.copying) setText(copy, tr('settings.copying'));
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
    builtin: tr('settings.builtin'),
    required: tr('settings.required'),
    optional: tr('settings.optional')
  };
  const requirementLabel = {
    base: tr('settings.builtin'),
    faker: tr('settings.installedWithCore'),
    mimesis: tr('settings.installOnDemand')
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
  }, serverText(item, 'description') || descriptions[item.id] || serverText(item) || ''), item.available && item.guidance ? h('p', {
    class: 'settings-dependency'
  }, serverText(item, 'guidance')) : null, !metadataOnly && !item.available && componentImpact(item.id) ? h('p', {
    class: 'settings-component-impact',
    'data-component-impact': ''
  }, componentImpact(item.id)) : null), h('span', {
    class: 'mono settings-version'
  }, requirement === 'builtin' ? tr('settings.providedByCore') : item.version || '—'), h('div', {
    class: 'settings-package-status'
  }, h('span', {
    class: `settings-badge${packageBadgeClass()}`
  }, state)));
  if (!item.available && (!metadataOnly || !item.installed && requirement !== 'builtin')) {
    renderPackageHelp();
  }
  appendContent(row, h('div', {
    'data-plugin-controls': ''
  }, controls));
  return row;
  function packageStateLabel() {
    let state;
    if (metadataOnly && requirement === 'builtin') {
      state = tr('settings.builtin');
    } else if (metadataOnly && item.installed) {
      state = tr('settings.installedUnverified');
    } else if (item.available) {
      state = tr('settings.available');
    } else if (item.installed) {
      state = tr('settings.importError');
    } else if (requirement === 'optional') {
      state = tr('settings.notInstalled');
    } else {
      state = tr('settings.requiredMissing');
    }
    return state;
  }
  function renderPackageHelp() {
    appendContent(row, h('details', {
      class: 'settings-package-help',
      hidden: !item.installed && managedInstallAvailable(controls)
    }, h('summary', {}, broken ? tr('settings.repairGuide') : tr('settings.adminInstall')), h('p', {}, serverText(item, 'guidance') || serverText(item) || tr('settings.checkEnvironment')), ...installationInstructions(installer, item.installed || requirement === 'builtin' ? item.repair_command : item.install_command, item.installed || requirement === 'builtin' ? item.repair_commands : item.install_commands)));
  }
}
function showConnectionProbe(response) {
  setNotice(testNotice, serverText(response) || (response.ok ? tr('settings.probeSuccess') : tr('settings.probeFailed')), response.ok ? 'success' : 'error');
  if (response.ok) {
    for (const name of (response.models || []).slice(0, 30)) {
      appendContent(models, button(name, () => {
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
