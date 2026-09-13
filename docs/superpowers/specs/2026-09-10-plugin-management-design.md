# Web 可选组件自动管理

2026-09-11 修订：根据用户要求，网页操作不再依赖手动切换启动模式或重启。本设计替代 2026-09-10 的普通用户维护命令流程。实现完全位于 Web 插件，不改变 Core public API。

## 生命周期与部署边界

默认 `sqlseed-web` 和 `python -m sqlseed_web` 启动稳定 supervisor，绑定 `127.0.0.1:8630` 并持有监听 socket。业务和维护 worker 通过 spawn 启动，轮流继承同一 socket；不引入 HTTP 代理，原有流式 NDJSON 路由不变。supervisor 保留管理 token、计划、任务状态和切换期间的会话快照，不导入可选插件或连接数据库。

业务 worker 的全部非管理 HTTP 请求从 ASGI 入口到真实响应结束都持有 lease。生成、auto-heal、工作台执行及 AI 分析线程在启动前登记后台 lease，并在实际退出后释放；取消响应不冒充 SDK 线程已停止。确认执行时，RuntimeGate 在同一锁内检查计数并关闭准入。仍有请求或后台工作时立即返回 409 `plugin_management_busy` 与活动计数，不取消任务、不等待数分钟，也不强杀业务进程。

空闲切换顺序：暂停准入 → 导出连接与 AI 会话 → 业务 worker 自然退出 → 维护 worker 提供设置和进度 → 执行包变更 → 停止维护 worker → 新业务 worker 恢复会话 → 开放准入 → 发布任务终态。维护 worker 不加载业务 router，仅允许 health、environment、管理及静态页面。启动未就绪的业务 worker 保持准入关闭；仅此阶段的超时进程允许回收。

会话快照只经有界匿名 IPC 传递，parent 仅在内存暂存原连接 ID、原目标及凭据、provider、locale 和完整 AI 会话覆盖标记。成功恢复后清除原始快照；响应只保留不含凭据的恢复摘要。浏览器不 reload，保持工作台草稿、DOM 和当前连接选择；新 worker 以相同连接 ID 真实连接并反射表验证。缺失 SQLite 文件不会自动创建；部分连接失败单独报告，不静默切换其他数据库。SQLite 私有或共享内存连接无法跨进程恢复，操作在停止业务前返回 409 `plugin_session_not_restorable`。

包变更失败仍尝试恢复业务服务，不自动回滚部分安装。恢复失败时保持维护页面，用户可在页面重试恢复；该操作绝不重复安装或卸载。意外业务 worker 退出也切换到恢复页面；这类异常退出无法恢复没有事先导出的内存会话。任务历史仅保存在 supervisor 内存，整个服务重启后不提供历史管理日志。

外部 `create_app()` 托管没有 supervisor 能力，返回真实不可用原因；普通业务仍可使用。旧 `--manage-plugins` 作为兼容维护入口保留，仅此旧模式保留手动重启语义，不是普通页面推荐流程。

## 环境与可操作组件

仅管理当前解释器所在的可写独立 virtualenv。系统 Python、EXTERNALLY-MANAGED、共享系统 site-packages、环境外安装目录或 distribution metadata 均禁止执行。首版支持 macOS/Linux，Windows 普通 Web 仍可用；在完整实现并验证 Windows 子进程树超时回收前，不开放界面包变更。

| id | Distribution | 操作 |
| --- | --- | --- |
| ai | sqlseed-ai | 缺失时安装，反向依赖允许时卸载 |
| cli | sqlseed-cli | 缺失时安装；保留 AI 时不可卸载 |
| mcp | mcp-server-sqlseed | 缺失时安装，反向依赖允许时卸载 |
| mimesis | mimesis | 缺失时安装，反向依赖允许时卸载 |

Core、Web、Faker 必需；Base 内置，均不接受管理请求。卸载仅传递一个白名单 distribution，不递归清理依赖。反向依赖从已安装 Requires-Dist 解析有效 Python/platform markers；extra 默认空，历史安装 extra 不会使 Web 的可选 AI 依赖阻止卸载 AI，AI 的必需 CLI 依赖会阻止卸载 CLI。

管理和维护环境页只读取 distribution metadata，不导入可选插件。恢复后的业务环境页重新验证可选模块的加载状态。包管理计划不保证依赖可解析，也不保证新安装插件的全部业务能力通过验证。

## 安全与互斥

管理 API 要求实际 client 及 Host 为 loopback literal 或 localhost，拒绝重复/畸形 Host、DNS rebinding 域名、跨 Origin 和跨站 fetch。POST 要求严格同 Origin 及管理状态返回的随机 token（`X-Sqlseed-Management-Token`）。token 只在服务内存保存并跨 worker 切换保留；管理响应 no-store 并禁止 frame 嵌入。

默认 supervisor 在整个生命周期持有环境独占 flock；外部正常 app 持有共享锁，旧维护服务持独占锁。业务子进程继承同一文件描述符，因此父进程意外退出时仍保护环境；发现 IPC 断开后，子进程关闭新业务准入，等待已有工作自然结束再关闭连接和退出。不能在另一端口并行启动遵守此锁的服务。旧版本 Web 和任意外部 pip/Python 不遵守该协议，锁无法强制协调它们；服务不会扫描或终止外部进程。不可写或其他本就不可管理环境不要求新增可写锁，保留正常使用。

安装器仅为当前解释器 `-m pip`，或检测到的 uv 加固定 `--python`。HTTP 不接受解释器、版本、URL、目录、shell、额外参数或任意包名。安装约束文件冻结全部已有版本，只安装 wheel，不升级或重装已安装环境，也不下载解释器。卸载后不自动清理依赖。子进程使用受控环境、进程组超时、有界输出和敏感信息脱敏；超长行整体丢弃至换行。真实成功要求退出码为零、目标 metadata 符合操作且已有其他 distribution 保持不变。

## API 契约

- `GET /api/settings/plugins/management`：保留 enabled、available、reason、python_executable、token、active_task、components，增加 automatic_lifecycle、instance_id、service_generation、phase、service_ready、session_restore。受管流程 restart_required 恒为 false，maintenance_command 为 null。session_restore 在任务完成后继续返回，直至下次恢复更新。
- `phase`：ready、preparing、installing、restoring、recovery_failed；忙碌执行以 409 的明确活动计数表达。
- `POST /api/settings/plugins/plan`：仅 component_id 和 install/uninstall，返回影响与当前 metadata 快照绑定的计划，有效五分钟，仅保留最新计划。
- `POST /api/settings/plugins/execute`：仅 plan_id。原子空闲检查通过后，一次领取计划并返回 202 任务；执行前重验环境和 metadata，不允许重复 execute。
- `GET /api/settings/plugins/tasks/{id}`：running/succeeded/failed、stage、message、output、returncode、service_ready。新业务真正恢复前不发布安装成功终态。
- `POST /api/settings/plugins/recover`：仅 recovery_failed 可用，返回 202 管理状态，只恢复业务，不重放包操作。

切换 socket 的短暂连接中断由前端有限重试 GET 轮询处理，不自动重发 execute。维护启动的 HTML 使用独立固定标记跳到插件页，不能因此永久禁用恢复后的导航。

## 验证

API 测试使用临时真实 dist-info，包含安全、白名单、反向依赖、快照失效、单任务互斥和错误状态。真实 pip/uv 安装测试只使用临时 virtualenv 与本地 wheel，无网络、不改变用户环境。运行 gate 测试覆盖 HTTP 及后台 lease、取消后真实工作仍忙和关闭准入后自然退出；session 测试使用真实 SQLite 验证原身份、provider/locale、密钥内存恢复、内存库拒绝及部分重连失败。

真实 HTTP 集成通过随机端口运行完整业务→维护→业务进程切换，安装边界受控，断言同端口、原连接 ID、数据库记录不变、恢复后就绪和实际环境包列表不变；进一步验证父锁句柄关闭后子进程仍持锁、IPC 断开后子进程自然退出再释放锁。前端独立验证进度、轮询重连、恢复重试和不刷新草稿。
