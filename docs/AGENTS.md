# 文档维护

继承 [根指南](../AGENTS.md) 的文档同步矩阵；本文件补充读者、内容归属与站点规则。

## 内容放置

| 读者需求 | 维护位置 |
|---|---|
| 了解用途、安装并完成第一次生成 | 根 README.md / README.zh-CN.md 与 [index.md](index.md) |
| 完整 generator、表达式、CLI、hooks 参考 | [guide.md](guide.md) |
| Python public API | [api.md](api.md)，由 mkdocstrings 读取源码 |
| 工作台操作、AI 审阅、组件管理 | [web-workbench.md](web-workbench.md) |
| 架构与配置模型 | [architecture.md](architecture.md) / [architecture.zh-CN.md](architecture.zh-CN.md)，结合根 ARCHITECTURE.md |
| 升级兼容与发布验收 | migration 双语文档、[maintainable-release.md](maintainable-release.md)、[releasing.md](releasing.md) |

- README 保留任务入口、最小可运行示例和参考链接；私有方法名、CHECK 模式逐项清单和历史实现细节不重新堆回首页。
- API/参数/依赖/能力以 manifest、实现和 CI 为依据；历史计划、评审日志和测试数量不能代替当前行为。区分确定性生成、显式 AI 请求、已验证范围与未支持能力。
- 面向普通用户的安装与启动应使用正式包入口，示例自行创建临时数据库和 schema；维护者验收脚本不是产品启动依赖。SQLite/PostgreSQL、五包边界、AGPL 许可证保持一致。
- 修改有中英文对应版本的语义内容时同步两份；根 README 是摘要，完整参考链接指向对应维护页，避免复制多份可漂移的长表。
- GitHub Wiki 是独立 Git 仓库，作为入门和文档导航；这里修改不会自动发布 Wiki，也不在 Wiki 复制完整 API 参考。

## 同步与构建

从仓库根、安装根指南中的 docs extras 后运行：

```bash
python scripts/sync_docs.py
python scripts/sync_docs.py --check
pytest tests/test_doc_sync.py
make docs-build
```

- 不手改 `AUTO-GENERATED` 区域；数量与名称由 `scripts/_fact_extractors.py` 从源码提取。普通说明、例子和未使用标记的表格仍需人工核对。
- 发布范围由根 `mkdocs.yml` 的 nav/exclude_docs 决定。评审记录、设计稿、原型及本 AGENTS 不作为用户站点页面；保留已发布页面的 strict 校验，不通过全局忽略 warning 掩盖断链。
- 新增正式页面时补 nav 和相关入口；移动内容时检查相对路径、标题锚点及双语链接。构建输出不提交。
- 文档构建通过不证明命令或代码示例可用；变更入门例子时实际运行，发行功能声明以相应安装环境的验收结果为依据。
