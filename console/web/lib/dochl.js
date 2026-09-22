// Keeps the documentation outlines (lib/doc.js `hl=` tokens) on the elements they name: re-applied after every
// store flush (once the components have re-rendered), on route changes and once after the first render.
import { state, subscribe } from '../store.js';
import { applyHighlights } from './doc.js';

let pending = 0;

function schedule() {
  if (pending) return;
  pending = requestAnimationFrame(() => {
    pending = 0;
    // Preact renders on a microtask after the flush; a second frame lands after that render.
    requestAnimationFrame(() => applyHighlights(state.ui.doc));
  });
}

export function installDocHighlights() {
  const doc = state.ui.doc;
  if (!doc || !doc.active || !doc.hl.length) return () => {};
  const off = subscribe('*', schedule);
  window.addEventListener('hashchange', schedule);
  schedule();
  // Late-mounting panels (data loaded on demand) still get their outline.
  const timer = setInterval(schedule, 1000);
  return () => { off(); window.removeEventListener('hashchange', schedule); clearInterval(timer); };
}
