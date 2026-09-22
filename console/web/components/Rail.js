import { html } from '../lib/html.js';
import { useSections, useUI, useSection } from '../lib/hooks.js';
import { railEntries } from '../lib/rail.js';
import { badge } from '../lib/suggestions.js';
import { goDevice, navigate } from '../router.js';
import { section } from '../store.js';
import { signalBars } from '../lib/format.js';
import { withMacs } from './basics.js';

function Item({ entry, selected }) {
  const advisor = section('advisor') || { suggestions: [] };
  const mac = entry.device ? entry.device.mac : entry.zone ? entry.zone.mac : entry.row ? entry.row.mac : null;
  const b = badge(advisor.suggestions, entry.id, mac);
  let sub = '', dot = 'muted';
  if (entry.device) {
    const d = entry.device;
    sub = d.port.replace('/dev/cu.', '').replace('/dev/', '');
    dot = d.state === 'session' ? 'ok' : d.state === 'job' ? 'info' : d.state === 'foreign' ? 'warn' : d.state === 'probing' ? 'info' : 'muted';
    if (d.role === 'zone' && d.details && d.details.db_version != null) sub += ` · v${d.details.db_version}`;
  } else if (entry.zone) {
    sub = `radio ${signalBars(entry.zone.rssi)} · v${entry.zone.db_version}`;
    dot = entry.zone.state === 'current' ? 'ok' : entry.zone.state === 'behind' ? 'warn' : entry.zone.state === 'ahead' ? 'bad' : 'info';
  } else if (entry.row) {
    sub = entry.row.pinned ? '📌 USB pinned' : 'radio';
    dot = entry.row.recent ? 'ok' : 'muted';
  }
  const go = () => (entry.id === 'computer' ? navigate('#/devices/computer') : goDevice(entry.id));
  return html`<div class=${'rail-item' + (b ? ' sev-' + b.severity : '')} data-doc=${`rail:${entry.id}`} aria-current=${selected ? 'true' : 'false'} onClick=${go} role="link" tabindex="0" onKeyDown=${(e) => e.key === 'Enter' && go()}>
    <span class=${'dot ' + dot}></span><span class="label"><span class="name">${withMacs(entry.label)}</span>${sub && html`<span class="sub">${sub}</span>`}</span>
    ${b && html`<span class=${'badge ' + b.severity}>${b.count}</span>`}</div>`;
}

export function Rail() {
  useSections(['devices', 'inventory', 'registry', 'station', 'advisor', 'ui']);
  const ui = useUI();
  const groups = railEntries(section('devices') || [], section('inventory'), section('registry'), section('station'), ui.search);
  const selected = ui.route.section === 'devices' ? (ui.route.device || null) : null;
  return html`<nav class="rail" aria-label="devices" data-doc="rail">${groups.map((g) => html`<div key=${g.key}>
    <div class="rail-group"><span>${g.title}</span><span>${g.entries.length}</span></div>
    ${g.entries.map((e) => html`<${Item} key=${e.id} entry=${e} selected=${selected === e.id} />`)}</div>`)}
    ${!groups.length && html`<div class="note rail-empty">No devices match.</div>`}</nav>`;
}
