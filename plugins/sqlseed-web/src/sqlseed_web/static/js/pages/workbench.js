import {tr, setText, errorText, setAttr, replaceContent, UserFacingError, t, appendContent, joinText, formatNumber, formatDate, serverText} from '../i18n.js';
import '../i18n/messages/workbench.js';
import { h, api, get, store, restoreConnection } from '../api.js';
import { genLabel, paramLabel } from '../labels.js';
import { createDropdown } from '../dropdown.js';
import { readGenerationDefaults } from '../generation-defaults.js';
import { createSegmentIndicator } from '../segment-motion.js';
import { WorkbenchSession } from '../workbench/session.js';
import { openConnectionDialog } from '../workbench/connection.js';
import { openAIAssistant } from '../workbench/ai.js';
import { rememberAIHandoff, consumeAIHandoff, clearAIHandoff } from '../workbench/ai-handoff.js';
import { openDataPreview } from '../workbench/preview.js';
import { openTableData } from '../workbench/table-data.js';
import { fieldAIEligibility } from '../workbench/ai-eligibility.js';
import { remainingRun } from '../workbench/recovery.js';
import { providerGuide } from '../workbench/provider-guide.js';
import { nextStep } from '../workbench/guidance.js';
import { clearRecoveryState, clearScopeCandidate } from '../workbench/clear-recovery.js';
import { createRuleEditor } from '../workbench/editor.js';
import { createSchemaGraph } from '../workbench/graph.js';
import { button, icon, modal, download, valueText } from '../workbench/ui.js';

// The approved v8 workbench is the product surface. Models and HTTP contracts
// are reusable business logic; no legacy page, wizard or theme is mounted here.
const sessions = new Map();
const importedStructures = new Map();
const graphViews = new WeakMap();
const sidebarViews = new WeakMap();
const previewResults = new WeakMap();
const previewReturns = new WeakMap();
const executionChecks = new WeakMap();
const pendingSchemas = new Map(),
  pendingActions = new WeakMap(),
  disabledBeforeBusy = new WeakMap();
const databaseActions = new Map([[save, tr("workbench.action.save")], [showDependencies, tr("workbench.action.checkDependencies")], [showPlan, tr("workbench.action.checkDependencies")], [summary, tr("workbench.action.preparePlan")], [refreshSchema, tr("workbench.action.readSchema")], [configDocument, tr("workbench.action.readDocument")]]);
let root,
  session,
  catalog,
  notice,
  status,
  sidebar,
  content,
  graph,
  active = 0,
  openedModal;
let graphOwner = null,
  modalIntent = 0;
let tablePreview = null;
let guidanceCollapsed = true;
let guidanceIndicator = null;
let directoryMedia = null;
let providerMetadata = null,
  providerRequest = 0;
try {
  guidanceCollapsed = localStorage.getItem('sqlseed.workbench.guide.collapsed') !== 'false';
} catch {/* Storage may be unavailable. */}
let fieldQuery = '',
  columnName = '',
  inspectorMode = 'fields',
  selectedEdge = null;
const model = () => session.model;
const send = (path, body, method = 'POST') => api(path, {
  method,
  body: JSON.stringify(body)
});
// Lifecycle events update cached workbenches even while the configuration page is active.
window.addEventListener('sqlseed:draft-deleted', event => {
  for (const savedSession of sessions.values()) {
    if (savedSession.model.saved?.id === event.detail.id) {
      savedSession.model.lifecycleVersion++;
      savedSession.model.saved = null;
      savedSession.model.savedEpoch = -1;
    }
  }
  if (root?.isConnected && session) {
    updateStatus();
  }
});
window.addEventListener('sqlseed:draft-renamed', event => {
  for (const savedSession of sessions.values()) {
    if (savedSession.model.saved?.id === event.detail.id) {
      savedSession.model.lifecycleVersion++;
      savedSession.model.saved = {
        ...savedSession.model.saved,
        revision: event.detail.revision,
        name: event.detail.name
      };
      savedSession.name = event.detail.name;
    }
  }
  if (root?.isConnected && session) {
    draw();
  }
});
function ticket() {
  const version = active,
    current = session,
    document = model(),
    epoch = document.epoch,
    lifecycle = document.lifecycleVersion;
  return () => version === active && current === session && document === model() && epoch === document.epoch && lifecycle === document.lifecycleVersion;
}
function notify(text, error = false, {inputValidation = false} = {}) {
  if (notice?.isConnected) {
    setText(notice, text);
    notice.className = `wb-notice${error ? ' wb-error' : ''}`;
    notice.dataset.execution = '';
    notice.dataset.inputValidation = inputValidation ? 'true' : '';
  }
  const banner = root?.querySelector('.wb-operation-status');
  if (banner && error) {
    banner.hidden = false;
    setText(banner, text);
    banner.className = 'wb-operation-status wb-error';
    banner.dataset.inputValidation = inputValidation ? 'true' : '';
  }
}
function notifyPreviewError(error) {
  notify(errorText(error), true, {inputValidation: error.code === 'workbench_invalid_input'});
}
function deferPreviewReturn(onReturn, canReturn) {
  const version = active, owner = session, document = model();
  // Restore only after the closing modal has released its focus trap. The
  // returned callback can reopen a preview asynchronously, so observe it too.
  return Promise.resolve().then(() => {
    if (canReturn()) return onReturn();
  }).catch(error => {
    if (version === active && owner === session && document === model()) notifyPreviewError(error);
  });
}
function reportExecutionCheck(m = model()) {
  const context = executionChecks.get(m);
  if (!context || !notice?.isConnected) return;
  setText(notice, tr("workbench.clear.guidanceLocation", {status: clearRecoveryState(m, context).status}));
  notice.className = 'wb-notice';
  notice.dataset.execution = 'true';
}
function modalTicket() {
  const current = ticket(),
    intent = ++modalIntent;
  return () => current() && intent === modalIntent;
}
function action(fn, label = databaseActions.get(fn), {feedback = 'page', restoreFocusTo} = {}) {
  const listener = async (...args) => {
    const version = active,
      owner = session;
    if (!owner) {
      return;
    }
    let pending = pendingActions.get(owner);
    if (!pending) {
      pending = new Map();
      pendingActions.set(owner, pending);
    }
    const key = label ? 'database' : fn;
    if (pending.has(key)) {
      return;
    }
    const focusTarget = restoreFocusTo?.();
    const pendingAction = {label: label || tr("workbench.action.process"), feedback,
      opener: args[0]?.currentTarget || document.activeElement};
    pending.set(key, pendingAction);
    syncBusy();
    try {
      return await fn(...args);
    } catch (error) {
      if (version === active) {
        notify(errorText(error), true);
      }
    } finally {
      pending.delete(key);
      if (owner === session) {
        syncBusy();
      }
      // Closing while a request disables its opener cannot restore focus yet.
      // Retry after releasing the gate only if the user has not focused elsewhere.
      const returnTarget = pendingAction.returnFocus?.() || focusTarget;
      if (version === active && owner === session && returnTarget?.isConnected && !returnTarget.disabled &&
          (!document.activeElement || document.activeElement === document.body)) {
        returnTarget.focus({preventScroll: true});
      }
    }
  };
  listener.databaseAction = Boolean(label);
  return listener;
}
function syncBusy() {
  if (!root?.isConnected || !session) {
    return;
  }
  const pending = pendingActions.get(session)?.get('database');
  const label = pending?.label;
  const controls = [...root.querySelectorAll('[data-db-action]'), ...(openedModal?.el?.querySelectorAll('[data-db-action]') || [])];
  for (const control of controls) {
    if (label) {
      if (!disabledBeforeBusy.has(control)) {
        disabledBeforeBusy.set(control, control.disabled);
      }
      control.disabled = true;
      setAttr(control, 'aria-busy', 'true');
    } else if (disabledBeforeBusy.has(control)) {
      control.disabled = disabledBeforeBusy.get(control);
      disabledBeforeBusy.delete(control);
      control.removeAttribute('aria-busy');
    }
  }
  const banner = root.querySelector('.wb-operation-status');
  if (banner && label && pending.feedback === 'page') {
    banner.hidden = false;
    banner.className = 'wb-operation-status';
    setText(banner, tr("workbench.action.busy", {action: label}));
  } else if (banner && !banner.classList.contains('wb-error')) {
    banner.hidden = true;
  }
}
function setActionDisabled(control, disabled) {
  // Loading may finish while another render has already captured this control's
  // disabled state. Update that baseline so releasing the gate restores readiness.
  if (disabledBeforeBusy.has(control)) {
    disabledBeforeBusy.set(control, disabled);
  } else {
    control.disabled = disabled;
  }
}
function readSchema(connId) {
  if (!pendingSchemas.has(connId)) {
    const request = get(`/api/workbench/connections/${encodeURIComponent(connId)}/schema`).finally(() => pendingSchemas.delete(connId));
    pendingSchemas.set(connId, request);
  }
  return pendingSchemas.get(connId);
}
function closeComponents() {
  tablePreview?.destroy();
  tablePreview = null;
  if (graph?.getView && graphOwner) {
    graphViews.set(graphOwner, graph.getView());
  }
  graph?.destroy();
  graph = null;
  graphOwner = null;
}
function validNavigation() {
  if (model().errors.size) {
    notify(joinText([...model().errors.values()], '; '), true, {inputValidation: true});
    return false;
  }
  return true;
}
function chooseTable(name, page = 'fields', graphMode = 'paths') {
  if (!validNavigation()) {
    return;
  }
  if (!model().schema.tables.some(t => t.name === name)) {
    notify(tr("workbench.schema.external"));
    return;
  }
  closeComponents();
  graphViews.delete(model());
  model().view.imported = false;
  model().selectTable(name, page);
  if (page === 'graph') model().view.graphMode = graphMode;
  fieldQuery = '';
  columnName = '';
  selectedEdge = null;
  if (compactDirectory()) {
    const view = sidebarViews.get(model());
    if (view) view.directoryOpen = false;
    const directory = sidebar.querySelector('.wb-table-directory');
    if (directory) directory.open = false;
  }
  const rendered = drawBody();
  if (compactDirectory()) {
    content.querySelector('.table-heading h2')?.focus({preventScroll:true});
    content.scrollIntoView({block:'start'});
  } else {
    sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({block:'nearest'});
  }
  return rendered;
}
function compactDirectory() {
  return directoryMedia?.matches ?? innerWidth <= 760;
}
function syncDirectoryLayout() {
  const directory = sidebar?.querySelector('.wb-table-directory');
  if (!directory?.isConnected || !session) return;
  directory.open = !compactDirectory() || Boolean(sidebarViews.get(model())?.directoryOpen);
}
function openTableDirectory() {
  const view = sidebarViews.get(model());
  if (view) view.directoryOpen = true;
  const directory = sidebar?.querySelector('.wb-table-directory');
  if (directory) directory.open = true;
}
function locateGenerationSelection() {
  openTableDirectory();
  const entry = [...sidebar.querySelectorAll('.wb-table-entry')].find(row => !row.hidden);
  const input = entry?.querySelector('input[type="checkbox"]') || sidebar.querySelector('input[type="search"]');
  input?.focus();
  input?.scrollIntoView({
    block: 'nearest'
  });
}
function locateInputIssue(issue) {
  const m = model();
  if (issue?.kind !== 'generation-count' || !m.errors.has(issue.key) || !m.schema.tables.some(table=>table.name===issue.table)) return;
  openTableDirectory();
  // Navigating specifically to repair an invalid quantity must not be vetoed by
  // that same quantity. Keep the raw draft and every other validation error.
  if (m.view.table !== issue.table || !content.querySelector('.count-setting')?.querySelector('input')) {
    closeComponents();
    m.view.imported = false;
    m.selectTable(issue.table, 'fields');
    fieldQuery = '';columnName = '';selectedEdge = null;
    drawBody({autoPreview:false});
  }
  const input = content.querySelector('.count-setting')?.querySelector('input');
  input?.focus();input?.select?.();
  input?.scrollIntoView({block:'nearest'});
}
function clearInputValidationMessages(m) {
  if (!m.errors.size) {
    for (const message of root.querySelectorAll('[data-input-validation="true"]')) {
      setText(message, '');
      message.dataset.inputValidation = '';
      if (message.classList.contains('wb-operation-status')) message.hidden = true;
      else message.classList.remove('wb-error');
    }
  }
}
function updateStatus() {
  if (!status?.isConnected) {
    return;
  }
  const m = model();
  clearInputValidationMessages(m);
  if (notice?.dataset.execution === 'true') reportExecutionCheck(m);
  if (m.errors.size) {
    setText(status, tr("workbench.status.invalid"));
  } else if (m.dirty) {
    setText(status, tr("workbench.status.unsaved"));
  } else {
    setText(status, tr("workbench.status.saved", {revision: m.saved?.revision || 1}));
  }
  status.className = `draft-tag wb-state${m.errors.size ? ' wb-error' : ''}`;
  const errors = m.check?.issues?.filter(issue => issue.severity === 'error') || [];
  const count = root.querySelector('[data-dependency-count]');
  if (count) {
    setText(count, tr("workbench.dependency.badge", {count: errors.length ? " · " + errors.length : ''}));
  }
  root.querySelector('[data-selection-count]')?.replaceChildren(`${m.document.tables.length} / ${m.schema.tables.length}`);
  for (const control of root.querySelectorAll('[data-requires-schema]')) {
    setActionDisabled(control, !m.schema.tables.length);
  }
  updateScopeSummary(m, errors);
  updateProviderWarning();
  updateGuidance();
  syncBusy();
}
function dependencySummaryClass(errors, execution, currentExecution) {
  if (errors.length || currentExecution?.state === 'blocked') return ' needs-attention';
  return !execution || ['ok', 'reviewed'].includes(currentExecution?.state) ? ' dependency-ok' : '';
}
function updateScopeSummary(m, errors) {
  const scope = sidebar?.querySelector('.scope-summary');
  if (scope) {
    const refs = referencedTables();
    const execution = executionChecks.get(m);
    const currentExecution = execution?.epoch === m.epoch && execution.lifecycle === m.lifecycleVersion ? execution : null;
    const dependencyActionLabel = () => {
      if (generationLimitations(m.check).length) return tr('workbench.unsupported.title');
      if (execution) return clearRecoveryState(m, execution).status;
      if (errors.length) {
        return tr("workbench.dependency.blockingStatus", {count: errors.length});
      } else if (m.check?.ok) {
        return tr("workbench.dependency.appendStatus");
      } else if (m.document.tables.length) {
        return tr("workbench.dependency.unchecked");
      } else {
        return tr("workbench.dependency.noPlan");
      }
    };
    replaceContent(scope, h('div', {}, tr("workbench.scope.summary", {selected: m.document.tables.length, references: refs.size})), h('p', {
      class: `dependency-summary${dependencySummaryClass(errors, execution, currentExecution)}`,
      role:'status'
    }, dependencyActionLabel()));
  }
}
function referencedTables() {
  const m = model(),
    refs = new Set();
  for (const edge of m.schema.edges) {
    if (m.selected(edge.target) && !m.selected(edge.source)) {
      refs.add(edge.source);
    }
  }
  return refs;
}
const databaseLabel = () => model().schema.target_label.split(/[\\/]/).findLast(Boolean) || model().schema.target_label;
export function render() {
  guidanceIndicator?.destroy();
  guidanceIndicator = null;
  active++;
  providerMetadata = null;
  root = h('div', {
    class: 'page wb-page'
  }, h('p', {
    class: 'empty wb-empty'
  }, tr("workbench.schema.loading")));
  return root;
}
async function loadMountSchema(connId, cached) {
  let cachedSchemaNotice = '';
  const schemaRequest = pendingSchemas.get(connId) || (pendingActions.get(cached)?.has('database') ? cached.model.schema : readSchema(connId));
  const [schema, metadata] = await Promise.all([Promise.resolve(schemaRequest).catch(error => {
    if (!cached || error.status !== 409 || error.detail?.code !== 'connection_busy') {
      throw error;
    }
    cachedSchemaNotice = tr("workbench.schema.cached");
    return cached.model.schema;
  }), get('/api/workbench/generators')]);
  return {schema, metadata, cachedSchemaNotice};
}
function showMountFailure(error, requestedHash) {
  const mismatched = error.code === 'workbench_target_mismatch';
  const actions = mismatched ? [
    button(tr("workbench.action.returnDatabase"), () => {location.hash = '#/workbench';}, {primary:true}),
    button(tr("workbench.action.matchDatabase"), () => openConnectionDialog({workbenchRequest:requestedHash}), {glyph:'database'})
  ] : [button(tr("workbench.action.retry"), mount, {primary:true}), button(tr("workbench.action.selectDatabase"), () => openConnectionDialog({}), {glyph:'database'})];
  replaceContent(root, h('section', {
    class: 'wb-welcome'
  }, h('h2', {}, mismatched ? tr("workbench.welcome.mismatch") : tr("workbench.welcome.failed")), h('p', {
    role: 'alert'
  }, errorText(error)), ...(mismatched ? [h('p', {}, tr("workbench.welcome.mismatchHelp"))] : []), h('div', {class:'wb-welcome-actions'}, ...actions)));
}
export async function mount() {
  directoryMedia?.removeEventListener?.('change', syncDirectoryLayout);
  directoryMedia = window.matchMedia?.('(max-width: 760px)') || null;
  directoryMedia?.addEventListener?.('change', syncDirectoryLayout);
  const version = ++active,
    mountedRoot = root,
    requestedHash = location.hash;
  const currentMount = () => version === active && root === mountedRoot && root?.isConnected && location.hash === requestedHash;
  try {
    if (!store.connId) {
      await restoreConnection();
    }
    if (!currentMount()) {
      return;
    }
    if (!store.connId) {
      replaceContent(root, h('section', {
        class: 'wb-welcome'
      }, icon('database'), h('h1', {}, tr("workbench.welcome.title")), h('p', {}, tr("workbench.welcome.help")), h('div', {class:'wb-welcome-actions'}, button(tr("workbench.action.connect"), () => openConnectionDialog({workbenchRequest:requestedHash}), {
        primary: true,
        glyph: 'database'
      })), h('div', {
        class: 'wb-welcome-steps'
      }, h('span', {}, tr("workbench.welcome.scope")), h('span', {}, tr("workbench.welcome.rules")), h('span', {}, tr("workbench.welcome.generate")))));
      return;
    }
    const connId = store.connId;
    const cached = sessions.get(connId);
    const {schema, metadata, cachedSchemaNotice} = await loadMountSchema(connId, cached);
    if (!currentMount() || store.connId !== connId) {
      return;
    }
    catalog = metadata;
    adoptSchema(connId, schema);
    const restoredAI = consumeAIHandoff({
      model: session.model,
      connId,
      returnTo: location.hash
    });
    const query = new URLSearchParams(restoredAI ? '' : requestedHash.split('?')[1] || '');
    if (!(await restoreRequestedDocument(query, connId, schema)) || !currentMount() || store.connId !== connId) {
      return;
    }
    const previewOrigin = restoredAI?.previewOrigin;
    restorePreviewReturn(previewOrigin);
    draw({
      autoPreview: !previewOrigin
    });
    loadProviderStatus().catch(error => {
      if (currentMount()) notify(errorText(error), true);
    });
    if (cachedSchemaNotice) {
      notify(cachedSchemaNotice, true);
    }
    if (query.get('import')) {
      await configDocument();
    }
    if (restoredAI && currentMount()) {
      const {
        previewOrigin,
        ...aiState
      } = restoredAI;
      await openAI(aiState.scope, aiState, {
        previewOrigin
      });
    }
  } catch (error) {
    if (currentMount()) {
      showMountFailure(error, requestedHash);
    }
  }
  async function restoreRequestedDocument(query, connId, schema) {
    const owner = session,
      original = owner.model,
      epoch = original.epoch,
      lifecycle = original.lifecycleVersion;
    const currentRequest = () => currentMount() && store.connId === connId && session === owner && owner.model === original && original.epoch === epoch && original.lifecycleVersion === lifecycle;
    const draftId = query.get('draft'), runId = query.get('run');
    let requested;
    if (draftId || runId) {
      requested = await get(`/api/workbench/${draftId ? 'drafts' : 'runs'}/${encodeURIComponent(draftId || runId)}`);
      if (!currentRequest()) return false;
      // Validate before any autosave or replacement: a foreign link must not
      // write or discard this connection's cached, possibly unsaved document.
      validateRequestedTarget(requested, schema, draftId);
    }
    if (draftId || runId || query.get('new')) {
      if (original.dirty && (original.saved || original.epoch > 0)) await owner.save();
      if (!currentRequest()) return false;
    }
    if (query.get('new')) {
      session = newSession(connId, schema);
      sessions.set(connId, session);
    }
    if (draftId) session.open(requested);
    else if (runId) applyRunSnapshot(requested);
    return true;
    function applyRunSnapshot(run) {
      if (schema.target_key !== run.target_key) {
        throw new UserFacingError(tr("workbench.route.runMismatch"));
      }
      executionChecks.delete(session.model);
      if (query.get('recover') === 'remaining') {
        const recovery = remainingRun(run);
        if (!recovery.ok) {
          throw new UserFacingError(recovery.reason);
        }
        session.model.replaceDocument(recovery.document);
        session.model.view.tableDrafts = recovery.tableDrafts;
        session.model.selectTable(recovery.document.tables[0].name);
        session.name = t("workbench.snapshot.remainingName", {name: run.name || t("workbench.snapshot.defaultName")});
      } else {
        session.model.replaceDocument(run.document);
        session.name = t("workbench.snapshot.copyName", {name: run.name || t("workbench.snapshot.defaultName")});
      }
      session.model.saved = null;
    }
  }
}
function validateRequestedTarget(requested, schema, draftId) {
  if (requested.target_key === schema.target_key) return;
  const error = new UserFacingError(draftId ? tr("workbench.route.draftMismatch") : tr("workbench.route.runMismatch"));
  error.code = 'workbench_target_mismatch';
  throw error;
}
function newSession(connId, schema) {
  const owner = new WorkbenchSession(connId, schema, send);
  const defaults = readGenerationDefaults({provider:schema.provider, locale:schema.locale, count:100});
  owner.model.document.provider = defaults.provider;
  owner.model.document.locale = defaults.locale;
  // A starting count is not an edited table draft: prepopulating drafts would
  // incorrectly add untouched tables to the AI candidate configuration.
  owner.model.newTableCount = defaults.count;
  owner.model.newTableSeed = defaults.seed ?? null;
  owner.model.view.previewCount = defaults.previewCount ?? 10;
  return owner;
}
function adoptSchema(connId, schema) {
  if (session && session.connId !== connId) executionChecks.delete(session.model);
  session = sessions.get(connId);
  if (!session) {
    session = newSession(connId, schema);
    sessions.set(connId, session);
  } else {
    if (session.model.schema.schema_hash !== schema.schema_hash) {
      session.model.touch();
    }
    session.model.schema = schema;
  }
}
function restorePreviewReturn(previewOrigin) {
  if (previewOrigin?.scope === 'current' && session.model.view.page === 'preview' && session.model.view.table === previewOrigin.table) {
    previewReturns.set(session.model, {
      table: previewOrigin.table,
      view: previewOrigin.view
    });
  }
}
export function unmount() {
  directoryMedia?.removeEventListener?.('change', syncDirectoryLayout);
  directoryMedia = null;
  guidanceIndicator?.destroy();
  guidanceIndicator = null;
  active++;
  closeComponents();
  openedModal?.close();
  openedModal = null;
  // The close callback runs first; leaving ends this temporary adjustment flow.
  if (session) executionChecks.delete(session.model);
}
function draw(options = {}) {
  guidanceIndicator?.destroy();
  guidanceIndicator = null;
  closeComponents();
  status = h('span', {
    class: 'draft-tag wb-state'
  });
  const checkButton = button('', action(showDependencies), {
    glyph: 'check',
    'data-requires-schema': ''
  });
  appendContent(checkButton, h('span', {
    'data-dependency-count': ''
  }, tr("workbench.dependency.title")));
  sidebar = h('aside', {
    class: 'sidebar wb-sidebar'
  });
  content = h('div', {
    class: 'main wb-content'
  });
  replaceContent(root, h('section', {
    class: 'heading'
  }, h('div', {
    class: 'title-line'
  }, h('h1', {}, button(session.name, renameConfig, {
    plain: true,
    class: 'title-button wb-config-name',
    'aria-label': tr("workbench.config.rename"),
    title: session.name,
    glyph: 'edit'
  })), status), h('div', {
    class: 'heading-actions',
    role: 'group',
    'aria-label': tr("workbench.config.actions")
  }, button(tr("workbench.ai.title"), () => openAI(model().document.tables.length ? 'selected' : 'current'), {
    glyph: 'sparkles',
    'data-requires-schema': ''
  }), checkButton, button(tr("workbench.action.viewPlan"), action(summary), {
    'data-plan-entry':'',
    'data-requires-schema': '',
    glyph: 'database',
    primary: true,
    title: tr("workbench.action.viewPlanHelp")
  }))), h('p', {
    class: 'wb-operation-status',
    role: 'status',
    'aria-live': 'polite',
    hidden: true
  }), h('div', {
    class: 'wb-config-context'
  }, h('div', {
    class: 'wb-config-tools',
    role: 'group',
    'aria-label': tr("workbench.config.management")
  }, button(tr("workbench.action.save"), action(save), {
    glyph: 'save'
  }), button(tr("workbench.config.open"), action(openDrafts), {
    glyph: 'folder'
  }), button(tr("workbench.config.editYaml"), action(configDocument, undefined, {
    feedback: 'dialog', restoreFocusTo: () => root.querySelector('.wb-config-document')
  }), {
    glyph: 'code',
    class: 'wb-config-document',
    title: tr("workbench.config.editYamlHelp")
  })), h('section', {
    class: 'wb-generation-settings',
    'aria-label': tr("workbench.defaults.title")
  }, h('span', {
    class: 'wb-settings-heading',
    title: tr("workbench.defaults.scope")
  }, icon('settings'), tr("workbench.defaults.global")), button('', action(configSettings), {
    plain: true,
    class: 'wb-setting-tile',
    'aria-label': tr("workbench.defaults.engineLabel")
  }), button('', action(configSettings), {
    plain: true,
    class: 'wb-setting-tile',
    'aria-label': tr("workbench.defaults.localeLabel")
  })), h('div', {
    class: 'wb-settings-note',
    'data-provider-warning': '',
    role: 'status',
    hidden: true
  })), h('section', {
    class: 'wb-next-step',
    'aria-label': tr("workbench.guide.label")
  }), h('section', {
    class: 'workspace wb-workspace',
    'aria-label': tr("workbench.page.label")
  }, sidebar, content));
  const tiles = root.querySelectorAll('.wb-setting-tile');
  appendContent(tiles[0], h('small', {}, tr("workbench.defaults.engine")), h('strong', {}, model().document.provider || tr("workbench.defaults.automatic")), h('span', {}, tr("workbench.defaults.change")));
  appendContent(tiles[1], h('small', {}, tr("workbench.defaults.locale")), h('strong', {}, model().document.locale || 'en_US'), h('span', {}, tr("workbench.defaults.change")));
  drawBody(options);
}
async function loadProviderStatus() {
  const version = active,
    owner = session,
    request = ++providerRequest;
  let response = null;
  try {
    response = await get('/api/meta/providers');
  } catch {/* Preserve configuration when metadata is unavailable. */}
  if (version !== active || owner !== session || request !== providerRequest) {
    return;
  }
  providerMetadata = response;
  updateProviderWarning();
}
function updateProviderWarning() {
  const host = root?.querySelector('[data-provider-warning]');
  if (!host || !session) {
    return;
  }
  const m = model(),
    fields = m.schema.tables.flatMap(table => (m.table(table.name).columns || []).filter(column => column.provider === 'mimesis' || column.mimesis_method || column.native_mimesis_method).map(column => ({
      table,
      column
    })));
  const selected = m.document.provider === 'mimesis';
  const capability = providerMetadata?.statuses?.mimesis;
  const unavailable = capability ? capability.available === false : providerMetadata?.available && !providerMetadata.available.includes('mimesis');
  host.hidden = !(unavailable && (selected || fields.length));
  if (host.hidden) {
    replaceContent(host);
    return;
  }
  const broken = capability?.status === 'import_error';
  const fieldNames = fields.slice(0, 3).map(({
    table,
    column
  }) => `${table.name}.${column.name}`).join('、');
  function fieldOverrideHint() {
    if (fields.length) {
      return [h('p', {}, tr("workbench.defaults.overrides", {fields: fieldNames, additional: fields.length > 3 ? tr("workbench.defaults.additionalFields", {count: fields.length}) : ''}))];
    } else {
      return [];
    }
  }
  replaceContent(host, h('p', {
    class: 'wb-error'
  }, tr("workbench.defaults.mimesisUnavailable", {status: broken ? tr("workbench.component.importError") : tr("workbench.component.notInstalled")})), ...fieldOverrideHint(), button(tr("workbench.component.manage"), () => {
    if (host.isConnected) {
      location.hash = '#/settings?section=plugins';
    }
  }, {
    small: true
  }), button(tr("workbench.defaults.changeEngine"), () => {
    if (!host.isConnected) {
      return;
    }
    if (selected) {
      return action(configSettings)();
    }
    const {
        table,
        column
      } = fields[0],
      schemaColumn = table.columns.find(value => value.name === column.name);
    if (schemaColumn) {
      openRule(table, schemaColumn);
    }
  }, {
    small: true
  }));
}
function guidanceStep(m, recommended) {
  const selectedStage = m.view.guideEpoch === m.epoch ? m.view.guideStage : null;
  const stage = selectedStage || recommended.stage;
  let step = recommended;
  if (selectedStage && recommended.stage === 1 && ['select','edit','check'].includes(recommended.action)) {
    let stageName = tr("workbench.guide.rules");
    if (selectedStage === 2) stageName = tr("workbench.guide.preview");
    else if (selectedStage === 3) stageName = tr("workbench.guide.confirm");
    step = {...recommended, body: tr("workbench.guide.beforeStage", {stage: stageName, help: recommended.body})};
  } else if (selectedStage === 1) {
    step = {...recommended, title:tr("workbench.guide.editTitle"), body:tr("workbench.guide.editHelp"), action:'edit', label:tr("workbench.guide.editAction")};
  } else if (selectedStage === 2) {
    step = {...recommended, title:recommended.stage === 2 ? recommended.title : tr("workbench.guide.previewTitle"), body:tr("workbench.guide.previewHelp"), action:'preview', label:tr("workbench.guide.previewAction")};
  } else if (selectedStage === 3) {
    step = {...recommended, title:tr("workbench.guide.confirmTitle"), body:tr("workbench.guide.confirmHelp"), action:'generate', label:tr("workbench.action.viewPlan")};
  }
  return {stage, step};
}
function showGuidanceRecovery(host, m, clearContext) {
  if (generationLimitations(m.check).length) {
    guidanceIndicator?.destroy(); guidanceIndicator = null;
    host.hidden = false;
    const globalPlan = root.querySelector('[data-plan-entry]');
    if (globalPlan) globalPlan.hidden = true;
    replaceContent(host, generationUnsupportedCard(m.check));
    return true;
  }
  if (clearContext) {
    guidanceIndicator?.destroy();
    guidanceIndicator = null;
    host.hidden = false;
    const globalPlan = root.querySelector('[data-plan-entry]');
    if (globalPlan) globalPlan.hidden = true;
    replaceContent(host, clearRecoveryCard(m, {
      inspect: action(summary),
      review: action(reviewClearScope, tr("workbench.clear.reviewScope"), {feedback:'modal'}),
      append: () => {
        executionChecks.delete(m);
        notify(tr("workbench.clear.switchedAppend"));
        updateStatus();
        root.querySelector('[data-guide-action="next"]')?.focus();
      },
      adjust: locateGenerationSelection,
      locate: name => chooseTable(name, 'graph')
    }));
    return true;
  }
  return false;
}
function updateGuidance({animateStage = false} = {}) {
  if (!root?.isConnected) {
    return;
  }
  const host = root?.querySelector('.wb-next-step');
  if (!host || !session) {
    return;
  }
  const m = model(), recommended = nextStep(m, previewResults.get(m));
  const clearContext = executionChecks.get(m);
  if (showGuidanceRecovery(host, m, clearContext)) return;
  const {stage, step} = guidanceStep(m, recommended);
  host.hidden = !m.schema.tables.length || Boolean(m.view.imported);
  const globalPlan = root.querySelector('[data-plan-entry]');
  if (globalPlan) globalPlan.hidden = !host.hidden && (!guidanceCollapsed || step.action === 'generate');
  const focused = host.contains?.(document.activeElement) ? document.activeElement?.dataset.guideAction : null;
  const currentSelected = () => m.selected(m.view.table) ? m.view.table : m.document.tables[0]?.name || m.view.table;
  const edit = () => {
    if (m.errors.size) {
      const issue = m.inputIssues().find(issue=>issue.kind==='generation-count');
      if (issue) {locateInputIssue(issue);return;}
      const input = content.querySelector('[aria-invalid="true"]') || content.querySelector('.count-setting input');
      input?.focus();
      input?.scrollIntoView({
        block: 'nearest'
      });
      return;
    }
    chooseTable(currentSelected(), 'fields');
    [...content.querySelectorAll('.wb-rule-button')].find(control => !control.disabled)?.focus();
  };
  const preview = () => m.document.tables.length > 1 ? refreshSamples() : chooseTable(currentSelected(), 'preview');
  const handlers = {
    select: locateGenerationSelection,
    edit,
    preview: action(preview),
    check: action(showDependencies),
    generate: action(summary)
  };
  const toggle = button(guidanceCollapsed ? tr("workbench.guide.expand") : tr("workbench.guide.collapse"), () => {
    guidanceCollapsed = !guidanceCollapsed;
    try {
      localStorage.setItem('sqlseed.workbench.guide.collapsed', String(guidanceCollapsed));
    } catch {/* Keep the in-memory preference. */}
    updateGuidance();
    syncBusy();
    host.querySelector('[data-guide-action="toggle"]')?.focus();
  }, {
    plain: true,
    small: true,
    'aria-expanded': String(!guidanceCollapsed),
    'aria-controls': 'wb-next-step-body',
    'data-guide-action': 'toggle'
  });
  const actions = h('div', {
    class: 'wb-next-step-actions'
  }, button(step.label, handlers[step.action], {
    primary:true,
    small: true,
    glyph: 'arrow',
    'data-guide-action': 'next',
    ...(['preview', 'check', 'generate'].includes(step.action) ? {
      'data-db-action': ''
    } : {})
  }));
  const navigateStage = async index => {
    m.view.guideStage = index; m.view.guideEpoch = m.epoch;
    updateGuidance({animateStage: true});
    const blocked = !m.document.tables.length || m.errors.size || m.check?.issues?.some(issue => issue.severity === 'error');
    if (blocked) {
      if (!m.document.tables.length) locateGenerationSelection();
      else if (m.errors.size) edit();
      else await handlers.check();
    } else if (index === 1) {
      edit(); content.scrollIntoView({block:'nearest'});
    } else if (index === 2) {
      await handlers.preview();
      if (m.document.tables.length === 1) content.querySelector('.wb-table-preview')?.scrollIntoView({block:'nearest'});
    } else await handlers.generate();
    updateGuidance();
  };
  const stages = [
    [tr("workbench.guide.rules"), tr("workbench.guide.rulesDescription"), tr("workbench.guide.rulesLabel"), tr('workbench.guide.rulesShort')],
    [tr("workbench.guide.preview"), tr("workbench.guide.previewDescription"), tr("workbench.guide.previewLabel"), tr('workbench.guide.previewShort')],
    [tr("workbench.guide.confirm"), tr("workbench.guide.confirmDescription"), tr("workbench.guide.confirmLabel"), tr('workbench.guide.confirmShort')]
  ];
  const previousBody = host.querySelector('#wb-next-step-body');
  let stageList = host.querySelector('.wb-guide-stages');
  if (!stageList) {
    stageList = h('ol', { class: 'wb-guide-stages', 'aria-label': tr("workbench.guide.flow") },
      ...stages.map(([label, description], index) => h('li', {}, h('button', {
        type:'button',
        'data-guide-action':`stage-${index + 1}`,
        ...(index ? {'data-db-action':''} : {})
      }, h('span', {'aria-hidden':'true', class:'wb-guide-number'}, String(index + 1)), h('span', {class:'wb-guide-label'}, h('strong', {}, label), h('small', {}, description))))));
  }
  // Preserve the buttons and their decorative plate across guidance updates.
  // Callbacks use this render's model/handlers; selection itself commits now.
  stageList.dataset.compact = String(guidanceCollapsed);
  [...stageList.querySelectorAll('button')].forEach((control, index) => {
    control.onclick = () => navigateStage(index + 1);
    setAttr(control, 'title', stages[index][2]);
    setAttr(control, 'aria-label', stages[index][0]);
    setText(control.querySelector('strong'), stages[index][guidanceCollapsed ? 3 : 0]);
    const detail = control.querySelector('small');
    detail.hidden = guidanceCollapsed;
    if (index + 1 === stage) control.setAttribute('aria-current', 'step');
    else control.removeAttribute('aria-current');
  });
  const description = h('div', {class:'wb-guide-description'}, h('p', {}, step.body));
  const heading = h('div', {class:'wb-next-step-heading'},
    h('div', {class:'wb-guide-heading'},
      h('strong', {class:'wb-guide-current'}, tr('workbench.guide.currentStage', {stage, title:stages[stage - 1][0]})),
      h('h3', {'aria-live':'polite'}, step.title), h('span', {}, step.scope)), toggle);
  renderGuidanceBody(host, previousBody, {heading, stageList, description, actions});
  guidanceIndicator?.update({animate: animateStage});
  if (focused) {
    const target = host.querySelector(`[data-guide-action="${focused}"]`);
    if (target !== document.activeElement) target?.focus({preventScroll: true});
  }
}
function renderGuidanceBody(host, previousBody, {heading, stageList, description, actions}) {
  if (previousBody) {
    previousBody.hidden = guidanceCollapsed;
    if (guidanceCollapsed) previousBody.setAttribute('hidden', '');
    else previousBody.removeAttribute('hidden');
    host.querySelector('.wb-next-step-heading').replaceWith(heading);
    previousBody.querySelector('.wb-guide-description').replaceWith(description);
    host.querySelector('.wb-next-step-actions').replaceWith(actions);
  } else {
    const body = h('div', {
      id: 'wb-next-step-body',
      class: 'wb-next-step-body',
      hidden: guidanceCollapsed
    }, h('div', {
      class: 'wb-next-step-main'
    }, description));
    body.hidden = guidanceCollapsed;
    replaceContent(host, h('div', {class:'wb-next-step-summary'}, heading, actions), stageList, body);
    guidanceIndicator?.destroy();
    guidanceIndicator = createSegmentIndicator(stageList);
  }
}
function needsAIDefaultPreflight(m) {
  const mappings = m.document.custom_column_mappings;
  const custom = Object.keys(mappings?.exact || {}).length || mappings?.pattern?.length;
  return m.schema.tables.some(table => table.columns.some(column => column.default !== null && column.default !== undefined) && (custom || m.table(table.name).enrich));
}
async function openAI(initialScope = 'current', initialState = null, {
  previewOrigin = null
} = {}) {
  clearAIHandoff();
  const current = modalTicket(),
    m = model(),
    version = active,
    owner = session;
  if (!validNavigation()) {
    return;
  }
  const onReturn = previewOrigin ? previewReturnHandler(owner, m, previewOrigin) : null;
  const intent = modalIntent;
  let suppressReturn = false;
  const returnToPreview = () => {
    if (onReturn) {
      return deferPreviewReturn(onReturn, () => !suppressReturn && intent === modalIntent);
    }
  };
  function goAISettings({
    section,
    context
  }) {
    if (!current()) {
      return;
    }
    suppressReturn = true;
    const returnTo = location.hash.startsWith('#/workbench') ? location.hash : '#/workbench';
    rememberAIHandoff({
      model: m,
      connId: owner.connId,
      returnTo,
      context: previewOrigin ? {
        ...context,
        previewOrigin
      } : context
    });
    location.hash = `#/settings?section=${section}`;
  }
  let defaultModes;
  if (needsAIDefaultPreflight(m)) {
    if (!(await resolveDefaultModes()) || !current()) {
      return;
    }
  }
  openedModal = openAIAssistant({
    model: m,
    catalog,
    defaultModes,
    connId: session.connId,
    isCurrent: current,
    initialScope: typeof initialScope === 'string' ? initialScope : 'current',
    initialState,
    onSettings: goAISettings,
    onClose: () => {
      if (version === active && owner === session) {
        updateGuidance();
        syncBusy();
      }
      return returnToPreview();
    },
    onApply: suggestions => {
      if (!current()) {
        throw new UserFacingError(tr("workbench.ai.stale"));
      }
      for (const item of suggestions) {
        if (!m.schema.tables.find(t => t.name === item.table)?.columns.some(c => c.name === item.column)) {
          throw new UserFacingError(tr("workbench.ai.fieldStale"));
        }
      }
      m.applyPatches(suggestions);
      m.aiApplied = {
        epoch: m.epoch,
        targets: suggestions.map(item => ({
          table: item.table,
          column: item.column
        }))
      };
      if (!onReturn) {
        drawBody();
      } else {
        updateStatus();
      }
      notify(tr("workbench.ai.applied", {count: suggestions.length}));
    }
  });
  async function resolveDefaultModes() {
    let cancelled = false;
    const loading = openedModal = modal(tr("workbench.ai.title"), {
      dismiss: 'footer',
      onClose: () => {
        cancelled = true;
        if (!suppressReturn) {
          return returnToPreview();
        }
      }
    });
    appendContent(loading.body, h('p', {
      role: 'status'
    }, tr("workbench.ai.resolving")));
    appendContent(loading.actions, button(tr("workbench.action.cancel"), loading.close));
    try {
      const result = await send('/api/workbench/ai/eligibility', {
        conn_id: owner.connId,
        schema_hash: m.schema.schema_hash,
        document: m.document,
        table_drafts: Object.values(m.view.tableDrafts)
      });
      if (cancelled || !current()) {
        loading.close();
        return false;
      }
      if (result.schema_hash !== m.schema.schema_hash) {
        throw new UserFacingError(tr("workbench.ai.schemaStale"));
      }
      defaultModes = result.default_modes;
      suppressReturn = true;
      loading.close();
      suppressReturn = false;
    } catch (error) {
      if (!cancelled && current()) {
        const unavailable = error.status === 503 && error.detail?.code === 'ai_unavailable';
        const aiUnavailableMessage = () => {
          if (unavailable) {
            return tr("workbench.ai.unavailable", {status: error.detail.availability_status === 'import_error' ? tr("workbench.component.importError") : tr("workbench.component.notInstalled"), action: error.detail.availability_status === 'import_error' ? tr("workbench.component.inspectError") : tr("workbench.component.install")});
          } else {
            return errorText(error);
          }
        };
        replaceContent(loading.body, h('p', {
          role: 'alert'
        }, aiUnavailableMessage()));
        if (unavailable) {
          appendContent(loading.actions, button(tr("workbench.component.openSettings"), () => {
            if (cancelled || !current()) {
              return;
            }
            goAISettings({
              section: 'plugins',
              context: {
                scope: typeof initialScope === 'string' ? initialScope : 'current',
                currentTable: m.view.table,
                businessContext: '',
                ...initialState
              }
            });
            loading.close();
          }, {
            primary: true
          }));
        }
      } else {
        loading.close();
      }
      return false;
    }
    return true;
  }
}
function renameConfig() {
  modalIntent++;
  const current = ticket(),
    dialog = openedModal = modal(tr("workbench.config.rename"), { dismiss: 'footer' });
  const input = h('input', {
    'aria-label': tr("workbench.config.name"),
    value: session.name,
    maxlength: 120
  });
  const error = h('p', {
    class: 'wb-error',
    role: 'alert'
  });
  appendContent(dialog.body, h('label', {
    class: 'control'
  }, tr("workbench.config.name"), input), error);
  appendContent(dialog.actions, button(tr("workbench.action.cancel"), dialog.close), button(tr("workbench.action.confirm"), () => {
    if (!current()) {
      dialog.close();
      return;
    }
    if (!input.value.trim()) {
      setText(error, tr("workbench.config.nameRequired"));
      return;
    }
    session.name = input.value.trim();
    model().touch();
    dialog.close();
    draw();
  }, {
    primary: true
  }));
  input.focus();
}
function drawSidebar() {
  const m = model(),
    refs = referencedTables();
  const view = sidebarViews.get(m) || {
    structureOpen: false,
    directoryOpen: false,
    query: ''
  };
  sidebarViews.set(m, view);
  const previousMenu = sidebar.querySelector('.wb-structure-menu');
  if (previousMenu) {
    view.structureOpen = previousMenu.open;
  }
  const previousDirectory = sidebar.querySelector('.wb-table-directory');
  if (previousDirectory && compactDirectory()) view.directoryOpen = previousDirectory.open;
  const scrollTop = sidebar.querySelector('.wb-table-list')?.scrollTop || 0;
  function tableGenerationLabel(table) {
    if (m.errors.has(`count:${table.name}`)) return tr("workbench.count.invalid");
    if (m.selected(table.name)) {
      return tr("workbench.count.generateRows", {count: m.table(table.name).count});
    } else if (refs.has(table.name)) {
      return tr("workbench.scope.reference");
    } else {
      return tr("workbench.scope.excluded");
    }
  }
  replaceContent(sidebar, h('div', {
    class: 'source'
  }, button(databaseLabel(), () => {
    if (!validNavigation()) {
      return;
    }
    closeComponents();
    graphViews.delete(m);
    m.view.imported = false;
    m.view.page = 'graph';
    m.view.graphMode = 'all';
    selectedEdge = null;
    drawBody();
  }, {
    glyph: 'database',
    plain: true,
    class: 'source-head wb-source',
    title: tr("workbench.schema.viewAll")
  }), h('div', {
    class: 'source-note'
  }, tr("workbench.connection.connected", {dialect: m.schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'}), button('ⓘ', connectionInfo, {
    plain: true,
    class: 'source-info',
    'aria-label': tr("workbench.connection.details")
  })), h('details', {
    class: 'wb-structure-menu',
    open: view.structureOpen,
    ontoggle: event => {
      view.structureOpen = event.currentTarget.open;
    }
  }, h('summary', {}, icon('fields'), tr("workbench.schema.actions")), h('div', {
    class: 'wb-structure-commands',
    role: 'group',
    'aria-label': tr("workbench.schema.actions")
  }, h('small', {}, tr("workbench.schema.counts", {tables: m.schema.tables.length, edges: m.schema.edges.length})), button(tr("workbench.schema.refresh"), action(refreshSchema), {
    small: true,
    glyph: 'refresh',
    title: tr("workbench.schema.refreshHelp")
  }), button(tr("workbench.schema.exportGraph"), () => download('sqlseed-schema.json', JSON.stringify(structureSnapshot(), null, 2)), {
    small: true,
    glyph: 'download'
  }), button(tr("workbench.schema.importGraph"), action(importStructure), {
    small: true,
    glyph: 'upload'
  }), ...(importedStructures.has(session.connId) ? [button(tr("workbench.schema.viewImported"), () => {
    m.view.imported = true;
    drawBody();
  }, {
    small: true,
    glyph: 'schema'
  })] : [])))), h('div', {
    class: 'sidebar-label'
  }, h('span', {}, tr("workbench.scope.tables")), h('span', {
    'data-selection-count': ''
  }, `${m.document.tables.length} / ${m.schema.tables.length}`)), h('div', {
    class: 'selection-actions'
  }, button(tr("workbench.scope.selectAll"), () => {
    if (!validNavigation()) {
      return;
    }
    m.schema.tables.forEach(t => m.toggleTable(t.name, true));
    drawBody();
  }, {
    small: true,
    disabled: !m.schema.tables.length
  }), button(tr("workbench.scope.clearSelection"), () => {
    if (!validNavigation()) {
      return;
    }
    m.schema.tables.forEach(t => m.toggleTable(t.name, false));
    drawBody();
  }, {
    small: true,
    disabled: !m.schema.tables.length
  })), h('label', {
    class: 'search wb-table-search'
  }, icon('search'), h('input', {
    type: 'search',
    placeholder: tr("workbench.scope.search"),
    'aria-label': tr("workbench.scope.search"),
    disabled: !m.schema.tables.length,
    value: view.query,
    oninput: event => {
      view.query = event.target.value;
      filterTables();
    }
  })), h('div', {
    class: 'tables wb-table-list'
  }, ...m.schema.tables.map(table => h('div', {
    class: `table-entry wb-table-entry${m.view.table === table.name ? ' active' : ''}`,
    'data-table': table.name
  }, h('label', {class:'wb-table-select', title:tr('workbench.scope.generateTable', {table:table.name})}, h('input', {
    type: 'checkbox',
    checked: m.selected(table.name),
    'aria-label': tr("workbench.scope.generateTable", {table: table.name}),
    onchange: e => {
      if (!validNavigation()) {
        e.target.checked = m.selected(table.name);
        return;
      }
      m.toggleTable(table.name, e.target.checked);
      drawBody();
    }
  })), h('button', {
    class: 'table-button wb-table-name',
    title: tr("workbench.scope.fieldRules", {table: table.name}),
    onclick: () => chooseTable(table.name)
  }, h('span', {
    class: 'table-name'
  }, table.name), h('span', {
    class: 'count'
  }, tableGenerationLabel(table))), button('', () => chooseTable(table.name, 'graph'), {
    glyph: 'relations',
    plain: true,
    class: `table-graph-shortcut wb-table-graph${m.view.table === table.name && m.view.page === 'graph' ? ' active' : ''}`,
    title: tr("workbench.scope.fullPath", {table: table.name}),
    'aria-label': tr("workbench.scope.path", {table: table.name}),
    'aria-pressed': String(m.view.table === table.name && m.view.page === 'graph')
  })))), ...(m.document.tables.length > 1 ? [button(tr("workbench.preview.selected"), action(refreshSamples), {
    glyph: 'fields',
    small: true,
    class: 'wb-batch-preview',
    'data-db-action': '',
    title: tr("workbench.preview.selectedHelp", {count: m.document.tables.length})
  })] : []), h('div', {
    class: 'scope-summary',
    'aria-live': 'polite'
  }));
  function filterTables() {
    for (const row of sidebar.querySelectorAll('.wb-table-entry')) {
      row.hidden = !row.dataset.table.toLowerCase().includes(view.query.trim().toLowerCase());
    }
  }
  filterTables();
  sidebar.querySelector('.wb-table-list').scrollTop = scrollTop;
  const directoryContent = h('div', {class:'wb-table-directory-content'});
  directoryContent.append(...sidebar.childNodes);
  const directory = h('details', {
    class:'wb-table-directory',
    ontoggle: event => {
      if (event.currentTarget.isConnected && compactDirectory()) view.directoryOpen = event.currentTarget.open;
    }
  }, h('summary', {class:'wb-table-directory-summary'}, h('span', {},
    h('strong', {}, tr('workbench.scope.viewing', {table:m.view.table || tr('workbench.scope.noTable')})),
    h('small', {}, tr('workbench.scope.selectedCount', {count:m.document.tables.length})))), directoryContent);
  directory.open = !compactDirectory() || Boolean(view.directoryOpen);
  replaceContent(sidebar, directory);
}
function connectionInfo() {
  modalIntent++;
  const dialog = openedModal = modal(tr("workbench.connection.current"));
  appendContent(dialog.body, h('dl', {
    class: 'wb-key-values'
  }, h('dt', {}, tr("workbench.connection.target")), h('dd', {
    class: 'mono'
  }, model().schema.target_label), h('dt', {}, tr("workbench.connection.dialect")), h('dd', {}, model().schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'), h('dt', {}, tr("workbench.connection.status")), h('dd', {}, tr("workbench.connection.available"))));
  appendContent(dialog.actions, button(tr("workbench.connection.switch"), () => {
    dialog.close();
    document.getElementById('connection-button')?.click();
  }));
}
function viewCurrentData(tableName = null) {
  const current = modalTicket(),
    owner = session,
    m = model(),
    table = typeof tableName === 'string' ? tableName : m.view.table;
  const viewer = openTableData({
    connId: owner.connId,
    table,
    targetKey: m.schema.target_key,
    targetLabel: m.schema.target_label,
    isCurrent: () => current() && session === owner && model() === m &&
      (typeof tableName === 'string' || m.view.table === table) && m.schema.tables.some(item => item.name === table)
  });
  openedModal = viewer.dialog;
}
function generationCountControl(table) {
  const m = model();
  const countHelp = tr("workbench.count.help");
  const changeCount = e => {
    const valid = m.setCount(table.name, e.target.value);
    setAttr(e.target, 'aria-invalid', valid ? 'false' : 'true');
    setAttr(e.target, 'title', valid ? countHelp : joinText([e.target.value || tr("workbench.count.empty"), m.errors.get(`count:${table.name}`)], ': '));
    const row = [...sidebar.querySelectorAll('.wb-table-entry')].find(entry=>entry.dataset.table===table.name);
    const label = row?.querySelector('.count');
    if (label && (!valid || m.selected(table.name))) setText(label, valid ? tr("workbench.count.generateRows", {count: m.table(table.name).count}) : tr("workbench.count.invalid"));
    else if (label) drawSidebar();
    if (m.view.page === 'preview') {
      tablePreview?.destroy();
      tablePreview = null;
      content.querySelector('.wb-table-preview')?.replaceChildren(h('p', {
        class: 'wb-preview-help'
      }, tr("workbench.count.changed")));
    }
    updateStatus();
  };
  const count = h('input', {
    type: 'number',
    min: 1,
    max: Number.MAX_SAFE_INTEGER,
    step: 1,
    value: m.view.invalidCounts?.[table.name] ?? m.table(table.name).count,
    disabled: !m.selected(table.name) && !m.errors.has(`count:${table.name}`),
    title: m.errors.get(`count:${table.name}`) || countHelp,
    'aria-invalid': m.errors.has(`count:${table.name}`) ? 'true' : 'false',
    'aria-label': tr("workbench.count.label", {table: table.name}),
    oninput: changeCount
  });
  const stepCount = delta => {
    const value = Number(count.value);
    if (!/^\d+$/.test(String(count.value)) || !Number.isSafeInteger(value) || value < 1 || !Number.isSafeInteger(value + delta)) {
      count.focus();
      return;
    }
    const next = Math.max(1, value + delta);
    if (next === value) return;
    count.value = String(next);
    changeCount({target:count});
  };
  return h('span', {class:'wb-number-control'}, count, h('span', {class:'wb-number-actions'},
    button('+', () => stepCount(1), {plain:true, disabled:count.disabled, 'aria-label':tr("workbench.count.increase", {table: table.name})}),
    button('−', () => stepCount(-1), {plain:true, disabled:count.disabled, 'aria-label':tr("workbench.count.decrease", {table: table.name})})));
}
function drawBody({
  autoPreview = true
} = {}) {
  if (!root?.isConnected) {
    return;
  }
  closeComponents();
  const m = model(),
    table = m.schema.tables.find(t => t.name === m.view.table) || m.schema.tables[0];
  // Refreshing an empty database (or removing the viewed table externally)
  // must make the newly available structure reachable without changing scope.
  if (table) m.view.table = table.name;
  drawSidebar();
  replaceContent(content);
  const imported = importedStructures.get(session.connId);
  if (m.view.imported && imported) {
    drawImportedStructure(imported);
    appendStatus();
    updateStatus();
    return;
  }
  if (!table) {
    appendContent(content, h('section', {
      class: 'empty wb-empty-schema',
      'aria-label': tr("workbench.schema.emptyTitle")
    }, h('h2', {}, tr("workbench.schema.emptyHeading")),
    h('p', {}, tr("workbench.schema.emptyHelp")),
    h('div', {class:'wb-welcome-actions'},
      button(tr("workbench.schema.refresh"), action(refreshSchema), {primary:true, glyph:'refresh'}),
      button(tr("workbench.connection.other"), () => openConnectionDialog(), {glyph:'database', 'data-db-action':''}))));
    appendStatus();
    updateStatus();
    return;
  }
  const countControl = generationCountControl(table);
  appendContent(content, h('div', {
    class: 'table-heading'
  }, h('div', {
    class: 'table-title'
  }, h('h2', {tabindex:-1}, table.name), h('span', {
    class: 'desc'
  }, tr("workbench.table.summary", {fields: table.columns.length, rows: table.row_count})), button(tr("workbench.table.currentData"), viewCurrentData, {
    plain: true,
    small: true,
    class: 'wb-view-current-data',
    'data-db-action': ''
  })), h('div', {
    class: 'table-actions'
  }, ...(!m.selected(table.name) ? [button(tr("workbench.table.include"), () => {
    m.toggleTable(table.name, true);
    drawBody();
  }, {
    small: true
  })] : []), h('label', {
    class: 'count-setting'
  }, tr("workbench.count.title"), countControl, h('span', {}, tr("workbench.count.unit"))))));
  const pages = [['fields', tr("workbench.tab.rules")], ['preview', tr("workbench.tab.preview")], ['graph', tr("workbench.tab.graph")]];
  const tabs = h('div', {
    class: 'tabs',
    role: 'tablist',
    'aria-label': tr("workbench.tab.label")
  });
  for (const [page, label] of pages) {
    appendContent(tabs, button(label, () => {
      const rendered = chooseTable(m.view.table, page, m.view.graphMode === 'paths' ? 'plan' : m.view.graphMode || 'plan');
      root.querySelector(`#wb-table-tab-${page}`)?.focus();
      return rendered;
    }, {
      plain: true,
      role: 'tab',
      id: `wb-table-tab-${page}`,
      'aria-controls': 'wb-table-panel',
      'aria-selected': String(m.view.page === page),
      tabindex: m.view.page === page ? 0 : -1,
      class: m.view.page === page ? 'active' : '',
      onkeydown: event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          return;
        }
        event.preventDefault();
        const buttons = [...tabs.children],
          index = buttons.indexOf(event.currentTarget);
        let next;
        if (event.key === 'Home') {
          next = 0;
        } else if (event.key === 'End') {
          next = buttons.length - 1;
        } else {
          next = (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
        }
        buttons.forEach((item, i) => setAttr(item, 'tabindex', i === next ? '0' : '-1'));
        buttons[next].focus();
      }
    }));
  }
  const viewbar = h('div', {
    class: 'viewbar'
  }, tabs);
  appendContent(content, viewbar);
  const panel = h('section', {
    id: 'wb-table-panel',
    role: 'tabpanel',
    'aria-labelledby': `wb-table-tab-${m.view.page}`
  });
  appendContent(content, panel);
  drawTablePanel(table, viewbar, panel);
  appendStatus();
  updateStatus();
  if (autoPreview && m.view.page === 'preview' && !tablePreview?.cached) {
    return tablePreview?.refresh();
  }
}
function drawTablePanel(table, viewbar, panel) {
  const m = model();
  // Leaf renderers append to the same table panel; the page header stays stable.
  const host = content;
  content = panel;
  if (m.view.page === 'graph') {
    drawGraph(table);
  } else if (m.view.page === 'preview') {
    drawTablePreview(table);
  } else {
    drawFields(table, viewbar);
  }
  content = host;
}
function appendStatus() {
  notice = h('span', {
    class: 'wb-notice',
    role: 'status',
    'aria-live': 'polite'
  }, tr("workbench.preview.afterEdit"));
  appendContent(content, h('div', {
    class: 'statusbar'
  }, h('span', {}, h('i', {
    class: 'status-dot'
  }), notice), h('span', {}, tr("workbench.preview.readOnly"))));
  reportExecutionCheck();
}
function ruleDescription(table, column) {
  const rule = model().rule(table.name, column.name),
    generator = rule.generator || rule.generator_name;
  const fk = table.foreign_keys.find(key => key.columns.includes(column.name));
  const locked = column.is_autoincrement || column.is_computed;
  const allocated = locked || generator === 'skip';
  if (allocated) {
    const allocatedColumnLabel = () => {
      if (column.is_computed) {
        return tr("workbench.rule.computed");
      } else if (column.is_autoincrement || column.is_rowid_alias) {
        return tr("workbench.rule.auto");
      } else if (column.default != null) {
        return tr("workbench.rule.default");
      } else {
        return tr("workbench.rule.null");
      }
    };
    const allocatedColumnDetail = () => {
      if (column.is_autoincrement || column.is_rowid_alias) {
        return tr("workbench.rule.autoHelp");
      } else if (column.is_computed) {
        return tr("workbench.rule.computedHelp");
      } else if (column.default != null) {
        return tr("workbench.rule.defaultHelp", {value: column.default});
      } else {
        return tr("workbench.rule.nullHelp");
      }
    };
    return {
      rule,
      fk,
      locked,
      allocated,
      label: allocatedColumnLabel(),
      detail: allocatedColumnDetail()
    };
  }
  if (fk) {
    return {
      rule,
      fk,
      locked,
      label: tr("workbench.rule.reference", {table: fk.ref_table, columns: fk.ref_columns.join(', ')}),
      detail: rule.params?.strategy === 'coverage' ? tr("workbench.rule.coverParent") : tr("workbench.rule.sampleParent"),
      glyph: 'link'
    };
  }
  if (rule.derive_from) {
    return {
      rule,
      locked,
      label: tr("workbench.rule.derived"),
      detail: `${Array.isArray(rule.derive_from) ? rule.derive_from.join(' / ') : rule.derive_from} · ${rule.expression || ''}`,
      glyph: 'derive'
    };
  }
  return generatorDescription();
  function generatorDescription() {
    const params = rule.params || {};
    const parameters = Object.entries(params).filter(([key, value]) => !key.startsWith('_') && value != null);
    let detail = parameters.length ? joinText(parameters.map(([key, value]) => joinText([paramLabel(key), valueText(value)], ' ')), ', ') : '';
    if (params.min_value !== undefined || params.max_value !== undefined) {
      detail = joinText([params.min_value ?? tr("workbench.rule.unbounded"), '—', params.max_value ?? tr("workbench.rule.unbounded"), params.precision != null ? tr("workbench.rule.precision", {count: params.precision}) : '']);
    }
    if (params.choices) {
      detail = Array.isArray(params.choices) ? params.choices.map(valueText).join(' / ') : valueText(params.choices);
    }
    if (params.start_date || params.end_date) {
      detail = joinText([params.start_date || tr("workbench.rule.unbounded"), params.end_date || tr("workbench.rule.unbounded")], ' — ');
    }
    if (rule.null_ratio) {
      detail = joinText([detail, tr("workbench.rule.nullRatio", {separator: detail ? ', ' : '', percent: Math.round(rule.null_ratio * 100)})]);
    }
    return {
      rule,
      locked,
      label: generator ? genLabel(generator) : tr("workbench.rule.inferred"),
      detail: detail || tr("workbench.rule.defaults")
    };
  }
}
function sampleNode(value, allocated = false) {
  if (value === undefined) {
    const unavailableSampleLabel = () => {
      if (allocated) {
        if (allocated === true) {
          return tr("workbench.rule.autoValue");
        } else {
          return allocated;
        }
      } else {
        return tr("workbench.rule.awaitingPreview");
      }
    };
    return h('span', {
      class: 'sample placeholder'
    }, unavailableSampleLabel());
  }
  if (value === null) {
    return h('span', {
      class: 'sample null'
    }, 'NULL');
  }
  const text = valueText(value),
    parts = /^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d.*)$/.exec(text);
  if (parts) {
    return h('span', {
      class: 'sample timestamp',
      title: text
    }, h('span', {}, parts[1]), h('span', {
      class: 'sample-time'
    }, parts[2]));
  }
  return h('span', {
    class: 'sample',
    title: text
  }, text);
}
const previewIssueTables = issue => [issue.table, ...(Array.isArray(issue.tables) ? issue.tables : [])].filter(Boolean);
function drawFields(table, viewbar) {
  const m = model();
  const rows = h('tbody'),
    previewNote = h('div', {
      class: 'wb-preview-notice',
      role: 'status'
    });
  const search = h('input', {
    type: 'search',
    placeholder: tr("workbench.field.search"),
    'aria-label': tr("workbench.field.search"),
    value: fieldQuery,
    oninput: e => {
      if (e.isComposing) {
        return;
      }
      fieldQuery = e.target.value;
      drawRows();
    },
    oncompositionend: e => {
      fieldQuery = e.target.value;
      drawRows();
    }
  });
  appendContent(viewbar, h('label', {
    class: 'search'
  }, icon('search'), search));
  if (!m.selected(table.name)) {
    appendContent(content, h('div', {
      class: 'view-only-note'
    }, tr("workbench.field.draftHelp")));
  }
  appendContent(content, h('div', {
    class: 'sample-guide'
  }, h('span', {}, tr("workbench.field.tableHelp"))), previewNote, h('div', {
    class: 'wb-rules-scroll',
    tabindex: 0,
    'aria-label': tr("workbench.field.scrollLabel", {table: table.name})
  }, h('table', {
    class: 'field-table wb-data'
  }, h('colgroup', {}, h('col', {
    class: 'col-field'
  }), h('col', {
    class: 'col-rule'
  })), h('thead', {}, h('tr', {}, ...[tr("workbench.field.name"), tr("workbench.field.valueRule")].map(text => h('th', {
    scope: 'col'
  }, text)))), rows)));
  function drawRows() {
    replaceContent(previewNote, ...(m.previewIssues || []).filter(issue => {
      const names = previewIssueTables(issue);
      return !names.length || names.includes(table.name);
    }).map(issue => {
      const target = issue.table ? [issue.table, issue.column].filter(Boolean).join('.') : previewIssueTables(issue).join('、');
      return h('p', {
        class: issue.severity === 'error' ? 'wb-error' : 'muted'
      }, joinText([target ? `${target}: ` : '', serverText(issue)]));
    }));
    replaceContent(rows, ...table.columns.filter(c => c.name.toLowerCase().includes(fieldQuery.toLowerCase())).map(column => {
      const info = ruleDescription(table, column);
      const ruleButton = h('button', {
        class: 'wb-rule-button',
        'data-rule-column': column.name,
        onclick: () => openRule(table, column)
      }, h('span', {
        class: 'rule-line'
      }, ...(info.glyph ? [icon(info.glyph)] : []), info.label), h('span', {
        class: 'rule-meta'
      }, info.detail));
      return h('tr', {
        class: columnName === column.name ? 'selected' : ''
      }, h('td', {}, button(column.name, () => {
        columnName = column.name;
        for (const row of rows.children) {
          row.classList.toggle('selected', row.querySelector('.wb-field-name')?.textContent === column.name);
        }
        openRule(table, column, 'information');
      }, {
        plain: true,
        class: 'field-name wb-field-name'
      }), h('small', {
        class: 'field-type'
      }, joinText([column.type, column.is_primary_key ? tr("workbench.field.pkSuffix") : '', info.fk ? tr("workbench.field.fkSuffix") : '', column.nullable ? tr("workbench.field.nullableSuffix") : tr("workbench.field.requiredSuffix")]))), h('td', {}, ruleButton));
    }));
    if (!rows.children.length) {
      appendContent(rows, h('tr', {}, h('td', {
        colspan: 2,
        class: 'empty'
      }, tr("workbench.field.noMatch"))));
    }
  }
  if (!table.columns.some(c => c.name === columnName)) {
    columnName = table.columns[0]?.name || '';
  }
  drawRows();
}
function openRule(table, column, initialTab = 'rule', {
  onReturn,
  previewOrigin = null
} = {}) {
  const intent = ++modalIntent;
  const m = model(),
    epoch = m.epoch,
    version = active,
    current = ticket();
  let component,
    error = null,
    changed = false,
    pending;
  const batchPreview = previewOrigin?.scope === 'selected';
  const dialog = openedModal = modal(batchPreview ? tr("workbench.field.previewTitle", {column: column.name}) : column.name, {
    dismiss: 'footer',
    drawer: !batchPreview,
    wide: batchPreview,
    onClose: () => {
      component?.destroy();
      if (onReturn) {
        return deferPreviewReturn(onReturn, () => intent === modalIntent);
      }
    }
  });
  if (batchPreview) dialog.el.classList.add('wb-preview-rule');
  const apply = button(batchPreview ? tr("workbench.field.applyReturn") : tr("workbench.field.apply"), () => {
    if (error) {
      return;
    }
    if (version !== active || m !== model() || epoch !== m.epoch) {
      dialog.close();
      notify(tr("workbench.field.stale"), true);
      return;
    }
    if (changed) {
      m.setColumn(table.name, column.name, pending);
    }
    dialog.close();
    if (!onReturn) {
      drawBody();
      content.querySelectorAll('.wb-rule-button').forEach(node => {
        if (node.dataset.ruleColumn === column.name) {
          node.focus();
        }
      });
    } else {
      updateStatus();
    }
    notify(changed ? tr("workbench.field.applied", {table: table.name, column: column.name}) : tr("workbench.field.unchanged"));
  }, {
    primary: true
  });
  appendContent(dialog.body, h('div', {
    class: 'drawer-subtitle'
  }, `${table.name}.${column.name} · ${column.type}`));
  if (batchPreview) appendContent(dialog.body, h('p', {class:'wb-muted'}, tr("workbench.field.previewHelp")));
  const tabs = h('div', {
    class: 'wb-field-tabs',
    role: 'tablist',
    'aria-label': tr("workbench.field.details")
  });
  const information = h('section', {
    id: 'field-information',
    role: 'tabpanel',
    'aria-labelledby': 'field-information-tab'
  });
  const rules = h('section', {
    id: 'field-rule',
    role: 'tabpanel',
    'aria-labelledby': 'field-rule-tab'
  });
  const info = ruleDescription(table, column),
    metadata = h('dl', {
      class: 'wb-field-facts'
    });
  renderColumnInformation();
  const names = [['information', tr("workbench.field.information")], ['rule', tr("workbench.field.valueRule")]];
  let currentTab = initialTab;
  function activate(name, focus = false) {
    currentTab = name;
    information.hidden = name !== 'information';
    rules.hidden = name !== 'rule';
    [...tabs.children].forEach(tab => {
      const selected = tab.dataset.tab === name;
      setAttr(tab, 'aria-selected', String(selected));
      setAttr(tab, 'tabindex', selected ? '0' : '-1');
      if (selected && focus) {
        tab.focus();
      }
    });
    replaceContent(dialog.actions, button(batchPreview ? tr("workbench.field.returnPreview") : tr("workbench.action.cancel"), dialog.close), name === 'information' ? button(tr("workbench.field.edit"), () => activate('rule', true), {
      primary: true
    }) : apply);
    if (name === 'rule' && !component) {
      mountEditor();
    }
  }
  for (const [name, label] of names) {
    appendContent(tabs, button(label, () => activate(name), {
      plain: true,
      id: `field-${name}-tab`,
      role: 'tab',
      'data-tab': name,
      'aria-controls': name === 'rule' ? 'field-rule' : 'field-information',
      onkeydown: event => {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          event.preventDefault();
          const ruleTabTarget = () => {
            if (event.key === 'Home') {
              return 'information';
            } else if (event.key === 'End') {
              return 'rule';
            } else if (currentTab === 'rule') {
              return 'information';
            } else {
              return 'rule';
            }
          };
          activate(ruleTabTarget(), true);
        }
      }
    }));
  }
  const eligibility = fieldAIEligibility(table, column, m.rule(table.name, column.name));
  if (!eligibility.eligible) {
    appendContent(information, h('p', {
      class: 'wb-ai-protected'
    }, eligibility.reason));
  }
  const canAI = eligibility.eligible || needsAIDefaultPreflight(m) && eligibility.code === 'database_default';
  const aiHint = h('p', {
    class: 'muted',
    role: 'status',
    'data-rule-ai-hint': ''
  });
  const ai = button(tr("workbench.field.ai"), () => {
    if (!dialog.el.isConnected || !current() || error || changed || !canAI) {
      return;
    }
    return openAI('columns', {
      scope: 'columns',
      currentTable: table.name,
      columnSelection: {
        [table.name]: [column.name]
      }
    }, {
      previewOrigin
    });
  }, {
    small: true,
    glyph: 'sparkles',
    'data-rule-ai': ''
  });
  function updateAI() {
    ai.disabled = Boolean(error || changed || !canAI || !current());
    if (error || changed) {
      setText(aiHint, tr("workbench.field.aiPending"));
    } else if (canAI) {
      setText(aiHint, tr("workbench.field.aiHelp"));
    } else {
      setText(aiHint, eligibility.reason);
    }
  }
  appendContent(rules, h('div', {
    class: 'wb-field-rule-ai'
  }, ai, aiHint));
  updateAI();
  appendContent(dialog.body, tabs, information, rules);
  function mountEditor() {
    component = createRuleEditor({
      table,
      column,
      rule: m.rule(table.name, column.name),
      baseline: table.mapping[column.name],
      catalog,
      onChange: rule => {
        pending = rule;
        changed = true;
        updateAI();
      },
      onValidity: message => {
        error = message;
        apply.disabled = !!message;
        updateAI();
      }
    });
    appendContent(rules, component.el);
  }
  activate(initialTab);
  function renderColumnInformation() {
    for (const [label, value] of [[tr("workbench.field.name"), column.name], [tr("workbench.field.type"), column.type], [tr("workbench.field.nullable"), column.nullable ? tr("workbench.boolean.yes") : tr("workbench.boolean.no")], [tr("workbench.field.primaryKey"), column.is_primary_key ? tr("workbench.boolean.yes") : tr("workbench.boolean.no")], [tr("workbench.rule.default"), column.default ?? tr("workbench.field.unset")], [tr("workbench.rule.autoValue"), column.is_autoincrement || column.is_rowid_alias ? tr("workbench.field.assigned") : tr("workbench.boolean.no")]]) {
      appendContent(metadata, h('dt', {}, label), h('dd', {}, value));
    }
    appendContent(information, h('p', {
      class: 'muted'
    }, tr("workbench.field.structureHelp")), metadata);
    if (info.fk) {
      appendContent(information, h('h3', {}, tr("workbench.field.foreignSource")), h('p', {
        class: 'mono'
      }, `${info.fk.ref_table}.${info.fk.ref_columns.join(', ')}`), h('p', {}, info.detail));
    }
    for (const constraint of table.unique_constraints || []) {
      if (constraint.columns.includes(column.name)) {
        appendContent(information, h('h3', {}, constraint.columns.length === 1 ? tr("workbench.field.unique") : tr("workbench.field.compositeUnique")), h('p', {
          class: 'mono'
        }, constraint.columns.join(' + ')));
      }
    }
    if (table.checks?.length) {
      appendContent(information, h('details', {
        class: 'wb-field-constraints'
      }, h('summary', {}, tr("workbench.field.checkConstraints")), h('p', {
        class: 'muted'
      }, tr("workbench.field.checkHelp")), ...table.checks.map(check => h('p', {
        class: 'mono'
      }, typeof check === 'string' ? check : check.sqltext || check.expression || JSON.stringify(check)))));
    }
  }
}
function drawGraph(table, previousSection = null) {
  const m = model(),
    panel = h('aside', {
      class: 'graph-inspector wb-inspector'
    }),
    area = h('div', {
      class: 'graph-workspace wb-graph-workspace'
    });
  const refs = referencedTables();
  const graphSchema = {
    ...m.schema,
    nodes: m.schema.nodes.map(node => ({
      ...node,
      selected: m.selected(node.id),
      referenced: refs.has(node.id),
      count: m.table(node.id).count
    }))
  };
  const inspectorBody = h('div', {
    class: 'inspector-body wb-inspector-body'
  });
  graphOwner = m;
  graph = createSchemaGraph({
    schema: graphSchema,
    focus: table.name,
    mode: m.view.graphMode || 'plan',
    pathMode: m.view.pathMode || 'complete',
    initialView: graphViews.get(m),
    issues: m.check?.issues || [],
    checked: Boolean(m.check),
    onSelect: name => {
      if (!validNavigation()) {
        return false;
      }
      const next = m.schema.tables.find(t => t.name === name);
      if (!next) {
        notify(tr("workbench.schema.externalSource"));
        return;
      }
      table = next;
      m.view.table = name;
      selectedEdge = null;
      drawSidebar();
      updateStatus();
      inspect();
      // Count/actions belong to the focused table: rebuild its context through
      // the same page path on next table navigation, not through selection.
      syncTableHeading(table);
      sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({
        block: 'nearest'
      });
    },
    onEdge: edge => {
      selectedEdge = edge;
      inspect();
    },
    onViewChange: view => {
      const changedMode = m.view.graphMode !== view.mode;
      const wasIssues = m.view.graphMode === 'issues';
      graphViews.set(m, view);
      m.view.graphMode = view.mode;
      m.view.pathMode = view.pathMode;
      if (changedMode && panel.isConnected && (view.mode === 'issues' || wasIssues)) {
        if (view.mode === 'issues') inspectorMode = 'dependencies';
        selectedEdge = null;
        inspect();
      }
    },
    onExpand: expanded => area.classList.toggle('expanded', expanded)
  });
  const section = h('section', {
    class: 'panel-content database-graph wb-graph-section'
  });
  if (graph.toolbar) {
    appendContent(section, graph.toolbar);
  }
  area.classList.toggle('expanded', graph.getView().expanded);
  appendContent(area, graph.el, panel);
  appendContent(section, area);
  if (previousSection?.isConnected) previousSection.replaceWith(section);
  else appendContent(content, section);
  if (m.view.graphMode === 'issues' && !selectedEdge) inspectorMode = 'dependencies';
  function inspect() {
    const checkingIssues = m.view.graphMode === 'issues' && inspectorMode === 'dependencies';
    replaceContent(panel, h('div', {
      class: 'inspector-tabs'
    }, button(tr("workbench.tab.rules"), () => {
      inspectorMode = 'fields';
      selectedEdge = null;
      inspect();
    }, {
      plain: true,
      class: inspectorMode === 'fields' ? 'active' : ''
    }), button(tr("workbench.dependency.title"), () => {
      inspectorMode = 'dependencies';
      selectedEdge = null;
      inspect();
    }, {
      plain: true,
      class: inspectorMode === 'dependencies' ? 'active' : ''
    })), h('div', {
      class: 'inspector-actions', hidden: checkingIssues
    }, h('div', {
      class: 'inspector-table-title'
    }, h('strong', {
      class: 'mono'
    }, table.name), h('small', {}, tr("workbench.field.count", {count: table.columns.length}))), button(tr("workbench.field.viewRules"), () => chooseTable(table.name), {
      small: true
    })), inspectorBody);
    if (selectedEdge) {
      replaceContent(inspectorBody, h('h3', {}, tr("workbench.edge.title")), h('div', {
        class: 'wb-edge-mapping'
      }, ...selectedEdge.sourceColumns.map((source, i) => h('div', {}, h('code', {}, `${selectedEdge.source}.${source}`), h('span', {}, '↓'), h('code', {}, `${selectedEdge.target}.${selectedEdge.targetColumns[i]}`)))), h('p', {
        class: 'muted'
      }, tr("workbench.edge.help")), button(tr("workbench.edge.locateColumn"), () => {
        const target = m.schema.tables.find(t => t.name === selectedEdge.target);
        const column = target?.columns.find(c => c.name === selectedEdge.targetColumns[0]);
        if (column) {
          openRule(target, column);
        }
      }, {
        small: true
      }));
    } else if (inspectorMode === 'dependencies') {
      renderDependencies(inspectorBody, name => {
        if (!validNavigation()) {
          return;
        }
        const next = m.schema.tables.find(t => t.name === name);
        if (!next) {
          return;
        }
        table = next;
        m.view.table = name;
        graph.focusTable?.(name);
        drawSidebar();
        syncTableHeading(table);
        updateStatus();
        inspect();
        sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({
          block: 'nearest'
        });
      }, checkingIssues ? null : table.name);
    } else {
      replaceContent(inspectorBody, h('p', {
        class: 'muted'
      }, tr("workbench.field.selectHelp")), ...table.columns.map(column => button('', () => openRule(table, column), {
        plain: true,
        class: 'graph-field inspector-field wb-field-card',
        title: tr("workbench.field.adjust", {table: table.name, column: column.name})
      })));
    }
    if (!selectedEdge && inspectorMode === 'fields') {
      [...inspectorBody.querySelectorAll('.wb-field-card')].forEach((card, i) => {
        const column = table.columns[i],
          info = ruleDescription(table, column);
        function columnSourceLabel() {
          if (info.allocated) {
            return tr("workbench.rule.database");
          } else if (info.fk) {
            return tr("workbench.rule.referenceType");
          } else if (info.rule.derive_from) {
            return tr("workbench.rule.derivedType");
          } else {
            return tr("workbench.rule.generatorType");
          }
        }
        appendContent(card, h('div', {
          class: 'graph-field-title field-card-heading'
        }, h('strong', {
          class: 'mono'
        }, column.name), h('small', {}, columnSourceLabel())), h('span', {}, info.label), sampleNode(m.samples[table.name]?.[0]?.[column.name], info.allocated ? info.label : false));
      });
    }
  }
  inspect();
}
function refreshGraphCheck() {
  const m = model();
  if (!graph || graphOwner !== m || m.view.page !== 'graph' || m.view.imported) return;
  const section = content.querySelector('.wb-graph-section');
  const table = m.schema.tables.find(item => item.name === m.view.table);
  if (!section || !table) return;
  // A check updates issue availability, colors and the inspector together. Keep
  // its view snapshot and replace only the graph section, not the page/header.
  closeComponents();
  drawGraph(table, section);
}
function syncTableHeading(table) {
  const header = content.querySelector('.table-heading');
  if (!header) {
    return;
  }
  // Reuse the exact controls without keeping handlers bound to the previous node.
  setText(header.querySelector('h2'), table.name);
  setText(header.querySelector('.desc'), tr("workbench.table.summary", {fields: table.columns.length, rows: table.row_count}));
  const countControl = generationCountControl(table);
  replaceContent(header.querySelector('.table-actions'), ...(!model().selected(table.name) ? [button(tr("workbench.table.include"), () => {
    model().toggleTable(table.name, true);
    drawBody();
  }, {
    small: true
  })] : []), h('label', {
    class: 'count-setting'
  }, tr("workbench.count.title"), countControl, h('span', {}, tr("workbench.count.unit"))));
  const tabButtons = content.querySelector('.tabs').querySelectorAll('button');
  tabButtons[0].onclick = () => chooseTable(table.name);
}
function generationLimitations(result) {
  if (result?.epoch != null && result.epoch !== model().epoch) return [];
  return (result?.issues || []).filter(issue => issue.severity === 'error' && issue.code === 'cross_table_cycle');
}
function generationUnsupportedCard(result) {
  const current = ticket();
  const issues = generationLimitations(result);
  const tables = [...new Set(issues.flatMap(issue => issue.tables || []))];
  return h('section', {class: 'wb-clear-recovery wb-generation-unsupported', role: 'status'},
    h('h3', {}, tr('workbench.unsupported.title')),
    h('p', {}, tr('workbench.unsupported.body', {tables: tables.join('、')})),
    button(tr('workbench.unsupported.reason'), () => {if (current()) showCapabilityReasons(result);}, {small: true}));
}
function showCapabilityReasons(result = model().check) {
  const dialog = openedModal = modal(tr('workbench.unsupported.reason'), {wide: true});
  renderDependencies(dialog.body, name => {
    dialog.close(); inspectorMode = 'dependencies'; chooseTable(name, 'graph');
  }, null, null, result);
}
function dependencyEdges(schema, document) {
  const edges = [...schema.edges];
  for (const association of document.associations || []) {
    for (const target of association.target_tables || []) {
      edges.push({
        source: association.source_table,
        target,
        sourceColumns: [association.source_column || association.column_name],
        targetColumns: [association.column_name]
      });
    }
  }
  return edges;
}
function cycleRetentionMessage(dialect) {
  if (dialect === 'sqlite') return 'workbench.cycle.keepSQLite';
  return dialect === 'postgresql' ? 'workbench.cycle.keepPostgres' : 'workbench.cycle.keepCapabilities';
}
function retainedCycleTables(members, edges, tables) {
  const retained = new Set(members);
  // A retained child still references its parents after clearing. Preserve the
  // entire upstream scope in the explanation, never just the cycle members.
  for (const name of retained) for (const edge of edges) {
    if (edge.target === name && tables.has(edge.source)) retained.add(edge.source);
  }
  return retained;
}
function cycleIssueDetails(issue, locate, document = model().document) {
  const m = model(), current = ticket();
  const tables = new Map(m.schema.tables.map(table => [table.name, table]));
  const edges = [...m.schema.edges];
  for (const association of document.associations || []) {
    for (const target of association.target_tables || []) edges.push({source: association.source_table, target});
  }
  const members = (issue.tables || []).filter(name => tables.has(name));
  const retained = retainedCycleTables(members, edges, tables);
  const references = Array.isArray(issue.references) ? issue.references : edges
    .filter(edge => (issue.edge_ids || []).includes(edge.id))
    .map(edge => ({table: edge.target, columns: edge.targetColumns, source_table: edge.source, source_columns: edge.sourceColumns}));
  const detail = h('section', {class: 'wb-cycle-help'});
  if (references.length) appendContent(detail, h('h4', {}, tr('workbench.cycle.references')),
    h('ul', {class: 'wb-cycle-references'}, ...references.map(reference => {
      const target = `${reference.table}.${(reference.columns || []).join(' + ')}`;
      const source = `${reference.source_table}.${(reference.source_columns || []).join(' + ')}`;
      const table = tables.get(reference.table);
      const column = table?.columns.find(item => item.name === reference.columns?.[0]);
      return h('li', {}, h('p', {class: 'mono'}, tr('workbench.cycle.reference', {target, source})),
        ...(column ? [button(tr('workbench.cycle.inspect', {target}), () => {
          if (!current() || !validNavigation()) return;
          locate(table.name);
          openRule(table, column, 'information');
        }, {small: true})] : []));
    })));
  appendContent(detail, h('h4', {}, tr('workbench.cycle.rebuildTitle')),
    h('p', {}, tr('workbench.cycle.rebuildHelp')));
  const alternatives = h('details', {}, h('summary', {}, tr('workbench.unsupported.otherScope')));
  appendContent(alternatives, h('h4', {}, tr('workbench.cycle.keepTitle')),
    h('p', {}, tr('workbench.cycle.keepHelp', {tables: [...retained].join('、')})),
    h('p', {}, tr(cycleRetentionMessage(m.schema.dialect))),
    h('p', {class: 'muted'}, tr('workbench.cycle.keepLimit')));
  const firstSelected = members.find(name => m.selected(name)) || members[0];
  if (firstSelected) appendContent(alternatives, button(tr('workbench.cycle.locateScope'), () => {
    if (!current() || !validNavigation()) return;
    const sidebarView = sidebarViews.get(m);
    if (sidebarView) sidebarView.query = '';
    locate(firstSelected);
    const input = [...sidebar.querySelectorAll('.wb-table-entry')]
      .find(row => row.dataset.table === firstSelected)?.querySelector('input[type="checkbox"]');
    input?.focus(); input?.scrollIntoView({block: 'nearest'});
  }, {small: true, primary: true}));
  appendContent(detail, alternatives);
  return detail;
}
const dependencyIssueTables = issue => [...new Set([issue.table, ...(Array.isArray(issue.tables) ? issue.tables : [])]
  .filter(name => typeof name === 'string' && name))];
function renderDependencies(out, locate = name => {
  inspectorMode = 'dependencies';
  chooseTable(name, 'graph');
}, focus = null, onUpdate = null, resultOverride = null) {
  const m = model(),
    result = resultOverride || m.check;
  const edges = dependencyEdges(m.schema, m.document);
  const related = relatedTables();
  const executable = executableTables();
  const upstreamEdges = edges.filter(edge => related.has(edge.target) && related.has(edge.source));
  const relevantIssues = (result?.issues || []).filter(issue => !focus || !dependencyIssueTables(issue).length || dependencyIssueTables(issue).some(name => executable.has(name)));
  const sourceCards = upstreamEdges.map(edge => {
    const parent = m.schema.tables.find(t => t.name === edge.source);
    const evidence = result?.sources?.find(source => source.table === edge.target && source.source_table === edge.source && source.column === (edge.targetColumns || []).join(','));
    const selected = m.selected(edge.source),
      rows = evidence?.row_count ?? parent?.row_count;
    let explanation;
    if (focus && !executable.has(edge.target)) {
      explanation = tr("workbench.source.indirect");
    } else if (selected) {
      explanation = evidence?.has_values === false ? tr("workbench.source.generatedKeys") : tr("workbench.source.generated");
    } else if (evidence?.has_values) {
      explanation = tr("workbench.source.existing", {rows: rows});
    } else if (evidence?.has_values === false) {
      explanation = evidence.nullable ? tr("workbench.source.nullable") : tr("workbench.source.empty");
    } else {
      explanation = tr("workbench.source.unchecked", {rows: rows == null ? tr("workbench.source.unknownRows") : tr("workbench.source.existingRows", {count: formatNumber(rows)}), scope: selected ? tr("workbench.scope.selected") : tr("workbench.scope.referenceOnly")});
    }
    return h('article', {
      class: 'wb-source-card'
    }, h('strong', {
      class: 'mono'
    }, `${edge.source}.${(edge.sourceColumns || []).join(' + ')} → ${edge.target}.${(edge.targetColumns || []).join(' + ')}`), h('p', {}, explanation), button(tr("workbench.action.viewTable", {table: edge.source}), () => locate(edge.source), {
      small: true
    }));
  });
  const previousSources = out.querySelector('.wb-dependency-sources');
  function dependencySourceCards() {
    if (sourceCards.length) {
      return sourceCards;
    } else {
      return [h('p', {
        class: 'muted'
      }, focus ? tr("workbench.source.none") : tr("workbench.source.noExternal"))];
    }
  }
  const sources = h('details', {
    class: 'wb-dependency-sources',
    open: previousSources ? previousSources.open : Boolean(focus)
  }, h('summary', {}, focus ? tr("workbench.source.allUpstream", {table: focus, count: sourceCards.length}) : tr("workbench.source.details", {count: sourceCards.length})), h('p', {
    class: 'muted'
  }, focus ? tr("workbench.source.upstreamHelp") : tr("workbench.source.detailsHelp")), ...dependencySourceCards());
  replaceContent(out, h('h3', {}, focus ? tr("workbench.dependency.tableTitle", {table: focus}) : tr("workbench.dependency.selectedTitle")));
  if (focus && !m.selected(focus)) {
    appendContent(out, h('p', {
      class: 'muted'
    }, tr("workbench.dependency.excluded")), sources);
    return;
  }
  if (!result) {
    appendContent(out, h('p', {
      class: 'muted'
    }, tr("workbench.dependency.notChecked")), button(tr("workbench.dependency.start"), action(async () => {
      if (await check(false)) {
        drawBody();
      }
    }, tr("workbench.action.checkDependencies")), {
      glyph: 'check'
    }), sources);
    syncBusy();
    return;
  }
  const blockers = relevantIssues.filter(issue => issue.severity === 'error'),
    reminders = relevantIssues.filter(issue => issue.severity !== 'error');
  const blockingTitle = blockers.length && blockers.every(issue => issue.code === 'cross_table_cycle')
    ? tr('workbench.unsupported.reasonTitle') : tr('workbench.dependency.blockingTitle');
  function dependencySummary() {
    if (generationLimitations({issues: relevantIssues}).length) return tr('workbench.unsupported.title');
    if (blockers.length) {
      return tr("workbench.dependency.issues");
    } else if (result.ok) {
      return tr("workbench.dependency.passed");
    } else {
      return tr("workbench.dependency.otherIssues");
    }
  }
  appendContent(out, h('section', {
    class: `wb-dependency-summary ${blockers.length || !result.ok ? 'wb-dependency-blocked' : 'wb-dependency-passed'}`,
    role: 'status'
  }, h('strong', {}, dependencySummary()), h('p', {}, tr("workbench.dependency.counts", {blockers: blockers.length, warnings: reminders.length}))));
  const issueCard = issue => h('article', {
    class: `dependency-card ${issue.severity}`
  }, h('strong', {}, dependencyIssueTables(issue).join('、') || tr("workbench.config.title")), h('p', {}, serverText(issue)), ...(issue.code === 'cross_table_cycle' ? [cycleIssueDetails(issue, locate)] : []), ...(issue.code === 'missing_parent_source' && issue.source_table && m.schema.tables.some(t => t.name === issue.source_table) && !m.selected(issue.source_table) ? [button(tr("workbench.dependency.addSource", {table: issue.source_table, count: m.table(issue.source_table).count}), action(async () => {
    m.toggleTable(issue.source_table, true);
    const stillCurrent = ticket();
    if (await check(false)) {
      if (!stillCurrent()) {
        return;
      }
      drawBody();
      if (out.isConnected) {
        renderDependencies(out, locate, focus, onUpdate);
      }
      onUpdate?.();
    }
  }, tr("workbench.action.checkDependencies")), {
    small: true
  })] : []), ...dependencyIssueTables(issue).filter(name => m.schema.tables.some(table => table.name === name)).map(name => button(tr("workbench.action.locate", {target: name === issue.table && issue.column || name}), () => {
    locate(name);
    const table = m.schema.tables.find(t => t.name === name),
      column = name === issue.table && table?.columns.find(c => c.name === issue.column);
    if (column) {
      openRule(table, column);
    }
  }, {
    small: true
  })));
  if (blockers.length) {
    appendContent(out, h('section', {
      class: 'wb-dependency-issues',
      'aria-label': blockingTitle
    }, h('h4', {}, blockingTitle), ...blockers.map(issueCard)));
  }
  if (reminders.length) {
    appendContent(out, h('section', {
      class: 'wb-dependency-issues',
      'aria-label': tr("workbench.dependency.warningTitle")
    }, h('h4', {}, tr("workbench.dependency.warningTitle")), ...reminders.map(issueCard)));
  }
  appendContent(out, sources);
  const layers = (result.layers || []).map(names => names.filter(name => !focus || executable.has(name))).filter(names => names.length);
  function dependencyOrderTitle() {
    if (!result.ok) {
      return tr("workbench.dependency.groupsReference");
    } else if (focus) {
      return tr("workbench.dependency.tableOrder");
    } else {
      return tr("workbench.dependency.selectedOrder");
    }
  }
  function dependencyOrderHint() {
    if (generationLimitations(result).length) return tr('workbench.unsupported.partialOrder');
    if (!result.ok) {
      return tr("workbench.dependency.incompletePlan");
    } else if (focus) {
      return tr("workbench.dependency.tableOrderHelp");
    } else {
      return tr("workbench.dependency.groupHelp");
    }
  }
  appendContent(out, h('div', {
    class: 'execution-heading'
  }, h('h3', {}, dependencyOrderTitle()), ...(generationLimitations(result).length ? [] : [button(tr("workbench.dependency.fullPlan"), action(showPlan), {
    plain: true,
    class: 'text-button'
  })])), h('ol', {
    class: 'execution-sequence'
  }, ...layers.map((names, i) => h('li', {}, h('span', {
    class: 'execution-step'
  }, i + 1), h('div', {
    class: 'execution-group'
  }, h('small', {}, tr("workbench.dependency.group", {number: i + 1, count: names.length})), h('div', {
    class: 'execution-tables'
  }, ...names.map(name => button(h('span', {class:'execution-table-caption'}, name), () => locate(name), {
    small: true,
    glyph: 'table',
    class: 'execution-table',
    'aria-label': tr("workbench.action.locate", {target:name}),
    title: tr("workbench.action.locate", {target:name})
  }))))))), h('p', {
    class: 'muted'
  }, dependencyOrderHint()));
  syncBusy();
  function relatedTables() {
    const related = new Set(focus ? [focus] : m.document.tables.map(t => t.name));
    for (const name of related) {
      for (const edge of edges) {
        if (edge.target === name) {
          related.add(edge.source);
        }
      }
    }
    return related;
  }
  function executableTables() {
    const executable = new Set(focus ? [focus] : m.document.tables.map(t => t.name));
    for (const name of executable) {
      for (const edge of edges) {
        if (edge.target === name && m.selected(edge.source)) {
          executable.add(edge.source);
        }
      }
    }
    return executable;
  }
}
async function showPlan() {
  return showDependencies();
}
async function showDependencies() {
  const current = modalTicket();
  if (!model().document.tables.length) {
    const dialog = openedModal = modal(tr("workbench.scope.noneTitle"));
    appendContent(dialog.body, h('p', {}, tr("workbench.scope.noneHelp")));
    appendContent(dialog.actions, button(tr("workbench.scope.select"), () => {
      if (!current()) {
        dialog.close();
        return;
      }
      dialog.close();
      locateGenerationSelection();
    }, {
      primary: true
    }));
    return;
  }
  if (!(await check(false)) || !current()) {
    return;
  }
  const dialog = openedModal = modal(tr("workbench.dependency.fullTitle"), {
    wide: true
  });
  const generate = button(tr("workbench.action.viewPlan"), () => {
    if (!model().check?.ok) {
      return;
    }
    dialog.close();
    return action(summary)();
  }, {
    primary: true,
    disabled: !model().check?.ok
  });
  renderDependencies(dialog.body, name => {
    dialog.close();
    inspectorMode = 'dependencies';
    chooseTable(name, 'graph');
  }, null, () => {
    generate.disabled = !model().check?.ok;
  });
  appendContent(dialog.actions, generate);
}
function previewTables(m) {
  return m.schema.tables.map(item => ({
    ...item,
    count: m.table(item.name).count,
    ruleSummaries: Object.fromEntries(item.columns.map(column => {
      const {
        label,
        detail
      } = ruleDescription(item, column);
      return [column.name, {
        label,
        detail
      }];
    })),
    omittedColumns: Object.fromEntries(item.columns.flatMap(column => {
      const info = ruleDescription(item, column);
      return info.allocated ? [[column.name, info.label]] : [];
    }))
  }));
}
function drawTablePreview(table) {
  const current = ticket(),
    owner = session,
    m = model(),
    epoch = m.epoch,
    lifecycle = m.lifecycleVersion;
  const acceptsResult = () => owner.model === m && m.epoch === epoch && m.lifecycleVersion === lifecycle;
  const container = h('section', {
    class: 'wb-table-preview',
    'aria-label': tr("workbench.preview.tableLabel", {table: table.name})
  });
  appendContent(content, container);
  const cached = previewResults.get(m)?.get(table.name);
  const returned = previewReturns.get(m);
  previewReturns.delete(m);
  const resume = returned?.table === table.name ? returned.view : null;
  // A selected-scope cycle does not establish that this table and its own
  // prerequisites are unsupported. Keep useful group samples, but require a
  // table-preview result before caching a capability block for this entry.
  const applicableCache = cached?.origin === 'table' || !generationLimitations(cached?.result).length;
  const initialResult = resume?.result || (applicableCache && cached?.epoch === m.epoch && cached.count === (m.view.previewCount ?? 10) ? cached.result : null);
  const component = openDataPreview({
    container,
    fixedScope: true,
    tables: previewTables(m),
    relationships: {edges:m.schema.edges, nodes:m.schema.nodes},
    currentTable: table.name,
    selectedTables: m.document.tables.map(item => item.name),
    initialCount: m.view.previewCount ?? 10,
    initialResult,
    initialView: resume,
    initialStale: Boolean(resume?.stale),
    onColumnAction: (action, context) => editPreviewColumn(owner, m, 'current', action, context),
    onValidationIssue: issue => {if (owner === session && m === model()) locateInputIssue(issue);},
    onUnsupported: result => {if (current()) showCapabilityReasons(result);},
    onCurrentData: name => {if (current()) viewCurrentData(name);},
    isCurrent: () => current() && m.view.page === 'preview' && m.view.table === table.name,
    guard: task => action(task, tr("workbench.preview.current")),
    setControlDisabled: setActionDisabled,
    generate: async ({
      count
    }) => {
      const result = await owner.previewTable(table.name, count);
      if (result && acceptsResult()) {
        cachePreview(m, [table.name], count, result);
        // A user may leave and re-enter this table while the one shared request
        // is running. Publish into that current view without another request.
        if (root?.isConnected && session === owner && model() === m && tablePreview && tablePreview !== component && m.view.page === 'preview' && m.view.table === table.name) {
          drawBody();
        }
      }
      return result;
    },
    onOptionsChange: ({
      count
    }) => {
      m.view.previewCount = count;
    },
    onResult: (result, {
      count
    }) => {
      if (current()) {
        cachePreview(m, [table.name], count, result);
        updateStatus();
        if (generationLimitations(result).length) notify(previewMessage(result), true);
      }
    },
    onError: error => {
      if (current()) {
        notifyPreviewError(error);
      }
    }
  });
  tablePreview = component;
  tablePreview.cached = Boolean(initialResult);
}
function cachePreview(m, names, count, result, origin = 'table') {
  const cache = previewResults.get(m) || new Map();
  previewResults.set(m, cache);
  for (const name of names) {
    cache.set(name, {
      epoch: m.epoch,
      count,
      origin,
      result
    });
  }
}
function previewReturnHandler(owner, m, {
  scope,
  table,
  column,
  view: sourceView
}) {
  const version = active,
    epoch = m.epoch,
    lifecycle = m.lifecycleVersion,
    schemaHash = m.schema.schema_hash;
  return () => {
    if (!root?.isConnected || version !== active || owner !== session || m !== model() || lifecycle !== m.lifecycleVersion || schemaHash !== m.schema.schema_hash) {
      return;
    }
    const view = {
      ...sourceView,
      stale: sourceView.stale || epoch !== m.epoch
    };
    if (scope === 'selected') {
      return refreshSamples(view);
    }
    if (m.view.page !== 'preview' || m.view.table !== table) {
      return;
    }
    previewReturns.set(m, {
      table,
      view
    });
    drawBody();
    [...content.querySelectorAll('[data-preview-column]')].find(item => item.dataset.previewColumn === column && item.dataset.previewEntry === (sourceView.columnAction || 'information'))?.focus({
      preventScroll: true
    });
  };
}
function editPreviewColumn(owner, m, scope, action, context) {
  if (owner !== session || m !== model() || !validNavigation()) {
    return;
  }
  const table = m.schema.tables.find(item => item.name === context.table),
    column = table?.columns.find(item => item.name === context.column);
  if (!column) {
    return;
  }
  const origin = {
    scope,
    ...context
  };
  openRule(table, column, action === 'information' ? 'information' : 'rule', {
    onReturn: previewReturnHandler(owner, m, origin),
    previewOrigin: origin
  });
}
async function refreshSamples(resume = null) {
  resume = resume?.result ? resume : null;
  const current = modalTicket(),
    owner = session,
    m = model(),
    table = m.view.table,
    epoch = m.epoch,
    lifecycle = m.lifecycleVersion;
  const names = m.document.tables.map(item => item.name);
  const knownLimitation = generationLimitations(m.check).length ? m.check : null;
  const preview = openDataPreview({
    tables: previewTables(m),
    relationships: {edges:m.schema.edges, nodes:m.schema.nodes},
    currentTable: table,
    selectedTables: m.document.tables.map(item => item.name),
    initialScope: 'selected',
    fixedScope: true,
    initialCount: m.view.previewCount ?? 10,
    isCurrent: current,
    initialResult: resume?.result || knownLimitation,
    initialView: resume,
    initialStale: Boolean(resume?.stale),
    onColumnAction: (action, context) => editPreviewColumn(owner, m, 'selected', action, context),
    onValidationIssue: issue => {if (owner === session && m === model()) locateInputIssue(issue);},
    onUnsupported: result => {if (current()) showCapabilityReasons(result);},
    onCurrentData: name => {if (current()) viewCurrentData(name);},
    guard: task => action(task, tr("workbench.preview.selected")),
    setControlDisabled: setActionDisabled,
    generate: async ({
      count
    }) => {
      const result = await owner.check(true, count);
      if (result && owner.model === m && m.epoch === epoch && m.lifecycleVersion === lifecycle) {
        cachePreview(m, names, count, result, 'selected');
        if (!preview.dialog.el.isConnected && root?.isConnected && session === owner && model() === m && tablePreview && m.view.page === 'preview' && names.includes(m.view.table)) {
          drawBody();
        }
      }
      return result;
    },
    onOptionsChange: ({
      count
    }) => {
      m.view.previewCount = count;
    },
    onResult: (result, {
      count
    }) => {
      if (current()) {
        cachePreview(m, m.document.tables.map(item => item.name), count, result, 'selected');
        drawBody();
        notify(previewMessage(result, tr("workbench.preview.selectedScope")), !result.ok);
      }
    },
    onError: error => {
      if (current()) {
        notifyPreviewError(error);
      }
    }
  });
  openedModal = preview.dialog;
  if (resume) {
    [...preview.dialog.body.querySelectorAll('[data-preview-column]')].find(item => item.dataset.previewColumn === resume.column && item.dataset.previewEntry === (resume.columnAction || 'information'))?.focus({
      preventScroll: true
    });
    return;
  }
  if (knownLimitation) {
    notify(previewMessage(knownLimitation), true);
    return;
  }
  await preview.refresh();
}
function previewMessage(result, scope) {
  if (generationLimitations(result).length) return tr('workbench.unsupported.preview');
  if (!result.ok) {
    return tr("workbench.preview.issues");
  }
  if (result.preview_complete === false) {
    return tr("workbench.preview.partial");
  }
  return tr("workbench.preview.updated", {scope: scope});
}
function structureSnapshot() {
  const s = model().schema;
  return {
    format: 'sqlseed-schema-graph',
    version: 1,
    label: s.target_label,
    title: s.target_label,
    nodes: s.nodes,
    edges: s.edges
  };
}
async function configSettings() {
  const current = modalTicket();
  const [providers, locales] = await Promise.all([get('/api/meta/providers'), get('/api/meta/locales')]);
  if (!current()) {
    return;
  }
  providerRequest++;
  providerMetadata = providers;
  updateProviderWarning();
  const draft = structuredClone(model().document),
    controls = [];
  const available = new Set(providers.available || []);
  const dialog = openedModal = modal(tr("workbench.defaults.title"), {
    dismiss: 'footer',
    onClose: () => controls.forEach(c => c.destroy())
  });
  const guide = h('section', {
    class: 'wb-provider-guide',
    'aria-live': 'polite',
    'aria-label': tr("workbench.defaults.features")
  });
  const apply = button(tr("workbench.defaults.apply"), () => {
    if (!current()) {
      dialog.close();
      return;
    }
    if (!available.has(draft.provider)) {
      return;
    }
    model().document = draft;
    model().touch();
    dialog.close();
    draw();
  }, {
    primary: true
  });
  function availabilityLabel(value) {
    if (providers.statuses?.[value]?.status === 'import_error') {
      return tr("workbench.component.importError");
    }
    if (!available.has(value)) {
      return value === 'mimesis' ? tr("workbench.component.notInstalled") : tr("workbench.component.unavailable");
    }
    return value === 'base' ? tr("workbench.component.builtIn") : tr("workbench.component.installed");
  }
  function showGuide() {
    const description = providerGuide(draft.provider, draft.locale);
    const installed = available.has(draft.provider);
    function providerRequirementHint() {
      if (installed && draft.provider === 'faker') {
        return [tr("workbench.component.bundledSuffix")];
      } else if (installed && draft.provider === 'mimesis') {
        return [tr("workbench.component.optionalSuffix")];
      } else {
        return [];
      }
    }
    const status = joinText([availabilityLabel(draft.provider), ...providerRequirementHint()]);
    apply.disabled = !installed;
    function providerUnavailableHint() {
      if (!installed) {
        return h('p', {
          class: 'wb-error'
        }, providerUnavailableMessage());
      } else {
        return null;
      }
    }
    function providerUnavailableMessage() {
      if (providers.statuses?.[draft.provider]?.status === 'import_error') {
        return tr("workbench.defaults.engineBroken", {engine: description.title});
      }
      if (draft.provider === 'mimesis') {
        return tr("workbench.defaults.mimesisMissing");
      }
      return tr("workbench.defaults.engineMissing");
    }
    function providerManagementHint() {
      if (!installed && draft.provider === 'mimesis') {
        return h('p', {
          class: 'wb-provider-example'
        }, h('a', {
          href: '#/settings?section=plugins',
          onclick: dialog.close
        }, tr("workbench.component.manage")), h('br'), h('small', {}, providers.statuses?.mimesis?.status === 'import_error' ? tr("workbench.defaults.repairHelp") : tr("workbench.defaults.installHelp")));
      } else {
        return null;
      }
    }
    replaceContent(guide, ...[h('h3', {}, description.title, h('small', {}, status)), h('p', {}, description.summary), providerUnavailableHint(), providerManagementHint(), h('p', {
      class: 'wb-provider-limit'
    }, description.limits[0] || ''), h('details', {}, h('summary', {}, tr("workbench.defaults.examples")), h('ul', {}, ...description.features.map(feature => h('li', {}, feature))), h('div', {
      class: 'wb-provider-example'
    }, ...description.examples.map(example => h('p', {}, h('span', {}, joinText([example.label, ': '])), h('code', {}, example.value)))), h('small', {
      class: 'muted'
    }, description.exampleNote), ...description.limits.slice(1).map(limit => h('p', {}, limit)), ...description.sources.map(source => h('a', {
      href: source.url,
      target: '_blank',
      rel: 'noopener noreferrer'
    }, source.label)))].filter(Boolean));
  }
  // Unavailable engines may be inspected locally, but cannot be applied.
  // Keep the document's engine in the list so reopening never implies a fallback.
  const choices = [...new Set(['base', 'faker', 'mimesis', ...available, draft.provider].filter(Boolean))];
  const provider = createDropdown({
    label: tr("workbench.defaults.engine"),
    options: choices.map(value => {
      const description = providerGuide(value, draft.locale);
      return {
        value,
        label: joinText([description.title, description.choice, availabilityLabel(value)], ' · ')
      };
    }),
    value: draft.provider,
    onChange: value => {
      draft.provider = value;
      showGuide();
    }
  });
  const locale = createDropdown({
    label: tr("workbench.defaults.locale"),
    options: locales.locales.map(item => ({
      value: item.code,
      label: item.label
    })),
    value: draft.locale,
    onChange: value => {
      draft.locale = value;
      showGuide();
    }
  });
  controls.push(provider, locale);
  appendContent(dialog.body, h('p', {
    class: 'muted'
  }, tr("workbench.defaults.applyHelp")), h('label', {
    class: 'control'
  }, tr("workbench.defaults.engine"), provider.el), guide, h('label', {
    class: 'control'
  }, tr("workbench.defaults.locale"), locale.el), h('p', {
    class: 'wb-settings-note'
  }, tr("workbench.defaults.localeHelp")));
  showGuide();
  appendContent(dialog.actions, button(tr("workbench.action.cancel"), dialog.close), apply);
}
async function save() {
  const current = ticket();
  if (!session.name.trim()) {
    throw new UserFacingError(tr("workbench.config.nameRequired"));
  }
  const saved = await session.save();
  if (current()) {
    updateStatus();
    notify(tr("workbench.config.saved", {revision: saved.revision}));
  }
  return saved;
}
async function check(preview = false) {
  const current = ticket();
  notify(preview ? tr("workbench.preview.loading") : tr("workbench.dependency.loading"));
  const result = await session.check(preview);
  if (!current()) {
    return null;
  }
  if (!result) {
    notify(tr("workbench.dependency.stale"));
    return null;
  }
  function validationResultMessage() {
    if (result.ok) {
      if (preview) {
        return tr("workbench.preview.refreshed");
      } else {
        return tr("workbench.dependency.appendValid");
      }
    } else {
      return tr("workbench.dependency.foundIssues", {count: result.issues?.length || 1});
    }
  }
  notify(validationResultMessage(), !result.ok);
  if (!preview) reportExecutionCheck();
  refreshGraphCheck();
  updateStatus();
  return result;
}
async function refreshSchema() {
  if (!validNavigation()) {
    return;
  }
  const current = session,
    version = active;
  const schema = await readSchema(current.connId);
  if (version !== active) {
    return;
  }
  const changedSchema = schema.schema_hash !== model().schema.schema_hash;
  model().schema = schema;
  model().touch();
  drawBody();
  notify(changedSchema ? tr("workbench.schema.changed") : tr("workbench.schema.refreshed"));
}
async function openDrafts() {
  const current = modalTicket();
  const response = await get(`/api/workbench/drafts?conn_id=${encodeURIComponent(session.connId)}`);
  if (!current()) {
    return;
  }
  const drafts = Array.isArray(response) ? response : response.drafts || [];
  const dialog = openedModal = modal(tr("workbench.config.savedTitle"));
  let opening = false;
  appendContent(dialog.body, h('p', {
    class: 'wb-muted'
  }, tr("workbench.config.openHelp")));
  if (!drafts.length) {
    appendContent(dialog.body, h('p', {}, tr("workbench.config.none")));
  }
  for (const draft of drafts) {
    appendContent(dialog.body, button('', action(async () => {
      if (opening) {
        return;
      }
      opening = true;
      const stillCurrent = ticket();
      try {
        if (model().dirty && (model().document.tables.length || Object.keys(model().view.tableDrafts).length)) {
          await save();
        }
        if (!stillCurrent() || !dialog.body.isConnected) {
          return;
        }
        const full = await get(`/api/workbench/drafts/${encodeURIComponent(draft.id)}`);
        if (!stillCurrent() || !dialog.body.isConnected) {
          return;
        }
        session.open(full);
        dialog.close();
        draw();
      } finally {
        opening = false;
      }
    }), {
      class: 'wb-draft-card'
    }));
  }
  appendContent(dialog.actions, button(tr("workbench.config.management"), () => {
    dialog.close();
    location.hash = '#/configs';
  }, {
    glyph: 'settings'
  }));
  [...dialog.body.querySelectorAll('.wb-draft-card')].forEach((card, i) => appendContent(card, h('strong', {}, drafts[i].name), h('small', {}, joinText([`v${drafts[i].revision}`, formatDate(drafts[i].updated_at * 1000, {dateStyle:'medium', timeStyle:'short', hour12:false})], ' · '))));
}
async function configDocument() {
  const stillCurrent = modalTicket(),
    current = session;
  const opener = root.querySelector('.wb-config-document');
  const documentFeedback = {feedback: 'dialog', restoreFocusTo: () => opener};
  let formatControl;
  const dialog = openedModal = modal(tr("workbench.config.editYaml"), {
    dismiss: 'footer',
    wide: true,
    onClose: () => formatControl?.destroy()
  });
  const text = h('textarea', {
    class: 'wb-code',
    rows: 20,
    spellcheck: false,
    'aria-label': tr("workbench.yaml.label"),
    'aria-busy': 'true',
    disabled: true,
    placeholder: tr("workbench.yaml.loading")
  });
  const error = h('p', {
    class: 'wb-error',
    role: 'alert'
  });
  let textVersion = 0,
    requestVersion = 0;
  text.addEventListener('input', () => {
    textVersion++;
  });
  appendContent(dialog.body, h('p', {
    class: 'muted'
  }, tr("workbench.yaml.help")), text, error);
  const file = h('input', {
    type: 'file',
    accept: '.yaml,.yml,.json',
    hidden: true,
    onchange: async e => {
      const selected = e.target.files?.[0];
      if (!selected) {
        return;
      }
      if (selected.size > 2 * 1024 * 1024) {
        setText(error, tr("workbench.yaml.tooLarge"));
        return;
      }
      const version = textVersion;
      try {
        const value = await selected.text();
        if (dialog.body.isConnected && version === textVersion) {
          text.value = value;
          textVersion++;
        }
      } catch (readError) {
        if (stillCurrent() && dialog.body.isConnected && version === textVersion) setText(error, errorText(readError));
      }
    }
  });
  async function parseVisible() {
    const applyCurrent = ticket(),
      raw = text.value,
      inputVersion = textVersion,
      request = ++requestVersion;
    const parsed = await send('/api/workbench/parse', {
      conn_id: current.connId,
      text: raw
    });
    if (!applyCurrent() || !dialog.body.isConnected || request !== requestVersion) {
      return null;
    }
    if (raw !== text.value || inputVersion !== textVersion) {
      setText(error, tr("workbench.yaml.changed"));
      return null;
    }
    return {
      document: parsed.document,
      current: () => applyCurrent() && dialog.body.isConnected && request === requestVersion && raw === text.value && inputVersion === textVersion
    };
  }
  async function downloadCurrent(format) {
    try {
      const parsed = await parseVisible();
      if (!parsed) {
        return;
      }
      const output = await send('/api/workbench/export', {
        conn_id: current.connId,
        document: parsed.document
      });
      if (!parsed.current()) {
        return;
      }
      const exportedDocument = () => {
        if (format === 'json') {
          if (typeof output.json === 'string') {
            return output.json;
          } else {
            return JSON.stringify(output.json, null, 2);
          }
        } else {
          return output.yaml;
        }
      };
      download(`sqlseed.${format}`, exportedDocument(), format === 'json' ? 'application/json' : 'application/yaml');
    } catch (e) {
      if (dialog.body.isConnected) {
        setText(error, errorText(e));
      }
    }
  }
  let format = 'yaml';
  formatControl = createDropdown({
    label: tr("workbench.yaml.format"),
    value: format,
    options: [{
      value: 'yaml',
      label: 'YAML'
    }, {
      value: 'json',
      label: 'JSON'
    }],
    onChange: value => {
      format = value;
    }
  });
  const readFile = button(tr("workbench.yaml.readFile"), () => file.click(), {glyph: 'upload', disabled: true});
  const downloadFile = button(tr("workbench.yaml.download"), action(() => downloadCurrent(format), tr("workbench.yaml.export"), documentFeedback), {
    glyph: 'download', disabled: true
  });
  const toolbar = h('div', {
    class: 'wb-document-toolbar',
    role: 'group',
    'aria-label': tr("workbench.yaml.tools")
  }, file, readFile, h('label', {
    class: 'wb-document-format'
  }, tr("workbench.yaml.format"), formatControl.el), downloadFile);
  dialog.body.insertBefore(toolbar, text);
  const apply = button(tr("workbench.yaml.apply"), action(async () => {
    try {
      const parsed = await parseVisible();
      if (!parsed) {
        return;
      }
      current.model.replaceDocument(parsed.document);
      executionChecks.delete(current.model);
      dialog.close();
      draw();
      notify(tr("workbench.yaml.applied"));
    } catch (e) {
      if (dialog.body.isConnected) {
        setText(error, errorText(e));
      }
    }
  }, tr("workbench.yaml.check"), documentFeedback), {
    primary: true, disabled: true
  });
  appendContent(dialog.actions, button(tr("workbench.action.cancel"), dialog.close), apply);
  try {
    const exported = await send('/api/workbench/export', {
      conn_id: current.connId,
      document: current.model.payload(current.name).document
    });
    if (!stillCurrent() || !dialog.body.isConnected) return;
    text.value = exported.yaml;
    setAttr(text, 'placeholder', '');
    text.disabled = readFile.disabled = false;
    setActionDisabled(downloadFile, false);
    setActionDisabled(apply, false);
    if (exported.credentials_omitted) {
      appendContent(dialog.body, h('p', {
        class: 'muted'
      }, tr("workbench.yaml.credentials")));
    }
  } catch (e) {
    if (stillCurrent() && dialog.body.isConnected) {
      setAttr(text, 'placeholder', tr("workbench.yaml.failed"));
      setText(error, errorText(e));
    }
  } finally {
    text.removeAttribute('aria-busy');
  }
}
async function importStructure() {
  const current = modalTicket();
  const dialog = openedModal = modal(tr("workbench.schema.importGraph"), {
    dismiss: 'footer',
    wide: true
  });
  const example = {
    format: 'sqlseed-schema-graph',
    version: 1,
    title: t("workbench.graph.title"),
    nodes: [{
      id: 'users'
    }, {
      id: 'orders'
    }],
    edges: [{
      id: 'orders_user_id',
      source: 'users',
      target: 'orders',
      sourceColumns: ['id'],
      targetColumns: ['user_id'],
      nullable: false
    }]
  };
  const text = h('textarea', {
    class: 'wb-code',
    rows: 10,
    'aria-label': tr("workbench.graph.json"),
    placeholder: tr("workbench.graph.placeholder")
  });
  const error = h('p', {
    class: 'wb-error',
    role: 'alert'
  });
  const file = h('input', {
    type: 'file',
    accept: '.json',
    hidden: true,
    onchange: async e => {
      const selected = e.target.files?.[0];
      if (!selected) {
        return;
      }
      if (selected.size > 1024 * 1024) {
        setText(error, tr("workbench.graph.tooLarge"));
        return;
      }
      try {
        const value = await selected.text();
        if (dialog.body.isConnected) {
          text.value = value;
        }
      } catch (readError) {
        if (current() && dialog.body.isConnected) setText(error, errorText(readError));
      }
    }
  });
  appendContent(dialog.body, h('p', {}, tr("workbench.graph.importHelp")), h('details', {}, h('summary', {}, tr("workbench.graph.formatHelp")), h('p', {}, tr("workbench.graph.formatDetails")), h('pre', {
    class: 'wb-import-help'
  }, JSON.stringify(example, null, 2))), text, error);
  appendContent(dialog.actions, file, button(tr("workbench.graph.template"), () => download('sqlseed-schema-template.json', JSON.stringify(example, null, 2))), button(tr("workbench.graph.selectFile"), () => file.click()), button(tr("workbench.action.cancel"), dialog.close), button(tr("workbench.graph.import"), () => {
    try {
      if (!current()) {
        dialog.close();
        return;
      }
      if (new Blob([text.value]).size > 1024 * 1024) {
        throw new UserFacingError(tr("workbench.graph.tooLarge"));
      }
      const schema = JSON.parse(text.value);
      if (schema.version !== undefined && schema.version !== 1 || schema.format !== undefined && schema.format !== 'sqlseed-schema-graph') {
        throw new UserFacingError(tr("workbench.graph.invalidFormat"));
      }
      if (!Array.isArray(schema.nodes) || !Array.isArray(schema.edges) || !schema.nodes.length || schema.nodes.length > 200 || schema.edges.length > 1000) {
        throw new UserFacingError(tr("workbench.graph.invalidSize"));
      }
      const ids = new Set();
      for (const node of schema.nodes) {
        if (typeof node?.id !== 'string' || !node.id.trim() || ids.has(node.id)) {
          throw new UserFacingError(tr("workbench.graph.invalidNodes"));
        }
        ids.add(node.id);
      }
      const edgeIds = new Set();
      schema.edges = schema.edges.map((edge, i) => {
        if (!edge || !ids.has(edge.source) || !ids.has(edge.target)) {
          throw new UserFacingError(tr("workbench.graph.invalidEndpoints"));
        }
        const sourceColumns = edge.sourceColumns ?? [],
          targetColumns = edge.targetColumns ?? [];
        if (!Array.isArray(sourceColumns) || !Array.isArray(targetColumns) || sourceColumns.length !== targetColumns.length || [...sourceColumns, ...targetColumns].some(col => typeof col !== 'string' || !col.trim())) {
          throw new UserFacingError(tr("workbench.graph.invalidColumns"));
        }
        const id = edge.id || `relation-${i + 1}`;
        if (typeof id !== 'string' || edgeIds.has(id)) {
          throw new UserFacingError(tr("workbench.graph.invalidIds"));
        }
        edgeIds.add(id);
        return {
          ...edge,
          id,
          sourceColumns,
          targetColumns
        };
      });
      if (typeof schema.title !== 'string') {
        schema.title = typeof schema.label === 'string' ? schema.label : t("workbench.graph.importedTitle");
      }
      importedStructures.set(session.connId, schema);
      model().view.imported = true;
      dialog.close();
      drawBody();
    } catch (e) {
      setText(error, errorText(e));
    }
  }, {
    primary: true
  }));
}
function drawImportedStructure(schema) {
  const section = h('section', {
    class: 'panel-content database-graph wb-imported-structure'
  });
  const inspect = h('div', {
    class: 'wb-edge-mapping',
    hidden: true
  });
  appendContent(section, h('div', {
    class: 'wb-imported-note'
  }, h('div', {}, h('h3', {}, schema.title), h('span', {}, tr("workbench.graph.readOnly"))), button(tr("workbench.action.returnDatabase"), () => {
    model().view.imported = false;
    drawBody();
  }, {
    small: true
  })));
  graphOwner = null;
  graph = createSchemaGraph({
    schema: {
      ...schema,
      tables: []
    },
    mode: 'all',
    onSelect: () => {},
    onEdge: edge => {
      inspect.hidden = false;
      replaceContent(inspect, h('strong', {}, `${edge.source} → ${edge.target}`), ...edge.sourceColumns.map((column, i) => h('code', {}, `${column} → ${edge.targetColumns[i]}`)));
    }
  });
  if (graph.toolbar) {
    appendContent(section, graph.toolbar);
  }
  appendContent(section, graph.el, inspect);
  appendContent(content, section);
}
function appendClearRecoveryIssues(card, state, context, locate, reset) {
  if (!state.current) return;
  for (const issue of state.otherIssues) {
    appendContent(card, h('p', {}, serverText(issue)));
    if (issue.table) appendContent(card, button(tr("workbench.action.viewTable", {table: issue.table}), () => locate(issue.table), {plain:true, small:true}));
    if (issue.code === 'identity_reset_not_supported' && reset) appendContent(card, button(tr("workbench.clear.disableReset"), reset, {small:true}));
  }
  if (context.error) appendContent(card, h('p', {}, tr("workbench.clear.retryHelp", {error: context.error})));
}
function appendClearRecoveryAction(actions, state, needsScope, review, inspect) {
  if (needsScope && review) {
    appendContent(actions, button(tr("workbench.clear.expand"), review, {primary:true, small:true}));
  } else if (inspect) {
    appendContent(actions, button(['ok','reviewed'].includes(state.state) ? tr("workbench.action.viewPlan") : tr("workbench.clear.recheck"), inspect, {primary:true, small:true, disabled:state.state==='checking'}));
  }
}
function clearRecoveryCard(m, {inspect, review, append, adjust, locate, reset}) {
  const context = executionChecks.get(m), state = clearRecoveryState(m, context);
  if (state.unsupported.length) return generationUnsupportedCard({issues: state.unsupported});
  const card = h('section', {class:'wb-clear-recovery', 'aria-label':tr("workbench.clear.recoveryTitle")});
  appendContent(card, h('p', {class:'wb-clear-recovery-status', role:'status'}, state.status));
  const needsScope = state.current && state.state === 'blocked' && state.externalTables.length > 0;
  if (state.state === 'blocked') {
    appendContent(card, h('p', {}, state.externalTables.length
      ? tr("workbench.clear.expandHelp", {count: state.externalTables.length})
      : tr("workbench.clear.resolveHelp")));
  } else if (state.state === 'pending') {
    appendContent(card, h('p', {}, tr("workbench.clear.scopeChanged")));
  }
  const actions = h('div', {class:'wb-clear-recovery-actions'});
  appendClearRecoveryAction(actions, state, needsScope, review, inspect);
  appendContent(card, actions);
  if (state.externalTables.length) {
    appendContent(card, h('p', {class:'wb-muted'}, state.current ? tr("workbench.clear.relatedTables") : tr("workbench.clear.previousTables")), h('ul', {class:'wb-clear-recovery-tables'}, ...state.externalTables.map(name => h('li', {}, button(name, () => locate(name), {plain:true, small:true})))));
  }
  appendClearRecoveryIssues(card, state, context, locate, reset);
  if (!['ok','reviewed','checking'].includes(state.state)) {
    appendContent(card, h('details', {}, h('summary', {}, tr("workbench.clear.alternatives")),
      h('div', {class:'wb-clear-recovery-actions'}, button(tr("workbench.clear.adjustScope"), adjust, {small:true}), button(tr("workbench.clear.switchAppend"), append, {small:true}))));
  }
  return card;
}
async function reviewClearScope() {
  const current = ticket(), m = model(), owner = session;
  const candidate = clearScopeCandidate(m);
  const dialog = openedModal = modal(tr("workbench.clear.expandTitle"), {dismiss:'footer', wide:true});
  const valid = () => current() && dialog.body.isConnected && executionChecks.has(m);
  const feedback = h('div', {role:'status', 'aria-live':'polite'});
  const adjust = () => {dialog.close();locateGenerationSelection();};
  let candidateReady = false;
  const apply = button(tr("workbench.clear.confirmScope"), action(async () => {
    if (!valid() || !candidateReady) return;
    for (const table of candidate.added) m.toggleTable(table.name, true);
    executionChecks.set(m, {epoch:m.epoch, lifecycle:m.lifecycleVersion, state:'pending'});
    dialog.close();draw();
    await summary();
  }, tr("workbench.clear.prepare"), {feedback:'modal'}), {primary:true, disabled:true});
  appendContent(dialog.body, h('section', {class:'wb-clear-recovery'},
    h('h3', {}, tr("workbench.clear.scopeCounts", {original: candidate.original.length, total: candidate.total, added: candidate.added.length})),
    h('p', {}, tr("workbench.clear.relatedHelp")),
    h('p', {}, tr("workbench.clear.confirmHelp")), feedback));
  appendContent(dialog.body, h('table', {class:'wb-clear-scope-review'},
    h('thead', {}, h('tr', {}, ...[tr("workbench.clear.addedTables"),tr("workbench.clear.existingRows"),tr("workbench.clear.generatedRows")].map(label=>h('th', {}, label)))),
    h('tbody', {}, ...candidate.added.map(table=>h('tr', {}, h('td', {}, table.name), h('td', {}, Number.isFinite(table.rowCount) ? formatNumber(table.rowCount) : tr("workbench.value.unknown")), h('td', {}, formatNumber(table.count)))))));
  appendContent(dialog.body, h('details', {}, h('summary', {}, tr("workbench.clear.originalTables", {count: candidate.original.length})), h('p', {}, candidate.original.join('、'))), h('p', {class:'wb-muted'}, tr("workbench.clear.countDisclaimer")));
  appendContent(dialog.actions, button(tr("workbench.action.cancel"), dialog.close), apply);
  if (!candidate.added.length || candidate.unresolved.length) {
    appendContent(feedback, h('p', {}, candidate.unresolved.length ? tr("workbench.clear.unresolved", {tables: candidate.unresolved.join('、')}) : tr("workbench.clear.noCandidates")), button(tr("workbench.clear.adjust"), adjust, {small:true}));
    return;
  }
  setText(feedback, tr("workbench.clear.checkingCandidate"));
  try {
    const result = await send('/api/workbench/check', {conn_id:owner.connId, document:candidate.document, schema_hash:m.schema.schema_hash, count:3});
    if (!valid()) return;
    const errors = (result.issues || []).filter(issue=>issue.severity==='error');
    if (result.existing_cycle_sources?.length) {
      const tables = [...new Set(result.existing_cycle_sources.flatMap(source=>[source.table, source.source_table]))];
      errors.push({severity:'error', code:'replacement_cycle_not_supported', tables,
        message_key:'backend.workbench_execution.existing_cycle_cannot_clear', message_params:{p1:tables.join(', ')}});
    }
    const passed = result.ok && !errors.length;
    const issueDetails = errors.map(issue => {
      let prefix = '';
      if (issue.tables?.length) prefix = issue.tables.join(', ') + ': ';
      else if (issue.table) prefix = issue.table + ': ';
      const detail = h('div', {}, h('p', {}, joinText([prefix, serverText(issue)])));
      if (issue.code === 'cross_table_cycle') appendContent(detail, cycleIssueDetails(issue, name => {
        dialog.close(); inspectorMode = 'dependencies'; chooseTable(name, 'graph');
      }, candidate.document));
      return detail;
    });
    const failedMessage = generationLimitations(result).length ? 'workbench.unsupported.title' : 'workbench.clear.candidateFailed';
    replaceContent(feedback, h('p', {}, tr(passed ? 'workbench.clear.candidatePassed' : failedMessage)), ...issueDetails);
    if (!passed && !generationLimitations(result).length) {
      const tables = [...new Set(errors.flatMap(issue=>issue.tables || (issue.table ? [issue.table] : [])))].filter(name=>m.schema.tables.some(table=>table.name===name));
      appendContent(feedback, h('div', {class:'wb-clear-recovery-actions'}, ...tables.map(name=>button(tr("workbench.action.locate", {target: name}), ()=>{dialog.close();inspectorMode='dependencies';chooseTable(name,'graph');}, {small:true})), button(tr("workbench.clear.adjust"), adjust, {small:true})));
    }
    candidateReady = passed;
    setActionDisabled(apply, !passed);
  } catch (error) {
    if (valid()) setText(feedback, tr("workbench.clear.candidateError", {error: errorText(error)}));
  }
}
async function summary() {
  const stillCurrent = modalTicket();
  // Busy controls lose native focus before the async checks open the dialog.
  const pendingAction = pendingActions.get(session)?.get('database');
  const opener = pendingAction?.opener || document.activeElement;
  const guideAction = opener?.dataset.guideAction;
  if (!model().document.tables.length) {
    throw new UserFacingError(tr("workbench.scope.required"));
  }
  if (model().dirty) {
    await save();
  }
  if (!stillCurrent()) {
    return;
  }
  const result = generationLimitations(model().check).length ? model().check : await check(false);
  if (!result || !stillCurrent()) {
    return;
  }
  const current = session,
    m = model(),
    epoch = m.epoch,
    lifecycle = m.lifecycleVersion,
    version = active;
  let sequence = 0,
    plan = null,
    busy = false,
    planning = false,
    failed = false,
    execution = {
      // Only the current model's adjustment flow remembers clear intent. No
      // plan/hash/reset option survives closing this confirmation dialog.
      mode: executionChecks.has(m) && m.schema.dialect === 'sqlite' ? 'replace_selected' : 'append',
      reset_identity: false
    };
  const returnFocus = () => {
    if (version !== active || current !== session || m !== model()) return null;
    const target = guideAction ? root.querySelector(`[data-guide-action="${guideAction}"]`) : opener;
    if (target?.isConnected && !target.hidden) return target;
    return [root.querySelector('[data-plan-entry]'), root.querySelector('[data-guide-action="next"]'),
      root.querySelector('.wb-clear-recovery-actions')?.querySelector('button'),
      root.querySelector('.wb-generation-unsupported')?.querySelector('button')]
      .find(control => control && !control.hidden && !control.disabled);
  };
  if (pendingAction) pendingAction.returnFocus = returnFocus;
  const dialog = openedModal = modal(tr("workbench.execution.title"), {
    dismiss: 'footer',
    wide: true,
    returnFocus,
    onClose: () => {
      sequence++;
      plan = null;
      const context = executionChecks.get(m);
      if (execution.mode === 'replace_selected' && context && context.state !== 'blocked') {
        executionChecks.set(m, {...context, state:['ok', 'reviewed'].includes(context.state) ? 'reviewed' : 'pending'});
      }
      if (version === active && current === session) {
        updateStatus();
        reportExecutionCheck(m);
      }
    }
  });
  const isCurrent = () => version === active && current === session && m === model() && m.epoch === epoch && m.lifecycleVersion === lifecycle && dialog.body.isConnected;
  const planInfo = h('div', {
    class: 'wb-execution-plan',
    id: 'wb-execution-details',
    tabindex: -1
  });
  const reset = h('input', {
    type: 'checkbox',
    checked: false,
    disabled: true,
    'aria-label': tr("workbench.execution.reset"),
    'aria-describedby': 'wb-reset-reason',
    onchange: () => {
      if (planning || busy || reset.disabled) {
        return;
      }
      execution.reset_identity = reset.checked;
      return inspectExecution();
    }
  });
  const resetReason = h('small', {id: 'wb-reset-reason', class: 'wb-reset-reason'});
  const unsupported = generationLimitations(result).length > 0;
  function selectAppend() {
    if (busy || unsupported) return;
    execution = {mode:'append', reset_identity:false};
    append.checked = true;
    replace.checked = false;
    reset.checked = false;
    reset.disabled = true;
    return inspectExecution();
  }
  const append = h('input', {
    type: 'radio',
    name: 'execution-mode',
    value: 'append',
    checked: execution.mode === 'append',
    'aria-label': tr("workbench.execution.append"),
    onchange: selectAppend
  });
  const replace = h('input', {
    type: 'radio',
    name: 'execution-mode',
    value: 'replace_selected',
    checked: execution.mode === 'replace_selected',
    disabled: m.schema.dialect !== 'sqlite',
    'aria-label': tr("workbench.execution.replace"),
    onchange: () => {
      if (planning || busy || unsupported || m.schema.dialect !== 'sqlite') {
        return;
      }
      execution.mode = 'replace_selected';
      return inspectExecution();
    }
  });
  function databaseDialectLabel() {
    if (m.schema.dialect === 'sqlite') {
      return 'SQLite';
    } else if (m.schema.dialect === 'postgresql') {
      return 'PostgreSQL';
    } else {
      return m.schema.dialect;
    }
  }
  const totalRows = m.document.tables.reduce((sum, table) => sum + BigInt(table.count), 0n);
  appendContent(dialog.body, planInfo, h('section', {
    class: 'wb-write-target',
    'aria-label': tr("workbench.execution.target")
  }, h('div', {}, h('strong', {}, tr("workbench.execution.target")), h('span', {
    class: 'wb-muted'
  }, databaseDialectLabel())), h('p', {
    class: 'mono'
  }, m.schema.target_label), h('small', {
    class: 'wb-muted'
  }, m.schema.dialect === 'sqlite' ? tr("workbench.execution.fileTargetHelp") : tr("workbench.execution.urlTargetHelp"))), h('p', {
    class: 'wb-muted'
  }, `${current.name} · v${m.saved.revision}`), h('fieldset', {
    class: 'wb-write-strategy'
  }, h('legend', {}, tr("workbench.execution.existingData")), h('label', {}, append, h('span', {}, h('strong', {}, tr("workbench.execution.append")), h('small', {}, tr("workbench.execution.appendHelp")))), h('label', {}, replace, h('span', {}, h('strong', {}, tr("workbench.execution.replace")), h('small', {}, tr("workbench.execution.replaceHelp")))), ...(m.schema.dialect !== 'sqlite' ? [h('p', {
    class: 'muted'
  }, tr("workbench.execution.postgresAppend"))] : []), h('label', {
    class: 'wb-reset-identity'
  }, reset, h('span', {}, tr("workbench.execution.reset"), resetReason))), h('div', {
    class: 'wb-summary-total'
  }, h('strong', {}, formatNumber(totalRows)), tr("workbench.execution.totalRows", {count: totalRows}), ' / ', tr("workbench.execution.totalTables", {count: m.document.tables.length, tables: formatNumber(m.document.tables.length)})), ...(unsupported ? [h('p', {class: 'wb-muted'}, tr('workbench.unsupported.scope'))] : []), h(unsupported ? 'ul' : 'ol', {
    class: 'wb-summary-plan'
  }, ...(unsupported ? m.document.tables.map(table => table.name) : result.order || []).map(name => h('li', {}, button(name, () => {
    dialog.close();
    inspectorMode = 'dependencies';
    chooseTable(name, 'graph');
  }, {
    plain: true,
    class: 'mono execution-table'
  }), h('span', {}, tr("workbench.count.rows", {count: m.table(name).count}))))));
  const submit = button(tr("workbench.execution.write"), async () => {
    if (!isCurrent() || busy || planning || !m.canRun() || execution.mode === 'replace_selected' && !plan?.ok) {
      return;
    }
    busy = true;
    failed = false;
    submit.disabled = true;
    setStrategyBusy(true);
    try {
      const run = await current.run(execution.mode === 'append' ? undefined : execution, plan?.plan_hash);
      if (isCurrent()) {
        executionChecks.delete(m);
        dialog.close();
        location.hash = `#/runs?id=${encodeURIComponent(run.id)}`;
      }
    } catch (error) {
      if (isCurrent()) {
        appendContent(planInfo, h('p', {
          class: 'wb-error',
          role: 'alert'
        }, errorText(error)));
        busy = false;
        failed = true;
        setStrategyBusy(false);
        submit.disabled = execution.mode === 'replace_selected';
        if (execution.mode === 'replace_selected') {
          plan = null;
          executionChecks.set(m, {epoch, lifecycle, state:'pending'}); updateStatus();
          appendContent(planInfo, button(tr("workbench.execution.reviewAgain"), inspectExecution));
        }
      }
    }
  }, {
    primary: true,
    disabled: !m.canRun(),
    'aria-describedby': 'wb-execution-status'
  });
  const executionStatus = h('span', {id:'wb-execution-status', role:'status', 'aria-live':'polite'});
  const showDetails = button(tr('workbench.execution.viewReasons'), () => {
    planInfo.focus({preventScroll:true});
    planInfo.scrollIntoView({block:'start'});
  }, {plain:true, small:true, 'aria-controls':'wb-execution-details'});
  const executionFeedback = h('div', {class:'wb-execution-feedback'}, executionStatus, showDetails);
  dialog.actions.classList.add('wb-execution-actions');
  appendContent(dialog.actions, executionFeedback, button(unsupported ? tr('workbench.unsupported.close') : tr("workbench.execution.return"), dialog.close), submit);
  function syncExecutionStatus() {
    let state = 'ready';
    if (busy) state = 'busy';
    else if (planning) state = 'checking';
    else if (failed) state = 'failure';
    else if (unsupported || !m.canRun() || execution.mode === 'replace_selected' && (!plan?.ok || !plan?.atomic)) state = 'blocked';
    executionFeedback.dataset.state = state;
    setText(executionStatus, tr(`workbench.execution.status.${state}`));
    showDetails.hidden = !['blocked', 'failure'].includes(state);
  }
  function appendPlan() {
    executionChecks.delete(m);
    notify(m.check?.ok ? tr("workbench.dependency.appendValid") : tr("workbench.execution.appendUnchecked"), !m.check?.ok);
    updateStatus();
    let helpKey = 'workbench.execution.appendPlanHelp';
    if (!result.ok) helpKey = 'workbench.execution.appendUnchecked';
    else if (result.existing_cycle_sources?.length) helpKey = 'workbench.execution.existingCycle';
    replaceContent(planInfo, h('p', {
      class: 'wb-muted'
    }, tr(helpKey)), ...generationDiagnostics());
  }
  function generationDiagnostics() {
    return (result.issues || []).filter(issue => !unsupported || issue.code !== 'cross_table_cycle').map(issue => h('p', {
      class: issue.severity === 'error' ? 'wb-error' : 'wb-muted'
    }, joinText([issue.table || '', serverText(issue)], ' ')));
  }
  function setStrategyBusy(value) {
    append.disabled = busy || unsupported;
    replace.disabled = value || unsupported || m.schema.dialect !== 'sqlite';
    reset.disabled = value || execution.mode !== 'replace_selected' || !result.ok || !plan?.ok || !plan?.atomic || !plan?.reset_identity_supported;
    const hasSequence = m.document.tables.some(item => m.schema.tables.find(table => table.name === item.name)?.columns.some(column => column.is_autoincrement));
    let reason;
    if (m.schema.dialect !== 'sqlite') reason = tr('workbench.execution.resetDialect', {dialect: databaseDialectLabel()});
    else if (!hasSequence) reason = joinText([tr('workbench.execution.resetUnneeded'),
      !result.ok || plan?.ok === false ? tr('workbench.execution.resetBlocked') : ''], ' ');
    else if (!result.ok || plan?.ok === false) reason = tr('workbench.execution.resetBlocked');
    else if (execution.mode !== 'replace_selected') reason = tr('workbench.execution.resetAppend');
    else if (value) reason = tr('workbench.execution.resetChecking');
    else if (!plan) reason = tr('workbench.execution.resetNoPlan');
    else if (!plan.reset_identity_supported) reason = tr('workbench.execution.resetNotSupported');
    else reason = tr('workbench.execution.resetHelp');
    setText(resetReason, reason);
    setAttr(planInfo, 'aria-busy', String(value));
    syncExecutionStatus();
  }
  function recoveryActions() {
    return {
      append:selectAppend,
      review: () => {dialog.close();return action(reviewClearScope, tr("workbench.clear.reviewScope"), {feedback:'modal'})();},
      adjust: () => {dialog.close();locateGenerationSelection();},
      locate: name => {dialog.close();chooseTable(name,'graph');},
      reset: () => {reset.checked=false;execution.reset_identity=false;return inspectExecution();}
    };
  }
  function acceptExecutionPlan(response) {
    plan = response;
    executionChecks.set(m, {epoch, lifecycle, issues:structuredClone(plan.issues || []), state:plan.ok && plan.atomic ? 'ok' : 'blocked'}); updateStatus();
    const tables = plan.clear_tables || [];
    replaceContent(planInfo, clearRecoveryCard(m, recoveryActions()), h('details', {}, h('summary', {}, tr("workbench.execution.clearCounts", {intent: plan.ok && plan.atomic ? tr("workbench.execution.willClear") : tr("workbench.execution.proposedClear"), count: tables.length, tables: formatNumber(tables.length), rows: formatNumber(tables.reduce((sum, t) => sum + t.row_count, 0))})),
      h('ul', {}, ...tables.map(table => h('li', {}, tr("workbench.execution.tableCount", {table: table.name, count: table.row_count})))),
      h('p', {}, plan.atomic ? tr("workbench.execution.atomic") : tr("workbench.execution.nonAtomic")),
      ...(plan.issues || []).filter(issue=>issue.severity!=='error').map(issue=>h('p',{class:'wb-muted'},serverText(issue)))));
    const errors = (plan.issues || []).filter(issue => issue.severity === 'error');
    if (errors.length) appendContent(planInfo, h('details', {}, h('summary', {}, tr('workbench.execution.diagnostics')),
      ...errors.map(issue => h('p', {class:'wb-error'}, serverText(issue)))));
    appendContent(planInfo, ...generationDiagnostics());
    submit.disabled = !plan.ok || !plan.atomic || !m.canRun();
    reset.disabled = !plan.reset_identity_supported;
  }
  async function inspectExecution() {
    if (!isCurrent() || busy || planning && execution.mode !== 'append') {
      return;
    }
    const request = ++sequence;
    plan = null;
    failed = false;
    submit.disabled = true;
    if (unsupported) {
      if (execution.mode === 'replace_selected') executionChecks.set(m, {epoch, lifecycle, issues:structuredClone(result.issues), state:'blocked'});
      replaceContent(planInfo, generationUnsupportedCard(result), ...generationDiagnostics());
      setText(submit, tr('workbench.unsupported.cannotGenerate'));
      setStrategyBusy(false); updateStatus();
      return;
    }
    if (execution.mode === 'append') {
      appendPlan();
      setText(submit, tr("workbench.execution.write"));
      submit.disabled = planning || !m.canRun();
      setStrategyBusy(planning);
      return;
    }
    setText(submit, tr("workbench.execution.clearWrite"));
    executionChecks.set(m, {...executionChecks.get(m), epoch, lifecycle, state:'checking'}); updateStatus(); reportExecutionCheck(m);
    replaceContent(planInfo, h('p', {}, tr("workbench.execution.preflight")));
    planning = true;
    setStrategyBusy(true);
    try {
      const response = await current.executionPlan({
        ...execution
      });
      if (!isCurrent() || request !== sequence) {
        return;
      }
      acceptExecutionPlan(response);
    } catch (error) {
      if (isCurrent() && request === sequence) {
        failed = true;
        executionChecks.set(m, {epoch, lifecycle, error:errorText(error), state:'blocked'}); updateStatus();
        replaceContent(planInfo, clearRecoveryCard(m, {...recoveryActions(), inspect:inspectExecution}), ...generationDiagnostics());
      }
    } finally {
      planning = false;
      if (isCurrent()) {
        setStrategyBusy(false);
        if (execution.mode === 'append') {
          submit.disabled = !m.canRun();
        }
      }
    }
  }
  await inspectExecution();
}
