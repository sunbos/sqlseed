# 生成器效果审计与局部修复

日期：2026-09-07。范围：`sqlseed.generators`；未访问或写入用户数据库。

## 结论

Mimesis 收到了正确的 `zh_CN → zh` locale；姓名不对的原因是 native `full_name()` 仍以“名 姓”格式拼接。现仅对中文调整为“姓名”，例如固定 seed 1707 下，`思悦 鲍` 改为 `鲍思悦`；英文保持原输出。

完整 catalog 的两个 locale、三个真实 provider 都已采样。审计还复现并修复 Faker JSON schema 解释错误、省份/邮编方法误判、短文本长度运行错误，以及所有 provider 的加权列表参数遗漏。没有重写全部生成器，也没有修改 mapper、AI 或数据库生成流程。

“所有名称都采样通过”不能证明所有业务语义正确。下文分别列出运行契约、已修复问题和仍存在的效果限制。

## 方法与可复现证据

- 实际 `GeneratorDispatchMixin.GENERATOR_MAP` 共 **36** 个名称，不包括由上层处理的 `skip`、`foreign_key`。
- 三个实际 provider：Base、Faker、Mimesis；locale 为 `en_US`、`zh_CN`。
- 每个 case 使用独立 provider，先设置 locale，再设置 seed **1707**；采样 **25** 次，另创建同 seed 的独立 provider 复跑，比较输出及异常。
- catalog 默认值或必要有效参数：36 × 3 × 2 = **216** cases。`choice`、`weighted_choice` 提供有效候选值。
- 25 组有效代表参数 × 3 × 2 = **150** cases。总计 **366** cases。
- 代表参数覆盖：数字范围与精度、digits/自定义中文字符集、电话 mask、工作日/固定日期、日期时间窗口、精确/短文本长度、密码/bytes 长度、混合类型枚举、JSON 对象/标量/数组、正则及其 alias、模板序号、加权参数两种入口。
- 运行环境：Python **3.11.15**，Faker **40.15.0**、Mimesis **19.1.0**。机器结果记录完整 Python 版本、其他依赖版本、各 generator 源文件 SHA-256、参数、样本、异常及重复性检查。

任务证据文件（本地临时目录，未提交全量数据）：

| 文件 | 内容 |
| --- | --- |
| `/tmp/sqlseed-generator-audit.py` | 无数据库访问的完整采样脚本 |
| `/tmp/sqlseed-generator-audit.before.json` | 修复前完整矩阵与源文件 hashes |
| `/tmp/sqlseed-generator-audit.after.json` | 相同矩阵的修复后结果 |
| `/tmp/sqlseed-generator-audit.comparison.json` | 前后统计、语义样例及剩余失败 |
| `/tmp/sqlseed-generator-red.txt` | 写修复前的真实回归失败证据 |

运行脚本：`PYTHONPATH=src .venv/bin/python /tmp/sqlseed-generator-audit.py`。输出 `/tmp/sqlseed-generator-audit.json`；前后证据文件另行保留。

## 修复前后结果

| 同一矩阵指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| cases | 366 | 366 |
| 主采样实际生成值（不含独立复跑） | 8,704 | 9,150 |
| 抛异常 cases | 18 | 0 |
| 值断言失败 cases | 2 | 2 |
| 总失败 cases | 20 | 2 |
| 独立同 seed 复跑不一致 cases | 0 | 0 |

剩余 2 cases 均为 Base 在两个 locale 下忽略 phone mask。其实现明确说明输出占位电话号码，属于已有能力限制，保留为可见审计结果，没有归零或掩盖。排除此声明过的限制，当前矩阵没有运行或值断言失败。

原矩阵的类型/长度断言没有检测中文姓名顺序与地区真实来源，不能把这些语义问题算进原有 20 个失败数。针对语义补充了真实回归，下表单独说明。

| 问题 | 修前证据 | 最小修复 | 验证重点 |
| --- | --- | --- | --- |
| Mimesis 中文姓名顺序 | `zh_CN` 已转成 `zh`，仍输出 `思悦 鲍` | 中文使用 native 反向 fullname，去掉分隔空格 | 姓在前；用独立 native 名/姓序列校验；`zh_CN`/`zh`；英文 native 序列不变 |
| Faker JSON 契约 | schema 的 `type: object/integer/array` 被当成 Faker formatter，抛 `Unknown formatter`；默认 JSON 为原生行数组 | 复用共有 JSON schema 生成逻辑，叶子仍通过实际 Faker provider 生成 | 默认对象、各标量、对象、数组及递归组合、同 seed 复现 |
| Faker 中文省份/邮编 | `state()`/`zipcode()` 不存在，错误降级为 `state_001_2958`/`00001`，实际有 `province()`/`postcode()` | 在安装 Base fallback 前解析真实等价方法 | 中文真实省份、六位邮编；来回切换 locale；确实缺失能力仍可 fallback |
| Faker text 长度 | 10/10、50/50、1/4 长度共 6 cases 抛异常，native 不接受小于 5 的片段长度 | native 片段至少请求 5 字符，达到最小长度后截取；提前拒绝倒置范围 | 两个 locale 的短/精确/普通范围、倒置范围及同 seed 复现 |
| `weighted_choices` 列表 | 6 cases 对声明接受的 `[{value, weight}]` 抛“缺少 choices” | 将列表规范化到已有加权列表分支 | 零权重、分数权重、候选类型及既有 `choices` RNG 序列完全一致 |

新文件 `tests/test_generators/test_generator_quality_regressions.py` 包含 **22** 个参数化测试实例；另把已有 `JsonSchemaTestMixin` 的 **8** 个契约实例应用到 Faker。原地区 fallback 测试改为验证真实省份/邮编，并用确实不提供 state/province 的 `zh_TW` 保留缺失方法降级与切回清理验证。

这些修改前运行：**28 failed / 40 passed**；修改后同一组：**68 passed**。它们验证实际 provider 输出，不 mock 生成器。

## 全部 36 个 generator 的检查范围

每一行均覆盖 Base/Faker/Mimesis × `en_US`/`zh_CN`。通过仅表示表中检查范围；自然语言与地理关联仍有下节限制。

| Generator | 本轮实际检查 |
| --- | --- |
| `address` | 非空文本与两个 locale 样例；不保证地址组件地理一致 |
| `boolean` | Python `bool` |
| `bytes` | Python `bytes`，默认 16 字节及指定 12 字节 |
| `catch_phrase` | 文本输出、locale 样例；不保证中文或真实业务名称 |
| `choice` | 必需候选集合、混合候选类型 |
| `city` | 文本与 locale 样例 |
| `company` | 文本与 locale 样例 |
| `country` | 文本与 locale 样例；语言不等于国籍限制 |
| `country_code` | 文本与两种引擎含义差异观察；Base 为占位 |
| `date` | 真正 `date` 类型、范围、工作日、单一天及自定义 weekday |
| `datetime` | 真正 `datetime`、日期范围、时间窗口、无微秒 |
| `email` | 基本 `local@domain.tld` 格式 |
| `first_name` | 文本与中文名字段样例 |
| `float` | 类型、范围、两位精度 |
| `integer` | 类型与含负数的指定范围 |
| `ipv4` | 可由 `IPv4Address` 解析 |
| `job_title` | 文本与 locale 样例 |
| `json` | 可解析、指定对象字段类型、整数标量、布尔数组；回归补充递归 |
| `last_name` | 文本与中文姓字段样例 |
| `name` | 文本；额外校验中文姓在前无空格、英文 native 格式 |
| `password` | 默认长度与指定 12 字符；未作为安全密码强度评估 |
| `pattern` | 无规则时为空；固定字母/数字正则与 `regex` alias 完整匹配 |
| `phone` | locale 样例；Faker/Mimesis mask 满足 11 位规则；Base 忽略 mask |
| `sentence` | 文本与 locale 样例；不保证自然叙述 |
| `state` | 文本；额外校验 Faker 中文真实省份与 locale 切换 |
| `string` | 默认/指定长度、数字字符集、自定义中文字符集 |
| `template` | 无模板时为空；指定模板从 1 开始、步长 2、四位格式序号 |
| `text` | 默认/精确/短长度；两个 locale 文本样例 |
| `time` | 真正 `time` 类型、09:00–18:30 窗口、无微秒 |
| `timestamp` | 真正 `datetime` 类型、日期/秒级时间窗口 |
| `url` | http/https scheme 与非空 host |
| `username` | 当前继承 Base 的 `user_...` 占位格式 |
| `uuid` | 可由 `UUID` 解析 |
| `weighted_choice` | 候选集合；字典/`choices` 列表/`weighted_choices` 列表；额外权重序列验证 |
| `word` | 文本与 locale 样例；Base 是合成伪词 |
| `zip_code` | 文本；额外校验 Faker 中文六位邮编与真实方法来源 |

## 仍需产品与规则层处理的效果限制

1. **locale 不等于所有字段都输出中文或只属于中国。** Faker `zh_CN` 的 `catch_phrase` 仍可输出英文，如 `Enterprise-wide user-facing capability`；Mimesis 拼出的短语是中文词组合，如 `制度 倾向`，也不是有业务含义的商品名称。姓名修复不意味着短语生成器也已本地化完成。
2. **字段之间没有自动业务关联。** 原生 Faker 地址样例可出现 `吉林省柳州市...` 等不同地域组件拼接；country、country_code、state、city 分别生成不会自动保持地理一致。Mimesis country_code 可按 locale 固定为 CN，Faker 可随机其他国家代码。这需要明确的关联规则/共享对象能力。
3. **`name` 是人名 generator。** 商品表 `name` 使用它仍会得到人名；这是列规则/映射选择的问题，不能靠把人名 generator 改成“通用名称”解决。UI、规则推荐与 AI 应明确“姓名”“商品名/枚举/模板”的用途。
4. **Base 不提供真实业务数据；username 目前也沿用 Base。** Base country_code、地址、名字等是占位字符串，其 locale 不产生真实地区数据。Base 电话 mask 也未实现。对真实效果有要求时要显示这些能力边界。
5. **自然文本来自词库或组合，不保证流畅。** Mimesis sentence 的高基数策略会组合随机词语，中文中有空格；text 使用原生语料，不保证领域合适。应把“规则正确”和“内容像真实业务”分开评价。
6. **JSON schema 是子集。** 本轮修复对象/数组/标量类型约定，不新增 `minimum`、`enum`、`required`、`minItems` 等完整 JSON Schema 验证与生成能力。
7. **空 pattern/template 是空字符串。** 有配置才有指定格式；初始化 UI 应给有效模板示例或明确要求，不应把无参数默认值展示成生成器能自动理解编号格式。

本轮没有覆盖任意 regex 特性、全部 locale、所有数值边界、native method overrides、媒体模式、CHECK/UNIQUE/FK 编排、schema mapper、AI 输出质量或生产规模分布。每个 case 的 25 个样本和重复 seed 验证不能证明大批量唯一性、统计分布或跨版本结果完全一致。

## 验证结果

- `pytest tests/test_generators/`：**274 passed，1 skipped**；跳过原因为 Pillow 未安装，JPEG 用例未验证。
- `pytest tests/test_architecture.py tests/test_doc_sync.py`：**31 passed**。
- `ruff check` 与 `ruff format --check`（generators 及其测试目录）：通过。
- `mypy src/sqlseed/generators/`：10 个 source files 通过。
- `lint-imports`：3 contracts kept，0 broken。
- `scripts/sync_docs.py --check`：标记均为最新；保留已有 CLAUDE 文档示例 marker 警告。

未修改 dispatch 名称、公有 API、依赖或数据库入口；没有提交、合并或发布操作。
