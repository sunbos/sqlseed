# 十项反馈第一阶段实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 用户已批准评审中的分阶段顺序，本轮直接执行。

**Goal:** 修复切页宽度跳动、空计划呈现、运行记录布局、图标状态，并完善折叠、预览表头、关系图文案与安装指引。

**Architecture:** 保留现有原生前端和后端契约。只在表现层处理空选择，不移除后端 empty_plan 校验；组件页只消费现有环境事实和安装命令。本轮不新增执行 pip 的接口，安装卸载执行另有维护生命周期设计。

**Tech Stack:** 原生 ES modules / CSS、Node 内置测试、现有 FastAPI、浏览器验收。

依据：[已批准的十项评审](../../design-review/2026-09-10-ten-ui-comments-review.md)。当前目录已有大量未提交实现，本轮定点修改，不 reset、提交或推送。

## 1. 应用宽度、折叠与表头

文件：`static/navigation.css`、`static/disclosure.css`、`static/preview.css`（下文 static 为 plugins/sqlseed-web/src/sqlseed_web/static）。

- [x] 在根滚动容器预留槽位，兼容回退保持传统滚动条空间：
  ```css
  html { overflow-y: scroll; }
  @supports (scrollbar-gutter: stable) {
    html { overflow-y: auto; scrollbar-gutter: stable; }
  }
  ```
- [x] CHECK 独立折叠区用一层 `var(--line)` 轻描边和 `var(--wash)` 标题背景；容器圆角保持 8px，展开标题只保留上角，正文正常换行。仅限定 `.wb-field-constraints`，保留原生语义与既有动效。
- [x] 列名默认 `text-decoration: underline; text-underline-offset: 4px`，元数据不加线。可交互表头的 padding 由内部按钮负责，让完整标题区可点击；只读表头保持原样。
- [x] 浏览器验证导航加载前后位置、标题点击与折叠焦点；CSS 不添加只检查源码片段的自证测试。

## 2. 生成空状态、路径按钮、关系图文案

文件：`static/js/pages/workbench.js` 及相关 Node 测试。该模块由同一个实现者负责，避免共享状态修改冲突。

- [x] 为无已选表的依赖检查入口添加中性空状态：
  ```js
  if (!model().document.tables.length) {
    // 展示“尚未选择生成表”和“选择生成表”，关闭后定位勾选入口。
    // 不调用 session.check，不展示阻断、来源分组或执行按钮。
    return;
  }
  ```
  选择引导不得自动勾选表，保留忙碌门禁与离页清理。
- [x] 路径按钮输出与当前表和 graph 视图一致的 `aria-pressed`，样式沿用既有选择器；在字段规则页保持 false，不能把当前表和当前图视图混为一个状态。
- [x] 菜单和导入窗口统一“导出关系图 JSON / 导入关系图 JSON”，说明只浏览表与外键关系，不创建或修改数据库。保持 `sqlseed-schema-graph`、下载文件格式和导入兼容性不变。
- [x] 行为测试断言空选择不发检查请求、选择入口定位且不改生成范围，路径状态在切换时更新，导入导出原有往返与离页守卫仍有效。先观察相关行为用例失败，再修实现并运行相关测试。

## 3. 运行记录边界与结果操作

文件：`static/js/pages/runs.js`、新 `static/runs.css`，相关 Node 回归。根代理将新样式导入 style.css。

- [x] 保留运行列表语义与滚动位置，补容器边界、内边距和圆角，普通卡片淡化描边，选中项仍明确。
- [x] `td` 中用独立 `.run-result-content` 容器包裹说明和查看按钮：
  ```css
  .runs-page .run-result-content { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
  .runs-page .run-result-content .run-view-data { margin: 0; }
  ```
- [x] 长错误按可用宽度换行；保持打开当前数据时的 run/table 身份、目标匹配和原事件处理。
- [x] 运行既有 runs、run_recovery、table_data 行为测试；浏览器确认长错误和成功状态的间距及窄屏列表边界。

## 4. 缺包安装引导与复制命令

文件：`static/js/pages/settings.js`、`static/settings.css`、`tests/test_settings.cjs`。

- [x] 缺包与加载异常显示醒目的安装/修复指引；已有 `dependency_ids`、`requirement`、`guidance` 保留，不自行猜依赖。
- [x] 命令配复制按钮，使用 `navigator.clipboard.writeText(command)`；复制失败显示可手动选择的命令和明确提示，不伪报成功，不执行命令。
- [x] 重复点击有在途状态，异步完成只更新仍连接且属于当前页面的节点。保留命令中的准确 shell 引号，来自服务器的内容只作为文本。
- [x] 安装设备和重启要求清楚；内置/必需组件不提供伪卸载按钮。页面说明目前提供安装指引，执行操作在运行服务的设备完成。
- [x] 测试核心基础环境下缺 AI/CLI/MCP/Mimesis 的指引、复制成功/失败、迟到响应和现有生命周期；测试只替换 clipboard 边界，不调用包管理器。

## 5. 集成与交付

- [x] 根代理挂载 runs.css，检查并行实现的范围与代码质量，再运行 `node --test plugins/sqlseed-web/tests/test_*.cjs`。
- [x] 浏览器检查真实服务：跨页过渡、空选择与实际阻断、预览表头、CHECK、图标移出鼠标后的状态、运行结果及设置指引；窄屏与减少动态效果保持正常。
- [x] 页面请求与资料仅作只读核验，不生成或删除数据库记录，不安装卸载正式环境组件。
- [x] 更新本计划、静态目录约定及验收记录，准确列出本轮完成内容和组件管理执行的独立范围。

完成记录：[第一阶段验收](../../design-review/2026-09-10-ui-review-verification.md)。前端 597/597 通过；实际浏览器核验与缺包模拟已完成，真实环境未变更。非空阻断由行为回归核验，未制造新的数据库失败运行。
