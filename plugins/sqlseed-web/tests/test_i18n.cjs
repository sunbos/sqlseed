const assert = require('node:assert/strict');
const test = require('node:test');
const {Element, createDom, loadFrontend, loadI18n} = require('./frontend_helpers.cjs');

test('JSON language resources share an awaited fetch across callers and language changes', async () => {
  let resolveResponse;
  const pending = new Promise(resolve => { resolveResponse = resolve; });
  const requests = [];
  const ui = loadI18n({fetch: async url => { requests.push(url); return pending; }});
  const url = new URL('https://local.example/static/messages/async.json');
  const first = ui.loadMessages(url);
  const second = ui.loadMessages(String(url));
  assert.equal(first, second);
  ui.setLanguage('en');
  ui.setLanguage('zh-CN');
  ui.setLanguage('en');
  resolveResponse({ok: true, json: async () => ({asyncCatalog: {ready: ['已载入 {name}', 'Loaded {name}']}})});
  await Promise.all([first, second]);
  assert.equal(ui.t('asyncCatalog.ready', {name: '用户值'}), 'Loaded 用户值');
  await ui.loadMessages(url);
  assert.deepEqual(requests, [String(url)]);
  ui.setLanguage('zh-CN');
  assert.equal(ui.t('asyncCatalog.ready', {name: '用户值'}), '已载入 用户值');
  assert.equal(requests.length, 1);
});

test('resource failures reject explicitly, retain the failure and give a localized initial-page alert', async () => {
  const document = createDom(), app = new Element('main');
  app.setAttribute('id', 'app'); document.body.append(app);
  let requests = 0;
  const ui = loadI18n({document, navigator: {languages: ['en']}, fetch: async () => {
    requests++; return {ok: false, status: 503};
  }});
  const failed = ui.loadMessages('https://local.example/static/messages/missing.json');
  await assert.rejects(failed, error => {
    assert.match(error.message, /Interface language resources could not be loaded/);
    assert.match(error.cause.message, /HTTP 503/);
    return true;
  });
  assert.equal(app.querySelector('[role="alert"]').textContent, ui.t('common.languageResourcesFailed'));
  ui.setLanguage('zh-CN');
  assert.match(app.textContent, /界面语言资源加载失败/);
  assert.equal(ui.loadMessages('https://local.example/static/messages/missing.json'), failed);
  assert.equal(requests, 1, 'failed resources are not silently retried on language changes');
});

test('invalid JSON catalogs cannot partially register messages or replace an active form', async () => {
  const document = createDom(), app = new Element('main'), input = new Element('input');
  app.setAttribute('id', 'app'); input.value = '未应用的修改';
  app.append(input); document.body.append(app); document.activeElement = input;
  const ui = loadI18n({document, fetch: async () => ({ok: true, json: async () => ({
    pendingCatalog: {valid: ['有效', 'Valid'], invalid: ['缺少英文']}
  })})});
  const before = JSON.stringify(ui.messageEntries());
  await assert.rejects(ui.loadMessages('https://local.example/static/messages/invalid.json'), error => {
    assert.match(error.cause.message, /Invalid UI message: pendingCatalog.invalid/);
    return true;
  });
  assert.equal(JSON.stringify(ui.messageEntries()), before);
  assert.equal(app.firstChild, input);
  assert.equal(input.value, '未应用的修改');
  assert.equal(document.activeElement, input);
});

test('a JSON parse failure preserves its diagnostic cause and does not register entries', async () => {
  const ui = loadI18n({fetch: async () => ({ok: true, json: async () => { throw new SyntaxError('invalid JSON'); }})});
  const before = JSON.stringify(ui.messageEntries());
  await assert.rejects(ui.loadMessages('https://local.example/static/messages/broken.json'), error => {
    assert.equal(error.cause.message, 'invalid JSON'); return true;
  });
  assert.equal(JSON.stringify(ui.messageEntries()), before);
});

test('language notifications use a stable subscriber snapshot', () => {
  const ui = loadI18n(), events = [];
  const third = language => events.push(`third:${language}`);
  let removeSecond;
  ui.onLanguageChange(language => {
    events.push(`first:${language}`); removeSecond(); ui.onLanguageChange(third);
  });
  removeSecond = ui.onLanguageChange(language => events.push(`second:${language}`));
  ui.setLanguage('en'); ui.setLanguage('zh-CN');
  assert.deepEqual(events, ['first:en', 'second:en', 'first:zh-CN', 'third:zh-CN']);
});

test('UI language follows the first supported preference and has an English fallback', () => {
  const ui = loadI18n();
  assert.equal(ui.browserLanguage(['fr-FR', 'en-GB', 'zh-CN']), 'en');
  assert.equal(ui.browserLanguage(['zh-Hans-CN', 'en-US']), 'zh-CN');
  assert.equal(ui.browserLanguage(['de-DE']), 'en');
  assert.equal(ui.browserLanguage([]), 'en');
  assert.equal(loadI18n({navigator: {languages: ['en-US']}}).getLanguage(), 'en');
});

test('an explicit preference wins and corrupt or unavailable storage remains usable', () => {
  const writes = [];
  const ui = loadI18n({navigator: {languages: ['en-US']}, localStorage: {
    getItem: () => 'zh-CN', setItem: (...values) => writes.push(values),
  }});
  assert.equal(ui.getLanguage(), 'zh-CN');
  ui.setLanguage('en');
  assert.deepEqual(writes, [['sqlseed.ui.language', 'en']]);
  assert.equal(ui.setLanguage('unsupported'), false);
  assert.equal(ui.getLanguage(), 'en');
  assert.equal(loadI18n({navigator: {languages: ['zh-CN']}, localStorage: {getItem: () => 'corrupt'}}).getLanguage(), 'zh-CN');
  const blocked = loadI18n({navigator: {languages: ['en']}, localStorage: {
    getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); },
  }});
  assert.equal(blocked.getLanguage(), 'en');
  assert.equal(blocked.setLanguage('zh-CN'), true);
  assert.equal(blocked.getLanguage(), 'zh-CN');
});

test('language changes update only bound text and labels without replacing form state', () => {
  const document = createDom();
  const ui = loadFrontend('api.js', {document});
  ui.registerMessages('testForm', {
    label: ['编辑 {name}', 'Edit {name}'],
    rows: ['{count} 行', {one: '{count} row', other: '{count} rows'}],
  });
  const field = ui.h('input', {value: '未应用的修改', placeholder: ui.tr('testForm.label', {name: '客户表'})});
  const text = ui.h('span', {}, ui.tr('testForm.rows', {count: 1}));
  const button = ui.h('button', {'aria-label': ui.tr('testForm.label', {name: '<script>客户</script>'})}, text);
  document.body.append(field, button);
  field.scrollLeft = 12;
  field.selectionStart = 2;
  document.activeElement = field;
  const originalTextNode = text.firstChild;
  ui.setLanguage('en');
  assert.equal(document.documentElement.getAttribute('lang'), 'en');
  assert.equal(field.getAttribute('placeholder'), 'Edit 客户表');
  assert.equal(field.value, '未应用的修改');
  assert.equal(field.scrollLeft, 12);
  assert.equal(field.selectionStart, 2);
  assert.equal(document.activeElement, field);
  assert.equal(text.firstChild, originalTextNode);
  assert.equal(text.textContent, '1 row');
  assert.equal(button.getAttribute('aria-label'), 'Edit <script>客户</script>');
  assert.equal(button.querySelector('script'), null);
  ui.setText(text, ui.tr('testForm.rows', {count: 2}));
  assert.equal(text.textContent, '2 rows');
  ui.setLanguage('zh-CN');
  assert.equal(text.textContent, '2 行');
  ui.setText(text, '用户自定义：2 行');
  ui.setLanguage('en');
  assert.equal(text.textContent, '用户自定义：2 行');
});

test('storage events synchronize the language without writing it back or sharing documents', async () => {
  const document = createDom(), window = new Element('window'), writes = [];
  let stored = 'en';
  const ui = loadI18n({document, window, localStorage: {getItem: () => stored, setItem: (...args) => writes.push(args)}});
  const independent = loadI18n({navigator: {languages: ['en']}});
  stored = 'zh-CN';
  await window.dispatchEvent({type: 'storage', key: ui.LANGUAGE_KEY, newValue: 'zh-CN'});
  assert.equal(ui.getLanguage(), 'zh-CN');
  stored = 'en';
  await window.dispatchEvent({type: 'storage', key: ui.LANGUAGE_KEY, newValue: 'zh-CN'});
  assert.equal(ui.getLanguage(), 'en', 'late events cannot roll back a newer preference');
  assert.deepEqual(writes, []);
  assert.equal(independent.getLanguage(), 'en');
  assert.deepEqual(writes, []);
  await window.dispatchEvent({type: 'storage', key: 'sqlseed.connId', newValue: 'en'});
  assert.equal(ui.getLanguage(), 'en');
});

test('server descriptors preserve nested messages and arbitrary user text', () => {
  const ui = loadI18n();
  ui.registerMessages('backend', {
    'test.failed': ['检查失败：{issues}', 'Check failed: {issues}'],
    'test.table': ['表 {table} 缺少来源', 'Table {table} has no source'],
  });
  const message = ui.serverText({message: '检查失败', message_key: 'backend.test.failed', message_params: {
    issues: {message: '表失败', message_key: 'backend.test.table', message_params: {table: '姓名'}},
  }});
  assert.equal(String(message), '检查失败：表 姓名 缺少来源');
  ui.setLanguage('en');
  assert.equal(String(message), 'Check failed: Table 姓名 has no source');
  assert.equal(String(ui.serverText({message: '原始第三方诊断'})), 'Details: 原始第三方诊断');
  assert.equal(String(ui.tr('unknown.key')), 'Translation unavailable');
  assert.ok(ui.missingMessages().includes('unknown.key'));
});

test('localized errors retain their presentation after a language change', () => {
  const ui = loadI18n();
  const error = new ui.UserFacingError(ui.tr('common.loading'));
  assert.equal(error.message, '正在加载…');
  ui.setLanguage('en');
  assert.equal(String(ui.errorText(error)), 'Loading…');
  assert.match(String(ui.errorText(new Error('driver details'))), /Details: driver details/);
});

test('composite server diagnostics retain order, separators and nested translations', () => {
  const ui = loadI18n();
  ui.registerMessages('backend', {'test.item': ['表 {table}', 'Table {table}']});
  const value = ui.serverText({message: '原始诊断', message_key: 'backend.message_list', message_params: {
    items: [{message:'表 客户', message_key:'backend.test.item', message_params:{table:'客户'}}, 'driver: raw'], separator:' / '
  }});
  assert.equal(String(value), '表 客户 / driver: raw');
  ui.setLanguage('en');
  assert.equal(String(value), 'Table 客户 / driver: raw');
  assert.match(String(ui.serverText({message:'driver diagnostic', message_key:'backend.new.unknown'})), /Details: driver diagnostic/);
});

test('legacy diagnostics gain a live explanation without changing opaque records or empty fields', () => {
  const ui = loadI18n();
  const record = {message:'driver: 中文用户值', errors:['旧运行诊断'], row:{message:'客户原文'}};
  const before = JSON.stringify(record);
  const message = ui.serverText(record), errors = ui.serverMessages(record, 'errors');
  assert.equal(String(message), '诊断详情：driver: 中文用户值');
  assert.equal(String(errors[0]), '诊断详情：旧运行诊断');
  assert.equal(ui.serverText({}), '');
  assert.equal(ui.serverText({message:''}), '');
  ui.setLanguage('en');
  assert.equal(String(message), 'Details: driver: 中文用户值');
  assert.equal(String(errors[0]), 'Details: 旧运行诊断');
  assert.equal(JSON.stringify(record), before);
  assert.equal(record.row.message, '客户原文');
});

for (const detail of ['driver failed', {code:'old_error',message:'旧后端诊断'},
  [{loc:['body','count'],msg:'legacy validation'}, {loc:['body','table'],msg:'legacy table'}]]) {
  test(`HTTP diagnostics retain the legacy Error.message for ${JSON.stringify(detail)}`, async () => {
    const ui = loadFrontend('api.js', {fetch:async()=>new Response(JSON.stringify({detail}),{status:422})});
    let error;
    try { await ui.api('/failure'); } catch (value) { error = value; }
    const original = typeof detail === 'string' ? detail : Array.isArray(detail) ? 'body.count: legacy validation；body.table: legacy table' : detail.message;
    assert.equal(error.message, original);
    assert.equal(error.status, 422);
    assert.deepEqual(JSON.parse(JSON.stringify(error.detail)), detail);
    assert.match(String(ui.errorText(error)), /诊断详情/);
    ui.setLanguage('en');
    assert.match(String(ui.errorText(error)), /Details:/);
    assert.equal(error.message, original);
  });
}

test('described HTTP errors keep their original message while presentation follows language', async () => {
  const detail={code:'not_found',message:'unknown connection: old',
    message_key:'backend.state.unknown_connection',message_params:{p1:'old'}};
  const ui=loadFrontend('api.js',{fetch:async()=>new Response(JSON.stringify({detail}),{status:404})});
  let error;
  try { await ui.api('/failure'); } catch (value) { error=value; }
  assert.equal(error.message, 'unknown connection: old');
  assert.equal(String(ui.errorText(error)), '未知连接：old');
  ui.setLanguage('en');
  assert.equal(String(ui.errorText(error)), 'unknown connection: old');
  assert.equal(error.message, 'unknown connection: old');
});
