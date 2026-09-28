import {tr, setText, setAttr, replaceContent, UserFacingError, errorText, appendContent, liveText} from '../i18n.js';
import '../i18n/messages/flow.js';
import { cycleFocus } from "./focus.js";
import { h, get, send, store, rememberConnId, setConnBadge, safeTargetLabel } from '../api.js';
import { lockPageScroll } from './scroll-lock.js';
let activeDialog = null;
let dialogSequence = 0;

/** The same target picker serves first use and connection switching. */
export function openConnectionDialog({
  onConnected,
  workbenchRequest = null
} = {}) {
  function switchConnectionLabel(connection) {
    if (pendingOperation?.kind === 'switch' && pendingOperation.connId === connection.conn_id) {
      return tr("flow.connection.switching");
    } else if (connection.conn_id === store.connId) {
      return tr("flow.connection.current");
    } else {
      return tr("flow.connection.switch");
    }
  }

  activeDialog?.close();
  const previousFocus = document.activeElement;
  const unlockScroll = lockPageScroll();
  const app = document.getElementById('app');
  const previousInert = app?.inert;
  if (app) {
    app.inert = true;
  }
  let closed = false,
    busy = false,
    sequence = 0,
    fileSequence = 0,
    existingSequence = 0,
    kind = 'sqlite';
  let pendingOperation = null;
  let connections = [];
  const fields = {};
  const errorId = `connection-error-${++dialogSequence}`;
  const error = h('p', {
    id: errorId,
    class: 'connection-error',
    role: 'alert',
    tabindex: '-1'
  });
  const notice = h('p', {
    class: 'connection-notice',
    role: 'status',
    'aria-live': 'polite'
  });
  const existing = h('div', {
    class: 'connection-existing'
  });
  const controls = h('div', {
    class: 'connection-fields'
  });
  const browser = h('section', {
    class: 'connection-browser',
    hidden: true,
    'aria-label': tr("flow.files.chooseDatabase")
  });
  const subtitle = h('p', {
    class: 'muted'
  }, tr("flow.connection.intro"));
  const heading = h('h2', { tabindex: '-1' }, tr("flow.connection.connect"));
  const submit = h('button', {
    class: 'btn primary',
    type: 'button',
    onclick: connect
  }, tr("flow.connection.connect"));
  const choices = h('div', {
    class: 'segmented',
    role: 'group',
    'aria-label': tr("flow.connection.kind")
  }, ...['sqlite', 'postgresql'].map(value => h('button', {
    type: 'button',
    class: value === kind ? 'active' : '',
    'aria-pressed': String(value === kind),
    onclick: () => {
      if (busy || kind === value) {
        return;
      }
      clearSecrets();
      kind = value;
      setText(error, '');
      browser.hidden = true;
      fileSequence++;
      for (const button of choices.querySelectorAll('button')) {
        const selected = button.textContent === (kind === 'sqlite' ? 'SQLite' : 'PostgreSQL');
        button.classList.toggle('active', selected);
        setAttr(button, 'aria-pressed', String(selected));
      }
      renderFields();
    }
  }, value === 'sqlite' ? 'SQLite' : 'PostgreSQL')));
  const overlay = h('div', {
    class: 'overlay open wb-overlay connection-overlay',
    onclick: event => {
      if (event.target === overlay) {
        close();
      }
    }
  }, h('section', {
    class: 'modal wb-modal connection-modal',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': tr("flow.connection.connect")
  }, h('header', {
    class: 'modal-head'
  }, heading), h('div', {
    class: 'modal-body connection-body'
  }, subtitle, existing, h('h3', {
    class: 'connection-add-title'
  }, tr("flow.connection.add")), choices, controls, browser, error, notice), h('footer', {
    class: 'modal-footer connection-footer'
  }, h('button', {
    class: 'btn',
    type: 'button',
    onclick: close
  }, tr("flow.action.cancel")), submit)));
  function clearSecrets() {
    if (fields.password) {
      fields.password.value = '';
    }
  }
  function close() {
    if (closed) {
      return;
    }
    closed = true;
    sequence++;
    fileSequence++;
    existingSequence++;
    clearSecrets();
    overlay.remove();
    unlockScroll();
    document.removeEventListener('keydown', keydown);
    if (app) {
      app.inert = previousInert;
    }
    previousFocus?.focus?.({
      preventScroll: true
    });
    if (activeDialog?.close === close) {
      activeDialog = null;
    }
  }
  function field(name, label, value = '', type = 'text') {
    const input = h('input', {
      name,
      value,
      type,
      spellcheck: 'false',
      autocomplete: type === 'password' ? 'current-password' : 'off',
      oninput: () => clearFieldError(input)
    });
    fields[name] = input;
    return h('label', {
      class: 'connection-field'
    }, h('span', {}, label), input);
  }
  function renderFields() {
    for (const name of Object.keys(fields)) {
      delete fields[name];
    }
    if (kind === 'sqlite') {
      replaceContent(controls, field('db_path', tr("flow.connection.file")), h('button', {
        type: 'button',
        class: 'btn',
        onclick: () => {
          browser.hidden = false;
          browseFiles();
        }
      }, tr("flow.connection.chooseFile")));
      setAttr(fields.db_path, 'placeholder', '/path/to/database.sqlite3');
      fields.db_path.classList.add('wb-code');
    } else {
      replaceContent(controls, h('div', {
        class: 'connection-pair'
      }, field('host', tr("flow.connection.host"), 'localhost'), field('port', tr("flow.connection.port"), '5432', 'number')), field('database', tr("flow.connection.database")), h('div', {
        class: 'connection-pair'
      }, field('user', tr("flow.connection.username")), field('password', tr("flow.connection.password"), '', 'password')));
    }
  }
  function setBusy(operation = null) {
    const previous = pendingOperation;
    pendingOperation = operation;
    busy = !!operation;
    submit.disabled = busy;
    setText(submit, operation?.kind === 'add' ? tr("flow.connection.adding") : tr("flow.connection.connect"));
    setAttr(controls, 'aria-busy', String(busy));
    setAttr(existing, 'aria-busy', String(busy));
    if (operation) {
      setText(notice, operation.message);
      fileSequence++;
      browser.hidden = true;
    } else if (notice.textContent === String(previous?.message ?? '')) {
      setText(notice, '');
    }
    for (const input of controls.querySelectorAll('input,button')) {
      input.disabled = busy;
    }
    for (const button of choices.querySelectorAll('button')) {
      button.disabled = busy;
    }
    renderExisting();
  }
  function finishOperation() {
    setBusy();
    // Disabling or replacing the submitting control can send browser focus to
    // body. Recover only lost focus; do not interrupt a user on Cancel.
    const focused = document.activeElement;
    if (error.textContent && (!focused || focused === document.body ||
      focused === document.documentElement || !focused.isConnected)) {
      error.focus();
    }
  }
  function publish(connection) {
    store.connId = connection.conn_id;
    const target = connection.target_label || connection.target;
    store.target = String(target || '').includes('://') ? safeTargetLabel(target) : target;
    store.tables = connection.tables || [];
    rememberConnId(connection.conn_id);
    setConnBadge();
    close();
    window.dispatchEvent(new CustomEvent('sqlseed:connection-changed', {
      detail: {workbenchRequest}
    }));
    onConnected?.({
      conn_id: store.connId,
      target_label: safeTargetLabel(store.target),
      tables: store.tables
    });
  }
  function payload() {
    Object.values(fields).forEach(clearFieldError);
    if (kind === 'sqlite') {
      const dbPath = fields.db_path.value.trim();
      if (!dbPath) {
        invalidFields(['db_path'], tr("flow.connection.pathRequired"));
      }
      // A connection is an adapter target. Generator defaults belong to the
      // document; BaseProvider keeps connecting independent of optional extras.
      return {
        db_path: dbPath,
        require_existing: true,
        provider: 'base'
      };
    }
    const hostname = fields.host.value.trim(),
      database = fields.database.value.trim(),
      user = fields.user.value.trim();
    const port = fields.port.value.trim();
    if (!hostname || !database || !user) {
      invalidFields(['host', 'database', 'user'].filter(name => !fields[name].value.trim()), tr("flow.connection.fieldsRequired"));
    }
    if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
      invalidFields(['port'], tr("flow.connection.portInvalid"));
    }
    const host = hostname.includes(':') && !hostname.startsWith('[') ? `[${hostname}]` : hostname;
    return {
      url: `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(fields.password.value)}@${host}:${port}/${encodeURIComponent(database)}`,
      provider: 'base'
    };
  }
  function clearFieldError(input) {
    if (input.getAttribute('aria-invalid') !== 'true') return;
    input.removeAttribute('aria-invalid');
    input.removeAttribute('aria-describedby');
    if (!Object.values(fields).some(field => field.getAttribute('aria-invalid') === 'true')) setText(error, '');
  }
  function invalidFields(names, message) {
    for (const name of names) {
      setAttr(fields[name], 'aria-invalid', 'true');
      setAttr(fields[name], 'aria-describedby', errorId);
    }
    fields[names[0]].focus({preventScroll: true});
    throw new UserFacingError(message);
  }
  async function connect() {
    if (closed || busy) {
      return;
    }
    setText(error, '');
    let data;
    try {
      data = payload();
    } catch (error_) {
      setText(error, errorText(error_));
      return;
    }
    const expected = ++sequence;
    setBusy({
      kind: 'add',
      message: tr("flow.connection.waitDatabase")
    });
    try {
      const connection = await send('/api/connections', data);
      if (!closed && expected === sequence) {
        publish(connection);
      }
    } catch (error_) {
      if (!closed && expected === sequence) setText(error, connectionError(errorText(error_)));
    } finally {
      clearSecrets();
      if (!closed && expected === sequence) {
        finishOperation();
      }
    }
  }
  async function useConnection(connection) {
    if (closed || busy || connection.conn_id === store.connId) {
      return;
    }
    const expected = ++sequence;
    setText(error, '');
    setBusy({
      kind: 'switch',
      connId: connection.conn_id,
      message: tr("flow.connection.readingSchema", {target: safeTargetLabel(connection.target_label || connection.target)})
    });
    try {
      const detail = await get(`/api/connections/${encodeURIComponent(connection.conn_id)}/tables`);
      if (!closed && expected === sequence) {
        publish({
          ...detail,
          conn_id: connection.conn_id
        });
      }
    } catch (error_) {
      if (!closed && expected === sequence) setText(error, connectionError(errorText(error_)));
    } finally {
      if (!closed && expected === sequence) {
        finishOperation();
      }
    }
  }
  async function disconnect(connection) {
    if (closed || busy) {
      return;
    }
    const expected = ++sequence;
    existingSequence++;
    setText(error, '');
    setBusy({
      kind: 'disconnect',
      connId: connection.conn_id,
      message: tr("flow.connection.disconnectingTarget", {target: safeTargetLabel(connection.target_label || connection.target)})
    });
    try {
      await send(`/api/connections/${encodeURIComponent(connection.conn_id)}`, undefined, 'DELETE');
      // The server close still took place if the dialog was closed meanwhile.
      // Clear only the removed current session, never a more recent selection.
      if (store.connId === connection.conn_id) {
        store.connId = null;
        store.target = null;
        store.tables = [];
        rememberConnId('');
        setConnBadge();
        window.dispatchEvent(new Event('sqlseed:connection-changed'));
      }
      if (!closed && expected === sequence) {
        connections = connections.filter(item => item.conn_id !== connection.conn_id);
        setText(notice, tr("flow.connection.disconnectedTarget", {target: safeTargetLabel(connection.target_label || connection.target)}));
        renderExisting();
      }
    } catch (error_) {
      if (!closed && expected === sequence) setText(error, connectionError(errorText(error_)));
    } finally {
      if (!closed && expected === sequence) {
        finishOperation();
      }
    }
  }
  function renderExisting() {
    if (!connections.length) {
      replaceContent(existing);
      return;
    }
    const groups = new Map();
    for (const connection of connections) {
      const key = connection.group_key || connection.target || connection.conn_id;
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(connection);
    }
    replaceContent(existing, h('h3', {
      class: 'connection-label'
    }, tr("flow.connection.list")), h('p', {
      class: 'muted connection-session-help'
    }, tr("flow.connection.switchHelp")), ...[...groups.values()].map(group => {
      const target = group[0].target_label || group[0].target;
      return h('section', {
        class: 'connection-group'
      }, h('header', {
        class: 'connection-group-heading'
      }, h('strong', {}, safeTargetLabel(target)), h('small', {}, tr("flow.connection.sessions", {count: group.length}))), h('p', {
        class: 'mono connection-target'
      }, targetDescription(target)), ...group.map((connection, index) => h('div', {
        class: 'connection-session'
      }, h('button', {
        class: 'connection-card',
        type: 'button',
        disabled: busy || connection.conn_id === store.connId,
        onclick: () => useConnection(connection),
        'aria-label': tr("flow.connection.sessionLabel", {action: connection.conn_id === store.connId ? tr("flow.connection.current") : tr("flow.connection.switchTo"), target: safeTargetLabel(target), number: index + 1})
      }, h('span', {}, tr("flow.connection.session", {number: index + 1})), h('small', {}, switchConnectionLabel(connection))), h('button', {
        class: 'btn small connection-disconnect',
        type: 'button',
        disabled: busy,
        'aria-label': tr("flow.connection.disconnectLabel", {target: safeTargetLabel(target), number: index + 1}),
        onclick: () => disconnect(connection)
      }, pendingOperation?.kind === 'disconnect' && pendingOperation.connId === connection.conn_id ? tr("flow.connection.disconnecting") : tr("flow.connection.disconnect")))));
    }));
  }
  async function loadExisting() {
    const expected = ++existingSequence;
    try {
      const response = await get('/api/connections');
      if (closed || expected !== existingSequence) {
        return;
      }
      connections = response.connections || [];
      renderExisting();
    } catch (error_) {
      if (!closed && expected === existingSequence) replaceContent(existing, h('p', {
        class: 'muted'
      }, tr("flow.connection.listUnavailable", {detail: connectionError(errorText(error_))})));
    }
  }
  async function browseFiles(path) {
    if (closed || busy) {
      return;
    }
    const expected = ++fileSequence;
    replaceContent(browser, h('p', {
      role: 'status'
    }, tr("flow.files.reading")));
    try {
      const response = await get(`/api/fs/browse${path ? "?path=" + encodeURIComponent(path) : ''}`);
      if (closed || expected !== fileSequence) {
        return;
      }
      const pathInput = h('input', {
        class: 'wb-code',
        value: response.path,
        'aria-label': tr("flow.files.path"),
        spellcheck: 'false'
      });
      const go = () => browseFiles(pathInput.value.trim());
      pathInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          go();
        }
      });
      replaceContent(browser, h('div', {
        class: 'connection-file-path'
      }, pathInput, h('button', {
        class: 'btn small',
        type: 'button',
        onclick: go
      }, tr("flow.files.go")), h('button', {
        class: 'btn small',
        type: 'button',
        disabled: !response.parent,
        onclick: () => browseFiles(response.parent)
      }, tr("flow.files.parent"))), h('div', {
        class: 'connection-file-list'
      }, ...response.entries.map(entry => h('button', {
        type: 'button',
        class: `connection-file${entry.is_dir ? ' directory' : ''}`,
        onclick: () => {
          if (entry.is_dir) {
            browseFiles(entry.path);
          } else {
            fields.db_path.value = entry.path;
            clearFieldError(fields.db_path);
            browser.hidden = true;
            fileSequence++;
            fields.db_path.focus();
          }
        }
      }, entry.name))), ...(response.entries.length ? [] : [h('p', {
        class: 'muted'
      }, tr("flow.files.noDatabase"))]));
    } catch (error_) {
      if (!closed && expected === fileSequence) replaceContent(browser, h('p', {
        role: 'alert',
        class: 'connection-error'
      }, connectionError(errorText(error_))), h('button', {
        type: 'button',
        class: 'btn small',
        onclick: () => browseFiles()
      }, tr("flow.files.returnHome")));
    }
  }
  function keydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
    if (event.key !== 'Tab') {
      return;
    }
    const candidates = [...overlay.querySelectorAll('button,input,a[href]')].filter(element => !element.disabled && !element.closest('[hidden]'));
    cycleFocus(event, candidates);
  }
  renderFields();
  appendContent(document.body, overlay);
  document.addEventListener('keydown', keydown);
  heading.focus({ preventScroll: true });
  activeDialog = {
    close
  };
  loadExisting();
  return activeDialog;
}
function targetDescription(target) {
  const text = String(target || '');
  if (!text.includes('://')) {
    return text;
  }
  try {
    const url = new URL(text);
    return `${url.protocol}//${url.host}${decodeURIComponent(url.pathname)}`;
  } catch {
    return tr("flow.connection.title");
  }
}
function connectionError(message) {
  return liveText(() => {
  const parts = String(message || tr("flow.connection.failed")).split('://');
  for (let index = 1; index < parts.length; index++) {
    const authority = parts[index],
      at = authority.indexOf('@');
    if (at > 0 && !/[\s/]/.test(authority.slice(0, at))) {
      parts[index] = '[credentials]' + authority.slice(at);
    }
  }
  return parts.join('://').replace(/((?:password|sslpassword|token|secret|api_key)=)[^&\s'")]+/gi, '$1[redacted]');
  });
}
