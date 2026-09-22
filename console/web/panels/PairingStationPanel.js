import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useCopy, useRouteTab } from '../lib/hooks.js';
import { ledToken } from '../lib/theme.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, ProgressBar, Tabs, Ladder } from '../components/basics.js';
import { ActionButton } from '../components/actions.js';
import { DataTable, LogPane, JobCard } from '../components/data.js';
import { LedRing } from '../components/canvas.js';
import { DeviceHeader, sessionOf, RawConsole, JobHistory, rowByMac } from './common.js';
import { StationBanner, CubeActions, CubeDetail, registrationPill, cubeLevel } from './CubePanel.js';
import { goDevice } from '../router.js';
import { stationEvents } from '../store.js';
import { hhmmss, crc, ago, signalBars } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';

// `device`: the board whose link the relay commands should use (a General Radio beside a pairing
// station); without it they go to the primary link. The table shows the primary registry either way.
export function ZoneRelay({ device }) {
  useSections(['registry', 'inventory', 'settings']);
  const autoOn = !!(section('settings') || {}).auto_zone_db_radio;
  const scope = device && device.id ? { device: device.id } : {};
  const reg = section('registry') || {};
  const inv = section('inventory') || {};
  const pub = reg.published || inv.published || {};
  const p = reg.publishing;
  const [showOut, setShowOut] = useState(false);
  const onUsb = new Set((section('devices') || []).map((d) => d.mac).filter(Boolean));
  // In range: answered within 20 s (the registry's own in_range flag) or on USB here; the rest are hidden by default.
  const near = (z) => !!z.in_range || (z.age_s != null && z.age_s <= 20) || onUsb.has(z.mac);
  const all = reg.zones || [];
  const zones = showOut ? all : all.filter(near);
  const outOfRange = all.length - all.filter(near).length;
  const behind = all.filter((z) => z.in_range && z.state === 'behind');
  const columns = [
    { key: 'name', label: 'Zone', render: (z) => html`<a href="#" onClick=${(e) => { e.preventDefault(); goDevice(zoneId(z)); }}>${z.name || z.mac}</a>` },
    { key: 'zone_label', label: 'Type', render: (z) => (Number(z.zone_type) === 0 ? 'unconfigured' : z.zone_label) }, { key: 'point_id', label: 'Point', render: (z) => (Number(z.zone_type) === 0 ? '—' : z.point_id) }, { key: 'firmware', label: 'Firmware', mono: true },
    { key: 'db_version', label: 'DB', render: (z) => html`v${z.db_version} <${Pill} status=${'zonedb.' + z.state} />` },
    { key: 'rssi', label: 'Signal', render: (z) => signalBars(z.rssi, '—') }, { key: 'age_s', label: 'Seen', render: (z) => z.age_s == null ? 'never' : ago(z.age_s) + ' ago' },
    { key: 'rx_gain', label: 'RX gain', render: (z) => z.rx_gain_pending ? `→ ${z.rx_gain_pending} dB …` : z.rx_gain ? `${z.rx_gain} dB${z.rx_gain_applied ? '' : ' (not applied)'}` : '—' },
    { key: 'error_text', label: 'Error' },
  ];
  return html`<div class="card"><h3>Zone relay (over the air)</h3><${Explainer} id="dongle" />
    <${KeyValue} items=${[['Published database', pub.version ? `v${pub.version} · ${pub.count} records · CRC ${crc(pub.crc)}` : 'nothing published yet'], ['Relay', reg.connected ? 'ready' : 'station not connected or no zone support'], ['Message', reg.message || '—'],
      ['Zones', `${all.filter(near).length} in range · ${outOfRange} out of range${showOut ? ' (shown)' : ' (hidden)'} · ${behind.length} behind`]]} />
    ${p && html`<div class="stack" data-doc="relay.progress"><div class="row"><strong>Publishing v${p.version}</strong> <span class="note">cycle ${p.cycles} · ${p.elapsed_s} s · ${p.pending.length} pending of ${p.expected.length} · ${p.send_failures} send failures</span></div>
      <${ProgressBar} value=${p.expected.length ? 100 * (p.expected.length - p.pending.length) / p.expected.length : 0} />
      <div class="note mono">${p.pending.join(', ')}</div></div>`}
    <div class="row">
      <${ActionButton} name="zones.query" args=${scope} label="Query zones" disabled=${!reg.connected} />
      <label class="check" data-doc="relay.auto"><input type="checkbox" checked=${!!reg.auto_refresh} onChange=${(e) => run('zones.auto_refresh', { ...scope, enabled: e.target.checked }).catch((x) => notify(x.message, 'bad'))} /> auto-refresh (3 s)</label>
      <${ActionButton} name="zones.update_all" args=${scope} label=${`Update all out-of-date zones (${behind.length})`} disabled=${!reg.connected || !behind.length} hazard="One broadcast run for every in-range zone that is behind." />
      <label class="check" title="walkaround" data-doc="zones.walkaround"><input type="checkbox" checked=${autoOn} onChange=${(e) => run('zones.walkaround', { ...scope, enabled: e.target.checked }).catch((x) => notify(x.message, 'bad'))} /> auto-update all (walk the space)${autoOn && !reg.walkaround ? ' · another relay is walking' : ''}</label>
      ${p && html`<${ActionButton} name="zones.stop" args=${scope} label="Stop publishing" className="btn danger small" />`}
      <label class="check" data-doc="relay.show_out"><input type="checkbox" checked=${showOut} onChange=${(e) => setShowOut(e.target.checked)} /> Show out of range (${outOfRange})</label></div>
    <${DataTable} columns=${columns} rows=${zones} keyOf=${(z) => z.mac} doc="relay.table" rowDoc=${(z) => `relay.zone:${z.mac}`} empty=${all.length ? 'Every zone heard is out of range (tick Show out of range)' : 'No zones have answered yet'} /></div>`;
}

export function zoneId(z) {
  const usb = (section('devices') || []).find((d) => d.mac === z.mac);
  return usb ? usb.id : `zone:${z.mac}`;
}

export function DiscoveryGrid() {
  useSections(['inventory', 'station']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.age_s != null && r.role !== 'excluded').sort((a, b) => a.age_s - b.age_s);
  return html`<div class="card"><h3>Cubes heard over the radio (${rows.length})</h3>
    <div class="ring-grid">${rows.map((r) => html`<div key=${r.mac} class="ring-tile" role="link" tabindex="0" onClick=${() => goDevice('cube:' + r.mac)} onKeyDown=${(e) => e.key === 'Enter' && goDevice('cube:' + r.mac)}>
      <${LedRing} size=${90} colour=${ledToken(r)} label=${r.cube_id != null ? `#${r.cube_id}` : '—'} sub=${r.recent ? 'heard' : ago(r.age_s)} blink=${r.telemetry && r.telemetry.command === 'identify'} />
      ${registrationPill(r)}</div>`)}
      </div>${!rows.length && html`<div class="note">No discovery replies yet. Discover runs on connection and every few seconds while idle.</div>`}</div>`;
}

export function PairingStationPanel({ device }) {
  useSections(['station', 'sessions', 'devices']);
  const st = section('station') || {};
  const s = sessionOf(device) || {};
  const hello = st.hello || {};
  const TABS = [['station', 'Pairing'], ['relay', 'Zone relay'], ['console', 'Console']];
  const [tab, setTab] = useRouteTab('station', TABS.map((t) => t[0]));
  const isDongle = st.dongle || hello.nfc_ok === false;
  const title = isDongle ? 'ESP-NOW dongle' : 'Pairing station';
  const nfc = st.connected ? (st.reader_ok ? 'nfc.ok' : 'nfc.bad') : null;
  const pills = html`${st.connected ? html`<${Pill} tone="ok" label="radio ready" />` : html`<${Pill} tone="warn" label=${st.present ? 'not connected' : 'no session'} />`} ${nfc && html`<${Pill} status=${nfc} />`} ${hello.channel != null && html`<${Pill} tone=${hello.channel === 2 ? 'ok' : 'bad'} label=${`channel ${hello.channel}`} />`} ${st.zone_support === false && st.connected && html`<${Pill} tone="warn" label="no zone relay" tip="Station firmware has no zone support; reflash it with nct-pairing-1.8-zones." />`}`;
  return html`<div>
    <${DeviceHeader} device=${device} title=${title} pills=${pills} kv=${[['Firmware', hello.firmware], ['NFC', st.connected ? `${st.reader_ok ? 'ready' : 'unavailable'} · I²C status ${hello.nfc_i2c_status ?? '?'} · PN532 ${hello.nfc_firmware || '?'}` : '—'], ['Tag on reader', st.tag_present ? 'yes (remove it before registering)' : 'clear'], ['Status', st.message], ['Last disconnect', st.last_disconnect]]} />
    <${StationBanner} />
    <${Tabs} tabs=${TABS} current=${tab} onChange=${setTab} />
    ${tab === 'station' && html`<div class="card"><${Explainer} id="station" />
      <div class="row">
        <${ActionButton} name="pairing.discover" args=${{}} label="Discover" disabled=${!st.connected} />
        <${ActionButton} name="pairing.start_pair" args=${{}} label="Pair new cubes (auto)" disabled=${!st.connected || !st.reader_ok || !!st.mode} hazard="Discovers new cubes, flashes each in turn and waits for its tag." />
        ${st.phase === 'paused' && html`<${ActionButton} name="pairing.retry" args=${{}} label="Retry paused" />`}
        ${st.mode && html`<${ActionButton} name="pairing.skip" args=${{}} label="Skip" />`}
        <${ActionButton} name="pairing.stop" args=${{}} label="■ Stop" className="btn danger" disabled=${!st.connected} />
        ${st.connected && !st.reader_ok && html`<${ActionButton} name="station.nfc_recover" args=${{}} label="Recover NFC reader" hazard="I²C bus clear and PN532 re-init; refused while an operation runs." />`}
        <${ActionButton} name="station.nfc_status" args=${{}} label="NFC status" className="btn small" disabled=${!st.connected} /></div>
      <${StationLadder} st=${st} />
      ${st.active && html`<section class="sub"><h3>Current target</h3><${TargetCard} active=${st.active} /></section>`}
      ${st.total ? html`<div class="progress-row"><${ProgressBar} value=${100 * st.progress / st.total} /><span class="note mono">${st.progress} / ${st.total}</span></div>` : null}
      </div>
      <${DiscoveryGrid} />`}
    ${tab === 'relay' && html`<${ZoneRelay} device=${device} />`}
    ${tab === 'console' && html`<div class="card"><h3>Station events (JSON)</h3><${LogPane} items=${stationEvents.items.map((e) => ({ seq: e.seq, t: e.t, text: JSON.stringify(e.event), level: e.event.event === 'error' ? 'bad' : '' }))} height=${300} /></div>`}
    <${JobHistory} device=${device} />
  </div>`;
}

// The registration in flight on the truth ladder: identifying = the flash command went out; registering = the
// mapping is on the radio (delivered when the station's radio ACK arrives); removal = the cube acknowledged.
function StationLadder({ st }) {
  let level = null, failed = false, note = 'no registration in flight';
  const active = st.active || {};
  const t = active.mac && st.telemetry ? st.telemetry[active.mac] || {} : {};
  if (st.mode && ['identifying', 'flashing', 'waiting'].includes(st.phase)) { level = 'sent'; note = 'flashing the cube, waiting for a fresh tag'; }
  else if (st.mode && st.phase === 'registering') { level = t.delivery === 'delivered' ? 'delivered' : 'sent'; note = t.delivery === 'delivered' ? 'radio ACK; waiting for the cube to acknowledge the mapping' : 'mapping sent over the radio'; }
  else if (st.mode && ['removal', 'done', 'registered'].includes(st.phase)) { level = 'acknowledged'; note = 'the cube acknowledged; remove the tag'; }
  else if (st.mode && st.phase === 'paused') { level = 'sent'; failed = true; note = 'no acknowledgment: Retry or Skip'; }
  else if (st.active) { ({ level, note } = cubeLevel(st.active)); }
  return html`<${Ladder} doc="station.ladder" level=${level} failed=${failed} note=${note} />`;
}

function TargetCard({ active }) {
  const row = rowByMac(active.mac) || active;
  return html`<div class="grid2"><div><${LedRing} colour="--led-identify" blink=${true} label=${row.cube_id != null ? `#${row.cube_id}` : '—'} sub="identify" size=${150} /></div><div><${CubeDetail} row=${row} mac=${active.mac} /></div></div>`;
}
