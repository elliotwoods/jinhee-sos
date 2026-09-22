// Snapshot sections with versions, an event stream, per-device line rings, and coalesced notifications.
import { Ring } from './lib/ring.js';

const listeners = new Map();   // section name -> Set(fn)
let frame = 0;
const changed = new Set();

export const state = {
  sections: {}, versions: {}, seq: 0, copy: null, commands: {}, connected: false, lastPull: 0, errors: 0,
  ui: { route: { section: 'devices' }, selected: null, search: '', theme: 'dark', dismissedCards: new Set(),
    // The documentation query parsed once at boot (lib/doc.js): hl/open tokens, dock, theme, still, explainers, search.
    doc: { hl: [], open: [], dock: false, theme: null, still: false, explainers: false, search: '', cube: null, active: false } },
};
export const rings = new Map();       // device id -> Ring of {seq,t,dir,text}
export const timeline = new Ring(2000);
export const stationEvents = new Ring(500);

export function ring(device) {
  if (!rings.has(device)) rings.set(device, new Ring(2000));
  return rings.get(device);
}

export function subscribe(names, fn) {
  const list = Array.isArray(names) ? names : [names];
  for (const n of list) {
    if (!listeners.has(n)) listeners.set(n, new Set());
    listeners.get(n).add(fn);
  }
  return () => list.forEach((n) => listeners.get(n)?.delete(fn));
}

export function touch(name) {
  changed.add(name);
  if (!frame) frame = requestAnimationFrame(flush);
}

function flush() {
  frame = 0;
  const names = [...changed];
  changed.clear();
  const fns = new Set();
  for (const n of names) listeners.get(n)?.forEach((f) => fns.add(f));
  listeners.get('*')?.forEach((f) => fns.add(f));
  fns.forEach((f) => { try { f(names); } catch (e) { console.error(e); } });
}

export function applyPull(result) {
  if (!result || result.ok === false) { state.connected = false; state.errors += 1; touch('link'); return; }
  state.connected = true; state.errors = 0; state.lastPull = Date.now();
  for (const [name, entry] of Object.entries(result.sections || {})) {
    state.sections[name] = entry.data;
    state.versions[name] = entry.version;
    touch(name);
  }
  for (const e of result.events || []) {
    if (e.seq <= state.seq) continue;
    state.seq = e.seq;
    if (e.kind === 'line') ring(e.device).push(e);
    else if (e.kind === 'station') { stationEvents.push(e); }
    else timeline.push(e);
    if (e.kind === 'line') touch(`lines:${e.device}`); else touch('timeline');
  }
  touch('link');
}

export function section(name) { return state.sections[name]; }
export function select(id) { state.ui.selected = id; touch('ui'); }
export function setSearch(q) { state.ui.search = q; touch('ui'); }
export function setRoute(route) { state.ui.route = route; touch('ui'); }
