// 唯一可执行文档；视图和未勾选表的编辑草稿单独持久化。
const copy = value => structuredClone(value);

export class WorkbenchDocument {
  constructor(schema, document) {
    this.schema = schema;
    this.document = copy(document || {provider:schema.provider, locale:schema.locale, tables:[]});
    this.view = {table:schema.tables[0]?.name || '', page:'fields', graphMode:'all', tableDrafts:{}};
    this.errors = new Map();
    this.epoch = 0;
    this.savedEpoch = -1;
    this.lifecycleVersion = 0;
    this.saved = null;
    this.check = null;
    this.samples = {};
    this.previewIssues = [];
  }
  get dirty() { return this.epoch !== this.savedEpoch; }
  touch() { this.epoch++; this.check = null; this.samples = {}; this.previewIssues = []; }
  restoreView(view) {
    this.view = {...this.view, ...copy(view || {})};
    if (!this.schema.tables.some(t=>t.name===this.view.table)) this.view.table=this.schema.tables[0]?.name || '';
  }
  selectTable(name, page='fields') {
    this.view.table = name;
    this.view.page = page;
    if (page==='graph') this.view.graphMode='paths';
  }
  table(name) {
    return this.document.tables.find(t=>t.name===name)
      || this.view.tableDrafts[name] || {name,count:100,columns:[]};
  }
  selected(name) { return this.document.tables.some(t=>t.name===name); }
  putTable(table) {
    const index=this.document.tables.findIndex(t=>t.name===table.name);
    if(index>=0) this.document.tables[index]=copy(table);
    else this.view.tableDrafts[table.name]=copy(table);
    this.touch();
  }
  toggleTable(name,selected) {
    if(this.selected(name)===selected) return;
    const table=copy(this.table(name));
    this.document.tables=this.document.tables.filter(t=>t.name!==name);
    if(selected) { this.document.tables.push(table); delete this.view.tableDrafts[name]; }
    else this.view.tableDrafts[name]=table;
    this.touch();
  }
  setCount(name,text) {
    const key=`count:${name}`;
    if(!/^\d+$/.test(String(text)) || !Number.isSafeInteger(Number(text)) || Number(text)<1) {
      this.setError(key,'生成数量必须是大于 0 的整数'); return false;
    }
    this.errors.delete(key);
    this.putTable({...this.table(name),count:Number(text)});
    return true;
  }
  setError(key,error) {
    if(error) this.errors.set(key,error); else this.errors.delete(key);
    this.touch();
  }
  setColumn(tableName,column,config) {
    const table=copy(this.table(tableName));
    table.columns=(table.columns || []).filter(c=>c.name!==column);
    if(config) table.columns.push({...copy(config),name:column});
    this.errors.delete(`column:${tableName}.${column}`);
    this.putTable(table);
  }
  applyPatches(patches) {
    const tables=copy(this.document.tables), drafts=copy(this.view.tableDrafts), seen=new Set();
    for(const patch of patches) {
      const key=`${patch.table}.${patch.column}`;
      if(seen.has(key) || !this.schema.tables.find(t=>t.name===patch.table)?.columns?.some(c=>c.name===patch.column))
        throw new Error('建议字段已失效或重复，请重新分析');
      seen.add(key);
      const index=tables.findIndex(t=>t.name===patch.table);
      const table=copy(index>=0?tables[index]:drafts[patch.table] || this.table(patch.table));
      table.columns=(table.columns || []).filter(c=>c.name!==patch.column);
      if(patch.after)table.columns.push({...copy(patch.after),name:patch.column});
      if(index>=0)tables[index]=table;else drafts[patch.table]=table;
    }
    this.document.tables=tables;this.view.tableDrafts=drafts;
    for(const key of seen)this.errors.delete(`column:${key}`);
    if(patches.length)this.touch();
  }
  rule(tableName,column) {
    const override=this.table(tableName).columns?.find(c=>c.name===column);
    if(override) return copy(override);
    const inferred=copy(this.check?.effective_rules?.[tableName]?.[column]
      || this.schema.tables.find(t=>t.name===tableName)?.mapping?.[column] || {});
    // Reflected/resolved specs may contain sampled parent values. They are
    // runtime evidence, not editable generator parameters or saved rules.
    if(inferred.params) inferred.params=Object.fromEntries(Object.entries(inferred.params).filter(([key])=>!key.startsWith('_')));
    return inferred;
  }
  replaceDocument(document) {
    if('url' in document || 'db_path' in document) throw new Error('连接由当前工作台绑定，文档不能包含连接地址');
    this.document=copy(document);
    this.view.tableDrafts={};
    this.errors.clear();
    this.touch();
  }
  payload(name) {
    if(this.errors.size) throw new Error([...this.errors.values()].join('；'));
    return {name,document:copy(this.document),schema_hash:this.schema.schema_hash,view_state:copy(this.view)};
  }
  markSaved(saved,epoch) { this.saved=copy(saved); this.savedEpoch=epoch; }
  // Keep legacy direct callers' full-result behavior; session callers explicitly
  // distinguish validation from preview, including empty or failed previews.
  acceptCheck(result,epoch,preview=true) {
    if(epoch!==this.epoch || this.errors.size) return false;
    this.check={...copy(result),epoch};
    if(preview) this.acceptPreview(result,epoch);
    return true;
  }
  acceptPreview(result,epoch) {
    if(epoch!==this.epoch || this.errors.size) return false;
    this.samples=copy(result.samples || {});
    this.previewIssues=copy(result.issues || []);
    return true;
  }
  canRun() {
    return !!(this.saved && !this.dirty && !this.errors.size && this.check?.ok && this.check.epoch===this.epoch);
  }
}
