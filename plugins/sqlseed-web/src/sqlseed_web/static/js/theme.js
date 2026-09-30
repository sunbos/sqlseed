// 在 CSS 前同步加载，使首次绘制即可使用保存的外观偏好。
(() => {
  if (window.sqlseedTheme) return;
  const key = 'sqlseed.theme.preference';
  const valid = value => ['light', 'dark', 'system'].includes(value);
  let storage = null;
  let preference = 'light';
  let media = null;
  try {
    storage = window.localStorage;
    const saved = storage.getItem(key);
    if (valid(saved)) preference = saved;
  } catch {/* 浏览器禁止存储时，工作台仍须正常打开。 */}
  try {
    media = window.matchMedia?.('(prefers-color-scheme: dark)') || null;
  } catch {/* 没有系统信号时，跟随系统回退为浅色。 */}
  let resolved = null;
  function snapshot() {
    return Object.freeze({preference, resolved});
  }
  function apply(next) {
    const previous = preference;
    preference = next;
    const systemColor = media?.matches ? 'dark' : 'light';
    const color = preference === 'system' ? systemColor : preference;
    const changed = previous !== preference || resolved !== color;
    resolved = color;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = preference;
    document.documentElement.style.colorScheme = resolved;
    if (changed) window.dispatchEvent(new CustomEvent('sqlseed:theme-changed', {detail: snapshot()}));
    return snapshot();
  }
  Object.defineProperty(window, 'sqlseedTheme', {value: Object.freeze({
    get: snapshot,
    setPreference(next) {
      if (!valid(next)) throw new TypeError('Unsupported theme preference');
      try {
        storage?.setItem(key, next);
      } catch {/* 无法持久化时仍保留本页选择。 */}
      return apply(next);
    }
  })});
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    if (event.storageArea && storage && event.storageArea !== storage) return;
    // 事件可能晚于另一标签页或本页的新选择；以当前存储值为准，避免旧事件回滚。
    let saved = event.newValue;
    try {
      if (storage) saved = storage.getItem(key);
    } catch {/* 无法读取当前值时，仍可接收此事件携带的偏好。 */}
    apply(valid(saved) ? saved : 'light');
  });
  const systemChanged = () => {
    if (preference === 'system') apply(preference);
  };
  function observeSystemChanges(query, listener) {
    if (!query) return;
    // Older MediaQueryList implementations expose only the one-argument API.
    // Detect the callable capability and preserve its receiver in either case.
    const register = query.addEventListener;
    if (typeof register === 'function') {
      register.call(query, 'change', listener);
      return;
    }
    const legacyRegister = Reflect.get(query, 'addListener');
    if (typeof legacyRegister === 'function') legacyRegister.call(query, listener);
  }
  observeSystemChanges(media, systemChanged);
  apply(preference);
})();
