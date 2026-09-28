import {tr, joinText, formatNumber, setText, appendContent, replaceContent, UserFacingError, errorText, serverText, serverMessages} from '../i18n.js';
import '../i18n/messages/components.js';
import { h, api } from '../api.js';
import { button, modal } from './ui.js';
const prefix = '/api/settings/plugins';
const managed = new Set(['ai', 'cli', 'mcp', 'mimesis']);
const operationLabels = {install: tr('plugins.install'), uninstall: tr('plugins.uninstall'), update: tr('plugins.update')};
export function componentImpact(id) {
  return {
    ai: tr('plugins.aiImpact'),
    cli: tr('plugins.cliImpact'),
    mcp: tr('plugins.mcpImpact'),
    mimesis: tr('plugins.mimesisImpact')
  }[id] || '';
}
export function createPluginManagement({
  onChange = () => {},
  onMode = () => {},
  onRestored = async () => {},
  initialEnabled = false
}) {
  let active = true,
    version = 0,
    info = {
      enabled: initialEnabled
    },
    pending = false,
    error = '',
    uncertain = false;
  let task = null,
    taskError = '',
    polling = false,
    timer = null,
    review = null,
    reconnects = 0,
    generation = null,
    syncing = false;
  const controllers = new Set();
  const updateEntries = new Set();
  const el = h('section', {
    class: 'settings-management',
    'aria-label': tr('plugins.management')
  }, h('p', {}, tr('plugins.loading')));
  const current = expected => active && expected === version;
  const automatic = () => info?.automatic_lifecycle === true;
  const maintenance = () => Boolean(info?.enabled) && !automatic();
  const busy = () => pending || Boolean(review) || task?.status === 'running';
  const locked = () => busy() || uncertain || syncing || !info?.token || Boolean(info?.restart_required);
  async function request(path, body) {
    const controller = new AbortController();
    controllers.add(controller);
    try {
      return await api(`${prefix}/${path}`, {
        signal: controller.signal,
        ...(body ? {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Sqlseed-Management-Token': info.token
          },
          body: JSON.stringify(body)
        } : {})
      });
    } finally {
      controllers.delete(controller);
    }
  }
  function draw() {
    const outputOpen = Boolean(el.querySelector('[data-plugin-output]')?.open) || task?.status === 'failed';
    const environmentOpen = Boolean(el.querySelector('[data-plugin-environment]')?.open);
    function managementAvailabilityHint() {
      if (automatic()) {
        return serverText(info, 'reason') || tr('plugins.automaticHint');
      } else if (maintenance()) {
        return serverText(info, 'reason') || tr('plugins.manualHint');
      } else {
        return tr('plugins.unavailable');
      }
    }
    replaceContent(el, h('h3', {}, maintenance() ? tr('plugins.maintenance') : tr('plugins.components')), h('p', {}, error || managementAvailabilityHint()));
    if (info?.python_executable) {
      const environment = h('details', {
        class: 'settings-management-environment',
        'data-plugin-environment': ''
      }, h('summary', {}, tr('plugins.environment')), h('p', {
        class: 'mono'
      }, info.python_executable));
      environment.open = environmentOpen;
      appendContent(el, environment);
    }
    if (info?.restart_required && !automatic()) {
      appendContent(el, h('p', {
        class: 'settings-management-restart',
        role: 'status'
      }, task?.status === 'running' ? tr('plugins.maintenanceHint') : tr('plugins.restartRequired')));
    }
    if (pending) {
      appendContent(el, h('p', {
        class: 'settings-notice',
        role: 'status'
      }, tr('plugins.processing')));
    }
    if (task) {
      renderTaskProgress();
    }
    if (automatic() && info?.phase === 'recovery_failed') {
      appendContent(el, button(tr('plugins.recover'), recover, {
        small: true,
        disabled: busy()
      }));
    }
    if (info?.session_restore?.session_lost) {
      appendContent(el, h('p', {
        class: 'settings-management-restart',
        role: 'status'
      }, serverText(info.session_restore) || tr('plugins.sessionLost')));
    }
    if (info?.session_restore?.failed_connections?.length) {
      appendContent(el, h('section', {
        class: 'settings-management-restart',
        role: 'status'
      }, h('strong', {}, tr('plugins.connectionsFailed')), ...info.session_restore.failed_connections.map(item => h('p', {}, serverText(item) || tr('plugins.reconnectHint')))));
    }
    onChange();
    for (const entry of updateEntries) entry.draw();
    function renderTaskProgress() {
      let state;
      if (taskError) {
        if (automatic() && reconnects < 30) {
          state = tr('plugins.reconnecting');
        } else {
          state = tr('plugins.unknownStatus');
        }
      } else {
        state = {
          running: tr('plugins.running'),
          succeeded: tr('plugins.succeeded'),
          failed: tr('plugins.failed')
        }[task.status] || tr('plugins.unknownStatus');
      }
      const progress = h('section', {
        class: 'settings-plugin-task',
        'aria-label': tr('plugins.task'),
        'aria-busy': String(task.status === 'running')
      }, h('h4', {}, joinText([operationLabels[task.action] || tr('plugins.process'), " ", {
        ai: 'AI',
        cli: 'CLI',
        mcp: 'MCP',
        mimesis: 'Mimesis'
      }[task.component_id] || task.component_id, " · ", state])), h('p', {
        role: 'status',
        'aria-live': 'polite'
      }, taskError || serverText(task) || state));
      if (automatic() && task.status === 'running') {
        appendContent(progress, h('ol', {
          class: 'settings-plugin-stages',
          'aria-label': tr('plugins.stages')
        }, ...[['preparing', tr('plugins.prepare')], ['installing', tr('plugins.installStage')], ['restoring', tr('plugins.restore')]].map(([stage, label]) => h('li', {
          'aria-current': task.stage === stage ? 'step' : 'false'
        }, label))));
      }
      if (task.output?.length) {
        const output = h('details', {
          'data-plugin-output': ''
        }, h('summary', {}, tr('plugins.viewOutput')), h('pre', {
          class: 'settings-plugin-output'
        }, joinText(serverMessages(task, 'output'), '\n')));
        output.open = outputOpen;
        appendContent(progress, output);
      }
      if (Number.isInteger(task.returncode) && !automatic()) {
        appendContent(progress, h('p', {
          class: 'muted'
        }, tr('plugins.exitCode', {code: task.returncode})));
      }
      if (taskError && (!automatic() || reconnects >= 30)) {
        appendContent(progress, button(tr('plugins.reloadTask'), poll, {
          small: true,
          disabled: polling
        }));
      }
      appendContent(el, progress);
    }
  }
  async function refresh() {
    if (!active || pending || review) {
      return;
    }
    const expected = ++version;
    pending = true;
    error = '';
    clearTimeout(timer);
    polling = false;
    for (const controller of controllers) {
      controller.abort();
    }
    draw();
    try {
      const response = await request('management');
      if (!current(expected)) {
        return;
      }
      await receiveManagement(response);
    } catch (error_) {
      if (!current(expected)) return;
      error = tr('plugins.loadError', {detail: errorText(error_)});
      if (automatic() && (uncertain || syncing) && ++reconnects < 30) {
        error = tr('plugins.reconnectingResult');
        timer = setTimeout(refresh, 1000);
      }
    } finally {
      if (current(expected)) {
        pending = false;
        draw();
      }
    }
  }
  async function receiveManagement(response) {
    const nextGeneration = response.automatic_lifecycle ? `${response.instance_id}:${response.service_generation}` : null;
    const restored = generation !== null && nextGeneration !== generation && response.phase === 'ready';
    if (nextGeneration !== null) {
      generation = nextGeneration;
    }
    info = response;
    uncertain = false;
    syncing = false;
    error = '';
    taskError = '';
    task = null;
    reconnects = 0;
    onMode(maintenance());
    if (response.active_task) {
      receiveTask(typeof response.active_task === 'string' ? {
        task_id: response.active_task,
        status: 'running'
      } : response.active_task);
    } else if (automatic() && ['preparing', 'installing', 'restoring'].includes(response.phase)) {
      syncing = true;
      timer = setTimeout(refresh, 1000);
    }
    if (restored) {
      await onRestored(response);
    }
  }
  function allowed(id, action) {
    return active && managed.has(id) && info?.enabled && info.available && !error && Boolean(info.components?.find(value => value.id === id)?.[`can_${action}`]);
  }
  async function prepare(id, action) {
    if (locked() || !allowed(id, action)) {
      return;
    }
    const expected = version;
    pending = true;
    error = '';
    draw();
    try {
      const plan = await request('plan', {
        component_id: id,
        action
      });
      if (!current(expected)) {
        return;
      }
      if (!plan.plan_id || plan.component_id !== id || plan.action !== action || !Number.isFinite(plan.expires_in) || plan.expires_in <= 0) {
        throw new UserFacingError(tr('plugins.invalidPlan'));
      }
      if (action === 'update' && (!plan.version || !plan.target_version || !plan.artifact?.filename || !/^[0-9a-f]{64}$/.test(plan.artifact?.sha256 || ''))) {
        throw new UserFacingError(tr('plugins.incompleteUpdatePlan'));
      }
      showReview(plan);
    } catch (error_) {
      if (current(expected)) error = tr('plugins.planError', {detail: errorText(error_)});
    } finally {
      if (current(expected)) {
        pending = false;
        draw();
      }
    }
  }
  function showReview(plan) {
    const operation = operationLabels[plan.action];
    const confirmation = {
      plan,
      expired: false,
      expiresAt: Date.now() + plan.expires_in * 1000,
      dialog: null,
      timer: null
    };
    const dialog = modal(tr('plugins.reviewTitle', {operation}), {
      dismiss: 'footer',
      onClose: () => {
        clearTimeout(confirmation.timer);
        if (review === confirmation) {
          review = null;
        }
        if (active) {
          draw();
        }
      }
    });
    confirmation.dialog = dialog;
    review = confirmation;
    const expiry = h('p', {
      class: 'muted',
      role: 'status'
    }, tr('plugins.expiry', {count: Math.ceil(plan.expires_in / 60), value: formatNumber(Math.ceil(plan.expires_in / 60))}));
    const details = h('dl', {
      class: 'settings-plugin-plan'
    }, h('dt', {}, tr('plugins.component')), h('dd', {
      class: 'mono'
    }, plan.distribution), h('dt', {}, tr('plugins.version')), h('dd', {
      class: 'mono'
    }, plan.action === 'update' ? `${plan.version} → ${plan.target_version}` : plan.version || tr('plugins.compatibleVersion')), h('dt', {}, tr('plugins.targetEnvironment')), h('dd', {
      class: 'mono'
    }, info.python_executable || tr('plugins.currentEnvironment')));
    if (plan.action === 'update') {
      appendContent(dialog.body, h('p', {class: 'settings-component-impact'}, tr('plugins.updateImpact', {from: plan.version, to: plan.target_version})));
      appendContent(details, h('dt', {}, tr('plugins.artifactVerification')), h('dd', {class: 'mono'}, `${plan.artifact?.filename || ''}\nSHA256 ${plan.artifact?.sha256 || ''}`));
      if (plan.dependencies?.length) appendContent(details, h('dt', {}, tr('plugins.keptDependencies')), h('dd', {class: 'mono'}, plan.dependencies.join('\n')));
    }
    appendContent(dialog.body, h('p', {}, automatic() ? joinText([operation, " ", {
      ai: 'AI',
      cli: 'CLI',
      mcp: 'MCP',
      mimesis: 'Mimesis'
    }[plan.component_id] || plan.distribution]) : serverText(plan, 'summary')), ...(plan.action === 'uninstall' && componentImpact(plan.component_id) ? [h('p', {
      class: 'settings-component-impact'
    }, tr('plugins.uninstallImpact', {impact: componentImpact(plan.component_id)}))] : []), automatic() ? h('details', {
      class: 'settings-management-environment'
    }, h('summary', {}, tr('plugins.technicalInfo')), details) : details, h('ul', {
      class: 'settings-plugin-warnings'
    }, ...serverMessages(plan, 'warnings').map(warning => h('li', {}, warning))), expiry);
    const confirm = button(tr('plugins.confirm', {operation}), () => execute(confirmation), {
      primary: true,
      'data-plugin-confirm': ''
    });
    appendContent(dialog.actions, button(tr('plugins.cancel'), dialog.close), confirm);
    confirmation.timer = setTimeout(() => {
      if (!active || review !== confirmation) {
        return;
      }
      confirmation.expired = true;
      confirm.disabled = true;
      setText(expiry, tr('plugins.expiredPlan'));
    }, plan.expires_in * 1000);
  }
  async function execute(confirmation) {
    if (!active || pending || review !== confirmation || confirmation.expired || Date.now() >= confirmation.expiresAt) {
      return;
    }
    const expected = version;
    pending = true;
    error = '';
    uncertain = true;
    confirmation.dialog.close();
    draw();
    try {
      const response = await request('execute', {
        plan_id: confirmation.plan.plan_id
      });
      if (!current(expected)) {
        return;
      }
      receiveTask(response);
      uncertain = false;
    } catch (error_) {
      if (current(expected)) {
        if ([400, 403, 409, 422].includes(error_.status)) {
          uncertain = false;
          error = errorText(error_);
        } else {
          error = tr('plugins.unknownSubmit', {detail: errorText(error_)});
          if (automatic()) timer = setTimeout(refresh, 1000);
        }
      }
    } finally {
      if (current(expected)) {
        pending = false;
        draw();
      }
    }
  }
  function receiveTask(response) {
    if (!response?.task_id || !['running', 'succeeded', 'failed'].includes(response.status)) {
      throw new UserFacingError(tr('plugins.invalidTask'));
    }
    task = response;
    taskError = '';
    reconnects = 0;
    info.restart_required ||= Boolean(task.restart_required);
    clearTimeout(timer);
    if (task.status === 'running') {
      timer = setTimeout(poll, 1000);
    }
  }
  async function poll() {
    if (!active || !task?.task_id || polling) {
      return;
    }
    const expected = version,
      id = task.task_id;
    polling = true;
    clearTimeout(timer);
    try {
      const response = await request(`tasks/${encodeURIComponent(id)}`);
      if (!current(expected) || task?.task_id !== id) {
        return;
      }
      if (response.task_id !== id) {
        throw new UserFacingError(tr('plugins.taskMismatch'));
      }
      receiveTask(response);
      if (automatic() && response.status !== 'running') {
        syncing = true;
        await refresh();
      }
    } catch (error_) {
      showPollingFailure(error_);
    } finally {
      if (current(expected)) {
        polling = false;
        draw();
      }
    }
    function showPollingFailure(error_) {
      if (current(expected) && task?.task_id === id) {
        reconnects++;
        taskError = automatic() && reconnects < 30 ? tr('plugins.reconnectingTask') : tr('plugins.unknownTask', {detail: errorText(error_)});
        if (automatic() && reconnects < 30) timer = setTimeout(poll, 1000);
      }
    }
  }
  async function recover() {
    if (!active || busy() || !automatic() || info.phase !== 'recovery_failed') {
      return;
    }
    const expected = version;
    pending = true;
    error = '';
    draw();
    try {
      const response = await request('recover', {});
      if (current(expected)) {
        await receiveManagement(response);
      }
    } catch (error_) {
      if (current(expected)) {
        error = tr('plugins.unknownRecovery', {detail: errorText(error_)});
        uncertain = true;
        timer = setTimeout(refresh, 1000);
      }
    } finally {
      if (current(expected)) {
        pending = false;
        draw();
      }
    }
  }
  function controls(item) {
    if (!managed.has(item.id) || !info?.enabled || !info.available) {
      return null;
    }
    const component = info.components?.find(value => value.id === item.id);
    if (!component) {
      return null;
    }
    let action;
    if (component.can_install) {
      action = 'install';
    } else if (component.can_uninstall) {
      action = 'uninstall';
    } else {
      action = null;
    }
    let actionButton;
    if (action) {
      actionButton = button(action === 'install' ? tr('plugins.install') : tr('plugins.uninstall'), () => {
        if (actionButton.isConnected) {
          return prepare(item.id, action);
        }
      }, {
        small: true,
        disabled: locked() || Boolean(error),
        'data-plugin-action': action
      });
    } else {
      actionButton = null;
    }
    return h('div', {
      class: 'settings-package-management'
    }, actionButton, !action && component.reason ? h('span', {
      class: 'muted'
    }, serverText(component, 'reason')) : null, component.required_by?.length ? h('span', {
      class: 'muted'
    }, tr('plugins.requiredBy', {components: component.required_by.join(', ')})) : null);
  }
  function updateControls(item) {
    if (!managed.has(item.id) || item.status !== 'update_available') return null;
    let disabled = false;
    const note = h('span', {class: 'muted', role: 'status'});
    const action = button(tr('plugins.viewUpdatePlan'), () => {
      if (action.isConnected && !action.disabled) return prepare(item.id, 'update');
    }, {small: true, 'data-plugin-action': 'update'});
    const holder = h('div', {class: 'settings-package-management'}, action, note);
    const entry = {draw() {
      const component = info.components?.find(value => value.id === item.id);
      const stale = component?.version && component.version !== item.current;
      let reason = error || serverText(info, 'reason') || serverText(component, 'update_reason') || '';
      if (!reason && !info.enabled) reason = tr('plugins.noWebUpdates');
      if (!reason && !info.token) reason = tr('plugins.noToken');
      if (!reason && component && component.can_update === undefined) reason = tr('plugins.oldService');
      action.disabled = disabled || locked() || !allowed(item.id, 'update') || Boolean(stale);
      setText(note, stale ? tr('plugins.staleVersion') : reason);
    }};
    updateEntries.add(entry);
    entry.draw();
    return {el: holder, setDisabled(value) {disabled = Boolean(value); entry.draw();}, destroy() {disabled = true; entry.draw(); updateEntries.delete(entry);}};
  }
  return {
    el,
    refresh,
    controls,
    updateControls,
    get enabled() {
      return Boolean(info?.enabled);
    },
    get automatic() {
      return automatic();
    },
    get maintenance() {
      return maintenance();
    },
    get busy() {
      return busy();
    },
    get refreshBlocked() {
      return pending || Boolean(review);
    },
    destroy() {
      active = false;
      updateEntries.clear();
      version++;
      clearTimeout(timer);
      review?.dialog.close();
      for (const controller of controllers) {
        controller.abort();
      }
    }
  };
}
