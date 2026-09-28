import {tr} from '../i18n.js';
import '../i18n/messages/assistant.js';
// Presentation policy mirrors workbench_ai_relations.locked_column targets.
// Explicit/effective rules take precedence over schema mappings. The server
// validates the actual schema and complete candidate before returning patches.
const populated = value => {
  if (Array.isArray(value)) {
    return value.length > 0;
  } else if (value && typeof value === 'object') {
    return Object.keys(value).length > 0;
  } else {
    return Boolean(value);
  }
};
export function fieldAIEligibility(table, column, rule) {
  const denied = (code, reason) => ({
    eligible: false,
    code,
    reason
  });
  if (!table || !column?.name) return denied('unavailable', tr("assistant.protected.schema"));
  if (column.is_autoincrement) return denied('database_generated', tr("assistant.protected.auto"));
  if (column.is_primary_key || table.primary_key?.includes(column.name)) return denied('primary_key', tr("assistant.protected.primary"));
  if (table.foreign_keys?.some(key => key.columns?.includes(column.name))) return denied('foreign_key', tr("assistant.protected.foreign"));
  if (column.is_computed) return denied('computed', tr("assistant.protected.computed"));
  if (populated(rule?.derive_from) || populated(rule?.expression)) return denied('derived', tr("assistant.protected.derived"));
  if (['faker_method', 'mimesis_method', 'native_faker_method', 'native_mimesis_method', 'native_params'].some(key => populated(rule?.[key]))) return denied('native', tr("assistant.protected.native"));
  const effective = rule?.generator || rule?.generator_name || table.mapping?.[column.name]?.generator_name;
  if (column.default !== null && column.default !== undefined && (!effective || effective === 'skip' || effective.startsWith('__'))) return denied('database_default', tr("assistant.protected.default"));
  return {
    eligible: true,
    code: 'editable',
    reason: ''
  };
}
