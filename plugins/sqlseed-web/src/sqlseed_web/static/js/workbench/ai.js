import { h, api } from '../api.js';
import { genLabel } from '../labels.js';
import { button, modal } from './ui.js';
import { fieldAIEligibility } from './ai-eligibility.js';
import { requestAISuggestions } from './ai-stream.js';
const prefix = '/api/workbench/ai';
const copy = value => structuredClone(value);
const backendLabels = [{
  id: 'openai_compat',
  label: 'OpenAI 兼容服务'
}, {
  id: 'google_ai_studio',
  label: 'Google AI Studio'
}, {
  id: 'ollama',
  label: 'Ollama'
}, {
  id: 'lm_studio',
  label: 'LM Studio'
}];
const stageLabels = {
  context: '准备分析上下文',
  model: '等待 AI 模型',
  validation: '校验建议规则',
  preview: '检查只读样例'
};
const ruleText = rule => {
  if (rule?.derive_from) {
    return `同一行字段派生 · ${[rule.derive_from].flat().join('、')}`;
  }
  const name = rule?.generator || rule?.generator_name;
  if (!name) {
    return '使用现有自动匹配规则';
  }
  const params = Object.entries(rule.params || {}).filter(([key]) => !key.startsWith('_'));
  return `${genLabel(name)}${params.length ? ' · ' + JSON.stringify(Object.fromEntries(params)) : ''}`;
};

// The caller owns the document and writes only reviewed patches. This modal
// captures model identity/epoch/schema before requests and never writes a DB.
export function openAIAssistant({
  model,
  defaultModes,
  connId,
  columns = [],
  initialScope = 'current',
  initialState = null,
  isCurrent = () => true,
  onApply,
  onClose,
  onSettings
}) {
  const epoch = model.epoch,
    schemaHash = model.schema.schema_hash;
  let alive = true,
    busy = false,
    loadingSettings = true,
    settingsKnown = false,
    ready = false,
    available = false,
    availabilityStatus = '',
    version = 0,
    controller = null,
    timer = null,
    elapsedTimer = null,
    analysisState = null,
    diagnostics = null;
  const selected = new Set();
  function initialAnalysisScope() {
    if (columns.length) {
      return 'columns';
    } else if (initialScope === 'selected' && model.document.tables.length) {
      return 'selected';
    } else {
      return 'current';
    }
  }
  let suggestions = [],
    scope = initialState?.scope || initialAnalysisScope();
  const currentTable = initialState?.currentTable || model.view.table;
  const tableSelection = new Set(initialState?.tableSelection || model.document.tables.map(table => table.name));
  const eligibility = (table, column) => {
    const rule = model.rule(table.name, column.name),
      mode = defaultModes?.[table.name]?.[column.name];
    return fieldAIEligibility(table, column, mode === undefined ? rule : {
      ...rule,
      generator: mode
    });
  };
  const columnSelection = new Map(model.schema.tables.map(table => [table.name, new Set(initialState?.columnSelection?.[table.name] || (table.name === currentTable ? table.columns.filter(column => (!columns.length || columns.includes(column.name)) && eligibility(table, column).eligible).map(column => column.name) : []))]));
  const ui = modal('AI 配置助手', {
    wide: true,
    onClose: () => {
      alive = false;
      version++;
      controller?.abort();
      clearTimeout(timer);
      clearTimeout(elapsedTimer);
      onClose?.();
    }
  });
  const current = () => alive && isCurrent() && model.epoch === epoch && model.schema.schema_hash === schemaHash;
  const note = h('p', {
    class: 'hint'
  }, 'AI 根据表结构和业务说明提出字段规则建议，支持当前表、多表和指定字段；由你审阅并应用到生成配置。');
  const disclosure = h('p', {
    class: 'scope-notice'
  }, '仅发送表结构、约束、生成器目录和你填写的业务说明给所选 AI 服务；不发送数据库连接地址、凭据或已有记录。');
  const status = h('p', {
    class: 'wb-ai-status',
    role: 'status',
    'aria-live': 'polite'
  }, '正在读取 AI 设置…');
  const phase = h('strong', {
      role: 'status',
      'aria-live': 'polite'
    }),
    elapsed = h('span', {
      'aria-live': 'off'
    });
  const viewProblems = button('查看问题', () => {
    if (diagnostics) {
      diagnostics.open = true;
      diagnostics.scrollIntoView?.({
        block: 'nearest'
      });
      diagnostics.focus();
    }
  }, {
    small: true,
    hidden: true
  });
  const progress = h('div', {
    class: 'wb-ai-progress',
    hidden: true
  }, phase, elapsed, viewProblems);
  const readiness = h('strong', {}, '正在读取 AI 设置');
  const serviceSummary = h('p', {
    'aria-label': 'AI 服务摘要',
    class: 'hint'
  }, '服务信息尚未读取');
  const settingsLink = button('前往设置', () => goSettings(availabilityStatus === 'import_error' ? 'plugins' : 'ai'), {
    small: true
  });
  const readinessCard = h('section', {
    class: 'wb-source-card wb-ai-service-card',
    'aria-label': 'AI 状态'
  }, readiness, status, serviceSummary, settingsLink);
  const installation = h('section', {
    class: 'wb-source-card',
    'aria-label': '安装 AI 插件',
    hidden: true
  });
  const content = h('div', {
    class: 'wb-ai-review'
  });
  const scopes = h('fieldset', {
    class: 'wb-ai-scope wb-ai-scope-selector',
    'aria-describedby': 'ai-scope-help ai-scope-error'
  }, h('legend', {}, '选择要优化的范围'));
  const scopeOptions = h('div', {
    class: 'wb-ai-scope-options'
  });
  scopes.append(scopeOptions);
  const scopeHelp = h('p', {
    id: 'ai-scope-help',
    class: 'hint'
  }, '这里选择的是可修改规则的范围，独立于本次生成范围。未勾选表的建议仅更新草稿。指定字段时，只需勾选要改规则的字段；同表其他字段及必要上游结构仍作为分析上下文。受保护字段不会被修改。');
  const scopeSummary = h('div', {
    class: 'wb-ai-scope-summary',
    role: 'status',
    'aria-live': 'polite'
  });
  const scopeError = h('p', {
    id: 'ai-scope-error',
    class: 'hint',
    role: 'alert'
  });
  const tablePicker = h('fieldset', {
    class: 'wb-ai-targets'
  }, h('legend', {}, '选择要优化的表'));
  const columnPicker = h('div', {
    class: 'wb-ai-targets wb-ai-columns',
    'aria-label': '选择要优化的字段'
  });
  const fieldEntries = [],
    fieldGroups = [];
  let fieldQuery = '';
  const fieldSearch = h('input', {
    type: 'search',
    'aria-label': '查找表或字段',
    'aria-describedby': 'ai-field-search-help',
    placeholder: '表名、字段名或 orders.promised_at',
    oninput: () => {
      if (!alive || busy) {
        return;
      }
      filterFields();
      updateFieldControls();
    }
  });
  const fieldCount = h('p', {
    class: 'wb-ai-field-count',
    role: 'status',
    'aria-live': 'polite'
  });
  const fieldResults = h('p', {
    class: 'wb-ai-field-results hint'
  });
  const fieldList = h('div', {
    class: 'wb-ai-field-list'
  });
  const fieldEmpty = h('p', {
    class: 'wb-ai-field-empty hint'
  }, '没有匹配的表或字段；已有选择保留，请修改搜索。');
  const selectFiltered = button('选择筛选结果', () => {
    if (!alive || busy) {
      return;
    }
    let changed = false;
    for (const entry of fieldEntries.filter(entry => entry.input && !entry.row.hidden)) {
      const set = columnSelection.get(entry.table);
      if (!set.has(entry.column)) {
        set.add(entry.column);
        entry.input.checked = true;
        changed = true;
      }
    }
    if (changed) {
      clearReview();
    }
  }, {
    small: true
  });
  selectFiltered.dataset.aiSelectFiltered = '';
  const clearFields = button('清空选择', () => {
    if (!alive || busy) {
      return;
    }
    for (const set of columnSelection.values()) {
      set.clear();
    }
    for (const entry of fieldEntries) {
      if (entry.input) {
        entry.input.checked = false;
      }
    }
    clearReview();
  }, {
    small: true
  });
  clearFields.setAttribute('title', '清空全部已选字段，包括当前筛选之外的字段');
  columnPicker.append(h('label', {
    class: 'wb-ai-field-search'
  }, '查找表或字段', fieldSearch), h('p', {
    id: 'ai-field-search-help',
    class: 'hint'
  }, '搜索仅影响显示；选择结果会保留其他已选字段，清空选择会移除全部字段授权。'), fieldCount, fieldResults, h('div', {
    class: 'wb-ai-actions'
  }, selectFiltered, clearFields), fieldList);
  function clearReview() {
    suggestions = [];
    selected.clear();
    content.replaceChildren();
    diagnostics = null;
    viewProblems.hidden = true;
    progress.hidden = true;
    analysisState = null;
    clearTimeout(elapsedTimer);
    apply.hidden = true;
    update();
  }
  const scopeChoices = [['current', `当前表 · ${currentTable}`, '优化当前正在查看的表，不改变生成勾选。'], ['selected', `已选表 · ${model.document.tables.length} 张`, model.document.tables.length ? '优化左侧已勾选的生成表。' : '尚未勾选生成表；可选择当前表或指定表。'], ['database', `整库 · ${model.schema.tables.length} 张表`, '覆盖数据库中的所有表；未勾选表只更新草稿。'], ['tables', '指定表（多选）', '在下方选择一张或多张表。'], ['columns', '指定字段（多选）', '在下方选择要调整规则的字段，可说明同表关系。']];
  for (const [value, label, description] of scopeChoices) {
    const helpId = `ai-scope-${value}-help`;
    const input = h('input', {
      type: 'radio',
      name: 'ai-scope',
      value,
      'aria-label': label,
      'aria-describedby': helpId,
      checked: scope === value,
      onchange: () => {
        scope = value;
        clearReview();
      }
    });
    if (value === 'selected' && !model.document.tables.length) {
      input.disabled = true;
    }
    scopeOptions.append(h('label', {
      class: 'wb-ai-scope-choice'
    }, input, h('span', {}, h('strong', {}, label), h('small', {
      id: helpId,
      class: 'wb-ai-scope-description'
    }, description))));
  }
  let fieldIndex = 0;
  for (const table of model.schema.tables) {
    const input = h('input', {
      type: 'checkbox',
      'data-ai-table': table.name,
      checked: tableSelection.has(table.name),
      onchange: () => {
        if (input.checked) {
          tableSelection.add(table.name);
        } else {
          tableSelection.delete(table.name);
        }
        clearReview();
      }
    });
    tablePicker.append(h('label', {}, input, h('span', {
      class: 'mono'
    }, table.name), h('small', {
      class: 'hint'
    }, model.selected(table.name) ? '本次生成' : '仅更新草稿')));
    const group = h('details', {
      'data-ai-field-table': table.name
    }, h('summary', {
      class: 'mono'
    }, table.name));
    group.open = table.name === currentTable;
    const fields = h('fieldset', {}, h('legend', {}, `${table.name} 的字段`));
    const protectedTitle = h('summary', {}, '受保护字段 · 保留现有规则');
    const protectedFields = h('details', {
      class: 'wb-ai-protected-fields'
    }, protectedTitle);
    const entries = [];
    for (const column of table.columns) {
      const permission = eligibility(table, column),
        helpId = `ai-column-help-${fieldIndex++}`;
      const qualified = `${table.name}.${column.name}`;
      let choice = null,
        row;
      if (permission.eligible) {
        choice = h('input', {
          type: 'checkbox',
          'data-ai-column': qualified,
          'aria-describedby': helpId,
          checked: columnSelection.get(table.name).has(column.name),
          onchange: () => {
            const set = columnSelection.get(table.name);
            if (!alive || busy) {
              choice.checked = set.has(column.name);
              return;
            }
            if (choice.checked) {
              set.add(column.name);
            } else {
              set.delete(column.name);
            }
            clearReview();
          }
        });
        row = h('label', {}, choice, h('span', {
          class: 'mono'
        }, column.name), h('small', {
          id: helpId,
          class: 'hint'
        }, column.type));
        fields.append(row);
      } else {
        row = h('div', {
          class: 'wb-ai-protected-field',
          'data-ai-protected-column': qualified
        }, h('span', {
          class: 'mono'
        }, column.name), h('small', {
          class: 'hint'
        }, permission.reason));
        protectedFields.append(row);
      }
      const entry = {
        table: table.name,
        column: column.name,
        key: qualified.toLowerCase(),
        input: choice,
        row
      };
      entries.push(entry);
      fieldEntries.push(entry);
    }
    group.append(fields, protectedFields);
    fieldList.append(group);
    fieldGroups.push({
      group,
      fields,
      protectedFields,
      protectedTitle,
      entries
    });
  }
  fieldList.append(fieldEmpty);
  filterFields();
  function filterFields() {
    const query = fieldSearch.value.trim().toLowerCase();
    for (const item of fieldGroups) {
      if (!fieldQuery && query) {
        item.savedOpen = item.group.open;
        item.savedProtectedOpen = item.protectedFields.open;
      }
      for (const entry of item.entries) {
        entry.row.hidden = !entry.key.includes(query);
      }
      const visible = item.entries.filter(entry => !entry.row.hidden);
      const protectedCount = visible.filter(entry => !entry.input).length;
      item.group.hidden = !visible.length;
      item.fields.hidden = !visible.some(entry => entry.input);
      item.protectedFields.hidden = !protectedCount;
      item.protectedTitle.textContent = `受保护字段（${protectedCount}）· 保留现有规则`;
      if (query) {
        item.group.open = true;
        item.protectedFields.open = true;
      } else if (fieldQuery) {
        item.group.open = item.savedOpen;
        item.protectedFields.open = item.savedProtectedOpen;
      }
    }
    fieldQuery = query;
    fieldEmpty.hidden = fieldEntries.some(entry => !entry.row.hidden);
  }
  function updateFieldControls() {
    const editable = fieldEntries.filter(entry => entry.input),
      matches = editable.filter(entry => !entry.row.hidden);
    const chosen = editable.filter(entry => columnSelection.get(entry.table).has(entry.column));
    const matchedChosen = chosen.filter(entry => !entry.row.hidden).length;
    const protectedCount = fieldEntries.filter(entry => !entry.input && !entry.row.hidden).length;
    fieldCount.textContent = `已选 ${chosen.length} 个字段允许修改 · 筛选内 ${matchedChosen}，其他 ${chosen.length - matchedChosen}`;
    fieldResults.textContent = `${fieldQuery ? '筛选结果' : '全部表'}：${matches.length} 个可选字段${protectedCount ? "，" + protectedCount + " 个受保护字段仅作上下文" : ''}。`;
    selectFiltered.textContent = `${fieldQuery ? '选择筛选结果' : '选择全部可选字段'}（${matches.length}）`;
    selectFiltered.disabled = busy || matches.length === matchedChosen;
    clearFields.disabled = busy || !chosen.length;
    fieldSearch.disabled = busy;
  }
  const business = h('textarea', {
    'aria-label': '业务说明',
    'aria-describedby': 'ai-business-help',
    rows: 3,
    maxlength: 4000,
    placeholder: '例如：姓名使用中文；订单总额 = 数量 × 单价；完成日期在创建日期后 7 天。',
    oninput: clearReview
  });
  const businessField = h('label', {
    class: 'wb-ai-business'
  }, '业务说明（可选）', business, h('small', {
    id: 'ai-business-help',
    class: 'hint'
  }, '说明数据含义、范围和字段关系。请填写业务规则，不要填写密钥或真实个人记录。'));
  business.value = initialState?.businessContext || '';
  const analyze = button('开始分析', analyzeScope, {
    primary: true
  });
  const apply = button('应用所选建议', applySuggestions, {
    primary: true,
    disabled: true
  });
  const analysis = h('div', {
    class: 'wb-ai-analysis',
    hidden: true
  }, disclosure, scopes, tablePicker, columnPicker, scopeSummary, scopeHelp, scopeError, businessField, content);
  ui.body.append(note, readinessCard, installation, analysis);
  ui.actions.append(progress, button('取消', ui.close), analyze, apply);
  apply.hidden = true;
  function updateElapsed() {
    if (analysisState) {
      elapsed.textContent = `已耗时 ${Math.max(0, Math.floor(((analysisState.finished ?? Date.now()) - analysisState.started) / 1000))} 秒`;
    }
  }
  function tickElapsed() {
    updateElapsed();
    if (alive && analysisState?.finished === null) {
      elapsedTimer = setTimeout(tickElapsed, 1000);
    }
  }
  function finishProgress(message) {
    if (!analysisState) {
      return;
    }
    analysisState.finished = Date.now();
    clearTimeout(elapsedTimer);
    phase.textContent = message;
    updateElapsed();
  }
  function failedAnalysis(error) {
    const expired = !current();
    const missing = error.code === 'unknown_connection' || (error.status === 404 || error.code === 'not_found') && /unknown connection/i.test(error.message);
    let message;
    if (expired) {
      message = '配置已变化，请关闭面板后重新分析。';
    } else if (missing) {
      message = '数据库连接已失效，Web 服务重启后需要重新连接原数据库，再打开 AI 助手；当前配置未改变。';
    } else {
      message = error.message;
    }
    status.textContent = message;
    showDiagnostics({
      issues: [message]
    });
    const summary = message.length > 180 ? `${message.slice(0, 177)}…` : message;
    function analysisFailureStatus() {
      if (expired) {
        return `分析已失效 · ${summary}`;
      } else {
        return `${stageLabels[analysisState.stage]}${error.code === 'ai_timeout' ? '超时' : '失败'} · ${summary}`;
      }
    }
    finishProgress(analysisFailureStatus());
  }
  function showDiagnostics(result) {
    const issues = [...(Array.isArray(result.validation?.issues) ? result.validation.issues : []), ...(Array.isArray(result.issues) ? result.issues : [])];
    const reasons = issues.map(issue => {
      if (typeof issue === 'string') {
        return issue;
      } else {
        return [issue.table, issue.column].filter(Boolean).join('.') + (issue.message ? `：${issue.message}` : '');
      }
    });
    if (Array.isArray(result.rejected)) {
      reasons.push(...result.rejected.map(item => typeof item === 'string' ? item : item.message || item.reason || '建议未通过检查'));
    }
    if (!reasons.length) {
      return;
    }
    diagnostics = h('details', {
      class: 'wb-ai-diagnostics',
      tabindex: -1
    }, h('summary', {}, `检查详情 · ${reasons.length} 项`), h('ul', {}, ...reasons.map(reason => h('li', {}, reason))));
    diagnostics.open = true;
    content.append(diagnostics);
    viewProblems.hidden = false;
  }
  function update() {
    const importError = availabilityStatus === 'import_error';
    updateServiceStatus();
    installation.hidden = !settingsKnown || available;
    analysis.hidden = !available;
    analyze.hidden = !available;
    settingsLink.hidden = settingsKnown && !available && !importError;
    settingsLink.disabled = busy || loadingSettings;
    if (importError) {
      settingsLink.textContent = '查看插件状态';
    } else if (ready) {
      settingsLink.textContent = '更改设置';
    } else {
      settingsLink.textContent = '前往设置';
    }
    const targets = allowedTargets(),
      names = analysisTables();
    const count = targets.reduce((total, target) => total + target.columns.length, 0);
    const protectedCount = model.schema.tables.filter(table => names.includes(table.name)).reduce((total, table) => total + table.columns.filter(column => !eligibility(table, column).eligible).length, 0);
    const draftCount = names.filter(name => !model.selected(name)).length;
    scopeSummary.replaceChildren(h('strong', {}, `${scopeChoices.find(choice => choice[0] === scope)[1]} · ${count} 个字段可优化`), h('p', {}, `${names.length} 张表作为分析上下文${protectedCount ? "，" + protectedCount + " 个受保护字段保留现有规则" : ''}。${draftCount ? "" + draftCount + " 张表未加入生成范围，建议仅更新草稿。" : ''}`));
    analyze.disabled = busy || !available || !ready || !targets.length;
    apply.disabled = busy || selected.size === 0;
    for (const input of scopes.querySelectorAll('input')) {
      input.disabled = busy || input.value === 'selected' && !model.document.tables.length;
    }
    for (const input of [...tablePicker.querySelectorAll('input'), ...columnPicker.querySelectorAll('input')]) {
      input.disabled = busy;
    }
    updateFieldControls();
    business.disabled = busy;
    tablePicker.hidden = scope !== 'tables';
    columnPicker.hidden = scope !== 'columns';
    scopeError.textContent = targets.length ? '' : '请至少选择一张表或一个可由 AI 调整的字段；受保护字段仅作为结构上下文。';
    function updateServiceStatus() {
      if (loadingSettings) {
        readiness.textContent = '正在读取 AI 设置';
      } else if (!settingsKnown) {
        readiness.textContent = 'AI 状态未获取';
      } else if (!available) {
        if (importError) {
          readiness.textContent = 'AI 插件加载异常';
        } else {
          readiness.textContent = 'AI 扩展未安装';
        }
      } else if (ready) {
        readiness.textContent = 'AI 配置已填写';
      } else {
        readiness.textContent = 'AI 待配置';
      }
    }
  }
  function analysisTables() {
    if (scope === 'current') {
      return [currentTable];
    } else if (scope === 'selected') {
      return model.document.tables.map(table => table.name);
    } else if (scope === 'tables') {
      return [...tableSelection];
    } else if (scope === 'columns') {
      return model.schema.tables.filter(table => columnSelection.get(table.name).size).map(table => table.name);
    } else {
      return model.schema.tables.map(table => table.name);
    }
  }
  function allowedTargets() {
    const names = analysisTables();
    return model.schema.tables.filter(table => names.includes(table.name)).map(table => ({
      table: table.name,
      columns: table.columns.filter(column => eligibility(table, column).eligible && (scope !== 'columns' || columnSelection.get(table.name).has(column.name))).map(column => column.name)
    })).filter(target => target.columns.length);
  }
  function goSettings(section) {
    if (!current() || busy) {
      return;
    }
    const context = {
      scope,
      currentTable,
      tableSelection: [...tableSelection],
      columnSelection: Object.fromEntries([...columnSelection].map(([table, values]) => [table, [...values]])),
      businessContext: business.value
    };
    ui.close();
    onSettings?.({
      section,
      context
    });
  }
  function showSettings(config) {
    settingsKnown = true;
    available = Boolean(config.available);
    ready = available && Boolean(config.ready);
    availabilityStatus = config.availability_status || (available ? 'available' : 'not_installed');
    const effective = config.effective || {};
    // Only the known provider label and model ID are displayed. Never render
    // endpoint URLs or arbitrary returned credential fields in this summary.
    const backend = backendLabels.find(item => item.id === effective.backend)?.label || 'AI 服务';
    serviceSummary.textContent = available ? `${backend} · ${effective.model || '尚未选择模型'}` : '';
    if (!available) {
      if (availabilityStatus === 'import_error') {
        status.textContent = 'AI 扩展已安装但加载异常，规则建议与分析不可用。';
      } else {
        status.textContent = 'AI 扩展未安装，规则建议与分析不可用。';
      }
    } else {
      status.textContent = config.message || (ready ? '配置已填写，可开始分析。' : '请前往设置页完成 AI 服务配置。');
    }
    if (!available) {
      showUnavailableAI();
    }
    update();
    function showUnavailableAI() {
      const broken = availabilityStatus === 'import_error';
      installation.setAttribute('aria-label', broken ? '修复 AI 插件' : '安装 AI 插件');
      installation.replaceChildren(h('p', {}, broken ? '请在“设置 → 插件与版本”查看异常信息，处理后返回 AI 助手。' : '请在“设置 → 插件与版本”安装 AI 扩展，完成后返回 AI 助手。'), h('p', {
        class: 'hint'
      }, '当前生成配置保留，仍可手动调整规则、预览和生成数据。'), ...(!broken ? [button('前往插件设置', () => goSettings('plugins'), {
        small: true
      })] : []));
    }
  }
  async function analyzeScope() {
    if (!current()) {
      status.textContent = '配置已变化，请关闭面板后重新分析。';
      return;
    }
    if (busy || !available || !ready) {
      return;
    }
    const targets = allowedTargets(),
      names = analysisTables();
    if (!names.length || !targets.length) {
      return;
    }
    const document = copy(model.document);
    const table_drafts = copy(Object.values(model.view.tableDrafts || {}).filter(table => !model.selected(table.name)));
    const request = {
      conn_id: connId,
      schema_hash: schemaHash,
      tables: names,
      allowed_targets: targets,
      business_context: business.value.trim(),
      table_drafts,
      document
    };
    busy = true;
    const ticket = ++version;
    selected.clear();
    suggestions = [];
    content.replaceChildren();
    diagnostics = null;
    viewProblems.hidden = true;
    apply.hidden = true;
    controller = new AbortController();
    analysisState = {
      started: Date.now(),
      finished: null,
      stage: 'context'
    };
    progress.hidden = false;
    phase.textContent = '正在提交分析请求…';
    tickElapsed();
    update();
    status.textContent = '正在准备分析上下文…';
    const requestTimer = setTimeout(() => {
      if (alive && ticket === version) {
        controller.abort();
        version++;
        busy = false;
        const error = new Error('AI 分析超过 180 秒，请检查失败阶段后重试；当前规则未改变。');
        error.code = 'ai_timeout';
        failedAnalysis(error);
        update();
      }
    }, 180000);
    timer = requestTimer;
    try {
      const result = await requestAISuggestions(`${prefix}/suggest`, request, {
        signal: controller.signal,
        onProgress: event => {
          if (!alive || ticket !== version) {
            return;
          }
          if (!current()) {
            controller.abort();
            return;
          }
          analysisState.stage = event.stage;
          analysisState.hasProgress = true;
          phase.textContent = `${stageLabels[event.stage]} · ${event.message}`;
          status.textContent = event.message;
        }
      });
      if (!alive || ticket !== version) {
        return;
      }
      if (!current()) {
        throw new Error('配置已变化，请关闭面板后重新分析。');
      }
      if (result.schema_hash !== schemaHash) {
        throw new Error('数据库结构已变化，请刷新后重新分析。');
      }
      if (!Array.isArray(result.suggestions)) {
        throw new Error('AI 建议格式不正确，请重试。');
      }
      acceptSuggestions(result);
      renderSuggestionGroups();
      apply.hidden = !suggestions.length;
    } catch (error) {
      if (alive && ticket === version) {
        failedAnalysis(error);
      }
    } finally {
      clearTimeout(requestTimer);
      if (alive && ticket === version) {
        clearTimeout(elapsedTimer);
        busy = false;
        update();
      }
    }
    function renderSuggestionGroups() {
      const groups = new Map();
      suggestions.forEach((item, index) => {
        const id = item.group_id || `single-${index}`;
        if (!groups.has(id)) {
          groups.set(id, []);
        }
        groups.get(id).push(index);
      });
      for (const indices of groups.values()) {
        const input = h('input', {
          type: 'checkbox',
          'data-ai-suggestion': String(indices[0]),
          onchange: () => {
            for (const index of indices) {
              if (input.checked) {
                selected.add(index);
              } else {
                selected.delete(index);
              }
            }
            update();
          }
        });
        const article = h('article', {
          class: 'wb-ai-suggestion'
        }, h('label', {}, input, h('strong', {}, indices.length > 1 ? `关联规则 · ${indices.length} 个字段，一起应用` : `${suggestions[indices[0]].table}.${suggestions[indices[0]].column}`)));
        for (const index of indices) {
          appendSuggestionDetails(article, index, indices);
        }
        content.append(article);
      }
    }
    function appendSuggestionDetails(article, index, indices) {
      const item = suggestions[index],
        currentRule = model.rule(item.table, item.column);
      if (indices.length > 1) {
        article.append(h('h4', {
          class: 'mono'
        }, `${item.table}.${item.column}`));
      }
      if (!model.selected(item.table)) {
        article.append(h('p', {
          class: 'hint'
        }, '该表未加入生成范围；应用后仅更新其草稿。'));
      }
      article.append(h('p', {}, item.reason || '请结合业务含义确认。'), h('div', {
        class: 'wb-ai-diff'
      }, h('div', {}, h('small', {}, '当前规则'), h('p', {}, ruleText(currentRule))), h('div', {}, h('small', {}, '建议规则'), h('p', {}, ruleText(item.after)))));
      if (item.relation) {
        const labels = {
          copy: '复制',
          concat: '按顺序拼接',
          product: '相乘',
          date_offset: '日期偏移'
        };
        article.append(h('p', {
          class: 'wb-ai-relation'
        }, `${item.relation.sources.join(' + ')} → ${item.column} · ${labels[item.relation.template] || '同一行关系'}${Object.keys(item.relation.options || {}).length ? ' · ' + JSON.stringify(item.relation.options) : ''}`));
        if (item.evidence) {
          article.append(h('p', {
            class: 'hint'
          }, item.evidence.message));
          const rows = item.evidence.rows || [];
          if (rows.length) {
            const names = Object.keys(rows[0]);
            article.append(h('div', {
              class: 'wb-ai-evidence'
            }, h('table', {}, h('caption', {}, '同一行关系的只读样例'), h('thead', {}, h('tr', {}, ...names.map(name => h('th', {
              scope: 'col'
            }, name)))), h('tbody', {}, ...rows.map(row => h('tr', {}, ...names.map(name => h('td', {}, row[name] === null ? 'NULL' : String(row[name])))))))));
          }
        }
      }
    }
    function acceptSuggestions(result) {
      const valid = item => targets.some(target => target.table === item.table && target.columns.includes(item.column)) && item.after?.name === item.column;
      const invalidGroups = new Set(result.suggestions.filter(item => !valid(item)).map(item => item.group_id).filter(Boolean));
      suggestions = result.validation?.ok === false ? [] : result.suggestions.filter(item => valid(item) && !invalidGroups.has(item.group_id));
      status.textContent = suggestions.length ? `收到 ${suggestions.length} 条建议。存在关联的规则会作为一组应用，请对比后勾选。` : result.validation?.message || '没有可应用的建议，现有规则保持不变。';
      const analysisCompletionLabel = () => {
        if (result.validation?.ok === false) {
          return "" + (analysisState.hasProgress ? stageLabels[analysisState.stage] : '候选检查') + "未通过";
        } else {
          return '分析完成';
        }
      };
      finishProgress(`${analysisCompletionLabel()} · ${status.textContent}`);
      showDiagnostics(result);
    }
  }
  async function applySuggestions() {
    if (!current()) {
      status.textContent = '配置已变化，请关闭面板后重新分析。';
      apply.disabled = true;
      return;
    }
    if (!selected.size || busy) {
      return;
    }
    busy = true;
    update();
    try {
      await onApply?.([...selected].map(index => copy(suggestions[index])));
      if (alive) {
        ui.close();
      }
    } catch (error) {
      if (alive) {
        status.textContent = error.message;
        busy = false;
        update();
      }
    }
  }
  api(`${prefix}/config`).then(config => {
    if (alive) {
      showSettings(config);
    }
  }).catch(error => {
    if (alive) {
      status.textContent = error.message;
    }
  }).finally(() => {
    if (alive) {
      loadingSettings = false;
      update();
    }
  });
  update();
  return {
    ...ui,
    destroy: ui.close
  };
}
