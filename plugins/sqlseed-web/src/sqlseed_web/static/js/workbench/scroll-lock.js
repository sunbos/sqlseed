// Overlapping dialog owners share one lock and restore the original viewport.
let owners = 0;
let saved = null;

export function lockPageScroll() {
  const root = document.documentElement;
  if (owners === 0) {
    const scrolling = document.scrollingElement || root;
    saved = {root, scrolling, locked: root.classList.contains('wb-scroll-locked'),
      top: scrolling.scrollTop, left: scrolling.scrollLeft};
    root.classList.add('wb-scroll-locked');
  }
  owners++;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    owners--;
    if (owners || !saved) return;
    const snapshot = saved;
    saved = null;
    if (!snapshot.locked) snapshot.root.classList.remove('wb-scroll-locked');
    snapshot.scrolling.scrollTop = snapshot.top;
    snapshot.scrolling.scrollLeft = snapshot.left;
  };
}
