// 生成器中文语义标注（参考工具 树节点括号标注的来源）。

export const GEN_LABELS = {
  name: '姓名',
  first_name: '名字',
  last_name: '姓氏',
  username: '用户名',
  email: '电子邮箱',
  phone: '电话号码',
  address: '地址',
  city: '城市',
  country: '国家',
  state: '地区',
  zip_code: '邮政编码',
  country_code: '国家代码',
  url: '网址',
  uuid: 'UUID',
  ipv4: 'IP 地址',
  company: '公司名称',
  job_title: '职位名称',
  catch_phrase: '口号',
  date: '日期',
  datetime: '日期时间',
  timestamp: '时间戳',
  time: '时间',
  integer: '整数',
  float: '小数',
  boolean: '布尔',
  choice: '枚举',
  weighted_choice: '加权枚举',
  pattern: '正则表达式',
  template: '模板',
  string: '字符串',
  text: '文本',
  sentence: '句子',
  word: '单词',
  password: '密码',
  json: 'JSON',
  bytes: '图像或二进制',
  skip: '数据库默认值',
  foreign_key: '外键',
  foreign_key_or_integer: '外键',
  autoincrement: '自增',
  __enrich__: '增强',
};

export function genLabel(gen) {
  return GEN_LABELS[gen] || gen || '—';
}

// Output illustrations supplement the live catalogue, never replace real previews.
const GENERATOR_GUIDES = {
  name: ['人物的完整姓名；商品名请使用枚举或模板。', '张晓明 / Alex Smith'],
  first_name: ['人物的名字部分。', '晓明 / Alex'], last_name: ['人物的姓氏部分。', '张 / Smith'],
  username: ['登录名或账号名称。', 'alex_chen'], email: ['电子邮箱地址；语言与格式受全局引擎影响。', 'alex@example.test'],
  phone: ['电话号码；可用号码格式统一输出。', '13800138000'], address: ['完整地址；使用全局语言与地区。', '北京市朝阳区…'],
  city: ['城市名称。', '北京 / London'], state: ['省、州或地区名称。', '浙江省 / California'],
  country: ['国家名称。', '中国 / Canada'], country_code: ['国家代码。', 'CN'], zip_code: ['邮政编码。', '100000'],
  url: ['网站地址。', 'https://example.test'], uuid: ['通用唯一标识符。', '1f22b412-3d73-4e22-a5e4-40a7f18ce319'],
  ipv4: ['IPv4 地址。', '192.0.2.10'], company: ['公司或组织名称。', '示例科技有限公司'],
  job_title: ['职位名称。', '软件工程师'], catch_phrase: ['营销口号或短标语。', '让每一天更简单'],
  date: ['在日期范围内随机取值，可限定工作日。', '2026-09-07'],
  datetime: ['在日期和时间范围内随机取值。', '2026-09-07 14:30:00'],
  timestamp: ['生成日期时间对象；写入格式由数据库列类型决定。', '2026-09-07 14:30:00'],
  time: ['一天内的时间，可限定营业时段。', '09:30:00'],
  integer: ['范围内的随机整数，适合数量、年龄或库存。', '12'],
  float: ['范围内的随机小数，适合金额或度量值。', '128.50'], boolean: ['真或假，适合启用、完成等标记。', 'true / false'],
  choice: ['从你提供的候选值中随机选一个，适合状态或商品名。', 'pending / paid / shipped'],
  weighted_choice: ['按指定权重选择候选值，适合不均匀分布。', '普通 80% / VIP 20%'],
  pattern: ['生成符合正则表达式的值，适合固定格式编码。', '正则 [A-Z]{3}[0-9]{4} → ABC1234'],
  template: ['按模板生成编号或组合文本，可包含递增序号。', 'SKU-{sequence:04d} → SKU-0001'],
  string: ['从候选字符中生成随机字符串，适合随机代码；名称建议用枚举。', 'aB72xQ'],
  text: ['较长的自然语言文本。', '一段说明文字…'], sentence: ['一条自然语言句子。', '这是一条示例描述。'],
  word: ['一个单词。', 'river'], password: ['随机密码字符串。', 'a9B!x7Qp'],
  json: ['生成 JSON 值，可指定对象结构。', '{"active": true}'], bytes: ['生成字节或图像内容，适合二进制列。', '16 字节 / PNG 图像'],
};
export function genGuide(generator) {
  const guide = GENERATOR_GUIDES[generator];
  return guide ? {purpose: guide[0], example: guide[1]} : {purpose: '扩展生成器；参数由当前服务提供。', example: ''};
}

// 生成器参数中文标签（genform 动态参数表单）。未收录的参数原样显示。
export const PARAM_LABELS = {
  min_length: '最小长度',
  max_length: '最大长度',
  charset: '字符集',
  min_value: '最小值',
  max_value: '最大值',
  precision: '小数位数',
  length: '长度',
  width: '图像宽度',
  height: '图像高度',
  image_format: '图像格式',
  folder: '文件夹路径',
  extensions: '扩展名筛选',
  mask: '号码格式',
  start_year: '起始年份',
  end_year: '结束年份',
  start_date: '开始日期',
  end_date: '结束日期',
  all_day: '一整天',
  start_time: '开始时间',
  end_time: '结束时间',
  weekdays: '星期',
  choices: '候选值',
  weighted_choices: '加权候选值',
  pattern: '正则表达式',
  regex: '正则表达式',
  template: '模板',
  sequence_start: '序列起始值',
  sequence_step: '序列步长',
  schema: 'JSON 结构',
  value: '固定值',
  n: '数量',
  num_words: '单词数',
};

export function paramLabel(p) {
  return PARAM_LABELS[p] || p;
}

// 生成器分类（参考工具 式分组下拉，严格对照 示例UI/生成数据类型/ 的 7 组）。
// 顺序即下拉展示顺序；未收录的生成器自动落入末尾「其他」组。
// 空 gens 的组（支付 / 产品）是 参考工具 有、sqlseed 尚未实现的占位组：
// 下拉里显示为禁用项，等 P2 生成器落地后自动变为可选（无需改本文件）。
export const GEN_CATEGORIES = [
  {
    title: '通用',
    gens: ['integer', 'float', 'boolean', 'date', 'datetime', 'timestamp',
      'choice', 'weighted_choice', 'text', 'string', 'sentence', 'word',
      'pattern', 'template', 'uuid', 'json', 'bytes', 'time',
      'skip', 'foreign_key', 'foreign_key_or_integer', 'autoincrement'],
  },
  {
    title: '个人',
    gens: ['name', 'first_name', 'last_name', 'username', 'password',
      'email', 'phone', 'job_title'],
  },
  {
    // 参考工具：支付方式 / 信用卡类型 / 信用卡卡号 / 信用卡日期（P2）
    title: '支付',
    gens: [],
  },
  {
    title: '商业',
    gens: ['company', 'catch_phrase'],
  },
  {
    title: '位置',
    gens: ['address', 'city', 'state', 'country', 'zip_code', 'country_code'],
  },
  {
    // 参考工具：产品名称 / 产品类别 / 颜色 / 尺寸 / 重量单位 / 条码 / SKU（P2）
    title: '产品',
    gens: [],
  },
  {
    title: '电脑',
    gens: ['url', 'ipv4'],
  },
];

/** 占位组在下拉里显示的提示文案。 */
export const PENDING_GROUP_HINT = '（暂无生成器）';

/**
 * 把 meta.names（全部生成器）按分类分组。
 * 返回 [{title, names, pending}]——pending 表示该组在 参考工具 中存在但
 * sqlseed 尚无对应生成器（支付/产品），调用方应渲染为禁用项。
 * 兜底「其他」组保证不丢项。
 */
export function groupGenerators(names) {
  const remaining = new Set(names);
  const groups = [];
  for (const cat of GEN_CATEGORIES) {
    const hit = cat.gens.filter((g) => remaining.has(g));
    for (const g of hit) remaining.delete(g);
    groups.push({ title: cat.title, names: hit, pending: hit.length === 0 });
  }
  if (remaining.size) {
    groups.push({ title: '其他', names: [...remaining].sort(), pending: false });
  }
  return groups;
}

// 列的树节点语义标注：优先外键/自增，其次生成器语义。
export function colAnnotation(col, spec, fkCols) {
  if (fkCols.has(col.name)) return '外键';
  if (col.is_primary_key && col.is_autoincrement) return '序列';
  if (spec && spec.generator_name && spec.generator_name !== 'skip') {
    return genLabel(spec.generator_name);
  }
  if (spec && spec.generator_name === 'skip' && !col.is_primary_key) return '默认值';
  return null;
}
