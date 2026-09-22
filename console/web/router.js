// Hash routes: #/devices/<id>[/<tab>], #/register, #/inventory/<tab>, #/show, #/showedit, #/bench, #/settings
import { setRoute, select, state } from './store.js';
import { parseDoc } from './lib/doc.js';

// The hash may carry a documentation query (`#/devices/x/y?hl=…`, see lib/doc.js): it is stripped before the
// path is split, and parsed once at boot into state.ui.doc.
export function splitQuery(hash) {
  const text = hash || '';
  const at = text.indexOf('?');
  return at < 0 ? [text, ''] : [text.slice(0, at), text.slice(at + 1)];
}

export function parse(hash) {
  const [path] = splitQuery(hash);
  const parts = path.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  const section = parts[0] || 'devices';
  if (section === 'devices') return { section, device: parts[1] || null, tab: parts[2] || null };
  if (section === 'inventory') return { section, tab: parts[1] || 'cubes' };
  return { section };
}

export function navigate(path) {
  location.hash = path;
}

export function goDevice(id, tab) { navigate(`#/devices/${encodeURIComponent(id)}${tab ? '/' + encodeURIComponent(tab) : ''}`); }

export function install() {
  const [, query] = splitQuery(location.hash);
  if (query) {
    state.ui.doc = { ...parseDoc(query), active: true };
    if (state.ui.doc.search) state.ui.search = state.ui.doc.search;
    if (state.ui.doc.still && typeof document !== 'undefined') document.documentElement.dataset.still = '1';
  }
  const apply = () => {
    const route = parse(location.hash);
    setRoute(route);
    if (route.section === 'devices' && route.device) select(route.device);
  };
  window.addEventListener('hashchange', apply);
  apply();
  return () => state.ui.route;
}
