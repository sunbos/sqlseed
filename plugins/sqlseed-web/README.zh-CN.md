# sqlseed Web

[English](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-web/README.md)

面向 SQLite 与 PostgreSQL 声明式测试数据生成的本机浏览器工作台。连接数据库、编辑字段规则、预览样例、检查依赖并查看生成结果。Python core 离线运行；AI 建议是可选功能。

## 工作台概览

![sqlseed Web 简体中文浅色界面：左侧选表和四表关系图](https://raw.githubusercontent.com/sunbos/sqlseed/992ba0e733d5b41f73e37b0a9d02d573d6e2bb23/docs/assets/screenshots/web-workbench-zh-CN-light.png)

0.2.5 正式界面的实际截图，使用仓库中的虚构 SQLite 订单示例。
[查看原尺寸高清 PNG](https://raw.githubusercontent.com/sunbos/sqlseed/992ba0e733d5b41f73e37b0a9d02d573d6e2bb23/docs/assets/screenshots/web-workbench-zh-CN-light.png)，
或[查看深色主题下的只读样例预览](https://raw.githubusercontent.com/sunbos/sqlseed/992ba0e733d5b41f73e37b0a9d02d573d6e2bb23/docs/assets/screenshots/web-workbench-zh-CN-dark.png)。

连接已有数据库 → 选择表和生成数量 → 核对字段规则与依赖 → 预览样例 → 确认生成计划。

| 页面 | 可以做什么 |
| --- | --- |
| 工作台 | 编辑规则、浏览关系图、只读预览样例，并确认生成。 |
| 配置管理 | 保存可复用规则、导入导出 YAML、重新打开对应数据库的配置。 |
| 运行记录 | 查看逐表结果、实际已提交行数和本次使用的配置快照。 |
| 设置 | 调整生成默认值、浅色/深色外观、可选 AI 设置与组件。 |

[订单工作流示例](https://github.com/sunbos/sqlseed/tree/main/examples/order_workflow)提供建表结构、生成规则和操作说明，可用于创建自己的独立演示库。

## 安装

本文安装说明对应 0.2.5 版本；发布状态以 [Releases](https://github.com/sunbos/sqlseed/releases) 为准。测试尚未发布的候选版本时，使用下方的源码安装方式。请先创建并激活 Python 3.10+ 虚拟环境：

```bash
python -m pip install "sqlseed==0.2.5" "sqlseed-web==0.2.5"
sqlseed-web
```

打开 `http://127.0.0.1:8630`。wheel 包含前端，使用时无需 Node 或 npm 构建。PostgreSQL 还需安装 `"sqlseed[postgres]==0.2.5"`。Core 0.2.4 及更早版本缺少本版本所需的共享连接和诊断接口。

开发源码从仓库根同时安装 Core 与 Web：

```bash
python -m pip install -e . -e ./plugins/sqlseed-web
```

0.2.5 版本及其源码候选要求 Core `>=0.2.5.dev0,<0.3`，用于连接目标解析与诊断脱敏。请使用匹配的 Core 与 Web 版本，不要关闭依赖检查来保留旧 Core。

## 界面语言

0.2.5 版本在顶栏提供 **简体中文 / English**。浏览器记住选择，并与同源标签页同步。没有已存偏好时，采用浏览器偏好中第一个支持的语言，无匹配则使用 English；存储不可用时仍能在当前页切换。

切换就地更新标签、帮助和受支持的诊断，不刷新页面、不提交表单，也不发数据库或 AI 请求；未保存的修改、焦点和选择保持不变。**数据语言与地区**是独立的生成配置：切换界面语言不改变生成内容、配置名称、表列标识、YAML 或数据库原值。旧记录或第三方诊断可能保留原文，并附当前语言说明。

语言资源随 wheel 分发，不需要翻译服务。覆盖与新增文案所需验证见 [Web 双语维护](https://sunbos.github.io/sqlseed/development/web-i18n/)。

## 可选组件

在“设置 → 插件与版本”查看组件可用性及受影响功能。Base 内置，Faker 随 Core 安装，Mimesis 可选。只有模型辅助规则建议需要 AI；接受后的规则可以离线执行。

工作台要求 0.2.4 发布线的 AI 接口；旧包即使可导入，也不会被报告为可用。源码开发时在同一次解析中安装本地 Core、CLI、AI 与 Web：

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai -e ./plugins/sqlseed-web
```

0.2.5 使用 `python -m pip install "sqlseed-web[ai]==0.2.5"` 安装可选 AI 组件。页面不会回退到不兼容的旧版本。

0.2.5 的默认启动器可在受支持、可写的 Windows、macOS 与 Linux 虚拟环境中管理可选包，并自动恢复服务。外部托管、只读或系统环境仍可使用工作台，但不开放网页包变更。组件缺失会显示原因和恢复入口，不会静默替换配置中的引擎。更新必须审阅兼容 wheel，保持其他已安装组件的版本；Core 与 Web 由环境的包管理工具更新。

## 数据与部署边界

预览不写入生成记录。正式生成必须明确确认；分批失败可能保留此前已提交的数据，重试前应核对运行结果。演示使用测试数据库或可丢弃副本。

服务面向一个可信的本机用户，没有多用户认证，默认只监听 loopback。不要直接暴露到不可信网络；同源请求检查不能替代认证或数据库权限。

详见[工作台指南](https://sunbos.github.io/sqlseed/web-workbench/)与[支持边界](https://sunbos.github.io/sqlseed/maintainable-release/)。

## 依赖

- Python `>=3.10`
- `sqlseed>=0.2.5.dev0,<0.3`
- `fastapi>=0.110`
- `uvicorn>=0.29`
- `pyyaml>=6.0`
- `packaging>=23.2`
- 可选 `ai` extra：`sqlseed-ai>=0.2.4.dev0,<0.3`

## 开发验证

```bash
pytest plugins/sqlseed-web/tests/
node --test plugins/sqlseed-web/tests/test_*.cjs
```

许可证：[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE)。发行包包含完整 LICENSE 文本。
