// UI language is a browser preference, independent of the generation locale.
// Only explicitly bound presentation values change; no DOM scan or page remount.
export const LANGUAGE_KEY = 'sqlseed.ui.language';
export const UI_LANGUAGES = Object.freeze(['zh-CN', 'en']);
const messages = new Map();
const messageLoads = new Map();
const missing = new Set();
const listeners = new Set();
const bindings = new WeakMap();
const targets = new Set();
const finalizer = typeof FinalizationRegistry === 'function'
  ? new FinalizationRegistry(reference => targets.delete(reference)) : null;

export function browserLanguage(languages = globalThis.navigator?.languages) {
  const preferred = Array.isArray(languages) ? languages : [globalThis.navigator?.language];
  for (const value of preferred) {
    if (typeof value !== 'string') continue;
    if (/^zh(?:-|$)/i.test(value)) return 'zh-CN';
    if (/^en(?:-|$)/i.test(value)) return 'en';
  }
  return 'en';
}

function savedLanguage() {
  try {
    const value = globalThis.localStorage?.getItem(LANGUAGE_KEY);
    if (UI_LANGUAGES.includes(value)) return value;
  } catch { /* A blocked browser store must not prevent local language selection. */ }
  return browserLanguage();
}

let language = savedLanguage();
export function getLanguage() { return language; }
export function getFormatLocale() { return language === 'en' ? 'en-US' : 'zh-CN'; }

function updateDocumentLanguage() {
  globalThis.document?.documentElement?.setAttribute('lang', language);
}
updateDocumentLanguage();

export function setLanguage(value, {persist = true} = {}) {
  if (!UI_LANGUAGES.includes(value)) return false;
  if (persist) {
    try { globalThis.localStorage?.setItem(LANGUAGE_KEY, value); }
    catch { /* Keep the in-memory preference for this page. */ }
  }
  if (language === value) return true;
  language = value;
  updateDocumentLanguage();
  for (const reference of targets) {
    const target = reference.deref();
    if (!target) { targets.delete(reference); continue; }
    for (const apply of bindings.get(target)?.values() || []) apply(target);
  }
  // A listener may subscribe or unsubscribe while this notification is running.
  const notificationListeners = [...listeners];
  for (const listener of notificationListeners) listener(language);
  return true;
}

export function onLanguageChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

globalThis.window?.addEventListener?.('storage', event => {
  if (event.key === LANGUAGE_KEY || event.key === null) {
    let value = event.newValue;
    try {
      const storage = globalThis.localStorage;
      if (event.storageArea && storage && event.storageArea !== storage) return;
      if (storage) value = storage.getItem(LANGUAGE_KEY);
    } catch { /* A blocked store may still deliver a usable event preference. */ }
    setLanguage(UI_LANGUAGES.includes(value) ? value : browserLanguage(), {persist: false});
  }
});

/** Entries are [Simplified Chinese, English], optionally with plural forms. */
export function registerMessages(namespace, entries) {
  for (const [name, entry] of Object.entries(entries)) {
    const key = `${namespace}.${name}`;
    if (messages.has(key)) throw new Error(`Duplicate UI message: ${key}`);
    messages.set(key, entry);
  }
}

function isMessageTemplate(value) {
  if (typeof value === 'string') return value.length > 0;
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && typeof value.other === 'string'
    && Object.values(value).every(template => typeof template === 'string' && template.length > 0);
}

function validateMessageCatalog(catalog) {
  if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog) || Object.keys(catalog).length === 0) {
    throw new Error('UI language resource must contain namespaces');
  }
  const groups = Object.entries(catalog);
  for (const [namespace, entries] of groups) {
    if (!/^[A-Za-z]\w*$/.test(namespace) || !entries || typeof entries !== 'object'
      || Array.isArray(entries) || Object.keys(entries).length === 0) {
      throw new Error(`Invalid UI message namespace: ${namespace}`);
    }
    for (const [name, pair] of Object.entries(entries)) {
      const key = `${namespace}.${name}`;
      if (messages.has(key)) throw new Error(`Duplicate UI message: ${key}`);
      if (!Array.isArray(pair) || pair.length !== UI_LANGUAGES.length || !pair.every(isMessageTemplate)) {
        throw new Error(`Invalid UI message: ${key}`);
      }
    }
  }
  return groups;
}

async function fetchMessageFile(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`UI messages: HTTP ${response.status}`);
  return response.json();
}

/** Load a local JSON catalog once; switching language never requests assets. */
export function loadMessages(url) {
  const resource = String(url);
  if (!messageLoads.has(resource)) {
    const pending = fetchMessageFile(resource).then(catalog => {
      // Validate the whole resource before publishing any entries.
      const groups = validateMessageCatalog(catalog);
      for (const [namespace, entries] of groups) registerMessages(namespace, entries);
    }).catch(cause => {
      const error = new UserFacingError(tr('common.languageResourcesFailed'), {cause});
      const app = globalThis.document?.getElementById?.('app');
      if (app && app.childNodes.length === 0) {
        const notice = globalThis.document.createElement('p');
        notice.setAttribute('role', 'alert');
        setText(notice, error.localizedMessage);
        app.append(notice);
      }
      throw error;
    });
    messageLoads.set(resource, pending);
  }
  return messageLoads.get(resource);
}

export function messageEntries() { return [...messages.entries()]; }
export function missingMessages() { return [...missing]; }

export class LocalizedText {
  constructor(format) { this.format = format; Object.freeze(this); }
  toString() { return String(this.format(language)); }
  [Symbol.toPrimitive]() { return this.toString(); }
}

export function isLocalized(value) { return value instanceof LocalizedText; }
export function liveText(format) { return new LocalizedText(format); }
export function textValue(value) { return value == null ? '' : String(value); }

function templateText(template, params) {
  if (template && typeof template === 'object') {
    const count = Number(params.count);
    const form = new Intl.PluralRules(getFormatLocale()).select(count);
    template = template[form] ?? template.other;
  }
  return String(template).replace(/\{([A-Za-z]\w*)\}/g, (whole, key) =>
    Object.hasOwn(params, key) ? textValue(params[key]) : whole);
}

export function t(key, params = {}) {
  const entry = messages.get(key);
  if (!entry) {
    missing.add(key);
    return language === 'en' ? 'Translation unavailable' : '翻译暂不可用';
  }
  const template = entry[language === 'en' ? 1 : 0] ?? entry[1] ?? entry[0];
  return templateText(template, params);
}

export function tr(key, params = {}) {
  // Keep values, including identifiers, opaque. Only the template is translated.
  return liveText(() => t(key, params));
}

export function joinText(values, separator = '') {
  return liveText(() => values.map(textValue).join(textValue(separator)));
}

export function formatNumber(value, options = {}) {
  return liveText(() => new Intl.NumberFormat(getFormatLocale(), options).format(value));
}

export function formatDate(value, options = {}) {
  return liveText(() => {
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? textValue(value)
      : new Intl.DateTimeFormat(getFormatLocale(), options).format(date);
  });
}

function bind(target, slot, apply) {
  let registered = bindings.get(target);
  if (!registered && !apply) return;
  if (!registered) {
    registered = new Map();
    bindings.set(target, registered);
    const reference = new WeakRef(target);
    targets.add(reference);
    finalizer?.register(target, reference);
  }
  if (apply) { registered.set(slot, apply); apply(target); }
  else registered.delete(slot);
}

export function localizedNode(value, ownerDocument = globalThis.document) {
  if (value?.nodeType) return value;
  const node = ownerDocument.createTextNode(textValue(value));
  if (isLocalized(value)) bind(node, 'text', target => {
    const next = textValue(value);
    if (target.textContent !== next) target.textContent = next;
  });
  return node;
}

export function setText(element, value) {
  if (!element) return;
  if (element.nodeType === 3) {
    bind(element, 'text', isLocalized(value) ? target => { target.textContent = textValue(value); } : null);
    element.textContent = textValue(value);
  } else {
    element.replaceChildren(localizedNode(value, element.ownerDocument || globalThis.document));
  }
}

export function setAttr(element, name, value) {
  if (!element) return;
  bind(element, `attr:${name}`, isLocalized(value) ? target => {
    const next = textValue(value);
    if (target.getAttribute(name) !== next) target.setAttribute(name, next);
  } : null);
  if (value === null || value === undefined) element.removeAttribute(name);
  else element.setAttribute(name, textValue(value));
}

export function appendContent(element, ...values) {
  element.append(...values.flat(Infinity).filter(value => value != null)
    .map(value => localizedNode(value, element.ownerDocument || globalThis.document)));
}

export function replaceContent(element, ...values) {
  element.replaceChildren(...values.flat(Infinity).filter(value => value != null)
    .map(value => localizedNode(value, element.ownerDocument || globalThis.document)));
}

export class UserFacingError extends Error {
  constructor(message, {originalMessage = message, ...options} = {}) {
    // Keep the original API diagnostic available to existing error consumers.
    // Only the presentation value follows the current interface language.
    super(textValue(originalMessage), options);
    this.localizedMessage = diagnosticText(message);
  }
}

export function errorText(error) {
  if (isLocalized(error)) return error;
  if (error?.localizedMessage) return error.localizedMessage;
  return tr('common.diagnostic', {detail: error?.message || textValue(error)});
}

function serverParam(value) {
  if (value && typeof value === 'object' && typeof value.message_key === 'string') {
    return serverText(value);
  }
  return value;
}

function diagnosticText(value) {
  return value === '' || value == null || isLocalized(value)
    ? value : tr('common.rawDiagnostic', {detail: value});
}

/** Use only for known response presentation fields, never for user row values. */
export function serverText(record, field = 'message') {
  const key = record?.[`${field}_key`];
  if (typeof key !== 'string' || !key.startsWith('backend.')) return diagnosticText(record?.[field] ?? '');
  const supplied = record[`${field}_params`] || {};
  if (key === 'backend.message_list' && Array.isArray(supplied.items)) {
    return joinText(supplied.items.map(serverParam), supplied.separator ?? '; ');
  }
  const params = Object.fromEntries(Object.entries(supplied)
    .map(([name, value]) => [name, serverParam(value)]));
  return liveText(() => messages.has(key) ? t(key, params)
    : t('common.rawDiagnostic', {detail: record[field] ?? key}));
}

export function serverMessages(record, field) {
  return (record?.[field] || []).map((value, index) => {
    const descriptor = record[`${field}_i18n`]?.[index];
    if (descriptor) return serverText({message: value, message_key: descriptor.key, message_params: descriptor.params});
    if (typeof value === 'string' || isLocalized(value)) return diagnosticText(value);
    return value;
  });
}

let backendMessagesPromise;
export function loadBackendMessages() {
  backendMessagesPromise ??= fetchMessageFile('/static/i18n/backend-messages.json').then(entries => {
    registerMessages('backend', Object.fromEntries(Object.entries(entries)
      .map(([key, value]) => [key.replace(/^backend\./, ''), value])));
  }).catch(() => {
    // Keep the UI usable with original diagnostic text if an asset fails.
    // Language changes never retry requests or affect business operations.
  });
  return backendMessagesPromise;
}

registerMessages('common', {
  languageResourcesFailed: ['界面语言资源加载失败，请重新加载页面。', 'Interface language resources could not be loaded. Reload the page to try again.'],
  diagnostic: ['操作未完成。详细信息：{detail}', 'The operation could not be completed. Details: {detail}'],
  rawDiagnostic: ['诊断详情：{detail}', 'Details: {detail}'],
  cancel: ['取消', 'Cancel'],
  close: ['关闭', 'Close'],
  retry: ['重试', 'Retry'],
  save: ['保存', 'Save'],
  loading: ['正在加载…', 'Loading…'],
});
