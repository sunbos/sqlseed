// 自定义下拉组件：展开时放到当前 overlay，避免 modal-body 的滚动裁切。
// 不用原生 <select> 的原因：原生选项弹层由浏览器 UI 层渲染，在嵌入式
// WebView / IDE 预览浏览器中会出现定位错乱（脱离控件），页面 CSS 无法
// 干预。此组件在任何环境下行为一致。
//
// 用法：
//   const dd = createDropdown({
//     value: 'sqlite',
//     options: [{ value: 'sqlite', label: '本地数据库文件（SQLite）' }, ...],
//     onChange: (v) => { form.kind = v; },
//   });
//   container.append(dd.el);      // 挂载
//   dd.get()                       // 读当前值
//   dd.set(v)                      // 程序化设值（不触发 onChange）
//   dd.setOptions(opts, value?)    // 替换选项（异步数据加载后）

import { h, clear } from './api.js';

let dropdownSequence = 0;

export function createDropdown({ value = '', options = [], onChange, placeholder = '— 选择 —', width, label, labelledBy }) {
  const state = { value: '', options: [], active: -1 };
  const id = `sqlseed-dropdown-${++dropdownSequence}`;
  let itemElements = [], searchText = '', searchTime = 0, destroyed = false;
  let generatedLabel = label || (placeholder === '— 选择 —' ? '选择选项' : placeholder);

  const btn = h('button', { class: 'dropdown-btn', type: 'button', id, role: 'combobox', tabindex: 0,
    'aria-expanded': 'false', 'aria-haspopup': 'listbox', 'aria-controls': `${id}-list`,
    ...(labelledBy ? {'aria-labelledby': labelledBy} : {'aria-label': generatedLabel}),
    onclick: toggle, onkeydown: onKey, onfocus: syncName },
    h('span', { class: 'dropdown-btn-label' }, placeholder));
  const panel = h('div', { class: 'dropdown-panel', id: `${id}-list`, role: 'listbox', 'aria-labelledby': id, hidden: true });
  const el = h('div', { class: 'dropdown' }, btn, panel);
  if (width) el.style.minWidth = width;

  // Keep the caption as the accessible name without letting its native label
  // default action forward a second click to the select-only trigger.
  const onLabelClick = (event) => {
    const wrapper = el.closest('label');
    if (!wrapper || !wrapper.contains(event.target) || el.contains(event.target)) return;
    if (event.target.closest?.('a, button, input, textarea, select')) return;
    event.preventDefault();
  };
  document.addEventListener('click', onLabelClick, true);

  // 关闭面板：点击组件外部或按 Escape。
  const onDocClick = (e) => {
    if (!el.contains(e.target) && !panel.contains(e.target)) close();
  };
  function syncName() {
    // Hosts may name either the trigger or the composite control after creation.
    if (btn.getAttribute('aria-labelledby')) return;
    if (btn.getAttribute('aria-label') !== generatedLabel) return;
    const wrapper = el.closest('label');
    const wrappedLabel = wrapper ? [...wrapper.childNodes].filter(node => node !== el).map(node => node.textContent).join('').trim() : '';
    generatedLabel = el.getAttribute('aria-label') || wrappedLabel || label || generatedLabel;
    btn.setAttribute('aria-label', generatedLabel);
  }

  function onKey(e) {
    if (destroyed || btn.disabled || e.isComposing || e.ctrlKey || e.metaKey) return;
    if (e.target && e.target !== document && !el.contains(e.target) && !panel.contains(e.target)) return;
    const expanded = el.classList.contains('open');
    if (e.key === 'Tab') {
      if (expanded) chooseActive(false);
      return; // Keep the browser's normal forward/backward focus movement.
    }
    if (e.key === 'Escape') {
      if (expanded) {e.preventDefault(); e.stopImmediatePropagation(); close(); btn.focus();}
      return;
    }
    const move = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].includes(e.key);
    const choose = e.key === 'Enter' || e.key === ' ';
    const printable = e.key?.length === 1 && !e.altKey;
    if (!move && !choose && !printable) return;
    if (e.altKey && !['ArrowDown', 'ArrowUp'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    if (choose && expanded) {chooseActive(); return;}
    if (!expanded) open();
    if (choose) return;
    if (e.altKey) {if (e.key === 'ArrowUp') chooseActive(); return;}
    const enabled = enabledIndices();
    const position = enabled.indexOf(state.active);
    if (e.key === 'Home' || (!expanded && e.key === 'ArrowUp')) setActive(enabled[0] ?? -1);
    else if (e.key === 'End') setActive(enabled.at(-1) ?? -1);
    else if (move && (expanded || e.key.startsWith('Page'))) {
      const delta = e.key === 'PageDown' ? 10 : e.key === 'PageUp' ? -10 : e.key === 'ArrowDown' ? 1 : -1;
      setActive(enabled[Math.max(0, Math.min(enabled.length - 1, position + delta))] ?? -1);
    } else if (printable) {
      const now = Date.now();
      searchText = now - searchTime > 700 ? e.key : searchText + e.key;
      searchTime = now;
      const chars = [...searchText.toLocaleLowerCase()];
      const repeated = chars.every(character => character === chars[0]);
      const prefix = repeated ? chars[0] : chars.join('');
      const start = Math.max(0, position + (prefix.length === 1 ? 1 : 0));
      for (let offset = 0; offset < enabled.length; offset++) {
        const index = enabled[(start + offset) % enabled.length];
        if (String(state.options[index].label).toLocaleLowerCase().startsWith(prefix)) {setActive(index); break;}
      }
    }
  }

  function enabledIndices() {return state.options.flatMap((option, index) => option.disabled ? [] : [index]);}

  function resetActive() {
    const selected = state.options.findIndex(option => !option.disabled && option.value === state.value);
    state.active = selected >= 0 ? selected : enabledIndices()[0] ?? -1;
    searchText = ''; searchTime = 0;
  }

  function setActive(index, scroll = true) {
    state.active = index;
    for (let i = 0; i < itemElements.length; i++) {
      const active = i === index && !state.options[i].disabled;
      itemElements[i].classList.toggle('selected', active);
      itemElements[i].setAttribute('aria-selected', String(active));
    }
    if (itemElements[index] && !state.options[index].disabled) {
      btn.setAttribute('aria-activedescendant', itemElements[index].id);
      if (scroll) itemElements[index].scrollIntoView?.({block: 'nearest'});
    } else btn.removeAttribute('aria-activedescendant');
  }

  function chooseActive(restoreFocus = true) {
    const option = state.options[state.active];
    if (!option || option.disabled) {close(); if (restoreFocus) btn.focus(); return;}
    const changed = state.value !== option.value;
    set(option.value); close(); if (restoreFocus) btn.focus();
    if (changed) onChange?.(option.value);
  }

  function open() {
    if (destroyed || btn.disabled || !el.isConnected || el.classList.contains('open')) return;
    syncName(); resetActive();
    el.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    (el.closest('.overlay') || document.body).append(panel);
    panel.classList.add('dropdown-floating');
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('focusin', onDocClick);
    document.addEventListener('keydown', onKey, true);
    renderPanel();
    reposition();
    if (!el.classList.contains('open')) return;
    setActive(state.active);
    btn.focus();
    // 滚动翻页时保持弹层贴住控件。
    document.addEventListener('scroll', reposition, { capture: true, passive: true });
    window.addEventListener('resize', reposition);
  }
  function close() {
    el.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
    btn.removeAttribute('aria-activedescendant');
    panel.hidden = true;
    searchText = ''; searchTime = 0;
    panel.classList.remove('dropdown-floating');
    el.append(panel);
    document.removeEventListener('mousedown', onDocClick);
    document.removeEventListener('focusin', onDocClick);
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('scroll', reposition, { capture: true });
    window.removeEventListener('resize', reposition);
  }
  function toggle() {
    if (el.classList.contains('open')) close(); else open();
  }
  function reposition() {
    // 属性面板被 render() 整体重绘时（切列 / 切生成器 / AI 回填），旧的 dropdown
    // 元素会被丢弃，而 scroll 监听只在 close() 里注销——面板还开着就被丢弃的话，
    // 监听会泄漏下来，之后每次滚动都对已脱离文档的元素求值，并在 WebView 里抛出
    // "Cannot read properties of null (reading 'getBoundingClientRect')"。
    // 断开连接时主动注销，既修泄漏也顺带止住该报错。
    if (!el || !el.isConnected) {
      close();
      return;
    }
    const r = btn.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) { close(); return; }
    const gap = 5, margin = 8;
    const below = Math.max(0, innerHeight - r.bottom - gap - margin);
    const above = Math.max(0, r.top - gap - margin);
    const desired = Math.min(260, panel.scrollHeight || 260);
    const upwards = below < desired && above > below;
    const height = Math.min(desired, upwards ? above : below);
    const menuWidth = Math.min(r.width || r.right - r.left, innerWidth - margin * 2);
    Object.assign(panel.style, {
      position: 'fixed', width: `${menuWidth}px`, maxHeight: `${height}px`,
      left: `${Math.max(margin, Math.min(r.left, innerWidth - menuWidth - margin))}px`,
      right: 'auto', top: `${upwards ? r.top - gap - height : r.bottom + gap}px`,
    });
  }

  function renderPanel() {
    clear(panel);
    itemElements = [];
    if (!state.options.length) {
      btn.removeAttribute('aria-activedescendant');
      panel.append(h('div', { class: 'dropdown-empty muted' }, '（无选项）'));
      return;
    }
    // 选项可带 group 字段（如生成器分类）：组名变化时插入不可点击的组标题。
    // 选项可带 disabled（如 参考工具 有、sqlseed 未实现的占位组）：不可点选。
    let lastGroup = null;
    for (const [index, opt] of state.options.entries()) {
      if (opt.group && opt.group !== lastGroup) {
        lastGroup = opt.group;
        panel.append(h('div', { class: 'dropdown-group', role: 'presentation' }, opt.group));
      }
      const item = h('button', {
        class: `dropdown-item${opt.disabled ? ' disabled' : ''}`,
        type: 'button', id: `${id}-option-${index}`, role: 'option', tabindex: -1,
        'aria-selected': 'false', 'aria-disabled': String(Boolean(opt.disabled)),
        disabled: !!opt.disabled,
        onmousedown: event => event.preventDefault(),
        onmouseenter: opt.disabled ? undefined : () => setActive(index),
        onclick: opt.disabled ? undefined : () => {setActive(index); chooseActive();},
      }, opt.label);
      itemElements.push(item); panel.append(item);
    }
    setActive(state.active, false);
  }

  function renderBtn() {
    const current = state.options.find((o) => o.value === state.value);
    btn.querySelector('.dropdown-btn-label').textContent = current ? current.label : placeholder;
  }

  function set(v) {
    state.value = v;
    renderBtn();
    if (el.classList.contains('open')) { resetActive(); renderPanel(); reposition(); setActive(state.active); }
  }

  function setOptions(opts, v) {
    state.options = opts;
    if (v !== undefined) state.value = v;
    renderBtn();
    if (el.classList.contains('open')) { resetActive(); renderPanel(); reposition(); setActive(state.active); }
  }

  state.value = value;
  state.options = options;
  renderBtn();

  /**
   * 彻底注销监听器。宿主（如 genform）重绘并丢弃本组件时必须调用——
   * 监听只在 close() 里注销，面板开着就被丢弃会泄漏。
   */
  function destroy() {
    destroyed = true;
    close();
    document.removeEventListener('click', onLabelClick, true);
    btn.removeEventListener('keydown', onKey);
    btn.removeEventListener('focus', syncName);
  }

  return { el, get: () => state.value, set, setOptions, destroy };
}
