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

const THEMES = [['dark', '☾', 'Dark'], ['light', '☀', 'Light'], ['system', '◐', 'Match the system']];

// Dark / light / system, top right of the window. Also in Settings › Appearance.
export function ThemeSwitch() {
  const current = state.ui.theme;
  const set = (t) => { state.ui.theme = applyTheme(t); touch('ui'); };
  return html`<span class="theme-switch" role="radiogroup" aria-label="theme" data-doc="topbar.theme">${THEMES.map(([id, glyph, label]) => html`<button role="radio" aria-checked=${current === id ? 'true' : 'false'} title=${`${label} theme`} aria-label=${`${label} theme`} data-doc=${'theme.' + id} onClick=${() => set(id)}>${glyph}</button>`)}</span>`;
}

const SECTIONS = [['devices', 'Devices'], ['register', 'Register'], ['inventory', 'Inventory & database'], ['show', 'Show'], ['showedit', 'Show editor'], ['bench', 'Bench']];

export function SyncButton() {
  const sync = section('sync') || {};
  const [open, setOpen] = useState(useDocOpen('sync.signin'));   // a documentation link opens the sign-in popover
  const [pw, setPw] = useState('');
  const tone = syncTone(sync.tone);
  const needsSignin = sync.status && ['signin', 'unauthorized'].includes(sync.status.state);
  const click = async () => {
    if (needsSignin || !sync.password_known) { setOpen(!open); return; }
    try { await run('sync.run'); notify('Sync started', 'info'); } catch (e) { notify(e.message, 'bad'); }
  };
  const signin = async (e) => {
    e.preventDefault();
    try { await run('sync.signin', { password: pw }); setPw(''); setOpen(false); notify('Checking the password…', 'info'); } catch (x) { notify(x.message, 'bad'); }
  };
  return html`<span class="relative" data-doc="topbar.sync"><button class=${'chip ' + tone} data-doc="sync.run" onClick=${click} disabled=${sync.busy} title=${sync.detail || ''}>${sync.busy ? '⟳ Syncing…' : (sync.text || '⟳ Sync')}</button>
    ${open && html`<form class="popover right" onSubmit=${signin}><label class="lbl">Web inventory password (stored on this computer, never in git)</label>
      <div class="row"><input class="field" type="password" value=${pw} onInput=${(e) => setPw(e.target.value)} autofocus /><button class="btn primary small" data-doc="sync.signin">Sign in</button><button type="button" class="btn small quiet" onClick=${() => setOpen(false)}>Close</button></div>
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
    <nav class="sections" aria-label="sections">${SECTIONS.map(([id, label], i) => html`<button aria-current=${ui.route.section === id ? 'true' : 'false'} title=${`⌘${i + 1}`} onClick=${() => navigate('#/' + id)}>${label}</button>`)}</nav>
    <input id="search" class="search" type="search" placeholder="Search  /  number, MAC, UID" value=${ui.search} onInput=${(e) => setSearch(e.target.value)} />
    <span class="topbar-spacer"></span>
    <${SyncButton} />
    <${ActionButton} name="device.stop" args=${{}} label="■ Stop" title="Stop every active operation (Esc)" className="btn danger small" />
    <button class="btn small quiet narrow-only" onClick=${onToggleSide} aria-pressed=${sideOpen ? 'true' : 'false'} title="attention and jobs">Attention ${total > 0 && html`<span class=${'badge ' + worst}>${total}</span>`}</button>
    <button class="btn small quiet" onClick=${onToggleDock} aria-pressed=${dockOpen ? 'true' : 'false'} title="timeline">${dockOpen ? '▾' : '▴'} Log</button>
    <button class="btn small quiet" onClick=${() => navigate('#/settings')} title="settings (?)" aria-label="settings">⚙</button>
    <${ThemeSwitch} />
  </header>`;
}
