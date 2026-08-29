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
  state: '省份',
  zip_code: '邮政编码',
  country_code: '国家代码',
  url: '网址',
  uuid: 'UUID',
  ipv4: 'IP 地址',
  company: '公司',
  job_title: '职称',
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
  bytes: '二进制',
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
  mask: '号码格式',
  start_year: '起始年份',
  end_year: '结束年份',
  choices: '候选值',
  weighted_choices: '加权候选值',
  pattern: '正则表达式',
  regex: '正则表达式',
  template: '模板',
  sequence_start: '序列起始值',
  sequence_step: '序列步长',
  schema: 'JSON 结构',
};

export function paramLabel(p) {
  return PARAM_LABELS[p] || p;
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
