import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useCopy, useRouteTab } from '../lib/hooks.js';
import { ledToken } from '../lib/theme.js';
import { section, state } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, NumberField, Tabs, Ladder } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { DataTable, JobCard } from '../components/data.js';
import { LedRing } from '../components/canvas.js';
import { DeviceHeader, rowByMac, sessionOf, jobsFor, RawConsole, JobHistory } from './common.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { hhmmss, crc } from '../lib/format.js';

// A registration status as words (uitext STATUS label, else the enum humanised): shown on cards and detail rows.
const STATUS_WORDS = { awaiting_tag: 'awaiting tag', not_transmitted: 'saved, not sent', acknowledged: 'acknowledged', unconfirmed: 'unconfirmed', needs_number: 'needs a number', pending: 'pending', discovered: 'discovered' };
export function statusLabel(status) {
  if (!status) return '—';
  const entry = (state.copy && state.copy.status && state.copy.status['registration.' + status]) || null;
  return (entry && entry.label) || STATUS_WORDS[status] || String(status).replace(/_/g, ' ');
}

export function registrationPill(row) {
  return html`<${Pill} status=${'registration.' + (row ? row.status : 'discovered')} />`;
}

export function StationBanner() {
  useSections(['station']);
  const st = section('station') || {};
  const fb = st.feedback || {};
  if (!st.present) return null;
  if (fb.title) return html`<${Banner} kind=${fb.kind} title=${fb.title} detail=${fb.detail} doc="station.banner" />`;
  if (st.mode) return html`<${Banner} kind="info" title=${st.message} detail=${`${st.mode} · ${st.phase}`} doc="station.banner" />`;
  return null;
}

// Where a cube's last registration/command sits on the truth ladder (from the inventory row and station telemetry).
export function cubeLevel(row) {
  if (!row) return { level: null, note: 'not in the inventory' };
  const t = row.telemetry || {};
  if (row.status === 'acknowledged') return { level: 'acknowledged', note: 'the cube acknowledged its mapping; verified would need a read-back' };
  if (t.delivery === 'failed' || t.delivery === 'not delivered') return { level: 'sent', failed: true, note: `${t.command || 'last command'}: no radio delivery` };
  if (t.delivery === 'delivered') return { level: 'delivered', note: `${t.command || 'last command'}: radio ACK, not yet acknowledged by the cube` };
  if (['pending', 'unconfirmed', 'not_transmitted'].includes(row.status)) return { level: 'sent', note: `${statusLabel(row.status)}: no acknowledgment recorded` };
  return { level: null, note: 'nothing in flight' };
}

// The registration/identity block shared by the Cube USB panel and the inventory row detail.
export function CubeActions({ row, mac }) {
  useSections(['station', 'inventory']);
  const st = section('station') || {};
  const inv = section('inventory') || {};
  const connected = st.present && st.connected;
  const busy = connected && st.mode;
  const reason = !st.present ? 'No pairing station connected' : !st.connected ? 'Station not connected' : !st.reader_ok ? 'NFC reader unavailable on the station' : busy ? `Station busy: ${st.mode}` : null;
  const excluded = row && row.role === 'excluded';
  const hasNumber = row && row.cube_id != null;
  // The pairing app's button rules, computed on the owner thread (state.capabilities): why each action is off.
  const cap = (row && row.capabilities) || {};
  const why = (name) => (cap[name] && !cap[name].enabled ? cap[name].reason : null);
  const unavailable = [['Register', why('register')], ['Send saved mapping', row && (row.uid || row.pending_uid) ? why('transmit') : null], ['Flash', why('flash')], ['Rename', why('rename')], ['Role', why('role')]].filter(([, r]) => r);
  return html`<div class="stack">
    ${excluded && html`<div class="note">Excluded (reader / base station): registration and LED actions are not offered.</div>`}
    ${!hasNumber && !excluded && html`<div><div class="note">This device needs its physical label number before it can be registered.</div>
      <div data-doc="cube.number"><${NumberField} suggested=${inv.suggested_number} busy=${!!why('rename')} onSubmit=${(n) => run('inventory.rename', { mac, number: n }).then(() => notify(`Number ${n} assigned`, 'ok'))} /></div></div>`}
    ${hasNumber && !excluded && html`<div class="row">
      <${ActionButton} name="pairing.register" args=${{ mac }} label=${row.uid ? 'Replace tag (scan)' : 'Register (scan a tag)'} className="btn primary" disabled=${!!reason || !!why('register') || !st.reader_ok} reason=${why('register') || reason} hazard=${row.uid ? 'A new scan replaces this cube\'s committed tag; a tag held by another device is transferred.' : 'Flashes the cube and waits for a fresh NFC scan at the station.'} />
      ${(row.uid || row.pending_uid) && html`<${ActionButton} name="pairing.transmit" args=${{ macs: [mac] }} label="Send saved mapping" disabled=${!!reason || !!why('transmit')} reason=${why('transmit') || reason} hazard="Transmits the saved ID/UID; no scan." />`}
      <${ActionButton} name="pairing.flash" args=${{ macs: [mac] }} label="Flash LEDs until Stop" disabled=${!!reason || !!why('flash')} reason=${why('flash') || reason} />
      <${ActionButton} name="pairing.stop" args=${{}} label="Stop" className="btn small" disabled=${!connected} /></div>`}
    ${reason && !excluded && html`<div class="note warn-text">${reason}</div>`}
    ${unavailable.length > 0 && !excluded && html`<div class="note" data-doc="cube.unavailable">${unavailable.map(([what, r]) => html`<div>${what}: ${r}</div>`)}</div>`}
    ${hasNumber && !excluded && html`<div class="row" data-doc="cube.number"><span class="note">Change number</span><${NumberField} value=${row.cube_id} label="" busy=${!!why('rename')} onSubmit=${(n) => run('inventory.rename', { mac, number: n }).then(() => notify(`Renamed to #${n}`, 'ok'))} /></div>`}
    <div class="row"><label class="lbl">Role</label><select class="field" data-doc="inventory.set_role" disabled=${!!why('role')} title=${why('role') || ''} value=${row ? row.role : 'auto'} onChange=${(e) => run('inventory.set_role', { mac, role: e.target.value }).catch((x) => notify(x.message, 'bad'))}>
      <option value="auto">auto (cube)</option><option value="led">LED · manually assigned</option><option value="excluded">Reader / base station (excluded)</option></select>
      ${row && (row.uid || row.cube_id != null) && html`<${HoldButton} name="inventory.unregister" args=${{ mac }} label="Unregister" className="btn danger small" hazard="Releases the number and tags in the inventory only; the cube's firmware is not changed." />`}</div>
  </div>`;
}

export function CubeDetail({ row, mac }) {
  const t = (row && row.telemetry) || {};
  return html`<${KeyValue} items=${[
    ['Assigned number', row && row.cube_id != null ? `#${row.cube_id}` : 'none'],
    ['Original table number', row && row.original_number != null ? `#${row.original_number} · ${row.nfc_seen ? 'NFC scanned here' : 'NFC unseen here'}` : '—'],
    ['MAC', mac], ['Committed tag (uid)', row && row.uid, 'cube.tag'], ['Pending tag', row && row.pending_uid],
    ['Registration', row ? [statusLabel(row.status), row.detail].filter(Boolean).join(' · ') : 'not in the inventory'],
    ['Source / updated', row ? `${row.source} · ${row.updated_at}` : '—'],
    ['Radio', row && row.age_s != null ? `discovery reply ${row.age_s} s ago` : 'no discovery reply this session'],
    ['Last command', t.command ? `${t.command} · ${t.delivery || ''}` : '—'],
  ]} />`;
}

export function CubePanel({ device }) {
  useSections(['devices', 'sessions', 'inventory', 'station', 'builds']);
  const copy = useCopy();
  const TABS = [['overview', 'Overview'], ['firmware', 'Firmware'], ['history', 'History'], ['console', 'Console']];
  const [tab, setTab] = useRouteTab('overview', TABS.map((t) => t[0]));
  const mac = device.mac;
  const row = rowByMac(mac);
  const s = sessionOf(device) || {};
  const fw = device.fw_status || s.fw_status;
  const flags = s.flags || {};
  const label = row && row.cube_id != null ? `Cube #${row.cube_id}` : 'Cube (no number yet)';
  const pills = html`${registrationPill(row)} ${fw && html`<${Pill} status=${'firmware.' + fw.status} label=${`${fw.version || fw.reported || 'unverified'} · ${(copy.status['firmware.' + fw.status] || {}).label || fw.status}`} />`}`;
  return html`<div>
    <${DeviceHeader} device=${device} title=${label} pills=${pills} />
    <${StationBanner} />
    <${Tabs} tabs=${TABS} current=${tab} onChange=${setTab} />
    ${tab === 'overview' && html`<div class="card"><${Explainer} id="cube.overview" />
      <div class="grid2"><div><${LedRing} colour=${ledToken(row && { status: row.status })} label=${row && row.cube_id != null ? `#${row.cube_id}` : '—'} sub=${flags.zone ? `zone ${flags.zone.zone}` : ''} blink=${row && row.telemetry && row.telemetry.command === 'identify'} /></div>
        <div><${CubeDetail} row=${row} mac=${mac} /><${Ladder} doc="cube.ladder" ...${cubeLevel(row)} /></div></div>
      <h3>Registration</h3><${CubeActions} row=${row} mac=${mac} /></div>`}
    ${tab === 'firmware' && html`<div class="card"><${Explainer} id="cube.firmware" />
      <div class="row" data-doc="cube.fw.verdict">${fw ? html`<${Pill} status=${'firmware.' + fw.status} label=${`${fw.version || fw.reported || '?'} · ${(copy.status['firmware.' + fw.status] || {}).label || fw.status}`} /><span class="note">${fw.text || fw.detail || ''}${fw.expected ? ` · local build ${fw.expected}` : ''}</span>` : html`<${Pill} tone="muted" label="unverified" /><span class="note">No "?" answer yet: the version is unverified, not current.</span>`}</div>
      <${KeyValue} items=${[['Reported over USB', fw ? `${fw.version || fw.reported || '?'} (${fw.detail || fw.text || ''})` : 'no "?" answer yet'], ['Local build', (section('builds') || {}).cube ? ((section('builds').cube.version || '?') + ((section('builds').cube.error) ? ' · ' + section('builds').cube.error : '')) : '—'],
        ['Cube says', [flags.unregistered && 'UNREGISTERED', flags.espnow_init_error && 'ESP-NOW INIT ERROR', flags.registered && `REGISTERED #${flags.registered.number}`].filter(Boolean).join(' · ') || 'nothing notable']]} />
      <div class="row"><${ActionButton} name="cube.flash_firmware" args=${{ device: device.id, manual: true }} label="Flash cube firmware" hazard=${copy.actions['cube.flash_firmware']?.hazard} disabled=${device.state === 'job'} />
        <${ActionButton} name="cube.check_boot" args=${{ device: device.id }} label="Check boot (no reflash)" disabled=${device.state === 'job'} /></div>
      <${FlashRuns} mac=${mac} /></div>`}
    ${tab === 'history' && html`<div><div class="card"><div class="row"><${ActionButton} name="cube.check_boot" args=${{ device: device.id }} label="Check boot (no reflash)" disabled=${device.state === 'job'} /><span class="note">Opens the port, reads the boot banner and records the run; nothing is written.</span></div></div><${History} mac=${mac} /></div>`}
    ${tab === 'console' && html`<${RawConsole} device=${device} hint="?" />`}
    <${JobHistory} device=${device} />
  </div>`;
}

export function FlashRuns({ mac }) {
  const runs = ((section('inventory') || {}).flash_runs || []).filter((r) => !mac || r.mac === mac).slice(0, 20);
  const columns = [{ key: 'started_at', label: 'Started', mono: true }, { key: 'version', label: 'Version', mono: true }, { key: 'result', label: 'Result', render: (r) => html`<${Pill} tone=${r.result === 'success' ? 'ok' : r.result === 'running' ? 'info' : 'warn'} label=${r.result} />` }, { key: 'detail', label: 'Detail' }, { key: 'port', label: 'Port', mono: true }];
  return html`<section class="sub"><h3>Flash runs</h3><${DataTable} columns=${columns} rows=${runs} keyOf=${(r) => r.id} empty="No flash runs recorded for this cube" /></section>`;
}

export function History({ mac }) {
  const [data, setData] = useState(null);
  if (data === null) { run('inventory.events', { mac, limit: 200 }).then(setData).catch((e) => setData({ error: e.message })); return html`<div class="card note">Loading…</div>`; }
  if (data.error) return html`<div class="card bad-text">${data.error}</div>`;
  return html`<div class="card" data-doc="cube.history"><h3>Sightings</h3><${KeyValue} items=${(data.sightings || []).map((s) => [s.kind, `${s.at} ${s.detail || ''}`])} />
    <h3>Events</h3><${DataTable} columns=${[{ key: 'time', label: 'Time', mono: true }, { key: 'action', label: 'Action' }, { key: 'detail', label: 'Detail' }]} rows=${data.events || []} keyOf=${(e, i) => e.time + e.action + e.detail} empty="No events" /></div>`;
}
