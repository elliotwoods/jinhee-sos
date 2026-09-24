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
import { t, tk } from '../lib/i18n.js';

// The show the cube's "?" answer reported (cube v1.5.0+: `SHOW: v=… crc=… src=nvs|builtin`).
function showText(show) {
  if (!show) return t('not reported (firmware before v1.5.0, or no "?" answer yet)');
  return show.source === 'nvs' ? t('v{version} from NVS (crc {crc})', { version: show.version, crc: show.crc.toString(16).padStart(8, '0') }) : t('the built-in show (compiled into the firmware)');
}

// A registration status as words (uitext STATUS label, else the enum humanised): shown on cards and detail rows.
const STATUS_WORDS = { awaiting_tag: tk('awaiting tag'), not_transmitted: tk('saved, not sent'), acknowledged: tk('acknowledged'), unconfirmed: tk('unconfirmed'), needs_number: tk('needs a number'), pending: tk('pending'), discovered: tk('discovered') };
export function statusLabel(status) {
  if (!status) return '—';
  const entry = (state.copy && state.copy.status && state.copy.status['registration.' + status]) || null;
  return (entry && entry.label) || (STATUS_WORDS[status] && t(STATUS_WORDS[status])) || String(status).replace(/_/g, ' ');
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
  if (!row) return { level: null, note: t('not in the inventory') };
  const tel = row.telemetry || {};
  if (row.status === 'acknowledged') return { level: 'acknowledged', note: t('the cube acknowledged its mapping; verified would need a read-back') };
  if (tel.delivery === 'failed' || tel.delivery === 'not delivered') return { level: 'sent', failed: true, note: t('{command}: no radio delivery', { command: tel.command || t('last command') }) };
  if (tel.delivery === 'delivered') return { level: 'delivered', note: t('{command}: radio ACK, not yet acknowledged by the cube', { command: tel.command || t('last command') }) };
  if (['pending', 'unconfirmed', 'not_transmitted'].includes(row.status)) return { level: 'sent', note: t('{status}: no acknowledgment recorded', { status: statusLabel(row.status) }) };
  return { level: null, note: t('nothing in flight') };
}

// The registration/identity block shared by the Cube USB panel and the inventory row detail.
export function CubeActions({ row, mac }) {
  useSections(['station', 'inventory']);
  const st = section('station') || {};
  const inv = section('inventory') || {};
  const connected = st.present && st.connected;
  const busy = connected && st.mode && st.mode !== 'reader_flash';   // the tag-read flash gives way
  const reason = !st.present ? t('No pairing station connected') : !st.connected ? t('Station not connected') : !st.reader_ok ? t('NFC reader unavailable on the station') : busy ? t('Station busy: {mode}', { mode: st.mode }) : null;
  const excluded = row && row.role === 'excluded';
  const hasNumber = row && row.cube_id != null;
  // The pairing app's button rules, computed on the owner thread (state.capabilities): why each action is off.
  const cap = (row && row.capabilities) || {};
  const why = (name) => (cap[name] && !cap[name].enabled ? cap[name].reason : null);
  const unavailable = [[t('Register'), why('register')], [t('Send saved mapping'), row && (row.uid || row.pending_uid) ? why('transmit') : null], [t('Flash'), why('flash')], [t('Rename'), why('rename')], [t('Role'), why('role')]].filter(([, r]) => r);
  return html`<div class="stack">
    ${excluded && html`<div class="note">${t('Excluded (reader / base station): registration and LED actions are not offered.')}</div>`}
    ${!hasNumber && !excluded && html`<div><div class="note">${t('This device needs its physical label number before it can be registered.')}</div>
      <div data-doc="cube.number"><${NumberField} suggested=${inv.suggested_number} busy=${!!why('rename')} onSubmit=${(n) => run('inventory.rename', { mac, number: n }).then(() => notify(t('Number {n} assigned', { n }), 'ok'))} /></div></div>`}
    ${hasNumber && !excluded && html`<div class="row">
      <${ActionButton} name="pairing.register" args=${{ mac }} label=${row.uid ? t('Replace tag (scan)') : t('Register (scan a tag)')} className="btn primary" disabled=${!!reason || !!why('register') || !st.reader_ok} reason=${why('register') || reason} hazard=${row.uid ? t('A new scan replaces this cube\'s committed tag; a tag held by another device is transferred.') : t('Flashes the cube and waits for a fresh NFC scan at the station.')} />
      ${(row.uid || row.pending_uid) && html`<${ActionButton} name="pairing.transmit" args=${{ macs: [mac] }} label=${t('Send saved mapping')} disabled=${!!reason || !!why('transmit')} reason=${why('transmit') || reason} hazard=${t('Transmits the saved ID/UID; no scan.')} />`}
      <${ActionButton} name="pairing.flash" args=${{ macs: [mac] }} label=${t('Flash LEDs until Stop')} disabled=${!!reason || !!why('flash')} reason=${why('flash') || reason} />
      <${ActionButton} name="pairing.stop" args=${{}} label=${t('Stop')} className="btn small" disabled=${!connected} /></div>`}
    ${reason && !excluded && html`<div class="note warn-text">${reason}</div>`}
    ${unavailable.length > 0 && !excluded && html`<div class="note" data-doc="cube.unavailable">${unavailable.map(([what, r]) => html`<div>${what}: ${r}</div>`)}</div>`}
    ${hasNumber && !excluded && html`<div class="row" data-doc="cube.number"><span class="note">${t('Change number')}</span><${NumberField} value=${row.cube_id} label="" busy=${!!why('rename')} onSubmit=${(n) => run('inventory.rename', { mac, number: n }).then(() => notify(t('Renamed to #{n}', { n }), 'ok'))} /></div>`}
    <div class="row"><label class="lbl">${t('Role')}</label><select class="field" data-doc="inventory.set_role" disabled=${!!why('role')} title=${why('role') || ''} value=${row ? row.role : 'auto'} onChange=${(e) => run('inventory.set_role', { mac, role: e.target.value }).catch((x) => notify(x.message, 'bad'))}>
      <option value="auto">${t('auto (cube)')}</option><option value="led">${t('LED · manually assigned')}</option><option value="excluded">${t('Reader / base station (excluded)')}</option></select>
      ${row && (row.uid || row.cube_id != null) && html`<${HoldButton} name="inventory.unregister" args=${{ mac }} label=${t('Unregister')} className="btn danger small" hazard=${t('Releases the number and tags in the inventory only; the cube\'s firmware is not changed.')} />`}</div>
  </div>`;
}

export function CubeDetail({ row, mac }) {
  const tel = (row && row.telemetry) || {};
  return html`<${KeyValue} items=${[
    [t('Assigned number'), row && row.cube_id != null ? `#${row.cube_id}` : t('none')],
    [t('Original table number'), row && row.original_number != null ? `#${row.original_number} · ${row.nfc_seen ? t('NFC scanned here') : t('NFC unseen here')}` : '—'],
    ['MAC', mac], [t('Committed tag (uid)'), row && row.uid, 'cube.tag'], [t('Pending tag'), row && row.pending_uid],
    [t('Registration'), row ? [statusLabel(row.status), row.detail].filter(Boolean).join(' · ') : t('not in the inventory')],
    [t('Source / updated'), row ? `${row.source} · ${row.updated_at}` : '—'],
    [t('Radio'), row && row.age_s != null ? t('discovery reply {n} s ago', { n: row.age_s }) : t('no discovery reply this session')],
    [t('Last command'), tel.command ? `${tel.command} · ${tel.delivery || ''}` : '—'],
  ]} />`;
}

export function CubePanel({ device }) {
  useSections(['devices', 'sessions', 'inventory', 'station', 'builds']);
  const copy = useCopy();
  const TABS = [['overview', t('Overview')], ['firmware', t('Firmware')], ['history', t('History')], ['console', t('Console')]];
  const [tab, setTab] = useRouteTab('overview', TABS.map((x) => x[0]));
  const mac = device.mac;
  const row = rowByMac(mac);
  const s = sessionOf(device) || {};
  const fw = device.fw_status || s.fw_status;
  const flags = s.flags || {};
  const label = row && row.cube_id != null ? t('Cube #{n}', { n: row.cube_id }) : t('Cube (no number yet)');
  const pills = html`${registrationPill(row)} ${fw && html`<${Pill} status=${'firmware.' + fw.status} label=${`${fw.version || fw.reported || t('unverified')} · ${(copy.status['firmware.' + fw.status] || {}).label || fw.status}`} />`}`;
  return html`<div>
    <${DeviceHeader} device=${device} title=${label} pills=${pills} />
    <${StationBanner} />
    <${Tabs} tabs=${TABS} current=${tab} onChange=${setTab} />
    ${tab === 'overview' && html`<div class="card"><${Explainer} id="cube.overview" />
      <div class="grid2"><div><${LedRing} colour=${ledToken(row && { status: row.status })} label=${row && row.cube_id != null ? `#${row.cube_id}` : '—'} sub=${flags.zone ? t('zone {n}', { n: flags.zone.zone }) : ''} blink=${row && row.telemetry && row.telemetry.command === 'identify'} /></div>
        <div><${CubeDetail} row=${row} mac=${mac} /><${Ladder} doc="cube.ladder" ...${cubeLevel(row)} /></div></div>
      <h3>${t('Registration')}</h3><${CubeActions} row=${row} mac=${mac} /></div>`}
    ${tab === 'firmware' && html`<div class="card"><${Explainer} id="cube.firmware" />
      <div class="row" data-doc="cube.fw.verdict">${fw ? html`<${Pill} status=${'firmware.' + fw.status} label=${`${fw.version || fw.reported || '?'} · ${(copy.status['firmware.' + fw.status] || {}).label || fw.status}`} /><span class="note">${fw.text || fw.detail || ''}${fw.expected ? ` · ${t('local build {v}', { v: fw.expected })}` : ''}</span>` : html`<${Pill} tone="muted" label=${t('unverified')} /><span class="note">${t('No "?" answer yet: the version is unverified, not current.')}</span>`}</div>
      <${KeyValue} items=${[[t('Reported over USB'), fw ? `${fw.version || fw.reported || '?'} (${fw.detail || fw.text || ''})` : t('no "?" answer yet')], [t('Local build'), (section('builds') || {}).cube ? ((section('builds').cube.version || '?') + ((section('builds').cube.error) ? ' · ' + section('builds').cube.error : '')) : '—'],
        [t('Cube says'), [flags.unregistered && 'UNREGISTERED', flags.espnow_init_error && 'ESP-NOW INIT ERROR', flags.registered && `REGISTERED #${flags.registered.number}`].filter(Boolean).join(' · ') || t('nothing notable')],
        [t('Main show'), showText(device.details && device.details.show)]]} />
      <div class="row"><${ActionButton} name="cube.flash_firmware" args=${{ device: device.id, manual: true }} label=${t('Flash cube firmware')} hazard=${copy.actions['cube.flash_firmware']?.hazard} disabled=${device.state === 'job'} />
        <${ActionButton} name="cube.update_show" args=${{ device: device.id }} label=${t('Update show over USB')} hazard=${copy.actions['cube.update_show']?.hazard} disabled=${device.state === 'job' || device.role !== 'cube'} reason=${t('Identify the cube over USB first')} />
        <${ActionButton} name="cube.check_boot" args=${{ device: device.id }} label=${t('Check boot (no reflash)')} disabled=${device.state === 'job'} /></div>
      <${FlashRuns} mac=${mac} /></div>`}
    ${tab === 'history' && html`<div><div class="card"><div class="row"><${ActionButton} name="cube.check_boot" args=${{ device: device.id }} label=${t('Check boot (no reflash)')} disabled=${device.state === 'job'} /><span class="note">${t('Opens the port, reads the boot banner and records the run; nothing is written.')}</span></div></div><${History} mac=${mac} /></div>`}
    ${tab === 'console' && html`<${RawConsole} device=${device} hint="?" />`}
    <${JobHistory} device=${device} />
  </div>`;
}

export function FlashRuns({ mac }) {
  const runs = ((section('inventory') || {}).flash_runs || []).filter((r) => !mac || r.mac === mac).slice(0, 20);
  const columns = [{ key: 'started_at', label: t('Started'), mono: true }, { key: 'version', label: t('Version'), mono: true }, { key: 'result', label: t('Result'), render: (r) => html`<${Pill} tone=${r.result === 'success' ? 'ok' : r.result === 'running' ? 'info' : 'warn'} label=${r.result} />` }, { key: 'detail', label: t('Detail') }, { key: 'port', label: t('Port'), mono: true }];
  return html`<section class="sub"><h3>${t('Flash runs')}</h3><${DataTable} columns=${columns} rows=${runs} keyOf=${(r) => r.id} empty=${t('No flash runs recorded for this cube')} /></section>`;
}

export function History({ mac }) {
  const [data, setData] = useState(null);
  if (data === null) { run('inventory.events', { mac, limit: 200 }).then(setData).catch((e) => setData({ error: e.message })); return html`<div class="card note">${t('Loading…')}</div>`; }
  if (data.error) return html`<div class="card bad-text">${data.error}</div>`;
  return html`<div class="card" data-doc="cube.history"><h3>${t('Sightings')}</h3><${KeyValue} items=${(data.sightings || []).map((s) => [s.kind, `${s.at} ${s.detail || ''}`])} />
    <h3>${t('Events')}</h3><${DataTable} columns=${[{ key: 'time', label: t('Time'), mono: true }, { key: 'action', label: t('Action') }, { key: 'detail', label: t('Detail') }]} rows=${data.events || []} keyOf=${(e, i) => e.time + e.action + e.detail} empty=${t('No events')} /></div>`;
}
