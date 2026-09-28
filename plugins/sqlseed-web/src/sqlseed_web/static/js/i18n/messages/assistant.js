import {registerMessages} from '../../i18n.js';

registerMessages("assistant", {
  "backend.compatible": [
    "OpenAI 兼容服务",
    "OpenAI-compatible service"
  ],
  "stage.context": [
    "准备分析上下文",
    "Preparing analysis context"
  ],
  "stage.model": [
    "等待 AI 模型",
    "Waiting for the AI model"
  ],
  "stage.validation": [
    "校验建议规则",
    "Validating suggested rules"
  ],
  "stage.preview": [
    "检查只读样例",
    "Checking read-only samples"
  ],
  "rule.derived": [
    "同一行字段派生 · {fields}",
    "Derived from fields in the same row · {fields}"
  ],
  "rule.inferred": [
    "使用现有自动匹配规则",
    "Use existing inferred rules"
  ],
  "title": [
    "AI 配置助手",
    "AI configuration assistant"
  ],
  "intro": [
    "AI 根据表结构和业务说明提出字段规则建议，支持当前表、多表和指定字段；由你审阅并应用到生成配置。",
    "AI suggests field rules from the schema and your requirements. Choose a table, multiple tables or specific fields, then review and apply the suggestions."
  ],
  "privacy": [
    "仅发送表结构、约束、生成器目录和你填写的业务说明给所选 AI 服务；不发送数据库连接地址、凭据或已有记录。",
    "Only schema, constraints, the generator catalog and your requirements are sent to the selected AI service. Connection addresses, credentials and existing records are not sent."
  ],
  "settings.loading": [
    "正在读取 AI 设置…",
    "Loading AI settings…"
  ],
  "issues.view": [
    "查看问题",
    "View issues"
  ],
  "settings.loadingShort": [
    "正在读取 AI 设置",
    "Loading AI settings"
  ],
  "settings.summary": [
    "AI 服务摘要",
    "AI service summary"
  ],
  "settings.notLoaded": [
    "服务信息尚未读取",
    "Service information has not been loaded"
  ],
  "settings.open": [
    "前往设置",
    "Open settings"
  ],
  "status": [
    "AI 状态",
    "AI status"
  ],
  "component.install": [
    "安装 AI 插件",
    "Install AI component"
  ],
  "scope.title": [
    "选择要优化的范围",
    "Choose what to improve"
  ],
  "scope.help": [
    "这里选择的是可修改规则的范围，独立于本次生成范围。未勾选表的建议仅更新草稿。指定字段时，只需勾选要改规则的字段；同表其他字段及必要上游结构仍作为分析上下文。受保护字段不会被修改。",
    "This scope controls which rules AI may change and is separate from the generation scope. Suggestions for unselected tables only update their drafts. Select just the fields to change; other fields in the table and required upstream schema remain available as context. Protected fields stay unchanged."
  ],
  "scope.chooseTables": [
    "选择要优化的表",
    "Select tables to improve"
  ],
  "scope.chooseFields": [
    "选择要优化的字段",
    "Select fields to improve"
  ],
  "scope.search": [
    "查找表或字段",
    "Find tables or fields"
  ],
  "scope.searchPlaceholder": [
    "表名、字段名或 orders.promised_at",
    "Table, field or orders.promised_at"
  ],
  "scope.noMatches": [
    "没有匹配的表或字段；已有选择保留，请修改搜索。",
    "No matching tables or fields. Your selections are preserved; try another search."
  ],
  "scope.selectMatches": [
    "选择筛选结果",
    "Select matching fields"
  ],
  "scope.clear": [
    "清空选择",
    "Clear selection"
  ],
  "scope.clearAllLabel": [
    "清空全部已选字段，包括当前筛选之外的字段",
    "Clear all selected fields, including those outside the current filter"
  ],
  "scope.filterHelp": [
    "搜索仅影响显示；选择结果会保留其他已选字段，清空选择会移除全部字段授权。",
    "Searching only changes what is shown. Selecting matches keeps other selected fields; clearing the selection removes permission to change any field."
  ],
  "scope.currentTable": [
    "当前表 · {table}",
    "Current table · {table}"
  ],
  "scope.currentHelp": [
    "优化当前正在查看的表，不改变生成勾选。",
    "Improve the table you are viewing without changing the generation selection."
  ],
  "scope.selectedTables": [
    "已选表 · {count} 张",
    "Selected tables · {count}"
  ],
  "scope.selectedHelp": [
    "优化左侧已勾选的生成表。",
    "Improve the tables selected for generation on the left."
  ],
  "scope.noneSelected": [
    "尚未勾选生成表；可选择当前表或指定表。",
    "No generation tables selected. Choose the current table or specific tables."
  ],
  "scope.database": [
    "整库 · {count} 张表",
    "Entire database · Tables: {count}"
  ],
  "scope.databaseHelp": [
    "覆盖数据库中的所有表；未勾选表只更新草稿。",
    "Include every table in the database. Unselected tables only have their drafts updated."
  ],
  "scope.specificTables": [
    "指定表（多选）",
    "Specific tables"
  ],
  "scope.specificTablesHelp": [
    "在下方选择一张或多张表。",
    "Select one or more tables below."
  ],
  "scope.specificFields": [
    "指定字段（多选）",
    "Specific fields"
  ],
  "scope.specificFieldsHelp": [
    "在下方选择要调整规则的字段，可说明同表关系。",
    "Select fields to adjust below. You can describe relationships within a row."
  ],
  "scope.generated": [
    "本次生成",
    "Generate in this run"
  ],
  "scope.draftOnly": [
    "仅更新草稿",
    "Update draft only"
  ],
  "scope.tableFields": [
    "{table} 的字段",
    "Fields in {table}"
  ],
  "scope.protected": [
    "受保护字段 · 保留现有规则",
    "Protected field · Existing rule retained"
  ],
  "scope.protectedCount": [
    "受保护字段（{count}）· 保留现有规则",
    "Protected fields: {count} · Existing rules retained"
  ],
  "scope.fieldCounts": [
    "已选 {selected} 个字段允许修改 · 筛选内 {matching}，其他 {other}",
    "Fields allowed to change: {selected} · Matching: {matching}; outside filter: {other}"
  ],
  "scope.matchSummary": [
    "{scope}：{count} 个可选字段{protectedNote}。",
    {"one": "{scope}: {count} selectable field{protectedNote}.", "other": "{scope}: {count} selectable fields{protectedNote}."}
  ],
  "scope.filtered": [
    "筛选结果",
    "Filtered results"
  ],
  "scope.allTables": [
    "全部表",
    "All tables"
  ],
  "scope.protectedContext": [
    "，{count} 个受保护字段仅作上下文",
    "; protected fields used only as context: {count}"
  ],
  "scope.selectCount": ["{label}（{count}）", "{label} ({count})"],
  "progress.stageFailure": ["{stage}{outcome} · {summary}", "{stage}: {outcome} · {summary}"],
  "candidate.stageFailed": ["{stage}未通过", "{stage} failed"],
  "scope.selectAllFields": [
    "选择全部可选字段",
    "Select all available fields"
  ],
  "requirements.label": [
    "业务说明",
    "Requirements"
  ],
  "requirements.placeholder": [
    "例如：姓名使用中文；订单总额 = 数量 × 单价；完成日期在创建日期后 7 天。",
    "For example: use Chinese names; order total = quantity × unit price; completion date is 7 days after creation."
  ],
  "requirements.optional": [
    "业务说明（可选）",
    "Requirements (optional)"
  ],
  "requirements.help": [
    "说明数据含义、范围和字段关系。请填写业务规则，不要填写密钥或真实个人记录。",
    "Describe meanings, ranges and field relationships. Enter business rules, not secrets or real personal records."
  ],
  "action.analyze": [
    "开始分析",
    "Analyze"
  ],
  "action.apply": [
    "应用所选建议",
    "Apply selected suggestions"
  ],
  "action.cancel": [
    "取消",
    "Cancel"
  ],
  "progress.elapsed": [
    "已耗时 {seconds} 秒",
    "Elapsed: {seconds} s"
  ],
  "stale.configuration": [
    "配置已变化，请关闭面板后重新分析。",
    "Configuration changed. Close this panel and analyze again."
  ],
  "stale.connection": [
    "数据库连接已失效，Web 服务重启后需要重新连接原数据库，再打开 AI 助手；当前配置未改变。",
    "The database connection is no longer available. Reconnect to the original database after the Web service restarts, then reopen the AI assistant. Your configuration is preserved."
  ],
  "progress.invalidated": [
    "分析已失效 · {summary}",
    "Analysis is no longer valid · {summary}"
  ],
  "progress.timeout": [
    "超时",
    "Timed out"
  ],
  "progress.failed": [
    "失败",
    "Failed"
  ],
  "issues.failed": [
    "建议未通过检查",
    "Suggested rules did not pass validation"
  ],
  "issues.details": [
    "检查详情 · {count} 项",
    "Check details · Issues: {count}"
  ],
  "component.status": [
    "查看插件状态",
    "View component status"
  ],
  "settings.change": [
    "更改设置",
    "Change settings"
  ],
  "scope.eligible": [
    "{scope} · {count} 个字段可优化",
    "{scope} · Fields eligible for suggestions: {count}"
  ],
  "scope.analysisContext": [
    "{tables} 张表作为分析上下文{protectedNote}。{draftNote}",
    "Tables in analysis context: {tables}{protectedNote}. {draftNote}"
  ],
  "scope.protectedRules": [
    "，{count} 个受保护字段保留现有规则",
    "; protected fields keeping their existing rules: {count}"
  ],
  "scope.draftTables": [
    "{count} 张表未加入生成范围，建议仅更新草稿。",
    "Tables outside the generation scope: {count}. Suggestions only update their drafts."
  ],
  "scope.required": [
    "请至少选择一张表或一个可由 AI 调整的字段；受保护字段仅作为结构上下文。",
    "Select at least one table or a field that AI can adjust. Protected fields are only used as schema context."
  ],
  "settings.unknown": [
    "AI 状态未获取",
    "AI status not loaded"
  ],
  "component.importError": [
    "AI 插件加载异常",
    "AI component could not load"
  ],
  "component.missing": [
    "AI 扩展未安装",
    "AI component not installed"
  ],
  "settings.configured": [
    "AI 配置已填写",
    "AI settings provided"
  ],
  "settings.required": [
    "AI 待配置",
    "AI setup required"
  ],
  "settings.service": [
    "AI 服务",
    "AI service"
  ],
  "settings.noModel": [
    "尚未选择模型",
    "No model selected"
  ],
  "component.importHelp": [
    "AI 扩展已安装但加载异常，规则建议与分析不可用。",
    "The AI component is installed but could not load. Rule suggestions and analysis are unavailable."
  ],
  "component.missingHelp": [
    "AI 扩展未安装，规则建议与分析不可用。",
    "The AI component is not installed. Rule suggestions and analysis are unavailable."
  ],
  "settings.ready": [
    "配置已填写，可开始分析。",
    "Settings are provided. You can start analysis."
  ],
  "settings.setupHelp": [
    "请前往设置页完成 AI 服务配置。",
    "Complete the AI service configuration in Settings."
  ],
  "component.repair": [
    "修复 AI 插件",
    "Repair AI component"
  ],
  "component.repairHelp": [
    "请在“设置 → 插件与版本”查看异常信息，处理后返回 AI 助手。",
    "Review the error in Settings → Components and versions, resolve it, then return to the AI assistant."
  ],
  "component.installHelp": [
    "请在“设置 → 插件与版本”安装 AI 扩展，完成后返回 AI 助手。",
    "Install the AI component in Settings → Components and versions, then return to the AI assistant."
  ],
  "component.optionalHelp": [
    "当前生成配置保留，仍可手动调整规则、预览和生成数据。",
    "Your generation configuration is preserved. You can still edit rules manually, preview and generate data."
  ],
  "component.openSettings": [
    "前往插件设置",
    "Open component settings"
  ],
  "progress.submitting": [
    "正在提交分析请求…",
    "Submitting analysis request…"
  ],
  "progress.context": [
    "正在准备分析上下文…",
    "Preparing analysis context…"
  ],
  "progress.deadline": [
    "AI 分析超过 180 秒，请检查失败阶段后重试；当前规则未改变。",
    "AI analysis exceeded 180 seconds. Review the failed stage and try again. Current rules are unchanged."
  ],
  "stale.schema": [
    "数据库结构已变化，请刷新后重新分析。",
    "The database schema changed. Reload the schema and analyze again."
  ],
  "response.invalid": [
    "AI 建议格式不正确，请重试。",
    "AI suggestions have an invalid format. Try again."
  ],
  "suggestion.group": [
    "关联规则 · {count} 个字段，一起应用",
    {"one": "Related rule · Apply {count} field", "other": "Related rules · Apply {count} fields together"}
  ],
  "suggestion.draftOnly": [
    "该表未加入生成范围；应用后仅更新其草稿。",
    "This table is outside the generation scope. Applying suggestions only updates its draft."
  ],
  "suggestion.review": [
    "请结合业务含义确认。",
    "Review this suggestion against your requirements."
  ],
  "suggestion.current": [
    "当前规则",
    "Current rule"
  ],
  "suggestion.proposed": [
    "建议规则",
    "Suggested rule"
  ],
  "suggestion.adjust": [
    "调整规则",
    "Adjust rule"
  ],
  "suggestion.adjusted": [
    "已手动调整；原关系说明与样例已失效。请重新勾选，应用前会检查整组规则。",
    "Manually adjusted. The original relationship explanation and samples are no longer valid. Select this suggestion again; the full group will be checked before applying."
  ],
  "suggestion.adjustLabel": [
    "调整 {table}.{column} 的建议规则",
    "Adjust the suggested rule for {table}.{column}"
  ],
  "relation.copy": [
    "复制",
    "Copy"
  ],
  "relation.concat": [
    "按顺序拼接",
    "Concatenate in order"
  ],
  "relation.product": [
    "相乘",
    "Multiply"
  ],
  "relation.dateOffset": [
    "日期偏移",
    "Date offset"
  ],
  "relation.title": [
    "同一行关系",
    "Same-row relationship"
  ],
  "relation.samples": [
    "同一行关系的只读样例",
    "Read-only samples of the same-row relationship"
  ],
  "suggestion.received": [
    "收到 {count} 条建议。存在关联的规则会作为一组应用，请对比后勾选。",
    "Suggestions received: {count}. Related rules are applied as a group. Compare the changes and select the suggestions to apply."
  ],
  "suggestion.empty": [
    "没有可应用的建议，现有规则保持不变。",
    "No applicable suggestions. Existing rules are unchanged."
  ],
  "candidate.title": [
    "候选检查",
    "Candidate validation"
  ],
  "candidate.failed": [
    "未通过",
    "Failed"
  ],
  "progress.complete": [
    "分析完成",
    "Analysis complete"
  ],
  "stale.scope": [
    "建议范围已变化，请重新分析。",
    "The suggestion scope changed. Analyze again."
  ],
  "candidate.checking": [
    "正在检查调整后的规则，当前配置保持不变…",
    "Checking adjusted rules. Your current configuration is unchanged…"
  ],
  "candidate.invalid": [
    "调整后的规则未通过检查：{issues}",
    "Adjusted rules did not pass validation: {issues}"
  ],
  "candidate.checkHelp": [
    "请检查字段规则与表间依赖。",
    "Check the field rules and table dependencies."
  ],
  "stream.invalid": [
    "AI 进度格式不正确，请重试。",
    "AI progress has an invalid format. Try again."
  ],
  "stream.cancelled": [
    "AI 分析已取消。",
    "AI analysis cancelled."
  ],
  "stream.incomplete": [
    "AI 分析连接中断，未收到完整结果，请重试。",
    "The AI connection closed before a complete result was received. Try again."
  ],
  "protected.schema": [
    "字段结构不可用，请刷新结构后再分析。",
    "Field metadata is unavailable. Reload the schema before analyzing."
  ],
  "protected.auto": [
    "由数据库自动分配，AI 不修改该字段。",
    "The database assigns this value automatically. AI does not change it."
  ],
  "protected.primary": [
    "主键由现有规则和数据库约束管理，AI 保持原样。",
    "Existing rules and database constraints control this primary key. AI leaves it unchanged."
  ],
  "protected.foreign": [
    "外键从关联表取值，AI 保持引用关系。",
    "This foreign key reads from a related table. AI preserves the reference."
  ],
  "protected.computed": [
    "由数据库表达式计算，AI 不修改该字段。",
    "A database expression computes this value. AI does not change it."
  ],
  "protected.derived": [
    "已有派生规则，AI 保持原样；可在取值规则中手动调整。",
    "AI preserves the existing derived rule. You can edit it manually in the rule editor."
  ],
  "protected.native": [
    "已有原生引擎配置，AI 保持原样；可在取值规则中手动调整。",
    "AI preserves the existing native engine configuration. You can edit it manually in the rule editor."
  ],
  "protected.default": [
    "当前使用数据库 DEFAULT，AI 保持数据库默认规则。",
    "This field uses the database DEFAULT. AI preserves that behavior."
  ],
  "adjustment.loading": [
    "正在读取字段规则…",
    "Loading field rules…"
  ],
  "adjustment.save": [
    "保存调整",
    "Save adjustment"
  ],
  "adjustment.stale": [
    "配置已变化，请取消并重新分析。",
    "Configuration changed. Cancel and analyze again."
  ],
  "adjustment.cancel": [
    "取消调整",
    "Cancel adjustment"
  ],
  "adjustment.aria": [
    "调整 {table}.{column} 的建议",
    "Adjust the suggestion for {table}.{column}"
  ],
  "adjustment.title": [
    "调整建议 · {table}.{column}",
    "Adjust suggestion · {table}.{column}"
  ],
  "adjustment.help": [
    "只修改待审阅建议。保存后需重新勾选，并在应用前检查；当前配置保持不变。",
    "Only the pending suggestion changes. After saving, select it again for validation before applying. Your current configuration stays unchanged."
  ],
  "adjustment.saved": [
    "调整保留在建议中，最终应用前会重新检查。",
    "The adjustment is saved in the suggestion and will be checked before applying."
  ],
  "adjustment.reset": [
    "重置为本次调整前的建议",
    "Reset to the suggestion before this adjustment"
  ],
  "adjustment.loadFailed": [
    "无法读取规则编辑器，请取消后重试。",
    "Could not load the rule editor. Cancel and try again."
  ]
});
