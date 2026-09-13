# CI 与发布维护

继承 [根指南](../AGENTS.md)。本目录管理开发校验、锁定依赖、发行包和文档部署；以 workflow 与 composite action 的实际实现为准。

## 修改入口

| 范围 | 入口 |
|---|---|
| 测试矩阵、质量门禁、包验收 | [ci.yml](workflows/ci.yml) |
| 第三方依赖与本地五包安装 | [install-ci-deps](actions/install-ci-deps/action.yml)、[setup-env](actions/setup-env/action.yml) |
| 依赖锁更新方法及平台限制 | [DEPENDENCIES.md](DEPENDENCIES.md) |
| 源码事实同步 | [doc-sync.yml](workflows/doc-sync.yml) |
| PyPI 构建、上传、正式发行验收 | [publish.yml](workflows/publish.yml)、[发布指南](../docs/releasing.md) |
| GitHub Pages | [mkdocs-deploy.yml](workflows/mkdocs-deploy.yml) |

## 依赖与测试

- CI 先安装带哈希的 bootstrap/第三方依赖，再用 `--no-deps --no-build-isolation` 一次安装本地五包，最后 `pip check`。不要让 editable 插件从 PyPI 解析另一个 Core。
- 更新 `.in` 后按 `DEPENDENCIES.md` 重新导出对应 `.txt`；已有三个 `uv.lock` 是开发依赖锁，不能替代 CI 的哈希文件。
- 保留 `--require-hashes` 与 binary policy；`glob2`、`mutmut` 的源码包例外有明确哈希和 bootstrap 前提，不扩大为任意源码构建。
- Linux 覆盖 Python 3.10/3.12/3.13，macOS/Windows 兼容性任务使用 Python 3.12 并将资源泄漏 warning 视为错误。不要通过删除平台或全局过滤 warning 使 CI 变绿。
- PostgreSQL job 使用专用 service 数据库，运行全部 `test_pg_*.py` 和 URL e2e；真实 LLM 验收另行记录，不能由离线测试推定。
- `packages` 验收五包 sdist/wheel、严格 metadata、已安装入口及 Core/Web 最小环境。最小环境不能混入 CLI/AI/MCP/Mimesis 等可选组件，否则无法证明缺组件行为。

## 触发与发布边界

- `codex/` 分支 push 不在当前 CI push filters 中，向 main 的 PR 会触发 CI。PR 上 `docs` 部署被跳过是预期行为，strict MkDocs 构建仍由 lint job 执行。
- main 的 Pages 部署依赖 lint、测试矩阵、兼容性、集成、property-tests 和 packages 全部成功；保持 reusable workflow 与 `github-pages` environment。
- PyPI 使用同一 `pypi` environment 发布五个 distribution；不要为了包名不同重新拆出 environment。Trusted Publisher 的 owner/repository/workflow/environment 必须与实际发布身份一致。
- 发布只使用已解析 tag 对应的确定 commit；构建、测试与上传不得混用移动的 main。保持固定 action SHA、最小权限和现有 attestation 检查。
- 五包上传后必须检查 `verify-public` 及其 `public-pypi-acceptance` artifact；手动重验已有版本使用 workflow 的验证选项，不改写 tag 或尝试覆盖 PyPI 已有文件。

## 验证

修改 workflow 时核对 YAML、job 的 `needs`/条件/权限和引用路径；依赖变更运行锁定安装与 `pip check`。最终以对应 commit 的 GitHub Actions 结果为准，不能拿旧 run、仅本地构建或 skipped job 声称本次发布已通过。
