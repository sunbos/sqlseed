import {tr, formatNumber, setText, setAttr, UserFacingError, errorText, serverText} from './i18n.js';
import './i18n/messages/components.js';
import {h, api} from './api.js';
import {button} from './workbench/ui.js';
import {createDropdown} from './dropdown.js';
import {GENERATION_DEFAULTS, readGenerationDefaults, saveGenerationDefaults, validateGenerationDefaults} from './generation-defaults.js';

export function createGenerationDefaultsControl() {
  let saved = readGenerationDefaults(), destroyed = false, loading = false, loaded = false;
  let controller = null, localeOptions = [], providerFacts = {};
  const notice = h('p', {class: 'settings-notice', role: 'status', 'aria-live': 'polite'}, tr('defaults.hint'));
  const provider = createDropdown({label: tr('defaults.providerAria'), value: saved.provider, options: [
    {value: 'base', label: 'Base'}, {value: 'faker', label: 'Faker'}, {value: 'mimesis', label: 'Mimesis'}], onChange: changed});
  const locale = createDropdown({label: tr('defaults.localeAria'), value: saved.locale, options: [{value: saved.locale, label: saved.locale}], onChange: changed});
  const count = h('input', {type: 'number', min: '1', max: '1000000', step: '1', value: saved.count, 'aria-label': tr('defaults.countAria'), oninput: changed});
  const previewCount = h('input', {type:'number', min:'1', max:'100', step:'1', value:saved.previewCount, 'aria-label':tr('defaults.previewAria'), oninput:changed});
  const seed = h('input', {type:'number', min:'0', max:'4294967295', step:'1', value:saved.seed ?? '', placeholder:tr('defaults.seedPlaceholder'), 'aria-label':tr('defaults.seedAria'), oninput:changed});
  const save = button(tr('defaults.save'), persist, {primary: true});
  const reset = button(tr('defaults.reset'), () => {
    provider.set(GENERATION_DEFAULTS.provider); locale.set(GENERATION_DEFAULTS.locale); count.value = String(GENERATION_DEFAULTS.count);
    previewCount.value = String(GENERATION_DEFAULTS.previewCount); seed.value = '';
    changed(); setText(notice, tr('defaults.resetNotice'));
  });
  const retry = button(tr('defaults.retry'), load, {hidden: true});
  const el = h('div', {class: 'settings-generation-control'}, h('div', {class: 'settings-fields'},
    field(tr('defaults.provider'), provider.el), field(tr('defaults.locale'), locale.el), field(tr('defaults.count'), count),
    field(tr('defaults.preview'), previewCount), field(tr('defaults.seed'), seed)),
    h('p', {class:'muted'}, tr('defaults.previewHint')),
    h('p', {class: 'muted'}, tr('defaults.browserHint')),
    h('p', {class: 'muted'}, tr('defaults.uiLanguageHint')),
    h('div', {class: 'settings-actions'}, save, reset, retry), notice);
  changed();

  function field(label, control) { return h('label', {class: 'settings-field'}, h('span', {}, label), control); }
  function draft() { return {provider: provider.get(), locale: locale.get(), count: Number(count.value), previewCount:Number(previewCount.value), seed:seed.value === '' ? null : Number(seed.value)}; }
  function changed() {
    const value = draft();
    let error = '';
    for (const [input, max, optional, label] of [[count,1000000,false,tr('defaults.countAria')],[previewCount,100,false,tr('defaults.previewAria')],[seed,4294967295,true,tr('defaults.seedAria')]]) {
      const valid = optional && input.value === '' || /^\d+$/.test(String(input.value)) && Number(input.value) >= (optional ? 0 : 1) && Number(input.value) <= max;
      setAttr(input, 'aria-invalid', String(!valid));
      if (!valid) error = tr('defaults.invalidField', {label, min: optional ? 0 : 1, max: formatNumber(max), optional: optional ? tr('defaults.optionalSuffix') : ''});
    }
    try { validateGenerationDefaults(value); } catch (error_) { error ||= errorText(error_); }
    save.disabled = !loaded || Boolean(error) || JSON.stringify(value) === JSON.stringify(saved);
    if (error) setText(notice, error);
    else if (loaded && providerFacts[value.provider]?.available === false) setText(notice, tr('defaults.unavailableEngine'));
    else setText(notice, JSON.stringify(value) === JSON.stringify(saved) ? tr('defaults.saved') : tr('defaults.unsaved'));
  }
  function persist() {
    if (save.disabled) return;
    try {
      if (!localeOptions.some(option => option.value === locale.get())) throw new UserFacingError(tr('defaults.unsupportedLocale'));
      saved = saveGenerationDefaults(draft()); changed();
    } catch (error) { setText(notice, errorText(error)); }
  }
  async function load() {
    if (destroyed || loaded || loading) return;
    loading = true; controller = new AbortController(); retry.hidden = true;
    try {
      const [languages, providers] = await Promise.all([api('/api/meta/locales', {signal: controller.signal}), api('/api/meta/providers', {signal: controller.signal})]);
      if (destroyed) return;
      localeOptions = languages.locales.map(item => ({value: item.code, label: serverText(item, 'label')}));
      providerFacts = providers.statuses || {};
      // Keep unavailable stored choices visible; never silently switch their meaning.
      const value = locale.get();
      locale.setOptions(localeOptions.some(item => item.value === value) ? localeOptions : [...localeOptions, {value, label: tr('defaults.unsupportedOption', {value})}], value);
      loaded = true; changed();
    } catch (error) {
      if (!destroyed && error.name !== 'AbortError') {setText(notice, tr('defaults.loadError')); retry.hidden = false;}
    } finally { loading = false; }
  }
  return {el, load, close() {provider.close(); locale.close();}, destroy() {destroyed = true; controller?.abort(); provider.destroy(); locale.destroy();}};
}
