// 列属性面板（参考工具 Step2 右栏）七段式布局：
//   字段名 + 类型副标题 → 生成器下拉 → 类型专属参数区 → 预览 + 刷新 →
//   通用区（NULL 百分比 / 唯一）→ 重置属性
// 布局顺序与「通用区按生成器裁剪」矩阵严格对照
// docs/superpowers/plans/generator_ui_reference.md（§1.3 裁剪矩阵 / §9 检查要点）。

import { h, clear, post, msg } from './api.js';
import { createDropdown } from './dropdown.js';
import { openFilePicker } from './filepicker.js';
import { genLabel, paramLabel, groupGenerators, PENDING_GROUP_HINT } from './labels.js';

// 参考工具：勾选「包含 NULL 值」后百分比框默认 5，且未勾选时处于禁用态（§9.5）。
const DEFAULT_PERCENT = 5;

// 通用区裁剪矩阵（§1.3）。
// 注意：参考工具 的「序列」在 sqlseed 里对应的是 `skip`（自增列由数据库生成，
// 不在用户可选的生成器下拉里），不是 `template`——template 可含随机片段
// （如 SKU-{random_string:4}-{sequence:03d}），NULL% 与唯一对它都有意义。
// 曾误按「序列 → 通用区全无」裁掉 template，导致这两项不可见也不可改。
// 真正的独立 `sequence` 生成器属 P1，落地后加入此集合即可。
const NO_COMMON_GENS = new Set();
// 词表类（枚举 / 文本）值域有限，「设置唯一」无意义；图像或二进制同样不提供。
const NO_UNIQUE_GENS = new Set(['text', 'choice', 'weighted_choice', 'bytes']);
// 图像或二进制没有例值预览区（参考工具 该面板无预览）。
const NO_PREVIEW_GENS = new Set(['bytes']);

// 参数控件形态：显式列举而非用 /min|max|length/ 之类的名字正则匹配——
// precision、start_year 曾因此被误渲染成文本框。
const NUMERIC_PARAMS = new Set([
  'min_value', 'max_value', 'min_length', 'max_length', 'precision', 'length',
  'width', 'height', 'start_year', 'end_year', 'sequence_start', 'sequence_step',
  'n', 'num_words', 'value',
]);
const TEXTAREA_PARAMS = new Set(['pattern', 'regex', 'template']);

const PARAM_PLACEHOLDERS = {
  charset: '留空 = 默认字符集（字母/数字/空格/_/-）',
  mask: '号码模板，如 1##-####-####（# 为随机数字）',
  schema: '{"type":"object","properties":{"name":{"type":"string"}}}',
  template: '支持 {sequence}、{random:3} 等占位符',
  folder: '服务器本地文件夹路径，如 /Users/you/Pictures',
  extensions: '逗号分隔，如: png,jpg,svg',
  pattern: '[0-9]{11}',
  regex: '[0-9]{11}',
  start_year: '2000',
  end_year: '2026',
  min_length: '1',
  max_length: '100',
};

// 图像格式：核心 _gen_bytes 仅识别 png / jpeg（jpeg 需 Pillow，否则回退 PNG），
// 用下拉代替自由文本输入，避免写入无效值。
const IMAGE_FORMATS = [
  { value: 'png', label: 'PNG' },
  { value: 'jpeg', label: 'JPEG（需安装 Pillow，否则回退 PNG）' },
];

// 日期时间三件套（参考工具 日期/时间/日期时间面板）。
// 参数在面板上的排列顺序：精确日期优先，年份作为兼容项靠后。
const PARAM_ORDER = [
  'start_date', 'end_date', 'all_day', 'start_time', 'end_time', 'weekdays',
  'start_year', 'end_year',
];
// 有了精确日期参数后，年份参数降级为「旧配置兼容回退」：核心仍接受
// start_year / end_year（旧 YAML 继续生效），但仅在 start_date / end_date 未提供时生效。
// 面板不再暴露它们——两套边界并排会让人不知道谁优先。
// 另外 pattern 的 regex 是 pattern 的别名（核心 effective = pattern || regex），
// weighted_choice 的 choices 是 [{value,weight}] 对象列表（「每行一个值」的
// textarea 无法编辑，其字符串数组形式核心会崩）——各只保留一个主键。
const HIDDEN_PARAMS = {
  date: new Set(['start_year', 'end_year']),
  datetime: new Set(['start_year', 'end_year']),
  timestamp: new Set(['start_year', 'end_year']),
  pattern: new Set(['regex']),
  weighted_choice: new Set(['choices']),
};

// 日期类生成器：AI 回填的 YAML 经常整个省略 params（LLM 倾向不写可选字段，
// 实测 gemma4:31b-cloud 对 date/datetime 一律返回空 params），面板就会一片空白。
// 此时填入核心默认值——核心本来就这么跑，显示出来比留空更贴近 参考工具
// （其日期面板同样预填 2000-01-01 / 今天）。
const DATE_DEFAULT_GENS = new Set(['date', 'datetime', 'timestamp']);

// 星期：Monday=0 … Sunday=6（与核心 normalize_weekdays 一致）
const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'];

// 空参数必然让核心抛错的生成器（实测仅这两个）：切换生成器后参数区还是空的，
// 400ms 防抖预览就会发一个注定失败的请求。与其闪一条「预览失败」，不如提示待填。
const REQUIRED_PARAMS = {
  choice: ['choices'],
  weighted_choice: ['weighted_choices'],
};
const WEEKDAY_MODES = [
  { value: 'all', label: '全部' },
  { value: 'workdays', label: '工作日' },
  { value: 'custom', label: '自定义' },
];

/**
 * @param {object} opts
 * @param {string} opts.connId
 * @param {object} opts.meta - /api/meta/generators 响应（names + params）
 * @param {(table: string) => object[]} opts.foreignKeysOf - 数据库 schema 的外键关系
 * @param {(table: string, col: string, cfg: object|null) => void} opts.onChange
 *   cfg 为该列的 ColumnConfig 形状（generator/params/null_ratio/constraints），
 *   null 表示跟随零配置推断。
 */
export function createGenForm({ connId, meta, uniqueColumnsOf, foreignKeysOf, onChange }) {
  const el = h('div', { class: 'genform' });
  let current = null; // {table, col, colInfo, inferred, zeroConfig}
  let form = {};      // {generator, params, null_ratio, unique, constraints, options}
  let previewBox = null; // 当前预览容器（render() 时更新）
  let previewTimer = null;
  let paramsHolder = null; // 参数区容器（保留引用，不按 section 顺序查找）
  let bytesModeState = null; // bytes 双模式的显式选择（'image'|'folder'|null=按参数推导）
  // 数据库唯一列查询回调（wizard 注入）：table → Set<column>。缺省视为空集。
  const uniqueColsOf = uniqueColumnsOf || (() => new Set());
  const foreignKeys = () => current
    ? (foreignKeysOf?.(current.table) || []).filter((fk) => fk.column === current.col)
    : [];
  let nullPctInput = null; // NULL 百分比输入框（勾选框切换时联动禁用态）
  // 本轮 render() 创建的 dropdown。render() 会整体重建 DOM，若不先 destroy，
  // 旧的 scroll/mousedown 监听会残留在 document 上（面板开着被丢弃时）。
  let dropdowns = [];
  const paramErrors = new Map(); // 无效编辑草稿不写入 form.params，也不用于预览。

  // 防抖自动预览：生成器/参数/NULL/唯一任一变化后 400ms 刷新例值。
  // 之前只在选中列和手动「刷新」时预览，改参数后一直显示旧值（实测发现）。
  function schedulePreview() {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      previewTimer = null;
      if (current && previewBox && previewBox.isConnected) doPreview(previewBox);
    }, 400);
  }

  function cleanParams() {
    const out = {};
    for (const [k, v] of Object.entries(form.params)) {
      if (v === undefined || v === null || v === '') continue;
      out[k] = v;
    }
    return out;
  }

  /** 组装单列 ColumnConfig（emit 与预览共用，避免两处规则漂移）。 */
  function buildCfg() {
    if (foreignKeys().length && !isDbGenerated()) {
      // 由 schema 解析引用关系；不把运行时缓存的父表值或导入的普通生成器参数写回配置。
      // 使用解析型生成器，保留核心对空父表、可空外键及自引用的处理。
      const cfg = { generator: 'foreign_key_or_integer', params: { ...form.params } };
      if (form.null_ratio > 0 && !dbNotNull()) cfg.null_ratio = form.null_ratio / 100;
      const constraints = { ...form.constraints };
      // 复合主键成员并非单列唯一；只补充 schema 明确报告的单列唯一约束。
      if (uniqueColsOf(current.table)?.has(current.col)) constraints.unique = true;
      if (Object.keys(constraints).length) cfg.constraints = constraints;
      return cfg;
    }
    // 派生列走 ColumnConfig 的 derived 模式（derive_from + expression），
    // 与 generator 互斥——退化成 generator 会静默改写 AI 的配置，并在参与
    // 跨列 CHECK 时因类型不匹配直接预览失败。
    const cfg = { ...form.options };
    if (form.derived) {
      cfg.derive_from = form.derived;
      if (form.expression) cfg.expression = form.expression;
    } else {
      cfg.generator = form.generator;
      cfg.params = cleanParams();
    }
    const constraints = { ...form.constraints };
    // 通用区被裁剪时（序列类）不发送对应字段——否则切到模板类生成器后，
    // 之前勾的 NULL/唯一会因为控件不可见而「看不见也改不掉」。
    const showCommon = !NO_COMMON_GENS.has(form.generator);
    // form.null_ratio 是 0–100 百分比；核心 ColumnConfig.null_ratio 是 0–1
    // 小数（le=1.0）——发送前必须除以 100，否则 preview/fill 直接 422。
    // 数据库硬约束兜底：NOT NULL 强制不带 null_ratio；数据库唯一强制 unique。
    if (showCommon && form.null_ratio > 0 && !dbNotNull()) cfg.null_ratio = form.null_ratio / 100;
    if (dbUnique() || (showCommon && !NO_UNIQUE_GENS.has(form.generator) && form.unique)) {
      constraints.unique = true;
    } else {
      delete constraints.unique;
    }
    if (Object.keys(constraints).length) cfg.constraints = constraints;
    return cfg;
  }

  function emit() {
    if (!current || !onChange) return;
    onChange(current.table, current.col, buildCfg());
  }

  /** 注册 dropdown 以便 render() 重建时统一 destroy（防监听器泄漏）。 */
  function track(dd) {
    dropdowns.push(dd);
    return dd;
  }

  function render(preview = true) {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = null;
    previewBox = null;
    paramsHolder = null;
    nullPctInput = null;
    paramErrors.clear();
    // 旧 dropdown 的 scroll/mousedown 监听挂在 document 上，必须先注销再丢弃 DOM。
    for (const dd of dropdowns) dd.destroy();
    dropdowns = [];
    clear(el);
    if (!current) {
      el.append(h('div', { class: 'muted', style: 'padding:24px' }, '在左侧树中选择一列以配置生成器。'));
      return;
    }
    const { col, colInfo } = current;
    el.append(
      h('div', { class: 'genform-head' },
        h('div', { class: 'genform-title' }, col),
        h('div', { class: 'muted' }, `${colInfo.type}${colInfo.nullable ? '' : ' NOT NULL'}${colInfo.is_primary_key ? ' · PK' : ''}`),
      ),
    );

    // 外键身份来自数据库，不能被 AI、导入配置或 NULL 比例编辑改成普通生成器。
    if (foreignKeys().length && !isDbGenerated()) {
      renderForeignKey(preview);
      return;
    }

    // 派生列：没有生成器可配（与 derived 模式互斥），直接展示派生来源。
    if (form.derived) {
      const src = Array.isArray(form.derived) ? form.derived.join('、') : form.derived;
      el.append(
        formRow('派生自', h('span', {}, src || '—')),
        form.expression ? formRow('表达式', h('span', { class: 'mono' }, form.expression)) : null,
        h('div', { class: 'genform-section' },
          h('div', { class: 'msg warn' },
            '该列由其它列派生（derive_from），与「生成器」互斥，属性面板不可编辑。'
            + '要改回普通生成器，请点下方「重置属性」。'),
        ),
      );
      // 预览仍可用（派生结果来自源列），直接渲染，跳过参数区与通用区。
      const out = h('div', { class: 'genform-preview' });
      previewBox = out;
      el.append(h('div', { class: 'genform-section' }, formRow('预览', out)));
      if (preview) doPreview(out);
      el.append(h('div', { class: 'genform-section' },
        h('button', { class: 'small', onclick: reset }, '重置属性')));
      return;
    }

    // ② 自增主键（序列）列：值由数据库生成，sqlseed 跳过不生成（mapper 最高
    // 优先级），任何用户配置都不会生效——整个属性面板锁定为只读，避免「能改
    // 但改了没用」的误导。
    if (isDbGenerated()) {
      el.append(
        h('div', { class: 'msg warn', style: 'margin:8px 0' },
          '该列是自增主键（序列）：值由数据库自动生成，sqlseed 跳过不生成，'
          + '无需也不可配置。'),
        h('div', { class: 'genform-section' },
          formRow('预览', h('span', { class: 'muted' }, '由数据库自增生成，不预览'))),
      );
      return;
    }

    // ③ 生成器下拉：7 类分组（通用/个人/支付/商业/位置/产品/电脑）。
    // 未实现的组（支付/产品）渲染为禁用占位项，等 P2 生成器就绪后自动可选。
    const genOpts = [];
    for (const grp of groupGenerators(meta.names)) {
      if (grp.pending) {
        genOpts.push({
          value: `__pending_${grp.title}`, label: PENDING_GROUP_HINT,
          group: grp.title, disabled: true,
        });
        continue;
      }
      for (const name of grp.names) {
        genOpts.push({ value: name, label: `${genLabel(name)}（${name}）`, group: grp.title });
      }
    }
    const genSel = track(createDropdown({
      value: form.generator,
      options: genOpts,
      width: '260px',
      onChange: (v) => {
        if (v === form.generator) return;
        form.generator = v;
        form.params = {};
        // 原生方法覆盖属于原生成器，显式换生成器后不可继续覆盖新选择。
        delete form.options.faker_method;
        delete form.options.mimesis_method;
        delete form.options.native_params;
        bytesModeState = null;
        applyDateDefaults();
        // 参数、预览和通用区都依赖生成器，必须一起重建并清理旧下拉监听。
        render(false);
        emit();
        schedulePreview();
      },
    }));
    el.append(formRow('生成器', genSel.el));

    // ③ 类型专属参数区
    paramsHolder = h('div', { class: 'genform-params' });
    el.append(paramsHolder);
    renderParams();

    // ④ 预览 + 刷新
    if (NO_PREVIEW_GENS.has(form.generator)) {
      previewBox = null; // 图像或二进制面板没有预览区
    } else {
      const previewOut = h('div', { class: 'genform-preview' });
      previewBox = previewOut;
      el.append(
        h('div', { class: 'genform-section' },
          formRow('预览', h('div', { class: 'row genform-inline' },
            previewOut,
            h('button', { class: 'small', onclick: () => doPreview(previewOut) }, '刷新'),
          )),
        ),
      );
      if (preview) doPreview(previewOut);
    }

    // ⑤ 通用区（序列类整体隐藏）
    if (!NO_COMMON_GENS.has(form.generator)) {
      const pctInput = h('input', {
        type: 'number', class: 'num-input', value: form.null_ratio || DEFAULT_PERCENT,
        min: 0, max: 100,
        disabled: dbNotNull() || form.null_ratio <= 0,
        oninput: (e) => { form.null_ratio = +e.target.value; emit(); schedulePreview(); },
      });
      nullPctInput = pctInput;
      const notNull = dbNotNull();
      const common = [
        // 行标签即属性名（参考工具 同款两栏网格），控件只放勾选框本身。
        formRow('包含 NULL 值', h('input', {
          type: 'checkbox', checked: form.null_ratio > 0 && !notNull,
          disabled: notNull, // 数据库 NOT NULL：不可配置（配了必 IntegrityError）
          onchange: (e) => {
            form.null_ratio = e.target.checked ? DEFAULT_PERCENT : 0;
            renderNull(); emit(); schedulePreview();
          },
        })),
        formRow('百分比', pctInput),
      ];
      if (notNull) {
        common.push(formRow('', h('span', { class: 'muted' }, '数据库约束:NOT NULL,不允许 NULL 值')));
      }
      // 数据库唯一约束优先于「该生成器隐藏设置唯一」的裁剪规则：
      // 约束是硬性的，隐藏会让用户失去知情权（即使核心 unique_adjuster 会兜底）。
      const dbUniq = dbUnique();
      if (!NO_UNIQUE_GENS.has(form.generator) || dbUniq) {
        common.push(formRow('设置唯一', h('input', {
          type: 'checkbox',
          checked: dbUniq || !!form.unique,
          disabled: dbUniq,
          onchange: (e) => { form.unique = e.target.checked; emit(); schedulePreview(); },
        })));
        if (dbUniq) {
          common.push(formRow('', h('span', { class: 'muted' }, '数据库约束:UNIQUE,必须唯一')));
        }
      }
      el.append(h('div', { class: 'genform-section' }, ...common));
    }

    // ⑥ 重置属性（参考工具：面板底部独立按钮）
    el.append(h('div', { class: 'genform-section' },
      h('button', { class: 'small', onclick: reset }, '重置属性'),
    ));
  }

  function renderForeignKey(preview) {
    const refs = foreignKeys();
    const selfRef = refs.some((fk) => fk.ref_table === current.table);
    el.append(
      formRow('引用列', h('span', { class: 'mono' },
        refs.map((fk) => `${fk.ref_table}.${fk.ref_column}`).join('、'))),
      h('div', { class: 'msg warn', style: 'margin:8px 0' },
        '该列是外键，非空值从引用列中选取，不能切换为普通生成器。'
        + (selfRef ? '这是同一张表内的自引用关系。' : '生成数据时需先准备被引用表中的记录。')),
    );
    const out = h('div', { class: 'genform-preview' });
    previewBox = out;
    el.append(h('div', { class: 'genform-section' },
      formRow('预览', h('div', { class: 'row genform-inline' },
        out, h('button', { class: 'small', onclick: () => doPreview(out) }, '刷新')))));
    if (preview) doPreview(out);
    if (!dbNotNull()) {
      const pct = h('input', {
        type: 'number', class: 'num-input', min: 0, max: 100,
        value: form.null_ratio > 0 ? form.null_ratio : '',
        placeholder: '0', disabled: form.null_ratio <= 0,
        oninput: (e) => {
          form.null_ratio = e.target.value === '' ? 0 : +e.target.value;
          emit(); schedulePreview();
        },
      });
      el.append(h('div', { class: 'genform-section' },
        formRow('包含 NULL 值', h('input', {
          type: 'checkbox', checked: form.null_ratio > 0,
          onchange: (e) => {
            form.null_ratio = e.target.checked ? DEFAULT_PERCENT : 0;
            pct.value = form.null_ratio > 0 ? form.null_ratio : '';
            pct.disabled = form.null_ratio <= 0;
            emit(); schedulePreview();
          },
        })),
        formRow('百分比', pct),
        h('div', { class: 'muted' }, selfRef
          ? '首次向空表生成数据时，会先留空再建立表内关联，最终空值比例受初始化过程影响。'
          : '引用列没有可用值时，可空外键会先生成 NULL；填充被引用表后才能建立关联。')));
    } else {
      el.append(h('div', { class: 'genform-section muted' },
        '数据库约束：NOT NULL，不允许空值；引用列必须有可用记录。'));
    }
    el.append(h('div', { class: 'genform-section' },
      h('button', { class: 'small', onclick: reset }, '重置属性')));
  }

  /** NULL 勾选框联动：未勾选时百分比输入框禁用（参考工具 同款行为）。 */
  function renderNull() {
    if (nullPctInput) nullPctInput.disabled = dbNotNull() || form.null_ratio <= 0;
  }

  /**
   * 参数别名归一：核心存在「同一参数的多种写法」，面板只保留主键——
   * - pattern：pattern || regex 是别名 → 值搬到 pattern，删 regex
   * - weighted_choice：choices（对象列表/字符串数组）与 weighted_choices（值:权重
   *   字典）表达同一件事 → 搬到 weighted_choices（字符串数组按等权 1 处理）
   * 只在加载时做；提交只发主键。核心继续接受旧写法（手写 YAML 向后兼容）。
   */
  function normalizeAliasParams() {
    const p = form.params;
    if (form.generator === 'pattern') {
      if (!p.pattern && p.regex) p.pattern = p.regex;
      delete p.regex;
    }
    if (form.generator === 'weighted_choice' && !p.weighted_choices) {
      if (Array.isArray(p.choices) && p.choices.length) {
        const obj = {};
        for (const c of p.choices) {
          if (c && typeof c === 'object') obj[c.value] = c.weight ?? 1;
          else obj[c] = 1; // 等权字符串
        }
        p.weighted_choices = obj;
      }
      delete p.choices;
    }
  }

  /** 日期边界只在未提供任何边界时补默认值，保留 AI 给出的单边设置。 */
  function applyDateDefaults() {
    if (!DATE_DEFAULT_GENS.has(form.generator)) return;
    const p = form.params;
    const hasAny = p.start_date || p.end_date || p.start_year !== undefined || p.end_year !== undefined;
    if (hasAny) return;
    p.start_date = '2000-01-01';
    p.end_date = `${new Date().getFullYear()}-12-31`;
  }

  /**
   * 该列是否为显式 AUTOINCREMENT 主键——值由数据库生成，sqlseed 跳过。
   * 判定用 colInfo 而非 inferred.generator_name：核心的 `skip` 还用于
   * 「可空无默认值」「计算列」「隐式 INTEGER PK」等场景，而只有显式
   * AUTOINCREMENT 主键是用户配置**无法覆盖**的（mapper L1a 优先级最高）。
   */
  function isDbGenerated() {
    return !!(current?.colInfo?.is_primary_key && current?.colInfo?.is_autoincrement);
  }

  function renderParams() {
    if (!paramsHolder) return;
    clear(paramsHolder);
    const paramNames = meta.params?.[form.generator] || [];
    if (!paramNames.length) {
      paramsHolder.append(formRow('', h('span', { class: 'muted' }, '该生成器无可配置参数')));
      return;
    }
    // bytes（图像或二进制）双模式：参考工具 同款「图像生成器 / 从文件夹随机选择」
    // 单选二选一，未选侧的参数行变暗禁用（仍保留已填值，但发送前会被剥掉）。
    if (form.generator === 'bytes') {
      paramsHolder.append(bytesModeRow());
      // 两组参数都渲染，未选侧变暗禁用（参考工具 同款二选一联动）。
      for (const m of ['image', 'folder']) {
        for (const p of BYTES_MODE_PARAMS[m]) {
          paramsHolder.append(bytesParamRow(p, m));
        }
      }
      return;
    }
    // 按 参考工具 面板顺序排列；未列入 PARAM_ORDER 的参数保持签名原始顺序。
    const hidden = HIDDEN_PARAMS[form.generator];
    const ordered = [...paramNames].filter((p) => !hidden?.has(p)).sort((a, b) => {
      const ia = PARAM_ORDER.indexOf(a);
      const ib = PARAM_ORDER.indexOf(b);
      if (ia === -1 && ib === -1) return 0;
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
    for (const p of ordered) {
      paramsHolder.append(formRow(paramLabel(p), paramInput(p)));
    }
  }

  // bytes 双模式参数分组（顺序即 参考工具 面板顺序）。
  const BYTES_MODE_PARAMS = {
    image: ['width', 'height', 'image_format'],
    folder: ['folder', 'extensions'],
  };
  const BYTES_MODE_LABELS = [
    { value: 'image', label: '图像生成器' },
    { value: 'folder', label: '从文件夹随机选择' },
  ];

  /** bytes 当前模式：显式选择优先，未选过时回退到参数推导（folder 非空 → folder，
   *  与核心 _gen_bytes 的 folder 优先判定一致）。 */
  function bytesMode() {
    return bytesModeState || (form.params.folder ? 'folder' : 'image');
  }

  function switchBytesMode(mode) {
    if (mode === bytesMode()) return;
    bytesModeState = mode;
    if (mode === 'image') {
      delete form.params.folder;
      delete form.params.extensions;
    } else {
      delete form.params.width;
      delete form.params.height;
      delete form.params.image_format;
    }
    render(false);
    emit();
    schedulePreview();
  }

  function bytesModeRow() {
    const mode = bytesMode();
    const radios = h('div', { class: 'genform-radios' });
    for (const m of BYTES_MODE_LABELS) {
      radios.append(h('label', { class: 'genform-check' },
        h('input', {
          type: 'radio', name: 'genform-bytes-mode', checked: mode === m.value,
          onchange: () => switchBytesMode(m.value),
        }), m.label));
    }
    return formRow('模式', radios);
  }

  /** 渲染一行 bytes 参数；非当前模式的组加 .off（变暗 + 输入禁用）。 */
  function bytesParamRow(name, groupMode) {
    const row = formRow(paramLabel(name), paramInput(name));
    if (groupMode !== bytesMode()) {
      row.classList.add('off');
      for (const node of row.querySelectorAll('input, button, textarea')) {
        node.disabled = true;
      }
    }
    return row;
  }

  /** 「一整天」勾选后禁用时间输入框（参考工具 同款联动）。 */
  function syncTimeInputs() {
    const off = form.params.all_day !== false;
    for (const node of el.querySelectorAll('[data-time-param]')) node.disabled = off;
  }

  // ---- 数据库硬约束（schema 明确规定的 NOT NULL / UNIQUE）----
  // 这两类约束用户在 UI 上配反了必然 IntegrityError，所以直接锁定控件：
  // NOT NULL → NULL% 强制 0；数据库唯一 → 设置唯一强制开。

  /** 该列是否被数据库约束为 NOT NULL（含主键）。 */
  function dbNotNull() {
    return !!current?.colInfo && current.colInfo.nullable === false;
  }

  /** 该列是否被数据库约束为唯一（主键 / 单列唯一索引）。 */
  function dbUnique() {
    if (current?.colInfo?.is_primary_key) return true;
    const cols = uniqueColsOf(current?.table);
    return !!(cols && cols.has && current?.col && cols.has(current.col));
  }


  function paramInput(name) {
    const val = form.params[name] ?? '';
    const commit = (v) => { form.params[name] = v; emit(); schedulePreview(); };
    if (name === 'schema') {
      const error = h('div', { class: 'msg err', role: 'alert', hidden: true });
      const input = h('textarea', {
        class: 'grow', rows: '5', spellcheck: 'false',
        placeholder: PARAM_PLACEHOLDERS.schema,
        oninput: (e) => {
          let parsed;
          try {
            const text = e.target.value.trim();
            if (text) {
              parsed = JSON.parse(text);
              if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
                throw new Error('JSON schema must be an object');
              }
            }
          } catch {
            const detail = '请输入有效的 JSON 对象；留空使用默认结构。';
            paramErrors.set(name, detail);
            error.textContent = detail;
            error.hidden = false;
            input.setAttribute('aria-invalid', 'true');
            if (previewTimer) clearTimeout(previewTimer);
            previewTimer = null;
            return;
          }
          paramErrors.delete(name);
          error.textContent = '';
          error.hidden = true;
          input.removeAttribute('aria-invalid');
          commit(parsed);
        },
      }, typeof val === 'string' ? val : JSON.stringify(val, null, 2));
      return h('div', { class: 'genform-field-col' }, input, error);
    }
    if (name === 'choices' || name === 'weighted_choices') {
      // 参考工具 式：每行一个值；加权枚举支持每行「值:权重」。
      let text;
      if (Array.isArray(val)) {
        text = val.join('\n');
      } else if (val && typeof val === 'object') {
        text = Object.entries(val).map(([k, w]) => `${k}:${w}`).join('\n');
      } else {
        text = typeof val === 'string' ? val : '';
      }
      return h('textarea', {
        class: 'grow', rows: '4', spellcheck: 'false',
        placeholder: name === 'choices' ? '每行一个值，如:\nengineer\nmanager' : '每行一个「值:权重」，如:\nactive:80\nsuspended:15',
        oninput: (e) => {
          const lines = e.target.value.split('\n').map((s) => s.trim()).filter(Boolean);
          if (name === 'choices') {
            commit(lines);
          } else {
            const obj = {};
            for (const line of lines) {
              const idx = line.lastIndexOf(':');
              if (idx > 0) obj[line.slice(0, idx)] = Number(line.slice(idx + 1)) || 0;
              else obj[line] = 1;
            }
            commit(obj);
          }
        },
      }, text);
    }
    // 正则 / 模板：多行文本编辑区。
    if (TEXTAREA_PARAMS.has(name)) {
      return h('textarea', {
        class: 'grow', rows: name === 'template' ? '2' : '3', spellcheck: 'false',
        placeholder: PARAM_PLACEHOLDERS[name] || '',
        oninput: (e) => commit(e.target.value),
      }, String(val ?? ''));
    }
    // 日期 / 时间 / 星期：参考工具 日期、时间、日期时间三件套面板。
    if (name === 'start_date' || name === 'end_date') {
      return h('input', {
        type: 'date', class: 'grow', value: val || '',
        oninput: (e) => commit(e.target.value),
      });
    }
    if (name === 'start_time' || name === 'end_time') {
      return h('input', {
        type: 'time', class: 'grow', value: val || '', step: 1, // step=1 让秒可选
        'data-time-param': name,
        disabled: form.params.all_day !== false, // 「一整天」勾选时不参与
        oninput: (e) => commit(e.target.value),
      });
    }
    if (name === 'all_day') {
      return h('input', {
        type: 'checkbox',
        checked: form.params.all_day !== false, // 参考工具 默认勾选「一整天」
        onchange: (e) => { commit(e.target.checked); syncTimeInputs(); },
      });
    }
    if (name === 'weekdays') {
      return weekdayControl(commit);
    }
    if (NUMERIC_PARAMS.has(name)) {
      const attrs = {
        type: 'number', class: 'num-input', value: val,
        placeholder: PARAM_PLACEHOLDERS[name] || '',
        oninput: (e) => commit(e.target.value === '' ? undefined : +e.target.value),
      };
      // 年份加合法区间（datetime.year 必须落在 1–9999）。没有边界时很容易
      // 敲出 1396 这类荒谬年份——值本身合法，生成结果却完全跑偏。
      if (name === 'start_year' || name === 'end_year') {
        attrs.min = 1;
        attrs.max = 9999;
      }
      return h('input', attrs);
    }
    if (name === 'extensions') {
      // 逗号分隔列表（如 png,jpg），发送前解析为数组
      return h('input', {
        class: 'grow', value: Array.isArray(val) ? val.join(',') : (val || ''),
        placeholder: PARAM_PLACEHOLDERS.extensions,
        oninput: (e) => commit(e.target.value.split(',').map((s) => s.trim()).filter(Boolean)),
      });
    }
    if (name === 'image_format') {
      return track(createDropdown({
        value: val || 'png',
        options: IMAGE_FORMATS,
        width: '240px',
        onChange: (v) => commit(v),
      })).el;
    }
    if (name === 'folder') {
      // 目录走服务端浏览（浏览器不暴露绝对路径）——选完直接回填并触发预览。
      const input = h('input', {
        class: 'grow', value: val || '',
        placeholder: PARAM_PLACEHOLDERS.folder,
        oninput: (e) => commit(e.target.value),
      });
      return h('div', { class: 'genform-field' },
        input,
        h('button', {
          class: 'small',
          onclick: () => openFilePicker({
            mode: 'dir',
            startPath: val || undefined,
            onPick: (p) => { input.value = p; commit(p); },
          }),
        }, '选择文件夹'),
      );
    }
    return h('input', {
      class: 'grow', value: val, placeholder: PARAM_PLACEHOLDERS[name] || '',
      oninput: (e) => commit(e.target.value),
    });
  }

  /**
   * 星期控件：全部 / 工作日 / 自定义（参考工具 三选一），选「自定义」时展开周几勾选组。
   * 值形态：'all' | 'workdays' | [0…6]（Monday=0，与核心 normalize_weekdays 一致）。
   */
  function weekdayControl(commit) {
    const val = form.params.weekdays;
    const mode = val === 'workdays' ? 'workdays' : (Array.isArray(val) ? 'custom' : 'all');
    const radios = h('div', { class: 'genform-radios' });
    const box = h('div', { class: 'genform-weekdays' });
    for (const m of WEEKDAY_MODES) {
      radios.append(h('label', { class: 'genform-check' },
        h('input', {
          type: 'radio', name: 'genform-weekday-mode', checked: mode === m.value,
          onchange: () => {
            commit(m.value === 'custom' ? [] : m.value);
            box.style.display = m.value === 'custom' ? 'flex' : 'none';
          },
        }), m.label));
    }
    const days = new Set(Array.isArray(val) ? val : []);
    for (let i = 0; i < 7; i++) {
      box.append(h('label', { class: 'genform-check' },
        h('input', {
          type: 'checkbox', checked: days.has(i),
          onchange: (e) => {
            const next = new Set(Array.isArray(form.params.weekdays) ? form.params.weekdays : []);
            if (e.target.checked) next.add(i); else next.delete(i);
            commit([...next].sort((x, y) => x - y));
          },
        }), WEEKDAY_LABELS[i]));
    }
    box.style.display = mode === 'custom' ? 'flex' : 'none';
    return h('div', { class: 'genform-field-col' }, radios, box);
  }

  function formRow(labelText, control) {
    return h('div', { class: 'genform-row' },
      h('label', { class: 'genform-label' }, labelText ? `${labelText}:` : ''),
      control,
    );
  }

  /** 该生成器缺哪个必填参数（无必填返回 null）。 */
  function missingRequired() {
    const req = REQUIRED_PARAMS[form.generator];
    if (!req) return null;
    const missing = req.filter((k) => {
      const v = form.params[k];
      if (Array.isArray(v)) return v.length === 0;
      if (v && typeof v === 'object') return Object.keys(v).length === 0;
      return v === undefined || v === null || v === '';
    });
    return missing.length ? missing : null;
  }

  async function doPreview(out) {
    if (!current) return;
    if (paramErrors.size) {
      clear(out);
      out.append(msg('请先修正参数中的 JSON 格式错误。'));
      return;
    }
    const missing = missingRequired();
    if (missing) {
      // 空参请求注定失败（如 choice 缺候选值），提示待填而不是闪一条报错。
      clear(out);
      out.append(h('span', { class: 'muted' }, `待填写：${missing.map(paramLabel).join('、')}`));
      return;
    }
    clear(out);
    out.append(h('span', { class: 'muted' }, '…'));
    try {
      // 预览必须带 NULL/唯一，否则勾选后预览永远显示不出空值（实测发现）。
      const cfg = buildCfg();
      const res = await post(`/api/connections/${connId}/preview`, {
        table: current.table, count: 3, columns: { [current.col]: cfg },
      });
      clear(out);
      const vals = res.rows.map((r) => r[current.col]);
      out.append(h('span', { class: 'genform-preview-val' }, vals.map(String).join('、') || '（空）'));
    } catch (e) {
      clear(out);
      out.append(msg(`预览失败：${e.message}`));
    }
  }

  /** 源列与派生列都回到零配置基线，丢弃导入或手动编辑后的设置。 */
  function reset() {
    if (!current) return;
    bytesModeState = null;
    form = fromInferred(current.zeroConfig ?? current.inferred);
    normalizeAliasParams();
    applyDateDefaults();
    render();
    emit();
  }

  function fromInferred(spec) {
    // 保留面板未提供编辑器的 ColumnConfig 字段，参数编辑不应重写这些设置。
    const options = {};
    for (const key of ['provider', 'faker_method', 'mimesis_method', 'native_params']) {
      if (spec?.[key] !== undefined && spec[key] !== null) options[key] = spec[key];
    }
    const common = {
      options,
      constraints: { ...(spec?.constraints || {}) },
      // 核心为 0–1，UI 为 0–100；保留小数，避免未编辑比例时发生精度损失。
      null_ratio: (spec?.null_ratio || 0) * 100,
      unique: !!spec?.constraints?.unique,
    };
    if (foreignKeys().length && !isDbGenerated()) {
      const params = {};
      if (['random', 'coverage'].includes(spec?.params?.strategy)) params.strategy = spec.params.strategy;
      return { ...common, options: {}, generator: 'foreign_key_or_integer', params };
    }
    // 派生列（AI 常为 shipped_at 一类配 derive_from）必须原样保留：ColumnConfig
    // 的 derived 模式与 generator 互斥，退化成 generator 会静默改写 AI 配置，
    // 且该列一旦参与跨列 CHECK 就因类型不匹配而预览失败。
    if (spec && spec.derive_from) {
      return {
        ...common,
        generator: '',
        derived: spec.derive_from,
        expression: spec.expression || '',
        params: {},
      };
    }
    if (!spec || spec.generator_name === 'skip' || spec.generator_name === 'foreign_key'
      || spec.generator_name === 'foreign_key_or_integer' || spec.generator_name === '__enrich__') {
      return { ...common, generator: 'string', params: {} };
    }
    return {
      ...common,
      generator: spec.generator_name || spec.generator || 'string',
      params: { ...(spec.params || {}) },
    };
  }

  return {
    el,
    /** 选中一列：inferred 为当前配置，zeroConfig 为零配置推断的 GeneratorSpec。 */
    setColumn(table, col, colInfo, inferred, zeroConfig) {
      // zeroConfig 是该列的零配置推断结果，作为「重置属性」的回落基线
      // （inferred 可能已被 AI/加载的配置覆盖）。
      current = { table, col, colInfo, inferred, zeroConfig };
      bytesModeState = null;
      form = fromInferred(inferred);
      normalizeAliasParams();
      applyDateDefaults();
      render();
    },
  };
}
