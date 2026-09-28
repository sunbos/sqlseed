import {tr, appendContent, setAttr, replaceContent, setText, errorText, UserFacingError, joinText, liveText, isLocalized, serverText, serverMessages} from '../i18n.js';
import '../i18n/messages/assistant.js';
import { h, api } from '../api.js';
import { genLabel } from '../labels.js';
import { button, modal } from './ui.js';
import { fieldAIEligibility } from './ai-eligibility.js';
import { requestAISuggestions } from './ai-stream.js';
import { openSuggestionAdjustment } from './ai-adjustment.js';
const prefix = '/api/workbench/ai';
const copy = value => structuredClone(value);
const backendLabels = [{
  id: 'openai_compat',
  label: tr("assistant.backend.compatible")
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
  context: tr("assistant.stage.context"),
  model: tr("assistant.stage.model"),
  validation: tr("assistant.stage.validation"),
  preview: tr("assistant.stage.preview")
};
const ruleText = rule => {
  if (rule?.derive_from) {
    return tr("assistant.rule.derived", {fields: [rule.derive_from].flat().join('、')});
  }
  const name = rule?.generator || rule?.generator_name;
  if (!name) {
    return tr("assistant.rule.inferred");
  }
  const params = Object.entries(rule.params || {}).filter(([key]) => !key.startsWith('_'));
  return joinText([genLabel(name), params.length ? ' · ' + JSON.stringify(Object.fromEntries(params)) : '']);
};

// The caller owns the document and writes only reviewed patches. This modal
// captures model identity/epoch/schema before requests and never writes a DB.
export function openAIAssistant({
  model,
  catalog,
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
  let adjustment = null;
  const adjusted = new Set();
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
  const ui = modal(tr("assistant.title"), {
    wide: true,
    dismiss: 'footer',
    onClose: () => {
      alive = false;
      adjustment?.close();
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
  }, tr("assistant.intro"));
  const disclosure = h('p', {
    class: 'scope-notice'
  }, tr("assistant.privacy"));
  const status = h('p', {
    class: 'wb-ai-status',
    role: 'status',
    'aria-live': 'polite'
  }, tr("assistant.settings.loading"));
  const phase = h('strong', {
      role: 'status',
      'aria-live': 'polite'
    }),
    elapsed = h('span', {
      'aria-live': 'off'
    });
  const viewProblems = button(tr("assistant.issues.view"), () => {
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
  const readiness = h('strong', {}, tr("assistant.settings.loadingShort"));
  const serviceSummary = h('p', {
    'aria-label': tr("assistant.settings.summary"),
    class: 'hint'
  }, tr("assistant.settings.notLoaded"));
  const settingsLink = button(tr("assistant.settings.open"), () => goSettings(availabilityStatus === 'import_error' ? 'plugins' : 'ai'), {
    small: true
  });
  const readinessCard = h('section', {
    class: 'wb-source-card wb-ai-service-card',
    'aria-label': tr("assistant.status")
  }, readiness, status, serviceSummary, settingsLink);
  const installation = h('section', {
    class: 'wb-source-card',
    'aria-label': tr("assistant.component.install"),
    hidden: true
  });
  const content = h('div', {
    class: 'wb-ai-review'
  });
  const scopes = h('fieldset', {
    class: 'wb-ai-scope wb-ai-scope-selector',
    'aria-describedby': 'ai-scope-help ai-scope-error'
  }, h('legend', {}, tr("assistant.scope.title")));
  const scopeOptions = h('div', {
    class: 'wb-ai-scope-options'
  });
  appendContent(scopes, scopeOptions);
  const scopeHelp = h('p', {
    id: 'ai-scope-help',
    class: 'hint'
  }, tr("assistant.scope.help"));
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
  }, h('legend', {}, tr("assistant.scope.chooseTables")));
  const columnPicker = h('div', {
    class: 'wb-ai-targets wb-ai-columns',
    'aria-label': tr("assistant.scope.chooseFields")
  });
  const fieldEntries = [],
    fieldGroups = [];
  let fieldQuery = '';
  const fieldSearch = h('input', {
    type: 'search',
    'aria-label': tr("assistant.scope.search"),
    'aria-describedby': 'ai-field-search-help',
    placeholder: tr("assistant.scope.searchPlaceholder"),
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
  }, tr("assistant.scope.noMatches"));
  const selectFiltered = button(tr("assistant.scope.selectMatches"), () => {
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
  const clearFields = button(tr("assistant.scope.clear"), () => {
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
  setAttr(clearFields, 'title', tr("assistant.scope.clearAllLabel"));
  appendContent(columnPicker, h('label', {
    class: 'wb-ai-field-search'
  }, tr("assistant.scope.search"), fieldSearch), h('p', {
    id: 'ai-field-search-help',
    class: 'hint'
  }, tr("assistant.scope.filterHelp")), fieldCount, fieldResults, h('div', {
    class: 'wb-ai-actions'
  }, selectFiltered, clearFields), fieldList);
  function clearReview() {
    adjustment?.close();
    adjusted.clear();
    suggestions = [];
    selected.clear();
    replaceContent(content);
    diagnostics = null;
    viewProblems.hidden = true;
    progress.hidden = true;
    analysisState = null;
    clearTimeout(elapsedTimer);
    apply.hidden = true;
    update();
  }
  const scopeChoices = [['current', tr("assistant.scope.currentTable", {table: currentTable}), tr("assistant.scope.currentHelp")], ['selected', tr("assistant.scope.selectedTables", {count: model.document.tables.length}), model.document.tables.length ? tr("assistant.scope.selectedHelp") : tr("assistant.scope.noneSelected")], ['database', tr("assistant.scope.database", {count: model.schema.tables.length}), tr("assistant.scope.databaseHelp")], ['tables', tr("assistant.scope.specificTables"), tr("assistant.scope.specificTablesHelp")], ['columns', tr("assistant.scope.specificFields"), tr("assistant.scope.specificFieldsHelp")]];
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
    appendContent(scopeOptions, h('label', {
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
    appendContent(tablePicker, h('label', {}, input, h('span', {
      class: 'mono'
    }, table.name), h('small', {
      class: 'hint'
    }, model.selected(table.name) ? tr("assistant.scope.generated") : tr("assistant.scope.draftOnly"))));
    const group = h('details', {
      'data-ai-field-table': table.name
    }, h('summary', {
      class: 'mono'
    }, table.name));
    group.open = table.name === currentTable;
    const fields = h('fieldset', {}, h('legend', {}, tr("assistant.scope.tableFields", {table: table.name})));
    const protectedTitle = h('summary', {}, tr("assistant.scope.protected"));
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
        appendContent(fields, row);
      } else {
        row = h('div', {
          class: 'wb-ai-protected-field',
          'data-ai-protected-column': qualified
        }, h('span', {
          class: 'mono'
        }, column.name), h('small', {
          class: 'hint'
        }, permission.reason));
        appendContent(protectedFields, row);
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
    appendContent(group, fields, protectedFields);
    appendContent(fieldList, group);
    fieldGroups.push({
      group,
      fields,
      protectedFields,
      protectedTitle,
      entries
    });
  }
  appendContent(fieldList, fieldEmpty);
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
      setText(item.protectedTitle, tr("assistant.scope.protectedCount", {count: protectedCount}));
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
    setText(fieldCount, tr("assistant.scope.fieldCounts", {selected: chosen.length, matching: matchedChosen, other: chosen.length - matchedChosen}));
    setText(fieldResults, tr("assistant.scope.matchSummary", {scope: fieldQuery ? tr("assistant.scope.filtered") : tr("assistant.scope.allTables"), count: matches.length, protectedNote: protectedCount ? tr("assistant.scope.protectedContext", {count: protectedCount}) : ''}));
    setText(selectFiltered, tr('assistant.scope.selectCount', {label: fieldQuery ? tr("assistant.scope.selectMatches") : tr("assistant.scope.selectAllFields"), count: matches.length}));
    selectFiltered.disabled = busy || Boolean(adjustment) || matches.length === matchedChosen;
    clearFields.disabled = busy || Boolean(adjustment) || !chosen.length;
    fieldSearch.disabled = busy || Boolean(adjustment);
  }
  const business = h('textarea', {
    'aria-label': tr("assistant.requirements.label"),
    'aria-describedby': 'ai-business-help',
    rows: 3,
    maxlength: 4000,
    placeholder: tr("assistant.requirements.placeholder"),
    oninput: clearReview
  });
  const businessField = h('label', {
    class: 'wb-ai-business'
  }, tr("assistant.requirements.optional"), business, h('small', {
    id: 'ai-business-help',
    class: 'hint'
  }, tr("assistant.requirements.help")));
  business.value = initialState?.businessContext || '';
  const analyze = button(tr("assistant.action.analyze"), analyzeScope, {
    primary: true
  });
  const apply = button(tr("assistant.action.apply"), applySuggestions, {
    primary: true,
    disabled: true
  });
  const analysis = h('div', {
    class: 'wb-ai-analysis',
    hidden: true
  }, disclosure, scopes, tablePicker, columnPicker, scopeSummary, scopeHelp, scopeError, businessField, content);
  appendContent(ui.body, note, readinessCard, installation, analysis);
  appendContent(ui.actions, progress, button(tr("assistant.action.cancel"), ui.close), analyze, apply);
  apply.hidden = true;
  function updateElapsed() {
    if (analysisState) {
      setText(elapsed, tr("assistant.progress.elapsed", {seconds: Math.max(0, Math.floor(((analysisState.finished ?? Date.now()) - analysisState.started) / 1000))}));
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
    setText(phase, message);
    updateElapsed();
  }
  function failedAnalysis(error) {
    const expired = !current();
    const missing = error.code === 'unknown_connection' || error.messageKey === 'backend.state.unknown_connection' ||
      !error.messageKey && (error.status === 404 || error.code === 'not_found') && /unknown connection/i.test(error.message);
    let message;
    if (expired) {
      message = tr("assistant.stale.configuration");
    } else if (missing) {
      message = tr("assistant.stale.connection");
    } else {
      message = errorText(error);
    }
    setText(status, message);
    showDiagnostics({
      issues: [message]
    });
    const summary = liveText(() => String(message).length > 180 ? `${String(message).slice(0, 177)}…` : message);
    function analysisFailureStatus() {
      if (expired) {
        return tr("assistant.progress.invalidated", {summary: summary});
      } else {
        return tr('assistant.progress.stageFailure', {stage: stageLabels[analysisState.stage], outcome: error.code === 'ai_timeout' ? tr("assistant.progress.timeout") : tr("assistant.progress.failed"), summary});
      }
    }
    finishProgress(analysisFailureStatus());
  }
  function showDiagnostics(result) {
    const issues = [...(Array.isArray(result.validation?.issues) ? serverMessages(result.validation, 'issues') : []), ...(Array.isArray(result.issues) ? serverMessages(result, 'issues') : [])];
    const reasons = issues.map(issue => {
      if (typeof issue === 'string' || isLocalized(issue)) {
        return issue;
      } else {
        return joinText([[issue.table, issue.column].filter(Boolean).join('.'), issue.message ? joinText([': ', serverText(issue)]) : '']);
      }
    });
    if (Array.isArray(result.rejected)) {
      reasons.push(...serverMessages(result, 'rejected').map(item => typeof item === 'string' || isLocalized(item) ? item : serverText(item) || serverText(item, 'reason') || tr("assistant.issues.failed")));
    }
    if (!reasons.length) {
      return;
    }
    diagnostics = h('details', {
      class: 'wb-ai-diagnostics',
      tabindex: -1
    }, h('summary', {}, tr("assistant.issues.details", {count: reasons.length})), h('ul', {}, ...reasons.map(reason => h('li', {}, reason))));
    diagnostics.open = true;
    appendContent(content, diagnostics);
    viewProblems.hidden = false;
  }
  function update() {
    const importError = availabilityStatus === 'import_error';
    updateServiceStatus();
    installation.hidden = !settingsKnown || available;
    analysis.hidden = !available;
    analyze.hidden = !available;
    settingsLink.hidden = settingsKnown && !available && !importError;
    settingsLink.disabled = busy || loadingSettings || Boolean(adjustment);
    if (importError) {
      setText(settingsLink, tr("assistant.component.status"));
    } else if (ready) {
      setText(settingsLink, tr("assistant.settings.change"));
    } else {
      setText(settingsLink, tr("assistant.settings.open"));
    }
    const targets = allowedTargets(),
      names = analysisTables();
    const count = targets.reduce((total, target) => total + target.columns.length, 0);
    const protectedCount = model.schema.tables.filter(table => names.includes(table.name)).reduce((total, table) => total + table.columns.filter(column => !eligibility(table, column).eligible).length, 0);
    const draftCount = names.filter(name => !model.selected(name)).length;
    replaceContent(scopeSummary, h('strong', {}, tr("assistant.scope.eligible", {scope: scopeChoices.find(choice => choice[0] === scope)[1], count: count})), h('p', {}, tr("assistant.scope.analysisContext", {tables: names.length, protectedNote: protectedCount ? tr("assistant.scope.protectedRules", {count: protectedCount}) : '', draftNote: draftCount ? tr("assistant.scope.draftTables", {count: draftCount}) : ''})));
    analyze.disabled = busy || Boolean(adjustment) || !available || !ready || !targets.length;
    apply.disabled = busy || Boolean(adjustment) || selected.size === 0;
    for (const input of scopes.querySelectorAll('input')) {
      input.disabled = busy || Boolean(adjustment) || input.value === 'selected' && !model.document.tables.length;
    }
    for (const input of [...tablePicker.querySelectorAll('input'), ...columnPicker.querySelectorAll('input')]) {
      input.disabled = busy || Boolean(adjustment);
    }
    updateFieldControls();
    business.disabled = busy || Boolean(adjustment);
    for (const control of content.querySelectorAll('[data-ai-adjust], [data-ai-suggestion]')) control.disabled = busy || Boolean(adjustment);
    tablePicker.hidden = scope !== 'tables';
    columnPicker.hidden = scope !== 'columns';
    setText(scopeError, targets.length ? '' : tr("assistant.scope.required"));
    function updateServiceStatus() {
      if (loadingSettings) {
        setText(readiness, tr("assistant.settings.loadingShort"));
      } else if (!settingsKnown) {
        setText(readiness, tr("assistant.settings.unknown"));
      } else if (!available) {
        if (importError) {
          setText(readiness, tr("assistant.component.importError"));
        } else {
          setText(readiness, tr("assistant.component.missing"));
        }
      } else if (ready) {
        setText(readiness, tr("assistant.settings.configured"));
      } else {
        setText(readiness, tr("assistant.settings.required"));
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
    if (!current() || busy || adjustment) {
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
    const backend = backendLabels.find(item => item.id === effective.backend)?.label || tr("assistant.settings.service");
    setText(serviceSummary, available ? joinText([backend, effective.model || tr("assistant.settings.noModel")], ' · ') : '');
    if (!available) {
      if (availabilityStatus === 'import_error') {
        setText(status, tr("assistant.component.importHelp"));
      } else {
        setText(status, tr("assistant.component.missingHelp"));
      }
    } else {
      setText(status, serverText(config) || (ready ? tr("assistant.settings.ready") : tr("assistant.settings.setupHelp")));
    }
    if (!available) {
      showUnavailableAI();
    }
    update();
    function showUnavailableAI() {
      const broken = availabilityStatus === 'import_error';
      setAttr(installation, 'aria-label', broken ? tr("assistant.component.repair") : tr("assistant.component.install"));
      replaceContent(installation, h('p', {}, broken ? tr("assistant.component.repairHelp") : tr("assistant.component.installHelp")), h('p', {
        class: 'hint'
      }, tr("assistant.component.optionalHelp")), ...(!broken ? [button(tr("assistant.component.openSettings"), () => goSettings('plugins'), {
        small: true
      })] : []));
    }
  }
  async function analyzeScope() {
    if (!current()) {
      setText(status, tr("assistant.stale.configuration"));
      return;
    }
    if (busy || adjustment || !available || !ready) {
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
    adjusted.clear();
    suggestions = [];
    replaceContent(content);
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
    setText(phase, tr("assistant.progress.submitting"));
    tickElapsed();
    update();
    setText(status, tr("assistant.progress.context"));
    const requestTimer = setTimeout(() => {
      if (alive && ticket === version) {
        controller.abort();
        version++;
        busy = false;
        const error = new UserFacingError(tr("assistant.progress.deadline"));
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
          setText(phase, joinText([stageLabels[event.stage], serverText(event)], ' · '));
          setText(status, serverText(event));
        }
      });
      if (!alive || ticket !== version) {
        return;
      }
      if (!current()) {
        throw new UserFacingError(tr("assistant.stale.configuration"));
      }
      if (result.schema_hash !== schemaHash) {
        throw new UserFacingError(tr("assistant.stale.schema"));
      }
      if (!Array.isArray(result.suggestions)) {
        throw new UserFacingError(tr("assistant.response.invalid"));
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
            if (!current() || busy || adjustment) return;
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
        }, h('label', {}, input, h('strong', {}, indices.length > 1 ? tr("assistant.suggestion.group", {count: indices.length}) : `${suggestions[indices[0]].table}.${suggestions[indices[0]].column}`)));
        for (const index of indices) {
          appendSuggestionDetails(article, index, indices, input);
        }
        appendContent(content, article);
      }
    }
    function appendSuggestionDetails(article, index, indices, input) {
      const item = suggestions[index],
        currentRule = model.rule(item.table, item.column);
      if (indices.length > 1) {
        appendContent(article, h('h4', {
          class: 'mono'
        }, `${item.table}.${item.column}`));
      }
      if (!model.selected(item.table)) {
        appendContent(article, h('p', {
          class: 'hint'
        }, tr("assistant.suggestion.draftOnly")));
      }
      const afterText = h('p', {}, ruleText(item.after));
      appendContent(article, h('p', {}, item.reason || tr("assistant.suggestion.review")), h('div', {
        class: 'wb-ai-diff'
      }, h('div', {}, h('small', {}, tr("assistant.suggestion.current")), h('p', {}, ruleText(currentRule))), h('div', {}, h('small', {}, tr("assistant.suggestion.proposed")), afterText)));
      const adjustedNotice = h('p', {class: 'hint wb-ai-adjusted-notice', hidden: true});
      const edit = button(tr("assistant.suggestion.adjust"), () => {
        if (!current() || busy || adjustment) return;
        const table = model.schema.tables.find(table => table.name === item.table);
        const column = table?.columns.find(column => column.name === item.column);
        if (!column || !eligibility(table, column).eligible) return;
        adjustment = openSuggestionAdjustment({item, table, column, catalog, host: article, isCurrent: current,
          onCommit: rule => {
            if (!current()) return;
            item.after = copy(rule);
            adjusted.add(index);
            setText(afterText, ruleText(rule));
            for (const sibling of indices) {
              selected.delete(sibling);
              delete suggestions[sibling].evidence;
              delete suggestions[sibling].relation;
            }
            input.checked = false;
            for (const evidence of article.querySelectorAll('.wb-ai-evidence, .wb-ai-relation, [data-ai-evidence-message]')) evidence.remove();
            adjustedNotice.hidden = false;
            setText(adjustedNotice, tr("assistant.suggestion.adjusted"));
          },
          onDone: () => {adjustment = null; if (alive) {update(); edit.focus({preventScroll: true});}}
        });
        update();
      }, {small: true, 'data-ai-adjust': String(index), 'aria-label': tr("assistant.suggestion.adjustLabel", {table: item.table, column: item.column})});
      appendContent(article, edit, adjustedNotice);
      if (item.relation) {
        const labels = {
          copy: tr("assistant.relation.copy"),
          concat: tr("assistant.relation.concat"),
          product: tr("assistant.relation.product"),
          date_offset: tr("assistant.relation.dateOffset")
        };
        appendContent(article, h('p', {
          class: 'wb-ai-relation'
        }, joinText([`${item.relation.sources.join(' + ')} → ${item.column} · `, labels[item.relation.template] || tr("assistant.relation.title"), Object.keys(item.relation.options || {}).length ? ' · ' + JSON.stringify(item.relation.options) : ''])));
        if (item.evidence) {
          appendContent(article, h('p', {
            class: 'hint', 'data-ai-evidence-message': ''
          }, serverText(item.evidence)));
          const rows = item.evidence.rows || [];
          if (rows.length) {
            const names = Object.keys(rows[0]);
            appendContent(article, h('div', {
              class: 'wb-ai-evidence'
            }, h('table', {}, h('caption', {}, tr("assistant.relation.samples")), h('thead', {}, h('tr', {}, ...names.map(name => h('th', {
              scope: 'col'
            }, name)))), h('tbody', {}, ...rows.map(row => h('tr', {}, ...names.map(name => h('td', {}, row[name] === null ? 'NULL' : String(row[name])))))))));
          }
        }
      }
    }
    function acceptSuggestions(result) {
      const valid = item => targets.some(target => target.table === item.table && target.columns.includes(item.column)) && item.after?.name === item.column;
      const invalidGroups = new Set(result.suggestions.filter(item => !valid(item)).map(item => item.group_id).filter(Boolean));
      suggestions = result.validation?.ok === false ? [] : copy(result.suggestions.filter(item => valid(item) && !invalidGroups.has(item.group_id)));
      const completionMessage = suggestions.length ? tr("assistant.suggestion.received", {count: suggestions.length}) : serverText(result.validation) || tr("assistant.suggestion.empty");
      setText(status, completionMessage);
      const analysisCompletionLabel = () => {
        if (result.validation?.ok === false) {
          return tr('assistant.candidate.stageFailed', {stage: analysisState.hasProgress ? stageLabels[analysisState.stage] : tr("assistant.candidate.title")});
        } else {
          return tr("assistant.progress.complete");
        }
      };
      finishProgress(joinText([analysisCompletionLabel(), completionMessage], ' · '));
      showDiagnostics(result);
    }
  }
  async function applySuggestions() {
    if (!current()) {
      setText(status, tr("assistant.stale.configuration"));
      apply.disabled = true;
      return;
    }
    if (!selected.size || busy || adjustment) {
      return;
    }
    busy = true;
    update();
    try {
      const patches = [...selected].map(index => copy(suggestions[index]));
      const targets = allowedTargets();
      if (!patches.every(item => targets.some(target => target.table === item.table && target.columns.includes(item.column)) && item.after?.name === item.column)) throw new UserFacingError(tr("assistant.stale.scope"));
      if ([...selected].some(index => adjusted.has(index))) {
        setText(status, tr("assistant.candidate.checking"));
        const document = copy(model.document);
        for (const patch of patches) {
          let table = document.tables.find(table => table.name === patch.table);
          if (!table) {table = copy(model.table(patch.table)); document.tables.push(table);}
          table.columns = (table.columns || []).filter(column => column.name !== patch.column);
          table.columns.push(copy(patch.after));
        }
        const ticket = version;
        controller = new AbortController();
        const checked = await api('/api/workbench/check', {method: 'POST', signal: controller.signal,
          body: JSON.stringify({conn_id: connId, schema_hash: schemaHash, document, count: 3})});
        if (!alive || ticket !== version) return;
        if (!current()) throw new UserFacingError(tr("assistant.stale.configuration"));
        if (!checked.ok) {
          const errors = (checked.issues || []).filter(issue => issue.severity !== 'warning').map(issue => serverText(issue)).filter(Boolean);
          throw new UserFacingError(tr("assistant.candidate.invalid", {issues: errors.length ? joinText(errors, '; ') : tr("assistant.candidate.checkHelp")}));
        }
      }
      if (!current()) throw new UserFacingError(tr("assistant.stale.configuration"));
      await onApply?.(patches);
      if (alive) {
        ui.close();
      }
    } catch (error) {
      if (alive) {
        setText(status, errorText(error));
        busy = false;
        update();
      }
    } finally {
      if (alive) {busy = false; update();}
    }
  }
  api(`${prefix}/config`).then(config => {
    if (alive) {
      showSettings(config);
    }
  }).catch(error => {
    if (alive) {
      setText(status, errorText(error));
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
