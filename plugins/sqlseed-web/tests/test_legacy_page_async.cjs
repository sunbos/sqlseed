const assert = require('node:assert/strict');
const test = require('node:test');
const {createDom, loadFrontend} = require('./frontend_helpers.cjs');
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => {resolve = done; reject = fail;});
  return {promise, resolve, reject};
}
function healHarness(get) {
  const document = createDom();
  const dropdown = loadFrontend('dropdown.js', {document});
  const page = loadFrontend('pages/heal.js', {
    document, get, createDropdown: dropdown.createDropdown,
    store: {connId: 'fixture', tables: []},
  });
  const show = () => {
    const root = page.render();
    document.body.replaceChildren(root);
    return root.querySelector('#ai-panel-body');
  };
  return {document, page, show};
}

test('legacy AI panel reports a config request failure instead of leaving an unhandled rejection', async () => {
  const gate = deferred(), ui = healHarness(() => gate.promise), holder = ui.show();
  gate.reject(new Error('configuration service unavailable'));
  await flush();
  assert.match(holder.textContent, /AI 配置读取失败：configuration service unavailable/);
  assert.doesNotMatch(holder.textContent, /加载 AI 配置|sqlseed-ai 未安装/);
});

for (const failed of [false, true]) {
  test(`a replaced legacy AI panel ignores its obsolete ${failed ? 'failure' : 'response'}`, async () => {
    const old = deferred(); let request = 0;
    const ui = healHarness(() => ++request === 1 ? old.promise
      : Promise.resolve({available: false, reason: 'current installation has no AI'}));
    const first = ui.show(), current = ui.show();
    await flush();
    const content = current.textContent;
    assert.match(content, /current installation has no AI/);
    if (failed) old.reject(new Error('obsolete request failed'));
    else old.resolve({available: false, reason: 'obsolete configuration'});
    await flush();
    assert.equal(current.textContent, content);
    assert.equal(first.isConnected, false);
    assert.doesNotMatch(first.textContent, /obsolete/);
  });
}

test('legacy AI panel also contains response rendering errors', async () => {
  const ui = healHarness(async () => ({available: true})), holder = ui.show();
  await flush();
  assert.match(holder.textContent, /AI 配置读取失败/);
  assert.doesNotMatch(holder.textContent, /加载 AI 配置/);
});

test('legacy metadata mount waits for failed metadata and renders its error', async () => {
  const document = createDom(), gate = deferred();
  const page = loadFrontend('pages/meta.js', {document, get: () => gate.promise});
  document.body.append(page.render());
  let settled = false;
  const mounting = page.mount().then(() => {settled = true;});
  await flush();
  assert.equal(settled, false);
  gate.reject(new Error('metadata service unavailable'));
  await mounting;
  assert.match(document.getElementById('meta-out').textContent, /metadata service unavailable/);
});
