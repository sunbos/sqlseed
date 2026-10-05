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
| GitHub Pages | [mkdocs-deploy.yml](workflows/mkdocs-deploy.yml)、[部署维护说明](PAGES.md) |

## 依赖与测试

- CI 先安装带哈希的 bootstrap/第三方依赖，再用 `--no-deps --no-build-isolation` 一次安装本地五包，最后 `pip check`。不要让 editable 插件从 PyPI 解析另一个 Core。
- 更新 `.in` 后按 `DEPENDENCIES.md` 重新导出对应 `.txt`；已有三个 `uv.lock` 是开发依赖锁，不能替代 CI 的哈希文件。
- 保留 `--require-hashes` 与 binary policy；`glob2`、`mutmut` 的源码包例外有明确哈希和 bootstrap 前提。仅 Intel macOS 额外允许锁定的 `cryptography` 源码包，Python 构建依赖由 `requirements-macos-build.txt` 锁定，使用原生 Rust/Xcode/OpenSSL；不降级依赖、不扩大为任意源码构建。
- Linux 覆盖 Python 3.10/3.12/3.13；macOS 原生 ARM64 覆盖 Python 3.12/3.13、Intel 和 Windows 覆盖 3.12，并将资源泄漏 warning 视为错误。macOS 也运行 Node 前端与 Pages 回归。不要通过删除平台或全局过滤 warning 使 CI 变绿。
- Linux 工作流固定使用已验收的 `ubuntu-24.04`，避免 `ubuntu-latest` 的镜像迁移自动改变测试或发布环境；升级镜像时单独验证完整矩阵、包安装与覆盖率上传。
- Codecov 上传 pytest 已生成的 XML：保留明确的文件名、`disable_search: true`、`plugins: noop`、OIDC 和上传失败门禁，避免重复生成报告或启动无关语言工具；文件路径修复仍由上传器执行。
- 上传统一使用 `actions/upload-coverage`：仅在临时 keyring 内核验 Codecov 官方固定指纹并建立 direct/full 信任；导入官方唯一主键后开启 `import-options merge-only` 并关闭自动导入/获取，后续上游再次下载只能更新既有主键，不能添加其他签名者。保留上游 GPG 与 SHA256 校验；keyring 只对上传步骤生效，完成或失败均清理。密钥轮换时先核对官方[完整性校验说明](https://docs.codecov.com/docs/codecov-uploader#integrity-checking-the-codecov-cli)和 action 的密钥来源，不能改为 ultimate/always 信任或跳过验证。
- 根 `codecov.yml` 等待 Python 3.12 的 Linux、Windows、原生 ARM64 macOS、原生 Intel macOS 四份报告，并将覆盖率下降容差设为 0、缺报告视为失败；保留组织级覆盖率目标，不通过降低目标、排除源码或 informational 状态使检查通过。修改后用 Codecov `/validate` API 验证配置。
- 分支保护依赖稳定的 `test-compat (windows-latest)` 与 `test-compat (macos-latest)` 检查名称。Windows 矩阵项保留前者；后者是等待完整兼容性矩阵的汇总 gate，必须在失败、取消或跳过时失败，不能仅用 success 条件跳过 gate。macOS 各架构/Python 任务仍保留独立且唯一的检查名称，Pages 也等待汇总 gate。
- Sonar 保留 Automatic Analysis，与既有 Actions 测试和 Codecov 配合；根 `.sonarcloud.properties` 由默认分支读取。`sonar.exclusions` 仅精确列出已核验文件头的图片/字体二进制资产，避免 PR 变更元数据识别字符集时误将其当作文本；所有源码、测试、脚本和 CI 配置仍在原有范围内。调整该列表时核验文件类型与前后代码分析范围，不能加入目录通配符或代码路径来消除告警。CI 扫描迁移是可选方案，不能将新增 token 当作现有自动分析工作的前提。
- PostgreSQL job 使用专用 service 数据库，运行全部 `test_pg_*.py`、URL e2e 与 Web 的 `test_workbench_postgresql_cycles.py`；初始化显式使用 SCRAM 密码认证。真实 LLM 验收另行记录，不能由离线测试推定。
- `packages` 验收五包 sdist/wheel、严格 metadata、已安装入口及 Core/Web 最小环境。最小环境不能混入 CLI/AI/MCP/Mimesis 等可选组件，否则无法证明缺组件行为。

## 触发与发布边界

- `codex/` 分支 push 不在当前 CI push filters 中，向 main 的 PR 会触发 CI。PR 上 `docs` 部署被跳过是预期行为，strict MkDocs 构建仍由 lint job 执行。
- main 的 Pages 部署依赖 lint、测试矩阵、兼容性、集成、property-tests 和 packages 全部成功；保持 reusable workflow 与 `github-pages` environment。
- Pages 使用固定正式版本的 `actions/github-script` 调用官方 REST API，校验上传制品属于当前仓库、运行与提交，保留 OIDC。部署逻辑修改需运行 `node --test tests/test_deploy_pages.cjs`；CI 在部署所用的官方 Node 24 runtime 中执行同一组测试。不要打印可能含 OIDC 请求体的 SDK 异常。
- PyPI 使用同一 `pypi` environment 发布五个 distribution；不要为了包名不同重新拆出 environment。Trusted Publisher 的 owner/repository/workflow/environment 必须与实际发布身份一致。
- 发布只使用已解析 tag 对应的确定 commit；构建、测试与上传不得混用移动的 main。保持固定 action SHA、最小权限和现有 attestation 检查。
- 五包上传后必须检查 `verify-public` 及其 `public-pypi-acceptance` artifact；手动重验已有版本使用 workflow 的验证选项，不改写 tag 或尝试覆盖 PyPI 已有文件。

## 验证

修改 workflow 时核对 YAML、job 的 `needs`/条件/权限和引用路径；依赖变更运行锁定安装与 `pip check`。最终以对应 commit 的 GitHub Actions 结果为准，不能拿旧 run、仅本地构建或 skipped job 声称本次发布已通过。
