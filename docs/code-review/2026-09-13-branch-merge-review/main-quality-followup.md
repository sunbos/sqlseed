# 主分支 Sonar 后续修复

PR #10 合并为 `b9142c2c179bd1204ecb12481451d8c58aebc777` 后，main 的完整分析仍列出 19 项 OPEN。此前 PR 的新代码视图只列出 1 项，两者范围不同。28 项旧漏洞已由分析自动关闭，main 当前无 bug、vulnerability 或 security hotspot。

本次处理其中 18 项，保留用户明确暂缓的 `sqlseed.fill` 参数数量 S107，不修改公开 API、不登记 Accepted 或 false positive。

## 改动与依据

- 6 项维护性问题：简化 AI 分析路由、prompt 降级、模型选择、macOS RAM 解析和文档同步的嵌套控制流。保留请求次数、事件顺序、返回值、异常边界及文档命令输出。
- 8 项测试状态恢复问题：用 monkeypatch 恢复硬件缓存属性和表达式函数字典项。改前探针确认测试会泄漏全局状态；改后恢复原对象身份、原内容和已有字典项。
- 2 项测试表达问题：拆开非空与具体值断言；把不会抛出目标异常的 generator 构造移出 `pytest.raises`。
- 2 项分析误报：Pydantic 缓存采用官方支持的下划线私有属性默认值声明，保留精确类型；删除 timeout 字段已经解释过的重复行内注释。新增真实模型实例、schema 和 JSON round-trip 验证，不添加抑制规则。

## 本地验证

所有命令使用隔离 worktree 的五包源码导入路径，未修改用户环境。

- Python 3.12 完整 pytest：3646 passed、65 skipped，ResourceWarning 和 PytestUnraisableExceptionWarning 按 error；跳过项需要本机没有提供的 PostgreSQL / Docker、真实 LLM 或可选图像依赖。
- Node：669 passed；ruff、format、mypy（166 个 source files）、3 个 import contracts、doc-sync、MkDocs strict 全部通过。
- 1474 组旧新行为对照一致；独立审阅的 103 + 227 项测试通过，无 skipped。
- 修改的 10 个 Python 文件经 Pylint 2.17.7 扫描，0 diagnostics；jscpd 4.0.5 同范围默认扫描 447 个实际 source，0 clones。
- 本次不修改默认 mutation 目标 `unique_adjuster`、runner 测试或配置。逐文件 SHA256 核验与本轮先前 fresh mutation gate 一致，沿用其 246/246 killed、其他状态均 0 的结果；不把此结果称为 AI 重构的 mutation 覆盖。

云端 Sonar 是否关闭这 18 项，必须以该后续提交及合并后 main 的新分析为准。跨平台测试、真实 PostgreSQL 和分发包安装继续由 PR / main CI 验证。

## 风险与未完成项

独立代码审阅未发现行为回归。AI 分支对照使用确定性 LLM 边界输入，没有调用真实模型；不能据此宣称某个真实 LLM 环境已验证。既有五包迁移和真实后端限制仍按主审查记录执行。

Contributors 的 traeagent 显示尚未清除，用户已选择等待 GitHub 统计刷新；详见同目录的 GitHub Support 记录。没有公开发帖或为此改写合法提交历史。
