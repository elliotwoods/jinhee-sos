import { useEffect, useState, useRef, useCallback } from 'preact/hooks';
import { state, subscribe, section } from '../store.js';
import { localCopy } from './i18n.js';

// Re-render when any of the named sections (or 'ui', 'timeline', 'link', 'lines:<id>') change.
export function useSections(names) {
  const [, bump] = useState(0);
  useEffect(() => subscribe(names, () => bump((n) => n + 1)), [Array.isArray(names) ? names.join(',') : names]);
}
export function useSection(name) { useSections([name]); return section(name); }
export function useUI() { useSections(['ui']); return state.ui; }
// A device panel's tab, held in the route (#/devices/<id>/<tab>) so it survives reloads and can be linked.
export function useRouteTab(fallback, allowed) {
  const ui = useUI();
  const route = ui.route || {};
  const tab = route.tab && (!allowed || allowed.includes(route.tab)) ? route.tab : fallback;
  const set = (t) => { location.hash = `#/devices/${encodeURIComponent(route.device || '')}/${encodeURIComponent(t)}`; };
  return [tab, set];
}
// uitext copy in the interface language (Korean fields from uitext_ko laid over the English).
export function useCopy() { return localCopy(state.copy) || { panels: {}, status: {}, actions: {}, ladder: {}, glyphs: {} }; }
export function useInterval(fn, ms, deps = []) {
  const ref = useRef(fn); ref.current = fn;
  useEffect(() => { if (!ms) return; const id = setInterval(() => ref.current(), ms); return () => clearInterval(id); }, [ms, ...deps]);
}
export function useAsync() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = useCallback(async (fn) => {
    setBusy(true); setError(null);
    try { return await fn(); } catch (e) { setError(e.message || String(e)); throw e; } finally { setBusy(false); }
  }, []);
  return { busy, error, go, clear: () => setError(null) };
}
