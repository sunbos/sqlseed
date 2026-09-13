# GitHub Support 工单记录

2026-09-13 已按用户授权提交：[工单 #4753046](https://support.github.com/ticket/personal/0/4753046)。实际标题因 80 字符上限改为 `Stale traeagent entry in sunbos/sqlseed Contributors sidebar`，正文如下。

GitHub 虚拟客服随后以账号仅提供自助支持为由自动关闭工单，没有确认或修复统计异常。已准备补充官方文档依据，但页面的“重新打开并评论”按钮在填写后仍禁用，补充内容未发送。工单提交成功不代表 Contributors 已清除；需继续核验合并后统计，不能据此改写合法提交历史。

此草稿用于请求刷新仓库首页的 Contributors 统计。当前没有发现需要删除或改写的 `traeagent` 提交；没有改动 Git 历史、分支、权限或仓库设置。

## Subject

Repository sidebar retains a contributor absent from the current commit history and contributor graph

## Message

Hello GitHub Support,

I am the owner of the public repository https://github.com/sunbos/sqlseed.

The repository home page still shows `traeagent` under “Contributors (3)”. However, the current contributor graph with “Period: All” lists only `sunbos` and `claude`. The repository statistics and commit history are inconsistent with the sidebar entry.

Verified on 2026-09-13 (Asia/Shanghai):

- Default branch: `main`, commit `976b605dac47bd6d61cfcae4ff6c7a00fa0352a5`.
- `GET /repos/sunbos/sqlseed/stats/contributors` lists `sunbos` and `claude`, and does not list `traeagent`.
- `GET /repos/sunbos/sqlseed/contributors` lists `sunbos`, and does not list `traeagent`.
- `GET /repos/sunbos/sqlseed/commits?sha=main&author=traeagent` returns an empty list.
- Local inspection of all available branch/tag histories finds no author, committer, or co-author trailer mentioning `traeagent`.
- The same sidebar entry remains visible in a newly opened repository page.

Could you please investigate and refresh the repository sidebar's contributor cache/index so it reflects the current history? I am requesting a statistics correction, not removal of another user's account, access permissions, or valid commits.

Repository: https://github.com/sunbos/sqlseed

Contributor graph: https://github.com/sunbos/sqlseed/graphs/contributors

Thank you.

## 依据

GitHub 官方文档说明，历史变更后的贡献者数据可能需要约 24 小时刷新；若之后仍不正确，仓库所有者可联系 GitHub Support：

https://github.com/github/docs/blob/main/content/repositories/viewing-activity-and-data-for-your-repository/viewing-a-projects-contributors.md

注意：此核验未确定旧署名在何时、由谁移除，也不把缓存原因当作已经由 GitHub 证实的结论。
