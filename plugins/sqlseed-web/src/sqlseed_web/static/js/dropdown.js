// 自定义下拉组件：弹层渲染在页面 DOM 内（absolute 定位、贴控件正下方）。
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

export function createDropdown({ value = '', options = [], onChange, placeholder = '— 选择 —', width }) {
  const state = { value: '', options: [] };

  const btn = h('button', { class: 'dropdown-btn', type: 'button', onclick: toggle },
    h('span', { class: 'dropdown-btn-label' }, placeholder));
  const panel = h('div', { class: 'dropdown-panel' });
  const el = h('div', { class: 'dropdown' }, btn, panel);
  if (width) el.style.minWidth = width;

  // 关闭面板：点击组件外部或按 Escape。
  const onDocClick = (e) => {
    if (!el.contains(e.target)) close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { close(); btn.focus(); }
  };

  function open() {
    el.classList.add('open');
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    renderPanel();
    // 滚动翻页时保持弹层贴住控件。
    document.addEventListener('scroll', reposition, { capture: true, passive: true });
  }
  function close() {
    el.classList.remove('open');
    document.removeEventListener('mousedown', onDocClick);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('scroll', reposition, { capture: true });
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
    // absolute 定位随文档流自动跟随控件，无需计算；仅滚动到视口外时收起。
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) close();
  }

  function renderPanel() {
    clear(panel);
    if (!state.options.length) {
      panel.append(h('div', { class: 'dropdown-empty muted' }, '（无选项）'));
      return;
    }
    // 选项可带 group 字段（如生成器分类）：组名变化时插入不可点击的组标题。
    // 选项可带 disabled（如 Navicat 有、sqlseed 未实现的占位组）：不可点选。
    let lastGroup = null;
    for (const opt of state.options) {
      if (opt.group && opt.group !== lastGroup) {
        lastGroup = opt.group;
        panel.append(h('div', { class: 'dropdown-group' }, opt.group));
      }
      const selected = !opt.disabled && opt.value === state.value;
      panel.append(h('button', {
        class: `dropdown-item${selected ? ' selected' : ''}${opt.disabled ? ' disabled' : ''}`,
        type: 'button',
        disabled: !!opt.disabled,
        onclick: opt.disabled ? undefined : () => { set(opt.value); close(); if (onChange) onChange(opt.value); },
      }, opt.label));
    }
  }

  function renderBtn() {
    const current = state.options.find((o) => o.value === state.value);
    btn.querySelector('.dropdown-btn-label').textContent = current ? current.label : placeholder;
  }

  function set(v) {
    state.value = v;
    renderBtn();
    if (el.classList.contains('open')) renderPanel();
  }

  function setOptions(opts, v) {
    state.options = opts;
    if (v !== undefined) state.value = v;
    renderBtn();
    if (el.classList.contains('open')) renderPanel();
  }

  state.value = value;
  state.options = options;
  renderBtn();

  /**
   * 彻底注销监听器。宿主（如 genform）重绘并丢弃本组件时必须调用——
   * 监听只在 close() 里注销，面板开着就被丢弃会泄漏。
   */
  function destroy() {
    close();
  }

  return { el, get: () => state.value, set, setOptions, destroy };
}
