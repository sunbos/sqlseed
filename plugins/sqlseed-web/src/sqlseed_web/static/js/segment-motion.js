// Decorative selection motion. Call update only after committing the real
// selection; this helper never changes controls, focus or business state.
export function createSegmentIndicator(group, {selected} = {}) {
  const indicator = document.createElement(group.matches('ol,ul') ? 'li' : 'span');
  indicator.className = 'segment-indicator';
  indicator.setAttribute('aria-hidden', 'true');
  indicator.setAttribute('role', 'presentation');
  group.classList.add('segment-motion');
  group.append(indicator);
  const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  let geometry = null;
  let destroyed = false;
  const buttons = [...group.querySelectorAll('button')];
  const current = selected || (() => buttons.find(button =>
    button.getAttribute('aria-pressed') === 'true' || button.getAttribute('aria-current') === 'step'));

  function update({animate = false, resized = false} = {}) {
    if (destroyed) return;
    const target = current();
    const bounds = group.getBoundingClientRect();
    const box = target?.getBoundingClientRect();
    if (!group.isConnected || !target || !group.contains(target) || !box ||
        !Number.isFinite(box.width) || !Number.isFinite(box.height) || box.width <= 0 || box.height <= 0) {
      delete group.dataset.segmentReady;
      delete group.dataset.segmentSlide;
      geometry = null;
      return;
    }
    const next = {
      target,
      x: box.left - bounds.left - (group.clientLeft || 0) + (group.scrollLeft || 0),
      y: box.top - bounds.top - (group.clientTop || 0) + (group.scrollTop || 0),
      width: box.width,
      height: box.height
    };
    if (!resized && geometry && Object.keys(next).every(key => next[key] === geometry[key])) return;
    // CSS transitions continue from their current painted position on reversal.
    // Resizing, restoring a hidden group and first layout align immediately.
    group.dataset.segmentSlide = String(Boolean(animate && !preference?.matches &&
      geometry && next.target !== geometry.target));
    Object.assign(indicator.style, {
      transform: `translate(${next.x}px, ${next.y}px)`,
      width: `${next.width}px`, height: `${next.height}px`
    });
    group.dataset.segmentReady = '';
    geometry = next;
  }
  const align = () => update({resized: true});
  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(align);
  resize?.observe(group);
  buttons.forEach(button => resize?.observe(button));
  window.addEventListener('resize', align);
  preference?.addEventListener?.('change', align);
  update();
  return {
    update,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      resize?.disconnect();
      window.removeEventListener('resize', align);
      preference?.removeEventListener?.('change', align);
      indicator.remove();
      group.classList.remove('segment-motion');
      delete group.dataset.segmentReady;
      delete group.dataset.segmentSlide;
    }
  };
}
