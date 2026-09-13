本轮默认 unique_adjuster mutation gate：通过。

- `make mutmut` exit=0；246/246 killed；survived=0、timeout=0、suspicious=0、skipped=0、untested=0。
- Python 3.11.15；mutmut 2.5.1；pytest 9.1.1；耗时 809.612 秒。
- 目标：`src/sqlseed/core/unique_adjuster.py`；runner：`python -m pytest tests/test_core/test_unique_adjuster.py tests/test_core/test_unique_string_capacity.py -x -q --no-header`（未覆盖默认命令或配置）。
- 基准测试成功，mutmut 记录 baseline=7.365628004074097 秒。
- 隔离快照：`/tmp/sqlseed-merge-mutation-20260913-d1efqq1a/snapshot`；从共享仓库读取 578 个 Core/插件/测试/根配置文件，五包导入路径均已核对为快照。未修改共享仓库、用户环境或依赖；PYTHONDONTWRITEBYTECODE=1，缓存写入 /tmp。
- snapshot SHA256：`a0fca59c53d1b324f5b55f86fffd9796fd37d0767385b96290a12fa61d1c65a6`。
- source SHA256（复制时）：`000949ec8650fb78d8f1dd30aea78520abede0bbe1c3b240e2d6ea8f08feee40`；shared source SHA256（运行结束）：`ac3894783ade6f91f8e3d366d9d74464f34795c41eddfca8080866b5304bed8d`。
- unique_adjuster.py SHA256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`。
- mutation 运行后快照文件变化：`[]`。
- 运行期间其他任务对共享文件的变化：`['plugins/sqlseed-ai/tests/test_mcp_stdio.py', 'src/sqlseed/core/orchestrator/_self_ref.py', 'src/sqlseed/database/_value_normalizer.py', 'tests/integration/test_pg_typed_value_bindings.py', 'tests/test_package_boundaries.py', 'tests/test_typed_values_api.py']`；不能把本快照哈希当作这些变化之后整个源码树的哈希。
- 完整日志 SHA256：`3eaec3f92468fca65c2eab0a75a51309f86bd22880ccfcf72da7899b43b94666`。

`metadata.json`、`hashes-before.json`、`source-hashes-before.json` 和 `hashes-after.json` 记录准确快照及哈希；`gate-input-hashes.json` 记录本 gate 的目标/runner 输入文件；`command.sh.txt` 记录完整可复现命令及环境覆盖。结果同时核对 mutmut 日志、SQLite cache 全部状态和 `junit-strict.xml`，没有把超时、skipped 或未测试条目当作 killed。若存在未杀死项，详细 diff 见 `non-killed-diffs.txt`。

额外核验：Makefile、pyproject.toml、三层 conftest、unique_adjuster.py 及默认 runner 的两份测试，运行前后 SHA256 全部相同。共享源码的两项变化是 _self_ref.py 等价赋值表达式改写，以及 _value_normalizer.py 等价抽出 _temporal_value；其余4项为非本 runner 的测试文件变更。完整差异保存在 shared-changes-after-snapshot.diff。本报告不把非本次 mutation 目标宣称为已完成 mutation 验证。
