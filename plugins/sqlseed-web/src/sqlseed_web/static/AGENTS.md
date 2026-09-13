# sqlseed-web 静态前端

继承 [后端指南](../AGENTS.md)。使用 FastAPI 直接提供的原生 ES modules、DOM 与 CSS，无 bundler、CDN 或 npm 构建。产品能力见 [工作台指南](../../../../../docs/web-workbench.md)；本文件按职责保留已实现交互与回归约束，历史设计记录用于解释决策。

## 产品入口与主题

- 正式主导航为“工作台 / 配置管理 / 运行记录 / 设置”；连接、首次空状态与切换目标使用同主题弹窗。`connect/wizard/browse/heal/meta` 历史页面保留文件，不在正式 router 中注册或动态加载，旧/未知 hash 回到工作台。
- 保持当前 v8 shell、叶芽表格 SVG logo、字体、色彩与空间节奏；只有一套生效主题。`index.html` 仅加载 `style.css`，后者导入组件样式并承载 v8 基础规则；`workbench.css` 只补组件类，不定义第二套 tokens、body 或旧 Material 3 覆盖。
- 复用后端、model/session 与图计算；重新设计 presentation 不得退回模拟数据或独立 YAML/表单状态。生成引擎和语言地区属于同一生成配置；连接仅绑定目标。
- 表单标题使用中文：“数据生成引擎”“数据语言与地区”；保留 SQLite、Mimesis、Faker 等产品名。Locale 影响生成内容的语言与地区格式，不称“默认市场”，也不暗示改变界面语言。
- 用户可见文案、注释和文档用“参考工具/参考设计”，不要引入商业工具品牌名称。

## 修改入口

| 文件 | 职责 |
| --- | --- |
| [index.html](index.html)、[style.css](style.css) | v8 页面 shell、唯一主题、品牌与共享布局控件 |
| [js/app.js](js/app.js)、[js/api.js](js/api.js) | hash router、HTTP/DOM helpers、共享连接 `store` 与恢复 |
| [js/pages/](js/pages/) | 正式 workbench/configs/runs/settings；connect/wizard/browse/heal/meta 为历史模块，不由 router 加载 |
| [js/workbench/](js/workbench/) | model/session、真实 schema graph、右侧规则抽屉、connection 弹窗与共享 UI；`workbench.css` 仅组件样式 |
| [js/genform.js](js/genform.js) | 历史向导列属性面板，以下 legacy 回归规则仅适用于维护该文件 |
| [js/dropdown.js](js/dropdown.js)、[js/tree.js](js/tree.js)、[js/filepicker.js](js/filepicker.js) | 自绘下拉、表列树、服务器目录选择器 |
| [js/labels.js](js/labels.js) | generator/param 中文标签与分类 |

## 页面、连接与请求生命周期

- 新页面在 router 注册并导出 `render()`，可选 `mount()`；`render()` 发生在 DOM mount 前，访问新元素时传引用，挂载后再查 DOM。
- 页面切换保留 module-level 状态；刷新会清空 JS store，但服务器连接仍在。`restoreConnection()` 优先 localStorage 的 `sqlseed.connId`，其次主连接，再取表列表；失效时清除旧 key。显式断开使用空标识且优先于自动恢复，即使还有其他会话也不能自动切换；连接操作版本防止迟到恢复覆盖用户选择。
- router 支持 `unmount()` 并检查异步加载版本；工作台/记录页离开时销毁组件、关闭弹窗和停止轮询。网络迟到结果不可重开页面或覆盖新文档。
- 同一工作台会话的数据库操作共用在途门禁，主按钮、侧栏与配置文档快捷入口都必须接入；只读预览期间可继续查看/编辑字段。重新绘制不能丢失 busy 状态，失败必须恢复按钮并显示原因。
- 相同连接的结构读取共用在途请求；切页返回时不能丢弃正在刷新的结构。服务端 409 是忙碌提示，不自动重试生成。
- 连接添加、切换、断开和文件浏览分别显示在途反馈，保留服务端具体错误。原生 append/replaceChildren 不传 null，否则会渲染字面量。

## 配置、字段规则与执行确认

- `WorkbenchDocument.document` 是唯一可执行配置；取消勾选的表配置保存在 `view.tableDrafts`，换表/字段规则/关系图不改变生成范围。点表名固定打开字段，右侧 schema 图标打开完整依赖路径，库名打开整库。
- 字段名打开只读字段信息；取值规则打开编辑页，两者使用具有 tablist/tab/tabpanel 语义的同一右侧抽屉。图旁规则打开编辑页；应用、取消、切字段与关闭后恢复焦点，不沿用旧 inline auto-apply 布局。配置级保存/打开、provider/locale 与配置文档属于同一模型。
- `WorkbenchSession` 捕获 model 身份、epoch、connId 和保存版本；异步 check/preview/save 必须检查身份，不能只比较相同 epoch。run 只提交已保存并检查通过的版本/hash，由服务端接管整个计划。
- 无效抽屉输入就地保留并禁用“应用规则”，不得污染 model 或静默应用旧值；取消/离页关闭抽屉并丢弃未应用修改，返回后保留已应用配置。销毁 dropdown 监听器。表级 count 的无效值仍保留在视图草稿中并阻止保存/运行。
- 当前表使用“字段规则 / 预览数据 / 关系图”三个语义 tab；手动键盘激活，方向键只移动焦点。预览内嵌且首次自动请求当前表；多表选择区提供固定所选范围的“预览已选表”窗口。每表 1–100 行（默认 10），按真实返回记录展示。规则表只有字段/取值规则，不重复放样例。数据库结构操作位于左侧库上下文，重新读取结构不生成数据。基础引擎/语言可见，“编辑 YAML”弱化直达且兼容 JSON；文件与下载格式工具在编辑区上方，footer只留取消/应用，不为单项入口增加折叠；原生方法和复杂参数继续折叠。
- configs.js 提供筛选、重命名/复制/带 revision 的删除和离线导出；生命周期事件使缓存 model 失效，迟到保存不能复活删除的 id 或回退重命名版本。
- 生成确认默认追加；SQLite 可选择清空所选表与独立重置计数。replace 必须使用服务端 execution-plan 和 plan_hash，确认页显示真实清空行数、阻断项和事务边界。快照复用只复用规则，清空必须重新确认。
- 写入确认的“写入目标”继续直接使用 schema 的动态脱敏 `target_label`，附当前数据库类型与解释，不重建或猜测连接地址。
- provider-guide.js 区分本地化自然数据和 Base 占位值；格式示例不得表述为实时生成，不以未测数据宣称引擎性能优势。
- 配置工具与引擎/语言合并为紧凑上下文区，保留直接可见的全局设置、保存状态及生成主入口；侧栏表名与生成/引用状态分行，勾选、字段和依赖路径入口独立，完整名称可获取。AI 使用同一“AI 配置助手”，顶栏保留固定入口，后续批准的使用引导可提供范围快捷入口；NOT NULL 不渲染 NULL 控件，可空百分比按开关显示。侧栏展开状态按 model 保留，查找表不改勾选；内容按自身高度收缩，长表有限滚动且固定表头。
- 首次使用引导：`guidance.js` 只根据现有配置、输入问题和当前 epoch 的完整预览计算下一步，不追认业务规则已审阅。`workbench.js` 复用现有操作门禁和写入确认；引导内 AI 快捷操作与顶栏打开同一助手，默认已选表，不增加独立 AI 流程或自动分析。收起偏好属于浏览器，不改变生成文档；缺插件/待配置/配置已填写仅来自脱敏配置响应，不能当作连通性检测。

## 预览与当前数据

- `model.samples` 与执行授权分离；预览未勾选表只临时加入请求，不能改变勾选或拿该检查授权运行。本表预览只包含当前表与执行所需的已选上游，遇未选来源停止纳入其祖先；FK 与 associations 一致，根配置无损。所选表与本表预览共用请求版本，迟到结果不能覆盖新样例。有效编辑清掉旧样例和检查。
- `preview.js` 的范围/行数仅属只读预览状态，不能改变正式生成数或勾选；关闭、改配置和过期响应不能重开结果。结果缺少的自增/默认值/计算字段按结构和当前规则解释，不虚构 ID；缺少关联样例保留具体问题和空表标签。
- 预览缓存必须同时匹配 model、epoch 和 count，保留完整 ok/preview_complete/issues。结果接收与视图生命周期分开：在途离开/重入/remount或关闭批量窗口后，有效结果可在当前匹配的表内显示，但不能重开旧窗口或覆盖新的配置/无效输入。重建预览控件也须接入全局操作门禁。
- `preview.js` 重新预览保留上次 DOM、选中表和滚动；状态标明旧结果，失败保留旧结果。`preview.css` 只提供首载占位和状态高度。使用当前行为回归与实际浏览器尺寸核验，不能把历史测试数当成本轮验收。
- 预览表头使用真实列元数据；就地编辑复用字段规则抽屉与同一 AI 助手，显式绑定 shownTable/column。取消保持配置，应用标记旧样例失效。批量标签按 result.order 且保留错误表。预览→AI→设置显式返回通过内存 handoff 携带预览上下文，沿用身份/epoch/schema/lifecycle 守卫，不持久化样例。
- `workbench/table-data.js` 是工作台与运行记录共享的只读分页面板。运行结果只承诺“数据库当前数据”，不伪称本次新增快照；运行入口按目标匹配连接，后端再次验证。关闭、切运行或离页后丢弃迟到响应。
- 预览交互表头整格提供 hover/focus 背景；列名与明确标注“规则：…”的属性分别使用兄弟按钮，仅对应按钮 hover/focus 时显示下划线。列名直达字段信息，规则直达编辑页；数据库类型/PK/NOT NULL 元数据与只读数据表头不伪装为可编辑规则。关闭或应用后恢复表、列和具体入口焦点，保留样例，规则变更后标明旧结果。路径按钮的 `aria-pressed` 同时取决于当前表和 graph 视图。
- 预览表头只保留列名→字段信息、规则→取值规则两个直接入口；不再插入上方字段操作条。AI 调整位于规则面板中，同一时刻只有一个编辑/AI 面板。手动草稿未应用或无效时阻止跳转并解释原因，避免静默丢弃。
- 关闭字段面板后恢复具体入口焦点和原预览位置；预览→AI→设置往返仍保留身份、schema、epoch 和生命周期检查，不自动分析或写库。
- `preview-scroll-layout.js` 负责预览滚动归属：内嵌短表自然高度，长表保留固定表头；批量弹窗按实际空间选择表格或 body 单一纵向滚动。尺寸观察须在清空/销毁时释放，垂直位置按表统一保存，避免跨尺寸返回或切表时重复计入 body 偏移。恢复入口焦点使用 `preventScroll`，不可覆盖已恢复的位置。

## 关系图与依赖检查

- graph 的搜索框不随重画替换；IME composition 结束才搜索。百分比显示实际图形尺度，100% 是自然尺寸；适应画布按当前范围缩放，阅读当前表依赖切换完整路径并以 100% 居中，搜索结果支持同一定位动作。匹配数量可见，结果列表有限高度滚动。内部 `zoom` 保持相对 fit 的快照语义，不可直接作为显示百分比。完整路径包括下游及所有必需上游，字段标签使用实际成组 FK，不能凭字段名猜边。
- graph 的 `pathFocus` 是展示路径的起点，`focus` 是当前检查表；图内单击保持画布和路径标题稳定，不同时另标当前查看对象，明确读取路径才同步二者。两个值均保存在视图快照，旧快照缺 `pathFocus` 时回退到 `focus`；定位与重算不改变生成勾选，并保留宿主导航 veto。
- 图旁展示当前表完整结构上游及本表相关生成顺序；顶栏依赖检查覆盖所有勾选表。结果先呈现阻断/提醒摘要及对应问题，再展示可展开的来源明细和生成顺序；全局来源默认折叠，本表来源默认展开，重画保留展开状态。局部执行顺序不混入无关表，不把仅引用来源的祖先误作本次写入前置；未勾选表不能借用全局通过结果声称已检查。依赖弹窗的迟到响应不能替换后来打开的抽屉，修复问题后同步更新当前面板，阻断未解决时禁用生成入口。
- 数据库结构导入/导出位于数据库工具栏，配置保存/检查/摘要位于配置顶栏，行数位于当前表，规则参数位于当前列。导入结构 JSON 只浏览，不替换当前连接或可执行文档。
- `graph-clarity.css` 随主样式加载。节点内框表示生成/引用/其他状态，当前查看使用独立外圈并有图例。完整相关链高亮复用现有依赖选择语义，仅修改视觉类，不重排、不修改 viewBox、`pathFocus` 或生成勾选；环与分叉须可终止。单边选择优先，问题色保留，键盘焦点线与箭头同色，无持续动画。
- 无生成表时，依赖检查展示中性选择引导，不发 check 请求；定位入口不得自动勾选。后端 `empty_plan` 校验与非空计划阻断仍保留。
- “导出关系图 JSON / 导入关系图 JSON”只对应表与外键关系浏览，保留 `sqlseed-schema-graph` 格式及既有文件兼容性，不暗示完整 schema 导入或数据库建表。

## AI 范围、审阅与保护

- AI 的当前表/勾选表/整库/指定表/指定列范围与生成勾选分离。`ai.js` 传完整 document 与 tableDrafts，展示业务说明、关联来源及服务端只读样例；相同 group_id 只能整组选择并经 model 原子应用。列范围仍保留整表与上游分析上下文，不能扩张允许修改列。初次设置加载、分析、保存和探测期间防止迟到响应覆盖编辑；关闭/epoch/schema 变化后不能应用。
- [js/workbench/ai.js](js/workbench/ai.js) 提供同主题 AI 服务摘要、范围选择与建议审阅；支持当前表、已勾选表、整库、指定表和指定列，明确披露发送结构而非连接/记录。建议默认不勾选，显示当前规则、建议规则和原因后才允许应用。
- AI 面板捕获 model identity / epoch / schema hash；离页、关闭、结构改变、配置改变及过期响应不能应用。保存、检测和分析期间禁用可改变请求含义的控件（包含已列出的模型快捷按钮），迟到结果不能覆写新输入。
- AI 指定字段搜索仅过滤显示，不改变 `allowed_targets` 的既有选择；计数区分已选总量、筛选内与筛选外。选择筛选结果只追加当前可修改字段，清空选择清除全部授权；受保护字段按表折叠说明，仅作上下文，不得加入授权。忙碌时禁用搜索和批量选择，范围变化清除旧建议，生成勾选不变。
- AI 只调用 `/api/workbench/ai`；请求/审阅共用模态生命周期，销毁 dropdown、abort 请求和定时器。缺插件、缺模型或连接失败时显示具体下一步，不以本地匹配伪装成 AI 结果；不能自动选择或加入生成表。
- AI 入口使用 ai-eligibility.js 与服务端保护一致的显式规则判定；数据库分配、PK/FK、实际使用数据库默认值的列、计算列以及已有 derived/native 规则显示保护原因。
- AI DEFAULT 保护按当前实际生成模式判断；生成器主动提供值时可优化，真正省略使用 DEFAULT 时保持保护。PK/FK、计算列及已有派生/原生规则继续保护。追加失败只有完整精确计数才能创建剩余配置，扣除已提交行数，保留原快照与已完成表草稿，不自动提交；中断/未知计数/清空模式不能直接推导剩余量。
- 自定义映射/enrichment 涉及 DEFAULT 时，AI 助手先调用只读 eligibility 预检，并与 suggest 共用实际规则解析；响应只含生成模式，不含样例或父键。普通配置不增加请求；编辑、关闭或离页后的旧结果不得打开可分析界面。

## 设置与服务状态

- 设置页由 `pages/settings.js` 提供 AI 服务、插件与版本；不恢复旧 meta/heal 页面。普通设置由 Web 的 `ai_settings.py` 持久化，密钥保持环境变量或进程内存且按服务绑定。环境接口由 `settings_environment.py` 只读汇总当前 Python 环境。
- 工作台 AI 助手仅展示服务/模型摘要与设置入口；范围、业务说明、分析和审阅继续留在助手。`ai-handoff.js` 只在内存保存明确往返的上下文，身份/epoch/schema/生命周期失效时拒绝恢复。设置检测草稿不保存，不以模型列表成功声称推理成功；保存/检测防重复，迟到响应不覆盖新页面。
- AI 普通设置字段为 backend/model/base_url；`SQLSEED_WEB_SETTINGS_PATH` 可覆盖。UI key 不入磁盘，不随跨 endpoint 切换继承，清除只在当前进程有效。配置表单不把同一进程中的设置称为浏览器私有。
- 保存状态与服务就绪状态分别呈现。无修改须说明原因，本地服务空 Key 不阻止保存；已有密钥提示按服务和 endpoint 匹配，等价地址/本地默认地址不应误判切换，路径改变不能沿用旧凭据提示。
- 普通模式环境页消费后端分类、必要性与安装/修复事实，展示指引；显式维护模式的组件操作见后续维护契约。AI 助手及工作台引导保留 `availability_status`，区分未安装与加载异常。
- 安装指引来自后端针对服务解释器生成的 pip/uv 命令，缺工具明确说明；引擎设置跳转插件页复用指引，不另拼 pip 命令。Faker 仍为 Core 必需依赖，UI 标签为“随 sqlseed 安装”。

## 运行结果

- 运行记录里的 snapshot 固定；轮询网络错误不等于任务失败。running 表数量尚未收齐时显示统计中；中断记录必须显示提交数量不确定。

## 可选组件自动管理

- 默认受管启动由 `automatic_lifecycle` 表示；`enabled` 不等于旧维护模式，不得因安装能力可用而禁用 AI 设置或锁死导航。
- `plugin-management.js` 消费服务端能力，不自行推断可卸载关系。可选组件先请求操作计划，展示具体组件、解释器、依赖影响和重启要求，确认后只提交一次 execute；失败或未知响应不可自动重发。
- 组件安装/卸载在组件行发起，具体计划经确认后仅提交一次；界面显示准备、处理组件、恢复服务的真实阶段。短断连只自动重试读取状态，绝不重发 execute。任务终态后仍须完成能力与服务代次同步；同步失败保留只读重试。
- `recover` 返回完整 management snapshot，`active_task` 是其任务字段；重试恢复不重复安装。`instance_id` 与 `service_generation` 变化后刷新环境和当前连接的表列表；只匹配既有 connId，禁止调用会回退其他数据库的启动恢复逻辑。未保存的 AI 草稿继续保留。
- `data-plugin-supervised-maintenance` 只使恢复期间首次打开的页面落在组件状态，不永久固定设置页；业务暂停由后端准入门禁处理。已打开的页面自动恢复，无需刷新浏览器或输入命令。
- 管理不可用时说明部署限制；管理员命令与解释器信息默认折叠。自动管理可用的缺失可选组件直接给安装按钮，Faker/Core/Web 的必需依赖保护仍来自后端能力。
- 卸载确认与缺组件状态使用具体功能影响提示；AI/引擎的受影响入口保留安装或修复路径。卸载后的可用性刷新不可因未保存设置而跳过，草稿与可用性分别更新。全局和列级引擎缺失须区分，不能静默改为其他引擎。DEFAULT 预检遇 `ai_unavailable` 时显示恢复入口，不能绕过预检进入分析。
- 未受管部署的缺包/异常安装指引收进管理员折叠区，命令原样作为文本复制，不执行。复制在途门禁直到实际结束才释放；环境刷新、切分类、编辑与离页使旧反馈失效。默认受管启动的安装卸载使用下述网页内流程。

## 显式维护模式兼容

- 只有服务端启动时注入的 `data-plugin-maintenance` 能切换维护 shell：隐藏业务导航与连接入口，固定设置页插件分类，不请求 AI 设置。业务隔离还必须由后端执行，不能依靠隐藏按钮。
- 维护状态来自发行包 metadata，`installed` 表示“已安装（待验证）”，不能因 `available:false` 误报导入异常。开始包变更后锁定后续操作，完成后正常重启验证。
- 旧维护模式任务轮询停止于离页、错误或终态；未知结果仍锁定变更动作，但保留只读完整刷新，以恢复服务重启后丢失的任务和新凭据。此兼容流程不再是默认启动的用户路径。

## DOM、键盘与浮层

- 不用原生 `<select>`：嵌入式 WebView 的系统弹窗曾错位。用 `createDropdown()`；genform 新建实例必须经过 `track()`，重渲染前 `destroy()`，避免 document 监听器泄漏。
- 下拉展开时浮层挂在当前 overlay（无弹窗则 body），以视口固定定位避开滚动体裁切，并按剩余空间上下展开。关闭后还原 DOM，移除滚动、窗口与焦点监听；Escape 先关浮层，不能同时丢弃编辑抽屉。测试查找展开选项应从唯一 `.dropdown-floating` 进入。
- `h()` 的 boolean attributes 传真正布尔值；原生 `setAttribute('disabled', false)` 仍会禁用。数组节点用 `append(...nodes)`，直接 `append(nodes)` 会变成文本。
- input 通用宽度规则必须排除 checkbox/radio，避免勾选框挤开标签。
- 自绘 dropdown 遵循 select-only combobox/listbox：初始即提供语义名称、aria-expanded/controls/activedescendant，箭头探索不改值，Enter/Space/Tab 确认、Esc 取消；浮层不可被滚动区裁切。
- date-picker.js 使用 YYYY-MM-DD 文本、自绘日历、月份/年份跳转及网格键盘；无效文本保留并阻止应用。Tab/Escape 由最上层日历优先处理，关闭返回触发点，不误关父抽屉。

## 布局、滚动与动效

- `navigation.css` 保持品牌、四项导航和连接入口的稳定应用外壳；窄屏导航独立成行。当前页状态与键盘焦点分别表达，强制颜色模式也要同时可辨。
- `scrollbars.css` 统一根页面、面板、下拉和表格的滚动条。通用模态与连接弹窗通过 `workbench/scroll-lock.js` 共同锁定背景；最后一个持有者关闭才恢复原滚动位置与原有锁状态。关闭返回焦点使用 `preventScroll`，数据表仍保留必要的横向滚动。
- `app.js` 只在不同已提交顶层页面间添加短暂淡入；初载、同页参数和连接重挂载不播放。不等待动画再执行 import/mount，保留 `routeVersion` 与模块清理，不给页面添加 transform 或持久动画层。
- `disclosure.css` 统一正式页面与弹窗的圆头 Chevron，保留原生 details/summary、已有默认展开状态和整行点击范围；不为图标增加翻译字符串。
- 高度动画同时检测 `::details-content`、`interpolate-size`、离散过渡与 `interactivity: inert`。关闭期间内容立即 inert，展开完成后释放 overflow；缺任一能力时回退原生开合。减少动态效果时关闭新增过渡。
- 弹窗焦点循环包含首个有效 summary，排除隐藏区域和收起内容。CSS 动画的焦点、快速反转和裁切行为必须实测浏览器，Node DOM 回归不能代替。
- 根滚动容器使用稳定滚动条槽位；不支持时保留纵向滚动条空间，避免异步切页改变应用外壳位置。
- CHECK 折叠使用单层边界；展开标题仅上角圆角，长约束换行。运行列表的容器边界与卡片分层，结果文字与查看按钮使用独立布局容器。

## 验证与参考

- 页面变更用浏览器检查首次渲染、切页/刷新、下拉打开后重渲染、NULL 单位、硬约束锁定、derived 配置导入/重置/导出及相关预览。
- 回归从仓库根运行 `pytest plugins/sqlseed-web/tests/ -q` 和 `node --test plugins/sqlseed-web/tests/test_*.cjs`。
- [generator_parity.md](../../../../../docs/superpowers/plans/generator_parity.md) 与 [generator_ui_reference.md](../../../../../docs/superpowers/plans/generator_ui_reference.md) 仅供截图和历史能力差距查询，不是新 UI 检查基线；当前规范不要求照搬分类、空组占位或连接级 locale。
- 浏览器视觉/键盘、真实 LLM 与 PostgreSQL 验收分别记录；计划、历史通过数量和 Node DOM 回归不能证明本次实测完成。

## 历史 genform 回归

仅在维护 `genform.js` 时适用；保留数据库约束、配置往返和参数单位，不将旧面板布局、默认交互或能力裁剪作为当前工作台要求。

- 保持顺序：字段名/类型 → generator → 参数 → 预览/刷新 → NULL/唯一通用区 → 重置。重建时保存明确的 `paramsHolder` 引用，不按第一个 `.genform-section` 猜位置。
- 参数与预览共同使用 `buildCfg()`；UI NULL 百分比是 0–100，提交除以 100，`fromInferred()` 展示时乘以 100。勾选默认 5%，未勾选禁用输入。
- NOT NULL 禁止提交 null_ratio；数据库唯一列强制 unique，优先于通用区裁剪。显式自增主键整面板只读，依据 `ColumnInfo` 判断，不把所有 `skip` 都当成自增。
- 外键身份与引用来源由 schema `foreign_keys` 经 `foreignKeysOf` 传入，不按 generator 标签或 `_id` 名称判断。外键面板先于普通/派生配置显示引用列及预览；可空时允许 NULL 设置，保存为 `foreign_key_or_integer` 并保留采样策略和显式约束，不携带运行时父表值或普通生成器参数。空表自引用初始化不能承诺精确 NULL 比例。
- 外键的单列唯一性使用 schema `unique_columns`，复合主键成员不能仅因 `is_primary_key` 就各自设置 unique。
- `derive_from`/`expression` 必须在 `applyAiYaml`、`showColumnInPanel`、`fromInferred`、`buildCfg`、YAML 保存中保留；derived mode 与 generator 互斥，不能回落成 `string`。
- 派生列展示来源/表达式/预览；用户点“重置属性”才回到 `zeroConfig` 的普通生成器基线，不能以 AI 改写后的 inferred spec 当作原始基线。
- 旧普通生成器均保留 NULL 通用区；旧 `NO_UNIQUE_GENS` 隐藏 text/choice/weighted_choice/bytes 的普通唯一选项，`NO_PREVIEW_GENS` 隐藏 bytes 预览。新工作台不继承此裁剪：有限词表的 unique 根据候选容量和真实能力检查，数据库唯一约束始终保留。
- `schedulePreview()` 对 generator/params/NULL/unique 变化做 400ms 防抖，更新 `previewBox` 并检查 `isConnected`。choice/weighted_choice 缺必填参数时显示“待填写”，不发送注定失败的预览。
- 新参数同时维护 `PARAM_LABELS`、`NUMERIC_PARAMS`/`TEXTAREA_PARAMS` 等显式集合，不用名称正则猜控件类型。
- `HIDDEN_PARAMS` + `normalizeAliasParams()` 合并 pattern/regex 与 weighted_choice 的 choices/weighted_choices；加权值使用对象结构，不把自由文本直接作为对象列表处理。
- JSON generator 的 `schema` 使用 JSON 对象编辑器，不能用 `String(object)` 或按普通字符串提交；无效输入显示错误并保留最近有效配置，停止自动/手动列预览。
- 日期参数以精确日期为主，隐藏年份兼容字段；只有完全没有任何日期/年份边界时，`applyDateDefaults()` 才补默认范围，保留部分 AI 配置。
- date/datetime/time 控件保留“一整天”与时间输入联动、weekday 模式；weekdays 序列化为 `"all"`、`"workdays"` 或 `[0…6]`（Monday=0）。
- bytes 图像/目录两种模式要保留互斥参数清理：切换时删除另一模式参数，避免 core 的 folder 优先级覆盖用户新选择。
- 旧 `GEN_CATEGORIES` 的 `pending` 分类占位仅属历史行为；新工作台不显示空分类，不创建虚构 generator。

## 历史向导与 AI 页面回归

仅约束保留的 legacy 模块与原有 API 集成，不恢复正式产品导航。

- `treeSelection` 通过 `initialSelection` 与 `onChange` 往返保存，返回 Step 2 时不能重置用户或 AI 的表列选择。
- 向导配置按连接隔离；提交时深拷贝连接、表顺序、列配置和数量，所有后续请求使用同一快照。异步返回必须核对连接及页面版本。
- YAML 导出以完整配置对象调用 `/api/config/serialize`，不手拼 YAML；内部 `null_ratio` 始终为 0–1。导入的根级 associations/custom mappings 仅保留导出，向导需明确提示执行边界。
- browse 为每个连接独立读取表列表，选择后同时更新连接 ID、target、tables 和持久化记录；旧请求不能覆盖新选择。
- `applyAiYaml()` 替换当前列配置，只接受当前 schema 中存在的表/列，并同步树标注与当前属性面板；该动作不写库，写库由 Step 3“开始生成”触发。
- 读取 `/api/ai/config` 的有效配置做就绪检查：AI 已安装且本地 backend 或在线 key 可用；点击生成时再探测连接。不要把本地 backend 错拦在 API key 检查上。
- AI job 使用更长轮询预算（wizard 当前 900 次）；普通 fill 的 `pollJob` 默认 120 次、间隔 400ms，不能套给可能运行数分钟的 LLM 流程。
- 展示 `job.result.llm_calls`，允许 0；Step 3 填充遵循外键 topo-order。当前预览按选中表列表迭代，不要误称预览也已拓扑排序。
