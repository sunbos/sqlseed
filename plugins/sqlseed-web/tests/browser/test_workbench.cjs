'use strict';

// Real Chrome + real HTTP + disposable SQLite. No DOM/network substitutes.
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {once} = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {setTimeout: delay} = require('node:timers/promises');
const {test} = require('node:test');

const python = process.env.PYTHON || 'python';
const chrome = process.env.CHROME_BIN || 'google-chrome';
const artifacts = path.resolve(process.env.BROWSER_ARTIFACTS || 'browser-artifacts');

async function until(check, description, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${description}`);
}

async function stop(child) {
  if (!child || !child.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, 'exit');
  child.kill('SIGTERM');
  const forced = setTimeout(() => child.kill('SIGKILL'), 5000);
  try { await exited; } finally { clearTimeout(forced); }
}

// Chrome's private debugging pipe avoids exposing a debugging port. Each
// command has its own deadline; unexpected browser exits reject pending calls.
function protocol(child) {
  let id = 0;
  let buffer = '';
  const pending = new Map();
  const errors = [];
  function fail(error) {
    for (const request of pending.values()) request.reject(error);
    pending.clear();
  }
  child.on('error', fail);
  child.on('exit', () => fail(new Error('Chrome exited')));
  child.stdio[3].on('error', fail);
  child.stdio[4].setEncoding('utf8');
  child.stdio[4].on('data', chunk => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf('\0')) >= 0) {
      const message = JSON.parse(buffer.slice(0, end));
      buffer = buffer.slice(end + 1);
      if (message.method === 'Runtime.exceptionThrown') {
        errors.push(message.params.exceptionDetails.text + ': ' +
          (message.params.exceptionDetails.exception?.description || ''));
      }
      const request = pending.get(message.id);
      if (!request) continue;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result);
    }
  });
  return {
    errors,
    call(method, params = {}, sessionId, timeout = 10000) {
      return new Promise((resolve, reject) => {
        const requestId = ++id;
        const timer = setTimeout(() => {
          pending.delete(requestId);
          reject(new Error(`Chrome command timed out: ${method}`));
        }, timeout);
        pending.set(requestId, {
          resolve: value => { clearTimeout(timer); resolve(value); },
          reject: error => { clearTimeout(timer); reject(error); }
        });
        child.stdio[3].write(JSON.stringify({id: requestId, method, params, sessionId}) + '\0');
      });
    }
  };
}

test('browser workbench: connect, preview, cancel, generate and restore', {timeout: 180000}, async t => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'sqlseed-browser-'));
  fs.mkdirSync(artifacts, {recursive: true});
  const database = path.join(temporary, 'synthetic.sqlite3');
  const environment = {
    PATH: process.env.PATH,
    // setup-python's toolcache runtime can require its shared-library path.
    ...(process.env.LD_LIBRARY_PATH ? {LD_LIBRARY_PATH: process.env.LD_LIBRARY_PATH} : {}),
    HOME: temporary,
    TMPDIR: temporary,
    LANG: 'C.UTF-8',
    PYTHONUNBUFFERED: '1',
    SQLSEED_WEB_WORKSPACE_PATH: path.join(temporary, 'workspace.sqlite3'),
    SQLSEED_WEB_SETTINGS_PATH: path.join(temporary, 'settings.json'),
    SQLSEED_CACHE_DIR: path.join(temporary, 'cache')
  };
  let server, browser, cdp, session;
  let serverLog = '', browserLog = '';
  t.after(async () => {
    await stop(browser);
    await stop(server);
    fs.rmSync(temporary, {recursive: true, force: true});
  });
  const sql = statement => execFileSync(python, ['-c',
    'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); print(json.dumps(c.execute(sys.argv[2]).fetchall())); c.commit(); c.close()',
    database, statement], {env: environment, encoding: 'utf8', timeout: 10000}).trim();
  try {
    sql('CREATE TABLE smoke_items (id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 9))');
    // Port 0 lets the OS allocate a free loopback port. Uvicorn reports it only
    // after binding, avoiding a find-free-port / bind race.
    server = spawn(python, ['-m', 'uvicorn', 'sqlseed_web.app:create_app', '--factory',
      '--host', '127.0.0.1', '--port', '0'], {env: environment, stdio: ['ignore', 'pipe', 'pipe']});
    server.on('error', error => { serverLog += String(error); });
    for (const stream of [server.stdout, server.stderr]) stream.on('data', chunk => { serverLog += chunk; });
    const baseURL = await until(() => {
      if (server.exitCode !== null) throw new Error(`Server exited: ${serverLog}`);
      return serverLog.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    }, 'HTTP server startup');
    browser = spawn(chrome, ['--headless=new', '--remote-debugging-pipe',
      `--user-data-dir=${path.join(temporary, 'chrome')}`, '--no-first-run',
      '--no-default-browser-check', '--password-store=basic', '--disable-background-networking', '--disable-component-update',
      '--window-size=1440,900', 'about:blank'],
    {env: environment, stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe']});
    browser.stderr.on('data', chunk => { browserLog += chunk; });
    cdp = protocol(browser);
    const version = await cdp.call('Browser.getVersion', {}, undefined, 60000);
    console.log(`Browser: ${version.product}; Node: ${process.version}`);
    const {targetId} = await cdp.call('Target.createTarget', {url: 'about:blank'});
    ({sessionId: session} = await cdp.call('Target.attachToTarget', {targetId, flatten: true}));
    const call = (method, params) => cdp.call(method, params, session);
    const evaluate = async expression => {
      const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const wait = (expression, description) => until(() => evaluate(expression), description);
    const element = selector => `document.querySelector(${JSON.stringify(selector)})`;
    async function click(selector) {
      const point = await wait(`(() => {
        const e = ${element(selector)};
        if (!e || e.disabled || e.closest('[inert]')) return false;
        e.scrollIntoView({block: 'center'});
        const r = e.getBoundingClientRect();
        if (!r.width || !r.height) return false;
        const x = r.x + r.width / 2, y = r.y + r.height / 2;
        if (!e.contains(document.elementFromPoint(x, y))) return false;
        return {x, y};
      })()`, `clickable ${selector}`);
      await call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
      await call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
    }
    async function key(key, code, modifiers = 0) {
      await call('Input.dispatchKeyEvent', {type: 'keyDown', key, code, modifiers, windowsVirtualKeyCode: key === 'Escape' ? 27 : 65});
      await call('Input.dispatchKeyEvent', {type: 'keyUp', key, code, modifiers, windowsVirtualKeyCode: key === 'Escape' ? 27 : 65});
    }
    async function fill(selector, value) {
      await click(selector);
      await key('a', 'KeyA', 2);
      await call('Input.insertText', {text: value});
    }
    await call('Runtime.enable');
    await call('Page.enable');
    await call('Page.addScriptToEvaluateOnNewDocument', {source:
      "localStorage.setItem('sqlseed.ui.language', 'en'); window.__smokeDocument = crypto.randomUUID();"});
    await call('Page.navigate', {url: baseURL});
    await wait("document.querySelector('.wb-welcome')", 'workbench ES modules and empty state');
    await click('#connection-button');
    await wait("document.querySelector('.connection-modal')", 'connection dialog');
    await key('Escape', 'Escape');
    await wait("!document.querySelector('.connection-modal') && !document.querySelector('#app').inert", 'Escape dismissal');
    await click('#connection-button');
    await fill('input[name="db_path"]', database);
    await click('.connection-footer .primary');
    await wait("!document.querySelector('.connection-modal') && document.querySelector('[data-table=\"smoke_items\"]')", 'real SQLite schema');
    await click('[data-table="smoke_items"] input[type="checkbox"]');
    await click('[data-table="smoke_items"] .wb-table-name');
    await fill('.wb-number-control input', '3');
    await wait(`${element('.wb-number-control input')}.value === '3'`, 'edited generation count');
    await click('#wb-table-tab-preview');
    await click('.wb-preview-controls button[data-db-action]');
    await wait("document.querySelectorAll('.wb-preview-data tbody tr').length > 0", 'generated sample rows');
    assert.equal(sql('SELECT count(*) FROM smoke_items'), '[[0]]', 'preview must not write rows');
    assert.match(await evaluate("document.querySelector('.wb-preview-data').innerText"), /quantity/);
    await click('[data-plan-entry]');
    await wait("document.querySelector('.wb-execution-actions .primary:not(:disabled)')", 'validated generation plan');
    await key('Escape', 'Escape');
    await wait("!document.querySelector('.wb-execution-actions')", 'cancelled generation plan');
    assert.equal(sql('SELECT count(*) FROM smoke_items'), '[[0]]', 'cancel must not write rows');
    await click('[data-plan-entry]');
    await click('.wb-execution-actions .primary');
    await wait("document.querySelector('.run-detail .run-status.done')", 'successful persisted run');
    assert.equal(sql('SELECT count(*) FROM smoke_items'), '[[3]]');
    assert.equal(sql('SELECT count(*) FROM smoke_items WHERE quantity BETWEEN 1 AND 9'), '[[3]]');
    const previousDocument = await evaluate('window.__smokeDocument');
    await call('Page.reload');
    await until(async () => {
      try {
        return await evaluate(`Boolean(window.__smokeDocument) && window.__smokeDocument !== ${JSON.stringify(previousDocument)}`);
      } catch (error) {
        if (/execution context|Cannot find context/i.test(error.message)) return false;
        throw error;
      }
    }, 'a new document after reload');
    await wait("document.querySelector('.run-detail .run-status.done')", 'run restored after browser reload');
    await click('#nav [data-page="workbench"]');
    await wait("document.querySelector('[data-table=\"smoke_items\"]')", 'restored connection on workbench');
    assert.deepEqual(cdp.errors, [], 'no uncaught browser JavaScript errors');
    console.log('PASS: connection cancellation, real schema, preview without writes, plan cancellation, three committed rows, persisted run and connection restoration');
  } catch (error) {
    fs.writeFileSync(path.join(artifacts, 'server.log'), serverLog);
    fs.writeFileSync(path.join(artifacts, 'chrome.log'), browserLog);
    fs.writeFileSync(path.join(artifacts, 'failure.txt'), `${error.stack}\n${JSON.stringify(cdp?.errors || [])}`);
    if (cdp && session) {
      try {
        const screenshot = await cdp.call('Page.captureScreenshot', {format: 'png'}, session);
        fs.writeFileSync(path.join(artifacts, 'failure.png'), Buffer.from(screenshot.data, 'base64'));
        const dom = await cdp.call('Runtime.evaluate', {expression: 'document.documentElement.outerHTML', returnByValue: true}, session);
        fs.writeFileSync(path.join(artifacts, 'page.html'), dom.result.value);
      } catch { /* Preserve the original failure if Chrome itself is unavailable. */ }
    }
    throw error;
  }
});
