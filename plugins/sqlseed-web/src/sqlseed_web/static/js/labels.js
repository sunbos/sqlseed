// 生成器中文语义标注（Navicat 树节点括号标注的来源）。

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
  integer: '数字',
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
  skip: '序列',
  foreign_key: '外键',
  foreign_key_or_integer: '外键',
  autoincrement: '自增',
  __enrich__: '增强',
};

export function genLabel(gen) {
  return GEN_LABELS[gen] || gen || '—';
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

// 生成器分类（Navicat 式分组下拉，严格对照 示例UI/生成数据类型/ 的 7 组）。
// 顺序即下拉展示顺序；未收录的生成器自动落入末尾「其他」组。
// 空 gens 的组（支付 / 产品）是 Navicat 有、sqlseed 尚未实现的占位组：
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
    // Navicat：支付方式 / 信用卡类型 / 信用卡卡号 / 信用卡日期（P2）
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
    // Navicat：产品名称 / 产品类别 / 颜色 / 尺寸 / 重量单位 / 条码 / SKU（P2）
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
 * 返回 [{title, names, pending}]——pending 表示该组在 Navicat 中存在但
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
