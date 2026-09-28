import {tr} from '../i18n.js';
import '../i18n/messages/flow.js';
// Read-only presentation facts. Execution authorization always comes from a
// fresh server execution-plan after the user has saved an explicit scope.
function compareTableNames(left, right) {
  // Preserve the existing UTF-16 order independently of the browser locale.
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

export function clearRecoveryState(model, context) {
  const current = context.epoch === model.epoch && context.lifecycle === model.lifecycleVersion;
  const state = current ? context.state : 'pending';
  const errors = (context.issues || []).filter(issue => issue.severity === 'error');
  const externalCodes = new Set(['external_incoming_fk', 'external_incoming_association']);
  const externalTables = [...new Set(errors.filter(issue => externalCodes.has(issue.code) && issue.table).map(issue => issue.table))].sort(compareTableNames);
  const otherIssues = errors.filter(issue => !externalCodes.has(issue.code) || !issue.table);
  const count = externalTables.length + otherIssues.length;
  const rulesPassed = model.check?.ok && model.check.epoch === model.epoch && !model.errors.size;
  const rules = rulesPassed ? tr("flow.clear.rulesPassed") : tr("flow.clear.rulesPending");
  const status = state === 'checking' ? tr("flow.clear.checking", {rules: rules})
    : state === 'ok' ? tr("flow.clear.reviewed", {rules: rules})
    : state === 'reviewed' ? tr("flow.clear.recheckBeforeWrite", {rules: rules})
    : state === 'blocked' ? tr("flow.clear.issues", {rules: rules, count: count || 1})
    : tr("flow.clear.pending", {rules: rules});
  return {state, current, rulesPassed, externalTables, otherIssues, count, status};
}

export function clearScopeCandidate(model) {
  const document = model.payload('').document;
  const tables = new Map(model.schema.tables.map(table => [table.name, table]));
  const selected = new Set(document.tables.map(table => table.name));
  const original = [...selected], unresolved = new Set();
  const edges = [...(model.schema.edges || [])];
  for (const association of document.associations || []) {
    for (const target of association.target_tables || []) edges.push({source:association.source_table, target});
  }
  // Clearing a parent affects its incoming child references. Follow children,
  // never add unselected ancestors merely because generation reads their rows.
  for (const source of selected) {
    for (const edge of edges) {
      if (edge.source !== source || selected.has(edge.target)) continue;
      if (!tables.has(edge.target)) { unresolved.add(edge.target); continue; }
      selected.add(edge.target);
    }
  }
  const added = [...selected].filter(name => !original.includes(name)).sort(compareTableNames).map(name => {
    const config = structuredClone(model.table(name));
    document.tables.push(config);
    return {name, count:config.count, rowCount:tables.get(name).row_count};
  });
  return {document, original, added, unresolved:[...unresolved], total:selected.size};
}
