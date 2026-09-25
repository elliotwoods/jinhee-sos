// One panel for every radio host board with role 'workstation': the Workstation firmware, a legacy General
// Radio, a legacy pairing station and a legacy ESP-NOW dongle. The tabs light up by capability
// (s.capabilities from the hub); a tab a board cannot serve is greyed, and says why if it is opened.
import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useSections, useRouteTab } from '../lib/hooks.js';
import { ledToken } from '../lib/theme.js';
import { section, stationEvents } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, ProgressBar, Tabs, Ladder } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { DataTable, LogPane } from '../components/data.js';
import { LedRing, MemberGrid } from '../components/canvas.js';
import { DeviceHeader, sessionOf, RawConsole, JobHistory, rowByMac } from './common.js';
import { StationBanner, CubeDetail, registrationPill, cubeLevel, statusLabel } from './CubePanel.js';
import { ShowControl } from './ShowSection.js';
import { goDevice } from '../router.js';
import { hhmmss, crc, ago, signalBars } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { docCube } from '../lib/doc.js';
import { t, tk, hint } from '../lib/i18n.js';

// `device`: the board whose link the relay commands should use (a second Workstation beside the primary
// link); without it they go to the primary link. The table shows the primary registry either way.
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
    { key: 'name', label: t('Zone'), render: (z) => html`<a href="#" onClick=${(e) => { e.preventDefault(); goDevice(zoneId(z)); }}>${z.name || z.mac}</a>` },
    { key: 'zone_label', label: t('Type'), render: (z) => (Number(z.zone_type) === 0 ? t('unconfigured') : z.zone_label) }, { key: 'point_id', label: t('Point'), render: (z) => (Number(z.zone_type) === 0 ? '—' : z.point_id) }, { key: 'firmware', label: t('Firmware'), mono: true },
    { key: 'db_version', label: 'DB', render: (z) => html`v${z.db_version} <${Pill} status=${'zonedb.' + z.state} />` },
    { key: 'rssi', label: t('Signal'), render: (z) => signalBars(z.rssi, '—') }, { key: 'age_s', label: t('Seen'), render: (z) => z.age_s == null ? t('never') : t('{ago} ago', { ago: ago(z.age_s) }) },
    { key: 'rx_gain', label: 'RX gain', render: (z) => z.rx_gain_pending ? `→ ${z.rx_gain_pending} dB …` : z.rx_gain ? `${z.rx_gain} dB${z.rx_gain_applied ? '' : ' ' + t('(not applied)')}` : '—' },
    { key: 'error_text', label: t('Error') },
  ];
  return html`<div class="card"><h3>${t('Zone relay (over the air)')}</h3><${Explainer} id="dongle" />
    <${KeyValue} items=${[[t('Published database'), pub.version ? t('v{v} · {n} records · CRC {crc}', { v: pub.version, n: pub.count, crc: crc(pub.crc) }) : t('nothing published yet')], [t('Relay'), reg.connected ? t('ready') : t('station not connected or no zone support')], [t('Message'), reg.message || '—'],
      [t('Zones'), t('{near} in range · {out} out of range ({shown}) · {behind} behind', { near: all.filter(near).length, out: outOfRange, shown: showOut ? t('shown') : t('hidden'), behind: behind.length })]]} />
    ${p && html`<div class="stack" data-doc="relay.progress"><div class="row"><strong>${t('Publishing v{v}', { v: p.version })}</strong> <span class="note">${t('cycle {cycles} · {elapsed} s · {pending} pending of {expected} · {failures} send failures', { cycles: p.cycles, elapsed: p.elapsed_s, pending: p.pending.length, expected: p.expected.length, failures: p.send_failures })}</span></div>
      <${ProgressBar} value=${p.expected.length ? 100 * (p.expected.length - p.pending.length) / p.expected.length : 0} />
      <div class="note mono">${p.pending.join(', ')}</div></div>`}
    <div class="row">
      <${ActionButton} name="zones.query" args=${scope} label=${t('Query zones')} disabled=${!reg.connected} />
      <label class="check" data-doc="relay.auto"><input type="checkbox" checked=${!!reg.auto_refresh} onChange=${(e) => run('zones.auto_refresh', { ...scope, enabled: e.target.checked }).catch((x) => notify(x.message, 'bad'))} /> ${t('auto-refresh (3 s)')}</label>
      <${ActionButton} name="zones.update_all" args=${scope} label=${t('Update all out-of-date zones ({n})', { n: behind.length })} disabled=${!reg.connected || !behind.length} hazard=${t('One broadcast run for every in-range zone that is behind.')} />
      <label class="check" title=${hint('walkaround')} data-doc="zones.walkaround"><input type="checkbox" checked=${autoOn} onChange=${(e) => run('zones.walkaround', { ...scope, enabled: e.target.checked }).catch((x) => notify(x.message, 'bad'))} /> ${t('auto-update all (walk the space)')}${autoOn && !reg.walkaround ? ' · ' + t('another relay is walking') : ''}</label>
      ${p && html`<${ActionButton} name="zones.stop" args=${scope} label=${t('Stop publishing')} className="btn danger small" />`}
      <label class="check" data-doc="relay.show_out"><input type="checkbox" checked=${showOut} onChange=${(e) => setShowOut(e.target.checked)} /> ${t('Show out of range ({n})', { n: outOfRange })}</label></div>
    <${DataTable} columns=${columns} rows=${zones} keyOf=${(z) => z.mac} doc="relay.table" rowDoc=${(z) => `relay.zone:${z.mac}`} empty=${all.length ? t('Every zone heard is out of range (tick Show out of range)') : t('No zones have answered yet')} /></div>`;
}

export function zoneId(z) {
  const usb = (section('devices') || []).find((d) => d.mac === z.mac);
  return usb ? usb.id : `zone:${z.mac}`;
}

export function DiscoveryGrid() {
  useSections(['inventory', 'station']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.age_s != null && r.role !== 'excluded').sort((a, b) => a.age_s - b.age_s);
  return html`<div class="card"><h3>${t('Cubes heard over the radio ({n})', { n: rows.length })}</h3>
    <div class="ring-grid">${rows.map((r) => html`<div key=${r.mac} class="ring-tile" role="link" tabindex="0" onClick=${() => goDevice('cube:' + r.mac)} onKeyDown=${(e) => e.key === 'Enter' && goDevice('cube:' + r.mac)}>
      <${LedRing} size=${90} colour=${ledToken(r)} label=${r.cube_id != null ? `#${r.cube_id}` : '—'} sub=${r.recent ? t('heard') : ago(r.age_s)} blink=${r.telemetry && r.telemetry.command === 'identify'} />
      ${registrationPill(r)}</div>`)}
      </div>${!rows.length && html`<div class="note">${t('No discovery replies yet. Discover runs on connection and every few seconds while idle.')}</div>`}</div>`;
}

const ZONES = [[0, tk('idle')], [1, tk('preshow')], [2, tk('desert')], [3, tk('pool')], [4, tk('mainshow')]];

function CubeColours({ device, s }) {
  useSections(['inventory', 'station']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.role !== 'excluded' && (r.cube_id != null || r.age_s != null));
  // Preselect the cube a documentation link names (?cube=), else the only known cube.
  const preset = (docCube() && rows.find((r) => r.cube_id === docCube())) || (rows.length === 1 ? rows[0] : null);
  const [mac, setMac] = useState(preset ? preset.mac : '');
  const [zone, setZone] = useState(4);
  const live = device.state === 'session' && s.connected;
  const chosen = rows.find((r) => r.mac === mac);
  return html`<div class="card"><${Explainer} id="workstation.cubes" />
    <div class="row"><label class="lbl">${t('Cube')}</label>
      <select class="field" value=${mac} onChange=${(e) => setMac(e.target.value)}>
        <option value="">${t('choose a cube…')}</option>
        ${rows.map((r) => html`<option value=${r.mac}>${r.cube_id != null ? `#${r.cube_id}` : t('no number')} · ${r.mac}${r.recent ? ' · ' + t('heard') : ''}</option>`)}
      </select>
      <label class="lbl">${t('Zone')}</label>
      <select class="field" value=${zone} onChange=${(e) => setZone(Number(e.target.value))}>${ZONES.map(([v, n]) => html`<option value=${v}>${v} · ${t(n)}</option>`)}</select>
      <${ActionButton} name="radio.set_zone" args=${{ device: device.id, mac, zone }} label=${t('Set {cube} → {zone}', { cube: chosen && chosen.cube_id != null ? '#' + chosen.cube_id : t('cube'), zone: t(ZONES[zone][1]) })} disabled=${!live || !mac} hazard=${t("Unicast SET_ZONE ×3; the cube's radio ACK is not a colour change.")} />
      <${ActionButton} name="radio.show_start" args=${{ device: device.id, cube: mac }} label=${t('Start show on this cube')} disabled=${!live || !mac} hazard=${t('MSG_SHOW_START with a fresh showId ×5; only a mainshow-ready cube starts.')} />
    </div>
    <div class="row">
      <${HoldButton} name="radio.set_zone_all" args=${{ device: device.id, zone }} label=${t('ALL cubes in range → {zone}', { zone: t(ZONES[zone][1]) })} disabled=${!live} hazard=${t('Broadcast SET_ZONE: recolours every cube that hears it, with no acknowledgment.')} />
      <${HoldButton} name="radio.show_start_all" args=${{ device: device.id }} label=${t('Start show on ALL ready cubes')} disabled=${!live} hazard=${t('Broadcast SHOW_START, no acknowledgment; cannot be undone.')} />
    </div>
    <div class="row">
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac] }} label=${t('Identify (flash until Stop)')} disabled=${!live || !mac} hazard=${t('The cube blinks blue/red until Stop; it is returned to idle afterwards.')} />
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac], sequential: true }} label=${t('Flash 2 s')} disabled=${!live || !mac} hazard=${t('A two-second blue/red flash on the cube, then idle.')} />
      <${ActionButton} name="radio.stop" args=${{ device: device.id }} label=${t('Stop')} className="btn danger" disabled=${!live} />
    </div>
    <${KeyValue} items=${[[t('Radio state'), s.busy || '—'], [t('Shows started'), s.shows], [t('Last show id'), s.last_show_id], [t('Show running (radio\'s view)'), s.show_running ? t('yes') : t('no')], [t('Lockout'), s.lockout_ms != null ? `${s.lockout_ms} ms` : '—']]} />
    ${(s.colour_sends || []).length ? html`<div class="note">${t('Colours sent:')} ${s.colour_sends.map((c) => t("{name} → {zone}: {delivered}/{sent} frames acknowledged by the cube's radio", { name: c.name, zone: c.zone_name, delivered: c.delivered, sent: c.sent }) + (c.name === 'broadcast' ? ' ' + t('(broadcast is never acknowledged)') : '')).join(' · ')}</div>` : ''}
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
  return html`<div class="card"><${Explainer} id="workstation.pool" />
    <${Banner} kind="info" title=${t('One lamp at a time')} detail=${t('The central keys its slots by sender address, so this radio holds one member. It is released 0.6 s after this page stops holding it, and by the radio itself 1.5 s after the console stops pinging.')} />
    <${MemberGrid} slots=${slots} disabled=${!live} onToggle=${toggle} doc="radio.pool" />
    <div class="row">
      <label class="lbl">${t('Radio id (label at the central)')}</label><select class="field" value=${radioId} onChange=${(e) => setRadioId(e.target.value)}>${[1, 2, 3, 4, 5, 6].map((i) => html`<option value=${i}>${i}</option>`)}</select>
      <${ActionButton} name="radio.pool_release" args=${{ device: device.id }} label=${t('Release lamp (Esc)')} className="btn danger" disabled=${!live || !held} />
    </div>
    <${KeyValue} items=${[[t('Held'), held ? t('member {n}', { n: held }) : t('nothing')], [t('Radio says'), pool.armed ? t('member {member} · radio id {id}', { member: pool.member, id: pool.radio_id }) : t('released')], [t('Central'), pool.central_mac ? `${pool.central_mac} · ${pool.unicast ? t('unicast (beacon fresh)') : t('broadcast (no fresh beacon)')} · ${t('radio mask {mask}', { mask: pool.radio_mask })}` : t('no beacon heard yet')], [t('Last beacon'), beacon ? t('{time} · epoch {epoch} · up {up} s · v{v}', { time: hhmmss(beacon.at), epoch: beacon.epoch, up: beacon.uptime_s, v: beacon.version }) : '—']]} />
  </div>`;
}

// The pairing-station verbs on this board's own link (radio.*), for a board that is not the primary
// pairing link: they work even while the primary link carries the pairing app's own flows.
function PairingVerbs({ device, s, caps }) {
  useSections(['inventory']);
  const rows = ((section('inventory') || {}).rows || []).filter((r) => r.role !== 'excluded' && (r.cube_id != null || r.age_s != null));
  const [mac, setMac] = useState('');
  const live = device.state === 'session' && s.connected;
  const chosen = rows.find((r) => r.mac === mac);
  const busy = !!s.mode && s.mode !== 'reader_flash';   // the tag-read flash gives way to anything started here
  const title = caps.reader ? t('Pairing goes via the primary link') : t('No NFC reader on this board');
  const detail = (caps.reader
    ? t('This board has a reader, but another link is the primary pairing link: the Cube panel and the pairing flows use it.')
    : t('Discovery, identify flashes and sending saved mappings work through this board; a fresh tag scan needs the primary pairing link.'))
    + ' ' + t('The buttons here use this board\'s own radio.');
  return html`<div class="card"><${Explainer} id="station" />
    <${Banner} kind="info" title=${title} detail=${detail} />
    <div class="row">
      <${ActionButton} name="radio.discover" args=${{ device: device.id }} label=${t('Discover')} disabled=${!live || busy} />
      <${ActionButton} name="radio.stop" args=${{ device: device.id }} label=${t('Stop')} className="btn danger" disabled=${!live} />
      <span class="note">${busy ? `${s.mode}: ${s.message || ''}` : s.message || ''}</span>
    </div>
    <div class="row"><label class="lbl">${t('Cube')}</label>
      <select class="field" value=${mac} onChange=${(e) => setMac(e.target.value)}>
        <option value="">${t('choose a cube…')}</option>
        ${rows.map((r) => html`<option value=${r.mac}>${r.cube_id != null ? `#${r.cube_id}` : t('no number')} · ${r.mac}${r.uid ? '' : ' · ' + t('no tag saved')}</option>`)}
      </select>
      <${ActionButton} name="radio.transmit" args=${{ device: device.id, macs: [mac] }} label=${chosen && chosen.cube_id != null ? t('Send saved mapping to #{n}', { n: chosen.cube_id }) : t('Send saved mapping')} disabled=${!live || !mac || busy || !(chosen && (chosen.uid || chosen.pending_uid))} hazard=${t("Registers the saved number and tag on the cube over the air (three attempts, then the cube's acknowledgment).")} />
      <${ActionButton} name="radio.identify" args=${{ device: device.id, macs: [mac], sequential: true }} label=${t('Flash 2 s')} disabled=${!live || !mac || busy} hazard=${t('A two-second blue/red flash on the cube, then idle.')} />
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
  return html`<div class="card"><${Explainer} id="workstation.preshow" />
    <div class="row">${[1, 2, 3, 4].map((p) => held === p
      ? html`<${ActionButton} name="radio.preshow" args=${{ device: device.id, point: p, on: false }} label=${t('POINT {p} · ON → off', { p })} className="btn primary" />`
      : html`<${ActionButton} name="radio.preshow" args=${{ device: device.id, point: p, on: true }} label=${t('POINT {p} ON', { p })} disabled=${!live || (held && held !== p)} hazard=${t('Raises a TouchDesigner cue through the bridge; held only while this page holds it.')} />`)}
      <${ActionButton} name="radio.preshow_release" args=${{ device: device.id }} label=${t('Release cue (Esc)')} className="btn danger" disabled=${!live || !held} /></div>
    <${KeyValue} items=${[[t('Held'), held ? t('point {n} ON', { n: held }) : t('nothing')], [t('Radio says'), ps.armed ? t('point {point} {state} · seq {seq} · {ack}', { point: ps.point, state: ps.state ? 'ON' : 'OFF', seq: ps.seq, ack: ps.acked ? t('acknowledged in {ms} ms', { ms: ps.ack_ms }) : t('not acknowledged') }) : t('released')], [t('Mode'), ps.mode === 'modern' ? t('modern · a bridge answers, cues are acknowledged end to end') : t('legacy · no bridge beacon heard; the 2-byte packet is also sent and nothing can acknowledge it')], [t('Bridge'), ps.bridge_mac ? `${ps.bridge_mac} · ${ps.unicast ? t('unicast') : t('broadcast')} · ${t('sees me: {answer}', { answer: ps.bridge_sees_me ? t('yes') : t('no') })}` : t('not heard from')], [t('Last beacon'), beacon ? t('{time} · epoch {epoch} · point mask {mask}', { time: hhmmss(beacon.at), epoch: beacon.epoch, mask: beacon.point_mask }) : '—']]} />
    ${(s.recent_acks || []).length ? html`<div class="note">${t('Recent acks:')} ${s.recent_acks.map((a) => t('{time} point {point} {state} in {ms} ms', { time: hhmmss(a.at), point: a.point, state: a.state ? 'ON' : 'OFF', ms: a.ms })).join(' · ')}</div>` : ''}
  </div>`;
}

// The primary pairing link's own flows (pairing.* / station.*): discovery, the auto pairing run, the
// registration in flight on the truth ladder. A board without a reader keeps discover/stop only.
function StationPairing({ st, caps }) {
  return html`<div class="card"><${Explainer} id="station" />
    ${!caps.reader && html`<${Banner} kind="info" title=${t('No NFC reader on this board')} detail=${t('Discovery, identify flashes and sending saved mappings work through this link; a fresh tag scan needs a board with a reader (a Workstation or a pairing station).')} />`}
    <div class="row">
      <${ActionButton} name="pairing.discover" args=${{}} label=${t('Discover')} disabled=${!st.connected} />
      <${ActionButton} name="pairing.start_pair" args=${{}} label=${t('Pair new cubes (auto)')} disabled=${!st.connected || !caps.reader || !st.reader_ok || (!!st.mode && st.mode !== 'reader_flash')} hazard=${t('Discovers new cubes, flashes each in turn and waits for its tag.')} />
      ${st.phase === 'paused' && html`<${ActionButton} name="pairing.retry" args=${{}} label=${t('Retry paused')} />`}
      ${st.mode && html`<${ActionButton} name="pairing.skip" args=${{}} label=${t('Skip')} />`}
      <${ActionButton} name="pairing.stop" args=${{}} label=${t('■ Stop')} className="btn danger" disabled=${!st.connected} />
      ${caps.reader && st.connected && !st.reader_ok && html`<${ActionButton} name="station.nfc_recover" args=${{}} label=${t('Recover NFC reader')} hazard=${t('I²C bus clear and PN532 re-init; refused while an operation runs.')} />`}
      ${caps.reader && html`<${ActionButton} name="station.nfc_status" args=${{}} label=${t('NFC status')} className="btn small" disabled=${!st.connected} />`}</div>
    <${StationLadder} st=${st} />
    ${st.active && html`<section class="sub"><h3>${t('Current target')}</h3><${TargetCard} active=${st.active} /></section>`}
    ${st.total ? html`<div class="progress-row"><${ProgressBar} value=${100 * st.progress / st.total} /><span class="note mono">${st.progress} / ${st.total}</span></div>` : null}
    </div>`;
}

// The cube lying on this board's reader, as a zone plate's Monitor shows the cube on the plate. The hub reads the tag's
// UID back from the reader (s.reader_tag, s.reader_history); the inventory says whose tag it is (committed first, then
// pending); the actions go out over this board's own radio. Nothing here writes the inventory. The switch on top
// (setting reader_flash, on by default; Workstation firmware only) makes the hub act on each tag placed, whether or not
// this page is open: the 2 s flash or one SET_ZONE (reader_action), only while nothing else uses the radio.
function ownerOf(uid) {
  const rows = (section('inventory') || {}).rows || [];
  const row = uid ? rows.find((r) => r.uid === uid) || rows.find((r) => r.pending_uid === uid) || null : null;
  return { row, pending: !!row && row.uid !== uid };
}

function ReaderCube({ device, s, caps }) {
  useSections(['inventory']);
  const [selected, setSelected] = useState(null);
  const tag = s.reader_tag || {};
  const history = s.reader_history || [];
  const key = (h) => `${h.time}:${h.uid}`;
  const picked = !tag.present && selected ? history.find((h) => key(h) === selected) : null;
  const uid = tag.present ? tag.uid : picked ? picked.uid : null;
  const { row, pending } = ownerOf(uid);
  const mac = row ? row.mac : null;
  const number = row && row.cube_id != null ? `#${row.cube_id}` : null;
  const sent = mac ? (s.colour_sends || []).find((c) => c.mac === mac) : null;
  const zc = sent && s.zone_colors ? s.zone_colors[sent.zone] : null;
  const ring = zc ? { colour: zc[1], sub: t(zc[0]) } : { colour: ledToken(row), sub: row ? statusLabel(row.status) : uid ? t('Unknown tag') : '—' };
  const live = device.state === 'session' && s.connected;
  const readout = tag.present ? (!tag.uid ? t('Reading the tag…') : number || (row ? t('no number') : t('Unknown tag'))) : picked ? number || (row ? t('no number') : t('Unknown tag')) : t('No cube on the reader');
  const held = (h) => (h.held_ms == null ? t('on the reader') : `${(h.held_ms / 1000).toFixed(1)} s`);
  const setReader = (args) => run('radio.reader_flash', args).catch((x) => notify(x.message, 'bad'));
  // One choice, Off or the action: what happens automatically to the cube whose tag is read, not a one-shot command.
  const choice = (checked, label, args, title) => html`<button class=${'btn small' + (checked ? ' primary' : '')} role="radio" aria-checked=${checked ? 'true' : 'false'} title=${title} onClick=${() => setReader(args)}>${label}</button>`;
  const last = s.reader_flash_last;
  const action = s.reader_action || 'flash';
  const actionZone = action.startsWith('zone:') ? Number(action.slice(5)) : null;
  const RESULTS = { flashed: tk('flashed'), 'flashed (pending tag)': tk('flashed (pending tag)'), 'unknown tag': tk('nothing sent: unknown tag'), busy: tk('nothing sent: the radio was busy'), excluded: tk('nothing sent: excluded device'), 'show running': tk('nothing sent: a main show is running') };
  const resultText = (r) => (r.startsWith('zone ') ? t('zone {n} sent', { n: r.split(' ')[1] }) : t(RESULTS[r] || r));
  const columns = [
    { key: 'time', label: t('Time'), render: (h) => hhmmss(h.time) },
    { key: 'cube_id', label: t('Cube'), render: (h) => { const o = ownerOf(h.uid).row; return o && o.cube_id != null ? `#${o.cube_id}` : o ? t('no number') : t('unknown'); } },
    { key: 'uid', label: 'UID', mono: true },
    { key: 'held_ms', label: t('Held'), render: held },
    { key: 'registry', label: t('Inventory'), render: (h) => { const o = ownerOf(h.uid); return o.row ? `${statusLabel(o.row.status)}${o.pending ? ' · ' + t('pending tag') : ''}` : t('unknown to this computer'); } },
  ];
  return html`<div class="card" data-doc="workstation.reader"><h3>${t('On the reader')}</h3>
    ${s.reader_action_capable && html`<div class=${'activate choose' + (s.reader_flash_setting ? ' on' : '')} data-doc="workstation.reader_flash">
      <span class="activate-text"><strong>${t('Signal the cube when its tag is read')}</strong>
        <span>${!s.reader_flash_setting ? t('Off: a tag on the reader is only shown here.')
          : actionZone == null ? t('Each tag placed on the reader makes its cube flash blue/red for 2 s, then idle white: the cube is registered and reachable. Anything you start takes over at once; nothing is sent while the radio is busy or a main show is running.')
          : t('Each tag placed on the reader sets its cube to {zone} (SET_ZONE {n}). Nothing is sent while the radio is busy or a main show is running.', { zone: t(ZONES[actionZone][1]), n: actionZone })}</span>
        <span class="filters" role="radiogroup" aria-label=${t('On each tag')} data-doc="workstation.reader_action">
          ${choice(!s.reader_flash_setting, t('Off'), { on: false })}
          ${choice(s.reader_flash_setting && actionZone == null, t('Flash 2 s'), { on: true, action: 'flash' })}
          ${ZONES.map(([z, name]) => choice(s.reader_flash_setting && actionZone === z, t(name), { on: true, action: `zone:${z}` }, t('Sends SET_ZONE {zone} ({name}) to the cube.', { zone: z, name: t(name) })))}</span></span></div>`}
    ${s.reader_flash && last && html`<div class="row"><span class="lbl">${t('Last automatic action')}</span><span class=${last.result.startsWith('flashed') || last.result.startsWith('zone ') ? 'ok-text' : 'warn-text'}>${last.cube_id != null ? `#${last.cube_id}` : last.uid} · ${resultText(last.result)} · ${hhmmss(last.at)}</span></div>`}
    ${!s.reader_ok && html`<div class="row"><${Pill} status="nfc.bad" /></div>`}
    <div class="grid2"><div>
      <${LedRing} colour=${ring.colour} label=${number || '—'} sub=${ring.sub} size=${140} blink=${row && row.telemetry && row.telemetry.command === 'identify'} /></div>
      <div class="stack"><div class=${number ? 'readout' : 'readout medium'}>${readout}</div>
      ${uid && html`<${KeyValue} items=${[['NFC UID', uid],
        ['MAC', mac ? html`<a href="#" onClick=${(e) => { e.preventDefault(); goDevice('cube:' + mac); }}>${mac}</a>` : '—'],
        [t('Inventory'), row ? html`${registrationPill(row)} ${pending ? t('pending tag of this cube (not yet acknowledged)') : ''}` : t('unknown to this computer')],
        [t('Colour sent'), sent ? t("{name} → {zone}: {delivered}/{sent} frames acknowledged by the cube's radio", { name: sent.name, zone: sent.zone_name, delivered: sent.delivered, sent: sent.sent }) : '—'],
        [t('On the reader'), tag.present && tag.since ? t('since {time}', { time: hhmmss(tag.since) }) : picked ? `${hhmmss(picked.time)} · ${held(picked)}` : '—']]} />`}
      ${uid && !row && html`<div class="warn-text">${t('No device in the inventory owns this tag. Register the cube to give it this tag.')}</div>`}
      </div></div>
    <div class="row">
      <${ActionButton} name="radio.stop" args=${{ device: device.id }} label=${t('Stop')} className="btn small danger" disabled=${!live} />
      ${mac && html`<button class="btn small" onClick=${() => goDevice('cube:' + mac)}>${t('Open cube page')}</button>`}</div>
    ${history.length > 0 && html`<${DataTable} columns=${columns} rows=${history} keyOf=${key} selected=${selected} onSelect=${(k) => setSelected(k === selected ? null : k)} maxRows=${5} />`}
  </div>`;
}

// Before a session opens (or with a hub that predates s.capabilities) the hello tells the same story.
function capsOf(s, device) {
  if (s.capabilities) return s.capabilities;
  const d = device.details || {};
  const fw = String(d.firmware || '');
  const modern = fw.startsWith('workstation-') || fw.startsWith('general-radio-');
  const reader = !fw.startsWith('general-radio-') && d.nfc_ok !== false;
  const relay = modern || d.zones === 1 || (d.zones == null && (s.zone_support ?? d.zone_support) !== false);
  return { reader, relay, show_verbs: modern, show_relay: modern, pool: modern, preshow: modern, live: modern };
}

const TABS = [['station', tk('Pairing')], ['relay', tk('Zone relay')], ['cubes', tk('Cubes & show')], ['pool', tk('Pool lamp')], ['preshow', tk('Preshow cue')], ['console', tk('Console')]];
const NEEDS = { relay: 'relay', cubes: 'show_verbs', pool: 'pool', preshow: 'preshow' };

function whyNot(id, label) {
  const who = label ? label.toLowerCase() : t('board');
  if (id === 'relay') return t('this {who} has no zone relay (legacy pairing firmware without zone support; reflash it with nct-pairing-1.8-zones or the Workstation firmware)', { who });
  const role = { cubes: tk('cube-colour'), pool: tk('pool-lamp'), preshow: tk('preshow-cue') }[id];
  return t('this {who} has no {role} role; a Workstation or General Radio does', { who, role: t(role) });
}

export function WorkstationPanel({ device }) {
  useSections(['station', 'sessions', 'devices', 'show']);
  const st = section('station') || {};
  const s = sessionOf(device) || {};
  const caps = capsOf(s, device);
  const isPrimary = st.device === device.id;
  const label = s.label || device.role_label || 'Workstation';
  const hello = s.hello || (isPrimary ? st.hello : null) || device.details || {};
  const connected = isPrimary ? !!(st.connected || s.connected) : !!s.connected;
  const readerOk = s.reader_ok ?? (isPrimary ? st.reader_ok : undefined);
  const message = (isPrimary ? st.message : null) || s.message;
  const off = new Set(TABS.map(([id]) => id).filter((id) => NEEDS[id] && !caps[NEEDS[id]]));
  const [tab, setTab] = useRouteTab(caps.reader ? 'station' : caps.show_verbs ? 'cubes' : 'relay', TABS.map(([id]) => id));
  const tx = s.tx, rx = s.rx;
  const nfc = caps.reader && connected ? (readerOk ? 'nfc.ok' : 'nfc.bad') : null;
  const pills = html`${connected ? html`<${Pill} tone="ok" label=${t('radio ready')} />` : html`<${Pill} tone="warn" label=${device.state === 'session' || st.present ? t('not answering') : t('no session')} />`}
    ${nfc && html`<${Pill} status=${nfc} />`}
    ${!caps.reader && html`<${Pill} tone="muted" label=${t('no NFC reader')} tip=${t('This board relays the radio only; a fresh tag scan needs a board with a reader.')} />`}
    ${hello.channel != null && html`<${Pill} tone=${hello.channel === 2 ? 'ok' : 'bad'} label=${t('channel {n}', { n: hello.channel })} />`}
    ${!caps.relay && connected && html`<${Pill} tone="warn" label=${t('no zone relay')} tip=${t('This firmware has no zone support; reflash it with nct-pairing-1.8-zones or the Workstation firmware.')} />`}
    ${s.host_fresh === false && html`<${Pill} tone="warn" label=${t('host lease lapsed')} tip=${t('The radio has not heard a ping within 5 s; it releases anything it held.')} />`}
    ${s.led_test && html`<${Pill} tone="info" label=${t('LED test')} />`}
    ${s.fatal && html`<${Pill} tone="bad" label=${t('radio fault')} tip=${s.problem} />`}
    ${isPrimary ? html`<${Pill} tone="info" label=${t('carries pairing + zone relay')} tip=${t('This board is the primary pairing link: the Cube panel, the pairing flows and the zone relay go through it.')} />` : html`<${Pill} tone="muted" label=${t('pairing goes via the primary link')} tip=${t("Another board is the primary pairing link and carries the pairing flows; this board's own verbs are on its Pairing tab.")} />`}`;
  const kv = [
    [t('Firmware'), hello.firmware],
    (s.roles || []).length ? [t('Roles'), s.roles.join(' · ')] : null,
    caps.reader && connected ? ['NFC', t('{state} · I²C status {status} · PN532 {firmware}', { state: readerOk ? t('ready') : t('unavailable'), status: hello.nfc_i2c_status ?? '?', firmware: hello.nfc_firmware || '?' })] : null,
    caps.reader && isPrimary ? [t('Tag on reader'), st.tag_present ? t('yes (remove it before registering)') : t('clear')] : null,
    tx ? ['TX', t('{sent} sent · {delivered} delivered · {unconfirmed} unconfirmed · {none} no result · {rejected} rejected', { sent: tx.sent ?? 0, delivered: tx.delivered ?? 0, unconfirmed: tx.unconfirmed ?? 0, none: tx.no_result ?? 0, rejected: tx.rejected ?? 0 })] : null,
    rx ? ['RX', t('{zone} zone frames · {dropped} dropped · {overflows} serial overflows', { zone: rx.zone ?? 0, dropped: rx.zone_dropped ?? 0, overflows: rx.serial_overflows ?? 0 })] : null,
    [t('Status'), message],
    (isPrimary ? st.last_disconnect : s.last_disconnect) ? [t('Last disconnect'), isPrimary ? st.last_disconnect : s.last_disconnect] : null,
  ];
  // A greyed tab that is still the route (a documentation link, or the board changed) shows why instead of its content.
  const body = (id, content) => (off.has(id) ? html`<div class="card"><div class="note">${t('Not on this board: {why}', { why: whyNot(id, label) })}</div></div>` : content());
  return html`<div>
    <${DeviceHeader} device=${device} title=${label} pills=${pills} kv=${kv} />
    ${s.problem && html`<${Banner} kind="bad" title=${s.fatal ? t('The radio driver stopped answering') : t('Radio problem')} detail=${`${s.problem}. ${s.fatal ? t('Every radio operation is refused until the board is power-cycled; its own leases release anything it held. Unplug and replug it, then probe again.') : ''}`} />`}
    ${caps.reader && s.reader_tag && html`<${ReaderCube} device=${device} s=${s} caps=${caps} />`}
    <${Explainer} id="workstation" />
    ${isPrimary && html`<${StationBanner} />`}
    <${Tabs} tabs=${TABS.map(([id, name]) => [id, t(name)])} current=${tab} onChange=${setTab} disabled=${off} />
    ${tab === 'station' && (isPrimary
      ? html`<${StationPairing} st=${st} caps=${caps} /><${DiscoveryGrid} />`
      : html`<${PairingVerbs} device=${device} s=${s} caps=${caps} /><${DiscoveryGrid} />`)}
    ${tab === 'relay' && body('relay', () => html`${!isPrimary && html`<div class="note">${t('The primary link carries the zone relay: the table below is its view, the buttons send through this board.')}</div>`}<${ZoneRelay} device=${device} />`)}
    ${tab === 'cubes' && body('cubes', () => html`<${CubeColours} device=${device} s=${s} /><${ShowControl} />`)}
    ${tab === 'pool' && body('pool', () => html`<${PoolLamp} device=${device} s=${s} />`)}
    ${tab === 'preshow' && body('preshow', () => html`<${PreshowCue} device=${device} s=${s} />`)}
    ${tab === 'console' && html`${caps.show_verbs && html`<div class="card"><div class="row"><${ActionButton} name="radio.led_test" args=${{ device: device.id, on: !s.led_test }} label=${s.led_test ? t('LED test off') : t('LED test on')} hazard=${t("Cycles the board's eight WS2812s.")} /><${ActionButton} name="radio.status" args=${{ device: device.id }} label=${t('Refresh status')} /><${ActionButton} name="radio.release" args=${{ device: device.id }} label=${t('Release everything')} className="btn danger" /></div></div>`}
      <${RawConsole} device=${device} hint=${caps.show_verbs ? '{"cmd":"status","id":"1"}' : '{"cmd":"hello"}'} />
      ${isPrimary && html`<div class="card"><h3>${t('Station events (JSON)')}</h3><${LogPane} items=${stationEvents.items.map((e) => ({ seq: e.seq, t: e.t, text: JSON.stringify(e.event), level: e.event.event === 'error' ? 'bad' : '' }))} height=${300} /></div>`}`}
    <${JobHistory} device=${device} />
  </div>`;
}

// The registration in flight on the truth ladder: identifying = the flash command went out; registering = the
// mapping is on the radio (delivered when the station's radio ACK arrives); removal = the cube acknowledged.
function StationLadder({ st }) {
  let level = null, failed = false, note = t('no registration in flight');
  const active = st.active || {};
  const tel = active.mac && st.telemetry ? st.telemetry[active.mac] || {} : {};
  if (st.mode && ['identifying', 'flashing', 'waiting'].includes(st.phase)) { level = 'sent'; note = t('flashing the cube, waiting for a fresh tag'); }
  else if (st.mode && st.phase === 'registering') { level = tel.delivery === 'delivered' ? 'delivered' : 'sent'; note = tel.delivery === 'delivered' ? t('radio ACK; waiting for the cube to acknowledge the mapping') : t('mapping sent over the radio'); }
  else if (st.mode && ['removal', 'done', 'registered'].includes(st.phase)) { level = 'acknowledged'; note = t('the cube acknowledged; remove the tag'); }
  else if (st.mode && st.phase === 'paused') { level = 'sent'; failed = true; note = t('no acknowledgment: Retry or Skip'); }
  else if (st.active) { ({ level, note } = cubeLevel(st.active)); }
  return html`<${Ladder} doc="station.ladder" level=${level} failed=${failed} note=${note} />`;
}

function TargetCard({ active }) {
  const row = rowByMac(active.mac) || active;
  return html`<div class="grid2"><div><${LedRing} colour="--led-identify" blink=${true} label=${row.cube_id != null ? `#${row.cube_id}` : '—'} sub=${t('identify')} size=${150} /></div><div><${CubeDetail} row=${row} mac=${active.mac} /></div></div>`;
}
