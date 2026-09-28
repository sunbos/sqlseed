import { tr } from './i18n.js';
import './i18n/messages/labels.js';
// 生成器中文语义标注（参考工具 树节点括号标注的来源）。

export const GEN_LABELS = {
  name: tr('labels.generator.name'),
  first_name: tr('labels.generator.first_name'),
  last_name: tr('labels.generator.last_name'),
  username: tr('labels.generator.username'),
  email: tr('labels.generator.email'),
  phone: tr('labels.generator.phone'),
  address: tr('labels.generator.address'),
  city: tr('labels.generator.city'),
  country: tr('labels.generator.country'),
  state: tr('labels.generator.state'),
  zip_code: tr('labels.generator.zip_code'),
  country_code: tr('labels.generator.country_code'),
  url: tr('labels.generator.url'),
  uuid: tr('labels.generator.uuid'),
  ipv4: tr('labels.generator.ipv4'),
  company: tr('labels.generator.company'),
  job_title: tr('labels.generator.job_title'),
  catch_phrase: tr('labels.generator.catch_phrase'),
  date: tr('labels.generator.date'),
  datetime: tr('labels.generator.datetime'),
  timestamp: tr('labels.generator.timestamp'),
  time: tr('labels.generator.time'),
  integer: tr('labels.generator.integer'),
  float: tr('labels.generator.float'),
  boolean: tr('labels.generator.boolean'),
  choice: tr('labels.generator.choice'),
  weighted_choice: tr('labels.generator.weighted_choice'),
  pattern: tr('labels.generator.pattern'),
  template: tr('labels.generator.template'),
  string: tr('labels.generator.string'),
  text: tr('labels.generator.text'),
  sentence: tr('labels.generator.sentence'),
  word: tr('labels.generator.word'),
  password: tr('labels.generator.password'),
  json: tr('labels.generator.json'),
  bytes: tr('labels.generator.bytes'),
  skip: tr('labels.generator.skip'),
  foreign_key: tr('labels.generator.foreign_key'),
  foreign_key_or_integer: tr('labels.generator.foreign_key_or_integer'),
  autoincrement: tr('labels.generator.autoincrement'),
  __enrich__: tr('labels.generator.__enrich__'),
};

export function genLabel(gen) {
  return GEN_LABELS[gen] || gen || '—';
}

// Output illustrations supplement the live catalogue, never replace real previews.
const GENERATOR_GUIDES = {
  name: [tr('labels.purpose.name'), tr('labels.example.name')],
  first_name: [tr('labels.purpose.first_name'), tr('labels.example.first_name')], last_name: [tr('labels.purpose.last_name'), tr('labels.example.last_name')],
  username: [tr('labels.purpose.username'), 'alex_chen'], email: [tr('labels.purpose.email'), 'alex@example.test'],
  phone: [tr('labels.purpose.phone'), '13800138000'], address: [tr('labels.purpose.address'), tr('labels.example.address')],
  city: [tr('labels.purpose.city'), tr('labels.example.city')], state: [tr('labels.purpose.state'), tr('labels.example.state')],
  country: [tr('labels.purpose.country'), tr('labels.example.country')], country_code: [tr('labels.purpose.country_code'), 'CN'], zip_code: [tr('labels.purpose.zip_code'), '100000'],
  url: [tr('labels.purpose.url'), 'https://example.test'], uuid: [tr('labels.purpose.uuid'), '1f22b412-3d73-4e22-a5e4-40a7f18ce319'],
  ipv4: [tr('labels.purpose.ipv4'), '192.0.2.10'], company: [tr('labels.purpose.company'), tr('labels.example.company')],
  job_title: [tr('labels.purpose.job_title'), tr('labels.example.job_title')], catch_phrase: [tr('labels.purpose.catch_phrase'), tr('labels.example.catch_phrase')],
  date: [tr('labels.purpose.date'), '2026-09-07'],
  datetime: [tr('labels.purpose.datetime'), '2026-09-07 14:30:00'],
  timestamp: [tr('labels.purpose.timestamp'), '2026-09-07 14:30:00'],
  time: [tr('labels.purpose.time'), '09:30:00'],
  integer: [tr('labels.purpose.integer'), '12'],
  float: [tr('labels.purpose.float'), '128.50'], boolean: [tr('labels.purpose.boolean'), 'true / false'],
  choice: [tr('labels.purpose.choice'), 'pending / paid / shipped'],
  weighted_choice: [tr('labels.purpose.weighted_choice'), tr('labels.example.weighted_choice')],
  pattern: [tr('labels.purpose.pattern'), tr('labels.example.pattern')],
  template: [tr('labels.purpose.template'), 'SKU-{sequence:04d} → SKU-0001'],
  string: [tr('labels.purpose.string'), 'aB72xQ'],
  text: [tr('labels.purpose.text'), tr('labels.example.text')], sentence: [tr('labels.purpose.sentence'), tr('labels.example.sentence')],
  word: [tr('labels.purpose.word'), 'river'], password: [tr('labels.purpose.password'), 'a9B!x7Qp'],
  json: [tr('labels.purpose.json'), '{"active": true}'], bytes: [tr('labels.purpose.bytes'), tr('labels.example.bytes')],
};
export function genGuide(generator) {
  const guide = GENERATOR_GUIDES[generator];
  return guide ? {purpose: guide[0], example: guide[1]} : {purpose: tr('labels.extensionPurpose'), example: ''};
}

// 生成器参数中文标签（genform 动态参数表单）。未收录的参数原样显示。
export const PARAM_LABELS = {
  min_length: tr('labels.parameter.min_length'),
  max_length: tr('labels.parameter.max_length'),
  charset: tr('labels.parameter.charset'),
  min_value: tr('labels.parameter.min_value'),
  max_value: tr('labels.parameter.max_value'),
  precision: tr('labels.parameter.precision'),
  length: tr('labels.parameter.length'),
  width: tr('labels.parameter.width'),
  height: tr('labels.parameter.height'),
  image_format: tr('labels.parameter.image_format'),
  folder: tr('labels.parameter.folder'),
  extensions: tr('labels.parameter.extensions'),
  mask: tr('labels.parameter.mask'),
  start_year: tr('labels.parameter.start_year'),
  end_year: tr('labels.parameter.end_year'),
  start_date: tr('labels.parameter.start_date'),
  end_date: tr('labels.parameter.end_date'),
  all_day: tr('labels.parameter.all_day'),
  start_time: tr('labels.parameter.start_time'),
  end_time: tr('labels.parameter.end_time'),
  weekdays: tr('labels.parameter.weekdays'),
  choices: tr('labels.parameter.choices'),
  weighted_choices: tr('labels.parameter.weighted_choices'),
  pattern: tr('labels.parameter.pattern'),
  regex: tr('labels.parameter.regex'),
  template: tr('labels.parameter.template'),
  sequence_start: tr('labels.parameter.sequence_start'),
  sequence_step: tr('labels.parameter.sequence_step'),
  schema: tr('labels.parameter.schema'),
  value: tr('labels.parameter.value'),
  n: tr('labels.parameter.n'),
  num_words: tr('labels.parameter.num_words'),
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
    title: tr('labels.general'),
    gens: ['integer', 'float', 'boolean', 'date', 'datetime', 'timestamp',
      'choice', 'weighted_choice', 'text', 'string', 'sentence', 'word',
      'pattern', 'template', 'uuid', 'json', 'bytes', 'time',
      'skip', 'foreign_key', 'foreign_key_or_integer', 'autoincrement'],
  },
  {
    title: tr('labels.personal'),
    gens: ['name', 'first_name', 'last_name', 'username', 'password',
      'email', 'phone', 'job_title'],
  },
  {
    // 参考工具：支付方式 / 信用卡类型 / 信用卡卡号 / 信用卡日期（P2）
    title: tr('labels.payment'),
    gens: [],
  },
  {
    title: tr('labels.business'),
    gens: ['company', 'catch_phrase'],
  },
  {
    title: tr('labels.location'),
    gens: ['address', 'city', 'state', 'country', 'zip_code', 'country_code'],
  },
  {
    // 参考工具：产品名称 / 产品类别 / 颜色 / 尺寸 / 重量单位 / 条码 / SKU（P2）
    title: tr('labels.product'),
    gens: [],
  },
  {
    title: tr('labels.computer'),
    gens: ['url', 'ipv4'],
  },
];

/** 占位组在下拉里显示的提示文案。 */
export const PENDING_GROUP_HINT = tr('labels.pending');

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
    groups.push({ title: tr('labels.other'), names: [...remaining].sort((left, right) => left < right ? -1 : Number(left > right)), pending: false });
  }
  return groups;
}

// 列的树节点语义标注：优先外键/自增，其次生成器语义。
export function colAnnotation(col, spec, fkCols) {
  if (fkCols.has(col.name)) return tr('labels.generator.foreign_key_or_integer');
  if (col.is_primary_key && col.is_autoincrement) return tr('labels.sequence');
  if (spec?.generator_name && spec.generator_name !== 'skip') {
    return genLabel(spec.generator_name);
  }
  if (spec?.generator_name === 'skip' && !col.is_primary_key) return tr('labels.defaultValue');
  return null;
}
