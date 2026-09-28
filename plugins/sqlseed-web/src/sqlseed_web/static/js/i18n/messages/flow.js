import {registerMessages} from '../../i18n.js';

registerMessages("flow", {
  "count.tooLarge": [
    "超出工作台可精确表示的整数范围，请输入 1–9,007,199,254,740,991 之间的整数",
    "exceeds the exact integer range. Enter an integer from 1 to 9,007,199,254,740,991"
  ],
  "count.positive": [
    "必须是大于 0 的整数，请填写完整数字",
    "must be a positive integer. Enter a complete number"
  ],
  "count.invalid": [
    "{table} 的生成数量{problem}",
    "Row count for {table} {problem}"
  ],
  "suggestion.stale": [
    "建议字段已失效或重复，请重新分析",
    "Suggested fields are no longer valid or contain duplicates. Analyze again."
  ],
  "document.connection": [
    "连接由当前工作台绑定，文档不能包含连接地址",
    "The workbench binds the connection. A configuration must not include a connection address."
  ],
  "preview.count": [
    "预览数量必须是 1–100 之间的整数",
    "Preview row count must be an integer from 1 to 100"
  ],
  "document.defaultName": [
    "数据生成配置",
    "Data generation configuration"
  ],
  "save.busy": [
    "正在保存，请稍候",
    "Saving. Please wait."
  ],
  "save.changed": [
    "保存期间此配置已被删除或重命名，请核对当前状态后重试",
    "This configuration was deleted or renamed while saving. Check its current state and try again."
  ],
  "table.missing": [
    "数据库中不存在表：{table}",
    "Table does not exist in the database: {table}"
  ],
  "document.wrongDatabase": [
    "此配置属于另一数据库，请先连接对应数据库",
    "This configuration belongs to another database. Connect to that database first."
  ],
  "document.saveAndCheck": [
    "请先保存并检查当前配置",
    "Save and check the current configuration first"
  ],
  "run.submitting": [
    "运行正在提交，请稍候",
    "Submitting the run. Please wait."
  ],
  "run.saveAndCheck": [
    "请先保存当前配置并完成依赖检查",
    "Save the current configuration and complete dependency checks first"
  ],
  "guide.invalidScope": [
    "已选 {count} 张表 · 生成数量待修正",
    "Selected tables: {count} · Row counts need correction"
  ],
  "guide.scope": [
    "已选 {count} 张表 · 计划生成 {rows} 行",
    "Selected tables: {count} · Planned rows: {rows}"
  ],
  "guide.noSelection": [
    "尚未选择生成表",
    "No tables selected for generation"
  ],
  "guide.chooseTitle": [
    "先选择要生成的表",
    "Choose the tables to generate"
  ],
  "guide.chooseBody": [
    "在左侧勾选本次需要生成数据的表，再设置每张表的生成数量。浏览表名不会加入生成范围。",
    "Select the tables on the left, then set the row count for each table. Viewing a table does not add it to the generation scope."
  ],
  "guide.chooseAction": [
    "选择生成表",
    "Select tables"
  ],
  "guide.invalidTitle": [
    "先修正无效输入",
    "Correct invalid input first"
  ],
  "guide.invalidAction": [
    "检查输入",
    "Check input"
  ],
  "guide.issueTitle": [
    "先处理检查发现的问题",
    "Resolve the reported issues first"
  ],
  "guide.issueBody": [
    "查看具体字段、引用来源和处理建议，修正后重新检查。",
    "Review the affected fields, reference sources and suggested fixes, then check again."
  ],
  "guide.issueAction": [
    "查看检查问题",
    "View check issues"
  ],
  "guide.previewedTitle": [
    "已预览所选 {count} 张表",
    "All selected tables previewed: {count}"
  ],
  "guide.previewedBody": [
    "确认样例符合业务要求后，核对写入目标和行数。也可点击“设定规则”返回修改，修改后重新预览。",
    "After reviewing the samples, check the target database and row counts. To make changes, return to Set rules and preview again."
  ],
  "guide.planAction": [
    "查看生成计划",
    "View generation plan"
  ],
  "guide.aiAppliedTitle": [
    "已应用 {count} 条 AI 建议，请预览",
    "AI suggestions applied: {count}. Preview the results."
  ],
  "guide.aiAppliedBody": [
    "建议已进入当前生成配置。请查看实际样例，核对业务要求是否都已覆盖；AI 建议不代表数据库写入一定成功。",
    "The suggestions are now part of the configuration. Review actual samples against your requirements. AI suggestions do not guarantee a successful database write."
  ],
  "guide.aiPreviewAction": [
    "预览 AI 调整结果",
    "Preview AI changes"
  ],
  "guide.partialTitle": [
    "已预览 {previewed}/{total} 张所选表",
    "Selected tables previewed: {previewed}/{total}"
  ],
  "guide.partialBody": [
    "可以继续查看其余表的样例，再核对写入计划。预览不会写入数据库。",
    "Preview the remaining tables, then review the generation plan. Previews do not write to the database."
  ],
  "guide.previewSelected": [
    "预览已选范围",
    "Preview selected tables"
  ],
  "guide.changedTitle": [
    "配置已变化，请重新预览",
    "Configuration changed. Preview again."
  ],
  "guide.changedBody": [
    "已有样例对应之前的规则或生成范围。重新查看样例，确认本次配置的实际效果。",
    "Existing samples use the previous rules or scope. Preview again to see the current configuration."
  ],
  "guide.previewAgain": [
    "重新预览",
    "Preview again"
  ],
  "guide.unavailableTitle": [
    "部分样例暂不可用",
    "Some samples are unavailable"
  ],
  "guide.unavailableBody": [
    "查看预览中的具体原因；依赖尚未生成的父键时，可先核对依赖计划。",
    "Review the preview details. If a parent key has not been generated yet, inspect the dependency plan first."
  ],
  "guide.checkDependencies": [
    "检查依赖",
    "Check dependencies"
  ],
  "guide.reviewTitle": [
    "先确认规则是否符合业务",
    "Review the rules against your requirements"
  ],
  "guide.reviewBody": [
    "检查数值范围、日期和字段含义。可以手动调整，也可让 AI 根据业务说明建议规则；已有配置合适时可直接预览。",
    "Check ranges, dates and field meanings. Edit rules manually or ask AI for suggestions based on your requirements. If the configuration is ready, preview it."
  ],
  "guide.previewNow": [
    "直接预览",
    "Preview samples"
  ],
  "guide.checkAI": [
    "检查 AI 插件",
    "Check AI component"
  ],
  "guide.aiImportError": [
    "插件加载异常 · 规则建议不可用",
    "Component could not load · Suggestions unavailable"
  ],
  "guide.installAI": [
    "安装 AI 扩展",
    "Install AI component"
  ],
  "guide.aiMissing": [
    "AI 扩展未安装 · 规则建议不可用",
    "AI component not installed · Suggestions unavailable"
  ],
  "guide.configureAI": [
    "配置 AI 助手",
    "Set up AI assistant"
  ],
  "guide.aiNeedsSetup": [
    "可选 · 需配置服务",
    "Optional · Service setup required"
  ],
  "guide.useAI": [
    "用 AI 建议规则",
    "Suggest rules with AI"
  ],
  "guide.aiConfigured": [
    "可选 · 服务配置已填写",
    "Optional · Service settings provided"
  ],
  "guide.viewAI": [
    "查看 AI 助手",
    "View AI assistant"
  ],
  "guide.aiUnknown": [
    "可选 · 状态待确认",
    "Optional · Status not yet checked"
  ],
  "clear.rulesPassed": [
    "生成规则已通过",
    "Generation rules passed"
  ],
  "clear.rulesPending": [
    "生成规则待检查",
    "Generation rules not yet checked"
  ],
  "clear.checking": [
    "{rules}；正在检查清空方案",
    "{rules}; checking the clearing plan"
  ],
  "clear.reviewed": [
    "{rules}；清空范围已核对",
    "{rules}; clearing scope reviewed"
  ],
  "clear.recheckBeforeWrite": [
    "{rules}；清空范围已核对，写入前会再次核对",
    "{rules}; clearing scope reviewed and will be checked again before writing"
  ],
  "clear.issues": [
    "{rules}；清空需处理 {count} 项",
    "{rules}; clearing issues to resolve: {count}"
  ],
  "clear.pending": [
    "{rules}；清空方案待重新检查",
    "{rules}; clearing plan needs another check"
  ],
  "files.loading": [
    "加载中…",
    "Loading…"
  ],
  "files.path": [
    "目录路径",
    "Directory path"
  ],
  "files.chooseFolder": [
    "选择文件夹",
    "Select folder"
  ],
  "files.chooseDatabase": [
    "选择数据库文件",
    "Select database file"
  ],
  "files.go": [
    "转到",
    "Go"
  ],
  "files.home": [
    "主目录",
    "Home directory"
  ],
  "files.showAll": [
    "显示全部文件",
    "Show all files"
  ],
  "action.cancel": [
    "取消",
    "Cancel"
  ],
  "files.selectFolder": [
    "选择此文件夹",
    "Select this folder"
  ],
  "action.select": [
    "选择",
    "Select"
  ],
  "files.entries": [
    "{count} 个条目",
    "Entries: {count}"
  ],
  "files.empty": [
    "（空目录）",
    "(Empty directory)"
  ],
  "files.error": [
    "无法浏览：{detail}",
    "Could not browse: {detail}"
  ],
  "connection.switching": [
    "正在切换…",
    "Switching…"
  ],
  "connection.current": [
    "当前连接",
    "Current connection"
  ],
  "connection.switch": [
    "切换到此连接",
    "Switch to this connection"
  ],
  "connection.intro": [
    "选择已有的 SQLite 文件或连接 PostgreSQL，开始创建生成配置。",
    "Select an existing SQLite file or connect to PostgreSQL to start configuring data generation."
  ],
  "connection.connect": [
    "连接数据库",
    "Connect database"
  ],
  "connection.kind": [
    "数据库类型",
    "Database type"
  ],
  "connection.add": [
    "添加连接",
    "Add connection"
  ],
  "connection.file": [
    "数据库文件",
    "Database file"
  ],
  "connection.chooseFile": [
    "选择文件",
    "Select file"
  ],
  "connection.host": [
    "主机",
    "Host"
  ],
  "connection.port": [
    "端口",
    "Port"
  ],
  "connection.database": [
    "数据库名称",
    "Database name"
  ],
  "connection.username": [
    "用户名",
    "Username"
  ],
  "connection.password": [
    "密码",
    "Password"
  ],
  "connection.adding": [
    "正在添加连接…",
    "Adding connection…"
  ],
  "connection.pathRequired": [
    "请选择或输入数据库文件路径。",
    "Select or enter a database file path."
  ],
  "connection.fieldsRequired": [
    "请填写主机、数据库名称和用户名。",
    "Enter a host, database name and username."
  ],
  "connection.portInvalid": [
    "端口必须是 1 到 65535 之间的整数。",
    "Port must be an integer from 1 to 65535."
  ],
  "connection.waitDatabase": [
    "正在添加连接，请等待数据库响应…",
    "Adding connection. Waiting for the database…"
  ],
  "connection.readingSchema": [
    "正在切换到 {target}，读取表结构…",
    "Switching to {target}. Reading the schema…"
  ],
  "connection.disconnectingTarget": [
    "正在断开 {target}…",
    "Disconnecting {target}…"
  ],
  "connection.disconnectedTarget": [
    "已断开 {target}，并从本次会话列表移除。数据库文件和数据保持不变。",
    "Disconnected {target} and removed it from this service session. The database file and data are unchanged."
  ],
  "connection.list": [
    "已连接的数据库",
    "Connected databases"
  ],
  "connection.switchHelp": [
    "切换连接后查看对应配置。断开并移除只关闭本次服务会话，不会删除数据库或运行记录。",
    "Switch connections to view their configurations. Disconnecting only closes this service session; it does not delete the database or run history."
  ],
  "connection.sessions": [
    "{count} 个会话",
    "Sessions: {count}"
  ],
  "connection.sessionLabel": [
    "{action} {target} 会话 {number}",
    "{action} {target}, session {number}"
  ],
  "connection.switchTo": [
    "切换到",
    "Switch to"
  ],
  "connection.session": [
    "会话 {number}",
    "Session {number}"
  ],
  "connection.disconnectLabel": [
    "断开并移除 {target} 会话 {number}",
    "Disconnect and remove {target}, session {number}"
  ],
  "connection.disconnecting": [
    "正在断开…",
    "Disconnecting…"
  ],
  "connection.disconnect": [
    "断开并移除",
    "Disconnect and remove"
  ],
  "connection.listUnavailable": [
    "已有连接暂不可用：{detail}",
    "Existing connections are unavailable: {detail}"
  ],
  "files.reading": [
    "正在读取文件列表…",
    "Reading files…"
  ],
  "files.parent": [
    "上一级",
    "Parent directory"
  ],
  "files.noDatabase": [
    "此目录没有数据库文件。",
    "This directory contains no database files."
  ],
  "files.returnHome": [
    "返回主目录",
    "Return to home directory"
  ],
  "connection.title": [
    "数据库连接",
    "Database connection"
  ],
  "connection.failed": [
    "连接失败，请检查目标及连接参数。",
    "Connection failed. Check the target and connection settings."
  ]
});
