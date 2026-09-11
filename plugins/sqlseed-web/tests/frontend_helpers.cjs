// Browser boundaries for Node regressions. Application functions run from the
// real source files; only DOM/network/timer surfaces are supplied by each test.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div', text = '') {
    this.tagName = tag.toUpperCase();
    this.nodeType = tag === '#text' ? 3 : 1;
    this._text = text;
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = {};
    this.style = {};
    this.listeners = new Map();
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.className = '';
    this.dataset = {};
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(' '); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter((n) => !names.includes(n)).join(' '); },
      toggle: (name, force) => {
        const on = force ?? !this.classList.contains(name);
        this.classList[on ? 'add' : 'remove'](name);
        return on;
      },
    };
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes.at(-1) || null; }
  get parentElement() { return this.parentNode; }
  get textContent() { return this._text + this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(text) { this.replaceChildren(); this._text = String(text ?? ''); }
  get innerHTML() { return this.textContent; }
  set innerHTML(text) { this.textContent = text; }
  get isConnected() { return this._connected || !!this.parentNode?.isConnected; }
  append(...nodes) {
    for (let node of nodes) {
      if (!(node instanceof Element)) node = new Element('#text', String(node));
      node.remove();
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }
  appendChild(node) { this.append(node); return node; }
  insertBefore(node, reference = null) {
    if (!(node instanceof Element)) throw new TypeError('The inserted value must be a Node');
    if (reference !== null && reference.parentNode !== this) throw new Error('The reference node is not a child of this parent');
    if (node.contains(this)) throw new Error('A node cannot be inserted into its descendant');
    if (node === reference) return node;
    if (reference === null) return this.appendChild(node);
    node.remove();
    node.parentNode = this;
    this.childNodes.splice(this.childNodes.indexOf(reference), 0, node);
    return node;
  }
  replaceChildren(...nodes) {
    for (const node of this.childNodes) node.parentNode = null;
    this.childNodes = [];
    this._text = '';
    this.append(...nodes);
  }
  removeChild(node) { node.remove(); return node; }
  remove() {
    if (this.parentNode) {
      this.parentNode.childNodes = this.parentNode.childNodes.filter((n) => n !== this);
      this.parentNode = null;
    }
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'id' || name === 'type') this[name] = String(value);
    if (name === 'disabled') this.disabled = true;
    if (name.startsWith('data-')) this.dataset[name.slice(5)] = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === 'disabled') this.disabled = false;
  }
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }
  removeEventListener(name, callback) { this.listeners.get(name)?.delete(callback); }
  async dispatchEvent(event) {
    event = typeof event === 'string' ? {type: event} : event;
    event.target ||= this;
    event.stopPropagation ||= () => {};
    event.preventDefault ||= () => {};
    await this['on' + event.type]?.(event);
    for (const callback of this.listeners.get(event.type) || []) await callback(event);
  }
  async click() {
    if (this.disabled) return;
    if (this.type === 'checkbox') this.checked = !this.checked;
    await this.dispatchEvent('click');
  }
  focus() {}
  contains(other) { return this === other || this.childNodes.some((n) => n.contains(other)); }
  matches(selector) {
    if (selector.includes(',')) return selector.split(',').some((s) => this.matches(s.trim()));
    const attrs = [...selector.matchAll(/\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g)];
    for (const [, key, value] of attrs) {
      const actual = this.getAttribute(key) ?? this[key];
      if (value === undefined ? actual === undefined || actual === null : String(actual) !== value) return false;
    }
    selector = selector.replace(/\[[^\]]+\]/g, '');
    const id = selector.match(/#([\w-]+)/)?.[1];
    if (id && this.id !== id) return false;
    for (const [, name] of selector.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(name)) return false;
    const tag = selector.match(/^[\w-]+/)?.[0];
    return !tag || this.tagName === tag.toUpperCase();
  }
  querySelectorAll(selector) {
    const result = [];
    for (const node of this.childNodes) {
      if (node.nodeType !== 1) continue;
      if (node.matches(selector)) result.push(node);
      result.push(...node.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
  getBoundingClientRect() { return {top: 0, bottom: 100, left: 0, right: 100}; }
}

function createDom() {
  const document = new Element('document');
  document._connected = true;
  document.body = new Element('body');
  document.documentElement = new Element('html');
  document.scrollingElement = document.documentElement;
  document.documentElement.scrollTop = 0;
  document.documentElement.scrollLeft = 0;
  document.append(document.documentElement);
  document.documentElement.append(document.body);
  document.createElement = (tag) => new Element(tag);
  document.createTextNode = (text) => new Element('#text', String(text));
  document.getElementById = (id) => document.querySelector('#' + id);
  return document;
}

const sourceRoot = path.join(__dirname, '../src/sqlseed_web/static/js');
const scrollModules = new WeakMap();
function source(name) {
  return fs.readFileSync(path.join(sourceRoot, name), 'utf8')
    .replace(/^import[\s\S]*?;\s*\n/gm, '')
    .replace(/^export /gm, '');
}

function loadFrontend(name, bindings = {}) {
  const document = bindings.document || createDom();
  const globals = {
    console, document, Map, Set, Date, Object, JSON, Array, String, Number,
    URL, Blob, structuredClone, setTimeout, clearTimeout, innerHeight: 1000, innerWidth: 1144,
    window: new Element('window'),
    fetch: async () => { throw new Error('Unexpected fetch in test'); },
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    location: {hash: '#/wizard'},
    ...bindings,
  };
  const apiContext = vm.createContext({...globals});
  vm.runInContext(source('api.js'), apiContext, {filename: 'api.js'});
  const api = vm.runInContext('({h, clear, msg, table, fmt, store, api, get, post, del, setConnBadge, rememberConnId, forgetConnId, restoreConnection})', apiContext);
  if (!scrollModules.has(document)) {
    const scrollContext = vm.createContext({document});
    vm.runInContext(source('workbench/scroll-lock.js'), scrollContext, {filename: 'workbench/scroll-lock.js'});
    scrollModules.set(document, vm.runInContext('lockPageScroll', scrollContext));
  }
  const context = vm.createContext({...globals, ...api, lockPageScroll: scrollModules.get(document), ...bindings});
  if (name !== 'api.js') vm.runInContext(source(name), context, {filename: name});
  return context;
}

module.exports = {Element, createDom, loadFrontend};
