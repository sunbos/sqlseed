# GitHub release notes / GitHub 发布说明

Each `v<version>.md` is the reviewed body for an existing or planned GitHub
Release. The title is exactly `v<version>`; the body does not repeat it as an H1.
Copy [TEMPLATE.md](TEMPLATE.md), replace every placeholder, and remove unused
subsections in both languages. Keep `English`, `中文`, and `Links / 相关链接`
in that order, with equivalent English and Chinese subsections. Use UTF-8,
LF newlines, a final newline, and blank lines around headings and lists.

Preserve historical features, removals, compatibility limits and verification
evidence. Do not copy current package boundaries or installation commands into
older releases. If the original notes were empty, say so and link the tagged
source; do not infer features from the version number. Comparison links normally
start at the previous published release. Keep an older comparison as an
additional link when its range differs. Changelog and source links use fixed
tags, and historical test counts are labeled as historical records. The links
section must include this repository's `tree/v<version>` source link. Unreplaced
template instructions are rejected; quotations and code examples may retain them.

The initial set covers all 20 published releases from `v0.1.1` through `v0.2.6`.
It preserves original release content and uses the matching bilingual changelog
where available. Missing version numbers are not new releases to create.

Check the files offline:

```bash
python scripts/sync_release_notes.py --check
```

The CI lint job runs the same offline check; it does not contact GitHub.

Preview existing GitHub Releases, then apply with a new backup name:

```bash
python scripts/sync_release_notes.py
python scripts/sync_release_notes.py --apply --backup-name release-notes-20261012
```

The tool writes UTF-8 output, including when a shell redirects a bilingual preview.
Both commands require GitHub CLI access to `api.github.com`; applying also
requires repository write access. Historical targets that change workflow files
relative to the default branch additionally need the classic PAT/OAuth `workflow`
scope or fine-grained/GitHub App `Workflows: write` permission. Authorize it in
the token/app settings; the built-in Actions `GITHUB_TOKEN` cannot provide it.
See the [release guide](../../docs/releasing.md#maintain-github-release-notes)
for authorization steps and GitHub's 403/404 behavior. Only release titles and bodies are
updated. Backups are stored in the checkout's gitignored `.release-backups/<name>/`;
names accept only ASCII letters, digits, hyphens and underscores. Existing names,
arbitrary paths and symlink backup roots are rejected. Keep or copy the backups
before removing the checkout. The script checks versioned links against the note
filename, detects concurrent changes (including initially matching releases),
spaces mutations by at least one second and verifies each update. If an update
fails partway through, retain the backup, inspect the reported versions and
preview again before retrying with a new backup name.
It does not create releases, republish packages or modify tags/assets.

For a new approved version, commit its reviewed notes with the release changes
and use `gh release create v<version> --title "v<version>" --notes-file
.github/release-notes/v<version>.md` after pushing the commit and tag.
See the [release guide](../../docs/releasing.md).

每个 `v<version>.md` 对应一个已有或计划发布的 GitHub Release 正文，标题统一为
`v<version>`，正文不再重复一级版本标题。复制[模板](TEMPLATE.md)，替换全部占位符，
同步删除中英文中不适用的章节。固定顺序为 `English`、`中文`、`Links / 相关链接`，
两种语言的子章节一一对应。文件使用 UTF-8、LF 换行和末尾换行，标题与列表前后保留空行。

保留历史功能、移除项、兼容性限制及验收依据，不将当前包结构或安装命令套用到旧版本。
原说明为空时明确标注并链接该标签的源码，不根据版本号编造功能。差异链接通常从上一个
已发布版本开始；原有比较范围不同时另行保留。变更日志与源码链接固定到标签，历史测试
数量明确标为历史记录。本次初始文件覆盖 `v0.1.1` 至 `v0.2.6` 的全部 20 个已发布版本，
以原发布说明及对应中英文变更日志为依据，不为跳过的版本号新建 Release。
链接章节必须包含本仓库的 `tree/v<version>` 源码链接。未替换的模板指引会被拒绝，
引用和代码示例中可以保留这些文字。

工具统一输出 UTF-8，包括重定向到文件的双语预览。
以上命令分别执行离线格式校验、线上差异预览与实际同步。线上操作要求 GitHub CLI 能
访问 `api.github.com`，同步还需仓库写入权限。历史目标相对默认分支修改 workflow 文件时，
还需在 token/App 设置中授权经典 PAT/OAuth 的 `workflow` scope，或细粒度及 GitHub App
token 的 `Workflows: write`；Actions 内置 `GITHUB_TOKEN` 无法提供此权限。授权步骤和
GitHub 的 403/404 行为见[发布指南](../../docs/releasing.zh-CN.md#maintain-github-release-notes)。
工具仅修改标题与正文，先将原文备份到检出目录下已被 Git 忽略的 `.release-backups/<name>/`。
名称只接受 ASCII 字母、数字、连字符和下划线，不接受已有名称、任意路径或符号链接备份根目录；
删除检出目录前须保留或复制备份。脚本检查版本链接与说明文件名一致，检查并发变化（包括初始
已匹配的版本），写请求之间至少间隔一秒，并回读验证。中途失败时保留备份、核对已报告版本，
重新预览后使用新的备份名称重试。工具不创建 Release、不重发包、不修改标签或附件。
CI 的 lint 任务也执行同一离线格式校验，不连接 GitHub。

新版本在发布审批后，将审阅过的说明随发布改动提交，推送提交与标签后用
`--notes-file` 创建 Release。完整流程见[发布指南](../../docs/releasing.zh-CN.md)。
