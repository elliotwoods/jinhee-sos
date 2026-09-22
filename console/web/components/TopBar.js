import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useUI, useCopy } from '../lib/hooks.js';
import { section, setSearch, state, touch } from '../store.js';
import { applyTheme } from '../lib/theme.js';
import { syncTone } from '../lib/tones.js';
import { navigate } from '../router.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { ActionButton } from './actions.js';
import { attentionCount } from './Attention.js';
import { useDocOpen } from '../lib/doc.js';
import { t, tk, lang } from '../lib/i18n.js';
import { setLang } from '../store.js';

const THEMES = [['dark', '☾', tk('Dark theme')], ['light', '☀', tk('Light theme')], ['system', '◐', tk('Match the system theme')]];

// Dark / light / system, top right of the window. Also in Settings › Appearance.
export function ThemeSwitch() {
  const current = state.ui.theme;
  const set = (id) => { state.ui.theme = applyTheme(id); touch('ui'); };
  return html`<span class="theme-switch" role="radiogroup" aria-label=${t('theme')} data-doc="topbar.theme">${THEMES.map(([id, glyph, label]) => html`<button role="radio" aria-checked=${current === id ? 'true' : 'false'} title=${t(label)} aria-label=${t(label)} data-doc=${'theme.' + id} onClick=${() => set(id)}>${glyph}</button>`)}</span>`;
}

// EN / KR, right of the theme switch. Also in Settings › Appearance. Labels stay in their own language.
const LANGS = [['en', 'EN', 'English'], ['ko', 'KR', '한국어']];
export function LangSwitch() {
  const current = state.ui.lang;
  return html`<span class="theme-switch lang-switch" role="radiogroup" aria-label="language · 언어" data-doc="topbar.lang">${LANGS.map(([id, text, name]) => html`<button role="radio" aria-checked=${current === id ? 'true' : 'false'} title=${name} aria-label=${name} lang=${id} data-doc=${'lang.' + id} onClick=${() => setLang(id)}>${text}</button>`)}</span>`;
}

const SECTIONS = [['devices', tk('Devices')], ['flash', tk('Flash')], ['register', tk('Register')], ['inventory', tk('Inventory & database')], ['show', tk('Show')], ['showedit', tk('Show editor')], ['bench', tk('Bench')]];

export function SyncButton() {
  const sync = section('sync') || {};
  const [open, setOpen] = useState(useDocOpen('sync.signin'));   // a documentation link opens the sign-in popover
  const [pw, setPw] = useState('');
  const tone = syncTone(sync.tone);
  const needsSignin = sync.status && ['signin', 'unauthorized'].includes(sync.status.state);
  const click = async () => {
    if (needsSignin || !sync.password_known) { setOpen(!open); return; }
    try { await run('sync.run'); notify(t('Sync started'), 'info'); } catch (e) { notify(e.message, 'bad'); }
  };
  const signin = async (e) => {
    e.preventDefault();
    try { await run('sync.signin', { password: pw }); setPw(''); setOpen(false); notify(t('Checking the password…'), 'info'); } catch (x) { notify(x.message, 'bad'); }
  };
  return html`<span class="relative" data-doc="topbar.sync"><button class=${'chip ' + tone} data-doc="sync.run" onClick=${click} disabled=${sync.busy} title=${sync.detail || ''}>${sync.busy ? t('⟳ Syncing…') : (sync.text || '⟳ Sync')}</button>
    ${open && html`<form class="popover right" onSubmit=${signin}><label class="lbl">${t('Web inventory password (stored on this computer, never in git)')}</label>
      <div class="row"><input class="field" type="password" value=${pw} onInput=${(e) => setPw(e.target.value)} autofocus /><button class="btn primary small" data-doc="sync.signin">${t('Sign in')}</button><button type="button" class="btn small quiet" onClick=${() => setOpen(false)}>${t('Close')}</button></div>
      ${sync.last_error && html`<div class="bad-text">${sync.last_error.text}</div>`}</form>`}</span>`;
}

export function TopBar({ onToggleDock, dockOpen, onToggleSide, sideOpen }) {
  useSections(['ui', 'advisor', 'sync']);
  const ui = useUI();
  const c = (section('advisor') || {}).counts || {};
  const worst = c.bad ? 'bad' : c.warn ? 'warn' : 'info';
  const total = attentionCount();
  return html`<header class="topbar">
    <span class="brand">NCT <span class="brand-dim">CONSOLE</span></span>
    <nav class="sections" aria-label=${t('sections')}>${SECTIONS.map(([id, label], i) => html`<button aria-current=${ui.route.section === id ? 'true' : 'false'} title=${lang() === 'ko' ? `EN: ${label} · ⌘${i + 1}` : `⌘${i + 1}`} onClick=${() => navigate('#/' + id)}>${t(label)}</button>`)}</nav>
    <input id="search" class="search" type="search" placeholder=${t('Search  /  number, MAC, UID')} value=${ui.search} onInput=${(e) => setSearch(e.target.value)} />
    <span class="topbar-spacer"></span>
    <${SyncButton} />
    <${ActionButton} name="device.stop" args=${{}} label=${t('■ Stop')} title=${t('Stop every active operation (Esc)')} className="btn danger small" />
    <button class="btn small quiet narrow-only" onClick=${onToggleSide} aria-pressed=${sideOpen ? 'true' : 'false'} title=${t('attention and jobs')}>${t('Attention')} ${total > 0 && html`<span class=${'badge ' + worst}>${total}</span>`}</button>
    <button class="btn small quiet" onClick=${onToggleDock} aria-pressed=${dockOpen ? 'true' : 'false'} title=${t('timeline')}>${dockOpen ? '▾' : '▴'} ${t('Log')}</button>
    <button class="btn small quiet" onClick=${() => navigate('#/settings')} title=${t('settings (?)')} aria-label=${t('settings')}>⚙</button>
    <${ThemeSwitch} />
    <${LangSwitch} />
  </header>`;
}
