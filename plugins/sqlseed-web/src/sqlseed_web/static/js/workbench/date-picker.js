import { tr, formatDate, setText, setAttr } from '../i18n.js';
import '../i18n/messages/datePicker.js';
// ISO date input with an accessible calendar. The date model stays separate
// from keyboard navigation and invalid text; only a valid choice is emitted.
import { h } from '../api.js';
let nextId = 0;
let activeClose = null;
const weekNames = [tr('datePicker.mon'), tr('datePicker.tue'), tr('datePicker.wed'), tr('datePicker.thu'), tr('datePicker.fri'), tr('datePicker.sat'), tr('datePicker.sun')];
const weekShortNames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map(day => tr(`datePicker.${day}Short`));
const invalidDate = tr('datePicker.invalid');
function dateAt(year, month, day) {
  const value = new Date(0);
  value.setUTCFullYear(year, month, day);
  value.setUTCHours(0, 0, 0, 0);
  return value;
}
function iso(value) {
  return `${String(value.getUTCFullYear()).padStart(4, '0')}-${String(value.getUTCMonth() + 1).padStart(2, '0')}-${String(value.getUTCDate()).padStart(2, '0')}`;
}
function parse(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }
  const result = dateAt(year, month - 1, day);
  return iso(result) === value ? result : null;
}
function today() {
  const current = new Date();
  return dateAt(current.getFullYear(), current.getMonth(), current.getDate());
}
function shiftMonth(value, amount) {
  const first = dateAt(value.getUTCFullYear(), value.getUTCMonth() + amount, 1);
  const lastDay = dateAt(first.getUTCFullYear(), first.getUTCMonth() + 1, 0).getUTCDate();
  return dateAt(first.getUTCFullYear(), first.getUTCMonth(), Math.min(value.getUTCDate(), lastDay));
}

/** onChange receives YYYY-MM-DD or undefined; invalid drafts only notify onValidity. */
export function createDatePicker({
  value = '',
  label = tr('datePicker.label'),
  onChange,
  onValidity
}) {
  const id = `wb-date-${++nextId}`;
  let disposed = false,
    layer = null,
    dialog = null,
    gridBody = null,
    heading = null;
  let yearInput = null,
    monthInput = null,
    jumpError = null,
    focused = null;
  let changedBackground = [];
  const input = h('input', {
    type: 'text',
    value: String(value ?? ''),
    placeholder: 'YYYY-MM-DD',
    autocomplete: 'off',
    spellcheck: 'false',
    'aria-describedby': `${id}-format ${id}-error`
  });
  const trigger = h('button', {
    type: 'button',
    class: 'wb-date-trigger',
    'aria-haspopup': 'dialog',
    'aria-expanded': 'false',
    'aria-controls': id,
    onclick: open
  }, tr('datePicker.calendar'));
  const error = h('small', {
    id: `${id}-error`,
    class: 'wb-date-error',
    role: 'alert'
  });
  const el = h('div', {
    class: 'wb-date-control'
  }, h('div', {
    class: 'wb-date-entry'
  }, h('label', {
    class: 'wb-date-input-label'
  }, h('span', {
    class: 'wb-date-sr'
  }, label), input), trigger), h('small', {
    id: `${id}-format`,
    class: 'wb-date-format'
  }, tr('datePicker.formatHint')), error);
  function check(commit) {
    if (disposed) {
      return false;
    }
    const empty = !input.value.trim(),
      parsed = parse(input.value);
    const message = empty || parsed ? null : invalidDate;
    if (message) {
      setAttr(input, 'aria-invalid', 'true');
    } else {
      input.removeAttribute('aria-invalid');
    }
    setText(error, message || '');
    setAttr(trigger, 'aria-label', parsed ? tr('datePicker.changeDate', {label, date: input.value}) : tr('datePicker.chooseDate', {label}));
    onValidity?.(message, input);
    if (!message && commit && !disposed) {
      onChange?.(empty ? undefined : input.value);
    }
    return !message;
  }
  input.addEventListener('input', () => check(true));
  input.addEventListener('keydown', event => {
    if (event.altKey && event.key === 'ArrowDown') {
      event.preventDefault();
      event.stopPropagation();
      open();
    }
  });
  function setValue(next) {
    input.value = String(next ?? '');
    check(false);
  }
  function close(restoreFocus = true) {
    if (!layer) {
      return;
    }
    layer.remove();
    layer = null;
    dialog = null;
    for (const element of changedBackground) {
      element.inert = false;
    }
    changedBackground = [];
    setAttr(trigger, 'aria-expanded', 'false');
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('focusin', containFocus, true);
    document.removeEventListener('scroll', reposition, true);
    window.removeEventListener('resize', reposition);
    if (activeClose === close) {
      activeClose = null;
    }
    if (restoreFocus && trigger.isConnected && !trigger.disabled && !input.disabled) {
      trigger.focus({preventScroll: true});
    }
  }
  function choose(next) {
    // 日历位于 body 浮层，入口被禁用或销毁后不能借浮层写回旧草稿。
    if (disposed || !el.isConnected || input.disabled || trigger.disabled) {
      close(false);
      return;
    }
    input.value = next ? iso(next) : '';
    check(true);
    close();
  }
  function focusDay() {
    const day = dialog?.querySelector(`[data-date="${iso(focused)}"]`);
    day?.focus();
    day?.scrollIntoView?.({
      block: 'nearest',
      inline: 'nearest'
    });
  }
  function move(next, focus = true) {
    if (next.getUTCFullYear() < 1 || next.getUTCFullYear() > 9999) {
      return;
    }
    focused = next;
    renderGrid();
    if (focus) {
      focusDay();
    }
  }
  function renderGrid() {
    const year = focused.getUTCFullYear(),
      month = focused.getUTCMonth();
    setText(heading, formatDate(dateAt(year, month, 1), {year: 'numeric', month: 'long', timeZone: 'UTC'}));
    yearInput.value = String(year);
    monthInput.value = String(month + 1);
    yearInput.removeAttribute('aria-invalid');
    monthInput.removeAttribute('aria-invalid');
    setText(jumpError, '');
    const first = dateAt(year, month, 1),
      offset = (first.getUTCDay() + 6) % 7;
    const total = dateAt(year, month + 1, 0).getUTCDate(),
      selected = parse(input.value),
      currentDay = iso(today());
    gridBody.replaceChildren();
    for (let row = 0; row < Math.ceil((offset + total) / 7); row++) {
      const tr = h('tr');
      for (let col = 0; col < 7; col++) {
        const number = row * 7 + col - offset + 1;
        if (number < 1 || number > total) {
          tr.append(h('td'));
          continue;
        }
        tr.append(dayCell(year, month, number));
      }
      gridBody.append(tr);
    }
    reposition();
    function dayCell(year, month, number) {
      const date = dateAt(year, month, number),
        key = iso(date),
        isSelected = selected && iso(selected) === key;
      const button = h('button', {
        type: 'button',
        class: `wb-date-day${isSelected ? ' selected' : ''}${key === currentDay ? ' today' : ''}`,
        'data-date': key,
        tabindex: key === iso(focused) ? '0' : '-1',
        'aria-label': formatDate(date, {year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'UTC'}),
        ...(key === currentDay ? {
          'aria-current': 'date'
        } : {}),
        onclick: () => choose(date)
      }, String(number));
      button.addEventListener('focus', () => {
        focused = date;
      });
      return h('td', {
        ...(isSelected ? {
          'aria-selected': 'true'
        } : {})
      }, button);
    }
  }
  function jump() {
    const year = Number(yearInput.value),
      month = Number(monthInput.value);
    const yearValid = /^\d{1,4}$/.test(yearInput.value) && year >= 1 && year <= 9999;
    const monthValid = /^\d{1,2}$/.test(monthInput.value) && month >= 1 && month <= 12;
    if (!yearValid || !monthValid) {
      setAttr(yearInput, 'aria-invalid', String(!yearValid));
      setAttr(monthInput, 'aria-invalid', String(!monthValid));
      setText(jumpError, !yearValid ? tr('datePicker.yearInvalid') : tr('datePicker.monthInvalid'));
      (!yearValid ? yearInput : monthInput).focus();
      return;
    }
    move(dateAt(year, month - 1, Math.min(focused.getUTCDate(), dateAt(year, month, 0).getUTCDate())));
  }
  function open() {
    if (disposed || layer || !el.isConnected || input.disabled || trigger.disabled) {
      return;
    }
    activeClose?.();
    focused = parse(input.value) || today();
    heading = h('h3', {
      id: `${id}-month`,
      'aria-live': 'polite',
      'aria-atomic': 'true'
    });
    const nav = (text, name, amount) => h('button', {
      type: 'button',
      class: 'wb-date-nav',
      'aria-label': name,
      onclick: () => move(shiftMonth(focused, amount), false)
    }, text);
    yearInput = h('input', {
      type: 'number',
      min: '1',
      max: '9999',
      step: '1',
      'data-calendar-year': '',
      'aria-describedby': `${id}-jump-error`
    });
    monthInput = h('input', {
      type: 'number',
      min: '1',
      max: '12',
      step: '1',
      'data-calendar-month': '',
      'aria-describedby': `${id}-jump-error`
    });
    for (const input of [yearInput, monthInput]) {
      input.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          jump();
        }
      });
    }
    jumpError = h('small', {
      id: `${id}-jump-error`,
      class: 'wb-date-error',
      role: 'alert'
    });
    gridBody = h('tbody');
    dialog = h('section', {
      id,
      class: 'wb-date-dialog',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': tr('datePicker.chooseLabel', {label})
    }, h('div', {
      class: 'wb-date-heading'
    }, heading), h('div', {
      class: 'wb-date-navigation'
    }, nav('«', tr('datePicker.previousYear'), -12), nav('‹', tr('datePicker.previousMonth'), -1), h('span', {}, tr('datePicker.navigationHint')), nav('›', tr('datePicker.nextMonth'), 1), nav('»', tr('datePicker.nextYear'), 12)), h('div', {
      class: 'wb-date-jump'
    }, h('label', {}, yearInput, tr('datePicker.year')), h('label', {}, monthInput, tr('datePicker.month')), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: jump
    }, tr('datePicker.jump'))), jumpError, h('table', {
      class: 'wb-date-grid',
      role: 'grid',
      'aria-labelledby': `${id}-month`,
      'aria-describedby': `${id}-keys`
    }, h('thead', {}, h('tr', {}, ...weekNames.map((name, index) => h('th', {
      scope: 'col',
      abbr: name
    }, weekShortNames[index])))), gridBody), h('div', {
      class: 'wb-date-actions'
    }, h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => choose(today())
    }, tr('datePicker.today')), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => choose(null)
    }, tr('datePicker.clear')), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => close()
    }, tr('datePicker.cancel'))), h('p', {
      id: `${id}-keys`,
      class: 'wb-date-help'
    }, tr('datePicker.keyboardHint')));
    layer = h('div', {
      class: 'wb-date-layer'
    }, dialog);
    layer.addEventListener('mousedown', event => {
      if (event.target === layer) {
        close();
      }
    });
    // Only undo changes made by this popup. The parent modal may already own
    // inert page siblings, and may restore them before destroying this editor.
    changedBackground = [...document.body.children].filter(element => !element.inert);
    for (const element of changedBackground) {
      element.inert = true;
    }
    document.body.append(layer);
    setAttr(trigger, 'aria-expanded', 'true');
    activeClose = close;
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('focusin', containFocus, true);
    document.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    renderGrid();
    focusDay();
  }
  function reposition(event) {
    if (!dialog) {
      return;
    }
    if (!el.isConnected) {
      close(false);
      return;
    }
    if (event?.target && dialog.contains(event.target)) {
      return;
    }
    const rect = trigger.getBoundingClientRect(),
      margin = 8,
      gap = 6;
    const viewportWidth = document.documentElement?.clientWidth || innerWidth,
      viewportHeight = document.documentElement?.clientHeight || innerHeight;
    const width = Math.min(340, viewportWidth - margin * 2),
      height = Math.min(dialog.scrollHeight || 430, viewportHeight - margin * 2);
    const below = viewportHeight - rect.bottom - gap - margin;
    const top = below >= height ? rect.bottom + gap : Math.max(margin, rect.top - gap - height);
    Object.assign(dialog.style, {
      position: 'fixed',
      width: `${width}px`,
      maxHeight: `${viewportHeight - margin * 2}px`,
      left: `${Math.max(margin, Math.min(rect.left, viewportWidth - width - margin))}px`,
      top: `${Math.min(top, viewportHeight - height - margin)}px`
    });
  }
  function containFocus(event) {
    if (dialog && !dialog.contains(event.target)) {
      focusDay();
    }
  }
  function onKey(event) {
    if (!dialog) {
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
      return;
    }
    if (event.key === 'Tab') {
      event.preventDefault();
      event.stopImmediatePropagation();
      const controls = [...dialog.querySelectorAll('button,input')].filter(control => !control.disabled && control.getAttribute('tabindex') !== '-1');
      const index = controls.indexOf(document.activeElement),
        direction = event.shiftKey ? -1 : 1;
      controls[(index + direction + controls.length) % controls.length]?.focus();
      return;
    }
    if (!event.target?.dataset.date) {
      return;
    }
    const key = event.key,
      weekday = (focused.getUTCDay() + 6) % 7;
    if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      choose(focused);
      return;
    }
    let next;
    if (key === 'PageUp' || key === 'PageDown') {
      next = shiftMonth(focused, (key === 'PageUp' ? -1 : 1) * (event.shiftKey ? 12 : 1));
    } else {
      const days = {
        ArrowLeft: -1,
        ArrowRight: 1,
        ArrowUp: -7,
        ArrowDown: 7,
        Home: -weekday,
        End: 6 - weekday
      }[key];
      if (days === undefined) {
        return;
      }
      next = dateAt(focused.getUTCFullYear(), focused.getUTCMonth(), focused.getUTCDate() + days);
    }
    event.preventDefault();
    move(next);
  }
  check(false);
  return {
    el,
    input,
    button: trigger,
    setValue,
    destroy() {
      disposed = true;
      close(false);
    }
  };
}
