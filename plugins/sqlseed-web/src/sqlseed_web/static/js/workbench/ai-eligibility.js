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
  if (!table || !column?.name) return denied('unavailable', '字段结构不可用，请刷新结构后再分析。');
  if (column.is_autoincrement) return denied('database_generated', '由数据库自动分配，AI 不修改该字段。');
  if (column.is_primary_key || table.primary_key?.includes(column.name)) return denied('primary_key', '主键由现有规则和数据库约束管理，AI 保持原样。');
  if (table.foreign_keys?.some(key => key.columns?.includes(column.name))) return denied('foreign_key', '外键从关联表取值，AI 保持引用关系。');
  if (column.is_computed) return denied('computed', '由数据库表达式计算，AI 不修改该字段。');
  if (populated(rule?.derive_from) || populated(rule?.expression)) return denied('derived', '已有派生规则，AI 保持原样；可在取值规则中手动调整。');
  if (['faker_method', 'mimesis_method', 'native_faker_method', 'native_mimesis_method', 'native_params'].some(key => populated(rule?.[key]))) return denied('native', '已有原生引擎配置，AI 保持原样；可在取值规则中手动调整。');
  const effective = rule?.generator || rule?.generator_name || table.mapping?.[column.name]?.generator_name;
  if (column.default !== null && column.default !== undefined && (!effective || effective === 'skip' || effective.startsWith('__'))) return denied('database_default', '当前使用数据库 DEFAULT，AI 保持数据库默认规则。');
  return {
    eligible: true,
    code: 'editable',
    reason: ''
  };
}
