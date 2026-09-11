# 当前表工作流与复杂业务测试库实施计划

**目标：** 根据最新八条浏览器注释减少重复功能入口，并交付可重建、可校验的复杂 SQLite 场景库。

**设计：** 保留当前主题与三项主导航。当前表拥有字段规则、预览数据、关系图三种视图；规则表只呈现字段与取值规则。预览使用同一真实只读服务，当前表内嵌展示；选中多张表时在选择区提供批量预览窗口。全局 AI 只有一个配置助手入口，范围与规则建议在助手内完成。全局生成设置和写入确认逻辑不变。

## 依据与取舍

- 参考图借鉴当前对象上下文、结构与数据分区、工具就近放置；不引入通用 SQL 编辑器或另一套主题。
- W3C APG Tabs Pattern https://www.w3.org/WAI/ARIA/apg/patterns/tabs/ ：手动激活页签避免键盘探索触发耗时请求，tablist/tab/tabpanel、方向键与 Home/End、Enter/Space。
- Carbon Data Table https://carbondesignsystem.com/components/data-table/usage/ ：表工具放在表上下文，批量操作依附选择范围。这是设计指导，不是强制布局标准。
- NN/g Progressive Disclosure https://www.nngroup.com/articles/progressive-disclosure/ ：按需展示可行动的复杂选项，数据库锁定项只在字段信息说明。
- YAML/JSON 是既有 core 加载/保存能力；编辑默认 YAML，读取/格式/下载放编辑区工具栏，底部只留取消与应用。
- 工作区取消由侧栏撑高整个右侧白底的设置；字段区设有限滚动和固定表头，少列按内容收缩。保留适量留白，不填充虚假数据或装饰。

## 执行与验证

- [x] root：侧栏展开状态跟随 model，表级页签和预览嵌入生命周期；移除规则表重复样例，更新文档工具位置。
- [x] editor_usability：不可空字段隐藏 NULL 控件，可空字段按开关显示百分比；统一运行徽章高度。
- [x] ai_assist_integration：统一 AI 标题与范围说明，保持指定字段与关联分组保护。
- [x] connection_runs_refinement：独立 24 表场景 SQL、确定性构建、验收与 baseline，创建全新 Desktop DB。
- [x] 行为回归：展开后切表/刷新仍展开；预览迟到结果、切页、配置变更、重复点击不污染状态；文件工具往返；可空/不可空强约束。
- [x] 全量 Node、Web pytest、结构/文档同步与 wheel 打包；新夹具合法性及副本真实生成。
- [x] 浏览器验证窄/宽表布局、预览、AI 范围、长标题徽章和窄屏，保留用户最新配置。

## 用户数据保护

刷新前通过现有保存按钮保存最新 96 行及五表选择为当前配置 v4，读取快照于 /tmp/sqlseed-context-refinement-preserved.json。只读预览不写入用户数据库。复杂场景另建 sqlseed_scenario_lab.db，存在时自动选择新路径；所有生成验证在临时副本。

## 最终验收（完成于 2026-09-08）

- 全量 Node 410/410：`/tmp/sqlseed-context-final-node.log`。Web 248、夹具5、架构/文档31，共284项pytest通过：`/tmp/sqlseed-context-final-python.log`。
- ruff check、format、mypy Web 12文件、doc markers及git diff --check通过；原有CLAUDE示例marker-name提示保留。wheel已构建到`/tmp/sqlseed-context-build/`，包含新预览组件和最终CSS。
- 独立review发现并修复当前表预览跨tab重入、离页remount、关闭批量窗口后回表内预览的有效结果丢失；同时保留过期结果/epoch/lifecycle约束和数量门禁。
- 真实浏览器1144×872：结构菜单切表与刷新保持展开；NOT NULL外键无NULL控件，可空自引用勾选后显示5%；取消后未应用。文档toolbar与footer分离；运行徽章10处测得高度20px。AI五种范围在统一面板显示，未请求真实LLM。
- 宽表orders33字段：表内高度523px、内容1578px，滚动到末字段时thead顶部与视口顶部相等。窄表tags2字段：内容卡高度295px。24节点/38外键完整图实际展示。
- 760×872：初次发现旧通用样式隐藏新表搜索，已按组件范围修复；复测搜索可见，页面宽745px，数据表927px在685px容器内滚动，未撑宽页面。已恢复1144px视口。
- 新库`~/Desktop/sqlseed_scenario_lab.db`为24表121条合法种子；root独立verify在只读源的一致性临时副本上执行121→159行，完整性/FK/12项业务对账通过。原库仍121行。压力配置实际阻断三列FK和跨表循环。
- 已用正式Web导入baseline并保存“复杂业务场景 · 基础生成”（f7a04ac1-ee01-4e1d-b710-0fe4fc80680a，v2）；当前浏览器显示customers的6条真实只读预览。
- 原用户demo数据库sha256与本轮开始一致，原c9d59fd7配置v4与保存快照完全相等。未提交、未推送、未调用真实LLM、未重启服务；不声明PostgreSQL或全部24表生成通过。
