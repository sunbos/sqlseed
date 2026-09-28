const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {Element, createDom, loadFrontend, loadI18n} = require('./frontend_helpers.cjs');

const staticRoot = path.join(__dirname, '../src/sqlseed_web/static');
const placeholders = text => [...new Set([...text.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]))].sort();
const templates = value => typeof value === 'string' ? [value] : Object.values(value);

test('native ES module entrypoints await real JSON catalogs and preserve every namespace, key and value', () => {
  const output = execFileSync(process.execPath, ['--experimental-vm-modules', '--input-type=module', '--eval', `
    import assert from 'node:assert/strict';
    import fs from 'node:fs';
    import path from 'node:path';
    import vm from 'node:vm';
    import {fileURLToPath, pathToFileURL} from 'node:url';
    const root = process.argv[1], resources = path.join(root, 'js/i18n/messages');
    const requests = [], modules = new Map();
    const context = vm.createContext({URL, Intl, navigator: {languages: ['en']}, fetch: async url => {
      const file = fileURLToPath(url);
      assert.equal(path.dirname(file), resources, 'only local language data may be requested');
      assert.equal(path.extname(file), '.json');
      requests.push(file);
      return {ok: true, json: async () => JSON.parse(await fs.promises.readFile(file, 'utf8'))};
    }});
    function load(file) {
      if (!modules.has(file)) modules.set(file, new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), {
        context, identifier: file, initializeImportMeta(meta) { meta.url = pathToFileURL(file).href; }
      }));
      return modules.get(file);
    }
    const expected = {}, files = fs.readdirSync(resources).filter(name => name.endsWith('.json')).sort();
    assert.ok(files.length > 0);
    for (const name of files) {
      const data = JSON.parse(fs.readFileSync(path.join(resources, name), 'utf8'));
      for (const [namespace, entries] of Object.entries(data)) {
        for (const [key, value] of Object.entries(entries)) expected[namespace + '.' + key] = value;
      }
      const module = load(path.join(resources, name.replace(/\\.json$/, '.js')));
      await module.link((specifier, parent) => load(path.resolve(path.dirname(parent.identifier), specifier)));
      await module.evaluate();
    }
    const ui = load(path.join(root, 'js/i18n.js')).namespace;
    const actual = Object.fromEntries(ui.messageEntries().filter(([key]) => !key.startsWith('common.')));
    assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected);
    for (const language of ['zh-CN', 'en', 'zh-CN', 'en']) ui.setLanguage(language);
    for (const file of requests.slice()) await ui.loadMessages(pathToFileURL(file));
    assert.equal(requests.length, files.length, 'cached resources and language switches must not refetch');
    assert.equal(new Set(requests).size, files.length);
    console.log(JSON.stringify({files: files.length, entries: Object.keys(expected).length}));
  `, '--', staticRoot], {encoding: 'utf8', stdio: 'pipe'});
  const result = JSON.parse(output);
  const catalogFiles = fs.readdirSync(path.join(staticRoot, 'js/i18n/messages')).filter(name => name.endsWith('.json'));
  assert.equal(result.files, catalogFiles.length);
  assert.ok(result.entries > 0);
});

test('every registered catalog entry has complete locales, reachable plural forms and matching parameters', () => {
  const ui = loadI18n();
  const entries = ui.messageEntries();
  assert.ok(entries.length > 0, 'the real resource loader must register messages');
  for (const [key, pair] of entries) {
    assert.match(key, /^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$/, key);
    assert.ok(Array.isArray(pair) && pair.length === ui.UI_LANGUAGES.length, key);
    const expected = placeholders(templates(pair[0])[0]);
    for (const [index, value] of pair.entries()) {
      assert.ok(typeof value === 'string' || value && typeof value === 'object' && !Array.isArray(value), key);
      if (typeof value !== 'string') {
        assert.ok(Object.hasOwn(value, 'other'), `${key}: a plural message requires an other fallback`);
        const forms = new Intl.PluralRules(ui.UI_LANGUAGES[index]).resolvedOptions().pluralCategories;
        for (const form of Object.keys(value)) assert.ok(forms.includes(form), `${key}: unreachable ${form} form`);
        for (const form of forms) assert.ok(Object.hasOwn(value, form), `${key}: missing ${form} form`);
      }
      for (const template of templates(value)) {
        assert.equal(typeof template, 'string', key);
        assert.ok(template.trim(), `${key}: empty translation`);
        assert.deepEqual(placeholders(template), expected, `${key}: locale/plural parameters differ`);
        if (index === 1) assert.doesNotMatch(template, /\p{Script=Han}/u, `${key}: untranslated English template`);
      }
    }
  }
});

test('all catalog messages render both languages without dropping values or leaving placeholders', () => {
  const ui = loadI18n();
  for (const [key, pair] of ui.messageEntries()) {
    const names = placeholders(templates(pair[0])[0]);
    for (const count of [0, 1, 2, 1000]) {
      const params = Object.fromEntries(names.map(name => [name, `VALUE_${name}`]));
      params.count = count;
      const message = ui.tr(key, params);
      for (const language of ui.UI_LANGUAGES) {
        ui.setLanguage(language, {persist: false});
        const text = String(message);
        assert.equal(placeholders(text).length, 0, `${key}: unresolved parameters in ${language}`);
        for (const name of names) assert.ok(text.includes(String(params[name])), `${key}: lost ${name} in ${language}`);
      }
    }
  }
  assert.equal(ui.missingMessages().length, 0);
});

test('the backend JSON catalog is registered unchanged for additive server descriptors', () => {
  const ui = loadI18n();
  const catalog = JSON.parse(fs.readFileSync(path.join(staticRoot, 'i18n/backend-messages.json'), 'utf8'));
  const registered = Object.fromEntries(ui.messageEntries().filter(([key]) => key.startsWith('backend.')));
  assert.deepEqual(JSON.parse(JSON.stringify(registered)), catalog);
  for (const [key, pair] of Object.entries(catalog)) {
    if (key === 'backend.message_list') continue; // Its explicit nested-list contract is covered in test_i18n.cjs.
    const params = Object.fromEntries(placeholders(pair[0]).map(name => [name, `RAW_${name}`]));
    const value = ui.serverText({message: pair[0], message_key: key, message_params: params});
    for (const language of ui.UI_LANGUAGES) {
      ui.setLanguage(language, {persist: false});
      assert.equal(String(value), ui.t(key, params));
      for (const raw of Object.values(params)) assert.ok(String(value).includes(raw), `${key}: user parameter changed`);
    }
  }
  assert.equal(ui.missingMessages().length, 0);
});

test('dynamic navigation, weekday and appearance keys resolve from the real controls', async () => {
  const document = createDom(), window = new Element('window');
  const ui = loadI18n({document, window});
  const html = fs.readFileSync(path.join(staticRoot, 'index.html'), 'utf8');
  const destinations = [...html.matchAll(/data-page="([^"]+)"/g)].map(match => match[1]);
  assert.ok(destinations.length > 0);
  const names = destinations.map(page => ui.tr(`shell.${page}`));
  const calendar = loadFrontend('workbench/date-picker.js', {document, window});
  const weekdays = vm.runInContext('[...weekNames, ...weekShortNames]', calendar);
  let state = {preference: 'light', resolved: 'light'};
  window.sqlseedTheme = {get: () => state, setPreference() {throw new Error('Language tests must not change appearance');}};
  const dropdown = loadFrontend('dropdown.js', {document, window});
  const theme = loadFrontend('theme-control.js', {document, window, createDropdown: dropdown.createDropdown});
  const control = theme.createThemeControl();
  document.body.append(control.el);
  try {
    for (const language of ui.UI_LANGUAGES) {
      ui.setLanguage(language, {persist: false});
      for (const name of [...names, ...weekdays]) assert.ok(String(name).trim());
      assert.equal(new Set(weekdays.slice(0, weekdays.length / 2).map(String)).size, weekdays.length / 2);
      for (const preference of ['light', 'dark', 'system']) {
        for (const resolved of ['light', 'dark']) {
          state = {preference, resolved};
          await window.dispatchEvent({type: 'sqlseed:theme-changed'});
          const expected = ui.t(preference === 'system' ? 'shell.systemTheme' : 'shell.currentTheme', {color: ui.t(`shell.${resolved}`)});
          assert.equal(control.el.querySelector('.theme-status').textContent, expected);
        }
      }
    }
    assert.equal(ui.missingMessages().length, 0);
  } finally {
    control.destroy();
  }
});

test('counted English phrases use singular and plural independently of formatted display values', () => {
  const ui = loadI18n();
  ui.setLanguage('en');
  const cases = [
    ['workbench.execution.totalRows', 'row to generate', 'rows to generate'],
    ['workbench.execution.totalTables', '1 table', '2 tables'],
    ['workbench.count.generateRows', 'Generate 1 row', 'Generate 2 rows'],
    ['workbench.count.rows', '1 row', '2 rows'],
    ['configurations.rowCount', '1 row', '2 rows'],
    ['graph.existing', '1 existing row', '2 existing rows'],
    ['preview.sourceCount', '1 source', '2 sources'],
  ];
  for (const [key, one, other] of cases) {
    assert.equal(ui.t(key, {count: 1, value: '1', tables: '1'}), one);
    assert.equal(ui.t(key, {count: 2, value: '2', tables: '2'}), other);
  }
  assert.equal(ui.t('graph.existing', {count: 1, value: 'DISPLAY'}), 'DISPLAY existing row');
  assert.equal(ui.t('graph.existing', {count: 1000, value: ui.formatNumber(1000)}), '1,000 existing rows');
  assert.match(ui.t('preview.invalidConfiguration', {count: 1, value: '1', detail: 'RAW'}), /limit of 1 row per table/);
  assert.match(ui.t('workbench.preview.selectedHelp', {count: 1}), /1 selected table without/);
  assert.match(ui.t('assistant.scope.matchSummary', {count: 1, scope: 'RAW', protectedNote: ''}), /1 selectable field\./);
});
