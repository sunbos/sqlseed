/** Keep Tab navigation inside the caller's already-filtered dialog controls. */
export function cycleFocus(event, controls) {
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
