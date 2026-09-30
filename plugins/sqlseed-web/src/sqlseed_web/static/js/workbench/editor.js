import { tr, joinText, setText, setAttr, UserFacingError, errorText, serverText } from '../i18n.js';
import '../i18n/messages/editor.js';
// Workbench column rules. Local drafts remain editable when validation fails;
// only complete input shapes are emitted. The server checks generator semantics.
import { h } from '../api.js';
import { createDropdown } from '../dropdown.js';
import { genLabel, paramLabel, genGuide } from '../labels.js';
import { createDatePicker } from './date-picker.js';
const copy = value => structuredClone(value);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const validTimeInput = value => {
  if (!value.trim()) {
    return undefined;
  }
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value)) {
    throw new UserFacingError(tr('editor.timeError'));
  }
  return value;
};

const labelFor = item => genLabel(item.id) === item.id ? serverText(item, 'label') || item.id : genLabel(item.id);
let editorSequence = 0;
function normalizeRule(value, name) {
  const rule = copy(value || {});
  rule.name = name;
  if (rule.generator === undefined && rule.generator_name !== undefined) {
    rule.generator = rule.generator_name;
  }
  if (rule.faker_method === undefined && rule.native_faker_method !== undefined) {
    rule.faker_method = rule.native_faker_method;
  }
  if (rule.mimesis_method === undefined && rule.native_mimesis_method !== undefined) {
    rule.mimesis_method = rule.native_mimesis_method;
  }
  delete rule.generator_name;
  delete rule.native_faker_method;
  delete rule.native_mimesis_method;
  // GeneratorSpec uses None for an absent native override; ColumnConfig's
  // native_params is a dictionary and cannot accept that serialized null.
  if (rule.native_params === null) {
    delete rule.native_params;
  }
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
  if (!output || output === 'json' || output === 'null') {
    return true;
  }
  const type = String(column.type || '').toUpperCase();
  if (/JSON/.test(type)) {
    return true;
  }
  if (/BLOB|BINARY|BYTEA/.test(type)) {
    return output === 'bytes';
  }
  if (/BOOL/.test(type)) {
    return output === 'boolean';
  }
  if (/INT/.test(type)) {
    return ['integer', 'boolean'].includes(output);
  }
  if (/NUMERIC|DECIMAL|FLOAT|DOUBLE|REAL|MONEY/.test(type)) {
    return ['integer', 'number', 'boolean'].includes(output);
  }
  if (/TIMESTAMP|DATETIME/.test(type)) {
    return ['datetime', 'string'].includes(output);
  }
  if (/DATE/.test(type)) {
    return ['date', 'datetime', 'string'].includes(output);
  }
  if (/TIME/.test(type)) {
    return ['time', 'string'].includes(output);
  }
  if (/CHAR|TEXT|CLOB|UUID|ENUM/.test(type)) {
    return ['string', 'date', 'datetime', 'time'].includes(output);
  }
  return true;
}

/** Create one column editor; callers retain it while onValidity reports an error. */
export function createRuleEditor({
  table,
  column,
  rule,
  baseline,
  catalog,
  draft,
  onChange,
  onValidity
}) {
  const el = h('div', {
    class: 'rule-editor wb-rule-editor'
  });
  const base = normalizeRule(baseline, column.name);
  const entries = new Map((catalog.entries || []).map(entry => [entry.id, entry]));
  const foreignKeys = (table.foreign_keys || []).filter(key => key.columns.includes(column.name));
  const readonly = Boolean(column.is_computed || column.is_primary_key && column.is_autoincrement);
  const uniqueBySchema = table.primary_key?.length === 1 && table.primary_key[0] === column.name || (table.unique_constraints || []).some(key => key.columns.length === 1 && key.columns[0] === column.name);
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
  const rangeErrors = new Map();
  const errorId = `wb-rule-error-${++editorSequence}`;
  const modeDrafts = new Map();
  function modeOf(value) {
    if (foreignKeys.length) {
      return 'foreign_key';
    }
    if (value.derive_from || value.expression) {
      return 'derived';
    }
    return value.generator === 'skip' && canSkip ? 'skip' : 'source';
  }
  function recommendationScore(entry) {
    const name = column.name.toLowerCase(),
      type = String(column.type || '').toUpperCase();
    const scalar = scalarGenerator();
    const semantic = semanticGenerator();
    return (compatibleOutput(column, entry) ? 100 : 0) + (entry.id === semantic ? 40 : 0) + (entry.id === base.generator ? 20 : 0) + (entry.id === current.generator ? 10 : 0) + (entry.id === scalar ? 8 : 0);
    function scalarGenerator() {
      let scalar;
      if (/BLOB|BINARY|BYTEA/.test(type)) {
        scalar = 'bytes';
      } else if (/JSON/.test(type)) {
        scalar = 'json';
      } else if (/BOOL/.test(type)) {
        scalar = 'boolean';
      } else if (/INT/.test(type)) {
        scalar = 'integer';
      } else if (/REAL|FLOAT|NUMERIC|DECIMAL|DOUBLE|MONEY/.test(type)) {
        scalar = 'float';
      } else if (/DATETIME|TIMESTAMP/.test(type)) {
        scalar = 'datetime';
      } else if (/DATE/.test(type)) {
        scalar = 'date';
      } else if (/TIME/.test(type)) {
        scalar = 'time';
      } else {
        scalar = 'string';
      }
      return scalar;
    }
    function semanticGenerator() {
      let semantic;
      if (/(^|_)(sku|code|no|number)$/.test(name)) {
        semantic = 'template';
      } else if (/(^|_)(status|category|product_name)$/.test(name)) {
        semantic = 'choice';
      } else if (/email/.test(name)) {
        semantic = 'email';
      } else if (/phone|mobile/.test(name)) {
        semantic = 'phone';
      } else if (/city/.test(name)) {
        semantic = 'city';
      } else if (/(^|_)(price|amount|rate)$/.test(name)) {
        semantic = 'float';
      } else if (/(^|_)(quantity|stock|age|count)$/.test(name)) {
        semantic = 'integer';
      } else {
        semantic = null;
      }
      return semantic;
    }
  }
  function recommendedEntries() {
    return [...entries.values()].filter(entry => compatibleOutput(column, entry)).sort((left, right) => recommendationScore(right) - recommendationScore(left));
  }
  function skipLabel() {
    if (column.is_rowid_alias) {
      return tr('editor.idAllocated');
    }
    return hasDefault ? tr('editor.defaultMode') : tr('editor.nullMode');
  }
  function skipDescription() {
    if (column.is_rowid_alias || column.is_autoincrement) {
      return tr('editor.idHelp');
    }
    if (hasDefault) {
      return tr('editor.defaultHelp', {value: String(column.default)});
    }
    return tr('editor.nullHelp');
  }
  function applyDerivedMode() {
    delete current.generator;
    delete current.params;
    withoutNative(current);
  }
  function applyMode() {
    if (mode === 'derived') {
      applyDerivedMode();
    } else {
      applyGeneratedMode();
    }
    if (!column.nullable) {
      delete current.null_ratio;
    }
    if (uniqueBySchema) {
      current.constraints = {
        ...current.constraints,
        unique: true
      };
    }
    function applyGeneratedMode() {
      delete current.derive_from;
      delete current.expression;
      if (mode === 'foreign_key') {
        current.generator = 'foreign_key_or_integer';
        current.params = ['random', 'coverage'].includes(current.params?.strategy) ? {
          strategy: current.params.strategy
        } : {};
        withoutNative(current);
      } else if (mode === 'skip') {
        current.generator = 'skip';
        current.params = {};
        withoutNative(current);
      } else {
        if (!current.generator || current.generator === 'skip') {
          current.generator = entries.has(base.generator) ? base.generator : recommendedEntries()[0]?.id || '';
        }
        current.params ||= {};
      }
    }
  }
  function report() {
    validateRanges();
    const message = errors.values().next().value || rangeErrors.values().next().value || null;
    if (!message) {
      lastValid = copy(current);
    }
    if (summary) {
      setText(summary, message || '');
    }
    if (!disposed) {
      onValidity?.(message);
    }
    return message;
  }
  function validateRanges() {
    const controls = new Map([...el.querySelectorAll('input[data-field]')].map(input => [input.dataset.field, input]));
    clearRangeErrors(controls);
    if (mode !== 'source' || current.faker_method || current.mimesis_method) return;
    const parameters = new Map((entries.get(current.generator)?.params || []).map(parameter => [parameter.name, parameter]));
    const value = name => current.params[name] ?? parameters.get(name)?.default;
    for (const [low, high] of [['min_value','max_value'], ['min_length','max_length'], ['start_time','end_time']]) {
      if (![low, high].every(name => parameters.has(name) && controls.has(name) && !errors.has(name))) continue;
      if (!rangeReversed(low, high, value)) continue;
      const message = tr('editor.rangeError', {minimum: paramLabel(low), maximum: paramLabel(high)});
      for (const name of [low, high]) {
        rangeErrors.set(name, message);
        setAttr(controls.get(name), 'aria-invalid', 'true');
        setAttr(controls.get(name), 'aria-describedby', errorId);
      }
    }
  }
  function clearRangeErrors(controls) {
    for (const field of rangeErrors.keys()) {
      const input = controls.get(field);
      if (input && !errors.has(field)) input.removeAttribute('aria-invalid');
      if (input?.getAttribute('aria-describedby') === errorId) input.removeAttribute('aria-describedby');
    }
    rangeErrors.clear();
  }
  function rangeReversed(low, high, value) {
    const time = low === 'start_time';
    if (time && value('all_day')) return false;
    const seconds = text => {
      const parts = String(text).split(':').map(Number);
      return parts[0] * 3600 + parts[1] * 60 + (parts[2] || 0);
    };
    const start = time ? seconds(value(low) ?? dateDefault(low)) : value(low);
    const end = time ? seconds(value(high) ?? dateDefault(high)) : value(high);
    return Number.isFinite(start) && Number.isFinite(end) && start > end;
  }
  function emit() {
    if (disposed) {
      return;
    }
    applyMode();
    if (!report()) {
      onChange?.(copy(current));
    }
  }
  function mark(field, control, message) {
    if (message) {
      errors.set(field, message);
      setAttr(control, 'aria-invalid', 'true');
    } else {
      errors.delete(field);
      control.removeAttribute('aria-invalid');
    }
  }
  function row(label, control, hint) {
    const caption = h('span', {
      class: 'editor-control-label'
    }, label);
    const wrapper = h('div', {
      class: 'control wb-editor-row'
    });
    if (['INPUT', 'TEXTAREA'].includes(control.tagName)) {
      wrapper.append(h('label', {}, caption, control));
    } else {
      // Composite controls already contain their own labels. Wrapping them in
      // another label would make clicking one weekday activate another input.
      setAttr(control, 'role', 'group');
      setAttr(control, 'aria-label', label);
      setAttr(control.querySelector('.dropdown-btn'), 'aria-label', label);
      wrapper.append(caption, control);
    }
    if (hint) {
      wrapper.append(h('small', {
        class: 'editor-note muted'
      }, hint));
    }
    return wrapper;
  }
  function dropdown(field, value, options, change) {
    const control = createDropdown({
      value,
      options,
      onChange: change
    });
    control.el.dataset.field = field;
    dropdowns.push(control);
    return control.el;
  }
  function textControl(field, value, validate, apply, {
    type = 'text',
    ...options
  } = {}) {
    return validatedControl('input', field, value, validate, apply, {
      type,
      ...options
    });
  }
  function multilineControl(field, value, validate, apply, options = {}) {
    return validatedControl('textarea', field, value, validate, apply, {
      class: 'wb-code',
      rows: '4',
      spellcheck: 'false',
      ...options
    });
  }
  function validatedControl(tagName, field, value, validate, apply, {
    disabled = false,
    placeholder = '',
    ...attributes
  } = {}) {
    const control = h(tagName, {
      'data-field': field,
      disabled,
      value: Object.hasOwn(restoredValues, field) ? restoredValues[field] : value ?? '',
      placeholder,
      ...attributes
    });
    delete restoredValues[field];
    const check = commit => {
      try {
        const parsed = validate(control.value);
        mark(field, control, null);
        if (commit) {
          apply(parsed);
        }
      } catch (error) {
        mark(field, control, errorText(error));
      }
      if (commit) {
        emit();
      }
    };
    control.addEventListener('input', () => check(true));
    check(false);
    return control;
  }
  function parseParam(parameter, raw) {
    const label = paramLabel(parameter.name);
    if (!raw.trim()) {
      if (parameter.required) {
        throw new UserFacingError(tr('editor.required', {label}));
      }
      return undefined;
    }
    if (parameter.type === 'integer' || parameter.type === 'number') {
      const value = Number(raw);
      if (!Number.isFinite(value) || parameter.type === 'integer' && !Number.isInteger(value)) {
        throw new UserFacingError(tr('editor.numberError', {label, type: parameter.type === 'integer' ? tr('editor.integer') : tr('editor.number')}));
      }
      return value;
    }
    if (['object', 'array', 'json'].includes(parameter.type)) {
      return parseJsonParameter();
    }
    return raw;
    function parseJsonParameter() {
      let value;
      try {
        value = JSON.parse(raw);
      } catch {
        throw new UserFacingError(tr('editor.jsonError', {label}));
      }
      if (parameter.type === 'object' && !isObject(value)) {
        throw new UserFacingError(tr('editor.objectError', {label}));
      }
      if (parameter.type === 'array' && !Array.isArray(value)) {
        throw new UserFacingError(tr('editor.arrayError', {label}));
      }
      return value;
    }
  }
  function dateDefault(name) {
    if (name === 'start_date') {
      return `${String(current.params.start_year ?? 2000).padStart(4, '0')}-01-01`;
    }
    if (name === 'end_date') {
      return `${String(current.params.end_year ?? new Date().getFullYear()).padStart(4, '0')}-12-31`;
    }
    return name === 'start_time' ? '00:00:00' : '23:59:59';
  }
  function calendarControl(parameter) {
    const name = parameter.name,
      isTime = name.endsWith('_time');
    const raw = current.params[name] ?? dateDefault(name);
    if (!isTime) {
      let ready = false;
      if (Object.hasOwn(restoredValues, name)) {
        dateTextDrafts.add(name);
      }
      const picker = createDatePicker({
        label: paramLabel(name),
        value: Object.hasOwn(restoredValues, name) ? restoredValues[name] : String(raw),
        onValidity: (message, input) => {
          mark(name, input, message);
          if (ready) {
            report();
          }
        },
        onChange: value => {
          dateTextDrafts.delete(name);
          if (value === undefined) {
            delete current.params[name];
          } else {
            current.params[name] = value;
          }
          emit();
        }
      });
      picker.input.dataset.field = name;
      picker.input.addEventListener('input', () => dateTextDrafts.add(name));
      delete restoredValues[name];
      datePickers.set(name, picker);
      ready = true;
      return picker.el;
    }
    // Keep invalid imported time text visible instead of erasing it.
    let malformed = false;
    try {
      validTimeInput(String(raw));
    } catch {
      malformed = true;
    }
    const input = textControl(name, String(raw), validTimeInput, value => {
      if (value === undefined) {
        delete current.params[name];
      } else {
        current.params[name] = value;
      }
    }, {
      type: malformed ? 'text' : 'time',
      placeholder: 'HH:MM:SS',
      disabled: current.params.all_day ?? true
    });
    setAttr(input, 'step', '1');
    return input;
  }
  function weekdayControl() {
    const value = current.params.weekdays ?? 'all';
    let custom;
    if (Array.isArray(value)) {
      custom = [...value];
    } else if (value === 'workdays') {
      custom = [0, 1, 2, 3, 4];
    } else if (value === 'weekend') {
      custom = [5, 6];
    } else {
      custom = [0, 1, 2, 3, 4, 5, 6];
    }
    let selectedMode;
    if (Array.isArray(value)) {
      selectedMode = 'custom';
    } else if (['all', 'workdays', 'weekend'].includes(value)) {
      selectedMode = value;
    } else {
      selectedMode = 'raw';
    }
    const wrap = h('div', {
        class: 'wb-weekday-control'
      }),
      days = h('div', {
        class: 'wb-weekday-options',
        role: 'group',
        'aria-label': tr('editor.weekdaysLabel')
      });
    const markDays = () => mark('weekdays', days,
      selectedMode === 'custom' && !custom.length ? tr('editor.weekdaysEmpty') : null);
    const updateDay = (day, checked) => {
      custom = custom.filter(item => item !== day);
      if (checked) {
        custom.push(day);
      }
      custom.sort((left, right) => left - right);
      if (custom.length) {
        current.params.weekdays = [...custom];
      }
      markDays();
      emit();
    };
    const renderDays = () => {
      days.hidden = selectedMode !== 'custom';
      days.replaceChildren(...[tr('editor.mon'), tr('editor.tue'), tr('editor.wed'), tr('editor.thu'), tr('editor.fri'), tr('editor.sat'), tr('editor.sun')].map((label, day) => h('label', {}, h('input', {
        type: 'checkbox',
        'data-field': `weekday-${day}`,
        checked: custom.includes(day),
        onchange: event => updateDay(day, event.target.checked)
      }), label)));
      markDays();
    };
    const choices = [{
      value: 'all',
      label: tr('editor.everyDay')
    }, {
      value: 'workdays',
      label: tr('editor.workdays')
    }, {
      value: 'weekend',
      label: tr('editor.weekends')
    }, {
      value: 'custom',
      label: tr('editor.customDays')
    }];
    if (selectedMode === 'raw') {
      choices.push({
        value: 'raw',
        label: tr('editor.imported', {value: String(value)})
      });
    }
    wrap.append(dropdown('weekdays', selectedMode, choices, next => {
      selectedMode = next;
      errors.delete('weekdays');
      if (next === 'workdays') {
        custom = [0, 1, 2, 3, 4];
      }
      if (next === 'weekend') {
        custom = [5, 6];
      }
      if (next === 'all') {
        custom = [0, 1, 2, 3, 4, 5, 6];
      }
      if (next === 'custom') {
        current.params.weekdays = [...custom];
      } else {
        current.params.weekdays = next;
      }
      renderDays();
      emit();
    }), days);
    renderDays();
    return wrap;
  }
  function charsetControl() {
    const aliases = {
      alphanum: 'alphanumeric',
      letters_digits: 'alphanumeric',
      ascii_letters_digits: 'alphanumeric',
      letters: 'alpha',
      ascii_letters: 'alpha',
      numeric: 'digits',
      numbers: 'digits'
    };
    const value = current.params.charset;
    let mode;
    if (value == null) {
      mode = 'default';
    } else {
      mode = aliases[value] || (['alphanumeric', 'alpha', 'digits'].includes(value) ? value : 'custom');
    }
    const custom = textControl('charset', mode === 'custom' ? value : '', raw => {
      if (mode === 'custom' && !raw) {
        throw new UserFacingError(tr('editor.charsetEmpty'));
      }
      return raw;
    }, raw => {
      if (mode === 'custom') {
        current.params.charset = raw;
      }
    }, {
      placeholder: tr('editor.charsetPlaceholder')
    });
    setAttr(custom, 'aria-label', tr('editor.customCharset'));
    custom.hidden = mode !== 'custom';
    return h('div', {}, dropdown('charset-preset', mode, [{
      value: 'default',
      label: tr('editor.charsetDefault')
    }, {
      value: 'alphanumeric',
      label: tr('editor.charsetAlphaNumeric')
    }, {
      value: 'alpha',
      label: tr('editor.charsetLetters')
    }, {
      value: 'digits',
      label: tr('editor.charsetDigits')
    }, {
      value: 'custom',
      label: tr('editor.charsetCustom')
    }], next => {
      mode = next;
      errors.delete('charset');
      custom.removeAttribute('aria-invalid');
      custom.hidden = next !== 'custom';
      if (next === 'default') {
        delete current.params.charset;
      } else if (next === 'custom') {
        if (!custom.value) {
          custom.value = 'ABCDEF0123456789';
        }
        current.params.charset = custom.value;
      } else {
        current.params.charset = next;
      }
      emit();
    }), custom);
  }
  function parameterControl(parameter) {
    const value = current.params[parameter.name];
    if (['start_date', 'end_date', 'start_time', 'end_time'].includes(parameter.name)) {
      return calendarControl(parameter);
    }
    if (parameter.name === 'weekdays') {
      return weekdayControl();
    }
    if (parameter.name === 'charset') {
      return charsetControl();
    }
    const write = parsed => {
      if (parsed === undefined) {
        delete current.params[parameter.name];
      } else {
        current.params[parameter.name] = parsed;
      }
      if (['start_year', 'end_year'].includes(parameter.name)) {
        const dateField = parameter.name.replace('_year', '_date');
        const input = el.querySelector(`[data-field="${dateField}"]`);
        if (input && current.params[dateField] == null && !dateTextDrafts.has(dateField)) {
          datePickers.get(dateField)?.setValue(dateDefault(dateField));
        }
      }
    };
    if (parameter.choices?.length) {
      return dropdown(parameter.name, JSON.stringify(value ?? parameter.default), parameter.choices.map(choice => ({
        value: JSON.stringify(choice),
        label: String(choice)
      })), selected => {
        write(JSON.parse(selected));
        emit();
      });
    }
    if (parameter.type === 'boolean') {
      return h('input', {
        type: 'checkbox',
        'data-field': parameter.name,
        checked: value ?? parameter.default ?? false,
        onchange: event => {
          write(event.target.checked);
          if (parameter.name === 'all_day') {
            for (const name of ['start_time', 'end_time']) {
              const input = el.querySelector(`[data-field="${name}"]`);
              if (input) {
                input.disabled = event.target.checked;
              }
            }
          }
          emit();
        }
      });
    }
    const json = ['object', 'array', 'json'].includes(parameter.type);
    let raw;
    if (value === undefined || value === null) {
      raw = '';
    } else if (json) {
      raw = JSON.stringify(value, null, 2);
    } else {
      raw = String(value);
    }
    let defaultHint;
    if (parameter.required) {
      defaultHint = tr('editor.requiredPlaceholder');
    } else if (parameter.default == null) {
      defaultHint = tr('editor.defaultPlaceholder');
    } else {
      defaultHint = tr('editor.defaultValue', {value: JSON.stringify(parameter.default)});
    }
    const createControl = json ? multilineControl : textControl;
    const options = {
      placeholder: defaultHint
    };
    if (!json) {
      options.type = ['integer', 'number'].includes(parameter.type) ? 'number' : 'text';
    }
    return createControl(parameter.name, raw, text => parseParam(parameter, text), write, options);
  }
  function renderSource() {
    const entry = entries.get(current.generator);
    const chooser = h('div', {
      class: 'generator-chooser',
      'data-field': 'generator'
    });
    const options = h('div', {
      class: 'generator-options',
      role: 'group',
      'aria-label': tr('editor.availableGenerators')
    });
    const search = h('input', {
      type: 'search',
      'data-field': 'generator-search',
      placeholder: tr('editor.searchGenerators'),
      'aria-label': tr('editor.searchGenerators'),
      autocomplete: 'off'
    });
    const all = h('input', {
      type: 'checkbox',
      'data-field': 'generator-show-all'
    });
    let composing = false,
      pickerOpen = false;
    const renderOptions = () => {
      if (disposed) {
        return;
      }
      const query = search.value.trim().toLocaleLowerCase();
      const available = [...entries.values()].filter(item => (all.checked || item.id === current.generator || compatibleOutput(column, item)) && `${labelFor(item)} ${item.id} ${genGuide(item.id).purpose}`.toLocaleLowerCase().includes(query)).sort((left, right) => recommendationScore(right) - recommendationScore(left));
      options.replaceChildren(...available.map(item => h('button', {
        type: 'button',
        'data-generator': item.id,
        'aria-pressed': String(item.id === current.generator),
        onclick: () => {
          if (disposed) {
            return;
          }
          preserveSharedInvalid();
          current.generator = item.id;
          current.params = {};
          withoutNative(current);
          render();
          emit();
        }
      }, h('span', {}, labelFor(item)), h('small', {}, item.id), h('span', {
        class: 'wb-generator-purpose'
      }, genGuide(item.id).purpose), genGuide(item.id).example ? h('small', {
        class: 'wb-generator-example'
      }, tr('editor.example', {example: genGuide(item.id).example})) : null)));
      if (!available.length) {
        options.append(h('p', {
          class: 'editor-note'
        }, tr('editor.noGenerators')));
      }
    };
    search.oncompositionstart = () => {
      composing = true;
    };
    search.oncompositionend = () => {
      composing = false;
      renderOptions();
    };
    search.oninput = event => {
      if (!composing && !event.isComposing) {
        renderOptions();
      }
    };
    all.onchange = renderOptions;
    const picker = h('div', {
      class: 'generator-picker',
      hidden: true
    }, search, h('label', {
      class: 'generator-all'
    }, all, tr('editor.showAll')), options, h('p', {
      class: 'editor-note'
    }, tr('editor.compatibilityHint')));
    const toggle = h('button', {
      type: 'button',
      class: 'btn small',
      'data-generator-toggle': '',
      'aria-expanded': 'false',
      onclick: () => {
        pickerOpen = !pickerOpen;
        picker.hidden = !pickerOpen;
        setAttr(toggle, 'aria-expanded', String(pickerOpen));
        if (pickerOpen) {
          renderOptions();
          search.focus();
        }
      }
    }, entry ? labelFor(entry) : tr('editor.chooseGenerator'), h('small', {}, tr('editor.change')));
    chooser.append(h('div', {
      class: 'generator-heading'
    }, h('span', {}, tr('editor.generator')), toggle), picker);
    el.append(chooser);
    if (!entry) {
      errors.set('generator', tr('editor.unavailableGenerator', {generator: current.generator || tr('editor.unspecified')}));
      return;
    }
    const guide = genGuide(entry.id);
    el.append(h('div', {
      class: 'wb-generator-guide'
    }, h('p', {
      class: 'editor-note wb-editor-description'
    }, guide.purpose), guide.example ? h('small', {
      class: 'wb-generator-example'
    }, tr('editor.formatExample', {example: guide.example})) : null));
    const params = h('div', {
      class: 'rule-parameters wb-editor-params'
    });
    const years = [];
    if (entry.params.some(parameter => parameter.name === 'start_date')) {
      params.append(h('div', {
        class: 'wb-param-presets'
      }, h('span', {}, tr('editor.dateRange')), h('button', {
        type: 'button',
        class: 'btn small',
        'data-date-preset': 'this-year',
        onclick: () => {
          const year = new Date().getFullYear();
          current.params.start_date = `${year}-01-01`;
          current.params.end_date = `${year}-12-31`;
          delete current.params.start_year;
          delete current.params.end_year;
          preserveDatePresetInvalid();
          render();
          emit();
        }
      }, tr('editor.thisYear')), h('button', {
        type: 'button',
        class: 'btn small',
        'data-date-preset': 'today',
        onclick: () => {
          const now = new Date();
          const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
          current.params.start_date = day;
          current.params.end_date = day;
          delete current.params.start_year;
          delete current.params.end_year;
          preserveDatePresetInvalid();
          render();
          emit();
        }
      }, tr('editor.today'))));
    }
    for (const parameter of entry.params) {
      if (['start_year', 'end_year'].includes(parameter.name)) {
        years.push(parameter);
        continue;
      }
      params.append(row(joinText([paramLabel(parameter.name), parameter.required ? ' *' : '']), parameterControl(parameter), parameterHint(parameter)));
    }
    if (years.length) {
      const legacy = h('details', {
        class: 'wb-editor-year-fallback'
      }, h('summary', {}, tr('editor.legacyYears')), h('p', {
        class: 'editor-note'
      }, tr('editor.legacyYearsHint')));
      for (const parameter of years) {
        legacy.append(row(paramLabel(parameter.name), parameterControl(parameter), parameterHint(parameter)));
      }
      params.append(legacy);
    }
    if (!entry.params.length) {
      params.append(h('p', {
        class: 'muted'
      }, tr('editor.noParams')));
    }
    el.append(params);
  }
  function renderDerived() {
    const source = Array.isArray(current.derive_from) ? current.derive_from.join(', ') : current.derive_from || '';
    const names = new Set(table.columns.map(item => item.name));
    el.append(row(tr('editor.sourceFields'), textControl('derive_from', source, raw => {
      const selected = raw.split(',').map(name => name.trim()).filter(Boolean);
      if (!selected.length) {
        throw new UserFacingError(tr('editor.sourceRequired'));
      }
      const missing = selected.find(name => !names.has(name));
      if (missing) {
        throw new UserFacingError(tr('editor.sourceMissing', {field: missing}));
      }
      if (selected.includes(column.name)) {
        throw new UserFacingError(tr('editor.sourceSelf'));
      }
      return selected.length === 1 && !Array.isArray(current.derive_from) ? selected[0] : selected;
    }, parsed => {
      current.derive_from = parsed;
    }), tr('editor.sourceHint')));
    el.append(row(tr('editor.expression'), multilineControl('expression', current.expression || '', raw => {
      if (!raw.trim()) {
        throw new UserFacingError(tr('editor.expressionRequired'));
      }
      return raw;
    }, parsed => {
      current.expression = parsed;
    }), tr('editor.expressionHint')));
  }
  function renderForeignKey() {
    for (const key of foreignKeys) {
      const source = `${key.ref_schema ? key.ref_schema + '.' : ''}${key.ref_table} (${key.ref_columns.join(', ')})`;
      el.append(h('p', {
        class: 'drawer-help wb-editor-fk'
      }, tr('editor.referenceSource', {source})));
      if (key.columns.length > 1) {
        el.append(h('p', {
          class: 'muted'
        }, tr('editor.compositeReference', {columns: key.columns.join(', ')})));
      }
      if (key.ref_table === table.name && column.nullable) {
        el.append(h('p', {
          class: 'muted'
        }, tr(key.columns.length === 1 ? 'editor.selfReference' : 'editor.compositeSelfReference')));
      }
    }
    el.append(row(tr('editor.sampling'), dropdown('strategy', current.params.strategy || 'random', [{
      value: 'random',
      label: tr('editor.random')
    }, {
      value: 'coverage',
      label: tr('editor.coverage')
    }], selected => {
      current.params.strategy = selected;
      emit();
    })));
  }
  function renderNullOptions() {
    // Nullability belongs to the database schema. Field information already
    // exposes NOT NULL; there is no editable NULL option for those columns.
    if (!column.nullable) {
      delete restoredValues.null_ratio;
      return;
    }
    const ratio = h('input', {
      type: 'number',
      'data-field': 'null_ratio',
      min: '0',
      max: '100',
      step: 'any',
      value: String((current.null_ratio || 0) * 100),
      disabled: !current.null_ratio
    });
    const percentageRow = row(tr('editor.nullPercent'), ratio, tr('editor.nullProbabilityHelp'));
    percentageRow.hidden = ratio.disabled;
    const nullable = h('input', {
      type: 'checkbox',
      'data-field': 'nullable',
      checked: Boolean(current.null_ratio),
      onchange: event => {
        ratio.disabled = !event.target.checked;
        percentageRow.hidden = ratio.disabled;
        if (event.target.checked) {
          current.null_ratio = current.null_ratio || 0.05;
          ratio.value = String(current.null_ratio * 100);
        } else {
          delete current.null_ratio;
        }
        mark('null_ratio', ratio, null);
        emit();
      }
    });
    const checkRatio = commit => {
      const value = Number(ratio.value);
      if (!ratio.value.trim() || !Number.isFinite(value) || value < 0 || value > 100) {
        mark('null_ratio', ratio, tr('editor.nullRange'));
      } else {
        mark('null_ratio', ratio, null);
        if (commit) {
          current.null_ratio = value / 100;
        }
      }
      if (commit) {
        emit();
      }
    };
    ratio.addEventListener('input', () => checkRatio(true));
    if (Object.hasOwn(restoredValues, 'null_ratio')) {
      ratio.value = restoredValues.null_ratio;
      checkRatio(false);
    }
    delete restoredValues.null_ratio;
    if (current.null_ratio !== undefined && (!Number.isFinite(current.null_ratio) || current.null_ratio < 0 || current.null_ratio > 1)) {
      mark('null_ratio', ratio, tr('editor.nullRange'));
    }
    // A reopened invalid draft must stay reachable, including one whose last
    // valid percentage was zero. Hiding it would leave Apply blocked forever.
    if (errors.has('null_ratio')) {
      nullable.checked = true;
      ratio.disabled = false;
      percentageRow.hidden = false;
    }
    el.append(row(tr('editor.includeNull'), nullable), percentageRow);
  }
  function renderCommon() {
    renderNullOptions();
    if (mode !== 'foreign_key') {
      uniqueInput = h('input', {
        type: 'checkbox',
        'data-field': 'unique',
        checked: Boolean(uniqueBySchema || current.constraints?.unique),
        disabled: Boolean(uniqueBySchema),
        onchange: event => {
          current.constraints = {
            ...current.constraints,
            unique: Boolean(uniqueBySchema || event.target.checked)
          };
          if (constraintsInput && !errors.has('constraints')) {
            constraintsInput.value = JSON.stringify(current.constraints, null, 2);
          }
          emit();
        }
      });
      el.append(row(tr('editor.unique'), uniqueInput, uniqueBySchema ? tr('editor.uniqueLocked') : tr('editor.uniqueComposite')));
    }
  }
  function renderAdvanced() {
    const advanced = h('details', {
      class: 'column-constraints wb-editor-advanced'
    }, h('summary', {}, tr('editor.advanced')), h('p', {
      class: 'editor-note'
    }, tr('editor.advancedHint')));
    const objectField = (field, label, value, update) => {
      const parameter = {
        name: label,
        type: 'object',
        required: false
      };
      const input = multilineControl(field, value == null ? '' : JSON.stringify(value, null, 2), raw => parseParam(parameter, raw), update, {
        placeholder: tr('editor.objectPlaceholder')
      });
      advanced.append(row(label, input));
      return input;
    };
    constraintsInput = objectField('constraints', tr('editor.constraints'), current.constraints, value => {
      if (value === undefined) {
        delete current.constraints;
      } else {
        current.constraints = value;
      }
      if (uniqueBySchema) {
        current.constraints = {
          ...current.constraints,
          unique: true
        };
      }
      if (uniqueInput) {
        uniqueInput.checked = Boolean(current.constraints?.unique);
      }
    });
    if (mode === 'source') {
      for (const [field, label] of [['provider', tr('editor.fieldProvider')], ['faker_method', tr('editor.fakerMethod')], ['mimesis_method', tr('editor.mimesisMethod')]]) {
        const nativeFieldPlaceholder = () => {
          if (field === 'provider') {
            return tr('editor.providerPlaceholder');
          } else if (field === 'faker_method') {
            return tr('editor.fakerPlaceholder');
          } else {
            return tr('editor.mimesisPlaceholder');
          }
        };
        advanced.append(row(label, textControl(field, current[field] || '', raw => raw.trim() || undefined, value => {
          if (value === undefined) {
            delete current[field];
          } else {
            current[field] = value;
          }
        }, {
          placeholder: nativeFieldPlaceholder()
        }), field === 'provider' ? tr('editor.providerHint') : tr('editor.nativeHint')));
      }
      objectField('native_params', tr('editor.nativeParams'), current.native_params, value => {
        if (value === undefined) {
          delete current.native_params;
        } else {
          current.native_params = value;
        }
      });
    }
    el.append(advanced);
  }
  function preserveInvalidField(field) {
    const input = [...el.querySelectorAll('[data-field]')].find(control => control.dataset.field === field);
    if (input && ['INPUT', 'TEXTAREA'].includes(input.tagName)) {
      restoredValues[field] = input.value;
    }
  }
  function preserveDatePresetInvalid() {
    for (const field of errors.keys()) {
      if (['start_date', 'end_date', 'start_year', 'end_year'].includes(field)) {
        continue;
      }
      preserveInvalidField(field);
    }
  }
  function preserveSharedInvalid() {
    for (const field of ['constraints', 'null_ratio', 'provider']) {
      if (!errors.has(field)) {
        continue;
      }
      preserveInvalidField(field);
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
    el.replaceChildren(h('div', {
      class: 'rule-heading wb-editor-heading'
    }, h('strong', {
      class: 'mono'
    }, column.name), h('span', {
      class: 'muted'
    }, column.type || '')));
    summary = h('p', {
      id: errorId,
      class: 'editor-error wb-editor-error',
      role: 'alert'
    });
    el.append(summary);
    if (readonly) {
      el.append(h('p', {
        class: 'muted'
      }, column.is_computed ? tr('editor.computedReadonly') : joinText([tr('editor.idReadonly'), skipDescription()])));
      report();
      return;
    }
    if (mode !== 'foreign_key') {
      const modes = [{
        value: 'source',
        label: tr('editor.generator')
      }, {
        value: 'derived',
        label: tr('editor.expression')
      }];
      if (canSkip) {
        modes.push({
          value: 'skip',
          label: skipLabel()
        });
      }
      el.append(row(tr('editor.mode'), dropdown('mode', mode, modes, next => {
        preserveSharedInvalid();
        modeDrafts.set(mode, copy(current));
        const previous = current;
        current = copy(modeDrafts.get(next) || current);
        // Shared options follow the latest edit when returning to another mode.
        for (const key of ['constraints', 'null_ratio', 'provider']) {
          if (previous[key] === undefined) {
            delete current[key];
          } else {
            current[key] = copy(previous[key]);
          }
        }
        mode = next;
        render();
        emit();
      })));
    }
    if (mode === 'source') {
      renderSource();
    } else if (mode === 'derived') {
      renderDerived();
    } else if (mode === 'foreign_key') {
      renderForeignKey();
    } else {
      el.append(h('p', {
        class: 'drawer-help wb-editor-default'
      }, skipDescription()));
    }
    if (mode !== 'skip') {
      renderCommon();
    }
    renderAdvanced();
    restoredValues = {};
    el.append(h('button', {
      type: 'button',
      class: 'btn small editor-reset wb-editor-reset',
      onclick: () => {
        current = copy(base);
        mode = modeOf(current);
        modeDrafts.clear();
        restoredValues = {};
        render();
        if (!report()) {
          onChange?.(null);
        }
      }
    }, tr('editor.reset')));
    report();
  }
  render();
  return {
    el,
    getDraft() {
      const invalidValues = {};
      for (const field of new Set([...errors.keys(), ...rangeErrors.keys()])) {
        const input = [...el.querySelectorAll('[data-field]')].find(control => control.dataset.field === field);
        if (input && ['INPUT', 'TEXTAREA'].includes(input.tagName)) {
          invalidValues[field] = input.value;
        }
      }
      return {
        config: copy(lastValid),
        current: copy(current),
        mode,
        invalidValues
      };
    },
    destroy() {
      disposed = true;
      dropdowns.forEach(control => control.destroy());
      dropdowns = [];
      datePickers.forEach(control => control.destroy());
      datePickers.clear();
      dateTextDrafts.clear();
    }
  };
}
function parameterHint(parameter) {
  const hints = {
    start_date: tr('editor.startDateHint'),
    end_date: tr('editor.endDateHint'),
    start_time: tr('editor.startTimeHint'),
    end_time: tr('editor.endTimeHint'),
    all_day: tr('editor.allDayHint'),
    weekdays: tr('editor.weekdaysHint'),
    charset: tr('editor.charsetHint'),
    choices: tr('editor.choicesHint'),
    weighted_choices: tr('editor.weightsHint'),
    template: tr('editor.templateHint'),
    sequence_start: tr('editor.sequenceHint'),
    pattern: tr('editor.patternHint'),
    regex: tr('editor.regexHint'),
    mask: tr('editor.maskHint'),
    schema: tr('editor.schemaHint')
  };
  function defaultParameterHint() {
    if (parameter.required) {
      return tr('editor.requiredHint');
    } else if (parameter.default == null) {
      return tr('editor.optionalHint');
    } else {
      return tr('editor.defaultHint', {value: String(parameter.default)});
    }
  }
  return hints[parameter.name] || defaultParameterHint();
}
