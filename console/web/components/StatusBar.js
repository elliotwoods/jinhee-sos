// One line of read-only facts at the bottom of the window. No controls: actions live in the top bar and panels.
import { html } from '../lib/html.js';
import { useSections } from '../lib/hooks.js';
import { section, state } from '../store.js';
import { t } from '../lib/i18n.js';

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
  const link = stale ? ['bad', t('Backend not responding')] : state.connected ? ['ok', t('Connected')] : ['warn', t('Connecting…')];
  const station = !st.present ? ['muted', t('none')] : !st.connected ? ['warn', t('not connected')] : st.reader_ok === false ? ['warn', t('no NFC')] : ['ok', st.mode || t('ready')];
  return html`<footer class="statusbar" role="status" aria-label=${t('status')}>
    <span class="status-item"><span class=${'dot ' + link[0]}></span><span class=${link[0] === 'ok' ? '' : link[0] + '-text'}>${link[1]}</span></span>
    ${meta.simulate && html`<${Item} label=${t('Mode')} value=${t('Simulation')} tone="warn" title=${t('Fake boards on a temporary copy of the database')} />`}
    <${Item} label=${t('Zone DB')} value=${`v${pub.version || 0}${inv.local_differs ? ' · ' + t('unpublished mappings') : ''}`} tone=${inv.local_differs ? 'warn' : ''} title=${inv.published_error || t('published zone database')} />
    <${Item} label=${t('Cubes')} value=${t('{total} · {registered} registered', { total: counts.total ?? '—', registered: counts.registered ?? '—' })} />
    <${Item} label=${t('Station')} value=${station[1]} tone=${station[0] === 'ok' ? '' : station[0]} />
    <${Item} label=${t('Jobs')} value=${running ? t('{n} running', { n: running }) : t('idle')} tone=${running ? 'info' : ''} />
    <span class="status-spacer"></span>
    ${meta.console_version && html`<span class="status-item status-faint">${meta.console_version}</span>`}
  </footer>`;
}
