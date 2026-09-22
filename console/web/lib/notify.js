// Toast notifications. Errors ('bad') stay until dismissed; everything else fades after `ms`.
const listeners = new Set();
let items = [];
const MAX = 6;

function emit() { listeners.forEach((f) => f(items)); }

export function notify(text, tone = 'info', ms = 4000) {
  const item = { text, tone, id: Date.now() + Math.random() };
  items = [...items, item].slice(-MAX);
  emit();
  const live = typeof document !== 'undefined' && document.getElementById('live');
  if (live) live.textContent = text;
  if (tone !== 'bad') setTimeout(() => dismiss(item.id), ms);
  return item.id;
}
export function dismiss(id) {
  const next = items.filter((i) => i.id !== id);
  if (next.length !== items.length) { items = next; emit(); }
}
export function onNotify(fn) { listeners.add(fn); return () => listeners.delete(fn); }
