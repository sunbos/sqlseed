# Web 双语维护

本页约定 0.2.6 工作台的简体中文与 English 界面范围、消息边界和验证方式。用户操作见[工作台指南](../web-workbench.md)。这是维护清单，不是浏览器、CI 或发行安装包已经全部验收的声明。

## 范围与术语

| 中文 | English | 范围 |
| --- | --- | --- |
| 工作台 | Workbench | 表选择、规则、依赖检查、预览、AI 审阅与写入确认 |
| 配置管理 | Configs | 保存、打开、搜索、复制、重命名、导入、导出与删除 |
| 运行记录 | Runs | 逐表结果、提交数量、固定配置快照与恢复指引 |
| 设置 | Settings | AI 服务、默认配置、组件管理与外观 |
| 数据生成引擎 | Data generation engine | Base、Faker、Mimesis 的配置选择 |
| 数据语言与地区 | Data language and region | 生成 locale；与 UI 语言无关 |

覆盖包含上述正式页面，以及它们打开的连接、目录选择、下拉、日历、规则编辑、关系图、预览与当前数据窗口。标题、帮助、按钮、加载/空态/错误、placeholder、title 和 aria 名称都属于文案。历史 `connect/wizard/browse/heal/meta` 页面未进入正式 router，不以重新启用旧页面扩大范围。

表列名称、用户配置名称、模型 ID、产品名称、URL/路径、SQL/YAML/JSON、生成器标识与数据库原值保持原文。数字和日期格式化只用于展示元数据；不得重新解析数据库时间导致精度或时区变化。第三方诊断与历史记录没有描述元数据时，保留安全原文并通过当前语言说明其含义，不猜测或递归翻译用户数据。

## 偏好与生命周期

顶栏是统一语言入口。`js/i18n.js` 支持 `zh-CN/en`，以 `sqlseed.ui.language` 保存主动选择；没有有效值时采用浏览器偏好中第一个支持的语言，无匹配默认英文。同源标签页通过 `storage` 事件同步；存储不可用时仅当前页生效。页面 `lang` 和浏览器标题随语言更新。

切换只更新显式绑定的展示槽位，不能调用 router、重挂表单、提交输入、重新取样或触发数据库/AI/组件管理请求。保留原 DOM 控件、输入值与选区、焦点、滚动、已打开的披露区域、未应用规则及请求状态。不得把 UI 语言存进生成文档，或联动更改数据 locale。

## 前端消息

- 字典位于 `static/js/i18n/messages/*.json`，每份文件使用 `{namespace: {key: entry}}` 结构；同名 JS 模块只负责通过统一 `loadMessages(url)` 加载和注册。使用模块保留显式 side-effect import，模块加载完成后才使用相应字典。key 使用稳定语义，条目为 `[中文, English]`，插值用 `{namedParameter}`；需要计数时可以使用 `one/other` 形式。
- 纯翻译数据与可执行逻辑分开维护。加载器校验完整资源后调用 `registerMessages(namespace, entries)`，并按 URL 复用加载结果；切语言不重新读取资源。保持原生 ES modules、现有顶层 await 和本地静态 fetch，不引入打包器或在线翻译服务。
- `tr()` 返回延迟格式化的展示值。`h()`、共享按钮和下拉接受该值；直接 DOM 更新使用 `setText()` / `setAttr()`。向原生 append 或 replaceChildren 传入翻译值时，改用 `appendContent()` / `replaceContent()`。
- 组合文案使用 `joinText()`，或只做格式化的 `liveText()`。模板字符串、普通数组 `.join()`、`String()` 和 `valueText()` 会提前取值，不能用它们保存需要随语言变化的文案。
- `t()` 返回当时的字符串，只用于确实需要固定值的场景，例如用户开始复制配置时给出的默认名称。之后切语言不能改掉用户名称或已提交的值。
- `formatNumber()` / `formatDate()` 用于展示元数据。复数分支的 `count` 保持原始数值，格式化显示值另用参数传入，不能让分组逗号参与复数判断。输入框中的机器值、排序键、传给 API 的数量和时间不能改成地区格式字符串。
- 可恢复的 UI 错误用 `UserFacingError(tr(...))` 保留 `localizedMessage`，catch 展示用 `errorText()`。原生或第三方错误用当前语言的诊断说明包裹安全原文，不把错误当作用户名称处理。

例如页面模块中的状态应保存绑定，而不是语言变化时重新请求：

```javascript
setText(status, tr('runs.identity', {revision: run.revision, id: run.id}));
setAttr(action, 'aria-label', tr('configurations.recordActions', {name: record.name}));
```

## 后端契约与打包

`sqlseed_web.messages` 只标记显式创建的消息，不根据已有字符串匹配译文。原 API 文本保留，增加 `<field>_key` / `<field>_params`；数组保留原值，同时提供索引对齐的 `<field>_i18n`（描述对象或 `null`）。HTTP、事件流、受管进程通信和运行记录边界都要保留这些描述，不改变状态码、业务标识、错误 code 或配置结构。参数仍需脱敏，不能携带密钥。

前端只对已知的展示字段调用 `serverText(record, field)` 或 `serverMessages(record, field)`，不要遍历整份响应翻译任意字符串。嵌套消息也必须带显式描述；缺失或无法识别的诊断使用安全原文回退。

后端共用字典位于 `static/i18n/backend-messages.json`，应用首载读取一次静态资源；切语言不重新请求它。前后端 JSON 字典及 JS 注册入口都随 Python wheel 分发，不依赖 CDN、运行时翻译服务或 npm 构建。资源加载失败不能改变业务操作结果，安装包验收须检查资源存在、静态路由可读及模块依赖能加载。

## 变更验证清单

| 维度 | 必须核对的行为 |
| --- | --- |
| 字典 | 中英 key、具名参数和复数形式对应，正式展示无遗漏或静态冻结 |
| 偏好 | 浏览器语言回退、存储拒绝/损坏、同源 storage 同步，生成 locale 独立 |
| 页面与浮层 | 语言切换更新正文及 title/placeholder/aria，保留原控件、未保存值与焦点 |
| 任务安全 | 请求次数、取消/迟到门禁、配置勾选、执行计划和实际数据库数据不因切语言改变 |
| 诊断 | 已知 descriptor 双语；未知原文保留并有说明；不回显敏感参数 |
| 可读性 | 两语言、浅/深主题、窄屏长标签、键盘操作、关系图和表格溢出 |
| 包资源 | wheel 中的 JS/JSON、原生 ES module 链接及安装后的静态读取 |

Node 使用真实 `loadFrontend/loadI18n` 和真实消息字典。旧行为用例明确中文环境，新双语用例主动切换语言；不能以恒等 `t()` stub 证明绑定正确。页面专项与 `test_i18n.cjs` 验证状态和请求；`test_i18n_catalog.cjs` 枚举实际注册资源，检查语言、参数、复数、后端描述及导航/星期/主题动态键。Python 消息/API 回归验证加法契约与原始数据隔离。Node 的最小 DOM 不证明实际浏览器排版；浏览器、wheel 与 CI 的结果应分别记录，并如实保留未运行项目。

从仓库根执行现有门禁，不为国际化添加构建工具：

```bash
node --test plugins/sqlseed-web/tests/test_*.cjs
pytest plugins/sqlseed-web/tests/
python scripts/sync_docs.py --check
python -m mkdocs build --strict
```

## 验收结果的记录位置

本功能的实现、浏览器与安装包证据及远端检查记录见 [PR #20](https://github.com/sunbos/sqlseed/pull/20)。核验时必须匹配提交 SHA；早期候选包和测试数量不能代表后续修改，也不能用自动化或 API 测试代替尚未完成的浏览器验收。

验收记录应分别列出自动化测试、真实浏览器、安装包、代码审查和远端门禁的结果，保留失败与复跑历史。例如真实 LLM 失败后因服务不可用而跳过，不能据此改记为通过。预期的 PR 文档部署跳过也不代表文档构建未检查；应同时核对 lint 中的严格构建和独立文档同步检查。
