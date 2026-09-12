import { WorkbenchDocument } from './model.js';
function validatePreviewCount(count) {
  if (!Number.isInteger(count) || count < 1 || count > 100) {
    throw new Error('预览数量必须是 1–100 之间的整数');
  }
}

// Transport injected so race and snapshot tests exercise real session behavior.
export class WorkbenchSession {
  constructor(connId, schema, request) {
    this.connId = connId;
    this.model = new WorkbenchDocument(schema);
    this.request = request;
    this.saving = false;
    this.submitting = false;
    this.previewSequence = 0;
    this.name = '数据生成配置';
  }
  async save(name = this.name) {
    if (this.saving) {
      throw new Error('正在保存，请稍候');
    }
    const model = this.model,
      epoch = model.epoch,
      lifecycle = model.lifecycleVersion;
    const payload = {
      ...model.payload(name),
      conn_id: this.connId
    };
    const previous = model.saved;
    if (previous) {
      payload.revision = previous.revision;
    }
    this.saving = true;
    try {
      const saved = await this.request(`/api/workbench/drafts${previous ? "/" + encodeURIComponent(previous.id) : ''}`, payload, previous ? 'PUT' : 'POST');
      if (lifecycle !== model.lifecycleVersion) {
        throw new Error('保存期间此配置已被删除或重命名，请核对当前状态后重试');
      }
      model.markSaved(saved, epoch);
      if (this.model === model && model.epoch === epoch) {
        this.name = name;
      }
      return saved;
    } finally {
      this.saving = false;
    }
  }
  async check(preview = false, count = 3) {
    validatePreviewCount(count);
    const model = this.model,
      epoch = model.epoch;
    const payload = {
      conn_id: this.connId,
      document: model.payload(this.name).document,
      schema_hash: model.schema.schema_hash,
      count
    };
    const sequence = preview ? ++this.previewSequence : null;
    const result = await this.request(`/api/workbench/${preview ? 'preview' : 'check'}`, payload, 'POST');
    if (preview && sequence !== this.previewSequence) {
      return null;
    }
    return this.model === model && model.acceptCheck(result, epoch, preview) ? result : null;
  }
  async previewTable(tableName, count = 3) {
    validatePreviewCount(count);
    const model = this.model,
      epoch = model.epoch;
    if (!model.schema.tables.some(table => table.name === tableName)) {
      throw new Error(`数据库中不存在表：${tableName}`);
    }
    const document = model.payload(this.name).document;
    // Follow the actual generation prerequisites. An unselected parent is read
    // from existing rows, so its ancestors are not part of this preview plan.
    // Keep the full root settings/associations intact for backend validation.
    const selected = new Set(document.tables.map(table => table.name));
    const needed = new Set([tableName]);
    const edges = [...(model.schema.edges || [])];
    for (const association of document.associations || []) {
      for (const target of association.target_tables || []) {
        edges.push({
          source: association.source_table,
          target
        });
      }
    }
    for (const name of needed) {
      for (const edge of edges) {
        if (edge.target === name && selected.has(edge.source)) {
          needed.add(edge.source);
        }
      }
    }
    document.tables = document.tables.filter(table => needed.has(table.name));
    if (!document.tables.some(table => table.name === tableName)) {
      document.tables.push(structuredClone(model.table(tableName)));
    }
    const payload = {
      conn_id: this.connId,
      document,
      schema_hash: model.schema.schema_hash,
      count
    };
    const sequence = ++this.previewSequence;
    const result = await this.request('/api/workbench/preview', payload, 'POST');
    if (sequence !== this.previewSequence || this.model !== model || epoch !== model.epoch || model.errors.size) {
      return null;
    }
    const refreshed = new Set(document.tables.map(table => table.name));
    const samples = Object.fromEntries(Object.entries(model.samples).filter(([name]) => !refreshed.has(name)));
    const issues = model.previewIssues.filter(issue => issue.table && !refreshed.has(issue.table));
    return model.acceptPreview({
      ...result,
      samples: {
        ...samples,
        ...result.samples
      },
      issues: [...issues, ...(result.issues || [])]
    }, epoch) ? result : null;
  }
  open(draft) {
    if (draft.target_key !== this.model.schema.target_key) {
      throw new Error('此配置属于另一数据库，请先连接对应数据库');
    }
    const model = new WorkbenchDocument(this.model.schema, draft.document);
    model.restoreView(draft.view_state);
    model.markSaved(draft, draft.schema_hash === model.schema.schema_hash ? model.epoch : -1);
    this.model = model;
    this.name = draft.name;
  }
  async executionPlan(execution) {
    const model = this.model;
    if (!model.saved || model.dirty || !model.check) {
      throw new Error('请先保存并检查当前配置');
    }
    return this.request('/api/workbench/execution-plan', {
      conn_id: this.connId,
      draft_id: model.saved.id,
      revision: model.saved.revision,
      schema_hash: model.schema.schema_hash,
      config_hash: model.check.config_hash,
      execution
    }, 'POST');
  }
  async run(execution, planHash) {
    if (this.submitting) {
      throw new Error('运行正在提交，请稍候');
    }
    if (!this.model.canRun()) {
      throw new Error('请先保存当前配置并完成依赖检查');
    }
    const model = this.model;
    const payload = {
      conn_id: this.connId,
      draft_id: model.saved.id,
      revision: model.saved.revision,
      schema_hash: model.schema.schema_hash,
      config_hash: model.check.config_hash
    };
    if (execution) {
      payload.execution = structuredClone(execution);
    }
    if (planHash) {
      payload.plan_hash = planHash;
    }
    this.submitting = true;
    try {
      return await this.request('/api/workbench/runs', payload, 'POST');
    } finally {
      this.submitting = false;
    }
  }
}
