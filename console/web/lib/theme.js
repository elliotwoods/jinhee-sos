// Theme: dark by default; 'light' pins light, 'system' follows the OS. Canvas code reads colours from the CSS tokens
// through cssVar() so nothing outside styles.css carries a literal colour.
const KEY = 'nct.theme';
const THEMES = ['system', 'dark', 'light'];
const listeners = new Set();
let cache = new Map();

export function normalise(theme) { return THEMES.includes(theme) ? theme : 'dark'; }

export function storedTheme() {
  try { return normalise(localStorage.getItem(KEY)); } catch (e) { return 'dark'; }
}

// `persist` false applies the theme for this page only (a documentation link's ?theme=), leaving the stored choice.
export function applyTheme(theme, { persist = true } = {}) {
  theme = normalise(theme);
  const root = typeof document !== 'undefined' ? document.documentElement : null;
  if (root) { if (theme === 'system') delete root.dataset.theme; else root.dataset.theme = theme; }
  if (persist) { try { localStorage.setItem(KEY, theme); } catch (e) { /* private mode */ } }
  changed();
  return theme;
}

export function onThemeChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

function changed() { cache = new Map(); listeners.forEach((f) => f()); }

if (typeof window !== 'undefined' && window.matchMedia) {
  try { window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', changed); } catch (e) { /* old webview */ }
}

// A token's current value ('--text' → its colour); `fallback` when there is no document (tests) or it is unset.
export function cssVar(name, fallback = '') {
  if (cache.has(name)) return cache.get(name);
  let value = '';
  if (typeof document !== 'undefined' && typeof getComputedStyle === 'function') {
    value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  value = value || fallback;
  if (value) cache.set(name, value);
  return value;
}

// A colour argument that may be a token name ('--chart-1') or a literal hex colour reported by a device.
export function colour(value, fallback = '') {
  if (!value) return fallback;
  return value.startsWith('--') ? cssVar(value, fallback) : value;
}

// The LED ring colour for an inventory row: identify flash, acknowledged (white) or unlit.
export function ledToken(row) {
  if (row && row.telemetry && row.telemetry.command === 'identify') return '--led-identify';
  if (row && row.status === 'acknowledged') return '--led-white';
  return '--led-off';
}
