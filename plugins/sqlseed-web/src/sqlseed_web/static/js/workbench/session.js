import {tr, UserFacingError, t} from '../i18n.js';
import '../i18n/messages/flow.js';
import { WorkbenchDocument } from './model.js';
function validatePreviewCount(count) {
  if (!Number.isInteger(count) || count < 1 || count > 100) {
    throw new UserFacingError(tr("flow.preview.count"));
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
    this.name = t("flow.document.defaultName");
  }
  async save(name = this.name) {
    if (this.saving) {
      throw new UserFacingError(tr("flow.save.busy"));
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
        throw new UserFacingError(tr("flow.save.changed"));
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
      throw new UserFacingError(tr("flow.table.missing", {table: tableName}));
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
      throw new UserFacingError(tr("flow.document.wrongDatabase"));
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
      throw new UserFacingError(tr("flow.document.saveAndCheck"));
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
      throw new UserFacingError(tr("flow.run.submitting"));
    }
    if (!this.model.canRun()) {
      throw new UserFacingError(tr("flow.run.saveAndCheck"));
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
