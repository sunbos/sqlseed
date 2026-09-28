import { registerMessages } from '../../i18n.js';

registerMessages('providerGuide', {
  "exampleNote": [
    "格式示例，非实时生成；实际结果取决于引擎、语言地区、字段规则与随机种子。",
    "Format examples, not live output. Actual results depend on the engine, data language and region, field rules and random seed."
  ],
  "commonLimit": [
    "引擎负责生成取值；字段业务含义、唯一性与关联关系仍需通过规则、预览和依赖检查确认。",
    "The engine generates values. Use rules, previews and dependency checks to verify business meaning, uniqueness and relationships."
  ],
  "fakerChoice": [
    "自然格式，首次使用推荐",
    "Natural formats; recommended for getting started"
  ],
  "fakerSummary": [
    "适合姓名、地址、电话等自然格式的测试数据，支持多种语言与地区。",
    "Natural-looking names, addresses and phone numbers in multiple languages and regions."
  ],
  "fakerLocale": [
    "按语言与地区生成姓名、地址和电话，便于检查本地化页面。",
    "Generate localized names, addresses and phone numbers to test localized pages."
  ],
  "fakerNative": [
    "支持常见语义生成器；需要更细控制时可使用 Faker 原生方法。",
    "Supports common semantic generators. Use native Faker methods for finer control."
  ],
  "fakerFallback": [
    "部分生成器未覆盖所选语言时，Faker 可能回退为英语内容。",
    "Faker may fall back to English when a generator does not support the selected language."
  ],
  "name": [
    "姓名",
    "Name"
  ],
  "integerRange": [
    "整数范围 1–5",
    "Integer range 1–5"
  ],
  "fakerDocs": [
    "Faker 官方说明",
    "Faker documentation"
  ],
  "mimesisChoice": [
    "高性能取值",
    "High-performance value generation"
  ],
  "mimesisSummary": [
    "以高性能取值为特点，适合需要大量姓名、地址等多语言数据的场景。",
    "Designed for high-performance value generation, including large volumes of multilingual names and addresses."
  ],
  "mimesisSource": [
    "姓名、地址、公司等使用 Mimesis 数据源，与 Faker 的内容和格式可能不同。",
    "Names, addresses and companies use Mimesis data sources; content and formats may differ from Faker."
  ],
  "mimesisNative": [
    "支持 Mimesis 原生方法；本项目对中文姓名采用姓在前、名在后的格式。",
    "Supports native Mimesis methods. Chinese names in this project place the family name before the given name."
  ],
  "speedLimit": [
    "整体生成速度还取决于字段规则、外键处理和数据库写入。",
    "Overall speed also depends on field rules, foreign keys and database writes."
  ],
  "benchmarkLimit": [
    "高性能是 Mimesis 官方强调的特点；上游基准不等同于 sqlseed 的写库速度，具体语言支持以当前安装版本为准。",
    "High performance is a feature emphasized by Mimesis. Its benchmarks do not measure sqlseed database write speed; language support depends on the installed version."
  ],
  "mimesisFeatures": [
    "Mimesis 官方特点",
    "Mimesis features"
  ],
  "mimesisBenchmarks": [
    "Mimesis 上游基准",
    "Mimesis benchmarks"
  ],
  "mimesisLocales": [
    "Mimesis 语言与地区",
    "Mimesis languages and regions"
  ],
  "baseChoice": [
    "基础占位",
    "Basic placeholders"
  ],
  "baseSummary": [
    "内置占位引擎，适合验证字段类型、规则与生成流程。",
    "A built-in placeholder engine for verifying field types, rules and the generation workflow."
  ],
  "baseValues": [
    "整数、日期、字符串等按规则生成；姓名、地址等语义字段使用程序构造的占位值。",
    "Integers, dates and strings follow the rules; semantic fields such as names and addresses use programmatically constructed placeholders."
  ],
  "baseBuiltIn": [
    "由 sqlseed 内置，无需额外安装。",
    "Included in sqlseed; no additional installation required."
  ],
  "baseLocale": [
    "选择中文不会把占位姓名转换成真实风格的中文姓名。",
    "Selecting Chinese does not turn placeholder names into natural Chinese names."
  ],
  "none": [
    "未选择引擎",
    "No engine selected"
  ],
  "custom": [
    "自定义引擎",
    "Custom engine"
  ],
  "customSummary": [
    "当前引擎暂无内置说明，请先查看样例并核对其字段规则。",
    "No built-in guidance is available for this engine. Review samples and field rules first."
  ]
});
