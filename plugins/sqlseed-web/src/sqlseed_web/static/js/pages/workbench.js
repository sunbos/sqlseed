import { h, api, get, store, restoreConnection } from '../api.js';
import { genLabel, paramLabel } from '../labels.js';
import { createDropdown } from '../dropdown.js';
import { WorkbenchSession } from '../workbench/session.js';
import { openAIAssistant } from '../workbench/ai.js';
import { rememberAIHandoff, consumeAIHandoff, clearAIHandoff } from '../workbench/ai-handoff.js';
import { openDataPreview } from '../workbench/preview.js';
import { openTableData } from '../workbench/table-data.js';
import { fieldAIEligibility } from '../workbench/ai-eligibility.js';
import { remainingRun } from '../workbench/recovery.js';
import { providerGuide } from '../workbench/provider-guide.js';
import { nextStep, guideAIState } from '../workbench/guidance.js';
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
const pendingSchemas = new Map(), pendingActions = new WeakMap(), disabledBeforeBusy = new WeakMap();
const databaseActions = new Map([[save,'保存配置'],[showDependencies,'检查依赖'],[showPlan,'检查依赖'],[summary,'准备生成计划'],[refreshSchema,'读取数据库结构'],[configDocument,'读取配置文档']]);
let root, session, catalog, notice, status, sidebar, content, graph, active = 0, openedModal;
let graphOwner=null, modalIntent=0;
let previewCount=10, tablePreview=null;
let guidanceAI=null, guidanceRequest=0, guidanceCollapsed=false;
let providerMetadata=null, providerRequest=0;
try { guidanceCollapsed=localStorage.getItem('sqlseed.workbench.guide.collapsed')==='true'; } catch { /* Storage may be unavailable. */ }
let fieldQuery = '', columnName = '', inspectorMode = 'fields', selectedEdge = null;
const model = () => session.model;
const send = (path, body, method = 'POST') => api(path, {method, body: JSON.stringify(body)});
// Lifecycle events update cached workbenches even while the configuration page is active.
window.addEventListener('sqlseed:draft-deleted', event => {
  for(const savedSession of sessions.values())if(savedSession.model.saved?.id===event.detail.id) {
    savedSession.model.lifecycleVersion++;
    savedSession.model.saved=null;savedSession.model.savedEpoch=-1;
  }
  if(root?.isConnected && session)updateStatus();
});
window.addEventListener('sqlseed:draft-renamed', event => {
  for(const savedSession of sessions.values())if(savedSession.model.saved?.id===event.detail.id) {
    savedSession.model.lifecycleVersion++;
    savedSession.model.saved={...savedSession.model.saved,revision:event.detail.revision,name:event.detail.name};
    savedSession.name=event.detail.name;
  }
  if(root?.isConnected && session)draw();
});
function ticket() {
  const version = active, current = session, document = model(), epoch = document.epoch, lifecycle=document.lifecycleVersion;
  return () => version === active && current === session && document === model() && epoch === document.epoch && lifecycle===document.lifecycleVersion;
}
function notify(text, error = false) {
  if (notice?.isConnected) { notice.textContent = text; notice.className = `wb-notice${error ? ' wb-error' : ''}`; }
  const banner=root?.querySelector('.wb-operation-status');
  if(banner && error){banner.hidden=false;banner.textContent=text;banner.className='wb-operation-status wb-error';}
}
function modalTicket() { const current=ticket(), intent=++modalIntent;return()=>current() && intent===modalIntent; }
function action(fn,label=databaseActions.get(fn)) {
  const listener=async (...args) => {
    const version=active, owner=session;
    if(!owner)return;
    let pending=pendingActions.get(owner);
    if(!pending){pending=new Map();pendingActions.set(owner,pending);}
    const key=label?'database':fn;
    if(pending.has(key))return;
    pending.set(key,label || '处理请求');syncBusy();
    try {return await fn(...args);}
    catch(error){if(version===active)notify(error.message,true);}
    finally {pending.delete(key);if(owner===session)syncBusy();}
  };
  listener.databaseAction=Boolean(label);
  return listener;
}
function syncBusy() {
  if(!root?.isConnected || !session)return;
  const label=pendingActions.get(session)?.get('database');
  const controls=[...root.querySelectorAll('[data-db-action]'),...(openedModal?.el?.querySelectorAll('[data-db-action]') || [])];
  for(const control of controls) {
    if(label){if(!disabledBeforeBusy.has(control))disabledBeforeBusy.set(control,control.disabled);control.disabled=true;control.setAttribute('aria-busy','true');}
    else if(disabledBeforeBusy.has(control)){control.disabled=disabledBeforeBusy.get(control);disabledBeforeBusy.delete(control);control.removeAttribute('aria-busy');}
  }
  const banner=root.querySelector('.wb-operation-status');
  if(banner && label){banner.hidden=false;banner.className='wb-operation-status';banner.textContent=`正在${label}，请稍候。期间可以查看和编辑字段。`;}
  else if(banner && !banner.classList.contains('wb-error'))banner.hidden=true;
}
function readSchema(connId) {
  if(!pendingSchemas.has(connId)) {
    const request=get(`/api/workbench/connections/${encodeURIComponent(connId)}/schema`).finally(()=>pendingSchemas.delete(connId));
    pendingSchemas.set(connId,request);
  }
  return pendingSchemas.get(connId);
}
function closeComponents() { tablePreview?.destroy();tablePreview=null; if (graph?.getView && graphOwner) graphViews.set(graphOwner, graph.getView()); graph?.destroy(); graph = null; graphOwner=null; }
function validNavigation() {
  if (model().errors.size) { notify('请先修正生成数量。', true); return false; }
  return true;
}
function chooseTable(name, page = 'fields') {
  if (!validNavigation()) return;
  if (!model().schema.tables.some(t => t.name === name)) { notify('这是其他 schema 的引用来源，仅展示结构。'); return; }
  closeComponents(); graphViews.delete(model()); model().view.imported=false; model().selectTable(name, page); fieldQuery = ''; columnName = ''; selectedEdge = null; const rendered=drawBody();
  sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({block: 'nearest'});
  return rendered;
}
function locateGenerationSelection() {
  const entry=[...sidebar.querySelectorAll('.wb-table-entry')].find(row=>!row.hidden);
  const input=entry?.querySelector('input[type="checkbox"]') || sidebar.querySelector('input[type="search"]');
  input?.focus();input?.scrollIntoView({block:'nearest'});
}
function updateStatus() {
  if (!status?.isConnected) return;
  const m = model();
  status.textContent = m.errors.size ? '有待修正的输入' : m.dirty ? '未保存' : `已保存 · v${m.saved?.revision || 1}`;
  status.className = `draft-tag wb-state${m.errors.size ? ' wb-error' : ''}`;
  const errors = m.check?.issues?.filter(issue => issue.severity === 'error') || [];
  const count = root.querySelector('[data-dependency-count]');
  if (count) count.textContent = `依赖检查${errors.length ? ` · ${errors.length}` : ''}`;
  root.querySelector('[data-selection-count]')?.replaceChildren(`${m.document.tables.length} / ${m.schema.tables.length}`);
  const scope = sidebar?.querySelector('.scope-summary');
  if (scope) {
    const refs = referencedTables();
    scope.replaceChildren(h('div', {}, `本次生成 ${m.document.tables.length} 张 · 仅引用 ${refs.size} 张`),
      h('button', {class: `dependency-jump${errors.length ? ' needs-attention' : ' dependency-ok'}`, 'data-db-action':'', onclick: action(showDependencies)},
        errors.length ? `${errors.length} 条依赖待处理 →` : m.check?.ok ? '依赖与规则检查通过 →' : m.document.tables.length ? '检查依赖与生成顺序 →' : '尚无生成计划'));
  }
  updateProviderWarning();updateGuidance();syncBusy();
}
function referencedTables() {
  const m = model(), refs = new Set();
  for (const edge of m.schema.edges) if (m.selected(edge.target) && !m.selected(edge.source)) refs.add(edge.source);
  return refs;
}
const databaseLabel = () => model().schema.target_label.split(/[\\/]/).filter(Boolean).at(-1) || model().schema.target_label;
export function render() {
  active++;
  providerMetadata=null;
  root = h('div', {class: 'page wb-page'}, h('p', {class: 'empty wb-empty'}, '正在读取数据库结构…'));
  return root;
}
export async function mount() {
  const version = active;
  try {
    if (!store.connId) await restoreConnection();
    if (version !== active) return;
    if (!store.connId) {
      root.replaceChildren(h('section', {class: 'wb-welcome'}, icon('database'), h('h1', {}, '从数据库结构开始'),
        h('p', {}, '先连接一个数据库，读取表、字段和约束，再配置需要生成的数据。'),
        button('连接数据库', () => document.getElementById('connection-button')?.click(), {primary: true, glyph: 'database'}),
        h('div', {class: 'wb-welcome-steps'}, h('span', {}, '01  选择生成范围'), h('span', {}, '02  调整字段规则'), h('span', {}, '03  检查并生成'))));
      return;
    }
    const connId = store.connId;
    const cached=sessions.get(connId);
    let cachedSchemaNotice='';
    const schemaRequest=pendingSchemas.get(connId) || (pendingActions.get(cached)?.has('database') ? cached.model.schema : readSchema(connId));
    const [schema, metadata] = await Promise.all([Promise.resolve(schemaRequest).catch(error=>{
      if(!cached || error.status!==409 || error.detail?.code!=='connection_busy')throw error;
      cachedSchemaNotice='当前连接有任务正在运行，暂时显示上次读取的缓存结构。可以查看和编辑配置，任务完成后请重新读取结构。';
      return cached.model.schema;
    }), get('/api/workbench/generators')]);
    if (version !== active) return;
    catalog = metadata;
    session = sessions.get(connId);
    if (!session) { session = new WorkbenchSession(connId, schema, send); sessions.set(connId, session); }
    else { if (session.model.schema.schema_hash !== schema.schema_hash) session.model.touch(); session.model.schema = schema; }
    const restoredAI=consumeAIHandoff({model:session.model,connId,returnTo:location.hash});
    const query = new URLSearchParams(restoredAI?'':location.hash.split('?')[1] || '');
    if (query.get('draft') || query.get('run') || query.get('new')) {
      if(session.model.dirty && (session.model.saved || session.model.epoch>0))await session.save();
      if(version!==active)return;
    }
    if(query.get('new')) {session=new WorkbenchSession(connId,schema,send);sessions.set(connId,session);}
    if (query.get('draft')) {
      const draft = await get(`/api/workbench/drafts/${encodeURIComponent(query.get('draft'))}`);
      if (version !== active) return;
      session.open(draft);
    } else if (query.get('run')) {
      const run = await get(`/api/workbench/runs/${encodeURIComponent(query.get('run'))}`);
      if (version !== active) return;
      if (schema.target_key !== run.target_key) throw new Error('运行记录属于另一数据库，请先连接对应数据库后再打开快照。');
      if(query.get('recover')==='remaining') {
        const recovery=remainingRun(run);
        if(!recovery.ok)throw new Error(recovery.reason);
        session.model.replaceDocument(recovery.document);
        session.model.view.tableDrafts=recovery.tableDrafts;
        session.model.selectTable(recovery.document.tables[0].name);
        session.name=`${run.name || '运行配置'} · 剩余数据`;
      } else {session.model.replaceDocument(run.document);session.name=`${run.name || '运行配置'} · 副本`;}
      session.model.saved = null;
    }
    const previewOrigin=restoredAI?.previewOrigin;
    if(previewOrigin?.scope==='current' && session.model.view.page==='preview' && session.model.view.table===previewOrigin.table)
      previewReturns.set(session.model,{table:previewOrigin.table,view:previewOrigin.view});
    draw({autoPreview:!previewOrigin});loadGuidanceAI();loadProviderStatus();
    if(cachedSchemaNotice)notify(cachedSchemaNotice,true);
    if(query.get('import'))await configDocument();
    if(restoredAI && version===active){
      const {previewOrigin,...aiState}=restoredAI;
      await openAI(aiState.scope,aiState,{previewOrigin});
    }
  } catch (error) {
    if (version === active) root.replaceChildren(h('section', {class: 'wb-welcome'}, h('h2', {}, '无法打开工作台'),
      h('p', {role: 'alert'}, error.message), button('重试', mount), button('选择数据库', () => document.getElementById('connection-button')?.click())));
  }
}
export function unmount() { active++; closeComponents(); openedModal?.close(); openedModal = null; }

function draw(options={}) {
  closeComponents();
  status = h('span', {class: 'draft-tag wb-state'});
  const checkButton = button('', action(showDependencies), {glyph: 'check'});
  checkButton.append(h('span', {'data-dependency-count': ''}, '依赖检查'));
  root.replaceChildren(h('section', {class: 'heading'},
    h('div', {class: 'title-line'}, h('h1', {}, button(session.name, renameConfig, {plain: true, class: 'title-button wb-config-name', 'aria-label': '重命名生成配置', title:session.name, glyph: 'edit'})), status),
    h('div', {class: 'heading-actions', role: 'group', 'aria-label': '整份生成配置操作'},
      button('AI 配置助手',openAI,{glyph:'sparkles'}),checkButton,
      button('生成数据', action(summary), {glyph:'database',primary:true,title:'检查配置并查看写入计划，确认后生成数据'}))),
    h('p',{class:'wb-operation-status',role:'status','aria-live':'polite',hidden:true}),
    h('div', {class:'wb-config-context'},
      h('div', {class: 'wb-config-tools', role: 'group', 'aria-label': '配置管理'}, button('保存配置', action(save), {glyph: 'save'}),
        button('打开配置', action(openDrafts)), button('编辑 YAML', action(configDocument), {glyph:'code',plain:true,class:'wb-config-document',title:'直接编辑完整生成配置；应用后仍需检查和确认写入'})),
      h('section', {class:'wb-generation-settings', 'aria-label':'全局生成设置'},
        h('span', {class:'wb-settings-heading',title:'作用于当前配置中的所有表'},icon('settings'),'全局'),
        button('',action(configSettings),{plain:true,class:'wb-setting-tile','aria-label':'设置数据生成引擎'}),
        button('',action(configSettings),{plain:true,class:'wb-setting-tile','aria-label':'设置数据语言与地区'})),
      h('div',{class:'wb-settings-note','data-provider-warning':'',role:'status',hidden:true})),
    h('section',{class:'wb-next-step','aria-label':'使用引导'}),
    h('section', {class: 'workspace wb-workspace', 'aria-label': '生成配置工作台'}, sidebar = h('aside', {class: 'sidebar wb-sidebar'}), content = h('div', {class: 'main wb-content'})));
  const tiles=root.querySelectorAll('.wb-setting-tile');
  tiles[0].append(h('small',{},'数据生成引擎'),h('strong',{},model().document.provider || '自动'),h('span',{},'修改 ›'));
  tiles[1].append(h('small',{},'数据语言与地区'),h('strong',{},model().document.locale || 'en_US'),h('span',{},'修改 ›'));
  drawBody(options);
}
async function loadProviderStatus() {
  const version=active,owner=session,request=++providerRequest;
  let response=null;
  try {response=await get('/api/meta/providers');} catch { /* Preserve configuration when metadata is unavailable. */ }
  if(version!==active || owner!==session || request!==providerRequest)return;
  providerMetadata=response;updateProviderWarning();
}
function updateProviderWarning() {
  const host=root?.querySelector('[data-provider-warning]');
  if(!host || !session)return;
  const m=model(),fields=m.schema.tables.flatMap(table=>(m.table(table.name).columns || [])
    .filter(column=>column.provider==='mimesis'||column.mimesis_method||column.native_mimesis_method).map(column=>({table,column})));
  const selected=m.document.provider==='mimesis';
  const capability=providerMetadata?.statuses?.mimesis;
  const unavailable=capability?capability.available===false:providerMetadata?.available&&!providerMetadata.available.includes('mimesis');
  host.hidden=!(unavailable&&(selected||fields.length));
  if(host.hidden){host.replaceChildren();return;}
  const broken=capability?.status==='import_error';
  const fieldNames=fields.slice(0,3).map(({table,column})=>`${table.name}.${column.name}`).join('、');
  host.replaceChildren(h('p',{class:'wb-error'},`Mimesis ${broken?'加载异常':'未安装'}，使用此引擎的字段暂不能预览或生成。`),
    ...(fields.length?[h('p',{},`字段规则：${fieldNames}${fields.length>3?`等 ${fields.length} 个字段`:''}。更换全局引擎会保留字段覆盖。`)]:[]),
    button('管理插件',()=>{if(host.isConnected)location.hash='#/settings?section=plugins';},{small:true}),
    button('更改引擎',()=>{
      if(!host.isConnected)return;
      if(selected)return action(configSettings)();
      const {table,column}=fields[0],schemaColumn=table.columns.find(value=>value.name===column.name);
      if(schemaColumn)openRule(table,schemaColumn);
    },{small:true}));
}
async function loadGuidanceAI() {
  const version=active,owner=session,request=++guidanceRequest;
  let config=null;
  try { const response=await get('/api/workbench/ai/config');config={available:response.available,ready:response.ready,availability_status:response.availability_status}; } catch { /* Manual configuration stays available. */ }
  if(version!==active || owner!==session || request!==guidanceRequest)return;
  guidanceAI=config;updateGuidance();syncBusy();
}
function updateGuidance() {
  if(!root?.isConnected)return;
  const host=root?.querySelector('.wb-next-step');
  if(!host || !session)return;
  const m=model(),step=nextStep(m,previewResults.get(m)),ai=guideAIState(guidanceAI);
  host.hidden=!m.schema.tables.length || Boolean(m.view.imported);
  const focused=host.contains?.(document.activeElement)?document.activeElement?.getAttribute('data-guide-action'):null;
  const currentSelected=()=>m.selected(m.view.table)?m.view.table:m.document.tables[0]?.name || m.view.table;
  const edit=()=>{
    if(m.errors.size) {
      const input=content.querySelector('[aria-invalid="true"]') || content.querySelector('.count-setting input');
      input?.focus();input?.scrollIntoView({block:'nearest'});return;
    }
    chooseTable(currentSelected(),'fields');
    [...content.querySelectorAll('.wb-rule-button')].find(control=>!control.disabled)?.focus();
  };
  const preview=()=>m.document.tables.length>1?refreshSamples():chooseTable(currentSelected(),'preview');
  const handlers={select:locateGenerationSelection,edit,preview:action(preview),check:action(showDependencies),generate:action(summary)};
  const toggle=button(guidanceCollapsed?'展开引导':'收起引导',()=>{
    guidanceCollapsed=!guidanceCollapsed;
    try { localStorage.setItem('sqlseed.workbench.guide.collapsed',String(guidanceCollapsed)); } catch { /* Keep the in-memory preference. */ }
    updateGuidance();syncBusy();host.querySelector('[data-guide-action="toggle"]')?.focus();
  },{plain:true,small:true,'aria-expanded':String(!guidanceCollapsed),'aria-controls':'wb-next-step-body','data-guide-action':'toggle'});
  const actions=h('div',{class:'wb-next-step-actions'},
    button(step.label,handlers[step.action],{small:true,'data-guide-action':'next',...(['preview','check','generate'].includes(step.action)?{'data-db-action':''}:{})}));
  if(m.document.tables.length && step.action!=='edit')actions.append(button('手动检查规则',edit,{plain:true,small:true,'data-guide-action':'edit'}));
  const body=h('div',{id:'wb-next-step-body',class:'wb-next-step-body',hidden:guidanceCollapsed},
    h('div',{class:'wb-next-step-main'},h('h3',{},step.title),h('p',{},step.body),actions),
    h('div',{class:'wb-next-step-ai'},h('span',{},icon('sparkles'),h('strong',{},'AI 辅助配置')),
      h('small',{},ai.status),button(ai.label,()=>openAI(m.document.tables.length?'selected':'current'),{small:true,'data-guide-action':'ai'})));
  host.replaceChildren(h('div',{class:'wb-next-step-heading'},h('span',{},step.scope),toggle),body);
  if(focused)host.querySelector(`[data-guide-action="${focused}"]`)?.focus();
}
function needsAIDefaultPreflight(m) {
  const mappings=m.document.custom_column_mappings;
  const custom=Object.keys(mappings?.exact || {}).length || mappings?.pattern?.length;
  return m.schema.tables.some(table=>table.columns.some(column=>column.default!==null&&column.default!==undefined)
    && (custom || m.table(table.name).enrich));
}
async function openAI(initialScope='current',initialState=null,{previewOrigin=null}={}) {
  clearAIHandoff();
  const current=modalTicket(), m=model(),version=active,owner=session;
  if(!validNavigation())return;
  const onReturn=previewOrigin?previewReturnHandler(owner,m,previewOrigin):null;
  const intent=modalIntent;let suppressReturn=false;
  const returnToPreview=()=>{if(onReturn)Promise.resolve().then(()=>{if(!suppressReturn&&intent===modalIntent)onReturn();});};
  function goAISettings({section,context}) {
    if(!current())return;
    suppressReturn=true;
    const returnTo=location.hash.startsWith('#/workbench')?location.hash:'#/workbench';
    rememberAIHandoff({model:m,connId:owner.connId,returnTo,context:previewOrigin?{...context,previewOrigin}:context});
    location.hash=`#/settings?section=${section}`;
  }
  let defaultModes;
  if(needsAIDefaultPreflight(m)) {
    let cancelled=false;
    const loading=openedModal=modal('AI 配置助手',{onClose:()=>{cancelled=true;if(!suppressReturn)returnToPreview();}});
    loading.body.append(h('p',{role:'status'},'正在解析当前配置的字段生成方式…'));
    loading.actions.append(button('取消',loading.close));
    try {
      const result=await send('/api/workbench/ai/eligibility',{conn_id:owner.connId,schema_hash:m.schema.schema_hash,
        document:m.document,table_drafts:Object.values(m.view.tableDrafts)});
      if(cancelled || !current()){loading.close();return;}
      if(result.schema_hash!==m.schema.schema_hash)throw new Error('数据库结构已变化，请刷新后重新打开 AI 助手。');
      defaultModes=result.default_modes;suppressReturn=true;loading.close();suppressReturn=false;
    } catch(error) {
      if(!cancelled&&current()){
        const unavailable=error.status===503&&error.detail?.code==='ai_unavailable';
        loading.body.replaceChildren(h('p',{role:'alert'},unavailable
          ?`AI 扩展${error.detail.availability_status==='import_error'?'加载异常':'未安装'}，规则建议与分析不可用。请前往插件与版本${error.detail.availability_status==='import_error'?'查看异常':'安装扩展'}后返回。`:error.message));
        if(unavailable)loading.actions.append(button('前往插件设置',()=>{
          if(cancelled||!current())return;
          goAISettings({section:'plugins',context:{scope:typeof initialScope==='string'?initialScope:'current',currentTable:m.view.table,businessContext:'',...initialState}});
          loading.close();
        },{primary:true}));
      }
      else loading.close();
      return;
    }
  }
  openedModal=openAIAssistant({model:m,defaultModes,connId:session.connId,isCurrent:current,initialScope:typeof initialScope==='string'?initialScope:'current',initialState,
    onSettings:goAISettings,
    onClose:()=>{if(version===active && owner===session)loadGuidanceAI();returnToPreview();},onApply:suggestions=>{
    if(!current())throw new Error('配置已变化，请重新分析。');
    for(const item of suggestions)if(!m.schema.tables.find(t=>t.name===item.table)?.columns.some(c=>c.name===item.column))throw new Error('建议字段已失效，请刷新结构。');
    m.applyPatches(suggestions);
    m.aiApplied={epoch:m.epoch,targets:suggestions.map(item=>({table:item.table,column:item.column}))};
    if(!onReturn)drawBody();else updateStatus();
    notify(`已应用 ${suggestions.length} 条 AI 建议。请预览并检查，确认效果后生成数据。`);
  }});
}
function renameConfig() {
  modalIntent++;
  const current = ticket(), dialog = openedModal = modal('重命名生成配置');
  const input = h('input', {'aria-label': '配置名称', value: session.name, maxlength: 120});
  const error = h('p', {class: 'wb-error', role: 'alert'});
  dialog.body.append(h('label', {class: 'control'}, '配置名称', input), error);
  dialog.actions.append(button('取消', dialog.close), button('确定', () => {
    if (!current()) { dialog.close(); return; }
    if (!input.value.trim()) { error.textContent = '请填写配置名称'; return; }
    session.name = input.value.trim(); model().touch(); dialog.close(); draw();
  }, {primary: true}));
  input.focus();
}
function drawSidebar() {
  const m = model(), refs = referencedTables();
  const view=sidebarViews.get(m) || {structureOpen:false,query:''};sidebarViews.set(m,view);
  const previousMenu=sidebar.querySelector('.wb-structure-menu');
  if(previousMenu)view.structureOpen=previousMenu.open;
  const scrollTop=sidebar.querySelector('.wb-table-list')?.scrollTop || 0;
  sidebar.replaceChildren(h('div', {class: 'source'},
    button(databaseLabel(), () => { if (!validNavigation()) return; closeComponents(); graphViews.delete(m); m.view.imported=false; m.view.page = 'graph'; m.view.graphMode = 'all'; selectedEdge = null; drawBody(); }, {glyph: 'database', plain: true, class: 'source-head wb-source', title: '查看整库关系图'}),
    h('div', {class: 'source-note'}, `${m.schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'} · 已连接`, button('ⓘ', connectionInfo, {plain: true, class: 'source-info', 'aria-label': '查看连接信息'})),
    h('details',{class:'wb-structure-menu',open:view.structureOpen,ontoggle:event=>{view.structureOpen=event.currentTarget.open;}},h('summary',{},icon('schema'),'数据库结构操作'),
      h('div',{class:'wb-structure-commands',role:'group','aria-label':'数据库结构操作'},
        h('small',{},`${m.schema.tables.length} 张表 · ${m.schema.edges.length} 条外键`),
        button('重新读取结构',action(refreshSchema),{small:true,glyph:'refresh',title:'重新读取表、字段和外键；不生成样例或写入数据'}),
        button('导出关系图 JSON',()=>download('sqlseed-schema.json',JSON.stringify(structureSnapshot(),null,2)),{small:true,glyph:'download'}),
        button('导入关系图 JSON',action(importStructure),{small:true,glyph:'upload'}),
        ...(importedStructures.has(session.connId)?[button('查看已导入关系图',()=>{m.view.imported=true;drawBody();},{small:true,glyph:'schema'})]:[])))),
    h('div', {class: 'sidebar-label'}, h('span', {}, '数据库表'), h('span', {'data-selection-count': ''}, `${m.document.tables.length} / ${m.schema.tables.length}`)),
    h('div', {class: 'selection-actions'}, button('全选', () => { if (!validNavigation()) return; m.schema.tables.forEach(t => m.toggleTable(t.name, true)); drawBody(); }, {small:true}),
      button('清空选择', () => { if (!validNavigation()) return; m.schema.tables.forEach(t => m.toggleTable(t.name, false)); drawBody(); }, {small:true})),
    h('label',{class:'search wb-table-search'},icon('search'),h('input',{type:'search',placeholder:'查找表','aria-label':'查找表',value:view.query,oninput:event=>{view.query=event.target.value;filterTables();}})),
    h('div', {class: 'tables wb-table-list'}, ...m.schema.tables.map(table => h('div', {class: `table-entry wb-table-entry${m.view.table === table.name ? ' active' : ''}`, 'data-table': table.name},
      h('input', {type: 'checkbox', checked: m.selected(table.name), 'aria-label': `生成 ${table.name}`, onchange: e => {
        if (!validNavigation()) { e.target.checked = m.selected(table.name); return; } m.toggleTable(table.name, e.target.checked); drawBody();
      }}),
      h('button', {class: 'table-button wb-table-name', title: `${table.name} 的字段规则`, onclick: () => chooseTable(table.name)},
        h('span', {class: 'table-name'}, table.name), h('span', {class: 'count'}, m.selected(table.name) ? `生成 ${m.table(table.name).count} 行` : refs.has(table.name) ? '仅引用已有数据' : '未加入生成')),
      button('', () => chooseTable(table.name, 'graph'), {glyph: 'schema', plain: true, class: `table-graph-shortcut wb-table-graph${m.view.table === table.name && m.view.page === 'graph' ? ' active' : ''}`, title: `${table.name} 的完整依赖路径`, 'aria-label': `${table.name} 的依赖路径`, 'aria-pressed': String(m.view.table === table.name && m.view.page === 'graph')})
    ))),
    ...(m.document.tables.length>1?[button('预览已选表',action(refreshSamples),{glyph:'fields',small:true,class:'wb-batch-preview','data-db-action':'',title:`预览已勾选的 ${m.document.tables.length} 张表，不写入数据库`})]:[]),
    h('div', {class: 'scope-summary', 'aria-live': 'polite'}));
  function filterTables(){
    for(const row of sidebar.querySelectorAll('.wb-table-entry'))row.hidden=!row.dataset.table.toLowerCase().includes(view.query.trim().toLowerCase());
  }
  filterTables();
  sidebar.querySelector('.wb-table-list').scrollTop=scrollTop;
}
function connectionInfo() {
  modalIntent++;
  const dialog = openedModal = modal('当前数据库');
  dialog.body.append(h('dl', {class: 'wb-key-values'}, h('dt', {}, '连接目标'), h('dd', {class: 'mono'}, model().schema.target_label),
    h('dt', {}, '数据库类型'), h('dd', {}, model().schema.dialect === 'sqlite' ? 'SQLite' : 'PostgreSQL'), h('dt', {}, '状态'), h('dd', {}, '已连接')));
  dialog.actions.append(button('切换数据库', () => { dialog.close(); document.getElementById('connection-button')?.click(); }), button('关闭', dialog.close, {primary: true}));
}
function viewCurrentData() {
  const current=modalTicket(), owner=session, m=model(), table=m.view.table;
  const viewer=openTableData({connId:owner.connId,table,targetKey:m.schema.target_key,targetLabel:m.schema.target_label,
    isCurrent:()=>current() && session===owner && model()===m && m.view.table===table});
  openedModal=viewer.dialog;
}
function drawBody({autoPreview=true}={}) {
  if (!root?.isConnected) return;
  closeComponents(); drawSidebar();
  const m = model(), table = m.schema.tables.find(t => t.name === m.view.table);
  content.replaceChildren();
  const imported=importedStructures.get(session.connId);
  if(m.view.imported && imported){drawImportedStructure(imported);appendStatus();updateStatus();return;}
  if (!table) { content.append(h('div', {class: 'empty'}, '当前数据库还没有可配置的表。')); appendStatus(); updateStatus(); return; }
  const count = h('input', {type: 'number', min: 1, step: 1, value: m.view.invalidCounts?.[table.name] ?? m.table(table.name).count,
    disabled: !m.selected(table.name), 'aria-label': `${table.name} 生成数量`, oninput: e => {
      const valid = m.setCount(table.name, e.target.value); m.view.invalidCounts ||= {};
      if (valid) delete m.view.invalidCounts[table.name]; else m.view.invalidCounts[table.name] = e.target.value;
      e.target.setAttribute('aria-invalid', valid ? 'false' : 'true');
      if(m.view.page==='preview'){tablePreview?.destroy();tablePreview=null;content.querySelector('.wb-table-preview')?.replaceChildren(h('p',{class:'wb-preview-help'},'生成数量已改变，请点击“预览数据”重新查看。'));}
      updateStatus();
    }});
  content.append(h('div', {class: 'table-heading'}, h('div', {class: 'table-title'}, h('h2', {}, table.name), h('span', {class: 'desc'}, `${table.columns.length} 个字段 · 已有 ${table.row_count} 行`),
    button('查看当前数据',viewCurrentData,{plain:true,small:true,class:'wb-view-current-data','data-db-action':''})),
    h('div', {class: 'table-actions'}, ...(!m.selected(table.name) ? [button('加入生成', () => { m.toggleTable(table.name, true); drawBody(); }, {small: true})] : []),
      h('label', {class: 'count-setting'}, '生成数量', count, h('span', {}, '行')))));
  const pages=[['fields','字段规则'],['preview','预览数据'],['graph','关系图']];
  const tabs=h('div',{class:'tabs',role:'tablist','aria-label':'当前表视图'});
  for(const [page,label] of pages)tabs.append(button(label,()=>{const rendered=chooseTable(m.view.table,page);root.querySelector(`#wb-table-tab-${page}`)?.focus();return rendered;},{
    plain:true,role:'tab',id:`wb-table-tab-${page}`,'aria-controls':'wb-table-panel',
    'aria-selected':String(m.view.page===page),tabindex:m.view.page===page?0:-1,
    class:m.view.page===page?'active':'',
    onkeydown:event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();const buttons=[...tabs.children],index=buttons.indexOf(event.currentTarget);
      const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      buttons.forEach((item,i)=>item.setAttribute('tabindex',i===next?'0':'-1'));buttons[next].focus();
    },
  }));
  const viewbar=h('div',{class:'viewbar'},tabs);content.append(viewbar);
  const panel=h('section',{id:'wb-table-panel',role:'tabpanel','aria-labelledby':`wb-table-tab-${m.view.page}`});
  content.append(panel);
  // Leaf renderers append to the same table panel; the page header stays stable.
  const host=content;content=panel;
  if(m.view.page==='graph')drawGraph(table);else if(m.view.page==='preview')drawTablePreview(table);else drawFields(table,viewbar);
  content=host;
  appendStatus();updateStatus();
  if(autoPreview && m.view.page==='preview' && !tablePreview?.cached)return tablePreview?.refresh();

}
function appendStatus() {
  notice = h('span', {class: 'wb-notice', role: 'status', 'aria-live': 'polite'}, '规则调整后，可在当前表的“预览数据”中检查效果。');
  content.append(h('div', {class: 'statusbar'}, h('span', {}, h('i', {class: 'status-dot'}), notice), h('span', {}, '预览不写入数据库')));
}
function ruleDescription(table, column) {
  const rule = model().rule(table.name, column.name), generator = rule.generator || rule.generator_name;
  const fk = table.foreign_keys.find(key => key.columns.includes(column.name));
  const locked = column.is_autoincrement || column.is_computed;
  const allocated = locked || generator === 'skip';
  if (allocated) return {rule, fk, locked, allocated, label: column.is_computed ? '数据库计算' : column.is_autoincrement || column.is_rowid_alias ? '数据库自动分配' : column.default != null ? '数据库默认值' : '使用 NULL（空值）', detail: column.is_autoincrement || column.is_rowid_alias ? '追加数据，由数据库继续分配主键；保留已有 ID' : column.is_computed ? '由数据库表达式计算' : column.default != null ? `使用数据库默认值：${column.default}` : '省略该列，由数据库填入 NULL'};
  if (fk) return {rule, fk, locked, label: `引用 ${fk.ref_table}.${fk.ref_columns.join(', ')}`, detail: rule.params?.strategy === 'coverage' ? '优先覆盖父表可用记录' : '从父表的可用记录中取值', glyph: 'link'};
  if (rule.derive_from) return {rule, locked, label: '根据其他字段推算', detail: `${Array.isArray(rule.derive_from) ? rule.derive_from.join(' / ') : rule.derive_from} · ${rule.expression || ''}`, glyph: 'derive'};
  const params = rule.params || {};
  let detail = Object.entries(params).filter(([key, value]) => !key.startsWith('_') && value != null).map(([key, value]) => `${paramLabel(key)} ${valueText(value)}`).join('，');
  if (params.min_value !== undefined || params.max_value !== undefined) detail = `${params.min_value ?? '不限'}—${params.max_value ?? '不限'}${params.precision != null ? `，保留 ${params.precision} 位小数` : ''}`;
  if (params.choices) detail = Array.isArray(params.choices) ? params.choices.map(valueText).join(' / ') : valueText(params.choices);
  if (params.start_date || params.end_date) detail = `${params.start_date || '不限'} — ${params.end_date || '不限'}`;
  if (rule.null_ratio) detail += `${detail ? '，' : ''}${Math.round(rule.null_ratio * 100)}% 为空`;
  return {rule, locked, label: genLabel(generator || '自动匹配'), detail: detail || '使用生成器默认参数'};
}
function sampleNode(value, allocated = false) {
  if (value === undefined) return h('span', {class: 'sample placeholder'}, allocated ? (allocated===true || allocated==='数据库自动分配'?'自动分配':allocated) : '待预览');
  if (value === null) return h('span', {class: 'sample null'}, 'NULL');
  const text = valueText(value), parts = text.match(/^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d(?:\.\d+)?)(.*)$/);
  if (parts) return h('span', {class: 'sample timestamp', title: text}, h('span', {}, parts[1]), h('span', {class: 'sample-time'}, parts[2] + parts[3]));
  return h('span', {class: 'sample', title: text}, text);
}
function drawFields(table, viewbar) {
  const m = model();
  const rows = h('tbody'), previewNote = h('div', {class: 'wb-preview-notice', role: 'status'});
  const search = h('input', {type: 'search', placeholder: '查找字段', 'aria-label': '查找字段', value: fieldQuery,
    oninput: e => { if (e.isComposing) return; fieldQuery = e.target.value; drawRows(); }, oncompositionend: e => { fieldQuery = e.target.value; drawRows(); }});
  viewbar.append(h('label', {class: 'search'}, icon('search'), search));
  if (!m.selected(table.name)) content.append(h('div', {class: 'view-only-note'}, '当前表未勾选，可查看和调整草稿；不会纳入本次生成。'));
  content.append(h('div',{class:'sample-guide'},h('span',{},'字段名查看结构，取值规则调整生成方式')),previewNote,
    h('div',{class:'wb-rules-scroll',tabindex:0,'aria-label':`${table.name} 字段规则，可滚动查看`},
      h('table',{class:'field-table wb-data'},h('colgroup',{},h('col',{class:'col-field'}),h('col',{class:'col-rule'})),
        h('thead',{},h('tr',{},...['字段','取值规则'].map(text=>h('th',{scope:'col'},text)))),rows)));
  function drawRows() {
    previewNote.replaceChildren(...(m.previewIssues || []).map(issue => h('p', {class: issue.severity === 'error' ? 'wb-error' : 'muted'}, `${issue.table || ''}${issue.column ? `.${issue.column}` : ''}：${issue.message}`)));
    rows.replaceChildren(...table.columns.filter(c => c.name.toLowerCase().includes(fieldQuery.toLowerCase())).map(column => {
      const info = ruleDescription(table, column);
      const ruleButton = h('button', {class: 'wb-rule-button', 'data-rule-column':column.name, onclick: () => openRule(table, column)},
        h('span', {class: 'rule-line'}, ...(info.glyph ? [icon(info.glyph)] : []), info.label), h('span', {class: 'rule-meta'}, info.detail));
      return h('tr', {class: columnName === column.name ? 'selected' : ''},
        h('td', {}, button(column.name, () => { columnName = column.name; for(const row of rows.children)row.classList.toggle('selected',row.querySelector('.wb-field-name')?.textContent===column.name); openRule(table, column, 'information'); }, {plain: true, class: 'field-name wb-field-name'}),
          h('small', {class: 'field-type'}, `${column.type}${column.is_primary_key ? ' · 主键' : ''}${info.fk ? ' · 外键' : ''}${column.nullable ? ' · 可空' : ' · 不可空'}`)), h('td', {}, ruleButton));
    }));
    if (!rows.children.length) rows.append(h('tr', {}, h('td', {colspan: 2, class: 'empty'}, '没有匹配的字段')));
  }
  if (!table.columns.some(c => c.name === columnName)) columnName = table.columns[0]?.name || '';
  drawRows();
}
function openRule(table, column, initialTab='rule',{onReturn,previewOrigin=null}={}) {
  const intent=++modalIntent;
  const m = model(), epoch = m.epoch, version = active, current=ticket();
  let component, error = null, changed = false, pending;
  const dialog = openedModal = modal(column.name, {drawer: true, onClose: () => {
    component?.destroy();
    if(onReturn)Promise.resolve().then(()=>{if(intent===modalIntent)onReturn();});
  }});
  const apply = button('应用规则', () => {
    if (error) return;
    if (version !== active || m !== model() || epoch !== m.epoch) { dialog.close(); notify('配置已变化，请重新打开字段规则。', true); return; }
    if (changed) m.setColumn(table.name, column.name, pending);
    dialog.close();
    if(!onReturn){drawBody();content.querySelectorAll('.wb-rule-button').forEach(node=>{if(node.dataset.ruleColumn===column.name)node.focus();});}else updateStatus();
    notify(changed ? `${table.name}.${column.name} 的规则已应用，请在“预览数据”中检查效果。` : '规则未变更。');
  }, {primary: true});
  dialog.body.append(h('div', {class: 'drawer-subtitle'}, `${table.name}.${column.name} · ${column.type}`));
  const tabs=h('div',{class:'wb-field-tabs',role:'tablist','aria-label':'字段详情'});
  const information=h('section',{id:'field-information',role:'tabpanel','aria-labelledby':'field-information-tab'});
  const rules=h('section',{id:'field-rule',role:'tabpanel','aria-labelledby':'field-rule-tab'});
  const info=ruleDescription(table,column), metadata=h('dl',{class:'wb-field-facts'});
  for(const [label,value] of [['字段',column.name],['数据类型',column.type],['允许空值',column.nullable?'是':'否'],['主键',column.is_primary_key?'是':'否'],['数据库默认值',column.default??'未设置'],['自动分配',column.is_autoincrement || column.is_rowid_alias?'由数据库分配':'否']])metadata.append(h('dt',{},label),h('dd',{},String(value)));
  information.append(h('p',{class:'muted'},'读取自数据库的结构信息。生成规则不会修改表结构。'),metadata);
  if(info.fk)information.append(h('h3',{},'外键来源'),h('p',{class:'mono'},`${info.fk.ref_table}.${info.fk.ref_columns.join(', ')}`),h('p',{},info.detail));
  for(const constraint of table.unique_constraints || [])if(constraint.columns.includes(column.name))information.append(h('h3',{},constraint.columns.length===1?'唯一约束':'复合唯一约束'),h('p',{class:'mono'},constraint.columns.join(' + ')));
  if(table.checks?.length)information.append(h('details',{class:'wb-field-constraints'},h('summary',{},'所属表的 CHECK 约束'),h('p',{class:'muted'},'这些约束作用于整张表，可能涉及其他字段。'),...table.checks.map(check=>h('p',{class:'mono'},typeof check==='string'?check:check.sqltext || check.expression || JSON.stringify(check)))));
  const names=[['information','字段信息'],['rule','取值规则']];
  let currentTab=initialTab;
  function activate(name,focus=false) {
    currentTab=name;information.hidden=name!=='information';rules.hidden=name!=='rule';
    [...tabs.children].forEach(tab=>{const selected=tab.dataset.tab===name;tab.setAttribute('aria-selected',String(selected));tab.setAttribute('tabindex',selected?'0':'-1');if(selected&&focus)tab.focus();});
    dialog.actions.replaceChildren(button('取消',dialog.close),name==='information'?button('编辑取值规则',()=>activate('rule',true),{primary:true}):apply);
    if(name==='rule' && !component)mountEditor();
  }
  for(const [name,label] of names)tabs.append(button(label,()=>activate(name),{plain:true,id:`field-${name}-tab`,role:'tab','data-tab':name,'aria-controls':name==='rule'?'field-rule':'field-information',onkeydown:event=>{
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();activate(event.key==='Home'?'information':event.key==='End'?'rule':currentTab==='rule'?'information':'rule',true);}
  }}));
  const eligibility=fieldAIEligibility(table,column,m.rule(table.name,column.name));
  if(!eligibility.eligible)information.append(h('p',{class:'wb-ai-protected'},eligibility.reason));
  const canAI=eligibility.eligible || (needsAIDefaultPreflight(m) && eligibility.code==='database_default');
  const aiHint=h('p',{class:'muted',role:'status','data-rule-ai-hint':''});
  const ai=button('用 AI 调整',()=>{
    if(!dialog.el.isConnected || !current() || error || changed || !canAI)return;
    return openAI('columns',{scope:'columns',currentTable:table.name,columnSelection:{[table.name]:[column.name]}},{previewOrigin});
  },{small:true,glyph:'sparkles','data-rule-ai':''});
  function updateAI(){
    ai.disabled=Boolean(error || changed || !canAI || !current());
    aiHint.textContent=error || changed ? '请先应用或取消当前修改，再使用 AI 调整此字段。'
      :canAI?'针对当前字段提出规则建议，审阅后再应用。':eligibility.reason;
  }
  rules.append(h('div',{class:'wb-field-rule-ai'},ai,aiHint));updateAI();
  dialog.body.append(tabs,information,rules);
  function mountEditor() {
  component = createRuleEditor({table, column, rule: m.rule(table.name, column.name), baseline: table.mapping[column.name], catalog,
    onChange: rule => { pending = rule; changed = true; updateAI(); }, onValidity: message => { error = message; apply.disabled = !!message; updateAI(); }});
  rules.append(component.el);
  }
  activate(initialTab);
}
function drawGraph(table) {
  const m = model(), panel = h('aside', {class: 'graph-inspector wb-inspector'}), area = h('div', {class: 'graph-workspace wb-graph-workspace'});
  const refs = referencedTables();
  const graphSchema = {...m.schema, nodes: m.schema.nodes.map(node => ({...node, selected: m.selected(node.id), referenced: refs.has(node.id), count: m.table(node.id).count}))};
  const inspectorBody = h('div', {class: 'inspector-body wb-inspector-body'});
  graphOwner=m;
  graph = createSchemaGraph({schema: graphSchema, focus: table.name, mode: m.view.graphMode || 'all', pathMode: m.view.pathMode || 'complete', initialView: graphViews.get(m), issues: m.check?.issues || [],
    onSelect: name => {
      if (!validNavigation()) return false;
      const next = m.schema.tables.find(t => t.name === name);
      if (!next) { notify('外部引用来源，仅展示结构。'); return; }
      table = next; m.view.table = name; selectedEdge = null; drawSidebar(); updateStatus(); inspect();
      // Count/actions belong to the focused table: rebuild its context through
      // the same page path on next table navigation, not through selection.
      syncTableHeading(table);
      sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({block: 'nearest'});
    },
    onEdge: edge => { selectedEdge = edge; inspect(); },
    onViewChange: view => { graphViews.set(m,view); m.view.graphMode=view.mode; m.view.pathMode=view.pathMode; },
    onExpand: expanded => area.classList.toggle('expanded', expanded)});
  const section = h('section', {class: 'panel-content database-graph wb-graph-section'});
  if (graph.toolbar) section.append(graph.toolbar);
  area.append(graph.el, panel); section.append(area); content.append(section);
  function inspect() {
    panel.replaceChildren(h('div', {class: 'inspector-tabs'},
      button('字段规则', () => { inspectorMode = 'fields'; selectedEdge = null; inspect(); }, {plain: true, class: inspectorMode === 'fields' ? 'active' : ''}),
      button('依赖检查', () => { inspectorMode = 'dependencies'; selectedEdge = null; inspect(); }, {plain: true, class: inspectorMode === 'dependencies' ? 'active' : ''})),
      h('div', {class: 'inspector-actions'}, h('div', {class: 'inspector-table-title'}, h('strong', {class: 'mono'}, table.name), h('small', {}, `${table.columns.length} 个字段`)),
        button('查看字段规则', () => chooseTable(table.name), {small: true})), inspectorBody);
    if (selectedEdge) {
      inspectorBody.replaceChildren(h('h3', {}, '外键引用'),
        h('div', {class: 'wb-edge-mapping'}, ...selectedEdge.sourceColumns.map((source, i) => h('div', {},
          h('code', {}, `${selectedEdge.source}.${source}`), h('span', {}, '↓'), h('code', {}, `${selectedEdge.target}.${selectedEdge.targetColumns[i]}`)))),
        h('p', {class: 'muted'}, '箭头从父表指向引用它的子表。成组字段共同构成同一条外键。'),
        button('定位引用字段', () => {
          const target = m.schema.tables.find(t => t.name === selectedEdge.target);
          const column = target?.columns.find(c => c.name === selectedEdge.targetColumns[0]);
          if (column) openRule(target, column);
        }, {small: true}));
    } else if (inspectorMode === 'dependencies') renderDependencies(inspectorBody, name => {
      if (!validNavigation()) return;
      const next = m.schema.tables.find(t => t.name === name);
      if (!next) return;
      table = next; m.view.table = name; graph.focusTable?.(name); drawSidebar(); syncTableHeading(table); updateStatus(); inspect();
      sidebar.querySelector('.wb-table-entry.active')?.scrollIntoView({block: 'nearest'});
    }, table.name);
    else inspectorBody.replaceChildren(h('p', {class: 'muted'}, '选择字段调整生成器与参数。'), ...table.columns.map(column => {
      const info = ruleDescription(table, column);
      return button('', () => openRule(table, column), {plain: true, class: 'graph-field inspector-field wb-field-card', title: `调整 ${table.name}.${column.name}`});
    }));
    if (!selectedEdge && inspectorMode === 'fields') [...inspectorBody.querySelectorAll('.wb-field-card')].forEach((card, i) => {
      const column = table.columns[i], info = ruleDescription(table, column);
      card.append(h('div', {class: 'graph-field-title field-card-heading'}, h('strong', {class: 'mono'}, column.name), h('small', {}, info.allocated ? '数据库处理' : info.fk ? '引用' : info.rule.derive_from ? '派生' : '生成器')),
        h('span', {}, info.label), sampleNode(m.samples[table.name]?.[0]?.[column.name], info.allocated?info.label:false));
    });
  }
  inspect();
}
function syncTableHeading(table) {
  const header = content.querySelector('.table-heading');
  if (!header) return;
  // Reuse the exact controls without keeping handlers bound to the previous node.
  header.querySelector('h2').textContent = table.name;
  header.querySelector('.desc').textContent = `${table.columns.length} 个字段 · 已有 ${table.row_count} 行`;
  const count = h('input', {type: 'number', min: 1, step: 1, disabled: !model().selected(table.name), value: model().table(table.name).count,
    'aria-label': `${table.name} 生成数量`, oninput: e => { const m=model(), valid=m.setCount(table.name, e.target.value); m.view.invalidCounts ||= {}; if(valid)delete m.view.invalidCounts[table.name];else m.view.invalidCounts[table.name]=e.target.value; e.target.setAttribute('aria-invalid',valid?'false':'true'); updateStatus(); }});
  header.querySelector('.table-actions').replaceChildren(...(!model().selected(table.name) ? [button('加入生成', () => { model().toggleTable(table.name, true); drawBody(); }, {small: true})] : []), h('label', {class: 'count-setting'}, '生成数量', count, h('span', {}, '行')));
  const tabButtons = content.querySelector('.tabs').querySelectorAll('button');
  tabButtons[0].onclick = () => chooseTable(table.name);
}
function renderDependencies(out, locate = name => { inspectorMode = 'dependencies'; chooseTable(name, 'graph'); }, focus = null, onUpdate = null) {
  const m=model(), result=m.check;
  const edges=[...m.schema.edges];
  for(const association of m.document.associations || []) for(const target of association.target_tables || [])
    edges.push({source:association.source_table,target,sourceColumns:[association.source_column || association.column_name],targetColumns:[association.column_name]});
  const related=new Set(focus?[focus]:m.document.tables.map(t=>t.name));
  for(const name of related) for(const edge of edges) if(edge.target===name)related.add(edge.source);
  const executable=new Set(focus?[focus]:m.document.tables.map(t=>t.name));
  for(const name of executable) for(const edge of edges) if(edge.target===name && m.selected(edge.source))executable.add(edge.source);
  const upstreamEdges=edges.filter(edge=>related.has(edge.target)&&related.has(edge.source));
  const relevantIssues=(result?.issues || []).filter(issue=>!focus || !issue.table || executable.has(issue.table));
  const sourceCards=upstreamEdges.map(edge=>{
    const parent=m.schema.tables.find(t=>t.name===edge.source);
    const evidence=result?.sources?.find(source=>source.table===edge.target && source.source_table===edge.source && source.column===(edge.targetColumns || []).join(','));
    const selected=m.selected(edge.source), rows=evidence?.row_count ?? parent?.row_count;
    let explanation;
    if(focus && !executable.has(edge.target)) explanation='结构上的间接上游；本次引用中间表已有数据，此关系不要求先生成该来源。';
    else if(selected) explanation=evidence?.has_values===false?'先生成父表，再从生成后的有效主键取值。': '父表也在本次生成范围，按依赖顺序先生成。';
    else if(evidence?.has_values) explanation=`已有 ${rows} 行 · 仅引用，不新增。已检查存在可用引用值，因此无需勾选父表。`;
    else if(evidence?.has_values===false) explanation=evidence.nullable?'无可用引用值；此外键允许 NULL。':'无可用引用值；请将父表加入生成范围。';
    else explanation=`${rows == null?'行数未知':`已有 ${rows} 行`} · ${selected?'本次生成':'仅引用'}；是否有可用引用值以检查结果为准。`;
    return h('article',{class:'wb-source-card'},h('strong',{class:'mono'},`${edge.source}.${(edge.sourceColumns || []).join(' + ')} → ${edge.target}.${(edge.targetColumns || []).join(' + ')}`),
      h('p',{},explanation),button(`查看 ${edge.source}`,()=>locate(edge.source),{small:true}));
  });
  const previousSources=out.querySelector('.wb-dependency-sources');
  const sources=h('details',{class:'wb-dependency-sources',open:previousSources?previousSources.open:Boolean(focus)},
    h('summary',{},focus?`${focus} · 全部上游来源（${sourceCards.length}）`:`引用来源明细（${sourceCards.length}）`),
    h('p',{class:'muted'},focus?'此处展示本表依赖的完整上游链。图中的下游表示受本表影响的表，不是本表的生成前置条件。':'查看来源字段映射、已有数据与生成范围之间的关系。'),
    ...(sourceCards.length?sourceCards:[h('p',{class:'muted'},focus?'当前表没有上游外键或关联依赖。':'所选表没有外部引用依赖。')]));
  out.replaceChildren(h('h3',{},focus?`${focus} · 依赖检查`:'检查所选表的规则与依赖'));
  if(focus && !m.selected(focus)){
    out.append(h('p',{class:'muted'},'当前表未纳入本次检查范围。这里仅解释结构；加入生成后再检查规则与引用来源。'),sources);return;
  }
  if(!result){out.append(h('p',{class:'muted'},'尚未检查当前配置。'),button('开始检查',action(async()=>{if(await check(false))drawBody();},'检查依赖'),{glyph:'check'}),sources);syncBusy();return;}
  const blockers=relevantIssues.filter(issue=>issue.severity==='error'),reminders=relevantIssues.filter(issue=>issue.severity!=='error');
  out.append(h('section',{class:`wb-dependency-summary ${blockers.length || !result.ok?'wb-dependency-blocked':'wb-dependency-passed'}`,role:'status'},
    h('strong',{},blockers.length?'当前范围有待处理的问题。':result.ok?'引用来源与规则检查通过。':'整个计划仍有待处理项，请查看完整检查。'),
    h('p',{},`${blockers.length} 项阻断 · ${reminders.length} 项提醒`)));
  const issueCard=issue=>h('article',{class:`dependency-card ${issue.severity}`},h('strong',{},issue.table || '生成配置'),h('p',{},issue.message),
    ...(issue.code==='missing_parent_source' && issue.source_table && m.schema.tables.some(t=>t.name===issue.source_table) && !m.selected(issue.source_table)?[button(`加入 ${issue.source_table}（${m.table(issue.source_table).count} 行）`,action(async()=>{
      m.toggleTable(issue.source_table,true);const stillCurrent=ticket();
      if(await check(false)){if(!stillCurrent())return;drawBody();if(out.isConnected)renderDependencies(out,locate,focus,onUpdate);onUpdate?.();}
    },'检查依赖'),{small:true})]:[]),
    ...(issue.table?[button(`定位 ${issue.column || issue.table}`,()=>{locate(issue.table);const table=m.schema.tables.find(t=>t.name===issue.table),column=table?.columns.find(c=>c.name===issue.column);if(column)openRule(table,column);},{small:true})]:[]));
  if(blockers.length)out.append(h('section',{class:'wb-dependency-issues','aria-label':'需先处理的问题'},h('h4',{},'需先处理的问题'),...blockers.map(issueCard)));
  if(reminders.length)out.append(h('section',{class:'wb-dependency-issues','aria-label':'提醒与说明'},h('h4',{},'提醒与说明'),...reminders.map(issueCard)));
  out.append(sources);
  const layers=(result.layers || []).map(names=>names.filter(name=>!focus || executable.has(name))).filter(names=>names.length);
  out.append(h('div',{class:'execution-heading'},h('h3',{},!result.ok?'依赖分组参考':focus?'本表相关生成顺序':'所选表生成顺序'),button('整个计划 ↗',action(showPlan),{plain:true,class:'text-button'})),
    h('ol',{class:'execution-sequence'},...layers.map((names,i)=>h('li',{},h('span',{class:'execution-step'},i+1),h('div',{class:'execution-group'},h('small',{},`第 ${i+1} 组 · ${names.length} 张表`),h('div',{class:'execution-tables'},...names.map(name=>button(name,()=>locate(name),{plain:true,class:'mono execution-table'}))))))),
    h('p',{class:'muted'},!result.ok?'尚未形成可执行计划；以下分组可能不包含循环依赖中的表。请先处理阻断项，再重新检查。':focus?'仅列本表及上游中已勾选的表；其他表在整个计划中查看。未勾选的来源使用已有数据。':'同组表示没有先后依赖；执行仍逐表进行。'));
  syncBusy();
}
async function showPlan() { return showDependencies(); }
async function showDependencies() {
  const current=modalTicket();
  if(!model().document.tables.length){
    const dialog=openedModal=modal('尚未选择生成表');
    dialog.body.append(h('p',{},'请在左侧勾选至少一张要生成数据的表，再检查规则与依赖。'));
    dialog.actions.append(button('关闭',dialog.close),button('选择生成表',()=>{
      if(!current()){dialog.close();return;}
      dialog.close();locateGenerationSelection();
    },{primary:true}));
    return;
  }
  if(!await check(false) || !current())return;
  const dialog=openedModal=modal('整个计划 · 依赖检查',{wide:true});
  const generate=button('生成数据',()=>{if(!model().check?.ok)return;dialog.close();action(summary)();},{primary:true,disabled:!model().check?.ok});
  renderDependencies(dialog.body,name=>{dialog.close();inspectorMode='dependencies';chooseTable(name,'graph');},null,()=>{generate.disabled=!model().check?.ok;});
  dialog.actions.append(button('关闭',dialog.close),generate);
}
function previewTables(m) {
  return m.schema.tables.map(item=>({...item,count:m.table(item.name).count,
    ruleSummaries:Object.fromEntries(item.columns.map(column=>{
      const {label,detail}=ruleDescription(item,column);return [column.name,{label,detail}];
    })),
    omittedColumns:Object.fromEntries(item.columns.flatMap(column=>{
      const info=ruleDescription(item,column);return info.allocated?[[column.name,info.label]]:[];
    }))}));
}
function drawTablePreview(table) {
  const current=ticket(),owner=session,m=model(),epoch=m.epoch,lifecycle=m.lifecycleVersion;
  const acceptsResult=()=>owner.model===m && m.epoch===epoch && m.lifecycleVersion===lifecycle;
  const container=h('section',{class:'wb-table-preview','aria-label':`${table.name} 预览数据`});content.append(container);
  const cached=previewResults.get(m)?.get(table.name);
  const returned=previewReturns.get(m);previewReturns.delete(m);
  const resume=returned?.table===table.name?returned.view:null;
  const initialResult=resume?.result || (cached?.epoch===m.epoch && cached.count===previewCount?cached.result:null);
  const component=openDataPreview({container,fixedScope:true,tables:previewTables(m),currentTable:table.name,
    selectedTables:m.document.tables.map(item=>item.name),initialCount:previewCount,initialResult,initialView:resume,initialStale:Boolean(resume?.stale),
    onColumnAction:(action,context)=>editPreviewColumn(owner,m,'current',action,context),
    isCurrent:()=>current() && m.view.page==='preview' && m.view.table===table.name,
    guard:task=>action(task,'预览当前表'),generate:async({count})=>{
      const result=await owner.previewTable(table.name,count);
      if(result && acceptsResult()){
        cachePreview(m,[table.name],count,result);
        // A user may leave and re-enter this table while the one shared request
        // is running. Publish into that current view without another request.
        if(root?.isConnected && session===owner && model()===m && tablePreview && tablePreview!==component && m.view.page==='preview' && m.view.table===table.name)drawBody();
      }
      return result;
    },
    onOptionsChange:({count})=>{previewCount=count;},
    onResult:(result,{count})=>{if(current()){cachePreview(m,[table.name],count,result);updateStatus();}},onError:error=>{if(current())notify(error.message,true);},
  });
  tablePreview=component;tablePreview.cached=Boolean(initialResult);
}
function cachePreview(m,names,count,result){
  const cache=previewResults.get(m) || new Map();previewResults.set(m,cache);
  for(const name of names)cache.set(name,{epoch:m.epoch,count,result});
}
function previewReturnHandler(owner,m,{scope,table,column,view:sourceView}) {
  const version=active,epoch=m.epoch,lifecycle=m.lifecycleVersion,schemaHash=m.schema.schema_hash;
  return ()=>{
    if(!root?.isConnected || version!==active || owner!==session || m!==model() || lifecycle!==m.lifecycleVersion || schemaHash!==m.schema.schema_hash)return;
    const view={...sourceView,stale:sourceView.stale || epoch!==m.epoch};
    if(scope==='selected')return refreshSamples(view);
    if(m.view.page!=='preview' || m.view.table!==table)return;
    previewReturns.set(m,{table,view});drawBody();
    [...content.querySelectorAll('[data-preview-column]')].find(item=>item.getAttribute('data-preview-column')===column && item.getAttribute('data-preview-entry')===(sourceView.columnAction || 'information'))?.focus();
  };
}
function editPreviewColumn(owner,m,scope,action,context) {
  if(owner!==session || m!==model() || !validNavigation())return;
  const table=m.schema.tables.find(item=>item.name===context.table),column=table?.columns.find(item=>item.name===context.column);
  if(!column)return;
  const origin={scope,...context};
  openRule(table,column,action==='information'?'information':'rule',{onReturn:previewReturnHandler(owner,m,origin),previewOrigin:origin});
}
async function refreshSamples(resume=null) {
  resume=resume?.result?resume:null;
  const current=modalTicket(),owner=session,m=model(),table=m.view.table,epoch=m.epoch,lifecycle=m.lifecycleVersion;
  const names=m.document.tables.map(item=>item.name);
  const preview=openDataPreview({tables:previewTables(m),currentTable:table,selectedTables:m.document.tables.map(item=>item.name),
    initialScope:'selected',fixedScope:true,initialCount:previewCount,isCurrent:current,
    initialResult:resume?.result,initialView:resume,initialStale:Boolean(resume?.stale),
    onColumnAction:(action,context)=>editPreviewColumn(owner,m,'selected',action,context),
    guard:task=>action(task,'预览已选表'),generate:async({count})=>{
      const result=await owner.check(true,count);
      if(result && owner.model===m && m.epoch===epoch && m.lifecycleVersion===lifecycle){
        cachePreview(m,names,count,result);
        if(!preview.dialog.el.isConnected && root?.isConnected && session===owner && model()===m && tablePreview && m.view.page==='preview' && names.includes(m.view.table))drawBody();
      }
      return result;
    },
    onOptionsChange:({count})=>{previewCount=count;},
    onResult:(result,{count})=>{if(current()){cachePreview(m,m.document.tables.map(item=>item.name),count,result);drawBody();notify(previewMessage(result,'已选表'),!result.ok);}},
    onError:error=>{if(current())notify(error.message,true);},
  });
  openedModal=preview.dialog;
  if(resume){[...preview.dialog.body.querySelectorAll('[data-preview-column]')].find(item=>item.getAttribute('data-preview-column')===resume.column && item.getAttribute('data-preview-entry')===(resume.columnAction || 'information'))?.focus();return;}
  await preview.refresh();
}

function previewMessage(result,scope) {
  if(!result.ok)return '样例有待处理项，请查看字段说明或依赖检查。';
  if(result.preview_complete===false)return '仅更新可预览的部分样例；完整关联样例需等待父表有可用记录。';
  return `${scope}样例已更新，数据库未写入。`;
}
function structureSnapshot() { const s = model().schema; return {format:'sqlseed-schema-graph', version: 1, label:s.target_label, title: s.target_label, nodes: s.nodes, edges: s.edges}; }
async function configSettings() {
  const current = modalTicket();
  const [providers, locales] = await Promise.all([get('/api/meta/providers'), get('/api/meta/locales')]);
  if (!current()) return;
  providerRequest++;providerMetadata=providers;updateProviderWarning();
  const draft = structuredClone(model().document), controls = [];
  const available = new Set(providers.available || []);
  const dialog = openedModal = modal('全局生成设置', {onClose: () => controls.forEach(c => c.destroy())});
  const guide=h('section',{class:'wb-provider-guide','aria-live':'polite','aria-label':'当前引擎特点'});
  const apply=button('应用设置', () => {
    if (!current()) { dialog.close(); return; }
    if (!available.has(draft.provider)) return;
    model().document = draft; model().touch(); dialog.close(); draw();
  }, {primary: true});
  function availabilityLabel(value) {
    if(providers.statuses?.[value]?.status==='import_error')return '加载异常';
    if (!available.has(value)) return value==='mimesis'?'未安装':'不可用';
    return value==='base'?'内置可用':'已安装';
  }
  function showGuide() {
    const description=providerGuide(draft.provider,draft.locale);
    const installed=available.has(draft.provider);
    const status=availabilityLabel(draft.provider)+(installed && draft.provider==='faker'?' · 随 sqlseed 安装':installed && draft.provider==='mimesis'?' · 可选依赖':'');
    apply.disabled=!installed;
    guide.replaceChildren(...[h('h3',{},description.title,h('small',{},status)),h('p',{},description.summary),
      !installed?h('p',{class:'wb-error'},providers.statuses?.[draft.provider]?.status==='import_error'?`${description.title} 已安装但加载异常，暂不能应用。`:draft.provider==='mimesis'?'当前环境未安装 Mimesis，暂不能应用。':'当前 Web 服务未提供此引擎，请检查安装环境。'):null,
      !installed && draft.provider==='mimesis'?h('p',{class:'wb-provider-example'},h('a',{href:'#/settings?section=plugins',onclick:dialog.close},'管理插件'),h('br'),h('small',{},providers.statuses?.mimesis?.status==='import_error'?'请在插件与版本中查看异常信息，处理后返回。':'在插件与版本中安装后，返回选择此引擎。')):null,
      h('p',{class:'wb-provider-limit'},description.limits[0] || ''),
      h('details',{},h('summary',{},'格式示例与详细说明'),
        h('ul',{},...description.features.map(feature=>h('li',{},feature))),
        h('div',{class:'wb-provider-example'},...description.examples.map(example=>h('p',{},h('span',{},`${example.label}：`),h('code',{},example.value)))),
        h('small',{class:'muted'},description.exampleNote),...description.limits.slice(1).map(limit=>h('p',{},limit)),
        ...description.sources.map(source=>h('a',{href:source.url,target:'_blank',rel:'noopener noreferrer'},source.label)))].filter(Boolean));
  }
  // Unavailable engines may be inspected locally, but cannot be applied.
  // Keep the document's engine in the list so reopening never implies a fallback.
  const choices=[...new Set(['base','faker','mimesis',...available,draft.provider].filter(Boolean))];
  const provider = createDropdown({label:'数据生成引擎',options: choices.map(value => {
    const description=providerGuide(value,draft.locale);
    return {value,label:`${description.title} · ${description.choice} · ${availabilityLabel(value)}`};
  }), value: draft.provider,
    onChange: value => { draft.provider = value; showGuide(); }});
  const locale = createDropdown({label:'数据语言与地区',options: locales.locales.map(item => ({value: item.code, label: item.label})), value: draft.locale,
    onChange: value => { draft.locale = value; showGuide(); }});
  controls.push(provider, locale);
  dialog.body.append(h('p', {class: 'muted'}, '应用于当前配置中的所有表；已有表级、字段级覆盖保留，检查时会提示不兼容的引擎设置。'),
    h('label', {class: 'control'}, '数据生成引擎', provider.el),guide,h('label', {class: 'control'}, '数据语言与地区', locale.el),h('p',{class:'wb-settings-note'},'影响生成内容的语言与格式，不改变界面语言。'));
  showGuide();
  dialog.actions.append(button('取消', dialog.close), apply);
}

async function save() {
  const current=ticket();
  if(!session.name.trim())throw new Error('请填写配置名称');
  const saved=await session.save();if(current()){updateStatus();notify(`配置已保存 · v${saved.revision}`);}return saved;
}
async function check(preview=false) {
  const current=ticket();
  notify(preview?'正在生成样例，不写入数据库…':'正在检查结构、规则与依赖…');
  const result=await session.check(preview);
  if(!current())return null;
  if(!result){notify('配置已变化，旧的检查结果已丢弃，请重新检查。');return null;}
  notify(result.ok?(preview?'样例已更新；数据库未写入。':'依赖与规则检查通过。'):`发现 ${result.issues?.length || 1} 个待处理项，请查看依赖检查。`,!result.ok);updateStatus();return result;
}
async function refreshSchema() {
  if(!validNavigation())return;
  const current=session,version=active;
  const schema=await readSchema(current.connId);
  if(version!==active)return;
  const changedSchema=schema.schema_hash!==model().schema.schema_hash;
  model().schema=schema;model().touch();drawBody();
  notify(changedSchema?'数据库结构已变化，请检查保留的规则后重新保存。':'已重新读取结构与行数。');
}
async function openDrafts() {
  const current=modalTicket();
  const response=await get(`/api/workbench/drafts?conn_id=${encodeURIComponent(session.connId)}`);
  if(!current())return;
  const drafts=Array.isArray(response)?response:response.drafts || [];
  const dialog=openedModal=modal('已保存的配置');
  let opening=false;
  dialog.body.append(h('p',{class:'wb-muted'},'仅列出当前数据库的配置。打开前会保存当前未保存的修改。'));
  if(!drafts.length)dialog.body.append(h('p',{},'尚未保存配置。'));
  for(const draft of drafts)dialog.body.append(button('',action(async()=>{
    if(opening)return;opening=true;
    const stillCurrent=ticket();
    try {
    if(model().dirty && (model().document.tables.length || Object.keys(model().view.tableDrafts).length))await save();
    if(!stillCurrent() || !dialog.body.isConnected)return;
    const full=await get(`/api/workbench/drafts/${encodeURIComponent(draft.id)}`);
    if(!stillCurrent() || !dialog.body.isConnected)return;
    session.open(full);dialog.close();draw();
    } finally {opening=false;}
  }),{class:'wb-draft-card'}));
  dialog.actions.append(button('配置管理',()=>{dialog.close();location.hash='#/configs';},{glyph:'settings'}));
  [...dialog.body.querySelectorAll('.wb-draft-card')].forEach((card,i)=>card.append(h('strong',{},drafts[i].name),h('small',{},`v${drafts[i].revision} · ${new Date(drafts[i].updated_at * 1000).toLocaleString('zh-CN', {hour12:false})}`)));
}
async function configDocument() {
  const stillCurrent=modalTicket(), current=session;
  const exported=await send('/api/workbench/export',{conn_id:current.connId,document:model().payload(session.name).document});
  if(!stillCurrent())return;
  let formatControl;
  const dialog=openedModal=modal('编辑 YAML',{wide:true,onClose:()=>formatControl?.destroy()});
  const text=h('textarea',{class:'wb-code',rows:20,spellcheck:false,'aria-label':'YAML 或 JSON 配置',value:exported.yaml});
  const error=h('p',{class:'wb-error',role:'alert'});
  let textVersion=0,requestVersion=0;
  text.addEventListener('input',()=>{textVersion++;});
  dialog.body.append(h('p',{class:'muted'},'默认使用 YAML，也可读取或粘贴 JSON。应用后更新生成配置；写入数据库仍需单独确认。'),text,error);
  if(exported.credentials_omitted)dialog.body.append(h('p',{class:'muted'},'导出内容省略连接凭据，单独执行时需补充连接信息。'));
  const file=h('input',{type:'file',accept:'.yaml,.yml,.json',hidden:true,onchange:async e=>{
    const selected=e.target.files?.[0];if(!selected)return;
    if(selected.size>2*1024*1024){error.textContent='配置文件不得超过 2 MiB';return;}
    const version=textVersion,value=await selected.text();
    if(dialog.body.isConnected && version===textVersion){text.value=value;textVersion++;}
  }});
  async function parseVisible() {
    const applyCurrent=ticket(), raw=text.value, inputVersion=textVersion, request=++requestVersion;
    const parsed=await send('/api/workbench/parse',{conn_id:current.connId,text:raw});
    if(!applyCurrent() || !dialog.body.isConnected || request!==requestVersion)return null;
    if(raw!==text.value || inputVersion!==textVersion){error.textContent='文本已变化，请重新应用或下载当前内容。';return null;}
    return {document:parsed.document,current:()=>applyCurrent() && dialog.body.isConnected && request===requestVersion && raw===text.value && inputVersion===textVersion};
  }
  async function downloadCurrent(format) {
    try {
      const parsed=await parseVisible();if(!parsed)return;
      const output=await send('/api/workbench/export',{conn_id:current.connId,document:parsed.document});
      if(!parsed.current())return;
      download(`sqlseed.${format}`,format==='json'?typeof output.json==='string'?output.json:JSON.stringify(output.json,null,2):output.yaml,format==='json'?'application/json':'application/yaml');
    }catch(e){if(dialog.body.isConnected)error.textContent=e.message;}
  }
  let format='yaml';
  formatControl=createDropdown({label:'下载格式',value:format,options:[{value:'yaml',label:'YAML'},{value:'json',label:'JSON'}],onChange:value=>{format=value;}});
  const toolbar=h('div',{class:'wb-document-toolbar',role:'group','aria-label':'配置文件工具'},file,button('读取文件',()=>file.click(),{glyph:'upload'}),h('label',{class:'wb-document-format'},'下载格式',formatControl.el),button('下载配置',action(()=>downloadCurrent(format),'导出配置'),{glyph:'download'}));
  dialog.body.insertBefore(toolbar,text);
  dialog.actions.append(button('取消',dialog.close),button('应用配置',action(async()=>{
    try { const parsed=await parseVisible();if(!parsed)return;current.model.replaceDocument(parsed.document);dialog.close();draw();notify('配置已应用，请检查并保存。'); }
    catch(e){if(dialog.body.isConnected)error.textContent=e.message;}
  },'检查配置文档'),{primary:true}));
}
async function importStructure() {
  const current = modalTicket();
  const dialog = openedModal = modal('导入关系图 JSON', {wide:true});
  const example = {format:'sqlseed-schema-graph',version:1,title:'数据库关系图',nodes:[{id:'users'},{id:'orders'}],
    edges:[{id:'orders_user_id',source:'users',target:'orders',sourceColumns:['id'],targetColumns:['user_id'],nullable:false}]};
  const text = h('textarea',{class:'wb-code',rows:10,'aria-label':'关系图 JSON',placeholder:'粘贴关系图 JSON，或选择文件'});
  const error = h('p',{class:'wb-error',role:'alert'});
  const file = h('input',{type:'file',accept:'.json',hidden:true,onchange:async e=>{
    const selected=e.target.files?.[0];if(!selected)return;
    if(selected.size>1024*1024){error.textContent='关系图文件不得超过 1 MiB';return;}
    const value=await selected.text();if(dialog.body.isConnected)text.value=value;
  }});
  dialog.body.append(h('p',{},'导入后只读浏览表与外键关系，不会创建或修改数据库。生成配置继续绑定当前数据库。'),
    h('details',{},h('summary',{},'格式说明'),h('p',{},'nodes 是表列表；edges 中 source 为父表、target 为子表，sourceColumns 和 targetColumns 按位置一一对应。复合外键放在同一条边内。'),h('pre',{class:'wb-import-help'},JSON.stringify(example,null,2))),text,error);
  dialog.actions.append(file,button('下载格式模板',()=>download('sqlseed-schema-template.json',JSON.stringify(example,null,2))),
    button('选择 JSON 文件',()=>file.click()),button('导入关系图',()=>{
      try {
        if(!current()){dialog.close();return;}
        if(new Blob([text.value]).size>1024*1024)throw new Error('关系图文件不得超过 1 MiB');
        const schema=JSON.parse(text.value);
        if((schema.version!==undefined && schema.version!==1) || (schema.format!==undefined && schema.format!=='sqlseed-schema-graph'))throw new Error('不支持此关系图格式或版本，请参考格式模板。');
        if(!Array.isArray(schema.nodes) || !Array.isArray(schema.edges) || !schema.nodes.length || schema.nodes.length>200 || schema.edges.length>1000)throw new Error('需要 nodes 和 edges，支持 1—200 张表 / 最多 1000 条关系。');
        const ids=new Set();
        for(const node of schema.nodes){if(typeof node?.id!=='string' || !node.id.trim() || ids.has(node.id))throw new Error('每张表需要非空且唯一的 id。');ids.add(node.id);}
        const edgeIds=new Set();
        schema.edges=schema.edges.map((edge,i)=>{
          if(!edge || !ids.has(edge.source) || !ids.has(edge.target))throw new Error('关系的 source / target 必须对应 nodes 中的表 id。');
          const sourceColumns=edge.sourceColumns ?? [],targetColumns=edge.targetColumns ?? [];
          if(!Array.isArray(sourceColumns)||!Array.isArray(targetColumns)||sourceColumns.length!==targetColumns.length||[...sourceColumns,...targetColumns].some(col=>typeof col!=='string'||!col.trim()))throw new Error('外键列必须是长度相同的字符串数组。');
          const id=edge.id || `relation-${i+1}`;
          if(typeof id!=='string'||edgeIds.has(id))throw new Error('每条关系需要唯一的 id。');edgeIds.add(id);
          return {...edge,id,sourceColumns,targetColumns};
        });
        schema.title=typeof schema.title==='string'?schema.title:typeof schema.label==='string'?schema.label:'导入的关系图';
        importedStructures.set(session.connId,schema); model().view.imported=true;dialog.close();drawBody();
      }catch(e){error.textContent=e.message;}
    },{primary:true}));
}
function drawImportedStructure(schema) {
  const section=h('section',{class:'panel-content database-graph wb-imported-structure'});
  const inspect=h('div',{class:'wb-edge-mapping',hidden:true});
  section.append(h('div',{class:'wb-imported-note'},h('div',{},h('h3',{},schema.title),h('span',{},'只读关系图 · 与当前生成配置分开浏览')),
    button('返回当前数据库',()=>{model().view.imported=false;drawBody();},{small:true})));
  graphOwner=null;
  graph=createSchemaGraph({schema:{...schema,tables:[]},mode:'all',onSelect:()=>{},onEdge:edge=>{
    inspect.hidden=false;inspect.replaceChildren(h('strong',{},`${edge.source} → ${edge.target}`),...edge.sourceColumns.map((column,i)=>h('code',{},`${column} → ${edge.targetColumns[i]}`)));
  }});
  if(graph.toolbar)section.append(graph.toolbar);
  section.append(graph.el,inspect);content.append(section);
}
async function summary() {
  const stillCurrent=modalTicket();
  if(!model().document.tables.length)throw new Error('请先勾选要生成的表');
  if(model().dirty)await save();
  if(!stillCurrent())return;
  const result=await check(false);
  if(!result || !stillCurrent())return;
  const current=session, m=model(), epoch=m.epoch, version=active;
  let sequence=0, plan=null, busy=false, planning=false, execution={mode:'append',reset_identity:false};
  const dialog=openedModal=modal('确认生成数据', {wide:true,onClose:()=>{sequence++;}});
  const isCurrent=()=>version===active && current===session && m===model() && m.epoch===epoch && dialog.body.isConnected;
  const planInfo=h('div',{class:'wb-execution-plan','aria-live':'polite'});
  const reset=h('input',{type:'checkbox',checked:false,disabled:true,'aria-label':'重置自增计数',onchange:()=>{if(planning || busy)return;execution.reset_identity=reset.checked;return inspectExecution();}});
  const append=h('input',{type:'radio',name:'execution-mode',value:'append',checked:true,'aria-label':'追加数据',onchange:()=>{if(busy)return;execution={mode:'append',reset_identity:false};reset.checked=false;reset.disabled=true;return inspectExecution();}});
  const replace=h('input',{type:'radio',name:'execution-mode',value:'replace_selected',disabled:m.schema.dialect!=='sqlite','aria-label':'清空所选表后生成',onchange:()=>{if(planning || busy)return;execution.mode='replace_selected';reset.disabled=false;return inspectExecution();}});
  dialog.body.append(h('section',{class:'wb-write-target','aria-label':'写入目标'},
    h('div',{},h('strong',{},'写入目标'),h('span',{class:'wb-muted'},m.schema.dialect==='sqlite'?'SQLite':m.schema.dialect==='postgresql'?'PostgreSQL':m.schema.dialect)),
    h('p',{class:'mono'},m.schema.target_label),
    h('small',{class:'wb-muted'},m.schema.dialect==='sqlite'?'当前连接的数据库位置；由运行 Web 的设备访问。':'当前连接的数据库地址；连接凭据已隐藏。')),
    h('p',{class:'wb-muted'},`${current.name} · v${m.saved.revision}`),
    h('fieldset',{class:'wb-write-strategy'},h('legend',{},'已有数据处理'),
      h('label',{},append,h('span',{},h('strong',{},'追加数据'),h('small',{},'保留已有记录，由数据库继续分配 ID。'))),
      h('label',{},replace,h('span',{},h('strong',{},'清空所选表后生成'),h('small',{},'删除下列所选表的现有记录，再生成新数据。'))),
      ...(m.schema.dialect!=='sqlite'?[h('p',{class:'muted'},'PostgreSQL 暂未开放清空模式；当前仅支持追加数据。')]:[]),
      h('label',{class:'wb-reset-identity'},reset,h('span',{},'重置自增计数',h('small',{},'仅清空后可选。SQLite AUTOINCREMENT 从 1 重新分配；普通整数主键在空表中通常也从 1 开始。')))),
    h('div',{class:'wb-summary-total'},h('strong',{},m.document.tables.reduce((sum,t)=>sum+t.count,0).toLocaleString()),' 行本次生成 / ',m.document.tables.length,' 张表'),
    h('ol',{class:'wb-summary-plan'},...(result.order || []).map(name=>h('li',{},button(name,()=>{dialog.close();inspectorMode='dependencies';chooseTable(name,'graph');},{plain:true,class:'mono execution-table'}),h('span',{},`${m.table(name).count} 行`)))),
    ...(result.issues || []).map(issue=>h('p',{class:issue.severity==='error'?'wb-error':'wb-muted'},`${issue.table || ''} ${issue.message}`)),planInfo);
  const submit=button('写入数据库',async()=>{
    if(!isCurrent() || busy || planning || !m.canRun() || (execution.mode==='replace_selected' && !plan?.ok))return;
    busy=true;submit.disabled=true;setStrategyBusy(true);
    try{const run=await current.run(execution.mode==='append'?undefined:execution,plan?.plan_hash);if(isCurrent()){dialog.close();location.hash=`#/runs?id=${encodeURIComponent(run.id)}`;}}
    catch(error){if(isCurrent()){planInfo.append(h('p',{class:'wb-error',role:'alert'},error.message));busy=false;setStrategyBusy(false);submit.disabled=execution.mode==='replace_selected';if(execution.mode==='replace_selected'){plan=null;planInfo.append(button('重新核对计划',inspectExecution));}}}
  },{primary:true,disabled:!m.canRun()});
  dialog.actions.append(button('返回调整',dialog.close),submit);
  function appendPlan() {
    planInfo.replaceChildren(h('p',{class:'wb-muted'},'向现有数据追加，不清空表；自动主键由数据库继续分配。按此顺序逐表写入。若中途失败，后续表停止；已经提交的数据保留，实际数量可在运行记录中查看。'));
  }
  function setStrategyBusy(value) {
    append.disabled=busy;replace.disabled=value || m.schema.dialect!=='sqlite';
    reset.disabled=value || execution.mode!=='replace_selected' || !plan?.reset_identity_supported;
    planInfo.setAttribute('aria-busy',String(value));
  }
  async function inspectExecution() {
    if(busy || (planning && execution.mode!=='append'))return;
    const request=++sequence;plan=null;submit.disabled=true;
    if(execution.mode==='append'){appendPlan();submit.textContent='写入数据库';submit.disabled=planning || !m.canRun();setStrategyBusy(planning);return;}
    submit.textContent='清空并生成';planInfo.replaceChildren(h('p',{},'正在核对清空范围、外键与事务能力…'));
    planning=true;setStrategyBusy(true);
    try {
      const response=await current.executionPlan({...execution});
      if(!isCurrent() || request!==sequence)return;
      plan=response;
      const tables=plan.clear_tables || [];
      planInfo.replaceChildren(h('h3',{},`将清空 ${tables.length} 张表 · ${tables.reduce((sum,t)=>sum+t.row_count,0).toLocaleString()} 行现有记录`),
        h('ul',{},...tables.map(table=>h('li',{},`${table.name}：${table.row_count} 行`))),
        ...((plan.issues || []).map(issue=>h('p',{class:issue.severity==='error'?'wb-error':'muted',role:issue.severity==='error'?'alert':'status'},issue.message))),
        h('p',{},plan.atomic?'清空与本次生成在同一事务中完成。失败将回滚本次操作，保留原有数据。':'此模式不具备整体回滚能力。'),
        h('p',{class:'muted'},execution.reset_identity?'已请求重置所选表的自增计数。':'保留 AUTOINCREMENT 计数；普通整数主键按数据库空表规则分配。'));
      submit.disabled=!plan.ok || !plan.atomic || !m.canRun();reset.disabled=!plan.reset_identity_supported;
    } catch(error) {if(isCurrent() && request===sequence)planInfo.replaceChildren(h('p',{class:'wb-error',role:'alert'},error.message));}
    finally {planning=false;if(isCurrent()){setStrategyBusy(false);if(execution.mode==='append')submit.disabled=!m.canRun();}}
  }
  appendPlan();
}
