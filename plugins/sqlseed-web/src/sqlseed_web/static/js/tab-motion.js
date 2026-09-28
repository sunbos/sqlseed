// A short selection cue shared by tab groups. Selection and requests remain
// synchronous; no animation owns focus or delays rendering the next panel.
let pendingFrame = null;
let running = null;
function clearRunning() {
  if (!running) return;
  running.animation.cancel();
  running.marker.remove();
  running.tab.classList.remove('tab-motion-active');
  running = null;
}
function capture(event) {
  if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
  const requested = event.target.closest?.('[role="tab"]');
  const group = requested?.closest('[role="tablist"]');
  const selected = group?.querySelector('[aria-selected="true"]');
  if (!selected || requested.disabled || selected === requested || !requested.id) return;
  const from = (running?.tab === selected ? running.marker : selected).getBoundingClientRect();
  const targetId = requested.id;
  if (pendingFrame !== null) cancelAnimationFrame(pendingFrame);
  pendingFrame = requestAnimationFrame(() => {
    pendingFrame = null;
    const target = document.getElementById(targetId);
    if (!target?.isConnected || target.getAttribute('aria-selected') !== 'true' || !target.animate) return;
    const to = target.getBoundingClientRect();
    clearRunning();
    if (Math.abs(from.top - to.top) > to.height / 2) {
      // Vertical navigation retains its existing surface and gets a brief fade.
      target.animate([{opacity:.65}, {opacity:1}], {duration:140, easing:'ease-out'});
      return;
    }
    const marker = document.createElement('span');
    marker.className = 'tab-motion-marker';
    marker.setAttribute('aria-hidden', 'true');
    target.classList.add('tab-motion-active');
    target.append(marker);
    const animation = marker.animate([
      {transform:`translateX(${from.left-to.left}px)`, width:`${from.width}px`},
      {transform:'translateX(0)', width:`${to.width}px`}
    ], {duration:160, easing:'cubic-bezier(.2,.8,.2,1)'});
    running = {tab:target, marker, animation};
    animation.onfinish = () => {if (running?.animation === animation) clearRunning();};
  });
}
document.addEventListener('click', capture, true);
document.addEventListener('keydown', capture, true);
