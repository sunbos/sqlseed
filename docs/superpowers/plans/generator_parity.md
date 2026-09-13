# 参考工具 数据生成器对齐规格（Generator Parity Spec）

> **历史差距资料（2026-09-07 收敛）：** 当前 UI 以 [v8 整体重建契约](2026-09-07-web-v8-rebuild.md) 为准。下文连接级 locale、严格复制分类和空组占位等旧 UI 选择已 superseded；能力状态需以当前 core 和真实测试重新核对，不能作为新增实现承诺。

**来源**: `示例UI/生成数据类型/` 下 44 张 参考工具 16 数据生成模块截图（2026-08-30 逐张核对）。
**配套**: 逐截图的布局/参数/默认值/选项记录见 [generator\_ui\_reference.md](./generator_ui_reference.md)；这些是历史素材。
**目的**: 保留参考工具每个生成器的配置粒度和历史差距，供能力演进时查询，不规定当前产品布局。
**状态**: 历史规划（非当前实施承诺）。下文 P0/P1/P2 为当时分类，需重新评估后才可进入新计划。

***

## 1. 参考工具 面板通用结构

每个生成器面板 = **类型专属参数区** + **例值** + **通用底部区**：

| 通用控件            | 说明                             | sqlseed-web 现状                     |
| --------------- | ------------------------------ | ---------------------------------- |
| 包含默认值 + 百分比     | 按比例插入列默认值（与 NULL 并列的第二种"空值"策略） | ❌ 未实现（P1，核心需 default\_ratio 概念）    |
| 包含 NULL 值 + 百分比 | 按比例插入 NULL                     | ✅ 已有（属性面板"包含 NULL 值/百分比"）          |
| 设置唯一            | 唯一约束                           | ✅ 已有                               |
| 尊重/禁用字段之间的数据链接  | 跨字段数据一致性开关                     | ❌ 未实现（P2，近似于 derive\_from/CHECK 链） |
| 例值 + 刷新         | 单值预览                           | ✅ 已有（属性面板预览）                       |
| 重置属性            | 恢复默认                           | ✅ 已有                               |

> 注：用户曾以为 web 端没有 NULL/百分比——实际在属性面板参数区下方（"包含 NULL 值"勾选 + "百分比"输入），已确认存在。

## 2. 下拉分类（2026-08-30 对齐到 web）

参考工具 分组：**通用 / 个人 / 支付 / 商业 / 位置 / 产品 / 电脑**。
web 现行分组（labels.js `GEN_CATEGORIES`）：**通用 / 个人 / 支付(占位) / 商业 / 位置 / 产品(占位) / 电脑 / 其他（兜底）**。

* 分组名与顺序严格对齐 参考工具；原「网络与文件」组更名为「电脑」（url / ipv4）。

* **支付 / 产品为空组**：参考工具 有、sqlseed 尚未实现（P2）。`groupGenerators()` 对空组标记 `pending: true`，
  下拉里渲染为**禁用占位项**（「（暂无生成器）」），而不是把生成器丢进"其他"。
  P2 生成器一旦落地，只需在 `GEN_CATEGORIES` 的 `gens` 里补名字，占位项自动变为可选项——
  **无需改动 genform.js 或本文件**。

## 2.5 Locale 粒度设计决策（2026-08-30）

结论：**两级模型** —— 连接级默认 locale（step1，现状）+ 列级可选覆盖（未来）。不采纳逐列全自定义。

理由：

1. provider 是连接级单例，`set_locale()` 重建 faker 实例并做能力探测（`faker_provider.py`），设计意图是"切换时探测一次、热路径零开销"。逐列热切换违背该设计；列级覆盖须用 **locale 实例缓存**（每 locale 一个实例，warm 后复用）实现。
2. 参考工具 语言面板（性别/称谓/婚姻/部门/行业等）的本质是**词表池**（有限枚举，与枚举的"值" textarea 同类），不是 locale。词表类生成器新增时的正确映射是词表参数（`values`/`brands`），而非 locale 参数。
3. 数据一致性：同一 DB 默认同市场；逐列自定义会让默认态滑向"中文姓名+美国地址"的混合数据。

落地路线：

* **P1a（零核心改动）**：词表类生成器新增时带词表参数（并入 P2 词表族）。

* **P1b（小核心改动）**：`ColumnConfig` 增加 `locale?: str`；orchestrator 用 locale 实例缓存切换，仅对 locale 敏感生成器（name/address/city/phone 族）生效。

* **UI**：属性面板加"locale（默认跟随连接）"项，仅 locale 敏感生成器显示；step1 下拉语义已澄清为"默认 Locale（连接级）"。

***

## 3. 逐生成器明细

格式：**参考工具 配置** → sqlseed 现状 → 差距/建议。

### 3.1 通用类

#### 数字 (integer/float)

* 参考工具: 开始(0)、结束(1000)、数字类型(整数/小数 radio)、小数位数(2)

* sqlseed: `integer(min_value,max_value)`、`float(min_value,max_value,precision)` ✅ 对齐（radio = 两个生成器）

#### 日期 (date) — ✅ 已实现（2026-08-30）

* 参考工具: 开始日期、结束日期（具体日期，非年份）、星期(全部/工作日/自定义+周几勾选)

* sqlseed: `date(start_date, end_date, weekdays, start_year, end_year)` ✅

  * `start_date` / `end_date`（`YYYY-MM-DD`）优先；未提供时回退到 `start_year` / `end_year`（保留向后兼容）。
  * `weekdays`: `"all"`（默认）/ `"workdays"` / `"weekend"` / `[0…6]`（Mon=0）。

#### 日期时间 (datetime) — ✅ 已实现（2026-08-30）

* 参考工具: 日期范围（同日期）+ 一整天 checkbox + 开始时间/结束时间 + 星期

* sqlseed: `datetime(start_date, end_date, all_day, start_time, end_time, weekdays, start_year, end_year)` ✅

  * `all_day=True`（默认，等同 参考工具「一整天」勾选）→ 全天 00:00:00–23:59:59，忽略时间参数；
    取消勾选则启用 `start_time` / `end_time` 时间窗（`HH:MM` 或 `HH:MM:SS`）。
  * 统一截断到**整秒**——此前 faker/mimesis 会带出微秒（`T10:21:03.895011`），base 不会，三 provider 已一致。

#### 时间 (time) — ✅ 新增生成器（2026-08-30）

* 参考工具: 一整天(checkbox) + 开始时间/结束时间

* sqlseed: `time(all_day=True, start_time, end_time)` ✅ 已加入 `GENERATOR_MAP`（生成器总数 35 → 36）

> **跨列 CHECK 类型防护（2026-08-30）**：`time` / `date` 与 `datetime` 混用会让跨列 CHECK
> （如 `shipped_at >= created_at`）比较 `datetime >= time`，此前抛裸 `TypeError` → HTTP 500，
> 前端只显示「预览失败：HTTP 500」，用户无从排查。现在 `core/stream.py` 捕获 `TypeError` 并转成
> `ConfigurationError`，明确指出两列各自产生的类型；web 层将其映射为 400 + 可读 detail。

#### 序列 (skip/autoincrement/template{sequence})

* 参考工具: 开始(1)、递增(1)、最小、最大、循环(checkbox)

* sqlseed: PK 走 `skip`（自增列交给数据库生成，`skip` **不在用户可选的生成器下拉里**）；
  自定义序列靠 `template` 的 `{sequence}` 占位符 + `sequence_start` / `sequence_step` 参数 ⚠️

* 已验证（2026-08-30）：
  `ORD-{sequence:04d}` → `ORD-0001…ORD-0005`；`start=100,step=5` → `A100 A105 A110 A115`；
  可与随机片段混用 `SKU-{random_string:4}-{sequence:03d}` → `SKU-OhbV-001`。

* 缺失：无独立 `sequence` 生成器（`GENERATOR_MAP` 中不存在）；无 最小 / 最大 / 循环 三个参数。

* 建议 P1: 独立 `sequence(start,step,min,max,loop)` 生成器

> **UI 映射坑（2026-08-30 修正）**：§1.3 裁剪矩阵里「序列 → 通用区全无」**不适用于 `template`**。
> 参考工具 的序列是纯确定性递增（恒非空、天然唯一），而 sqlseed 的 `template` 可含随机片段，
> NULL% 与「设置唯一」对它都有意义。曾据此裁掉 `template` 的通用区，导致这两项不可见也不可改。
> 现 `NO_COMMON_GENS` 为空集——真正的独立 `sequence` 生成器落地后再加入。

#### 枚举 (choice) / 加权枚举 (weighted\_choice)

* 参考工具: 值 textarea（每行一个）

* sqlseed: `choice(choices[])`、`weighted_choices(dict)` ✅ 参数齐全

* UI P0: 参数输入改为每行一个值的 textarea（本次已落地）；加权支持每行 `值:权重`

#### 文本 (text)

* 参考工具: 字符数(100–10000)

* sqlseed: `text(min_length,max_length)` ✅ 对齐

#### 字符串 (string)

* sqlseed 独有（min\_length/max\_length/charset），参考工具 无对应，保留

#### 布尔值 (boolean)

* 双方无参数 ✅ 对齐

#### 图像或二进制 (bytes) — ✅ 已实现（2026-08-30）

* 参考工具（粒度最细的一种，双模式）:

  * 模式A 图像生成器: 图像宽度(320)、图像高度(320)、图像格式(JPEG/PNG radio)

  * 模式B 从文件夹中随机选择: 文件夹路径(带选择按钮)、使用扩展名筛选(多选 png/gif/svg/…)

* sqlseed: `_gen_bytes(length, width, height, image_format, folder, extensions)` 全量对齐

  * `folder` 模式：目录不存在/无匹配文件抛 `ValueError`（大小写不敏感、容忍前导点）

  * 图像模式：PNG 由标准库直接构造（8-bit RGB，确定性强）；`image_format="jpeg"` 有 Pillow 用 Pillow，否则回退 PNG 字节

  * 参数已进 AI 修复白名单 `_GENERATOR_PARAM_WHITELIST["bytes"]`

  * UI 中文标签：图像宽度/图像高度/图像格式/文件夹路径/扩展名筛选

  * 后续可选增强：文件夹路径的"选择文件夹"按钮（可复用服务端 /api/fs/browse）

#### 外键 (foreign\_key)

* 参考工具: 模式(schema)、表、字段 下拉 + 生成模式(随机/不重复/重复每个值 N 次)

* sqlseed: FK 自动识别从父表采样 ✅ 基本对齐

* 建议 P1: 暴露采样策略（random / unique / repeat-each-N）；"不重复"受父表行数约束，写库时需校验

#### UUID (uuid)

* 参考工具: 格式(含连字符/无格式)

* sqlseed: `uuid()` ⚠️ P1: `hyphens: bool`

#### 正则表达式 (pattern)

* 参考工具: 正则表达式 textarea + 原始数据模式 checkbox

* sqlseed: `pattern(pattern/regex)` ✅ 对齐（"原始数据模式"≈ 字面量输出，暂不需要）

#### JSON (json)

* sqlseed 独有（schema 参数），参考工具 无对应，保留

### 3.2 个人类

#### 姓名 (name/first\_name/last\_name)

* 参考工具: 格式类型(全名…) + 语言多选(English PinYin / 简体中文 / 繁體中文 / Japanese…)

* sqlseed: `name/first_name/last_name`，语言由**连接级 locale** 决定 ⚠️

* 建议 P1: 生成器级 `locale` 覆盖参数（provider 已支持 set\_locale）

#### 性别 / 称谓 / 婚姻状况 / 产品类别 / 颜色 / 尺寸 / 行业 / 部门 / 职位名称 (job\_title)

* 参考工具: 语言多选（值域枚举：性别=M/F、称谓=Mr./…、婚姻=单身/…）

* sqlseed: 仅 `job_title`；其余缺失 ⚠️

* 建议 P2: 新增 `gender/marital_status/salutation/product_category/color/size/industry/department`（本质是内置词表的枚举生成器，mimesis/faker 均有对应数据源）

#### 电子邮箱 (email)

* 参考工具: 域 textarea（gmail.com/hotmail.com/…自定义）

* sqlseed: `email()` ⚠️ P1: `domains[]` 参数

#### 电话号码 (phone)

* 参考工具: 格式(国内/国际) + 包含分隔符 + 地区多选(美国/英国/中国/日本/其它)

* sqlseed: `phone(mask)` ⚠️ P1: `region[]`+`separator: bool`（注意 LENGTH CHECK 硬真相：分隔符开关必须尊重列长度约束）

#### 社交网络 ID (username)

* 参考工具: 无参数

* sqlseed: `username()` ✅ 对齐

#### 密码 (password)

* sqlseed 独有，保留

### 3.3 支付类（全部缺失，P2）

| 参考工具 | 配置                                       | 建议                                                |
| ------- | ---------------------------------------- | ------------------------------------------------- |
| 支付方式    | 值 textarea（Credit Card/PayPal/Apple Pay） | `choice` 预设词表 `payment_method`                    |
| 信用卡类型   | 类型多选(美国运通/JCB/万事达/银联/Visa)               | `credit_card_type(brands[])`                      |
| 信用卡卡号   | 类型多选（Luhn 合法号）                           | `credit_card_number(brands[])`（rstr 可按前缀+Luhn 生成） |
| 信用卡日期   | 日期类型(有效期限)、日期范围(月/年)、MM/YY               | `credit_card_expiry(start,end)`                   |

### 3.4 商业类

#### 公司名称 (company)

* 参考工具: 语言多选；sqlseed: `company()` ✅（语言走连接 locale，同姓名类 P1）

#### 部门 / 行业

* 参考工具: 语言多选；sqlseed 缺失 ⚠️ P2 新增（词表枚举）

#### 口号 (catch\_phrase)

* sqlseed 独有（参考工具 无对应图），保留

### 3.5 位置类

#### 地址 (address)

* 参考工具: 类型(第1行地址/第2行地址/完整地址) + 地区(中国/日本/…+书写语言)

* sqlseed: `address()` ⚠️ P1: `line: 1|2|full`

#### 城市 (city)

* 参考工具: 地区多选 + 语言；sqlseed: `city()` ⚠️ P1: `region[]`

#### 地区 (state)

* 参考工具: 格式类型(全名/缩写) + 语言 + **将值转换为(全角/半角)**

* sqlseed: `state()` ⚠️ P1: `format: full|abbr`；全半角转换 P2（通用文本后处理，可做成 transform 钩子）

#### 国家 / 邮政编码 / 国家代码 (country/zip\_code/country\_code)

* sqlseed 已有，参考工具 无独立截图（归并进地区/城市模式）✅

### 3.6 产品类（大部分缺失，P2）

| 参考工具        | 配置                                                         | 建议                                                   |
| -------------- | ---------------------------------------------------------- | ---------------------------------------------------- |
| 产品名称           | 使用关键字生成 textarea（Apple/Cherry/…）+ 组合修饰词（例值 Cherry premium） | `product_name(keywords[])`，模板 `{keyword} {modifier}` |
| 产品类别           | 语言多选                                                       | 词表枚举                                                 |
| 颜色 / 尺寸 / 重量单位 | 语言 / 值 textarea(g/kg/oz)                                   | 词表枚举                                                 |
| 条码             | 类型多选(EAN8/EAN13/UPCA/UPCE/Code39/ISBN) + 正则展示              | `barcode(types[])`（等价 pattern 预设）                    |
| SKU            | 正则表达式 textarea                                             | ≈ 我们的 `template`/`pattern`，文档注明映射即可                  |

### 3.7 网络与文件（电脑类）

#### IP 地址 (ipv4)

* 参考工具: IPv4/IPv6 radio；sqlseed: `ipv4()` ⚠️ P1: `ipv6()` 新增或 `family` 参数

#### MAC 地址

* 参考工具: 正则展示；sqlseed 缺失 ⚠️ P2 `mac_address()`（pattern 预设 `[0-9a-f]{2}(:[0-9a-f]{2}){5}`）

#### 主机名 / 网址 (url)

* 参考工具: 子域 textarea(auth/drive/mail/…) + 顶级域 textarea(com/cn/info/…)

* sqlseed: `url()` ⚠️ P1: `subdomains[]` + `tlds[]`（两者同构，可共用参数组）

#### 文件路径 / 文件名称 / 文件扩展名

* 参考工具: 路径类型多选(Windows/MacOS/Linux)、包含文件名称 checkbox、扩展名类型 dropdown、扩展名 textarea

* sqlseed 缺失 ⚠️ P2 `file_path(os[],include_name,extensions)` / `file_name(include_ext,extensions)` / `file_ext(extensions)`

## 4. 落地路线建议

* **P0（纯 UI，0 核心改动）**：枚举/加权枚举 textarea ✅；下拉"其他"组中拆分"产品/支付"占位组 ✅（均为 2026-08-30 落地）；
  属性面板改为 参考工具 七段式布局（预览上移至通用区之上、重置属性独立置底）✅；
  通用区按生成器裁剪（序列无通用区、词表类无"设置唯一"、图像或二进制无预览）✅；
  百分比默认 5 且未勾选时禁用 ✅；参数控件形态改为显式集合（数值/多行），`precision`、`start_year` 不再被误渲染为文本框 ✅；
  bytes 的 `image_format` 改为下拉（png/jpeg）、`folder` 增加服务端「选择文件夹」按钮（filepicker `mode: 'dir'`）✅

* **P1（核心参数扩展，向后兼容）**：

  1. `email(domains[])`、`phone(region[],separator)`（尊重 LENGTH CHECK）、`uuid(hyphens)`、`ipv4/ipv6`
  2. `date/datetime` 具体日期范围 + 时间段 + 星期过滤 ✅；新增 `time` 生成器 ✅（均为 2026-08-30 落地）
  3. `name` 族生成器级 locale 覆盖
  4. FK 采样策略参数（random/unique/repeat-each-N）
  5. `sequence(start,step,min,max,loop)`

* **P2（新生成器/新概念）**：图像或二进制双模式 ✅（2026-08-30 已随 `bytes` 落地）、支付四件套、产品词表族、性别/称谓/婚姻等行业词表、文件三件套、MAC/主机名、全半角转换 transform、`default_ratio`（包含默认值）

* 每个新参数同步：`labels.js PARAM_LABELS` 中文名、`meta/generators`（自动来自 `_gen_*` 签名）、AI 修复白名单 `_GENERATOR_PARAM_WHITELIST`（sqlseed-ai strategies.py，否则 normalize\_params 会剥掉新参数）

## 5. 截图 → 生成器对照速查

| 截图                        | 参考工具 生成器 | sqlseed 生成器                                         | 差距级                         |
| ------------------------- | ----------- | --------------------------------------------------- | --------------------------- |
| 数字                        | 数字          | integer/float                                       | ✅                           |
| 日期/日期时间/时间                | 日期类         | date/datetime/time                                  | ✅                           |
| 序列                        | 序列          | skip/template                                       | P1                          |
| 枚举                        | 枚举          | choice/weighted\_choice                             | ✅(UI textarea 已对齐)          |
| 文本                        | 文本          | text                                                | ✅                           |
| 布尔值                       | 布尔值         | boolean                                             | ✅                           |
| 图像或二进制                    | 图像或二进制      | bytes(width/height/image\_format/folder/extensions) | ✅                           |
| 外键                        | 外键          | foreign\_key                                        | P1(策略)                      |
| UUID                      | UUID        | uuid                                                | P1(格式)                      |
| 正则表达式                     | 正则表达式       | pattern                                             | ✅                           |
| 姓名                        | 姓名          | name/first\_name/last\_name                         | P1(locale/格式)               |
| 性别/称谓/婚姻状况                | 个人枚举        | —                                                   | P2                          |
| 电子邮箱                      | 电子邮箱        | email                                               | P1(域)                       |
| 电话号码                      | 电话号码        | phone                                               | P1(地区/分隔符)                  |
| 社交网络ID                    | 社交网络 ID     | username                                            | ✅                           |
| 职位名称                      | 职位名称        | job\_title                                          | ✅(locale P1)                |
| 公司名称                      | 公司名称        | company                                             | ✅(locale P1)                |
| 部门/行业                     | 商业枚举        | —                                                   | P2                          |
| 地址/城市/地区                  | 位置          | address/city/state                                  | P1(类型/地区/格式)                |
| 产品名称/类别/颜色/尺寸/重量单位/条码/SKU | 产品          | —/template                                          | P2                          |
| 支付方式/信用卡×3                | 支付          | —                                                   | P2                          |
| IP地址/MAC地址/主机名/网址         | 电脑          | ipv4/—/—/url                                        | P1(IPv6/子域/顶级域) P2(MAC/主机名) |
| 文件路径/文件名称/文件扩展名           | 电脑          | —                                                   | P2                          |
