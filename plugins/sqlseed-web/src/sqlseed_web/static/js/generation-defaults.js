// These preferences seed a new document only. Never apply them to a loaded document.
export const GENERATION_DEFAULTS_KEY = 'sqlseed.generation.defaults.v1';
export const GENERATION_DEFAULTS = Object.freeze({provider: 'base', locale: 'en_US', count: 100, previewCount: 10, seed: null});

export function validateGenerationDefaults(value) {
  if (!value || !['base', 'faker', 'mimesis'].includes(value.provider)
      || typeof value.locale !== 'string' || !/^[a-z]{2,3}_[A-Z]{2}$/.test(value.locale)
      || !Number.isSafeInteger(value.count) || value.count < 1 || value.count > 1000000) {
    throw new Error('请选择生成引擎和语言，行数需为 1–1,000,000 的整数。');
  }
  const previewCount = value.previewCount ?? 10, seed = value.seed ?? null;
  if (!Number.isInteger(previewCount) || previewCount < 1 || previewCount > 100) throw new Error('每表预览行数需为 1–100 的整数。');
  if (seed !== null && (!Number.isInteger(seed) || seed < 0 || seed > 4294967295)) throw new Error('随机种子需为 0–4,294,967,295 的整数，或留空。');
  return {provider: value.provider, locale: value.locale, count: value.count, previewCount, seed};
}

export function readGenerationDefaults(fallback = GENERATION_DEFAULTS) {
  try {
    const saved = window.localStorage.getItem(GENERATION_DEFAULTS_KEY);
    if (saved) return validateGenerationDefaults(JSON.parse(saved));
  } catch { /* Private browsing, corrupt or obsolete values retain the existing defaults. */ }
  return {...GENERATION_DEFAULTS, ...Object.fromEntries(Object.entries(fallback).filter(([, value]) => value !== undefined))};
}

export function saveGenerationDefaults(value) {
  const defaults = validateGenerationDefaults(value);
  try {
    window.localStorage.setItem(GENERATION_DEFAULTS_KEY, JSON.stringify(defaults));
  } catch {
    throw new Error('浏览器无法保存偏好，请检查浏览器存储权限后重试。');
  }
  return defaults;
}
