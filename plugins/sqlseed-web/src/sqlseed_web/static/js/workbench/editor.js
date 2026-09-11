// Workbench column rules. Local drafts remain editable when validation fails;
// only complete input shapes are emitted. The server checks generator semantics.
import {h} from '../api.js';
import {createDropdown} from '../dropdown.js';
import {genLabel, paramLabel, genGuide} from '../labels.js';
import {createDatePicker} from './date-picker.js';

const copy = value => structuredClone(value);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function normalizeRule(value, name) {
  const rule = copy(value || {});
  rule.name = name;
  if (rule.generator === undefined && rule.generator_name !== undefined) rule.generator = rule.generator_name;
  if (rule.faker_method === undefined && rule.native_faker_method !== undefined) rule.faker_method = rule.native_faker_method;
  if (rule.mimesis_method === undefined && rule.native_mimesis_method !== undefined) rule.mimesis_method = rule.native_mimesis_method;
  delete rule.generator_name;
  delete rule.native_faker_method;
  delete rule.native_mimesis_method;
  // GeneratorSpec uses None for an absent native override; ColumnConfig's
  // native_params is a dictionary and cannot accept that serialized null.
  if (rule.native_params === null) delete rule.native_params;
  return rule;
}

function withoutNative(rule) {
  delete rule.faker_method;
  delete rule.mimesis_method;
  delete rule.native_params;
}

// This is a catalogue filter, not database validation. Unknown/union outputs
// remain available, and the user can inspect the complete provider catalogue.
function compatibleOutput(column, entry) {
  const output = entry.output_type;
  if (!output || output === 'json' || output === 'null') return true;
  const type = String(column.type || '').toUpperCase();
  if (/JSON/.test(type)) return true;
  if (/BLOB|BINARY|BYTEA/.test(type)) return output === 'bytes';
  if (/BOOL/.test(type)) return output === 'boolean';
  if (/INT/.test(type)) return ['integer', 'boolean'].includes(output);
  if (/NUMERIC|DECIMAL|FLOAT|DOUBLE|REAL|MONEY/.test(type)) return ['integer', 'number', 'boolean'].includes(output);
  if (/TIMESTAMP|DATETIME/.test(type)) return ['datetime', 'string'].includes(output);
  if (/DATE/.test(type)) return ['date', 'datetime', 'string'].includes(output);
  if (/TIME/.test(type)) return ['time', 'string'].includes(output);
  if (/CHAR|TEXT|CLOB|UUID|ENUM/.test(type)) return ['string', 'date', 'datetime', 'time'].includes(output);
  return true;
}

/** Create one column editor; callers retain it while onValidity reports an error. */
export function createRuleEditor({table, column, rule, baseline, catalog, draft, onChange, onValidity}) {
  const el = h('div', {class: 'rule-editor wb-rule-editor'});
  const base = normalizeRule(baseline, column.name);
  const entries = new Map((catalog.entries || []).map(entry => [entry.id, entry]));
  const foreignKeys = (table.foreign_keys || []).filter(key => key.columns.includes(column.name));
  const readonly = Boolean(column.is_computed || (column.is_primary_key && column.is_autoincrement));
  const uniqueBySchema = (table.primary_key?.length === 1 && table.primary_key[0] === column.name)
    || (table.unique_constraints || []).some(key => key.columns.length === 1 && key.columns[0] === column.name);
  const hasDefault = column.default !== undefined && column.default !== null;
  const canSkip = column.default !== undefined && column.default !== null || column.nullable || column.is_rowid_alias;
  let current = normalizeRule(draft?.current ?? draft?.config ?? rule ?? baseline, column.name);
  let mode = !foreignKeys.length && ['source', 'derived', 'skip'].includes(draft?.mode) ? draft.mode : modeOf(current);
  let lastValid = copy(draft?.config ?? null);
  let restoredValues = copy(draft?.invalidValues || {});
  let disposed = false;
  let dropdowns = [];
  const datePickers = new Map();
  const dateTextDrafts = new Set();
  let summary;
  let constraintsInput;
  let uniqueInput;
  const errors = new Map();
  const modeDrafts = new Map();

  function modeOf(value) {
    if (foreignKeys.length) return 'foreign_key';
    if (value.derive_from || value.expression) return 'derived';
    return value.generator === 'skip' && canSkip ? 'skip' : 'source';
  }

  function recommendationScore(entry) {
    const name = column.name.toLowerCase(), type = String(column.type || '').toUpperCase();
    const scalar = /BLOB|BINARY|BYTEA/.test(type) ? 'bytes' : /JSON/.test(type) ? 'json' : /BOOL/.test(type) ? 'boolean'
      : /INT/.test(type) ? 'integer' : /REAL|FLOAT|NUMERIC|DECIMAL|DOUBLE|MONEY/.test(type) ? 'float'
      : /DATETIME|TIMESTAMP/.test(type) ? 'datetime' : /DATE/.test(type) ? 'date' : /TIME/.test(type) ? 'time' : 'string';
    const semantic = /(^|_)(sku|code|no|number)$/.test(name) ? 'template'
      : /(^|_)(status|category|product_name)$/.test(name) ? 'choice'
      : /email/.test(name) ? 'email' : /phone|mobile/.test(name) ? 'phone'
      : /city/.test(name) ? 'city' : /(^|_)(price|amount|rate)$/.test(name) ? 'float'
      : /(^|_)(quantity|stock|age|count)$/.test(name) ? 'integer' : null;
    return (compatibleOutput(column, entry) ? 100 : 0) + (entry.id === semantic ? 40 : 0)
      + (entry.id === base.generator ? 20 : 0) + (entry.id === current.generator ? 10 : 0) + (entry.id === scalar ? 8 : 0);
  }
  function recommendedEntries() {
    return [...entries.values()].filter(entry => compatibleOutput(column, entry))
      .sort((left, right) => recommendationScore(right) - recommendationScore(left));
  }
  function skipLabel() {
    if (column.is_rowid_alias) return '数据库自动分配 ID';
    return hasDefault ? '使用数据库默认值' : '使用 NULL（空值）';
  }
  function skipDescription() {
    if (column.is_rowid_alias || column.is_autoincrement) return 'ID 由数据库根据现有数据和序列状态分配。追加生成不会重新从 1 开始，也不会重置或覆盖已有主键。';
    if (hasDefault) return `本列不提供生成值，数据库使用已定义的默认值：${String(column.default)}。可切换为生成器来自定义内容。`;
    return '此列没有数据库默认值，省略后写入 NULL（空值）。需要真实内容时，请切换为生成器。';
  }

  function applyMode() {
    if (mode === 'derived') {
      delete current.generator;
      delete current.params;
      withoutNative(current);
    } else {
      delete current.derive_from;
      delete current.expression;
      if (mode === 'foreign_key') {
        current.generator = 'foreign_key_or_integer';
        current.params = ['random', 'coverage'].includes(current.params?.strategy)
          ? {strategy: current.params.strategy} : {};
        withoutNative(current);
      } else if (mode === 'skip') {
        current.generator = 'skip';
        current.params = {};
        withoutNative(current);
      } else {
        if (!current.generator || current.generator === 'skip') current.generator = entries.has(base.generator) ? base.generator : recommendedEntries()[0]?.id || '';
        current.params ||= {};
      }
    }
    if (!column.nullable) delete current.null_ratio;
    if (uniqueBySchema) current.constraints = {...current.constraints, unique: true};
  }

  function report() {
    const message = errors.values().next().value || null;
    if (!message) lastValid = copy(current);
    if (summary) summary.textContent = message || '';
    if (!disposed) onValidity?.(message);
    return message;
  }

  function emit() {
    if (disposed) return;
    applyMode();
    if (!report()) onChange?.(copy(current));
  }

  function mark(field, control, message) {
    if (message) {
      errors.set(field, message);
      control.setAttribute('aria-invalid', 'true');
    } else {
      errors.delete(field);
      control.removeAttribute('aria-invalid');
    }
  }

  function row(label, control, hint) {
    const caption = h('span', {class: 'editor-control-label'}, label);
    const wrapper = h('div', {class: 'control wb-editor-row'});
    if (['INPUT', 'TEXTAREA'].includes(control.tagName)) {
      wrapper.append(h('label', {}, caption, control));
    } else {
      // Composite controls already contain their own labels. Wrapping them in
      // another label would make clicking one weekday activate another input.
      control.setAttribute('role', 'group');
      control.setAttribute('aria-label', label);
      control.querySelector('.dropdown-btn')?.setAttribute('aria-label',label);
      wrapper.append(caption, control);
    }
    if (hint) wrapper.append(h('small', {class: 'editor-note muted'}, hint));
    return wrapper;
  }

  function dropdown(field, value, options, change) {
    const control = createDropdown({value, options, onChange: change});
    control.el.setAttribute('data-field', field);
    dropdowns.push(control);
    return control.el;
  }

  function textControl(field, value, validate, apply, {multiline = false, numeric = false, placeholder = '', type, disabled = false} = {}) {
    const control = h(multiline ? 'textarea' : 'input', {
      'data-field': field, disabled, value: Object.hasOwn(restoredValues, field) ? restoredValues[field] : value ?? '', placeholder,
      ...(multiline ? {rows: '4', spellcheck: 'false'} : {type: type || (numeric ? 'number' : 'text')}),
    });
    delete restoredValues[field];
    const check = commit => {
      try {
        const parsed = validate(control.value);
        mark(field, control, null);
        if (commit) apply(parsed);
      } catch (error) {
        mark(field, control, error.message);
      }
      if (commit) emit();
    };
    control.addEventListener('input', () => check(true));
    check(false);
    return control;
  }

  function parseParam(parameter, raw) {
    const label = paramLabel(parameter.name);
    if (!raw.trim()) {
      if (parameter.required) throw new Error(`${label} 为必填参数。`);
      return undefined;
    }
    if (parameter.type === 'integer' || parameter.type === 'number') {
      const value = Number(raw);
      if (!Number.isFinite(value) || parameter.type === 'integer' && !Number.isInteger(value)) {
        throw new Error(`${label} 必须是${parameter.type === 'integer' ? '整数' : '有效数字'}。`);
      }
      return value;
    }
    if (['object', 'array', 'json'].includes(parameter.type)) {
      let value;
      try { value = JSON.parse(raw); } catch { throw new Error(`${label} 需要有效 JSON。`); }
      if (parameter.type === 'object' && !isObject(value)) throw new Error(`${label} 需要 JSON 对象。`);
      if (parameter.type === 'array' && !Array.isArray(value)) throw new Error(`${label} 需要 JSON 数组。`);
      return value;
    }
    return raw;
  }

  function dateDefault(name) {
    if (name === 'start_date') return `${String(current.params.start_year ?? 2000).padStart(4, '0')}-01-01`;
    if (name === 'end_date') return `${String(current.params.end_year ?? new Date().getFullYear()).padStart(4, '0')}-12-31`;
    return name === 'start_time' ? '00:00:00' : '23:59:59';
  }
  function calendarControl(parameter) {
    const name = parameter.name, isTime = name.endsWith('_time');
    const raw = current.params[name] ?? dateDefault(name);
    if (!isTime) {
      let ready = false;
      if (Object.hasOwn(restoredValues, name)) dateTextDrafts.add(name);
      const picker = createDatePicker({label: paramLabel(name),
        value: Object.hasOwn(restoredValues, name) ? restoredValues[name] : String(raw),
        onValidity: (message, input) => {mark(name, input, message); if (ready) report();},
        onChange: value => {
          dateTextDrafts.delete(name);
          if (value === undefined) delete current.params[name]; else current.params[name] = value;
          emit();
        }});
      picker.input.setAttribute('data-field', name);
      picker.input.addEventListener('input', () => dateTextDrafts.add(name));
      delete restoredValues[name];
      datePickers.set(name, picker);
      ready = true;
      return picker.el;
    }
    const valid = value => {
      if (!value.trim()) return undefined;
      if (!/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value)) throw new Error('时间格式应为 HH:MM 或 HH:MM:SS。');
      return value;
    };
    // Keep invalid imported time text visible instead of erasing it.
    let malformed = false;
    try { valid(String(raw)); } catch { malformed = true; }
    const input = textControl(name, String(raw), valid, value => {
      if (value === undefined) delete current.params[name]; else current.params[name] = value;
    }, {type: malformed ? 'text' : 'time', placeholder: 'HH:MM:SS', disabled: current.params.all_day ?? true});
    input.setAttribute('step', '1');
    return input;
  }
  function weekdayControl() {
    const value = current.params.weekdays ?? 'all';
    let custom = Array.isArray(value) ? [...value] : value === 'workdays' ? [0, 1, 2, 3, 4] : value === 'weekend' ? [5, 6] : [0, 1, 2, 3, 4, 5, 6];
    let selectedMode = Array.isArray(value) ? 'custom' : ['all', 'workdays', 'weekend'].includes(value) ? value : 'raw';
    const wrap = h('div', {class: 'wb-weekday-control'}), days = h('div', {class: 'wb-weekday-options'});
    const renderDays = () => {
      days.hidden = selectedMode !== 'custom';
      days.replaceChildren(...['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((label, day) =>
        h('label', {}, h('input', {type: 'checkbox', 'data-field': `weekday-${day}`, checked: custom.includes(day), onchange: event => {
          custom = custom.filter(item => item !== day); if (event.target.checked) custom.push(day); custom.sort();
          if (!custom.length) errors.set('weekdays', '自定义星期至少选择一天。');
          else { errors.delete('weekdays'); current.params.weekdays = [...custom]; }
          emit();
        }}), label)));
    };
    const choices = [{value: 'all', label: '每天'}, {value: 'workdays', label: '工作日（周一至周五）'}, {value: 'weekend', label: '周末'}, {value: 'custom', label: '自定义星期'}];
    if (selectedMode === 'raw') choices.push({value: 'raw', label: `已导入：${String(value)}`});
    wrap.append(dropdown('weekdays', selectedMode, choices, next => {
      selectedMode = next; errors.delete('weekdays');
      if (next === 'workdays') custom = [0, 1, 2, 3, 4];
      if (next === 'weekend') custom = [5, 6];
      if (next === 'all') custom = [0, 1, 2, 3, 4, 5, 6];
      if (next === 'custom') current.params.weekdays = [...custom]; else current.params.weekdays = next;
      renderDays(); emit();
    }), days); renderDays();
    return wrap;
  }
  function charsetControl() {
    const aliases = {alphanum: 'alphanumeric', letters_digits: 'alphanumeric', ascii_letters_digits: 'alphanumeric', letters: 'alpha', ascii_letters: 'alpha', numeric: 'digits', numbers: 'digits'};
    const value = current.params.charset;
    let mode = value == null ? 'default' : aliases[value] || (['alphanumeric', 'alpha', 'digits'].includes(value) ? value : 'custom');
    const custom = textControl('charset', mode === 'custom' ? value : '', raw => {
      if (mode === 'custom' && !raw) throw new Error('请至少填写一个允许出现的字符。');
      return raw;
    }, raw => { if (mode === 'custom') current.params.charset = raw; }, {placeholder: '例如 ABCDEF0123456789 或 甲乙丙丁'});
    custom.setAttribute('aria-label', '自定义字符集');
    custom.hidden = mode !== 'custom';
    return h('div', {}, dropdown('charset-preset', mode, [
      {value: 'default', label: '默认：字母、数字、空格、下划线、连字符'},
      {value: 'alphanumeric', label: '字母和数字（A–Z / a–z / 0–9）'},
      {value: 'alpha', label: '仅英文字母'}, {value: 'digits', label: '仅数字'}, {value: 'custom', label: '自定义字符'},
    ], next => {
      mode = next; errors.delete('charset'); custom.removeAttribute('aria-invalid'); custom.hidden = next !== 'custom';
      if (next === 'default') delete current.params.charset;
      else if (next === 'custom') {
        if (!custom.value) custom.value = 'ABCDEF0123456789';
        current.params.charset = custom.value;
      } else current.params.charset = next;
      emit();
    }), custom);
  }
  function parameterHint(parameter) {
    const hints = {
      start_date: '格式 YYYY-MM-DD；显示当前生效边界。留空沿用年份范围。', end_date: '格式 YYYY-MM-DD；包含结束日期。',
      start_time: '格式 HH:MM:SS；取消“一整天”后生效。', end_time: '格式 HH:MM:SS；包含结束时间。',
      all_day: '勾选后可生成 00:00:00–23:59:59 内的时间；取消勾选可指定开始和结束时间。',
      weekdays: '按星期限制日期；工作日指周一至周五，不排除法定节假日。',
      charset: '候选字符决定结果中允许出现的字符，不是 UTF-8 等编码名称。',
      choices: '填写 JSON 数组，例如 ["pending", "paid", "shipped"]；数值可写 [1, 2, 3]。',
      weighted_choices: '填写值和权重组成的 JSON 对象，例如 {"普通": 80, "VIP": 20}。',
      template: '例如 SKU-{sequence:04d}；sequence 表示序号，04d 表示补齐 4 位。',
      sequence_start: '本次生成从此序号开始；不会读取或重置数据库 ID。',
      pattern: '例如 [A-Z]{3}[0-9]{4}；按此正则生成匹配的字符串。', regex: '正则表达式，例如 [A-Z]{3}[0-9]{4}。',
      mask: '例如 1##########；# 用随机数字替换。',
      schema: 'JSON Schema 对象，例如 {"type":"object","properties":{"active":{"type":"boolean"}}}。',
    };
    return hints[parameter.name] || (parameter.required ? '必填参数。' : parameter.default == null ? '可选；留空由生成器决定。' : `留空使用默认值：${String(parameter.default)}。`);
  }

  function parameterControl(parameter) {
    const value = current.params[parameter.name];
    if (['start_date', 'end_date', 'start_time', 'end_time'].includes(parameter.name)) return calendarControl(parameter);
    if (parameter.name === 'weekdays') return weekdayControl();
    if (parameter.name === 'charset') return charsetControl();
    const write = parsed => {
      if (parsed === undefined) delete current.params[parameter.name];
      else current.params[parameter.name] = parsed;
      if (['start_year', 'end_year'].includes(parameter.name)) {
        const dateField = parameter.name.replace('_year', '_date');
        const input = el.querySelector(`[data-field="${dateField}"]`);
        if (input && current.params[dateField] == null && !dateTextDrafts.has(dateField)) datePickers.get(dateField)?.setValue(dateDefault(dateField));
      }
    };
    if (parameter.choices?.length) {
      return dropdown(parameter.name, JSON.stringify(value ?? parameter.default),
        parameter.choices.map(choice => ({value: JSON.stringify(choice), label: String(choice)})),
        selected => { write(JSON.parse(selected)); emit(); });
    }
    if (parameter.type === 'boolean') {
      return h('input', {
        type: 'checkbox', 'data-field': parameter.name, checked: value ?? parameter.default ?? false,
        onchange: event => {
          write(event.target.checked);
          if (parameter.name === 'all_day') for (const name of ['start_time', 'end_time']) {
            const input = el.querySelector(`[data-field="${name}"]`); if (input) input.disabled = event.target.checked;
          }
          emit();
        },
      });
    }
    const json = ['object', 'array', 'json'].includes(parameter.type);
    const raw = value === undefined || value === null ? '' : json ? JSON.stringify(value, null, 2) : String(value);
    const defaultHint = parameter.required ? '请填写必填参数' : parameter.default == null ? '留空使用生成器默认值' : `默认：${JSON.stringify(parameter.default)}`;
    return textControl(parameter.name, raw, text => parseParam(parameter, text), write, {
      multiline: json, numeric: ['integer', 'number'].includes(parameter.type), placeholder: defaultHint,
    });
  }

  function renderSource() {
    const entry = entries.get(current.generator);
    const labelFor = item => genLabel(item.id) === item.id ? item.label || item.id : genLabel(item.id);
    const chooser = h('div', {class: 'generator-chooser', 'data-field': 'generator'});
    const options = h('div', {class: 'generator-options', role: 'group', 'aria-label': '可用生成器'});
    const search = h('input', {type: 'search', 'data-field': 'generator-search', placeholder: '查找生成器', 'aria-label': '查找生成器', autocomplete: 'off'});
    const all = h('input', {type: 'checkbox', 'data-field': 'generator-show-all'});
    let composing = false, pickerOpen = false;
    const renderOptions = () => {
      if (disposed) return;
      const query = search.value.trim().toLocaleLowerCase();
      const available = [...entries.values()].filter(item =>
        (all.checked || item.id === current.generator || compatibleOutput(column, item)) &&
        `${labelFor(item)} ${item.id} ${genGuide(item.id).purpose}`.toLocaleLowerCase().includes(query))
        .sort((left, right) => recommendationScore(right) - recommendationScore(left));
      options.replaceChildren(...available.map(item => h('button', {
        type: 'button', 'data-generator': item.id, 'aria-pressed': String(item.id === current.generator),
        onclick: () => {
          if (disposed) return;
          preserveSharedInvalid();
          current.generator = item.id;
          current.params = {};
          withoutNative(current);
          render();
          emit();
        },
      }, h('span', {}, labelFor(item)), h('small', {}, item.id),
      h('span', {class: 'wb-generator-purpose'}, genGuide(item.id).purpose),
      genGuide(item.id).example ? h('small', {class: 'wb-generator-example'}, `示例：${genGuide(item.id).example}`) : null)));
      if (!available.length) options.append(h('p', {class: 'editor-note'}, '没有匹配的生成器。'));
    };
    search.oncompositionstart = () => { composing = true; };
    search.oncompositionend = () => { composing = false; renderOptions(); };
    search.oninput = event => { if (!composing && !event.isComposing) renderOptions(); };
    all.onchange = renderOptions;
    const picker = h('div', {class: 'generator-picker', hidden: true}, search,
      h('label', {class: 'generator-all'}, all, '显示全部生成器'), options,
      h('p', {class: 'editor-note'}, '按字段类型推荐；完整兼容性与约束由检查配置验证。'));
    const toggle = h('button', {type: 'button', class: 'btn small', 'data-generator-toggle': '', 'aria-expanded': 'false',
      onclick: () => {
        pickerOpen = !pickerOpen;
        picker.hidden = !pickerOpen;
        toggle.setAttribute('aria-expanded', String(pickerOpen));
        if (pickerOpen) { renderOptions(); search.focus(); }
      }}, entry ? labelFor(entry) : '选择生成器', h('small', {}, '更换'));
    chooser.append(h('div', {class: 'generator-heading'}, h('span', {}, '生成器'), toggle), picker);
    el.append(chooser);
    if (!entry) {
      errors.set('generator', `生成器 ${current.generator || '（未指定）'} 不在当前可用列表中。`);
      return;
    }
    const guide = genGuide(entry.id);
    el.append(h('div', {class: 'wb-generator-guide'}, h('p', {class: 'editor-note wb-editor-description'}, guide.purpose),
      guide.example ? h('small', {class: 'wb-generator-example'}, `格式示例：${guide.example}。实际样例由当前引擎和规则生成。`) : null));
    const params = h('div', {class: 'rule-parameters wb-editor-params'});
    const years = [];
    if (entry.params.some(parameter => parameter.name === 'start_date')) {
      params.append(h('div', {class: 'wb-param-presets'}, h('span', {}, '日期范围'),
        h('button', {type: 'button', class: 'btn small', 'data-date-preset': 'this-year', onclick: () => {
          const year = new Date().getFullYear(); current.params.start_date = `${year}-01-01`; current.params.end_date = `${year}-12-31`;
          delete current.params.start_year; delete current.params.end_year; preserveDatePresetInvalid(); render(); emit();
        }}, '本年'),
        h('button', {type: 'button', class: 'btn small', 'data-date-preset': 'today', onclick: () => {
          const now = new Date(); const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
          current.params.start_date = day; current.params.end_date = day; delete current.params.start_year; delete current.params.end_year;
          preserveDatePresetInvalid(); render(); emit();
        }}, '今天')));
    }
    for (const parameter of entry.params) {
      if (['start_year', 'end_year'].includes(parameter.name)) { years.push(parameter); continue; }
      params.append(row(paramLabel(parameter.name) + (parameter.required ? ' *' : ''), parameterControl(parameter), parameterHint(parameter)));
    }
    if (years.length) {
      const legacy = h('details', {class: 'wb-editor-year-fallback'}, h('summary', {}, '年份兼容设置'),
        h('p', {class: 'editor-note'}, '仅在对应日期留空时生效；已导入的年份配置会保留。'));
      for (const parameter of years) legacy.append(row(paramLabel(parameter.name), parameterControl(parameter), parameterHint(parameter)));
      params.append(legacy);
    }
    if (!entry.params.length) params.append(h('p', {class: 'muted'}, '此生成器没有可配置参数。'));
    el.append(params);
  }

  function renderDerived() {
    const source = Array.isArray(current.derive_from) ? current.derive_from.join(', ') : current.derive_from || '';
    const names = new Set(table.columns.map(item => item.name));
    el.append(row('来源字段', textControl('derive_from', source, raw => {
      const selected = raw.split(',').map(name => name.trim()).filter(Boolean);
      if (!selected.length) throw new Error('派生列需要至少一个来源字段。');
      const missing = selected.find(name => !names.has(name));
      if (missing) throw new Error(`来源字段 ${missing} 不存在。`);
      if (selected.includes(column.name)) throw new Error('派生列不能引用自身。');
      return selected.length === 1 && !Array.isArray(current.derive_from) ? selected[0] : selected;
    }, parsed => { current.derive_from = parsed; }), '多个字段以英文逗号分隔。'));
    el.append(row('派生表达式', textControl('expression', current.expression || '', raw => {
      if (!raw.trim()) throw new Error('请填写派生表达式。');
      return raw;
    }, parsed => { current.expression = parsed; }, {multiline: true}),
    '表达式可用 value 或 row["字段名"]；完整语法由检查配置验证。'));
  }

  function renderForeignKey() {
    for (const key of foreignKeys) {
      const source = `${key.ref_schema ? key.ref_schema + '.' : ''}${key.ref_table} (${key.ref_columns.join(', ')})`;
      el.append(h('p', {class: 'drawer-help wb-editor-fk'}, `引用来源：${source}`));
      if (key.columns.length > 1) el.append(h('p', {class: 'muted'},
        `复合外键 (${key.columns.join(', ')}) 作为同一组引用，由数据库关系规则共同处理。`));
      if (key.ref_table === table.name && column.nullable) el.append(h('p', {class: 'muted'}, '此列为自引用；空表初始化时 NULL 比例可能受引用顺序影响。'));
    }
    el.append(row('采样方式', dropdown('strategy', current.params.strategy || 'random', [
      {value: 'random', label: '随机采样'}, {value: 'coverage', label: '覆盖父表值'},
    ], selected => { current.params.strategy = selected; emit(); })));
  }

  function renderNullOptions() {
    // Nullability belongs to the database schema. Field information already
    // exposes NOT NULL; there is no editable NULL option for those columns.
    if (!column.nullable) {
      delete restoredValues.null_ratio;
      return;
    }
    const ratio = h('input', {type: 'number', 'data-field': 'null_ratio', min: '0', max: '100', step: 'any',
      value: String((current.null_ratio || 0) * 100), disabled: !current.null_ratio});
    const percentageRow = row('NULL 百分比', ratio);
    percentageRow.hidden = ratio.disabled;
    const nullable = h('input', {type: 'checkbox', 'data-field': 'nullable',
      checked: Boolean(current.null_ratio),
      onchange: event => {
        ratio.disabled = !event.target.checked;
        percentageRow.hidden = ratio.disabled;
        if (event.target.checked) {
          current.null_ratio = current.null_ratio || 0.05;
          ratio.value = String(current.null_ratio * 100);
        } else delete current.null_ratio;
        mark('null_ratio', ratio, null);
        emit();
      }});
    const checkRatio = commit => {
      const value = Number(ratio.value);
      if (!ratio.value.trim() || !Number.isFinite(value) || value < 0 || value > 100) {
        mark('null_ratio', ratio, 'NULL 百分比必须在 0 到 100 之间。');
      } else {
        mark('null_ratio', ratio, null);
        if (commit) current.null_ratio = value / 100;
      }
      if (commit) emit();
    };
    ratio.addEventListener('input', () => checkRatio(true));
    if (Object.hasOwn(restoredValues, 'null_ratio')) {
      ratio.value = restoredValues.null_ratio;
      checkRatio(false);
    }
    delete restoredValues.null_ratio;
    if (current.null_ratio !== undefined &&
        (!Number.isFinite(current.null_ratio) || current.null_ratio < 0 || current.null_ratio > 1)) {
      mark('null_ratio', ratio, 'NULL 百分比必须在 0 到 100 之间。');
    }
    // A reopened invalid draft must stay reachable, including one whose last
    // valid percentage was zero. Hiding it would leave Apply blocked forever.
    if (errors.has('null_ratio')) {
      nullable.checked = true;
      ratio.disabled = false;
      percentageRow.hidden = false;
    }
    el.append(row('包含 NULL 值', nullable), percentageRow);
  }

  function renderCommon() {
    renderNullOptions();
    if (mode !== 'foreign_key') {
      uniqueInput = h('input', {type: 'checkbox', 'data-field': 'unique',
        checked: Boolean(uniqueBySchema || current.constraints?.unique), disabled: Boolean(uniqueBySchema),
        onchange: event => {
          current.constraints = {...current.constraints, unique: Boolean(uniqueBySchema || event.target.checked)};
          if (constraintsInput && !errors.has('constraints')) constraintsInput.value = JSON.stringify(current.constraints, null, 2);
          emit();
        }});
      el.append(row('设置唯一', uniqueInput, uniqueBySchema ? '数据库单列唯一约束已锁定。' : '复合主键或复合唯一约束不表示本列单独唯一。'));
    }
  }

  function renderAdvanced() {
    const advanced = h('details', {class: 'column-constraints wb-editor-advanced'}, h('summary', {}, '高级配置（通常无需调整）'),
      h('p', {class: 'editor-note'}, '普通生成规则继承全局数据生成引擎与语言。这里保留原生方法、额外约束和导入的高级参数；请在应用后检查配置。'));
    const objectField = (field, label, value, update) => {
      const parameter = {name: label, type: 'object', required: false};
      const input = textControl(field, value == null ? '' : JSON.stringify(value, null, 2),
        raw => parseParam(parameter, raw), update, {multiline: true, placeholder: 'JSON 对象；留空使用默认值'});
      advanced.append(row(label, input));
      return input;
    };
    constraintsInput = objectField('constraints', '约束', current.constraints, value => {
      if (value === undefined) delete current.constraints;
      else current.constraints = value;
      if (uniqueBySchema) current.constraints = {...current.constraints, unique: true};
      if (uniqueInput) uniqueInput.checked = Boolean(current.constraints?.unique);
    });
    if (mode === 'source') {
      for (const [field, label] of [['provider', '字段生成引擎'], ['faker_method', 'Faker 原生方法'], ['mimesis_method', 'Mimesis 原生方法']]) {
        advanced.append(row(label, textControl(field, current[field] || '', raw => raw.trim() || undefined, value => {
          if (value === undefined) delete current[field];
          else current[field] = value;
        }, {placeholder: field === 'provider' ? '留空继承全局，或填写与全局相同的引擎' : field === 'faker_method' ? '例如 email、random_int' : '例如 person.full_name、numeric.integer'}),
        field === 'provider' ? '当前仅支持继承全局或填写与全局相同的引擎；其他值会保留，但检查会阻止生成。' : '原生方法会优先于普通生成器执行，请按对应引擎的方法签名填写。'));
      }
      objectField('native_params', '原生方法参数', current.native_params, value => {
        if (value === undefined) delete current.native_params;
        else current.native_params = value;
      });
    }
    el.append(advanced);
  }

  function preserveDatePresetInvalid() {
    for (const field of errors.keys()) {
      if (['start_date', 'end_date', 'start_year', 'end_year'].includes(field)) continue;
      const input = [...el.querySelectorAll('[data-field]')].find(control => control.getAttribute('data-field') === field);
      if (input && ['INPUT', 'TEXTAREA'].includes(input.tagName)) restoredValues[field] = input.value;
    }
  }

  function preserveSharedInvalid() {
    for (const field of ['constraints', 'null_ratio', 'provider']) {
      if (!errors.has(field)) continue;
      const input = [...el.querySelectorAll('[data-field]')].find(control => control.getAttribute('data-field') === field);
      if (input && ['INPUT', 'TEXTAREA'].includes(input.tagName)) restoredValues[field] = input.value;
    }
  }

  function render() {
    dropdowns.forEach(control => control.destroy());
    dropdowns = [];
    datePickers.forEach(control => control.destroy());
    datePickers.clear();
    dateTextDrafts.clear();
    errors.clear();
    constraintsInput = null;
    uniqueInput = null;
    applyMode();
    el.replaceChildren(h('div', {class: 'rule-heading wb-editor-heading'}, h('strong', {class: 'mono'}, column.name), h('span', {class: 'muted'}, column.type || '')));
    summary = h('p', {class: 'editor-error wb-editor-error', role: 'alert'});
    el.append(summary);
    if (readonly) {
      el.append(h('p', {class: 'muted'}, column.is_computed ? '数据库计算列，由数据库自动计算，规则只读。' : '数据库自增主键，规则只读。' + skipDescription()));
      report();
      return;
    }
    if (mode !== 'foreign_key') {
      const modes = [{value: 'source', label: '生成器'}, {value: 'derived', label: '派生表达式'}];
      if (canSkip) modes.push({value: 'skip', label: skipLabel()});
      el.append(row('生成方式', dropdown('mode', mode, modes, next => {
        preserveSharedInvalid();
        modeDrafts.set(mode, copy(current));
        const previous = current;
        current = copy(modeDrafts.get(next) || current);
        // Shared options follow the latest edit when returning to another mode.
        for (const key of ['constraints', 'null_ratio', 'provider']) {
          if (previous[key] === undefined) delete current[key]; else current[key] = copy(previous[key]);
        }
        mode = next;
        render();
        emit();
      })));
    }
    if (mode === 'source') renderSource();
    else if (mode === 'derived') renderDerived();
    else if (mode === 'foreign_key') renderForeignKey();
    else el.append(h('p', {class: 'drawer-help wb-editor-default'}, skipDescription()));
    if (mode !== 'skip') renderCommon();
    renderAdvanced();
    restoredValues = {};
    el.append(h('button', {type: 'button', class: 'btn small editor-reset wb-editor-reset', onclick: () => {
      current = copy(base);
      mode = modeOf(current);
      modeDrafts.clear();
      restoredValues = {};
      render();
      if (!report()) onChange?.(null);
    }}, '重置为推断规则'));
    report();
  }

  render();
  return {el, getDraft() {
    const invalidValues = {};
    for (const field of errors.keys()) {
      const input = [...el.querySelectorAll('[data-field]')].find(control => control.getAttribute('data-field') === field);
      if (input && ['INPUT', 'TEXTAREA'].includes(input.tagName)) invalidValues[field] = input.value;
    }
    return {config: copy(lastValid), current: copy(current), mode, invalidValues};
  }, destroy() {
    disposed = true;
    dropdowns.forEach(control => control.destroy());
    dropdowns = [];
    datePickers.forEach(control => control.destroy());
    datePickers.clear();
    dateTextDrafts.clear();
  }};
}
