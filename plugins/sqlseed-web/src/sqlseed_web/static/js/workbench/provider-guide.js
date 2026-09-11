// Verified against sqlseed's provider adapters and the linked upstream docs.
// Examples illustrate formats only; this module never runs a provider or edits
// the selected configuration. Recommendation is guidance, not a default change.
export function providerGuide(provider,locale='zh_CN') {
  const chinese=String(locale).startsWith('zh');
  const exampleNote='格式示例，非实时生成；实际结果取决于引擎、语言地区、字段规则与随机种子。';
  const commonLimit='引擎负责生成取值；字段业务含义、唯一性与关联关系仍需通过规则、预览和依赖检查确认。';
  if(provider==='faker')return {
    id:provider,title:'Faker',choice:'自然格式，首次使用推荐',recommended:true,
    summary:'适合姓名、地址、电话等自然格式的测试数据，支持多种语言与地区。',
    features:['按语言与地区生成姓名、地址和电话，便于检查本地化页面。','支持常见语义生成器；需要更细控制时可使用 Faker 原生方法。'],
    limits:['部分生成器未覆盖所选语言时，Faker 可能回退为英语内容。',commonLimit],
    examples:[{label:'姓名',value:chinese?'王小明':'Alex Morgan'},{label:'整数范围 1–5',value:'3'}],
    exampleNote,sources:[{label:'Faker 官方说明',url:'https://faker.readthedocs.io/en/master/'}],
  };
  if(provider==='mimesis')return {
    id:provider,title:'Mimesis',choice:'高性能取值',recommended:false,
    summary:'以高性能取值为特点，适合需要大量姓名、地址等多语言数据的场景。',
    features:['姓名、地址、公司等使用 Mimesis 数据源，与 Faker 的内容和格式可能不同。','支持 Mimesis 原生方法；本项目对中文姓名采用姓在前、名在后的格式。'],
    limits:['整体生成速度还取决于字段规则、外键处理和数据库写入。','高性能是 Mimesis 官方强调的特点；上游基准不等同于 sqlseed 的写库速度，具体语言支持以当前安装版本为准。',commonLimit],
    examples:[{label:'姓名',value:chinese?'陈子涵':'Taylor Reed'},{label:'整数范围 1–5',value:'3'}],
    exampleNote,sources:[{label:'Mimesis 官方特点',url:'https://mimesis.name/master/about.html'},{label:'Mimesis 上游基准',url:'https://mimesis.name/master/benchmarks.html'},{label:'Mimesis 语言与地区',url:'https://mimesis.name/master/locales.html'}],
  };
  if(provider==='base')return {
    id:provider,title:'Base',choice:'基础占位',recommended:false,
    summary:'内置占位引擎，适合验证字段类型、规则与生成流程。',
    features:['整数、日期、字符串等按规则生成；姓名、地址等语义字段使用程序构造的占位值。','由 sqlseed 内置，无需额外安装。'],
    limits:['选择中文不会把占位姓名转换成真实风格的中文姓名。',commonLimit],
    examples:[{label:'姓名',value:'first_001_1234 last_001_1234'},{label:'整数范围 1–5',value:'3'}],
    exampleNote,sources:[],
  };
  return {id:provider,title:String(provider||'未选择引擎'),choice:'自定义引擎',recommended:false,summary:'当前引擎暂无内置说明，请先查看样例并核对其字段规则。',features:[],limits:[commonLimit],examples:[],exampleNote,sources:[]};
}
