已检查 CodeFlow 官方文档、公开 app bundle 和完整公开 GraphQL schema，未发现可用的服务端 Python 依赖安装或分析环境设置入口。schema 包含 81 个类型、16 个 query、9 个 mutation；CommitOptions 仅有 thresholds。此结论仅覆盖公开接口，不能推断后台内部或支持渠道没有能力。

[CodeFlow 文档](https://www.getcodeflow.com/pylint-configuration.html) 指定根目录 .pylintrc，但未公开配置继承机制。其旧默认值无法代表当前真实分析配置。Pylint 的 init-hook/sys.path 和 source-roots 可处理模块查找，不能安装第三方依赖；不应把 init-hook 中执行 pip install 当作受支持流程。

公开只读查询发现：旧 5b0dd07 和新 064854c 的 Pylint defaultConfig 均为 true；ESLint 从 true 变 false，jscpd 均为 true。因此 defaultConfig 不能单独证明本轮 Pylint 是否加载或替代自定义配置。完整响应保存在 `/tmp/sqlseed-codeflow-default-config-probe.json`。

同一前端包含 Codeac 品牌分支。[Codeac 当前 Pylint 默认](https://www.codeac.io/documentation/pylint-configuration.html) 的 11 个扩展和 11/27/100 复杂度阈值，与旧报告特征相符；py-version3.7.2 可解释 assignment-expr 检查不触发。这只是相关实现旁证。Pylint 2.17.7 源码确认该检查要求 py-version>=3.8，不能为减少告警而将本项目 Python>=3.10 配成3.7。

保留受控 CI/本地完整依赖分析；若服务只能部分分析依赖，应准确记录覆盖边界，不能把忽略依赖等同于完整分析已恢复。未登录、未读取凭证、未执行远端 mutation 或重跑，未修改仓库。详细证据、公开 schema 与限制见同名 JSON。
