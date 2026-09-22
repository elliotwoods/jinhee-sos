// Interface language: 'en' (default) or 'ko', remembered per machine like the theme. Text generated in Python
// (advisor cards, job stages, device logs, errors) stays English; everything the front end writes goes through t().
// t() is gettext-style: the English literal is the key into ko.js, and a missing entry falls back to English.
import KO from './ko.js';

const KEY = 'nct.lang';
const LANGS = ['en', 'ko'];
const listeners = new Set();
let current = 'en';

export function normalise(lang) { return LANGS.includes(lang) ? lang : 'en'; }
export function lang() { return current; }

export function storedLang() {
  try { return normalise(localStorage.getItem(KEY)); } catch (e) { return 'en'; }
}

// `persist` false applies the language for this page only (a documentation link's ?lang=), leaving the stored choice.
export function applyLang(value, { persist = true } = {}) {
  current = normalise(value);
  if (typeof document !== 'undefined') document.documentElement.lang = current;
  if (persist) { try { localStorage.setItem(KEY, current); } catch (e) { /* private mode */ } }
  listeners.forEach((f) => f(current));
  return current;
}

export function onLangChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

const fill = (text, vars) => (vars ? text.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? String(vars[k]) : m)) : text);

// `en` with {name} placeholders filled from `vars`, in the current language.
export function t(en, vars) {
  const text = current === 'ko' && Object.prototype.hasOwnProperty.call(KO, en) ? KO[en] : en;
  return fill(text, vars);
}

// A tooltip for a button/tab/nav label: in Korean it also names the English label the handover docs quote.
export function hint(en, vars) {
  const english = fill(en, vars);
  const shown = t(en, vars);
  return current === 'ko' && shown !== english ? `${shown} · EN: ${english}` : english;
}

// The copy from uitext (English) with the uitext_ko fields laid over it in Korean. Memoised per copy object.
let merged = { src: null, lang: null, out: null };
export function localCopy(copy) {
  if (!copy || current !== 'ko' || !copy.ko) return copy;
  if (merged.src === copy && merged.lang === current) return merged.out;
  const out = { ...copy };
  for (const group of ['panels', 'status', 'actions']) {
    out[group] = { ...copy[group] };
    for (const [k, v] of Object.entries(copy.ko[group] || {})) out[group][k] = { ...(copy[group] || {})[k], ...v };
  }
  out.ladder = { ...copy.ladder, ...(copy.ko.ladder || {}) };
  out.glossary = { ...copy.glossary, ...(copy.ko.glossary || {}) };
  merged = { src: copy, lang: current, out };
  return out;
}
