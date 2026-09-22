import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useSections, useRouteTab } from '../lib/hooks.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, StatTile, Tabs } from '../components/basics.js';
import { ActionButton, HoldButton, LeaseToggle } from '../components/actions.js';
import { MemberGrid } from '../components/canvas.js';
import { DeviceHeader, sessionOf, RawConsole, JobHistory, rowByMac } from './common.js';
import { StationBanner } from './CubePanel.js';
import { ZoneRelay, DiscoveryGrid } from './PairingStationPanel.js';
import { ShowControl } from './ShowSection.js';
import { ago, hhmmss } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';

const ZONES = [[0, 'idle'], [1, 'preshow'], [2, 'desert'], [3, 'pool'], [4, 'mainshow']];

function CubeColours({ device, s }) {
  useSections(['inventory', 'station']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.role !== 'excluded' && (r.cube_id != null || r.age_s != null));
  const [mac, setMac] = useState('');
  const [zone, setZone] = useState(4);
  const live = device.state === 'session' && s.connected;
  const chosen = rows.find((r) => r.mac === mac);
  return html`<div class="card"><${Explainer} id="generalradio.cubes" />
    <div class="row"><label class="lbl">Cube</label>
      <select class="field" value=${mac} onChange=${(e) => setMac(e.target.value)}>
        <option value="">choose a cube…</option>
        ${rows.map((r) => html`<option value=${r.mac}>${r.cube_id != null ? `#${r.cube_id}` : 'no number'} · ${r.mac}${r.recent ? ' · heard' : ''}</option>`)}
      </select>
      <label class="lbl">Zone</label>
      <select class="field" value=${zone} onChange=${(e) => setZone(Number(e.target.value))}>${ZONES.map(([v, n]) => html`<option value=${v}>${v} · ${n}</option>`)}</select>
      <${ActionButton} name="radio.set_zone" args=${{ device: device.id, mac, zone }} label=${`Set ${chosen && chosen.cube_id != null ? '#' + chosen.cube_id : 'cube'} → ${ZONES[zone][1]}`} disabled=${!live || !mac} hazard="Unicast SET_ZONE ×3; the cube's radio ACK is not a colour change." />
      <${ActionButton} name="radio.show_start" args=${{ device: device.id, cube: mac }} label="Start show on this cube" disabled=${!live || !mac} hazard="MSG_SHOW_START with a fresh showId ×5; only a mainshow-ready cube starts." />
    </div>
    <div class="row">
      <${HoldButton} name="radio.set_zone_all" args=${{ device: device.id, zone }} label=${`ALL cubes in range → ${ZONES[zone][1]} (hold)`} disabled=${!live} hazard="Broadcast SET_ZONE: recolours every cube that hears it, with no acknowledgment." />
      <${HoldButton} name="radio.show_start_all" args=${{ device: device.id }} label="Start show on ALL ready cubes (hold)" disabled=${!live} hazard="Broadcast SHOW_START, no acknowledgment; cannot be undone." />
    </div>
    <div class="row">
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac] }} label="Identify (flash until Stop)" disabled=${!live || !mac} hazard="The cube blinks blue/red until Stop; it is returned to idle afterwards." />
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac], sequential: true }} label="Flash 2 s" disabled=${!live || !mac} hazard="A two-second blue/red flash on the cube, then idle." />
      <${ActionButton} name="radio.stop" args=${{ device: device.id }} label="Stop" className="btn danger" disabled=${!live} />
    </div>
    <${KeyValue} items=${[['Radio state', s.busy || '—'], ['Shows started', s.shows], ['Last show id', s.last_show_id], ['Show running (radio\'s view)', s.show_running ? 'yes' : 'no'], ['Lockout', s.lockout_ms != null ? `${s.lockout_ms} ms` : '—']]} />
    ${(s.colour_sends || []).length ? html`<div class="note">Colours sent: ${s.colour_sends.map((c) => `${c.name} → ${c.zone_name}: ${c.delivered}/${c.sent} frames acknowledged by the cube's radio${c.name === 'broadcast' ? ' (broadcast is never acknowledged)' : ''}`).join(' · ')}</div>` : ''}
  </div>`;
}

function PoolLamp({ device, s }) {
  const pool = s.pool || {};
  const held = s.pool_held || 0;
  const [radioId, setRadioId] = useState(s.pool_radio_id || 1);
  const live = device.state === 'session' && s.connected;
  const slots = [held, 0, 0, 0, 0, 0];
  const toggle = (m) => {
    if (m === held) return run('radio.pool_release', { device: device.id }).catch((e) => notify(e.message, 'bad'));
    return run('radio.pool', { device: device.id, member: m, radio_id: Number(radioId) }).catch((e) => notify(e.message, 'bad'));
  };
  useEffect(() => {
    if (!held) return undefined;
    const timer = setInterval(() => run('radio.pool_touch', { device: device.id }).catch(() => {}), 300);
    return () => clearInterval(timer);
  }, [held, device.id]);
  const beacon = s.pool_beacon;
  return html`<div class="card"><${Explainer} id="generalradio.pool" />
    <${Banner} kind="info" title="One lamp at a time" detail="The central keys its slots by sender address, so this radio holds one member. It is released 0.6 s after this page stops holding it, and by the radio itself 1.5 s after the console stops pinging." />
    <${MemberGrid} slots=${slots} disabled=${!live} onToggle=${toggle} />
    <div class="row">
      <label class="lbl">Radio id (label at the central)</label><select class="field" value=${radioId} onChange=${(e) => setRadioId(e.target.value)}>${[1, 2, 3, 4, 5, 6].map((i) => html`<option value=${i}>${i}</option>`)}</select>
      <${ActionButton} name="radio.pool_release" args=${{ device: device.id }} label="Release lamp (Esc)" className="btn danger" disabled=${!live || !held} />
    </div>
    <${KeyValue} items=${[['Held', held ? `member ${held}` : 'nothing'], ['Radio says', pool.armed ? `member ${pool.member} · radio id ${pool.radio_id}` : 'released'], ['Central', pool.central_mac ? `${pool.central_mac} · ${pool.unicast ? 'unicast (beacon fresh)' : 'broadcast (no fresh beacon)'} · radio mask ${pool.radio_mask}` : 'no beacon heard yet'], ['Last beacon', beacon ? `${hhmmss(beacon.at)} · epoch ${beacon.epoch} · up ${beacon.uptime_s} s · v${beacon.version}` : '—']]} />
  </div>`;
}

// The pairing-station verbs on this board's own link (radio.*), so they work even while a real
// pairing station is also connected and carries the pairing app's own flows.
function PairingVerbs({ device, s, isStation }) {
  useSections(['inventory']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.role !== 'excluded' && (r.cube_id != null || r.age_s != null));
  const [mac, setMac] = useState('');
  const live = device.state === 'session' && s.connected;
  const chosen = rows.find((r) => r.mac === mac);
  const busy = !!s.mode;
  return html`<div class="card"><${Explainer} id="station" />
    <${Banner} kind="info" title="No NFC reader on this radio" detail=${`Discovery, identify flashes and sending saved mappings work through this board; a fresh tag scan needs the pairing station.${isStation ? '' : ' A pairing station is also connected: the Cube panel and the pairing flows use it, the buttons here use this radio.'}`} />
    <div class="row">
      <${ActionButton} name="radio.discover" args=${{ device: device.id }} label="Discover" disabled=${!live || busy} />
      <${ActionButton} name="radio.stop" args=${{ device: device.id }} label="Stop" className="btn danger" disabled=${!live} />
      <span class="note">${busy ? `${s.mode}: ${s.message || ''}` : s.message || ''}</span>
    </div>
    <div class="row"><label class="lbl">Cube</label>
      <select class="field" value=${mac} onChange=${(e) => setMac(e.target.value)}>
        <option value="">choose a cube…</option>
        ${rows.map((r) => html`<option value=${r.mac}>${r.cube_id != null ? `#${r.cube_id}` : 'no number'} · ${r.mac}${r.uid ? '' : ' · no tag saved'}</option>`)}
      </select>
      <${ActionButton} name="radio.transmit" args=${{ device: device.id, macs: [mac] }} label=${`Send saved mapping${chosen && chosen.cube_id != null ? ' to #' + chosen.cube_id : ''}`} disabled=${!live || !mac || busy || !(chosen && (chosen.uid || chosen.pending_uid))} hazard="Registers the saved number and tag on the cube over the air (three attempts, then the cube's acknowledgment)." />
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac], sequential: true }} label="Flash 2 s" disabled=${!live || !mac || busy} hazard="A two-second blue/red flash on the cube, then idle." />
    </div></div>`;
}

function PreshowCue({ device, s }) {
  const ps = s.preshow || {};
  const held = s.preshow_held || 0;
  const live = device.state === 'session' && s.connected;
  useEffect(() => {
    if (!held) return undefined;
    const timer = setInterval(() => run('radio.preshow_touch', { device: device.id }).catch(() => {}), 300);
    return () => clearInterval(timer);
  }, [held, device.id]);
  const beacon = s.preshow_beacon;
  return html`<div class="card"><${Explainer} id="generalradio.preshow" />
    <div class="row">${[1, 2, 3, 4].map((p) => held === p
      ? html`<${ActionButton} name="radio.preshow" args=${{ device: device.id, point: p, on: false }} label=${`POINT ${p} · ON → off`} className="btn primary" />`
      : html`<${ActionButton} name="radio.preshow" args=${{ device: device.id, point: p, on: true }} label=${`POINT ${p} ON`} disabled=${!live || (held && held !== p)} hazard="Raises a TouchDesigner cue through the bridge; held only while this page holds it." />`)}
      <${ActionButton} name="radio.preshow_release" args=${{ device: device.id }} label="Release cue (Esc)" className="btn danger" disabled=${!live || !held} /></div>
    <${KeyValue} items=${[['Held', held ? `point ${held} ON` : 'nothing'], ['Radio says', ps.armed ? `point ${ps.point} ${ps.state ? 'ON' : 'OFF'} · seq ${ps.seq} · ${ps.acked ? `acknowledged in ${ps.ack_ms} ms` : 'not acknowledged'}` : 'released'], ['Mode', ps.mode === 'modern' ? 'modern · a bridge answers, cues are acknowledged end to end' : 'legacy · no bridge beacon heard; the 2-byte packet is also sent and nothing can acknowledge it'], ['Bridge', ps.bridge_mac ? `${ps.bridge_mac} · ${ps.unicast ? 'unicast' : 'broadcast'} · sees me: ${ps.bridge_sees_me ? 'yes' : 'no'}` : 'not heard from'], ['Last beacon', beacon ? `${hhmmss(beacon.at)} · epoch ${beacon.epoch} · point mask ${beacon.point_mask}` : '—']]} />
    ${(s.recent_acks || []).length ? html`<div class="note">Recent acks: ${s.recent_acks.map((a) => `${hhmmss(a.at)} point ${a.point} ${a.state ? 'ON' : 'OFF'} in ${a.ms} ms`).join(' · ')}</div>` : ''}
  </div>`;
}

export function GeneralRadioPanel({ device }) {
  useSections(['station', 'sessions', 'devices', 'show']);
  const s = sessionOf(device) || {};
  const st = section('station') || {};
  const TABS = [['cubes', 'Cubes & show'], ['relay', 'Zone relay'], ['pool', 'Pool lamp'], ['preshow', 'Preshow cue'], ['pairing', 'Pairing'], ['console', 'Console']];
  const [tab, setTab] = useRouteTab('cubes', TABS.map((t) => t[0]));
  const tx = s.tx || {}, rx = s.rx || {};
  const isStation = st.device === device.id;
  const pills = html`${s.connected ? html`<${Pill} tone="ok" label="radio ready" />` : html`<${Pill} tone="warn" label="not answering" />`}
    ${(s.hello || {}).channel != null && html`<${Pill} tone=${s.hello.channel === 2 ? 'ok' : 'bad'} label=${`channel ${s.hello.channel}`} />`}
    ${s.host_fresh === false && html`<${Pill} tone="warn" label="host lease lapsed" tip="The radio has not heard a ping within 5 s; it releases anything it held." />`}
    ${s.led_test && html`<${Pill} tone="info" label="LED test" />`}
    ${s.fatal && html`<${Pill} tone="bad" label="radio fault" tip=${s.problem} />`}
    ${isStation ? html`<${Pill} tone="info" label="carries pairing + zone relay" tip="No other pairing station is connected, so this radio is the pairing link." />` : html`<${Pill} tone="muted" label="pairing goes via the station" tip="A pairing station is also connected and keeps the pairing link; this radio's own verbs are on its Pairing tab." />`}`;
  return html`<div>
    <${DeviceHeader} device=${device} title="General Radio" pills=${pills} kv=${[['Firmware', (s.hello || {}).firmware], ['Roles', (s.roles || []).join(' · ')], ['TX', `${tx.sent ?? 0} sent · ${tx.delivered ?? 0} delivered · ${tx.unconfirmed ?? 0} unconfirmed · ${tx.no_result ?? 0} no result · ${tx.rejected ?? 0} rejected`], ['RX', `${rx.zone ?? 0} zone frames · ${rx.zone_dropped ?? 0} dropped · ${rx.serial_overflows ?? 0} serial overflows`], ['Status', st.message]]} />
    <${Explainer} id="generalradio" />
    ${s.problem && html`<${Banner} kind="bad" title=${s.fatal ? 'The radio driver stopped answering' : 'Radio problem'} detail=${`${s.problem}. ${s.fatal ? 'Every radio operation is refused until the board is power-cycled; its own leases release anything it held. Unplug and replug it, then probe again.' : ''}`} />`}
    ${isStation && html`<${StationBanner} />`}
    <${Tabs} tabs=${TABS} current=${tab} onChange=${setTab} />
    ${tab === 'cubes' && html`<${CubeColours} device=${device} s=${s} /><${ShowControl} />`}
    ${tab === 'relay' && html`${!isStation && html`<div class="note">A pairing station carries the primary zone relay: the table below is its view, the buttons send through this radio.</div>`}<${ZoneRelay} device=${device} />`}
    ${tab === 'pool' && html`<${PoolLamp} device=${device} s=${s} />`}
    ${tab === 'preshow' && html`<${PreshowCue} device=${device} s=${s} />`}
    ${tab === 'pairing' && html`<${PairingVerbs} device=${device} s=${s} isStation=${isStation} /><${DiscoveryGrid} />`}
    ${tab === 'console' && html`<div class="card"><div class="row"><${ActionButton} name="radio.led_test" args=${{ device: device.id, on: !s.led_test }} label=${s.led_test ? 'LED test off' : 'LED test on'} hazard="Cycles the board's eight WS2812s." /><${ActionButton} name="radio.status" args=${{ device: device.id }} label="Refresh status" /><${ActionButton} name="radio.release" args=${{ device: device.id }} label="Release everything" className="btn danger" /></div></div><${RawConsole} device=${device} hint='{"cmd":"status","id":"1"}' />`}
    <${JobHistory} device=${device} /></div>`;
}
