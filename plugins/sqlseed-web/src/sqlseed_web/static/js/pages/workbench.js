import { h, api, get, store, restoreConnection } from '../api.js';
import { genLabel, paramLabel } from '../labels.js';
import { createDropdown } from '../dropdown.js';
import { readGenerationDefaults } from '../generation-defaults.js';
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
const databaseActions = new Map([[save, '保存配置'], [showDependencies, '检查依赖'], [showPlan, '检查依赖'], [summary, '准备生成计划'], [refreshSchema, '读取数据库结构'], [configDocument, '读取配置文档']]);
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
let guidanceCollapsed = false;
let providerMetadata = null,
  providerRequest = 0;
try {
  guidanceCollapsed = localStorage.getItem('sqlseed.workbench.guide.collapsed') === 'true';
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
    notice.textContent = text;
    notice.className = `wb-notice${error ? ' wb-error' : ''}`;
    notice.dataset.execution = '';
    notice.dataset.inputValidation = inputValidation ? 'true' : '';
  }
  const banner = root?.querySelector('.wb-operation-status');
  if (banner && error) {
    banner.hidden = false;
    banner.textContent = text;
    banner.className = 'wb-operation-status wb-error';
    banner.dataset.inputValidation = inputValidation ? 'true' : '';
  }
}
function notifyPreviewError(error) {
  notify(error.message, true, {inputValidation: error.code === 'workbench_invalid_input'});
}
function reportExecutionCheck(m = model()) {
  const context = executionChecks.get(m);
  if (!context || !notice?.isConnected) return;
  notice.textContent = `${clearRecoveryState(m, context).status}。处理入口在上方引导中。`;
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
    pending.set(key, {label: label || '处理请求', feedback});
    syncBusy();
    try {
      return await fn(...args);
    } catch (error) {
      if (version === active) {
        notify(error.message, true);
      }
    } finally {
      pending.delete(key);
      if (owner === session) {
        syncBusy();
      }
      // Closing while a request disables its opener cannot restore focus yet.
      // Retry after releasing the gate only if the user has not focused elsewhere.
      if (version === active && owner === session && focusTarget?.isConnected && !focusTarget.disabled &&
          (!document.activeElement || document.activeElement === document.body)) {
        focusTarget.focus({preventScroll: true});
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
      control.setAttribute('aria-busy', 'true');
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
    banner.textContent = `正在${label}，请稍候。期间可以查看和编辑字段。`;
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
    notify([...model().errors.values()].join('；'), true, {inputValidation: true});
    return false;
  }
  return true;
}
function chooseTable(name, page = 'fields', graphMode = 'paths') {
  if (!validNavigation()) {
    return;
  }
  if (!model().schema.tables.some(t => t.name === name)) {
    notify('这是其他 schema 的引用来源，仅展示结构。');
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
  const rendered = drawBody();
  sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({
    block: 'nearest'
  });
  return rendered;
}
function locateGenerationSelection() {
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
function updateStatus() {
  if (!status?.isConnected) {
    return;
  }
  const m = model();
  if (!m.errors.size) {
    for (const message of root.querySelectorAll('[data-input-validation="true"]')) {
      message.textContent = '';
      message.dataset.inputValidation = '';
      if (message.classList.contains('wb-operation-status')) message.hidden = true;
      else message.classList.remove('wb-error');
    }
  }
  if (notice?.dataset.execution === 'true') reportExecutionCheck(m);
  if (m.errors.size) {
    status.textContent = '有待修正的输入';
  } else if (m.dirty) {
    status.textContent = '未保存';
  } else {
    status.textContent = `已保存 · v${m.saved?.revision || 1}`;
  }
  status.className = `draft-tag wb-state${m.errors.size ? ' wb-error' : ''}`;
  const errors = m.check?.issues?.filter(issue => issue.severity === 'error') || [];
  const count = root.querySelector('[data-dependency-count]');
  if (count) {
    count.textContent = `依赖检查${errors.length ? " · " + errors.length : ''}`;
  }
  root.querySelector('[data-selection-count]')?.replaceChildren(`${m.document.tables.length} / ${m.schema.tables.length}`);
  for (const control of root.querySelectorAll('[data-requires-schema]')) {
    setActionDisabled(control, !m.schema.tables.length);
  }
  const scope = sidebar?.querySelector('.scope-summary');
  if (scope) {
    const refs = referencedTables();
    const execution = executionChecks.get(m);
    const currentExecution = execution?.epoch === m.epoch && execution.lifecycle === m.lifecycleVersion ? execution : null;
    const dependencyActionLabel = () => {
      if (execution) return clearRecoveryState(m, execution).status;
      if (errors.length) {
        return `${errors.length} 条依赖待处理 →`;
      } else if (m.check?.ok) {
        return '追加生成检查通过 →';
      } else if (m.document.tables.length) {
        return '检查依赖与生成顺序 →';
      } else {
        return '尚无生成计划';
      }
    };
    scope.replaceChildren(h('div', {}, `本次生成 ${m.document.tables.length} 张 · 仅引用 ${refs.size} 张`), h('p', {
      class: `dependency-summary${errors.length || currentExecution?.state === 'blocked' ? ' needs-attention' : !execution || ['ok','reviewed'].includes(currentExecution?.state) ? ' dependency-ok' : ''}`,
      role:'status'
    }, dependencyActionLabel().replace(' →','').replace('检查依赖与生成顺序','规则与依赖尚未检查')));
  }
  updateProviderWarning();
  updateGuidance();
  syncBusy();
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
  active++;
  providerMetadata = null;
  root = h('div', {
    class: 'page wb-page'
  }, h('p', {
    class: 'empty wb-empty'
  }, '正在读取数据库结构…'));
  return root;
}
export async function mount() {
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
      root.replaceChildren(h('section', {
        class: 'wb-welcome'
      }, icon('database'), h('h1', {}, '从数据库结构开始'), h('p', {}, '先连接一个数据库，读取表、字段和约束，再配置需要生成的数据。'), h('div', {class:'wb-welcome-actions'}, button('连接数据库', () => openConnectionDialog({workbenchRequest:requestedHash}), {
        primary: true,
        glyph: 'database'
      })), h('div', {
        class: 'wb-welcome-steps'
      }, h('span', {}, '01  选择生成范围'), h('span', {}, '02  调整字段规则'), h('span', {}, '03  检查并生成'))));
      return;
    }
    const connId = store.connId;
    const cached = sessions.get(connId);
    let cachedSchemaNotice = '';
    const schemaRequest = pendingSchemas.get(connId) || (pendingActions.get(cached)?.has('database') ? cached.model.schema : readSchema(connId));
    const [schema, metadata] = await Promise.all([Promise.resolve(schemaRequest).catch(error => {
      if (!cached || error.status !== 409 || error.detail?.code !== 'connection_busy') {
        throw error;
      }
      cachedSchemaNotice = '当前连接有任务正在运行，暂时显示上次读取的缓存结构。可以查看和编辑配置，任务完成后请重新读取结构。';
      return cached.model.schema;
    }), get('/api/workbench/generators')]);
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
    loadProviderStatus();
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
      const mismatched = error.code === 'workbench_target_mismatch';
      const actions = mismatched ? [
        button('返回当前数据库', () => {location.hash = '#/workbench';}, {primary:true}),
        button('选择对应数据库', () => openConnectionDialog({workbenchRequest:requestedHash}), {glyph:'database'})
      ] : [button('重试', mount, {primary:true}), button('选择数据库', () => openConnectionDialog({}), {glyph:'database'})];
      root.replaceChildren(h('section', {
        class: 'wb-welcome'
      }, h('h2', {}, mismatched ? '配置与当前数据库不匹配' : '无法打开工作台'), h('p', {
        role: 'alert'
      }, error.message), ...(mismatched ? [h('p', {}, '当前数据库连接可用；此链接属于另一数据库。返回可继续当前数据库的配置，未保存的修改仍会保留。')] : []), h('div', {class:'wb-welcome-actions'}, ...actions)));
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
      if (requested.target_key !== schema.target_key) {
        const error = new Error(draftId ? '此配置属于另一数据库，请先连接对应数据库。' : '运行记录属于另一数据库，请先连接对应数据库后再打开快照。');
        error.code = 'workbench_target_mismatch';
        throw error;
      }
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
        throw new Error('运行记录属于另一数据库，请先连接对应数据库后再打开快照。');
      }
      executionChecks.delete(session.model);
      if (query.get('recover') === 'remaining') {
        const recovery = remainingRun(run);
        if (!recovery.ok) {
          throw new Error(recovery.reason);
        }
        session.model.replaceDocument(recovery.document);
        session.model.view.tableDrafts = recovery.tableDrafts;
        session.model.selectTable(recovery.document.tables[0].name);
        session.name = `${run.name || '运行配置'} · 剩余数据`;
      } else {
        session.model.replaceDocument(run.document);
        session.name = `${run.name || '运行配置'} · 副本`;
      }
      session.model.saved = null;
    }
  }
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
  active++;
  closeComponents();
  openedModal?.close();
  openedModal = null;
  // The close callback runs first; leaving ends this temporary adjustment flow.
  if (session) executionChecks.delete(session.model);
}
function draw(options = {}) {
  closeComponents();
  status = h('span', {
    class: 'draft-tag wb-state'
  });
  const checkButton = button('', action(showDependencies), {
    glyph: 'check',
    'data-requires-schema': ''
  });
  checkButton.append(h('span', {
    'data-dependency-count': ''
  }, '依赖检查'));
  sidebar = h('aside', {
    class: 'sidebar wb-sidebar'
  });
  content = h('div', {
    class: 'main wb-content'
  });
  root.replaceChildren(h('section', {
    class: 'heading'
  }, h('div', {
    class: 'title-line'
  }, h('h1', {}, button(session.name, renameConfig, {
    plain: true,
    class: 'title-button wb-config-name',
    'aria-label': '重命名生成配置',
    title: session.name,
    glyph: 'edit'
  })), status), h('div', {
    class: 'heading-actions',
    role: 'group',
    'aria-label': '整份生成配置操作'
  }, button('AI 配置助手', () => openAI(model().document.tables.length ? 'selected' : 'current'), {
    glyph: 'sparkles',
    'data-requires-schema': ''
  }), checkButton, button('查看生成计划', action(summary), {
    'data-plan-entry':'',
    'data-requires-schema': '',
    glyph: 'database',
    primary: true,
    title: '检查配置并查看写入计划，确认后生成数据'
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
    'aria-label': '配置管理'
  }, button('保存配置', action(save), {
    glyph: 'save'
  }), button('打开配置', action(openDrafts), {
    glyph: 'folder'
  }), button('编辑 YAML', action(configDocument, undefined, {
    feedback: 'dialog', restoreFocusTo: () => root.querySelector('.wb-config-document')
  }), {
    glyph: 'code',
    class: 'wb-config-document',
    title: '直接编辑完整生成配置；应用后仍需检查和确认写入'
  })), h('section', {
    class: 'wb-generation-settings',
    'aria-label': '全局生成设置'
  }, h('span', {
    class: 'wb-settings-heading',
    title: '作用于当前配置中的所有表'
  }, icon('settings'), '全局'), button('', action(configSettings), {
    plain: true,
    class: 'wb-setting-tile',
    'aria-label': '设置数据生成引擎'
  }), button('', action(configSettings), {
    plain: true,
    class: 'wb-setting-tile',
    'aria-label': '设置数据语言与地区'
  })), h('div', {
    class: 'wb-settings-note',
    'data-provider-warning': '',
    role: 'status',
    hidden: true
  })), h('section', {
    class: 'wb-next-step',
    'aria-label': '使用引导'
  }), h('section', {
    class: 'workspace wb-workspace',
    'aria-label': '生成配置工作台'
  }, sidebar, content));
  const tiles = root.querySelectorAll('.wb-setting-tile');
  tiles[0].append(h('small', {}, '数据生成引擎'), h('strong', {}, model().document.provider || '自动'), h('span', {}, '修改 ›'));
  tiles[1].append(h('small', {}, '数据语言与地区'), h('strong', {}, model().document.locale || 'en_US'), h('span', {}, '修改 ›'));
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
    host.replaceChildren();
    return;
  }
  const broken = capability?.status === 'import_error';
  const fieldNames = fields.slice(0, 3).map(({
    table,
    column
  }) => `${table.name}.${column.name}`).join('、');
  function fieldOverrideHint() {
    if (fields.length) {
      return [h('p', {}, `字段规则：${fieldNames}${fields.length > 3 ? "等 " + fields.length + " 个字段" : ''}。更换全局引擎会保留字段覆盖。`)];
    } else {
      return [];
    }
  }
  host.replaceChildren(h('p', {
    class: 'wb-error'
  }, `Mimesis ${broken ? '加载异常' : '未安装'}，使用此引擎的字段暂不能预览或生成。`), ...fieldOverrideHint(), button('管理插件', () => {
    if (host.isConnected) {
      location.hash = '#/settings?section=plugins';
    }
  }, {
    small: true
  }), button('更改引擎', () => {
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
function updateGuidance() {
  if (!root?.isConnected) {
    return;
  }
  const host = root?.querySelector('.wb-next-step');
  if (!host || !session) {
    return;
  }
  const m = model(), recommended = nextStep(m, previewResults.get(m));
  const clearContext = executionChecks.get(m);
  if (clearContext) {
    host.hidden = false;
    const globalPlan = root.querySelector('[data-plan-entry]');
    if (globalPlan) globalPlan.hidden = true;
    host.replaceChildren(clearRecoveryCard(m, {
      inspect: action(summary),
      review: action(reviewClearScope, '检查关联重建范围', {feedback:'modal'}),
      append: () => {
        executionChecks.delete(m);
        notify('已改为追加，保留现有数据；尚未写入数据库。');
        updateStatus();
        root.querySelector('[data-guide-action="next"]')?.focus();
      },
      adjust: locateGenerationSelection,
      locate: name => chooseTable(name, 'graph')
    }));
    return;
  }
  const selectedStage = m.view.guideEpoch === m.epoch ? m.view.guideStage : null;
  const stage = selectedStage || recommended.stage;
  let step = recommended;
  if (selectedStage && recommended.stage === 1 && ['select','edit','check'].includes(recommended.action)) {
    step = {...recommended, body: `${selectedStage === 2 ? '预览样例' : selectedStage === 3 ? '确认写入' : '设定规则'}之前，${recommended.body}`};
  } else if (selectedStage === 1) {
    step = {...recommended, title:'调整表与字段规则', body:'在左侧选择生成表，在字段规则中调整取值。修改后可随时切到“预览样例”查看效果。', action:'edit', label:'编辑字段规则'};
  } else if (selectedStage === 2) {
    step = {...recommended, title:recommended.stage === 2 ? recommended.title : '查看当前规则生成的样例', body:'样例不会写入数据库。核对字段内容与业务要求；需要修改时返回“设定规则”。', action:'preview', label:'预览已选范围'};
  } else if (selectedStage === 3) {
    step = {...recommended, title:'核对目标与写入方式', body:'确认生成数量和已有数据处理方式。清空模式会额外检查未选下游表，只有在确认窗口提交后才写入。', action:'generate', label:'查看生成计划'};
  }
  host.hidden = !m.schema.tables.length || Boolean(m.view.imported);
  const globalPlan = root.querySelector('[data-plan-entry]');
  if (globalPlan) globalPlan.hidden = !host.hidden && !guidanceCollapsed;
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
  const toggle = button(guidanceCollapsed ? '展开引导' : '收起引导', () => {
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
    updateGuidance();
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
    ['设定规则', '选择表与字段'], ['预览样例', '只读查看结果'], ['确认写入', '核对生成计划']
  ];
  const body = h('div', {
    id: 'wb-next-step-body',
    class: 'wb-next-step-body',
    hidden: guidanceCollapsed
  }, h('div', {
    class: 'wb-next-step-main'
  }, h('ol', { class: 'wb-guide-stages', 'aria-label': '生成流程' },
    ...stages.map(([label, description], index) => h('li', {}, h('button', {
      type:'button', onclick:() => navigateStage(index + 1),
      'data-guide-action':`stage-${index + 1}`,
      ...(index + 1 === stage ? {'aria-current':'step'} : {}),
      ...(index ? {'data-db-action':''} : {}),
      title:index === 2 ? '核对生成计划；此处不会直接写入' : index === 0 ? '随时返回修改规则' : '查看样例，不写入数据库'
    }, h('span', {'aria-hidden':'true', class:'wb-guide-number'}, String(index + 1)), h('span', {class:'wb-guide-label'}, h('strong', {}, label), h('small', {}, description)))))),
  h('div', {class:'wb-guide-description', 'aria-live':'polite'}, h('h3', {}, step.title), h('p', {}, step.body)), actions));
  host.replaceChildren(h('div', {
    class: 'wb-next-step-heading'
  }, h('span', { class: 'wb-guide-heading' }, h('strong', {}, '生成流程'), step.scope), toggle), body);
  if (focused) {
    host.querySelector(`[data-guide-action="${focused}"]`)?.focus();
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
      Promise.resolve().then(() => {
        if (!suppressReturn && intent === modalIntent) {
          onReturn();
        }
      });
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
      returnToPreview();
    },
    onApply: suggestions => {
      if (!current()) {
        throw new Error('配置已变化，请重新分析。');
      }
      for (const item of suggestions) {
        if (!m.schema.tables.find(t => t.name === item.table)?.columns.some(c => c.name === item.column)) {
          throw new Error('建议字段已失效，请刷新结构。');
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
      notify(`已应用 ${suggestions.length} 条 AI 建议。请预览并检查，确认效果后生成数据。`);
    }
  });
  async function resolveDefaultModes() {
    let cancelled = false;
    const loading = openedModal = modal('AI 配置助手', {
      dismiss: 'footer',
      onClose: () => {
        cancelled = true;
        if (!suppressReturn) {
          returnToPreview();
        }
      }
    });
    loading.body.append(h('p', {
      role: 'status'
    }, '正在解析当前配置的字段生成方式…'));
    loading.actions.append(button('取消', loading.close));
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
        throw new Error('数据库结构已变化，请刷新后重新打开 AI 助手。');
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
            return `AI 扩展${error.detail.availability_status === 'import_error' ? '加载异常' : '未安装'}，规则建议与分析不可用。请前往插件与版本${error.detail.availability_status === 'import_error' ? '查看异常' : '安装扩展'}后返回。`;
          } else {
            return error.message;
          }
        };
        loading.body.replaceChildren(h('p', {
          role: 'alert'
        }, aiUnavailableMessage()));
        if (unavailable) {
          loading.actions.append(button('前往插件设置', () => {
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
    dialog = openedModal = modal('重命名生成配置', { dismiss: 'footer' });
  const input = h('input', {
    'aria-label': '配置名称',
    value: session.name,
    maxlength: 120
  });
  const error = h('p', {
    class: 'wb-error',
    role: 'alert'
  });
  dialog.body.append(h('label', {
    class: 'control'
  }, '配置名称', input), error);
  dialog.actions.append(button('取消', dialog.close), button('确定', () => {
    if (!current()) {
      dialog.close();
      return;
    }
    if (!input.value.trim()) {
      error.textContent = '请填写配置名称';
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
    query: ''
  };
  sidebarViews.set(m, view);
  const previousMenu = sidebar.querySelector('.wb-structure-menu');
  if (previousMenu) {
    view.structureOpen = previousMenu.open;
  }
  const scrollTop = sidebar.querySelector('.wb-table-list')?.scrollTop || 0;
  function tableGenerationLabel(table) {
    if (m.errors.has(`count:${table.name}`)) return '生成数量待修正';
    if (m.selected(table.name)) {
      return `生成 ${m.table(table.name).count} 行`;
    } else if (refs.has(table.name)) {
      return '仅引用已有数据';
    } else {
      return '未加入生成';
    }
  }
  sidebar.replaceChildren(h('div', {
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
    title: '查看整库关系图'
  }), h('div', {
    class: 'source-note'
  }, `${m.schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'} · 已连接`, button('ⓘ', connectionInfo, {
    plain: true,
    class: 'source-info',
    'aria-label': '查看连接信息'
  })), h('details', {
    class: 'wb-structure-menu',
    open: view.structureOpen,
    ontoggle: event => {
      view.structureOpen = event.currentTarget.open;
    }
  }, h('summary', {}, icon('fields'), '数据库结构操作'), h('div', {
    class: 'wb-structure-commands',
    role: 'group',
    'aria-label': '数据库结构操作'
  }, h('small', {}, `${m.schema.tables.length} 张表 · ${m.schema.edges.length} 条外键`), button('重新读取结构', action(refreshSchema), {
    small: true,
    glyph: 'refresh',
    title: '重新读取表、字段和外键；不生成样例或写入数据'
  }), button('导出关系图 JSON', () => download('sqlseed-schema.json', JSON.stringify(structureSnapshot(), null, 2)), {
    small: true,
    glyph: 'download'
  }), button('导入关系图 JSON', action(importStructure), {
    small: true,
    glyph: 'upload'
  }), ...(importedStructures.has(session.connId) ? [button('查看已导入关系图', () => {
    m.view.imported = true;
    drawBody();
  }, {
    small: true,
    glyph: 'schema'
  })] : [])))), h('div', {
    class: 'sidebar-label'
  }, h('span', {}, '数据库表'), h('span', {
    'data-selection-count': ''
  }, `${m.document.tables.length} / ${m.schema.tables.length}`)), h('div', {
    class: 'selection-actions'
  }, button('全选', () => {
    if (!validNavigation()) {
      return;
    }
    m.schema.tables.forEach(t => m.toggleTable(t.name, true));
    drawBody();
  }, {
    small: true,
    disabled: !m.schema.tables.length
  }), button('清空选择', () => {
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
    placeholder: '查找表',
    'aria-label': '查找表',
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
  }, h('input', {
    type: 'checkbox',
    checked: m.selected(table.name),
    'aria-label': `生成 ${table.name}`,
    onchange: e => {
      if (!validNavigation()) {
        e.target.checked = m.selected(table.name);
        return;
      }
      m.toggleTable(table.name, e.target.checked);
      drawBody();
    }
  }), h('button', {
    class: 'table-button wb-table-name',
    title: `${table.name} 的字段规则`,
    onclick: () => chooseTable(table.name)
  }, h('span', {
    class: 'table-name'
  }, table.name), h('span', {
    class: 'count'
  }, tableGenerationLabel(table))), button('', () => chooseTable(table.name, 'graph'), {
    glyph: 'relations',
    plain: true,
    class: `table-graph-shortcut wb-table-graph${m.view.table === table.name && m.view.page === 'graph' ? ' active' : ''}`,
    title: `${table.name} 的完整依赖路径`,
    'aria-label': `${table.name} 的依赖路径`,
    'aria-pressed': String(m.view.table === table.name && m.view.page === 'graph')
  })))), ...(m.document.tables.length > 1 ? [button('预览已选表', action(refreshSamples), {
    glyph: 'fields',
    small: true,
    class: 'wb-batch-preview',
    'data-db-action': '',
    title: `预览已勾选的 ${m.document.tables.length} 张表，不写入数据库`
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
}
function connectionInfo() {
  modalIntent++;
  const dialog = openedModal = modal('当前数据库');
  dialog.body.append(h('dl', {
    class: 'wb-key-values'
  }, h('dt', {}, '连接目标'), h('dd', {
    class: 'mono'
  }, model().schema.target_label), h('dt', {}, '数据库类型'), h('dd', {}, model().schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'), h('dt', {}, '状态'), h('dd', {}, '已连接')));
  dialog.actions.append(button('切换数据库', () => {
    dialog.close();
    document.getElementById('connection-button')?.click();
  }));
}
function viewCurrentData() {
  const current = modalTicket(),
    owner = session,
    m = model(),
    table = m.view.table;
  const viewer = openTableData({
    connId: owner.connId,
    table,
    targetKey: m.schema.target_key,
    targetLabel: m.schema.target_label,
    isCurrent: () => current() && session === owner && model() === m && m.view.table === table
  });
  openedModal = viewer.dialog;
}
function generationCountControl(table) {
  const m = model();
  const countHelp = '填写大于 0 的完整整数；工作台最多精确表示 9,007,199,254,740,991。实际生成规模受磁盘、运行时间、唯一值和外键约束影响。';
  const changeCount = e => {
    const valid = m.setCount(table.name, e.target.value);
    e.target.setAttribute('aria-invalid', valid ? 'false' : 'true');
    e.target.title = valid ? countHelp : `${e.target.value || '空值'}：${m.errors.get(`count:${table.name}`)}`;
    const row = [...sidebar.querySelectorAll('.wb-table-entry')].find(entry=>entry.dataset.table===table.name);
    const label = row?.querySelector('.count');
    if (label && (!valid || m.selected(table.name))) label.textContent = valid ? `生成 ${m.table(table.name).count} 行` : '生成数量待修正';
    else if (label) drawSidebar();
    if (m.view.page === 'preview') {
      tablePreview?.destroy();
      tablePreview = null;
      content.querySelector('.wb-table-preview')?.replaceChildren(h('p', {
        class: 'wb-preview-help'
      }, '生成数量已改变，请点击“预览数据”重新查看。'));
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
    'aria-label': `${table.name} 生成数量`,
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
    button('+', () => stepCount(1), {plain:true, disabled:count.disabled, 'aria-label':`${table.name} 增加 1 行`}),
    button('−', () => stepCount(-1), {plain:true, disabled:count.disabled, 'aria-label':`${table.name} 减少 1 行`})));
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
  content.replaceChildren();
  const imported = importedStructures.get(session.connId);
  if (m.view.imported && imported) {
    drawImportedStructure(imported);
    appendStatus();
    updateStatus();
    return;
  }
  if (!table) {
    content.append(h('section', {
      class: 'empty wb-empty-schema',
      'aria-label': '数据库尚无表'
    }, h('h2', {}, '当前数据库还没有可配置的表'),
    h('p', {}, '请先在数据库工具中创建表，再重新读取结构；也可以选择已有表的其他数据库。'),
    h('div', {class:'wb-welcome-actions'},
      button('重新读取结构', action(refreshSchema), {primary:true, glyph:'refresh'}),
      button('选择其他数据库', () => openConnectionDialog(), {glyph:'database', 'data-db-action':''}))));
    appendStatus();
    updateStatus();
    return;
  }
  const countControl = generationCountControl(table);
  content.append(h('div', {
    class: 'table-heading'
  }, h('div', {
    class: 'table-title'
  }, h('h2', {}, table.name), h('span', {
    class: 'desc'
  }, `${table.columns.length} 个字段 · 已有 ${table.row_count} 行`), button('查看当前数据', viewCurrentData, {
    plain: true,
    small: true,
    class: 'wb-view-current-data',
    'data-db-action': ''
  })), h('div', {
    class: 'table-actions'
  }, ...(!m.selected(table.name) ? [button('加入生成', () => {
    m.toggleTable(table.name, true);
    drawBody();
  }, {
    small: true
  })] : []), h('label', {
    class: 'count-setting'
  }, '生成数量', countControl, h('span', {}, '行')))));
  const pages = [['fields', '字段规则'], ['preview', '预览数据'], ['graph', '关系图']];
  const tabs = h('div', {
    class: 'tabs',
    role: 'tablist',
    'aria-label': '当前表视图'
  });
  for (const [page, label] of pages) {
    tabs.append(button(label, () => {
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
        buttons.forEach((item, i) => item.setAttribute('tabindex', i === next ? '0' : '-1'));
        buttons[next].focus();
      }
    }));
  }
  const viewbar = h('div', {
    class: 'viewbar'
  }, tabs);
  content.append(viewbar);
  const panel = h('section', {
    id: 'wb-table-panel',
    role: 'tabpanel',
    'aria-labelledby': `wb-table-tab-${m.view.page}`
  });
  content.append(panel);
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
  appendStatus();
  updateStatus();
  if (autoPreview && m.view.page === 'preview' && !tablePreview?.cached) {
    return tablePreview?.refresh();
  }
}
function appendStatus() {
  notice = h('span', {
    class: 'wb-notice',
    role: 'status',
    'aria-live': 'polite'
  }, '规则调整后，可在当前表的“预览数据”中检查效果。');
  content.append(h('div', {
    class: 'statusbar'
  }, h('span', {}, h('i', {
    class: 'status-dot'
  }), notice), h('span', {}, '预览不写入数据库')));
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
        return '数据库计算';
      } else if (column.is_autoincrement || column.is_rowid_alias) {
        return '数据库自动分配';
      } else if (column.default != null) {
        return '数据库默认值';
      } else {
        return '使用 NULL（空值）';
      }
    };
    const allocatedColumnDetail = () => {
      if (column.is_autoincrement || column.is_rowid_alias) {
        return '追加数据，由数据库继续分配主键；保留已有 ID';
      } else if (column.is_computed) {
        return '由数据库表达式计算';
      } else if (column.default != null) {
        return `使用数据库默认值：${column.default}`;
      } else {
        return '省略该列，由数据库填入 NULL';
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
      label: `引用 ${fk.ref_table}.${fk.ref_columns.join(', ')}`,
      detail: rule.params?.strategy === 'coverage' ? '优先覆盖父表可用记录' : '从父表的可用记录中取值',
      glyph: 'link'
    };
  }
  if (rule.derive_from) {
    return {
      rule,
      locked,
      label: '根据其他字段推算',
      detail: `${Array.isArray(rule.derive_from) ? rule.derive_from.join(' / ') : rule.derive_from} · ${rule.expression || ''}`,
      glyph: 'derive'
    };
  }
  return generatorDescription();
  function generatorDescription() {
    const params = rule.params || {};
    let detail = Object.entries(params).filter(([key, value]) => !key.startsWith('_') && value != null).map(([key, value]) => `${paramLabel(key)} ${valueText(value)}`).join('，');
    if (params.min_value !== undefined || params.max_value !== undefined) {
      detail = `${params.min_value ?? '不限'}—${params.max_value ?? '不限'}${params.precision != null ? "，保留 " + params.precision + " 位小数" : ''}`;
    }
    if (params.choices) {
      detail = Array.isArray(params.choices) ? params.choices.map(valueText).join(' / ') : valueText(params.choices);
    }
    if (params.start_date || params.end_date) {
      detail = `${params.start_date || '不限'} — ${params.end_date || '不限'}`;
    }
    if (rule.null_ratio) {
      detail += `${detail ? '，' : ''}${Math.round(rule.null_ratio * 100)}% 为空`;
    }
    return {
      rule,
      locked,
      label: genLabel(generator || '自动匹配'),
      detail: detail || '使用生成器默认参数'
    };
  }
}
function sampleNode(value, allocated = false) {
  if (value === undefined) {
    const unavailableSampleLabel = () => {
      if (allocated) {
        if (allocated === true || allocated === '数据库自动分配') {
          return '自动分配';
        } else {
          return allocated;
        }
      } else {
        return '待预览';
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
function drawFields(table, viewbar) {
  const m = model();
  const rows = h('tbody'),
    previewNote = h('div', {
      class: 'wb-preview-notice',
      role: 'status'
    });
  const search = h('input', {
    type: 'search',
    placeholder: '查找字段',
    'aria-label': '查找字段',
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
  viewbar.append(h('label', {
    class: 'search'
  }, icon('search'), search));
  if (!m.selected(table.name)) {
    content.append(h('div', {
      class: 'view-only-note'
    }, '当前表未勾选，可查看和调整草稿；不会纳入本次生成。'));
  }
  content.append(h('div', {
    class: 'sample-guide'
  }, h('span', {}, '字段名查看结构，取值规则调整生成方式')), previewNote, h('div', {
    class: 'wb-rules-scroll',
    tabindex: 0,
    'aria-label': `${table.name} 字段规则，可滚动查看`
  }, h('table', {
    class: 'field-table wb-data'
  }, h('colgroup', {}, h('col', {
    class: 'col-field'
  }), h('col', {
    class: 'col-rule'
  })), h('thead', {}, h('tr', {}, ...['字段', '取值规则'].map(text => h('th', {
    scope: 'col'
  }, text)))), rows)));
  function drawRows() {
    previewNote.replaceChildren(...(m.previewIssues || []).map(issue => h('p', {
      class: issue.severity === 'error' ? 'wb-error' : 'muted'
    }, `${issue.table || ''}${issue.column ? "." + issue.column : ''}：${issue.message}`)));
    rows.replaceChildren(...table.columns.filter(c => c.name.toLowerCase().includes(fieldQuery.toLowerCase())).map(column => {
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
      }, `${column.type}${column.is_primary_key ? ' · 主键' : ''}${info.fk ? ' · 外键' : ''}${column.nullable ? ' · 可空' : ' · 不可空'}`)), h('td', {}, ruleButton));
    }));
    if (!rows.children.length) {
      rows.append(h('tr', {}, h('td', {
        colspan: 2,
        class: 'empty'
      }, '没有匹配的字段')));
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
  const dialog = openedModal = modal(batchPreview ? `预览中的字段 · ${column.name}` : column.name, {
    dismiss: 'footer',
    drawer: !batchPreview,
    wide: batchPreview,
    onClose: () => {
      component?.destroy();
      if (onReturn) {
        Promise.resolve().then(() => {
          if (intent === modalIntent) {
            onReturn();
          }
        });
      }
    }
  });
  if (batchPreview) dialog.el.classList.add('wb-preview-rule');
  const apply = button(batchPreview ? '应用并返回预览' : '应用规则', () => {
    if (error) {
      return;
    }
    if (version !== active || m !== model() || epoch !== m.epoch) {
      dialog.close();
      notify('配置已变化，请重新打开字段规则。', true);
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
    notify(changed ? `${table.name}.${column.name} 的规则已应用，请在“预览数据”中检查效果。` : '规则未变更。');
  }, {
    primary: true
  });
  dialog.body.append(h('div', {
    class: 'drawer-subtitle'
  }, `${table.name}.${column.name} · ${column.type}`));
  if (batchPreview) dialog.body.append(h('p', {class:'wb-muted'}, '在预览中调整此字段；返回时保留表、列和滚动位置。应用后样例会标记为待更新，再预览即可核对效果。'));
  const tabs = h('div', {
    class: 'wb-field-tabs',
    role: 'tablist',
    'aria-label': '字段详情'
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
  const names = [['information', '字段信息'], ['rule', '取值规则']];
  let currentTab = initialTab;
  function activate(name, focus = false) {
    currentTab = name;
    information.hidden = name !== 'information';
    rules.hidden = name !== 'rule';
    [...tabs.children].forEach(tab => {
      const selected = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(selected));
      tab.setAttribute('tabindex', selected ? '0' : '-1');
      if (selected && focus) {
        tab.focus();
      }
    });
    dialog.actions.replaceChildren(button(batchPreview ? '返回预览' : '取消', dialog.close), name === 'information' ? button('编辑取值规则', () => activate('rule', true), {
      primary: true
    }) : apply);
    if (name === 'rule' && !component) {
      mountEditor();
    }
  }
  for (const [name, label] of names) {
    tabs.append(button(label, () => activate(name), {
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
    information.append(h('p', {
      class: 'wb-ai-protected'
    }, eligibility.reason));
  }
  const canAI = eligibility.eligible || needsAIDefaultPreflight(m) && eligibility.code === 'database_default';
  const aiHint = h('p', {
    class: 'muted',
    role: 'status',
    'data-rule-ai-hint': ''
  });
  const ai = button('用 AI 调整', () => {
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
      aiHint.textContent = '请先应用或取消当前修改，再使用 AI 调整此字段。';
    } else if (canAI) {
      aiHint.textContent = '针对当前字段提出规则建议，审阅后再应用。';
    } else {
      aiHint.textContent = eligibility.reason;
    }
  }
  rules.append(h('div', {
    class: 'wb-field-rule-ai'
  }, ai, aiHint));
  updateAI();
  dialog.body.append(tabs, information, rules);
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
    rules.append(component.el);
  }
  activate(initialTab);
  function renderColumnInformation() {
    for (const [label, value] of [['字段', column.name], ['数据类型', column.type], ['允许空值', column.nullable ? '是' : '否'], ['主键', column.is_primary_key ? '是' : '否'], ['数据库默认值', column.default ?? '未设置'], ['自动分配', column.is_autoincrement || column.is_rowid_alias ? '由数据库分配' : '否']]) {
      metadata.append(h('dt', {}, label), h('dd', {}, String(value)));
    }
    information.append(h('p', {
      class: 'muted'
    }, '读取自数据库的结构信息。生成规则不会修改表结构。'), metadata);
    if (info.fk) {
      information.append(h('h3', {}, '外键来源'), h('p', {
        class: 'mono'
      }, `${info.fk.ref_table}.${info.fk.ref_columns.join(', ')}`), h('p', {}, info.detail));
    }
    for (const constraint of table.unique_constraints || []) {
      if (constraint.columns.includes(column.name)) {
        information.append(h('h3', {}, constraint.columns.length === 1 ? '唯一约束' : '复合唯一约束'), h('p', {
          class: 'mono'
        }, constraint.columns.join(' + ')));
      }
    }
    if (table.checks?.length) {
      information.append(h('details', {
        class: 'wb-field-constraints'
      }, h('summary', {}, '所属表的 CHECK 约束'), h('p', {
        class: 'muted'
      }, '这些约束作用于整张表，可能涉及其他字段。'), ...table.checks.map(check => h('p', {
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
        notify('外部引用来源，仅展示结构。');
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
      graphViews.set(m, view);
      m.view.graphMode = view.mode;
      m.view.pathMode = view.pathMode;
    },
    onExpand: expanded => area.classList.toggle('expanded', expanded)
  });
  const section = h('section', {
    class: 'panel-content database-graph wb-graph-section'
  });
  if (graph.toolbar) {
    section.append(graph.toolbar);
  }
  area.classList.toggle('expanded', graph.getView().expanded);
  area.append(graph.el, panel);
  section.append(area);
  if (previousSection?.isConnected) previousSection.replaceWith(section);
  else content.append(section);
  function inspect() {
    panel.replaceChildren(h('div', {
      class: 'inspector-tabs'
    }, button('字段规则', () => {
      inspectorMode = 'fields';
      selectedEdge = null;
      inspect();
    }, {
      plain: true,
      class: inspectorMode === 'fields' ? 'active' : ''
    }), button('依赖检查', () => {
      inspectorMode = 'dependencies';
      selectedEdge = null;
      inspect();
    }, {
      plain: true,
      class: inspectorMode === 'dependencies' ? 'active' : ''
    })), h('div', {
      class: 'inspector-actions'
    }, h('div', {
      class: 'inspector-table-title'
    }, h('strong', {
      class: 'mono'
    }, table.name), h('small', {}, `${table.columns.length} 个字段`)), button('查看字段规则', () => chooseTable(table.name), {
      small: true
    })), inspectorBody);
    if (selectedEdge) {
      inspectorBody.replaceChildren(h('h3', {}, '外键引用'), h('div', {
        class: 'wb-edge-mapping'
      }, ...selectedEdge.sourceColumns.map((source, i) => h('div', {}, h('code', {}, `${selectedEdge.source}.${source}`), h('span', {}, '↓'), h('code', {}, `${selectedEdge.target}.${selectedEdge.targetColumns[i]}`)))), h('p', {
        class: 'muted'
      }, '箭头从父表指向引用它的子表。成组字段共同构成同一条外键。'), button('定位引用字段', () => {
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
      }, table.name);
    } else {
      inspectorBody.replaceChildren(h('p', {
        class: 'muted'
      }, '选择字段调整生成器与参数。'), ...table.columns.map(column => button('', () => openRule(table, column), {
        plain: true,
        class: 'graph-field inspector-field wb-field-card',
        title: `调整 ${table.name}.${column.name}`
      })));
    }
    if (!selectedEdge && inspectorMode === 'fields') {
      [...inspectorBody.querySelectorAll('.wb-field-card')].forEach((card, i) => {
        const column = table.columns[i],
          info = ruleDescription(table, column);
        function columnSourceLabel() {
          if (info.allocated) {
            return '数据库处理';
          } else if (info.fk) {
            return '引用';
          } else if (info.rule.derive_from) {
            return '派生';
          } else {
            return '生成器';
          }
        }
        card.append(h('div', {
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
  header.querySelector('h2').textContent = table.name;
  header.querySelector('.desc').textContent = `${table.columns.length} 个字段 · 已有 ${table.row_count} 行`;
  const countControl = generationCountControl(table);
  header.querySelector('.table-actions').replaceChildren(...(!model().selected(table.name) ? [button('加入生成', () => {
    model().toggleTable(table.name, true);
    drawBody();
  }, {
    small: true
  })] : []), h('label', {
    class: 'count-setting'
  }, '生成数量', countControl, h('span', {}, '行')));
  const tabButtons = content.querySelector('.tabs').querySelectorAll('button');
  tabButtons[0].onclick = () => chooseTable(table.name);
}
function renderDependencies(out, locate = name => {
  inspectorMode = 'dependencies';
  chooseTable(name, 'graph');
}, focus = null, onUpdate = null) {
  const m = model(),
    result = m.check;
  const edges = [...m.schema.edges];
  for (const association of m.document.associations || []) {
    for (const target of association.target_tables || []) {
      edges.push({
        source: association.source_table,
        target,
        sourceColumns: [association.source_column || association.column_name],
        targetColumns: [association.column_name]
      });
    }
  }
  const related = relatedTables();
  const executable = executableTables();
  const upstreamEdges = edges.filter(edge => related.has(edge.target) && related.has(edge.source));
  const issueTables = issue => [...new Set([issue.table, ...(Array.isArray(issue.tables) ? issue.tables : [])]
    .filter(name => typeof name === 'string' && name))];
  const relevantIssues = (result?.issues || []).filter(issue => !focus || !issueTables(issue).length || issueTables(issue).some(name => executable.has(name)));
  const sourceCards = upstreamEdges.map(edge => {
    const parent = m.schema.tables.find(t => t.name === edge.source);
    const evidence = result?.sources?.find(source => source.table === edge.target && source.source_table === edge.source && source.column === (edge.targetColumns || []).join(','));
    const selected = m.selected(edge.source),
      rows = evidence?.row_count ?? parent?.row_count;
    let explanation;
    if (focus && !executable.has(edge.target)) {
      explanation = '结构上的间接上游；本次引用中间表已有数据，此关系不要求先生成该来源。';
    } else if (selected) {
      explanation = evidence?.has_values === false ? '先生成父表，再从生成后的有效主键取值。' : '父表也在本次生成范围，按依赖顺序先生成。';
    } else if (evidence?.has_values) {
      explanation = `已有 ${rows} 行 · 仅引用，不新增。已检查存在可用引用值，因此无需勾选父表。`;
    } else if (evidence?.has_values === false) {
      explanation = evidence.nullable ? '无可用引用值；此外键允许 NULL。' : '无可用引用值；请将父表加入生成范围。';
    } else {
      explanation = `${rows == null ? '行数未知' : "已有 " + rows + " 行"} · ${selected ? '本次生成' : '仅引用'}；是否有可用引用值以检查结果为准。`;
    }
    return h('article', {
      class: 'wb-source-card'
    }, h('strong', {
      class: 'mono'
    }, `${edge.source}.${(edge.sourceColumns || []).join(' + ')} → ${edge.target}.${(edge.targetColumns || []).join(' + ')}`), h('p', {}, explanation), button(`查看 ${edge.source}`, () => locate(edge.source), {
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
      }, focus ? '当前表没有上游外键或关联依赖。' : '所选表没有外部引用依赖。')];
    }
  }
  const sources = h('details', {
    class: 'wb-dependency-sources',
    open: previousSources ? previousSources.open : Boolean(focus)
  }, h('summary', {}, focus ? `${focus} · 全部上游来源（${sourceCards.length}）` : `引用来源明细（${sourceCards.length}）`), h('p', {
    class: 'muted'
  }, focus ? '此处展示本表依赖的完整上游链。图中的下游表示受本表影响的表，不是本表的生成前置条件。' : '查看来源字段映射、已有数据与生成范围之间的关系。'), ...dependencySourceCards());
  out.replaceChildren(h('h3', {}, focus ? `${focus} · 依赖检查` : '检查所选表的规则与依赖'));
  if (focus && !m.selected(focus)) {
    out.append(h('p', {
      class: 'muted'
    }, '当前表未纳入本次检查范围。这里仅解释结构；加入生成后再检查规则与引用来源。'), sources);
    return;
  }
  if (!result) {
    out.append(h('p', {
      class: 'muted'
    }, '尚未检查当前配置。'), button('开始检查', action(async () => {
      if (await check(false)) {
        drawBody();
      }
    }, '检查依赖'), {
      glyph: 'check'
    }), sources);
    syncBusy();
    return;
  }
  const blockers = relevantIssues.filter(issue => issue.severity === 'error'),
    reminders = relevantIssues.filter(issue => issue.severity !== 'error');
  function dependencySummary() {
    if (blockers.length) {
      return '当前范围有待处理的问题。';
    } else if (result.ok) {
      return '引用来源与规则检查通过。';
    } else {
      return '整个计划仍有待处理项，请查看完整检查。';
    }
  }
  out.append(h('section', {
    class: `wb-dependency-summary ${blockers.length || !result.ok ? 'wb-dependency-blocked' : 'wb-dependency-passed'}`,
    role: 'status'
  }, h('strong', {}, dependencySummary()), h('p', {}, `${blockers.length} 项阻断 · ${reminders.length} 项提醒`)));
  const issueCard = issue => h('article', {
    class: `dependency-card ${issue.severity}`
  }, h('strong', {}, issueTables(issue).join('、') || '生成配置'), h('p', {}, issue.message), ...(issue.code === 'missing_parent_source' && issue.source_table && m.schema.tables.some(t => t.name === issue.source_table) && !m.selected(issue.source_table) ? [button(`加入 ${issue.source_table}（${m.table(issue.source_table).count} 行）`, action(async () => {
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
  }, '检查依赖'), {
    small: true
  })] : []), ...issueTables(issue).filter(name => m.schema.tables.some(table => table.name === name)).map(name => button(`定位 ${name === issue.table && issue.column || name}`, () => {
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
    out.append(h('section', {
      class: 'wb-dependency-issues',
      'aria-label': '需先处理的问题'
    }, h('h4', {}, '需先处理的问题'), ...blockers.map(issueCard)));
  }
  if (reminders.length) {
    out.append(h('section', {
      class: 'wb-dependency-issues',
      'aria-label': '提醒与说明'
    }, h('h4', {}, '提醒与说明'), ...reminders.map(issueCard)));
  }
  out.append(sources);
  const layers = (result.layers || []).map(names => names.filter(name => !focus || executable.has(name))).filter(names => names.length);
  function dependencyOrderTitle() {
    if (!result.ok) {
      return '依赖分组参考';
    } else if (focus) {
      return '本表相关生成顺序';
    } else {
      return '所选表生成顺序';
    }
  }
  function dependencyOrderHint() {
    if (!result.ok) {
      return '尚未形成可执行计划；以下分组可能不包含循环依赖中的表。请先处理阻断项，再重新检查。';
    } else if (focus) {
      return '仅列本表及上游中已勾选的表；其他表在整个计划中查看。未勾选的来源使用已有数据。';
    } else {
      return '同组表示没有先后依赖；执行仍逐表进行。';
    }
  }
  out.append(h('div', {
    class: 'execution-heading'
  }, h('h3', {}, dependencyOrderTitle()), button('整个计划 ↗', action(showPlan), {
    plain: true,
    class: 'text-button'
  })), h('ol', {
    class: 'execution-sequence'
  }, ...layers.map((names, i) => h('li', {}, h('span', {
    class: 'execution-step'
  }, i + 1), h('div', {
    class: 'execution-group'
  }, h('small', {}, `第 ${i + 1} 组 · ${names.length} 张表`), h('div', {
    class: 'execution-tables'
  }, ...names.map(name => button(name, () => locate(name), {
    plain: true,
    class: 'mono execution-table'
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
    const dialog = openedModal = modal('尚未选择生成表');
    dialog.body.append(h('p', {}, '请在左侧勾选至少一张要生成数据的表，再检查规则与依赖。'));
    dialog.actions.append(button('选择生成表', () => {
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
  const dialog = openedModal = modal('整个计划 · 依赖检查', {
    wide: true
  });
  const generate = button('查看生成计划', () => {
    if (!model().check?.ok) {
      return;
    }
    dialog.close();
    action(summary)();
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
  dialog.actions.append(generate);
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
    'aria-label': `${table.name} 预览数据`
  });
  content.append(container);
  const cached = previewResults.get(m)?.get(table.name);
  const returned = previewReturns.get(m);
  previewReturns.delete(m);
  const resume = returned?.table === table.name ? returned.view : null;
  const initialResult = resume?.result || (cached?.epoch === m.epoch && cached.count === (m.view.previewCount ?? 10) ? cached.result : null);
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
    isCurrent: () => current() && m.view.page === 'preview' && m.view.table === table.name,
    guard: task => action(task, '预览当前表'),
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
function cachePreview(m, names, count, result) {
  const cache = previewResults.get(m) || new Map();
  previewResults.set(m, cache);
  for (const name of names) {
    cache.set(name, {
      epoch: m.epoch,
      count,
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
  const preview = openDataPreview({
    tables: previewTables(m),
    relationships: {edges:m.schema.edges, nodes:m.schema.nodes},
    currentTable: table,
    selectedTables: m.document.tables.map(item => item.name),
    initialScope: 'selected',
    fixedScope: true,
    initialCount: m.view.previewCount ?? 10,
    isCurrent: current,
    initialResult: resume?.result,
    initialView: resume,
    initialStale: Boolean(resume?.stale),
    onColumnAction: (action, context) => editPreviewColumn(owner, m, 'selected', action, context),
    onValidationIssue: issue => {if (owner === session && m === model()) locateInputIssue(issue);},
    guard: task => action(task, '预览已选表'),
    generate: async ({
      count
    }) => {
      const result = await owner.check(true, count);
      if (result && owner.model === m && m.epoch === epoch && m.lifecycleVersion === lifecycle) {
        cachePreview(m, names, count, result);
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
        cachePreview(m, m.document.tables.map(item => item.name), count, result);
        drawBody();
        notify(previewMessage(result, '已选表'), !result.ok);
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
  await preview.refresh();
}
function previewMessage(result, scope) {
  if (!result.ok) {
    return '样例有待处理项，请查看字段说明或依赖检查。';
  }
  if (result.preview_complete === false) {
    return '仅更新可预览的部分样例；完整关联样例需等待父表有可用记录。';
  }
  return `${scope}样例已更新，数据库未写入。`;
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
  const dialog = openedModal = modal('全局生成设置', {
    dismiss: 'footer',
    onClose: () => controls.forEach(c => c.destroy())
  });
  const guide = h('section', {
    class: 'wb-provider-guide',
    'aria-live': 'polite',
    'aria-label': '当前引擎特点'
  });
  const apply = button('应用设置', () => {
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
      return '加载异常';
    }
    if (!available.has(value)) {
      return value === 'mimesis' ? '未安装' : '不可用';
    }
    return value === 'base' ? '内置可用' : '已安装';
  }
  function showGuide() {
    const description = providerGuide(draft.provider, draft.locale);
    const installed = available.has(draft.provider);
    function providerRequirementHint() {
      if (installed && draft.provider === 'faker') {
        return ' · 随 sqlseed 安装';
      } else if (installed && draft.provider === 'mimesis') {
        return ' · 可选依赖';
      } else {
        return '';
      }
    }
    const status = availabilityLabel(draft.provider) + providerRequirementHint();
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
        return `${description.title} 已安装但加载异常，暂不能应用。`;
      }
      if (draft.provider === 'mimesis') {
        return '当前环境未安装 Mimesis，暂不能应用。';
      }
      return '当前 Web 服务未提供此引擎，请检查安装环境。';
    }
    function providerManagementHint() {
      if (!installed && draft.provider === 'mimesis') {
        return h('p', {
          class: 'wb-provider-example'
        }, h('a', {
          href: '#/settings?section=plugins',
          onclick: dialog.close
        }, '管理插件'), h('br'), h('small', {}, providers.statuses?.mimesis?.status === 'import_error' ? '请在插件与版本中查看异常信息，处理后返回。' : '在插件与版本中安装后，返回选择此引擎。'));
      } else {
        return null;
      }
    }
    guide.replaceChildren(...[h('h3', {}, description.title, h('small', {}, status)), h('p', {}, description.summary), providerUnavailableHint(), providerManagementHint(), h('p', {
      class: 'wb-provider-limit'
    }, description.limits[0] || ''), h('details', {}, h('summary', {}, '格式示例与详细说明'), h('ul', {}, ...description.features.map(feature => h('li', {}, feature))), h('div', {
      class: 'wb-provider-example'
    }, ...description.examples.map(example => h('p', {}, h('span', {}, `${example.label}：`), h('code', {}, example.value)))), h('small', {
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
    label: '数据生成引擎',
    options: choices.map(value => {
      const description = providerGuide(value, draft.locale);
      return {
        value,
        label: `${description.title} · ${description.choice} · ${availabilityLabel(value)}`
      };
    }),
    value: draft.provider,
    onChange: value => {
      draft.provider = value;
      showGuide();
    }
  });
  const locale = createDropdown({
    label: '数据语言与地区',
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
  dialog.body.append(h('p', {
    class: 'muted'
  }, '应用于当前配置中的所有表；已有表级、字段级覆盖保留，检查时会提示不兼容的引擎设置。'), h('label', {
    class: 'control'
  }, '数据生成引擎', provider.el), guide, h('label', {
    class: 'control'
  }, '数据语言与地区', locale.el), h('p', {
    class: 'wb-settings-note'
  }, '影响生成内容的语言与格式，不改变界面语言。'));
  showGuide();
  dialog.actions.append(button('取消', dialog.close), apply);
}
async function save() {
  const current = ticket();
  if (!session.name.trim()) {
    throw new Error('请填写配置名称');
  }
  const saved = await session.save();
  if (current()) {
    updateStatus();
    notify(`配置已保存 · v${saved.revision}`);
  }
  return saved;
}
async function check(preview = false) {
  const current = ticket();
  notify(preview ? '正在生成样例，不写入数据库…' : '正在检查结构、规则与依赖…');
  const result = await session.check(preview);
  if (!current()) {
    return null;
  }
  if (!result) {
    notify('配置已变化，旧的检查结果已丢弃，请重新检查。');
    return null;
  }
  function validationResultMessage() {
    if (result.ok) {
      if (preview) {
        return '样例已更新；数据库未写入。';
      } else {
        return '追加生成的依赖与规则检查通过。';
      }
    } else {
      return `发现 ${result.issues?.length || 1} 个待处理项，请查看依赖检查。`;
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
  notify(changedSchema ? '数据库结构已变化，请检查保留的规则后重新保存。' : '已重新读取结构与行数。');
}
async function openDrafts() {
  const current = modalTicket();
  const response = await get(`/api/workbench/drafts?conn_id=${encodeURIComponent(session.connId)}`);
  if (!current()) {
    return;
  }
  const drafts = Array.isArray(response) ? response : response.drafts || [];
  const dialog = openedModal = modal('已保存的配置');
  let opening = false;
  dialog.body.append(h('p', {
    class: 'wb-muted'
  }, '仅列出当前数据库的配置。打开前会保存当前未保存的修改。'));
  if (!drafts.length) {
    dialog.body.append(h('p', {}, '尚未保存配置。'));
  }
  for (const draft of drafts) {
    dialog.body.append(button('', action(async () => {
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
  dialog.actions.append(button('配置管理', () => {
    dialog.close();
    location.hash = '#/configs';
  }, {
    glyph: 'settings'
  }));
  [...dialog.body.querySelectorAll('.wb-draft-card')].forEach((card, i) => card.append(h('strong', {}, drafts[i].name), h('small', {}, `v${drafts[i].revision} · ${new Date(drafts[i].updated_at * 1000).toLocaleString('zh-CN', {
    hour12: false
  })}`)));
}
async function configDocument() {
  const stillCurrent = modalTicket(),
    current = session;
  const opener = root.querySelector('.wb-config-document');
  const documentFeedback = {feedback: 'dialog', restoreFocusTo: () => opener};
  let formatControl;
  const dialog = openedModal = modal('编辑 YAML', {
    dismiss: 'footer',
    wide: true,
    onClose: () => formatControl?.destroy()
  });
  const text = h('textarea', {
    class: 'wb-code',
    rows: 20,
    spellcheck: false,
    'aria-label': 'YAML 或 JSON 配置',
    'aria-busy': 'true',
    disabled: true,
    placeholder: '正在读取配置文档…'
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
  dialog.body.append(h('p', {
    class: 'muted'
  }, '默认使用 YAML，也可读取或粘贴 JSON。应用后更新生成配置；写入数据库仍需单独确认。'), text, error);
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
        error.textContent = '配置文件不得超过 2 MiB';
        return;
      }
      const version = textVersion,
        value = await selected.text();
      if (dialog.body.isConnected && version === textVersion) {
        text.value = value;
        textVersion++;
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
      error.textContent = '文本已变化，请重新应用或下载当前内容。';
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
        error.textContent = e.message;
      }
    }
  }
  let format = 'yaml';
  formatControl = createDropdown({
    label: '下载格式',
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
  const readFile = button('读取文件', () => file.click(), {glyph: 'upload', disabled: true});
  const downloadFile = button('下载配置', action(() => downloadCurrent(format), '导出配置', documentFeedback), {
    glyph: 'download', disabled: true
  });
  const toolbar = h('div', {
    class: 'wb-document-toolbar',
    role: 'group',
    'aria-label': '配置文件工具'
  }, file, readFile, h('label', {
    class: 'wb-document-format'
  }, '下载格式', formatControl.el), downloadFile);
  dialog.body.insertBefore(toolbar, text);
  const apply = button('应用配置', action(async () => {
    try {
      const parsed = await parseVisible();
      if (!parsed) {
        return;
      }
      current.model.replaceDocument(parsed.document);
      executionChecks.delete(current.model);
      dialog.close();
      draw();
      notify('配置已应用，请检查并保存。');
    } catch (e) {
      if (dialog.body.isConnected) {
        error.textContent = e.message;
      }
    }
  }, '检查配置文档', documentFeedback), {
    primary: true, disabled: true
  });
  dialog.actions.append(button('取消', dialog.close), apply);
  try {
    const exported = await send('/api/workbench/export', {
      conn_id: current.connId,
      document: current.model.payload(current.name).document
    });
    if (!stillCurrent() || !dialog.body.isConnected) return;
    text.value = exported.yaml;
    text.placeholder = '';
    text.disabled = readFile.disabled = false;
    setActionDisabled(downloadFile, false);
    setActionDisabled(apply, false);
    if (exported.credentials_omitted) {
      dialog.body.append(h('p', {
        class: 'muted'
      }, '导出内容省略连接凭据，单独执行时需补充连接信息。'));
    }
  } catch (e) {
    if (stillCurrent() && dialog.body.isConnected) {
      text.placeholder = '配置文档未能读取，请关闭后重试。';
      error.textContent = e.message;
    }
  } finally {
    text.removeAttribute('aria-busy');
  }
}
async function importStructure() {
  const current = modalTicket();
  const dialog = openedModal = modal('导入关系图 JSON', {
    dismiss: 'footer',
    wide: true
  });
  const example = {
    format: 'sqlseed-schema-graph',
    version: 1,
    title: '数据库关系图',
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
    'aria-label': '关系图 JSON',
    placeholder: '粘贴关系图 JSON，或选择文件'
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
        error.textContent = '关系图文件不得超过 1 MiB';
        return;
      }
      const value = await selected.text();
      if (dialog.body.isConnected) {
        text.value = value;
      }
    }
  });
  dialog.body.append(h('p', {}, '导入后只读浏览表与外键关系，不会创建或修改数据库。生成配置继续绑定当前数据库。'), h('details', {}, h('summary', {}, '格式说明'), h('p', {}, 'nodes 是表列表；edges 中 source 为父表、target 为子表，sourceColumns 和 targetColumns 按位置一一对应。复合外键放在同一条边内。'), h('pre', {
    class: 'wb-import-help'
  }, JSON.stringify(example, null, 2))), text, error);
  dialog.actions.append(file, button('下载格式模板', () => download('sqlseed-schema-template.json', JSON.stringify(example, null, 2))), button('选择 JSON 文件', () => file.click()), button('取消', dialog.close), button('导入关系图', () => {
    try {
      if (!current()) {
        dialog.close();
        return;
      }
      if (new Blob([text.value]).size > 1024 * 1024) {
        throw new Error('关系图文件不得超过 1 MiB');
      }
      const schema = JSON.parse(text.value);
      if (schema.version !== undefined && schema.version !== 1 || schema.format !== undefined && schema.format !== 'sqlseed-schema-graph') {
        throw new Error('不支持此关系图格式或版本，请参考格式模板。');
      }
      if (!Array.isArray(schema.nodes) || !Array.isArray(schema.edges) || !schema.nodes.length || schema.nodes.length > 200 || schema.edges.length > 1000) {
        throw new Error('需要 nodes 和 edges，支持 1—200 张表 / 最多 1000 条关系。');
      }
      const ids = new Set();
      for (const node of schema.nodes) {
        if (typeof node?.id !== 'string' || !node.id.trim() || ids.has(node.id)) {
          throw new Error('每张表需要非空且唯一的 id。');
        }
        ids.add(node.id);
      }
      const edgeIds = new Set();
      schema.edges = schema.edges.map((edge, i) => {
        if (!edge || !ids.has(edge.source) || !ids.has(edge.target)) {
          throw new Error('关系的 source / target 必须对应 nodes 中的表 id。');
        }
        const sourceColumns = edge.sourceColumns ?? [],
          targetColumns = edge.targetColumns ?? [];
        if (!Array.isArray(sourceColumns) || !Array.isArray(targetColumns) || sourceColumns.length !== targetColumns.length || [...sourceColumns, ...targetColumns].some(col => typeof col !== 'string' || !col.trim())) {
          throw new Error('外键列必须是长度相同的字符串数组。');
        }
        const id = edge.id || `relation-${i + 1}`;
        if (typeof id !== 'string' || edgeIds.has(id)) {
          throw new Error('每条关系需要唯一的 id。');
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
        schema.title = typeof schema.label === 'string' ? schema.label : '导入的关系图';
      }
      importedStructures.set(session.connId, schema);
      model().view.imported = true;
      dialog.close();
      drawBody();
    } catch (e) {
      error.textContent = e.message;
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
  section.append(h('div', {
    class: 'wb-imported-note'
  }, h('div', {}, h('h3', {}, schema.title), h('span', {}, '只读关系图 · 与当前生成配置分开浏览')), button('返回当前数据库', () => {
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
      inspect.replaceChildren(h('strong', {}, `${edge.source} → ${edge.target}`), ...edge.sourceColumns.map((column, i) => h('code', {}, `${column} → ${edge.targetColumns[i]}`)));
    }
  });
  if (graph.toolbar) {
    section.append(graph.toolbar);
  }
  section.append(graph.el, inspect);
  content.append(section);
}
function clearRecoveryCard(m, {inspect, review, append, adjust, locate, reset}) {
  const context = executionChecks.get(m), state = clearRecoveryState(m, context);
  const card = h('section', {class:'wb-clear-recovery', 'aria-label':'清空方案处理'});
  card.append(h('p', {class:'wb-clear-recovery-status', role:'status'}, state.status));
  const needsScope = state.current && state.state === 'blocked' && state.externalTables.length > 0;
  if (state.state === 'blocked') {
    card.append(h('p', {}, state.externalTables.length
      ? `要清空后重新生成，还需将 ${state.externalTables.length} 张关联表纳入重建范围。先核对完整范围，再继续清空计划。`
      : '要继续清空重建，请先处理下列问题。'));
  } else if (state.state === 'pending') {
    card.append(h('p', {}, '重建范围已调整，请重新检查清空计划。'));
  }
  const actions = h('div', {class:'wb-clear-recovery-actions'});
  if (needsScope && review) actions.append(button('补齐关联表，继续重建', review, {primary:true, small:true}));
  else if (inspect) actions.append(button(['ok','reviewed'].includes(state.state) ? '查看生成计划' : '重新检查清空计划', inspect, {primary:true, small:true, disabled:state.state==='checking'}));
  card.append(actions);
  if (state.externalTables.length) {
    card.append(h('p', {class:'wb-muted'}, state.current ? '需一并重建的关联表（点击可定位）：' : '上次检查涉及的关联表：'),
      h('ul', {class:'wb-clear-recovery-tables'}, ...state.externalTables.map(name => h('li', {}, button(name, () => locate(name), {plain:true, small:true})))));
  }
  if (state.current) {
    for (const issue of state.otherIssues) {
      card.append(h('p', {}, issue.message));
      if (issue.table) card.append(button(`查看 ${issue.table}`, () => locate(issue.table), {plain:true, small:true}));
      if (issue.code === 'identity_reset_not_supported' && reset) card.append(button('取消重置并重新检查', reset, {small:true}));
    }
    if (context.error) card.append(h('p', {}, `${context.error} 请重新检查；尚未写入数据库。`));
  }
  if (!['ok','reviewed','checking'].includes(state.state)) {
    card.append(h('details', {}, h('summary', {}, '其他处理方式'),
      h('div', {class:'wb-clear-recovery-actions'}, button('手动调整重建范围', adjust, {small:true}), button('改为追加，保留现有数据', append, {small:true}))));
  }
  return card;
}
async function reviewClearScope() {
  const current = ticket(), m = model(), owner = session;
  const candidate = clearScopeCandidate(m);
  const dialog = openedModal = modal('补齐清空重建范围', {dismiss:'footer', wide:true});
  const valid = () => current() && dialog.body.isConnected && executionChecks.has(m);
  const feedback = h('div', {role:'status', 'aria-live':'polite'});
  const adjust = () => {dialog.close();locateGenerationSelection();};
  let candidateReady = false;
  const apply = button('确认范围，查看清空计划', action(async () => {
    if (!valid() || !candidateReady) return;
    for (const table of candidate.added) m.toggleTable(table.name, true);
    executionChecks.set(m, {epoch:m.epoch, lifecycle:m.lifecycleVersion, state:'pending'});
    dialog.close();draw();
    await summary();
  }, '准备清空计划', {feedback:'modal'}), {primary:true, disabled:true});
  dialog.body.append(h('section', {class:'wb-clear-recovery'},
    h('h3', {}, `${candidate.original.length} 张 → ${candidate.total} 张：新增 ${candidate.added.length} 张表`),
    h('p', {}, '以下关联表需要一并清空，再按各自规则重新生成。已自动查找所有受影响的下游表。'),
    h('p', {}, '确认范围后会保存配置并打开清空计划；只有在下一步确认“清空并生成”后才会写入数据库。'), feedback));
  dialog.body.append(h('table', {class:'wb-clear-scope-review'},
    h('thead', {}, h('tr', {}, ...['新增表','现有行数（上次读取）','将生成行数'].map(label=>h('th', {}, label)))),
    h('tbody', {}, ...candidate.added.map(table=>h('tr', {}, h('td', {}, table.name), h('td', {}, Number.isFinite(table.rowCount) ? table.rowCount.toLocaleString() : '未知'), h('td', {}, table.count.toLocaleString()))))));
  dialog.body.append(h('details', {}, h('summary', {}, `原选 ${candidate.original.length} 张表`), h('p', {}, candidate.original.join('、'))),
    h('p', {class:'wb-muted'}, '现有行数仅供审阅参考，最终清空数量以重新获取的生成计划为准。规则检查通过仍不代表清空一定可行，触发器、自引用等还需清空预检。'));
  dialog.actions.append(button('取消', dialog.close), apply);
  if (!candidate.added.length || candidate.unresolved.length) {
    feedback.append(h('p', {}, candidate.unresolved.length ? `无法定位关联表 ${candidate.unresolved.join('、')}，请重新读取数据库结构后核对。` : '没有可自动补入的关联表，请调整重建范围。'), button('调整重建范围', adjust, {small:true}));
    return;
  }
  feedback.textContent = '正在检查候选范围的规则与依赖，不修改当前配置…';
  try {
    const result = await send('/api/workbench/check', {conn_id:owner.connId, document:candidate.document, schema_hash:m.schema.schema_hash, count:3});
    if (!valid()) return;
    const errors = (result.issues || []).filter(issue=>issue.severity==='error');
    const passed = result.ok && !errors.length;
    feedback.replaceChildren(h('p', {}, passed ? '规则检查通过。核对下方新增表后，可直接继续清空计划。' : '这个范围仍有生成规则问题，暂时不能继续清空重建。请先调整下列冲突表。'),
      ...errors.map(issue=>h('p', {}, `${issue.tables?.length ? issue.tables.join('、') + '：' : issue.table ? issue.table + '：' : ''}${issue.message}`)));
    if (!passed) {
      const tables = [...new Set(errors.flatMap(issue=>issue.tables || (issue.table ? [issue.table] : [])))].filter(name=>m.schema.tables.some(table=>table.name===name));
      feedback.append(h('div', {class:'wb-clear-recovery-actions'}, ...tables.map(name=>button(`定位 ${name}`, ()=>{dialog.close();inspectorMode='dependencies';chooseTable(name,'graph');}, {small:true})), button('调整重建范围', adjust, {small:true})));
    }
    candidateReady = passed;
    setActionDisabled(apply, !passed);
  } catch (error) {
    if (valid()) feedback.textContent = `候选范围检查未完成：${error.message}。当前配置未改变，请稍后重新检查。`;
  }
}
async function summary() {
  const stillCurrent = modalTicket();
  if (!model().document.tables.length) {
    throw new Error('请先勾选要生成的表');
  }
  if (model().dirty) {
    await save();
  }
  if (!stillCurrent()) {
    return;
  }
  const result = await check(false);
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
    execution = {
      // Only the current model's adjustment flow remembers clear intent. No
      // plan/hash/reset option survives closing this confirmation dialog.
      mode: executionChecks.has(m) && m.schema.dialect === 'sqlite' ? 'replace_selected' : 'append',
      reset_identity: false
    };
  const dialog = openedModal = modal('确认生成数据', {
    dismiss: 'footer',
    wide: true,
    onClose: () => {
      sequence++;
      plan = null;
      const context = executionChecks.get(m);
      if (execution.mode === 'replace_selected' && context && context.state !== 'blocked') {
        executionChecks.set(m, {...context, state:context.state === 'ok' ? 'reviewed' : context.state === 'reviewed' ? 'reviewed' : 'pending'});
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
    'aria-live': 'polite'
  });
  const reset = h('input', {
    type: 'checkbox',
    checked: false,
    disabled: true,
    'aria-label': '重置自增计数',
    onchange: () => {
      if (planning || busy) {
        return;
      }
      execution.reset_identity = reset.checked;
      return inspectExecution();
    }
  });
  function selectAppend() {
    if (busy) return;
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
    'aria-label': '追加数据',
    onchange: selectAppend
  });
  const replace = h('input', {
    type: 'radio',
    name: 'execution-mode',
    value: 'replace_selected',
    checked: execution.mode === 'replace_selected',
    disabled: m.schema.dialect !== 'sqlite',
    'aria-label': '清空所选表后生成',
    onchange: () => {
      if (planning || busy) {
        return;
      }
      execution.mode = 'replace_selected';
      reset.disabled = false;
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
  dialog.body.append(planInfo, h('section', {
    class: 'wb-write-target',
    'aria-label': '写入目标'
  }, h('div', {}, h('strong', {}, '写入目标'), h('span', {
    class: 'wb-muted'
  }, databaseDialectLabel())), h('p', {
    class: 'mono'
  }, m.schema.target_label), h('small', {
    class: 'wb-muted'
  }, m.schema.dialect === 'sqlite' ? '当前连接的数据库位置；由运行 Web 的设备访问。' : '当前连接的数据库地址；连接凭据已隐藏。')), h('p', {
    class: 'wb-muted'
  }, `${current.name} · v${m.saved.revision}`), h('fieldset', {
    class: 'wb-write-strategy'
  }, h('legend', {}, '已有数据处理'), h('label', {}, append, h('span', {}, h('strong', {}, '追加数据'), h('small', {}, '保留已有记录，由数据库继续分配 ID。'))), h('label', {}, replace, h('span', {}, h('strong', {}, '清空所选表后生成'), h('small', {}, '删除下列所选表的现有记录，再生成新数据。'))), ...(m.schema.dialect !== 'sqlite' ? [h('p', {
    class: 'muted'
  }, 'PostgreSQL 暂未开放清空模式；当前仅支持追加数据。')] : []), h('label', {
    class: 'wb-reset-identity'
  }, reset, h('span', {}, '重置自增计数', h('small', {}, '仅清空后可选。SQLite AUTOINCREMENT 从 1 重新分配；普通整数主键在空表中通常也从 1 开始。')))), h('div', {
    class: 'wb-summary-total'
  }, h('strong', {}, m.document.tables.reduce((sum, t) => sum + BigInt(t.count), 0n).toLocaleString()), ' 行本次生成 / ', m.document.tables.length, ' 张表'), h('ol', {
    class: 'wb-summary-plan'
  }, ...(result.order || []).map(name => h('li', {}, button(name, () => {
    dialog.close();
    inspectorMode = 'dependencies';
    chooseTable(name, 'graph');
  }, {
    plain: true,
    class: 'mono execution-table'
  }), h('span', {}, `${m.table(name).count} 行`)))), ...(result.issues || []).map(issue => h('p', {
    class: issue.severity === 'error' ? 'wb-error' : 'wb-muted'
  }, `${issue.table || ''} ${issue.message}`)));
  const submit = button('写入数据库', async () => {
    if (!isCurrent() || busy || planning || !m.canRun() || execution.mode === 'replace_selected' && !plan?.ok) {
      return;
    }
    busy = true;
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
        planInfo.append(h('p', {
          class: 'wb-error',
          role: 'alert'
        }, error.message));
        busy = false;
        setStrategyBusy(false);
        submit.disabled = execution.mode === 'replace_selected';
        if (execution.mode === 'replace_selected') {
          plan = null;
          executionChecks.set(m, {epoch, lifecycle, state:'pending'}); updateStatus();
          planInfo.append(button('重新核对计划', inspectExecution));
        }
      }
    }
  }, {
    primary: true,
    disabled: !m.canRun()
  });
  dialog.actions.append(button('返回调整', dialog.close), submit);
  function appendPlan() {
    executionChecks.delete(m);
    notify(m.check?.ok ? '追加生成的依赖与规则检查通过。' : '追加生成的依赖与规则尚未通过检查。', !m.check?.ok);
    updateStatus();
    planInfo.replaceChildren(h('p', {
      class: 'wb-muted'
    }, '追加生成的依赖与规则检查已通过。向现有数据追加，不清空表；自动主键由数据库继续分配。按此顺序逐表写入。若中途失败，后续表停止；已经提交的数据保留，实际数量可在运行记录中查看。'));
  }
  function setStrategyBusy(value) {
    append.disabled = busy;
    replace.disabled = value || m.schema.dialect !== 'sqlite';
    reset.disabled = value || execution.mode !== 'replace_selected' || !plan?.reset_identity_supported;
    planInfo.setAttribute('aria-busy', String(value));
  }
  function recoveryActions() {
    return {
      append:selectAppend,
      review: () => {dialog.close();return action(reviewClearScope, '检查关联重建范围', {feedback:'modal'})();},
      adjust: () => {dialog.close();locateGenerationSelection();},
      locate: name => {dialog.close();chooseTable(name,'graph');},
      reset: () => {reset.checked=false;execution.reset_identity=false;return inspectExecution();}
    };
  }
  async function inspectExecution() {
    if (!isCurrent() || busy || planning && execution.mode !== 'append') {
      return;
    }
    const request = ++sequence;
    plan = null;
    submit.disabled = true;
    if (execution.mode === 'append') {
      appendPlan();
      submit.textContent = '写入数据库';
      submit.disabled = planning || !m.canRun();
      setStrategyBusy(planning);
      return;
    }
    submit.textContent = '清空并生成';
    executionChecks.set(m, {...executionChecks.get(m), epoch, lifecycle, state:'checking'}); updateStatus(); reportExecutionCheck(m);
    planInfo.replaceChildren(h('p', {}, '正在核对清空范围、外键与事务能力…'));
    planning = true;
    setStrategyBusy(true);
    try {
      const response = await current.executionPlan({
        ...execution
      });
      if (!isCurrent() || request !== sequence) {
        return;
      }
      plan = response;
      executionChecks.set(m, {epoch, lifecycle, issues:structuredClone(plan.issues || []), state:plan.ok && plan.atomic ? 'ok' : 'blocked'}); updateStatus();
      const tables = plan.clear_tables || [];
      planInfo.replaceChildren(clearRecoveryCard(m, recoveryActions()), h('details', {}, h('summary', {}, `${plan.ok && plan.atomic ? '将清空' : '拟清空'} ${tables.length} 张表 · ${tables.reduce((sum, t) => sum + t.row_count, 0).toLocaleString()} 行现有记录`),
        h('ul', {}, ...tables.map(table => h('li', {}, `${table.name}：${table.row_count} 行`))),
        h('p', {}, plan.atomic ? '清空与本次生成在同一事务中完成。失败将回滚本次操作，保留原有数据。' : '此模式不具备整体回滚能力。'),
        ...(plan.issues || []).filter(issue=>issue.severity!=='error').map(issue=>h('p',{class:'wb-muted'},issue.message))));
      submit.disabled = !plan.ok || !plan.atomic || !m.canRun();
      reset.disabled = !plan.reset_identity_supported;
    } catch (error) {
      if (isCurrent() && request === sequence) {
        executionChecks.set(m, {epoch, lifecycle, error:error.message, state:'blocked'}); updateStatus();
        planInfo.replaceChildren(clearRecoveryCard(m, {...recoveryActions(), inspect:inspectExecution}));
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
