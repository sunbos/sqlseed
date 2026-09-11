const assert = require('node:assert/strict');
const vm = require('node:vm');
const {Element, createDom, loadFrontend} = require('./frontend_helpers.cjs');

const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
};
const column = (name, type = 'INTEGER', extra = {}) => ({name, type, nullable: true, default: null,
  is_primary_key: false, is_autoincrement: false, is_computed: false, ...extra});
const spec = (generator, params = {}) => ({generator_name: generator, params, null_ratio: 0,
  provider: null, native_faker_method: null, native_mimesis_method: null, native_params: null});
const catalog = {names: ['integer', 'json', 'string'], entries: [
  {id: 'integer', params: [
    {name: 'min_value', type: 'integer', required: false, default: 0},
    {name: 'max_value', type: 'integer', required: false, default: 999999},
  ]},
  {id: 'json', params: [{name: 'schema', type: 'object', required: false, default: null}]},
  {id: 'string', params: [{name: 'max_length', type: 'integer', required: false, default: 100}]},
]};

function schema(target = 'A') {
  const users = {
    name: 'users', row_count: 0,
    columns: [column('id', 'INTEGER', {is_primary_key: true, is_autoincrement: true, nullable: false}),
      column('amount'), column('metadata', 'JSON')],
    primary_key: ['id'], unique_constraints: [], checks: [], foreign_keys: [],
    mapping: {id: spec('skip'), amount: spec('integer', {min_value: 1, max_value: 9}), metadata: spec('json', {schema: {type: 'object'}})},
  };
  const orders = {
    name: 'orders', row_count: 0, columns: [column('user_id', 'INTEGER', {nullable: false})],
    primary_key: [], unique_constraints: [], checks: [],
    foreign_keys: [{id: 'orders-user', columns: ['user_id'], ref_table: 'users', ref_schema: null, ref_columns: ['id'], nullable: false}],
    mapping: {user_id: spec('foreign_key', {ref_table: 'users', ref_column: 'id', strategy: 'random', _ref_values: []})},
  };
  const audit = {...orders, name: 'audit', columns: [column('event', 'TEXT')], foreign_keys: [], mapping: {event: spec('string')}};
  return {schema_hash: 'schema-v1', target_key: `target-${target}`, target_label: `${target}.db`, dialect: 'sqlite',
    provider: 'base', locale: 'en_US', tables: [users, orders, audit],
    nodes: ['users', 'orders', 'audit'].map(id => ({id})),
    edges: [{id: 'orders-user', source: 'users', target: 'orders', sourceColumns: ['id'], targetColumns: ['user_id'], nullable: false}],
  };
}

function harness({connected = true, timers = {}} = {}) {
  const document = createDom();
  const create = tag => {
    const node = new Element(tag);
    node.clientWidth = 800; node.clientHeight = 420;
    node.scrollLeft = 0; node.scrollTop = 0;
    node.setPointerCapture = () => {};
    node.scrollIntoView = () => {};
    node.focus = () => {document.activeElement = node;};
    return node;
  };
  document.createElement = create;
  document.createElementNS = (_, tag) => create(tag);
  const store = {connId: connected ? 'A' : null};
  const location = {hash: '#/workbench'};
  const requests = [];
  const routes = new Map();
  const fallback = (url, options) => {
    const match = url.match(/\/connections\/([^/]+)\/schema$/);
    if (match) return schema(match[1]);
    if (url.endsWith('/generators')) return catalog;
    if (url.startsWith('/api/workbench/drafts?')) return {drafts: []};
    if (url === '/api/workbench/export') return {yaml: 'provider: base\nlocale: en_US\ntables: []\n', json: {tables: []}};
    if (url === '/api/workbench/parse') return {document: {provider: 'base', locale: 'en_US', tables: []}};
    if (url === '/api/workbench/drafts' && options.method === 'POST') return {...JSON.parse(options.body), id: 'saved', revision: 1, target_key: 'target-A'};
    if (url === '/api/workbench/check' || url === '/api/workbench/preview') return {ok: true, config_hash: 'config', order: ['users'], layers: [['users']], samples: {users: [{amount: 3}]}, issues: []};
    throw new Error(`Unexpected network request: ${url}`);
  };
  const bindings = {
    document, store, location, URLSearchParams, TextDecoder, AbortController, ...timers,
    ResizeObserver: class {observe() {} disconnect() {}},
    restoreConnection: async () => {},
    fetch: async (url, options = {}) => {
      requests.push({url, options: plain(options)});
      const route = routes.get(url);
      const body = await (route ? route(options) : fallback(url, options));
      if(body instanceof Response)return body;
      return {ok: true, headers: new Headers({'Content-Type':'application/json'}), json: async () => body};
    },
  };
  const load = (name, extra = {}) => loadFrontend(name, {...bindings, ...extra});
  const model = load('workbench/model.js');
  const session = load('workbench/session.js', {WorkbenchDocument: vm.runInContext('WorkbenchDocument', model)});
  const labels = load('labels.js');
  const dropdown = load('dropdown.js');
  const datePicker=load('workbench/date-picker.js');
  const editor = load('workbench/editor.js', {
    createDatePicker:vm.runInContext('createDatePicker',datePicker),
    createDropdown: vm.runInContext('createDropdown', dropdown),
    ...vm.runInContext('({genLabel, paramLabel, genGuide})', labels),
  });
  const layout = load('workbench/graph-layout.js');
  const dependency = load('workbench/dependency-view.js');
  const graph = load('workbench/graph.js', {
    SqlseedGraphLayout: layout.SqlseedGraphLayout,
    SqlseedDependencyView: dependency.SqlseedDependencyView,
  });
  const ui = load('workbench/ui.js');
  const preview=load('workbench/preview.js',{createDropdown:vm.runInContext('createDropdown',dropdown),...vm.runInContext('({button,modal,valueText})',ui)});
  const tableData=load('workbench/table-data.js',{...vm.runInContext('({button,modal,valueText})',ui)});
  const eligibility=load('workbench/ai-eligibility.js'),guide=load('workbench/provider-guide.js');
  const guidance=load('workbench/guidance.js');
  const recovery=load('workbench/recovery.js');
  const fieldAIEligibility=vm.runInContext('fieldAIEligibility',eligibility),providerGuide=vm.runInContext('providerGuide',guide);
  const aiHandoff=load('workbench/ai-handoff.js');
  const handoff=vm.runInContext('({rememberAIHandoff,consumeAIHandoff,clearAIHandoff,peekAIHandoff,requestAIReturn,leaveAISettings})',aiHandoff);
  const aiStream=load('workbench/ai-stream.js');
  const ai = load('workbench/ai.js', {requestAISuggestions:vm.runInContext('requestAISuggestions',aiStream),fieldAIEligibility,createDropdown:vm.runInContext('createDropdown',dropdown),genLabel:vm.runInContext('genLabel',labels),...vm.runInContext('({button,modal})',ui),AbortController});
  const context = load('pages/workbench.js', {
    ...handoff,
    openTableData:vm.runInContext('openTableData',tableData),
    ...vm.runInContext('({nextStep,guideAIState})',guidance),
    ...vm.runInContext('({remainingRun})',recovery),
    fieldAIEligibility,providerGuide,openDataPreview:vm.runInContext('openDataPreview',preview),
    openAIAssistant:vm.runInContext('openAIAssistant',ai),
    WorkbenchSession: vm.runInContext('WorkbenchSession', session),
    createRuleEditor: vm.runInContext('createRuleEditor', editor),
    createSchemaGraph: vm.runInContext('createSchemaGraph', graph),
    ...vm.runInContext('({genLabel, paramLabel, genGuide})', labels),
    createDropdown: vm.runInContext('createDropdown', dropdown),
    ...vm.runInContext('({button, icon, modal, download, valueText})', ui),
  });
  let root;
  const mount = async () => {
    root = context.render();
    document.body.append(root);
    await context.mount();
    return root;
  };
  const leave = () => {context.unmount(); root?.remove();};
  const button = (text, within = root) => within.querySelectorAll('button').find(node =>
    node.textContent === text || node.getAttribute('aria-label') === text);
  const modelState = () => vm.runInContext('session.model', context);
  const field = name => document.querySelector(`[data-field="${name}"]`);
  const edit = async (name, value) => {
    const input = field(name); assert.ok(input, `Missing field ${name}`);
    input.value = String(value); await input.dispatchEvent('input');
    return input;
  };
  const selectColumn = async name => {
    const node = root.querySelectorAll('.wb-field-name').find(node => node.textContent === name);
    assert.ok(node, `Missing column ${name}`); await node.click();
  };
  const openRule = async name => {
    const fieldNode=root.querySelectorAll('.wb-field-name').find(node=>node.textContent===name);
    assert.ok(fieldNode,`Missing column ${name}`);
    await fieldNode.closest('tr').querySelector('.wb-rule-button').click();
    const drawer = document.querySelector('.drawer');
    assert.ok(drawer, `Missing rule drawer for ${name}`);
    assert.equal(drawer.getAttribute('aria-label'), name);
    return drawer;
  };
  const applyRule = async () => {
    const apply = button('应用规则', document);
    assert.ok(apply, 'Missing Apply rule action');
    assert.equal(apply.disabled, false, 'Invalid rule must not be applied');
    await apply.click();
    assert.equal(document.querySelector('.drawer'), null);
  };
  const cancelRule = async () => {
    const cancel = button('取消', document);
    assert.ok(cancel, 'Missing Cancel rule action');
    await cancel.click();
    assert.equal(document.querySelector('.drawer'), null);
  };
  return {document, store, location, requests, routes, context, mount, leave, button, modelState, handoff,
    field, edit, selectColumn, openRule, applyRule, cancelRule, root: () => root};
}


module.exports = {harness, plain, deferred, schema};
