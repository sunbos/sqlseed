# 第四轮：清除剩余 88 条 CodeFlow 告警

起点：`34fa7b236bc965e34c191c30fbb71d0808c8cfbd`，0 errors / 88 warnings。
2026-09-12 17:38 UTC 再次读取公开 API，确认 3 项分析全部完成，计数仍为 88。
本轮未修改 `.pylintrc`、ESLint/jscpd 配置、规则阈值或依赖版本，没有增加抑制注释。

## 实现

- 51 条过宽异常捕获：区分配置、数据库、I/O 和程序错误；schema metadata 使用带原异常链的读取契约。生成会话统一管理提交计数与失败结果，后台 Future 统一发布结果及原异常。
- 11 条精确类型检查：复用 `has_exact_type()` TypeGuard，仍拒绝布尔计数、错误内建类型和子类。
- 10 条集合成员判断：AI 先规范化 generator 名称，再使用共享 family 集合；非法 list/dict 不再在推断阶段引起哈希异常。布尔 enum 先识别数值类型。
- 2 条资源所有权：安装进程由 Popen context 管理，失败/超时清理整个进程组；IPC 用有界回复任务集合管理完整生命周期，线程启动失败也释放容量。
- 7 组重复代码：日期方法通过普通函数 factory 绑定 bookkeeping policy，保持实际关键字签名、类型反射、seed/RNG 和 Base fallback 行为；stream 由每行对象管理已接受的唯一键；真实 healer 测试复用已有运行时工厂，类型引用使用模块命名空间。

## 随整改发现并修复的问题

- 验证脚本原来忽略 `GenerationResult.errors`，部分失败被记作成功并按请求行数累计。现在检查返回错误并只累计实际提交行数。
- 修复策略先处理独立候选，成功后再替换列配置；失败不留下已修改一半的参数。
- 表达式/AI worker 的进程控制异常通过 Future 传递，避免变成 `None` 成功结果。
- 安装输出线程启动失败、安装父进程先退出而后代仍持锁，都由同一资源生命周期清理。
- 收窄异常种类后，后台任务使用独立终态保障：未知错误继续传播，但必须释放占用并记录失败。独立审查覆盖 legacy fill/auto-heal、快照读取、执行、终态存储和会话恢复。

## 验证证据

- 完整 pytest：**3484 passed / 47 skipped**，187.68 秒；ResourceWarning 与 PytestUnraisableExceptionWarning 作为错误。
- Pylint 2.17.7：426 文件，**0 条**；ESLint 8.57.1：37 文件，**0 errors / 0 warnings**；jscpd 4.0.5：434 文件，**0 clones**。
- Ruff、432 文件格式检查、mypy 163 source files、3 项 import-linter contracts、文档标记检查全部通过。
- 真实独立 smoke：14 passed / 0 failed。日期 41,280 次、stream 960 组旧新差分一致，完整 Web generator catalog 保持一致。
- 独立审阅新增 8 个 Web 失败回归全部通过；Core 审阅独立运行 38 个相关测试通过。前述后台终态缺陷已修复后重新验证。
- 五包 sdist → wheel 构建及 10 个产物的 Twine strict 检查通过；完整/最小环境安装后 smoke、pip check 和锁定依赖核对通过。225 个打包文件与源码及实际安装内容逐字节一致；MkDocs strict 通过，用户环境与原产物保持不变。

详见 [机器可读结果](verification.json) 与 [完整 pytest 日志](pytest.log)。此处为推送前本地结果；远端结果以新提交的 CodeFlow 页面为准。

历史 `third-pass/` 中的 88 条保留理由已经由本轮实际重构取代。默认 mutation gate 的 8 个历史幸存变异与 Codecov 账户侧 `Repository not found` 是前轮已有状态；本轮不改 mutation 目标或上传配置，也不宣称它们通过。没有执行合并或发布。
