# Navicat 数据生成器对齐规格（Generator Parity Spec）

**来源**: `示例UI/生成数据类型/` 下 44 张 Navicat 16 数据生成模块截图（2026-08-30 逐张核对）。
**目的**: 记录 Navicat 每个生成器的配置粒度，作为 sqlseed-web 属性面板与核心生成器参数演进的对照基线，防止遗忘。
**状态**: 规划文档（非实现承诺）。优先级：P0 = 纯 UI 可做；P1 = 需扩展核心生成器参数；P2 = 需新增生成器。

---

## 1. Navicat 面板通用结构

每个生成器面板 = **类型专属参数区** + **例值** + **通用底部区**：

| 通用控件 | 说明 | sqlseed-web 现状 |
|---|---|---|
| 包含默认值 + 百分比 | 按比例插入列默认值（与 NULL 并列的第二种"空值"策略） | ❌ 未实现（P1，核心需 default_ratio 概念） |
| 包含 NULL 值 + 百分比 | 按比例插入 NULL | ✅ 已有（属性面板"包含 NULL 值/百分比"） |
| 设置唯一 | 唯一约束 | ✅ 已有 |
| 尊重/禁用字段之间的数据链接 | 跨字段数据一致性开关 | ❌ 未实现（P2，近似于 derive_from/CHECK 链） |
| 例值 + 刷新 | 单值预览 | ✅ 已有（属性面板预览） |
| 重置属性 | 恢复默认 | ✅ 已有 |

> 注：用户曾以为 web 端没有 NULL/百分比——实际在属性面板参数区下方（"包含 NULL 值"勾选 + "百分比"输入），已确认存在。

## 2. 下拉分类（已在 2026-08-30 落地到 web）

Navicat 分组：**通用 / 个人 / 支付 / 商业 / 位置 / 产品 / 电脑**。
web 现行分组（labels.js `GEN_CATEGORIES`）：**通用 / 个人 / 商业 / 位置 / 网络与文件 / 其他（兜底）**。
"产品"类与"支付"类目前落在"其他"——待 P2 新增生成器后再拆组。

## 3. 逐生成器明细

格式：**Navicat 配置** → sqlseed 现状 → 差距/建议。

### 3.1 通用类

#### 数字 (integer/float)
- Navicat: 开始(0)、结束(1000)、数字类型(整数/小数 radio)、小数位数(2)
- sqlseed: `integer(min_value,max_value)`、`float(min_value,max_value,precision)` ✅ 对齐（radio = 两个生成器）

#### 日期 (date)
- Navicat: 开始日期、结束日期（具体日期，非年份）、星期(全部/工作日/自定义+周几勾选)
- sqlseed: `date(start_year,end_year)` ⚠️
- 建议 P1: 参数改为 `start_date/end_date`（兼容保留年份）；P1: `weekday: all|workday|custom + days[]`

#### 日期时间 (datetime)
- Navicat: 日期范围（同日期）+ 24小时制 + 开始时间/结束时间(08:00–18:00) + 星期
- sqlseed: `datetime(start_year,end_year)` ⚠️ 同上 + 时间段参数

#### 时间 (time)
- Navicat: 一整天(checkbox) + 开始时间/结束时间
- sqlseed: 无独立 `time` 生成器（仅标签占位）⚠️ P1 新增 `time(start,end)`

#### 序列 (skip/autoincrement/template{sequence})
- Navicat: 开始(1)、递增(1)、最小、最大、循环(checkbox)
- sqlseed: PK 走 `skip`；`template{sequence_start,sequence_step}` 部分覆盖 ⚠️
- 建议 P1: 独立 `sequence(start,step,min,max,loop)` 生成器

#### 枚举 (choice) / 加权枚举 (weighted_choice)
- Navicat: 值 textarea（每行一个）
- sqlseed: `choice(choices[])`、`weighted_choices(dict)` ✅ 参数齐全
- UI P0: 参数输入改为每行一个值的 textarea（本次已落地）；加权支持每行 `值:权重`

#### 文本 (text)
- Navicat: 字符数(100–10000)
- sqlseed: `text(min_length,max_length)` ✅ 对齐

#### 字符串 (string)
- sqlseed 独有（min_length/max_length/charset），Navicat 无对应，保留

#### 布尔值 (boolean)
- 双方无参数 ✅ 对齐

#### 图像或二进制 (bytes)
- Navicat（粒度最细的一种，双模式）:
  - 模式A 图像生成器: 图像宽度(320)、图像高度(320)、图像格式(JPEG/PNG radio)
  - 模式B 从文件夹中随机选择: 文件夹路径(带选择按钮)、使用扩展名筛选(多选 png/gif/svg/…)
- sqlseed: `bytes(length=16)` 仅随机字节 ⚠️ **最大差距之一**
- 建议 P2: `image(width,height,format)`（生成极简合法图片字节）+ `file_from_folder(path,extensions)`（本地测试数据目录）

#### 外键 (foreign_key)
- Navicat: 模式(schema)、表、字段 下拉 + 生成模式(随机/不重复/重复每个值 N 次)
- sqlseed: FK 自动识别从父表采样 ✅ 基本对齐
- 建议 P1: 暴露采样策略（random / unique / repeat-each-N）；"不重复"受父表行数约束，写库时需校验

#### UUID (uuid)
- Navicat: 格式(含连字符/无格式)
- sqlseed: `uuid()` ⚠️ P1: `hyphens: bool`

#### 正则表达式 (pattern)
- Navicat: 正则表达式 textarea + 原始数据模式 checkbox
- sqlseed: `pattern(pattern/regex)` ✅ 对齐（"原始数据模式"≈ 字面量输出，暂不需要）

#### JSON (json)
- sqlseed 独有（schema 参数），Navicat 无对应，保留

### 3.2 个人类

#### 姓名 (name/first_name/last_name)
- Navicat: 格式类型(全名…) + 语言多选(English PinYin / 简体中文 / 繁體中文 / Japanese…)
- sqlseed: `name/first_name/last_name`，语言由**连接级 locale** 决定 ⚠️
- 建议 P1: 生成器级 `locale` 覆盖参数（provider 已支持 set_locale）

#### 性别 / 称谓 / 婚姻状况 / 产品类别 / 颜色 / 尺寸 / 行业 / 部门 / 职位名称 (job_title)
- Navicat: 语言多选（值域枚举：性别=M/F、称谓=Mr./…、婚姻=单身/…）
- sqlseed: 仅 `job_title`；其余缺失 ⚠️
- 建议 P2: 新增 `gender/marital_status/salutation/product_category/color/size/industry/department`（本质是内置词表的枚举生成器，mimesis/faker 均有对应数据源）

#### 电子邮箱 (email)
- Navicat: 域 textarea（gmail.com/hotmail.com/…自定义）
- sqlseed: `email()` ⚠️ P1: `domains[]` 参数

#### 电话号码 (phone)
- Navicat: 格式(国内/国际) + 包含分隔符 + 地区多选(美国/英国/中国/日本/其它)
- sqlseed: `phone(mask)` ⚠️ P1: `region[]`+`separator: bool`（注意 LENGTH CHECK 硬真相：分隔符开关必须尊重列长度约束）

#### 社交网络 ID (username)
- Navicat: 无参数
- sqlseed: `username()` ✅ 对齐

#### 密码 (password)
- sqlseed 独有，保留

### 3.3 支付类（全部缺失，P2）

| Navicat | 配置 | 建议 |
|---|---|---|
| 支付方式 | 值 textarea（Credit Card/PayPal/Apple Pay） | `choice` 预设词表 `payment_method` |
| 信用卡类型 | 类型多选(美国运通/JCB/万事达/银联/Visa) | `credit_card_type(brands[])` |
| 信用卡卡号 | 类型多选（Luhn 合法号） | `credit_card_number(brands[])`（rstr 可按前缀+Luhn 生成） |
| 信用卡日期 | 日期类型(有效期限)、日期范围(月/年)、MM/YY | `credit_card_expiry(start,end)` |

### 3.4 商业类

#### 公司名称 (company)
- Navicat: 语言多选；sqlseed: `company()` ✅（语言走连接 locale，同姓名类 P1）

#### 部门 / 行业
- Navicat: 语言多选；sqlseed 缺失 ⚠️ P2 新增（词表枚举）

#### 口号 (catch_phrase)
- sqlseed 独有（Navicat 无对应图），保留

### 3.5 位置类

#### 地址 (address)
- Navicat: 类型(第1行地址/第2行地址/完整地址) + 地区(中国/日本/…+书写语言)
- sqlseed: `address()` ⚠️ P1: `line: 1|2|full`

#### 城市 (city)
- Navicat: 地区多选 + 语言；sqlseed: `city()` ⚠️ P1: `region[]`

#### 地区 (state)
- Navicat: 格式类型(全名/缩写) + 语言 + **将值转换为(全角/半角)**
- sqlseed: `state()` ⚠️ P1: `format: full|abbr`；全半角转换 P2（通用文本后处理，可做成 transform 钩子）

#### 国家 / 邮政编码 / 国家代码 (country/zip_code/country_code)
- sqlseed 已有，Navicat 无独立截图（归并进地区/城市模式）✅

### 3.6 产品类（大部分缺失，P2）

| Navicat | 配置 | 建议 |
|---|---|---|
| 产品名称 | 使用关键字生成 textarea（Apple/Cherry/…）+ 组合修饰词（例值 Cherry premium） | `product_name(keywords[])`，模板 `{keyword} {modifier}` |
| 产品类别 | 语言多选 | 词表枚举 |
| 颜色 / 尺寸 / 重量单位 | 语言 / 值 textarea(g/kg/oz) | 词表枚举 |
| 条码 | 类型多选(EAN8/EAN13/UPCA/UPCE/Code39/ISBN) + 正则展示 | `barcode(types[])`（等价 pattern 预设） |
| SKU | 正则表达式 textarea | ≈ 我们的 `template`/`pattern`，文档注明映射即可 |

### 3.7 网络与文件（电脑类）

#### IP 地址 (ipv4)
- Navicat: IPv4/IPv6 radio；sqlseed: `ipv4()` ⚠️ P1: `ipv6()` 新增或 `family` 参数

#### MAC 地址
- Navicat: 正则展示；sqlseed 缺失 ⚠️ P2 `mac_address()`（pattern 预设 `[0-9a-f]{2}(:[0-9a-f]{2}){5}`）

#### 主机名 / 网址 (url)
- Navicat: 子域 textarea(auth/drive/mail/…) + 顶级域 textarea(com/cn/info/…)
- sqlseed: `url()` ⚠️ P1: `subdomains[]` + `tlds[]`（两者同构，可共用参数组）

#### 文件路径 / 文件名称 / 文件扩展名
- Navicat: 路径类型多选(Windows/MacOS/Linux)、包含文件名称 checkbox、扩展名类型 dropdown、扩展名 textarea
- sqlseed 缺失 ⚠️ P2 `file_path(os[],include_name,extensions)` / `file_name(include_ext,extensions)` / `file_ext(extensions)`

## 4. 落地路线建议

- **P0（纯 UI，0 核心改动）**：枚举/加权枚举 textarea ✅（本次）；下拉"其他"组中拆分"产品/支付"占位组（待 P2 生成器就绪后启用）
- **P1（核心参数扩展，向后兼容）**：
  1. `email(domains[])`、`phone(region[],separator)`（尊重 LENGTH CHECK）、`uuid(hyphens)`、`ipv4/ipv6`
  2. `date/datetime` 具体日期范围 + 星期过滤；新增 `time`
  3. `name` 族生成器级 locale 覆盖
  4. FK 采样策略参数（random/unique/repeat-each-N）
  5. `sequence(start,step,min,max,loop)`
- **P2（新生成器/新概念）**：图像或二进制双模式（`image` / `file_from_folder`）、支付四件套、产品词表族、性别/称谓/婚姻等行业词表、文件三件套、MAC/主机名、全半角转换 transform、`default_ratio`（包含默认值）
- 每个新参数同步：`labels.js PARAM_LABELS` 中文名、`meta/generators`（自动来自 `_gen_*` 签名）、AI 修复白名单 `_GENERATOR_PARAM_WHITELIST`（sqlseed-ai strategies.py，否则 normalize_params 会剥掉新参数）

## 5. 截图 → 生成器对照速查

| 截图 | Navicat 生成器 | sqlseed 生成器 | 差距级 |
|---|---|---|---|
| 数字 | 数字 | integer/float | ✅ |
| 日期/日期时间/时间 | 日期类 | date/datetime/— | P1 |
| 序列 | 序列 | skip/template | P1 |
| 枚举 | 枚举 | choice/weighted_choice | ✅(UI textarea 已对齐) |
| 文本 | 文本 | text | ✅ |
| 布尔值 | 布尔值 | boolean | ✅ |
| 图像或二进制 | 图像或二进制 | bytes | **P2** |
| 外键 | 外键 | foreign_key | P1(策略) |
| UUID | UUID | uuid | P1(格式) |
| 正则表达式 | 正则表达式 | pattern | ✅ |
| 姓名 | 姓名 | name/first_name/last_name | P1(locale/格式) |
| 性别/称谓/婚姻状况 | 个人枚举 | — | P2 |
| 电子邮箱 | 电子邮箱 | email | P1(域) |
| 电话号码 | 电话号码 | phone | P1(地区/分隔符) |
| 社交网络ID | 社交网络 ID | username | ✅ |
| 职位名称 | 职位名称 | job_title | ✅(locale P1) |
| 公司名称 | 公司名称 | company | ✅(locale P1) |
| 部门/行业 | 商业枚举 | — | P2 |
| 地址/城市/地区 | 位置 | address/city/state | P1(类型/地区/格式) |
| 产品名称/类别/颜色/尺寸/重量单位/条码/SKU | 产品 | —/template | P2 |
| 支付方式/信用卡×3 | 支付 | — | P2 |
| IP地址/MAC地址/主机名/网址 | 电脑 | ipv4/—/—/url | P1(IPv6/子域/顶级域) P2(MAC/主机名) |
| 文件路径/文件名称/文件扩展名 | 电脑 | — | P2 |
