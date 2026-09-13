// ISO date input with an accessible calendar. The date model stays separate
// from keyboard navigation and invalid text; only a valid choice is emitted.
import { h } from '../api.js';
let nextId = 0;
let activeClose = null;
const weekNames = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'];
const invalidDate = '日期格式应为 YYYY-MM-DD，且必须是有效日期。';
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
  label = '日期',
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
  }, '日历');
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
  }, 'YYYY-MM-DD · 可输入或从日历选择'), error);
  function check(commit) {
    if (disposed) {
      return false;
    }
    const empty = !input.value.trim(),
      parsed = parse(input.value);
    const message = empty || parsed ? null : invalidDate;
    if (message) {
      input.setAttribute('aria-invalid', 'true');
    } else {
      input.removeAttribute('aria-invalid');
    }
    error.textContent = message || '';
    trigger.setAttribute('aria-label', parsed ? `${label}：更改日期，${input.value}` : `${label}：选择日期`);
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
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('focusin', containFocus, true);
    document.removeEventListener('scroll', reposition, true);
    window.removeEventListener('resize', reposition);
    if (activeClose === close) {
      activeClose = null;
    }
    if (restoreFocus && trigger.isConnected) {
      trigger.focus();
    }
  }
  function choose(next) {
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
    heading.textContent = `${year} 年 ${month + 1} 月`;
    yearInput.value = String(year);
    monthInput.value = String(month + 1);
    yearInput.removeAttribute('aria-invalid');
    monthInput.removeAttribute('aria-invalid');
    jumpError.textContent = '';
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
        tr.append(dayCell(year, month, number, col));
      }
      gridBody.append(tr);
    }
    reposition();
    function dayCell(year, month, number, col) {
      const date = dateAt(year, month, number),
        key = iso(date),
        isSelected = selected && iso(selected) === key;
      const button = h('button', {
        type: 'button',
        class: `wb-date-day${isSelected ? ' selected' : ''}${key === currentDay ? ' today' : ''}`,
        'data-date': key,
        tabindex: key === iso(focused) ? '0' : '-1',
        'aria-label': `${year} 年 ${month + 1} 月 ${number} 日，${weekNames[col]}`,
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
      yearInput.setAttribute('aria-invalid', String(!yearValid));
      monthInput.setAttribute('aria-invalid', String(!monthValid));
      jumpError.textContent = !yearValid ? '年份须为 1–9999 的整数。' : '月份须为 1–12 的整数。';
      (!yearValid ? yearInput : monthInput).focus();
      return;
    }
    move(dateAt(year, month - 1, Math.min(focused.getUTCDate(), dateAt(year, month, 0).getUTCDate())));
  }
  function open() {
    if (disposed || layer) {
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
      'aria-label': `选择${label}`
    }, h('div', {
      class: 'wb-date-heading'
    }, heading, h('button', {
      type: 'button',
      class: 'wb-date-nav',
      'aria-label': '关闭日历',
      onclick: () => close()
    }, '×')), h('div', {
      class: 'wb-date-navigation'
    }, nav('«', '上一年', -12), nav('‹', '上个月', -1), h('span', {}, '按月或按年切换'), nav('›', '下个月', 1), nav('»', '下一年', 12)), h('div', {
      class: 'wb-date-jump'
    }, h('label', {}, yearInput, '年'), h('label', {}, monthInput, '月'), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: jump
    }, '跳转')), jumpError, h('table', {
      class: 'wb-date-grid',
      role: 'grid',
      'aria-labelledby': `${id}-month`,
      'aria-describedby': `${id}-keys`
    }, h('thead', {}, h('tr', {}, ...weekNames.map(name => h('th', {
      scope: 'col',
      abbr: name
    }, name.slice(2))))), gridBody), h('div', {
      class: 'wb-date-actions'
    }, h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => choose(today())
    }, '今天'), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => choose(null)
    }, '清空'), h('button', {
      type: 'button',
      class: 'wb-date-action',
      onclick: () => close()
    }, '取消')), h('p', {
      id: `${id}-keys`,
      class: 'wb-date-help'
    }, '方向键移动 · Home/End 到周首尾 · PageUp/Down 换月，按住 Shift 换年 · Enter 选择 · Esc 关闭'));
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
    trigger.setAttribute('aria-expanded', 'true');
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
