// Deploy only the artifact produced by this workflow, using the public Pages API.
// Authentication and HTTP transport are supplied by the pinned official github-script action.
const {setTimeout: sleep} = require('node:timers/promises');

const MAX_TIMEOUT_MS = 600_000;
const FINAL_FAILURES = new Set([
  'deployment_failed', 'deployment_content_failed', 'deployment_cancelled', 'deployment_lost',
]);

class DeploymentError extends Error {}

/** Reject lossy or nonnumeric IDs before they become API path parameters. */
function positiveInteger(value) {
  return /^(?:[1-9]\d*)$/.test(String(value)) && Number.isSafeInteger(Number(value));
}

/** Bind the uploaded artifact to this repository, run, and immutable commit. */
function requireArtifact(artifact, artifactId, context) {
  const run = artifact?.workflow_run;
  const repositoryId = context.payload?.repository?.id;
  if (!positiveInteger(repositoryId) || !positiveInteger(context.runId) ||
      !/^[a-f\d]{40}$/i.test(context.sha || '')) {
    throw new DeploymentError('The workflow repository, run, or commit identity is missing.');
  }
  if (artifact?.id !== artifactId || artifact.name !== 'github-pages' || artifact.expired !== false ||
      run?.id !== Number(context.runId) || run.head_sha !== context.sha ||
      run.repository_id !== Number(repositoryId) || run.head_repository_id !== Number(repositoryId)) {
    throw new DeploymentError('The Pages artifact does not match this repository, workflow run, and commit, or has expired.');
  }
}

/** Keep HTTP status while discarding SDK request bodies that can contain the OIDC token. */
function safeFailure(stage, error) {
  if (error instanceof DeploymentError) return error;
  const status = Number(error?.status);
  const suffix = Number.isInteger(status) && status >= 400 && status <= 599 ? ` (HTTP ${status})` : '';
  return new DeploymentError(`${stage} failed${suffix}. Check Pages permissions and the GitHub service status.`);
}

/** Bound awaiting even for SDK operations, such as OIDC, without abortable transports. */
function abortable(task, signal) {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const aborted = () => reject(signal.reason);
    signal.addEventListener('abort', aborted, {once: true});
    Promise.resolve().then(task).then(resolve, reject).finally(() => signal.removeEventListener('abort', aborted));
  });
}

/** Use the injected official transport with bounded requests and no automatic retries. */
function pagesRequest(github, context, defaultSignal) {
  return async (route, values = {}, signal = defaultSignal) => {
    signal.throwIfAborted();
    const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
    return abortable(() => github.request(route, {
      ...context.repo, ...values,
      headers: {'X-GitHub-Api-Version': '2026-03-10'},
      request: {signal: requestSignal, retries: 0},
    }), requestSignal);
  };
}

/** Read artifact provenance without exposing SDK errors before requesting an OIDC token. */
async function checkArtifact(request, artifactId, context) {
  let artifact;
  try {
    ({data: artifact} = await request('GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}', {artifact_id: artifactId}));
  } catch (error) {
    throw safeFailure('Reading the Pages artifact', error);
  }
  requireArtifact(artifact, artifactId, context);
}

/** Obtain and mask the job identity token without logging or persisting its value. */
async function pagesToken(core, signal) {
  try {
    const token = await abortable(() => core.getIDToken(), signal);
    if (typeof token !== 'string' || !token) throw new DeploymentError('GitHub returned an empty OIDC token.');
    core.setSecret(token);
    return token;
  } catch (error) {
    throw safeFailure('Requesting the Pages OIDC token', error);
  }
}

/** Publish only a valid HTTPS URL without embedded credentials. */
function requirePagesUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error();
    return url.href;
  } catch {
    throw new DeploymentError('GitHub returned an invalid Pages URL.');
  }
}

/** Create once; retain a cleanup identity if the service accepted a lost response. */
async function createDeployment(request, payload, state, signal) {
  let deployment;
  try {
    signal.throwIfAborted();
    // If the response is lost, the API also accepts the build SHA when cancelling.
    state.pending = true;
    ({data: deployment} = await request('POST /repos/{owner}/{repo}/pages/deployments', payload));
  } catch (error) {
    if (Number(error?.status) >= 400 && Number(error?.status) < 500) state.pending = false;
    throw safeFailure('Creating the Pages deployment', error);
  }
  if (deployment?.id !== undefined && /^[a-z\d_-]+$/i.test(String(deployment.id))) {
    state.id = String(deployment.id);
  }
  return requirePagesUrl(deployment?.page_url);
}

/** Wait for confirmed success, bounded by HTTP error count and the lifecycle deadline. */
async function pollDeployment(request, core, state, signal, pollIntervalMs) {
  let interval = pollIntervalMs;
  let errorCount = 0;
  while (true) {
    await sleep(Math.round(interval * (0.8 + Math.random() * 0.4)), undefined, {signal});
    interval = Math.min(30_000, Math.round(interval * 1.5));
    let status;
    try {
      const response = await request('GET /repos/{owner}/{repo}/pages/deployments/{pages_deployment_id}', {
        pages_deployment_id: state.id,
      });
      status = response.data?.status;
    } catch (error) {
      signal.throwIfAborted();
      errorCount += 1;
      if (errorCount >= 10 || [400, 401, 403, 422].includes(Number(error?.status))) {
        throw safeFailure('Checking the Pages deployment', error);
      }
      core.info(`Pages status request failed; retry ${errorCount}/10.`);
      continue;
    }
    if (status === 'succeed') return;
    if (FINAL_FAILURES.has(status)) {
      state.pending = false;
      throw new DeploymentError(`Pages reported ${status}.`);
    }
    // GitHub can introduce new nonterminal statuses; bound them by the same deadline.
    if (typeof status !== 'string' || !/^[a-z_]+$/.test(status)) {
      throw new DeploymentError('GitHub returned an invalid Pages deployment status.');
    }
    core.info(`Pages deployment status: ${status}.`);
  }
}

/** Cancel unfinished work within a separate cleanup budget and preserve either failure. */
async function cancelPending(request, core, state, failure) {
  if (!state.pending) return failure;
  try {
    // A separate short budget permits cleanup after timeout or a workflow signal.
    await request('POST /repos/{owner}/{repo}/pages/deployments/{pages_deployment_id}/cancel', {
      pages_deployment_id: state.id,
    }, AbortSignal.timeout(5000));
    core.info('Pending Pages deployment cancelled.');
    return failure;
  } catch (error) {
    const cleanup = safeFailure('Cancelling the Pages deployment', error);
    return new DeploymentError(`${failure?.message || 'Pages deployment failed.'} ${cleanup.message}`);
  }
}

/** Run the Pages deployment lifecycle; short timings may be supplied by HTTP integration tests. */
async function deployPages({github, core, context}, {timeoutMs = MAX_TIMEOUT_MS, pollIntervalMs = 5000} = {}) {
  const artifactText = process.env.PAGES_ARTIFACT_ID;
  if (!positiveInteger(artifactText)) throw new DeploymentError('PAGES_ARTIFACT_ID must be the uploaded artifact ID.');
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > MAX_TIMEOUT_MS ||
      !Number.isInteger(pollIntervalMs) || pollIntervalMs <= 0 || pollIntervalMs > 30_000) {
    throw new DeploymentError('Deployment timings must be positive and within the ten-minute deployment limit.');
  }
  const artifactId = Number(artifactText);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(new DeploymentError('Pages deployment timed out.')), timeoutMs);
  const interrupted = () => controller.abort(new DeploymentError('Pages deployment was cancelled by the workflow.'));
  process.on('SIGINT', interrupted);
  process.on('SIGTERM', interrupted);
  const state = {pending: false, id: context.sha};
  const request = pagesRequest(github, context, controller.signal);
  let failure;
  try {
    await checkArtifact(request, artifactId, context);
    const token = await pagesToken(core, controller.signal);
    const pageUrl = await createDeployment(request, {
      artifact_id: artifactId, pages_build_version: context.sha,
      environment: 'github-pages', oidc_token: token,
    }, state, controller.signal);
    core.info(`Pages deployment created for artifact ${artifactId}, commit ${context.sha}.`);
    await pollDeployment(request, core, state, controller.signal, pollIntervalMs);
    state.pending = false;
    core.setOutput('page_url', pageUrl);
    core.info('Pages deployment succeeded.');
    return {page_url: pageUrl, deployment_id: state.id};
  } catch (error) {
    failure = controller.signal.aborted ? controller.signal.reason : safeFailure('Pages deployment', error);
  } finally {
    clearTimeout(timeout);
    failure = await cancelPending(request, core, state, failure);
    process.removeListener('SIGINT', interrupted);
    process.removeListener('SIGTERM', interrupted);
  }
  throw failure;
}

module.exports = {deployPages};
