// One line of read-only facts at the bottom of the window. No controls: actions live in the top bar and panels.
import { html } from '../lib/html.js';
import { useSections } from '../lib/hooks.js';
import { section, state } from '../store.js';

function Item({ label, value, tone, title }) {
  return html`<span class="status-item" title=${title || ''}><span class="status-label">${label}</span><span class=${'status-value' + (tone ? ' ' + tone + '-text' : '')}>${value}</span></span>`;
}

export function StatusBar() {
  useSections(['link', 'inventory', 'station', 'jobs', 'meta', 'advisor']);
  const inv = section('inventory') || {};
  const st = section('station') || {};
  const meta = section('meta') || {};
  const pub = inv.published || {};
  const counts = inv.counts || {};
  const running = (section('jobs') || []).filter((j) => j.state === 'running').length;
  const stale = state.lastPull && Date.now() - state.lastPull > 6000;
  const link = stale ? ['bad', 'Backend not responding'] : state.connected ? ['ok', 'Connected'] : ['warn', 'Connecting…'];
  const station = !st.present ? ['muted', 'none'] : !st.connected ? ['warn', 'not connected'] : st.reader_ok === false ? ['warn', 'no NFC'] : ['ok', st.mode || 'ready'];
  return html`<footer class="statusbar" role="status" aria-label="status">
    <span class="status-item"><span class=${'dot ' + link[0]}></span><span class=${link[0] === 'ok' ? '' : link[0] + '-text'}>${link[1]}</span></span>
    ${meta.simulate && html`<${Item} label="Mode" value="Simulation" tone="warn" title="Fake boards on a temporary copy of the database" />`}
    <${Item} label="Zone DB" value=${`v${pub.version || 0}${inv.local_differs ? ' · unpublished mappings' : ''}`} tone=${inv.local_differs ? 'warn' : ''} title=${inv.published_error || 'published zone database'} />
    <${Item} label="Cubes" value=${`${counts.total ?? '—'} · ${counts.registered ?? '—'} registered`} />
    <${Item} label="Station" value=${station[1]} tone=${station[0] === 'ok' ? '' : station[0]} />
    <${Item} label="Jobs" value=${running ? `${running} running` : 'idle'} tone=${running ? 'info' : ''} />
    <span class="status-spacer"></span>
    ${meta.console_version && html`<span class="status-item status-faint">${meta.console_version}</span>`}
  </footer>`;
}
