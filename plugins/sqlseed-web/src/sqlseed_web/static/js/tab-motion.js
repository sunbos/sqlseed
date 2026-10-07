// A short selection cue shared by tab groups. Selection and requests remain
// synchronous; no animation owns focus or delays rendering the next panel.
const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
let pending = null;
let running = null;
function clearMotion() {
  if (pending) cancelAnimationFrame(pending.frame);
  pending = null;
  observer?.disconnect();
  const previous = running;
  running = null;
  if (!previous) return;
  previous.animation.cancel();
  previous.marker.remove();
  previous.tab.classList.remove(previous.activeClass);
}
function selectedTarget(id) {
  const target = document.getElementById(id);
  return target?.isConnected && target.getAttribute('aria-selected') === 'true' &&
    target.closest('[role="tablist"]') && !target.disabled ? target : null;
}
const observer = typeof MutationObserver === 'undefined' ? null : new MutationObserver(() => {
  if (pending && !selectedTarget(pending.targetId) || running &&
      (selectedTarget(running.tab.id) !== running.tab || running.marker.parentNode !== running.tab)) {
    clearMotion();
  }
});
function observeTarget() {
  observer?.observe(document.documentElement, {
    childList:true, subtree:true, attributes:true, attributeFilter:['aria-selected', 'disabled']
  });
}
function capture(event) {
  if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
  const requested = event.target.closest?.('[role="tab"]');
  const group = requested?.closest('[role="tablist"]');
  const selected = group?.querySelector('[aria-selected="true"]');
  if (!selected || requested.disabled) return;
  const selectedBox = selected.getBoundingClientRect();
  const painted = running?.group === group && running.tab === selected &&
    running.activeClass === 'tab-motion-active' ? running.marker.getBoundingClientRect() : selectedBox;
  // The underline's vertical position belongs to the tab edge, not its row.
  const from = {left:painted.left, width:painted.width, top:selectedBox.top};
  clearMotion();
  if (preference?.matches || selected === requested || !requested.id) return;
  const targetId = requested.id;
  const frame = requestAnimationFrame(() => {
    pending = null;
    const target = selectedTarget(targetId);
    if (preference?.matches || !target?.animate) {
      clearMotion();
      return;
    }
    const to = target.getBoundingClientRect();
    const vertical = Math.abs(from.top - to.top) > to.height / 2;
    const marker = document.createElement('span');
    marker.className = vertical ? 'tab-motion-surface' : 'tab-motion-marker';
    marker.setAttribute('aria-hidden', 'true');
    const activeClass = vertical ? 'tab-motion-surface-active' : 'tab-motion-active';
    target.classList.add(activeClass);
    target.append(marker);
    // Vertical selection keeps its real surface and label fully visible.
    const animation = vertical ? marker.animate([
      {opacity:.65}, {opacity:0}
    ], {duration:140, easing:'ease-out'}) : marker.animate([
      {transform:`translateX(${from.left-to.left}px)`, width:`${from.width}px`},
      {transform:'translateX(0)', width:`${to.width}px`}
    ], {duration:160, easing:'cubic-bezier(.2,.8,.2,1)'});
    running = {tab:target, group:target.closest('[role="tablist"]'), marker, animation, activeClass};
    animation.onfinish = animation.oncancel = () => {
      if (running?.animation === animation) clearMotion();
    };
  });
  pending = {frame, targetId};
  observeTarget();
}
preference?.addEventListener?.('change', clearMotion);
document.addEventListener('click', capture, true);
document.addEventListener('keydown', capture, true);
