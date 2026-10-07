# 发布与验证版本

源码、文档和 PyPI 是三个独立的交付环节。合并成功会更新仓库；主分支 CI 通过后，Pages 工作流部署文档。PyPI 的项目介绍来自各发行包的 README 元数据，因此只修改 GitHub 不会更新已经上传的包。详情见 [PyPA 的 README 指南](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/)。

## 准备五个发行包 {#prepare-the-five-packages}

五包结构从 0.2.4 开始。Core（`sqlseed`）、CLI（`sqlseed-cli`）、AI（`sqlseed-ai`）、MCP（`mcp-server-sqlseed`）与 Web（`sqlseed-web`）必须基于同一个已审查提交和版本标签发布。不要将 0.2.3 Core 与新插件混用。[升级指南](migration.md)说明了入口变更与兼容边界。

发布前：

1. 通过全部必需检查后合并已审查的改动。遵循根目录的[发布清单](https://github.com/sunbos/sqlseed/blob/main/CLAUDE.md#release-checklist)，包括两份变更日志和本地变异测试门禁。同步更新根目录中英文 README、各包 README 与正式指南中的当前安装示例和能力说明；保留历史发布记录。包 README 中使用文档的绝对链接，确保在 PyPI 上也能打开。
2. 构建全部五个 wheel 和 sdist，对十个产物运行 `twine check --strict`。检查包名与版本匹配、每个压缩包都包含 AGPL 许可证正文，以及元数据中的 README、依赖和 Documentation URL 正确。
3. 在全新环境中安装这组产物，并运行下文的发行包检查。检查构建后的文档和 README 链接，包括实际渲染效果。元数据检查无法验证排版。
4. 确认五个项目的发布身份一致：所有者 `sunbos`、仓库 `sqlseed`、工作流文件 `publish.yml`、GitHub 环境 `pypi`。五个现有项目都必须授权该 Trusted Publisher。GitHub Pages 使用独立的 `github-pages` 环境。操作方式见 [PyPI 现有项目配置指南](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)。
5. 选定版本号并取得维护者的发布批准。先推送已审查提交，再推送对应的 `v<version>` 标签，然后创建 GitHub release。发布与文档审查是独立操作。

[发布工作流](https://github.com/sunbos/sqlseed/blob/main/.github/workflows/publish.yml)测试 Python 3.10、3.12 和 3.13，要求使用 `v` 标签，构建五个包并检查元数据与 wheel 版本，然后通过各自的 Trusted Publishing 任务发布每个项目的 wheel 和 sdist。各任务可以独立成功；这不是五包原子发布事务。

在发布记录中保留工作流运行、提交、标签与产物哈希。如果发布中途失败，重试同一版本前先确认哪些文件已到达 PyPI。`skip-existing` 设置不能证明五个包都已成功上传。

变更 Trusted Publisher 后，在停用旧环境前，针对已发布版本验证共用发布身份：

```bash
gh workflow run publish.yml --ref main -f release_tag=v0.2.4 -F verify_existing_release=true
```

此模式首先要求十个重新构建的文件都与公开文件名和 SHA256 哈希一致，且没有任何文件被撤回（yanked）。随后关闭 Twine 跳过已存在文件的快捷逻辑，让 PyPI 实际校验每个项目的上传权限。PyPI 接受完全相同的已存在文件，不会替换它们。此验证模式不生成新的证明（attestation）；现有文件和证明保持不变。常规发布仍保留 `skip-existing` 和证明生成。任何公开文件缺失或发生变化，都会在上传任务开始前终止验证。五个任务全部成功后，仍会运行公开安装验收。

如果上传工具需要兼容性修复，将工作流修正合并到 `main`，再使用已发布版本的标签手动触发：

```bash
gh workflow run publish.yml --ref main -f release_tag=v0.2.4
```

工作流仅解析一次标签对应的提交，然后使用该精确源码进行测试、构建与公开安装检查。因此可以维护工作流，而不移动已发布标签。保持元数据验证和证明生成功能开启。例如，Core Metadata 2.5 要求 [PyPA publish action v1.14.2 或更新版本](https://github.com/pypa/gh-action-pypi-publish/releases/tag/v1.14.2)；重新运行固定在旧上传工具版本的工作流只会重复元数据错误。

## 发布前验证已安装产物 {#validate-installed-artifacts-before-release}

在仓库检出目录之外创建全新虚拟环境。用一次 `pip install` 安装五个 wheel 路径，并为 AI wheel 请求 `[mcp]` extra，以启用独立的 AI MCP 服务。在检出目录之外、未设置 `PYTHONPATH` 的情况下，运行已审查仓库中的脚本：

```bash
python -m pip check
python /path/to/sqlseed/scripts/check_wheel_install.py
python /path/to/sqlseed/scripts/check_public_entrypoints.py 0.2.6
```

将 `0.2.6` 替换为实际待测版本。在仅安装 Core 与 Web 的全新环境中重复验收，运行 `check_wheel_install.py --without-optional-components`。再在第三个环境中一起安装五个 sdist，重复完整检查。不得将开发版本或本地版本覆盖值描述为已经正式发布的版本。

## 发布后从正式 PyPI 验证 {#verify-from-public-pypi-after-publication}

五个项目都发布精确版本后，从已审查的仓库目录运行以下命令。使用 Python 3.12 的 Linux runner 可作为参考环境；Bash 脚本也支持 macOS。通过 `PYTHON_BIN` 指定解释器。五个上传任务全部成功后，发布工作流会在 Linux / Python 3.12 环境中运行此检查，并保留 `public-pypi-acceptance` 产物。可用同一命令在本地或其他受支持的平台复验。

```bash
PYTHON_BIN=python3.12 bash scripts/verify_pypi_release.sh 0.2.6
```

脚本使用正式 PyPI 索引，创建一次性环境，忽略本地包路径，并保存包元数据和安装报告。它检查精确公开版本及其 wheel/sdist 是否可用，再测试完整 wheel、最小 Core/Web 和完整 sdist 安装。当某平台没有第三方依赖的 wheel 时，可能从源码构建该依赖，因此需要相应构建工具链。

已安装包检查覆盖：

- 从环境的 `site-packages` 导入、包版本一致，以及 Core 与 CLI 入口分离。
- 通过 Core、CLI 和离线 MCP 服务进行真实 SQLite 生成，包括预期行数与无关记录保留。
- Web 在临时端口启动、静态资源，以及通过 HTTP 预览和生成。
- 从独立 AI MCP 服务发现四个工具。工具发现不调用模型，也不证明 LLM 后端可达。

上传后打开五个 PyPI 项目页面，检查选中版本、渲染后的介绍、Documentation 链接、许可证和可下载文件。将上传文件哈希与保留的构建产物比较。确认 Pages 部署使用已审查的主分支提交，且安装、升级和 API 页面均可正常打开。

真实 PostgreSQL 与真实 LLM 的验收证据应单独保留。公开安装脚本使用 SQLite，不声称已验证上述两项集成。即使本地 wheel 检查通过，公开安装失败或入口损坏仍属于发布失败。
