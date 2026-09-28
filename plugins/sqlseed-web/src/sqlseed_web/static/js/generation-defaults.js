import {tr, UserFacingError} from './i18n.js';
import './i18n/messages/components.js';
// These preferences seed a new document only. Never apply them to a loaded document.
export const GENERATION_DEFAULTS_KEY = 'sqlseed.generation.defaults.v1';
export const GENERATION_DEFAULTS = Object.freeze({provider: 'base', locale: 'en_US', count: 100, previewCount: 10, seed: null});

export function validateGenerationDefaults(value) {
  if (!value || !['base', 'faker', 'mimesis'].includes(value.provider)
      || typeof value.locale !== 'string' || !/^[a-z]{2,3}_[A-Z]{2}$/.test(value.locale)
      || !Number.isSafeInteger(value.count) || value.count < 1 || value.count > 1000000) {
    throw new UserFacingError(tr('defaults.invalidDefaults'));
  }
  const previewCount = value.previewCount ?? 10, seed = value.seed ?? null;
  if (!Number.isInteger(previewCount) || previewCount < 1 || previewCount > 100) throw new UserFacingError(tr('defaults.invalidPreview'));
  if (seed !== null && (!Number.isInteger(seed) || seed < 0 || seed > 4294967295)) throw new UserFacingError(tr('defaults.invalidSeed'));
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
    throw new UserFacingError(tr('defaults.storageError'));
  }
  return defaults;
}
