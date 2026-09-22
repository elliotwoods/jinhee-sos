// Documentation hooks: the hash may carry a query the handover screenshots use
//   #/<section>[/<id>[/<tab>]]?hl=<tokens>&open=<tokens>&dock=1&theme=light|dark&lang=en|ko&still=1&explainers=1&search=<text>
// `hl`/`open` tokens name data-doc attributes: `name` (exact), `name*` (prefix) or `css:<selector>` (raw).
// Pure and node-testable: nothing here touches the DOM at import time.
import { state } from '../store.js';

export const EMPTY = Object.freeze({ hl: [], open: [], dock: false, theme: null, lang: null, still: false, explainers: false, search: '', cube: null });

function tokens(value) {
  return String(value || '').split(',').map((t) => t.trim()).filter(Boolean);
}

function flag(value) {
  return value != null && value !== '' && value !== '0' && value !== 'false' && value !== 'no';
}

// The parsed doc query. Accepts the raw query string with or without its leading `?`.
export function parseDoc(queryString) {
  const q = String(queryString || '').replace(/^[?#]/, '');
  const out = { hl: [], open: [], dock: false, theme: null, lang: null, still: false, explainers: false, search: '', cube: null };
  if (!q) return out;
  const params = new URLSearchParams(q);
  out.hl = tokens(params.get('hl'));
  out.open = tokens(params.get('open'));
  out.dock = flag(params.get('dock'));
  const theme = params.get('theme');
  out.theme = theme === 'light' || theme === 'dark' || theme === 'system' ? theme : null;
  const lang = params.get('lang');
  out.lang = lang === 'en' || lang === 'ko' ? lang : null;   // applied for this page only, like theme
  out.still = flag(params.get('still'));
  out.explainers = flag(params.get('explainers'));
  out.search = params.get('search') || '';
  const cube = parseInt(params.get('cube') || '', 10);
  out.cube = cube > 0 ? cube : null;   // preselects a cube number where a page asks for one (Show, Workstation cubes tab)
  return out;
}

// The CSS selector for one token.
export function docSelector(token) {
  const t = String(token || '').trim();
  if (!t) return null;
  if (t.startsWith('css:')) return t.slice(4);
  const escape = (s) => s.replace(/["\\]/g, '\\$&');
  if (t.endsWith('*')) return `[data-doc^="${escape(t.slice(0, -1))}"]`;
  return `[data-doc="${escape(t)}"]`;
}

let scrolled = false;

// Outline every match of each `hl` token (class doc-hl), drop it from elements no longer matching, and scroll
// the first match into view once per page load.
export function applyHighlights(doc, root = (typeof document !== 'undefined' ? document : null)) {
  if (!root || !doc || !doc.hl || !doc.hl.length) return 0;
  const wanted = new Set();
  for (const token of doc.hl) {
    const selector = docSelector(token);
    if (!selector) continue;
    let matches = [];
    try { matches = root.querySelectorAll(selector); } catch (e) { continue; }
    matches.forEach((el) => wanted.add(el));
  }
  try { root.querySelectorAll('.doc-hl').forEach((el) => { if (!wanted.has(el)) el.classList.remove('doc-hl'); }); } catch (e) { /* no DOM */ }
  let first = null;
  wanted.forEach((el) => { el.classList.add('doc-hl'); if (!first) first = el; });
  if (first && !scrolled && typeof first.scrollIntoView === 'function') {
    scrolled = true;
    try { first.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* ignore */ }
  }
  return wanted.size;
}

// True when the page was opened with this token in `open=`: the initial open/armed/holding state of a control.
export function useDocOpen(token) {
  const doc = (state.ui && state.ui.doc) || EMPTY;
  return !!(doc.open && doc.open.includes(token));
}

export function docCube() {
  const doc = (state.ui && state.ui.doc) || EMPTY;
  return doc.cube || null;
}

export function docStill() {
  const doc = (state.ui && state.ui.doc) || EMPTY;
  return !!doc.still;
}

export function docExplainers() {
  const doc = (state.ui && state.ui.doc) || EMPTY;
  return !!doc.explainers;
}
