const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const http = require('node:http');
const {test} = require('node:test');
const {deployPages} = require('../.github/scripts/deploy-pages.cjs');

const SHA = 'abc123'.repeat(6) + 'abcd';
const TOKEN = 'synthetic-oidc-secret-never-log';
const context = {repo: {owner: 'fixture', repo: 'pages'}, runId: 73, sha: SHA, payload: {repository: {id: 42}}};
const artifact = {
  id: 101, name: 'github-pages', expired: false,
  workflow_run: {id: 73, head_sha: SHA, repository_id: 42, head_repository_id: 42},
};

/** Exercise real HTTP with the injected Octokit request shape and deliberately unsafe errors. */
function httpClient(baseUrl) {
  return {async request(route, options) {
    const [method, template] = route.split(' ');
    const parameters = {...options};
    const path = template.replace(/\{(\w+)\}/g, (_, key) => {
      const value = parameters[key];
      delete parameters[key];
      return encodeURIComponent(value);
    });
    const {request, headers, ...body} = parameters;
    const response = await fetch(baseUrl + path, {
      method, signal: request.signal, headers: {...headers, 'Content-Type': 'application/json'},
      body: method === 'POST' ? JSON.stringify(body) : undefined,
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      // Deliberately include credentials in the SDK-like error to verify sanitization.
      throw Object.assign(new Error(`unsafe SDK details ${TOKEN}`), {status: response.status, request: body, response: {data}});
    }
    return {data};
  }};
}

/** Capture the action's user-visible results without needing runner credentials. */
function actionCore(logs, output, afterInfo = () => {}) {
  return {
    async getIDToken() { return TOKEN; },
    setSecret(value) { assert.equal(value, TOKEN); },
    info(value) { logs.push(value); afterInfo(value); },
    setOutput(name, value) { output[name] = value; },
  };
}

/** Serve a configurable Pages lifecycle and count its actual HTTP effects. */
async function fixture(t, behavior = {}) {
  const requests = [];
  const logs = [];
  const output = {};
  let polls = 0;
  let cancellations = 0;
  let deployments = 0;
  const server = http.createServer(async (req, res) => {
    let text = '';
    for await (const chunk of req) text += chunk;
    const body = text ? JSON.parse(text) : null;
    requests.push({method: req.method, url: req.url, body});
    let status = 200;
    let data;
    if (req.url === '/repos/fixture/pages/actions/artifacts/101' && req.method === 'GET') {
      status = behavior.artifactStatus || 200;
      data = behavior.artifact || artifact;
    } else if (req.url === '/repos/fixture/pages/pages/deployments' && req.method === 'POST') {
      deployments += 1;
      status = behavior.createStatus || 200;
      data = behavior.deployment || {id: 'deployment-1', page_url: 'https://fixture.github.io/pages/'};
      if (behavior.createStatus) data = {message: TOKEN};
      if (behavior.dropCreateResponse) {
        req.socket.destroy();
        return;
      }
    } else if (/\/pages\/deployments\/(deployment-1|[a-f\d]{40})\/cancel$/.test(req.url) && req.method === 'POST') {
      cancellations += 1;
      status = behavior.cancelStatus || 204;
      data = {message: TOKEN};
    } else if (/\/pages\/deployments\/(deployment-1|[a-f\d]{40})$/.test(req.url) && req.method === 'GET') {
      const entries = behavior.polls || ['succeed'];
      const entry = polls < entries.length ? entries[polls] : 'deployment_in_progress';
      polls += 1;
      if (entry === 'hang') return;
      status = typeof entry === 'number' ? entry : 200;
      data = typeof entry === 'number' ? {message: TOKEN} : {status: entry};
    } else {
      status = 404;
      data = {message: 'Unexpected fixture request'};
    }
    res.writeHead(status, {'Content-Type': 'application/json'});
    res.end(status === 204 ? undefined : JSON.stringify(data));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const previous = process.env.PAGES_ARTIFACT_ID;
  process.env.PAGES_ARTIFACT_ID = '101';
  t.after(() => {
    if (previous === undefined) delete process.env.PAGES_ARTIFACT_ID;
    else process.env.PAGES_ARTIFACT_ID = previous;
  });
  const baseUrl = `http://127.0.0.1:${server.address().port}`;
  const clients = {github: httpClient(baseUrl), core: actionCore(logs, output), context};
  return {
    baseUrl, clients, requests, logs, output,
    counts: () => ({polls, cancellations, deployments}),
    run: (options = {}) => deployPages(clients, {pollIntervalMs: 1, timeoutMs: 5000, ...options}),
  };
}

/** Run deployment in a separate process so cancellation also verifies listener cleanup. */
async function child() {
  const logs = [];
  const core = actionCore(logs, {}, value => {
    if (value.startsWith('Pages deployment created')) process.send({ready: true});
  });
  // Windows cannot deliver POSIX signals to child processes; Linux CI uses real signals.
  process.on('message', message => process.emit(message.signal));
  try {
    await deployPages({github: httpClient(process.env.PAGES_TEST_SERVER), core, context});
    process.send({unexpectedSuccess: true});
  } catch (error) {
    process.send({error: error.message, logs, listeners: ['SIGINT', 'SIGTERM'].map(name => process.listenerCount(name))});
    process.exitCode = 1;
  } finally {
    process.disconnect();
  }
}

if (process.argv[2] === 'child') {
  child();
} else {
  test('deploys only the validated artifact and publishes its URL after confirmed success', async t => {
    const f = await fixture(t, {polls: ['deployment_queued', 'deployment_in_progress', 'succeed']});
    const listeners = ['SIGINT', 'SIGTERM'].map(name => process.listenerCount(name));
    const result = await f.run();
    assert.deepEqual(result, {page_url: 'https://fixture.github.io/pages/', deployment_id: 'deployment-1'});
    assert.deepEqual(f.output, {page_url: result.page_url});
    assert.deepEqual(f.counts(), {deployments: 1, polls: 3, cancellations: 0});
    const creation = f.requests.find(request => request.method === 'POST');
    assert.deepEqual(creation.body, {
      artifact_id: 101, pages_build_version: SHA, environment: 'github-pages', oidc_token: TOKEN,
    });
    assert.ok(!f.logs.join('\n').includes(TOKEN));
    assert.deepEqual(['SIGINT', 'SIGTERM'].map(name => process.listenerCount(name)), listeners);
  });

  for (const [name, changes] of [
    ['different artifact', {id: 102}], ['different name', {name: 'other'}],
    ['expired artifact', {expired: true}], ['missing expiration', {expired: undefined}],
    ['different run', {workflow_run: {...artifact.workflow_run, id: 74}}],
    ['different commit', {workflow_run: {...artifact.workflow_run, head_sha: 'b'.repeat(40)}}],
    ['different repository', {workflow_run: {...artifact.workflow_run, repository_id: 43}}],
    ['fork artifact', {workflow_run: {...artifact.workflow_run, head_repository_id: 43}}],
    ['missing provenance', {workflow_run: undefined}],
  ]) {
    test(`rejects ${name} before obtaining OIDC or creating a deployment`, async t => {
      const f = await fixture(t, {artifact: {...artifact, ...changes}});
      f.clients.core.getIDToken = () => { throw new Error('OIDC must not be requested'); };
      await assert.rejects(f.run(), /does not match/);
      assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
      assert.deepEqual(f.output, {});
    });
  }

  for (const id of ['', '0', '-1', '1.2', '101; rm', '9007199254740992']) {
    test(`rejects invalid artifact ID ${JSON.stringify(id)} before any HTTP request`, async t => {
      const f = await fixture(t);
      process.env.PAGES_ARTIFACT_ID = id;
      await assert.rejects(f.run(), /PAGES_ARTIFACT_ID/);
      assert.deepEqual(f.requests, []);
    });
  }

  for (const [name, changes] of [
    ['repository', {payload: {}}], ['run', {runId: 0}], ['commit', {sha: 'main'}],
  ]) {
    test(`missing workflow ${name} identity cannot authorize deployment`, async t => {
      const f = await fixture(t);
      f.clients.context = {...context, ...changes};
      f.clients.core.getIDToken = () => { throw new Error('OIDC must not be requested'); };
      await assert.rejects(f.run(), /identity is missing/);
      assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
    });
  }

  for (const status of [401, 404, 500]) {
    test(`artifact metadata HTTP ${status} cannot create a deployment`, async t => {
      const f = await fixture(t, {artifactStatus: status});
      await assert.rejects(f.run(), error => {
        assert.match(error.message, new RegExp(`Reading the Pages artifact failed \\(HTTP ${status}\\)`));
        assert.ok(!error.message.includes(TOKEN));
        return true;
      });
      assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
    });
  }

  for (const status of [401, 403, 404, 422, 500]) {
    test(`creation HTTP ${status} fails without retrying or leaking SDK credentials`, async t => {
      const f = await fixture(t, {createStatus: status});
      await assert.rejects(f.run(), error => {
        assert.match(error.message, new RegExp(`Creating the Pages deployment failed \\(HTTP ${status}\\)`));
        assert.ok(!String(error).includes(TOKEN));
        return true;
      });
      assert.deepEqual(f.counts(), {deployments: 1, polls: 0, cancellations: status >= 500 ? 1 : 0});
      assert.deepEqual(f.output, {});
      assert.ok(!f.logs.join('\n').includes(TOKEN));
    });
  }

  test('lost creation response is not retried and triggers cleanup by the documented build SHA', async t => {
    const f = await fixture(t, {dropCreateResponse: true});
    await assert.rejects(f.run(), /Creating the Pages deployment failed/);
    assert.equal(f.counts().deployments, 1);
    assert.equal(f.counts().cancellations, 1);
    assert.ok(f.requests.at(-1).url.endsWith(`/${SHA}/cancel`));
  });

  test('a creation response without an ID can be polled by its documented build SHA', async t => {
    const f = await fixture(t, {deployment: {page_url: 'https://fixture.github.io/pages/'}});
    const result = await f.run();
    assert.equal(result.deployment_id, SHA);
    assert.equal(f.requests.at(-1).url, `/repos/fixture/pages/pages/deployments/${SHA}`);
    assert.deepEqual(f.counts(), {deployments: 1, polls: 1, cancellations: 0});
  });

  for (const pageUrl of [undefined, 'http://fixture.github.io/', 'https://secret@fixture.github.io/']) {
    test(`invalid Pages URL ${JSON.stringify(pageUrl)} triggers cleanup and cannot become an output`, async t => {
      const f = await fixture(t, {deployment: {id: 'deployment-1', page_url: pageUrl}});
      await assert.rejects(f.run(), /invalid Pages URL/);
      assert.deepEqual(f.output, {});
      assert.deepEqual(f.counts(), {deployments: 1, polls: 0, cancellations: 1});
    });
  }

  test('transient HTTP and deployment errors recover within the bounded polling loop', async t => {
    const f = await fixture(t, {polls: [503, 'deployment_attempt_error', 'succeed']});
    await f.run();
    assert.deepEqual(f.counts(), {deployments: 1, polls: 3, cancellations: 0});
  });

  for (const status of ['deployment_failed', 'deployment_content_failed', 'deployment_cancelled', 'deployment_lost']) {
    test(`terminal ${status} fails without publishing a URL or cancelling twice`, async t => {
      const f = await fixture(t, {polls: [status]});
      await assert.rejects(f.run(), new RegExp(status));
      assert.deepEqual(f.counts(), {deployments: 1, polls: 1, cancellations: 0});
      assert.deepEqual(f.output, {});
    });
  }

  test('authentication failure during polling stops immediately and cancels the pending deployment', async t => {
    const f = await fixture(t, {polls: [401, 'succeed']});
    await assert.rejects(f.run(), /Checking the Pages deployment failed \(HTTP 401\)/);
    assert.deepEqual(f.counts(), {deployments: 1, polls: 1, cancellations: 1});
  });

  test('ten HTTP failures exhaust the retry budget and cancel', async t => {
    const f = await fixture(t, {polls: Array(10).fill(503)});
    await assert.rejects(f.run(), /Checking the Pages deployment failed \(HTTP 503\)/);
    assert.deepEqual(f.counts(), {deployments: 1, polls: 10, cancellations: 1});
  });

  test('a hanging status request is aborted at the total deadline before cleanup', async t => {
    const f = await fixture(t, {polls: ['hang']});
    const started = performance.now();
    await assert.rejects(f.run({timeoutMs: 300}), /timed out/);
    assert.ok(performance.now() - started < 3000);
    assert.deepEqual(f.counts(), {deployments: 1, polls: 1, cancellations: 1});
    assert.deepEqual(f.output, {});
  });

  test('invalid status and failed cancellation both remain visible without leaking credentials', async t => {
    const f = await fixture(t, {polls: [null], cancelStatus: 500});
    await assert.rejects(f.run(), error => {
      assert.match(error.message, /invalid Pages deployment status/);
      assert.match(error.message, /Cancelling the Pages deployment failed \(HTTP 500\)/);
      assert.ok(!error.message.includes(TOKEN));
      return true;
    });
    assert.equal(f.counts().cancellations, 1);
  });

  test('OIDC failure is sanitized and never creates a deployment', async t => {
    const f = await fixture(t);
    f.clients.core.getIDToken = async () => { throw new Error(TOKEN); };
    await assert.rejects(f.run(), error => {
      assert.match(error.message, /Requesting the Pages OIDC token failed/);
      assert.ok(!error.message.includes(TOKEN));
      return true;
    });
    assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
  });

  test('an empty OIDC token cannot create a deployment', async t => {
    const f = await fixture(t);
    f.clients.core.getIDToken = async () => '';
    await assert.rejects(f.run(), /empty OIDC token/);
    assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
  });

  test('a stalled OIDC request is bounded by the total deadline', async t => {
    const f = await fixture(t);
    f.clients.core.getIDToken = () => new Promise(() => {});
    await assert.rejects(f.run({timeoutMs: 300}), /timed out/);
    assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
  });

  test('cancellation before creation never sends a deployment or cancellation request', async t => {
    const f = await fixture(t);
    f.clients.core.setSecret = () => process.emit('SIGINT');
    await assert.rejects(f.run(), /cancelled by the workflow/);
    assert.deepEqual(f.counts(), {deployments: 0, polls: 0, cancellations: 0});
  });

  for (const signal of ['SIGINT', 'SIGTERM']) {
    test(`child process handles ${signal} and cancels over HTTP (${process.platform === 'win32' ? 'Windows signal event' : 'OS signal'})`, {timeout: 10_000}, async t => {
      const f = await fixture(t);
      const worker = spawn(process.execPath, [__filename, 'child'], {
        env: {...process.env, PAGES_TEST_SERVER: f.baseUrl}, stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
      });
      t.after(() => { if (worker.exitCode === null) worker.kill(); });
      const exit = once(worker, 'exit');
      let report;
      let stderr = '';
      worker.stderr.on('data', chunk => { stderr += chunk; });
      worker.on('message', message => {
        if (message.ready) {
          if (process.platform === 'win32') worker.send({signal});
          else worker.kill(signal);
        } else report = message;
      });
      const [code] = await exit;
      assert.equal(code, 1, stderr);
      assert.match(report.error, /cancelled by the workflow/);
      assert.deepEqual(report.listeners, [0, 0]);
      assert.ok(!JSON.stringify(report).includes(TOKEN));
      assert.equal(stderr, '');
      assert.deepEqual(f.counts(), {deployments: 1, polls: 0, cancellations: 1});
    });
  }
}
