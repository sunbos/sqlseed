import {h, api} from './api.js';
import {button} from './workbench/ui.js';
import {createDropdown} from './dropdown.js';
import {GENERATION_DEFAULTS, readGenerationDefaults, saveGenerationDefaults, validateGenerationDefaults} from './generation-defaults.js';

export function createGenerationDefaultsControl() {
  let saved = readGenerationDefaults(), destroyed = false, loading = false, loaded = false;
  let controller = null, localeOptions = [], providerFacts = {};
  const notice = h('p', {class: 'settings-notice', role: 'status', 'aria-live': 'polite'}, '只用于新建配置；已打开、已保存和导入的配置保持原值。');
  const provider = createDropdown({label: '默认生成引擎', value: saved.provider, options: [
    {value: 'base', label: 'Base'}, {value: 'faker', label: 'Faker'}, {value: 'mimesis', label: 'Mimesis'}], onChange: changed});
  const locale = createDropdown({label: '默认数据语言与地区', value: saved.locale, options: [{value: saved.locale, label: saved.locale}], onChange: changed});
  const count = h('input', {type: 'number', min: '1', max: '1000000', step: '1', value: saved.count, 'aria-label': '默认每表行数', oninput: changed});
  const previewCount = h('input', {type:'number', min:'1', max:'100', step:'1', value:saved.previewCount, 'aria-label':'默认每表预览行数', oninput:changed});
  const seed = h('input', {type:'number', min:'0', max:'4294967295', step:'1', value:saved.seed ?? '', placeholder:'留空，每次重新随机取值', 'aria-label':'默认随机种子', oninput:changed});
  const save = button('保存偏好', persist, {primary: true});
  const reset = button('恢复默认值', () => {
    provider.set(GENERATION_DEFAULTS.provider); locale.set(GENERATION_DEFAULTS.locale); count.value = String(GENERATION_DEFAULTS.count);
    previewCount.value = String(GENERATION_DEFAULTS.previewCount); seed.value = '';
    changed(); notice.textContent = '已恢复表单默认值，保存后用于之后新建的配置。';
  });
  const retry = button('重新读取可用选项', load, {hidden: true});
  const el = h('div', {class: 'settings-generation-control'}, h('div', {class: 'settings-fields'},
    field('数据生成引擎', provider.el), field('数据语言与地区', locale.el), field('每张表的生成行数', count),
    field('每表预览行数', previewCount), field('随机种子（可选）', seed)),
    h('p', {class:'muted'}, '预览行数只影响查看样例。固定随机种子用于复现数据，会写入新配置的每张表；已有记录、引擎或依赖版本变化仍可能影响结果。'),
    h('p', {class: 'muted'}, '保存在当前浏览器；同一浏览器的新配置使用这些初始值。AI 默认模型继续使用「AI 服务」中的设置。'),
    h('div', {class: 'settings-actions'}, save, reset, retry), notice);
  changed();

  function field(label, control) { return h('label', {class: 'settings-field'}, h('span', {}, label), control); }
  function draft() { return {provider: provider.get(), locale: locale.get(), count: Number(count.value), previewCount:Number(previewCount.value), seed:seed.value === '' ? null : Number(seed.value)}; }
  function changed() {
    const value = draft();
    let error = '';
    for (const [input, max, optional] of [[count,1000000,false],[previewCount,100,false],[seed,4294967295,true]]) {
      const valid = optional && input.value === '' || /^\d+$/.test(String(input.value)) && Number(input.value) >= (optional ? 0 : 1) && Number(input.value) <= max;
      input.setAttribute('aria-invalid', String(!valid));
      if (!valid) error = `${input.getAttribute('aria-label')}需为 ${optional ? 0 : 1}–${max.toLocaleString()} 的整数${optional ? '，或留空' : ''}。`;
    }
    try { validateGenerationDefaults(value); } catch (failure) { error ||= failure.message; }
    save.disabled = !loaded || Boolean(error) || JSON.stringify(value) === JSON.stringify(saved);
    if (error) notice.textContent = error;
    else if (loaded && providerFacts[value.provider]?.available === false) notice.textContent = '此引擎当前不可用。可以保存默认值，生成前需在「插件与版本」中安装或修复。';
    else notice.textContent = JSON.stringify(value) === JSON.stringify(saved) ? '默认值已保存；只影响之后新建的配置。' : '有未保存的默认值；保存后用于新建配置。';
  }
  function persist() {
    if (save.disabled) return;
    try {
      if (!localeOptions.some(option => option.value === locale.get())) throw new Error('请选择当前支持的数据语言与地区。');
      saved = saveGenerationDefaults(draft()); changed();
    } catch (error) { notice.textContent = error.message; }
  }
  async function load() {
    if (destroyed || loaded || loading) return;
    loading = true; controller = new AbortController(); retry.hidden = true;
    try {
      const [languages, providers] = await Promise.all([api('/api/meta/locales', {signal: controller.signal}), api('/api/meta/providers', {signal: controller.signal})]);
      if (destroyed) return;
      localeOptions = languages.locales.map(item => ({value: item.code, label: item.label}));
      providerFacts = providers.statuses || {};
      // Keep unavailable stored choices visible; never silently switch their meaning.
      const value = locale.get();
      locale.setOptions(localeOptions.some(item => item.value === value) ? localeOptions : [...localeOptions, {value, label: `${value} · 当前不支持`}], value);
      loaded = true; changed();
    } catch (error) {
      if (!destroyed && error.name !== 'AbortError') {notice.textContent = '无法读取可用选项，请重试。'; retry.hidden = false;}
    } finally { loading = false; }
  }
  return {el, load, close() {provider.close(); locale.close();}, destroy() {destroyed = true; controller?.abort(); provider.destroy(); locale.destroy();}};
}
