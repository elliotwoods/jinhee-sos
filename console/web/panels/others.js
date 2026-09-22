// Mainshow controller, pool central, pool test bridge, preshow bridge, range test, unidentified board, this computer.
import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useSections, useCopy } from '../lib/hooks.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, StatTile, ProgressBar, PageHead } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { DataTable, Console, JobCard, PortTable, LogPane } from '../components/data.js';
import { LedRing, Chart, MemberGrid } from '../components/canvas.js';
import { DeviceHeader, sessionOf, RawConsole, JobHistory } from './common.js';
import { ShowControl } from './ShowSection.js';
import { hhmmss, ago, mmss } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { goDevice } from '../router.js';

export function MainshowPanel({ device }) {
  useSections(['devices', 'sessions', 'show']);
  const s = sessionOf(device) || {};
  const info = s.info || {};
  const pills = html`<${Pill} tone=${s.usable ? 'ok' : 'warn'} label=${s.usable ? 'controller ready' : s.connected ? 'wrong firmware' : 'not answering'} /> ${info.channel != null && html`<${Pill} tone=${info.channel === 2 ? 'ok' : 'bad'} label=${`ch ${info.channel}`} />`}`;
  return html`<div><${DeviceHeader} device=${device} title="Mainshow controller" pills=${pills} kv=${[['Firmware', info.firmware], ['Shows started', info.shows], ['Last show id', info.last_show_id], ['Lockout / rearm', info.lockout_ms != null ? `${info.lockout_ms} ms / ${info.rearm_ms} ms` : '—'], ['Problem', s.problem]]} />
    ${s.problem && html`<${Banner} kind="warn" title="Controller problem" detail=${s.problem} />`}
    <${ShowControl} />
    <div class="card"><h3>Controller</h3><div class="row"><${ActionButton} name="mainshow.led_test" args=${{ on: true }} label="LED test on" hazard="Lights the controller's LED." /><${ActionButton} name="mainshow.led_test" args=${{ on: false }} label="LED test off" />
      <${ActionButton} name="dongle.flash" args=${{ device: device.id, firmware: 'mainshow' }} label="Rewrite controller firmware" disabled=${device.state === 'job'} hazard="Writes flash; a first-time full backup is taken." /></div></div>
    <${JobHistory} device=${device} /></div>`;
}

export function PoolCentralPanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  const mask = (m) => Array.from({ length: 23 }, (_, i) => (m >> i) & 1);
  const strip = (m, on) => html`<span class="mono">${mask(m || 0).map((b) => (b ? on : '·')).join('')}</span>`;
  const columns = [{ key: 'id', label: 'Id' }, { key: 'mac', label: 'MAC', mono: true }, { key: 'holding', label: 'Holding' }, { key: 'member', label: 'Member' }, { key: 'seq', label: 'Seq' }, { key: 'lease_ms', label: 'Lease' }, { key: 'legacy', label: 'Legacy', render: (r) => r.legacy ? html`<${Pill} tone="warn" label="legacy packet" />` : '' }, { key: 'seen_ms', label: 'Seen', render: (r) => `${r.seen_ms} ms ago` }];
  return html`<div><${DeviceHeader} device=${device} title="Pool central controller" pills=${html`<${Pill} tone=${st.radio_ready ? 'ok' : 'warn'} label=${st.radio_ready ? 'radio ready' : 'radio?'} /> ${s.status_age_s != null && html`<${Pill} tone=${s.status_age_s < 3 ? 'ok' : 'warn'} label=${`status ${s.status_age_s} s ago`} />`}`} />
    <div class="card"><h3>Telemetry</h3><div class="tiles"><${StatTile} label="RX packets" value=${st.rx_packets} /><${StatTile} label="Legacy" value=${st.rx_legacy} tone=${st.rx_legacy ? 'warn' : ''} /><${StatTile} label="Rejected" value=${st.rx_rejected} /><${StatTile} label="Id clashes" value=${st.id_clashes} tone=${st.id_clashes ? 'bad' : ''} /><${StatTile} label="I²C errors" value=${st.i2c_errors} tone=${st.i2c_errors ? 'bad' : ''} /><${StatTile} label="Mismatches" value=${st.mismatches} tone=${st.mismatches ? 'bad' : ''} /><${StatTile} label="Recoveries" value=${st.recoveries} /><${StatTile} label="Log drops" value=${st.log_drops} /></div>
      <${KeyValue} items=${[['Desired', strip(st.desired, '█')], ['Verified', strip(st.verified, '█')], ['Known', strip(st.known, '█')], ['Boards', (st.boards || []).map((b) => `${b.addr || b.address || '?'}: ${b.online ? 'online' : 'OFFLINE'}`).join(' · ') || '—'], ['SDA / SCL', `${st.sda ?? '?'} / ${st.scl ?? '?'}`]]} />
      <div class="row"><${ActionButton} name="central.recover" args=${{ device: device.id }} label="Recover I²C" hazard="Re-initialises both PCA9685 boards." /></div></div>
    <div class="card"><h3>Radios</h3><${DataTable} columns=${columns} rows=${s.radios || []} keyOf=${(r) => r.mac} empty="No radios heard" /></div>
    <${RawConsole} device=${device} hint="STATUS" /><${JobHistory} device=${device} /></div>`;
}

export function PoolTestBridgePanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  const [channel, setChannel] = useState(st.channel || 2);
  const [interval, setInterval_] = useState(s.interval || 1);
  const live = device.state === 'session';
  return html`<div><${DeviceHeader} device=${device} title="Pool light test bridge" pills=${html`<${Pill} tone=${s.ready ? 'ok' : 'warn'} label=${s.ready ? `ready · channel ${st.channel}` : 'not ready'} />`} />
    <div class="card"><${Explainer} id="pooltest" /><${Banner} kind="warn" title="This bridge emulates pool radios 1-6" detail="Power off the real pool radios before testing; the central will hear this bridge instead." />
      <${MemberGrid} slots=${s.slots || []} disabled=${!live || !s.ready} onToggle=${(m) => run('pooltest.toggle', { device: device.id, member: m }).catch((e) => notify(e.message, 'bad'))} />
      <div class="note">RADIO SLOTS ${(s.slots || []).map((m, i) => `${i + 1}: ${m ? String(m).padStart(2, '0') : '—'}`).join('   ')} · ${s.notice || ''}</div>
      <div class="row"><${ActionButton} name="pooltest.all_off" args=${{ device: device.id }} label="ALL OFF (Esc)" className="btn danger" disabled=${!live} />
        <${ActionButton} name="pooltest.sequential" args=${{ device: device.id, on: !s.scanning, interval: Number(interval) }} label=${s.scanning ? 'Stop sequential test' : 'Sequential test'} hazard="Lights each member in turn." disabled=${!live || !s.ready} />
        <label class="lbl">seconds per light</label><input class="field num" value=${interval} onInput=${(e) => setInterval_(e.target.value)} />
        <label class="lbl">channel</label><input class="field num" value=${channel} onInput=${(e) => setChannel(e.target.value)} /><${ActionButton} name="pooltest.channel" args=${{ device: device.id, channel: Number(channel) }} label="Apply channel" hazard="Refused while any light is on." disabled=${!live} /></div>
      <${KeyValue} items=${[['Bridge', st.mac ? `${st.mac} · queued ${st.queued} · errors ${st.errors}` : '—'], ['Central', st.central_mac ? `${st.central_mac} · beacon ${st.beacon_ms} ms · radio mask ${st.radio_mask}` : 'no beacon heard']]} /></div>
    <${RawConsole} device=${device} hint="STATUS" /></div>`;
}

export function PreshowBridgePanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  return html`<div><${DeviceHeader} device=${device} title="Preshow media bridge (TouchDesigner)" pills=${html`<${Pill} tone=${st.radio === 'ready' || st.radio_ok ? 'ok' : 'muted'} label=${st.version || 'bridge'} />`} />
    <div class="card"><h3>Status</h3><${KeyValue} items=${Object.entries(st).filter(([k]) => !['device', 'type'].includes(k)).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)])} />
      <h3>Points</h3><${DataTable} columns=${[{ key: 'point', label: 'Point' }, { key: 'state', label: 'State' }, { key: 'plate', label: 'Plate', mono: true }, { key: 'seq', label: 'Seq' }]} rows=${Object.values(s.points || {})} keyOf=${(p) => p.point} empty="No point status yet" />
      <h3>Plates</h3><${DataTable} columns=${[{ key: 'mac', label: 'MAC', mono: true }, { key: 'point', label: 'Point' }, { key: 'seen_ms', label: 'Seen' }, { key: 'legacy', label: 'Legacy' }]} rows=${s.plates || []} keyOf=${(p) => p.mac} empty="No plates heard" />
      <div class="row">${[1, 2, 3, 4].map((p) => html`<${ActionButton} name="bridge.test" args=${{ device: device.id, point: p, on: true }} label=${`TEST ${p} ON`} hazard="Writes PRESHOW,n,ON to TouchDesigner." /><${ActionButton} name="bridge.test" args=${{ device: device.id, point: p, on: false }} label=${`${p} OFF`} className="btn small" />`)}</div>
      <h3>Recent cues</h3><div class="log short">${(s.cues || []).map((c) => html`<div>${hhmmss(c.t)} PRESHOW,${c.point},${c.state}</div>`)}</div></div>
    <${RawConsole} device=${device} hint="STATUS" /></div>`;
}

export function RangeTestPanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const stat = s.stat || {};
  const [span, setSpan] = useState(60);
  const rssi = (s.packets || []).map((p) => ({ t: p[0], v: p[1] }));
  const loss = (s.samples || []).map((p) => ({ t: p[0], v: p[1] }));
  const cmd = (name, args) => html`<button class="btn small" onClick=${() => run('device.console', { device: device.id, line: name }).catch((e) => notify(e.message, 'bad'))}>${name}</button>`;
  return html`<div><${DeviceHeader} device=${device} title=${`Range test ${stat.role || (s.banner && s.banner.Role) || ''}`} pills=${html`<${Pill} tone="info" label="nothing written to disk" />`} />
    <div class="card"><${Explainer} id="rangetest" /><div class="tiles"><${StatTile} label="Loss %" value=${stat.loss_pct} tone=${Number(stat.loss_pct) > 5 ? 'warn' : 'ok'} /><${StatTile} label="RSSI avg" value=${stat.rssi_avg} /><${StatTile} label="Noise floor" value=${stat.nf_avg} /><${StatTile} label="Packets" value=${stat.rx ?? stat.packets} /></div>
      <div class="row"><label class="check">Span <select class="field" value=${span} onChange=${(e) => setSpan(Number(e.target.value))}><option value="60">last minute</option><option value="1800">last 30 min</option></select></label></div>
      <div class="grid2"><${Chart} series=${[{ points: rssi, colour: '--chart-1', label: 'RSSI (dBm)' }]} span=${span} unit="" /><${Chart} series=${[{ points: loss, colour: '--chart-2', label: 'loss %' }]} span=${span} min=${0} max=${100} /></div>
      <div class="row"><${LedRing} pixels=${s.pixels} size=${110} label="" sub="" /><div class="note">The board's own 8-LED comet, mirrored. Red = this receiver, blue = the transmitter.</div></div>
      <${KeyValue} items=${Object.entries(s.banner || {}).map(([k, v]) => [k, v])} />
      <div class="row">${['STATUS', 'VERBOSE ON', 'VERBOSE OFF', 'LEDS ON', 'LEDS OFF', 'MUTE', 'RESET'].map((c) => cmd(c))}</div>
      <div class="note">Marks: ${(s.marks || []).map((m) => `${hhmmss(m.t)} ${m.label}`).join(' · ') || 'none (send MARK <label> in the console)'}</div></div>
    <${RawConsole} device=${device} hint="MARK back room" /></div>`;
}

export function UnknownBoardPanel({ device }) {
  useSections(['devices', 'sessions']);
  const copy = useCopy();
  return html`<div><${DeviceHeader} device=${device} title=${device.role_label || 'Unidentified USB board'} />
    <div class="card"><h3>What the probe saw</h3><${KeyValue} items=${[['USB', `${device.description || ''} · serial ${device.serial || '—'} · ${device.native_usb ? 'native ESP32 USB' : 'adapter'}`], ['Candidate ESP32', device.candidate ? 'yes' : 'no (not flashable)'], ['Attempts', device.attempts], ['Inventory', device.presumed && device.presumed.label], ['Bootloader detection', device.detection ? `${device.detection.label} (${device.detection.source})` : 'not read']]} />
      <div class="log short">${(device.transcript || []).length ? device.transcript.map((l) => html`<div>${l}</div>`) : 'no answer on serial'}</div>
      <div class="row"><${ActionButton} name="device.probe" args=${{ device: device.id }} label="Probe again (no reset)" />
        <${ActionButton} name="zone.detect" args=${{ device: device.id }} label="Identify via bootloader" hazard="Reboots the board." disabled=${!device.candidate || device.state === 'job'} />
        <${ActionButton} name="zone.check_report" args=${{ device: device.id }} label="Read zone report" hazard="Opens the port and sends ?" disabled=${device.state === 'job'} /></div></div>
    <div class="card"><h3>Make this board a…</h3><div class="row">
      <${HoldButton} name="dongle.flash" args=${{ device: device.id, firmware: 'dongle' }} label="ESP-NOW dongle (pairing relay)" hazard=${copy.actions['dongle.flash']?.hazard} disabled=${!device.candidate || device.state === 'job'} />
      <${HoldButton} name="dongle.flash" args=${{ device: device.id, firmware: 'mainshow' }} label="Mainshow controller" hazard=${copy.actions['dongle.flash']?.hazard} disabled=${!device.candidate || device.state === 'job'} />
      <${HoldButton} name="dongle.flash" args=${{ device: device.id, firmware: 'general' }} label="General Radio (relay + show + pool + preshow)" hazard=${copy.actions['dongle.flash']?.hazard} disabled=${!device.candidate || device.state === 'job'} />
      <${HoldButton} name="cube.flash_firmware" args=${{ device: device.id, manual: true }} label="Neocore cube" hazard=${copy.actions['cube.flash_firmware']?.hazard} disabled=${!device.candidate || device.state === 'job'} /></div>
      <div class="note">For a zone plate, open the zone identity form: Read zone report first, then the Firmware & database tab appears once the board is identified as a zone. Unidentified boards can also be flashed from the zone form after "Identify via bootloader".</div></div>
    <${JobHistory} device=${device} /></div>`;
}


// Automatic USB intake (This computer): auto-flash cubes / zones for boards plugged in from now on, the zone form
// the legacy sketches take, and the last result per port. Both switches are off at every launch.
export function Intake() {
  useSections(['inventory', 'devices', 'builds']);
  const intake = (section('inventory') || {}).intake || {};
  const builds = section('builds') || {};
  const devices = section('devices') || [];
  const [profiles, setProfiles] = useState(null);
  useEffect(() => { run('zone.profiles').then(setProfiles).catch(() => setProfiles({ profiles: {}, rx_gains: [] })); }, []);
  const form = intake.zone_form || {};
  const options = intake.zone_options || {};
  const results = intake.results || {};
  const setForm = (patch) => run('usb.intake_form', { form: { ...form, ...patch } }).catch((e) => notify(e.message, 'bad'));
  const setOption = (key) => (e) => run('usb.intake_form', { options: { [key]: e.target.checked } }).catch((e) => notify(e.message, 'bad'));
  const profile = profiles && profiles.profiles[form.profile];
  const points = profile ? profile.points : [form.point];
  const cubeBuild = builds.cube || {};
  const portOf = (key) => { const d = devices.find((x) => x.key === key || x.id === key || x.port === key); return d ? d.port : key; };
  const running = devices.filter((d) => d.state === 'job').map((d) => d.port);
  return html`<div class="card" data-doc="computer.intake"><h3>Automatic intake</h3><${Explainer} id="computer.intake" />
    <div class="row">
      <${ActionButton} name="usb.auto_cubes" args=${{ enabled: !intake.cubes_armed }} label=${intake.cubes_armed ? 'Auto-flash cubes · ON' : 'Auto-flash cubes'} className=${'btn physical' + (intake.cubes_armed ? ' on' : '')} disabled=${!intake.cubes_armed && !!cubeBuild.error} reason=${!intake.cubes_armed && cubeBuild.error ? cubeBuild.error : null} hazard="Every candidate board plugged in from now on is written with the bundled cube build (NVS preserved). Remove non-cube boards from the bench first." />
      <${ActionButton} name="usb.auto_zones" args=${{ enabled: !intake.zones_armed }} label=${intake.zones_armed ? 'Auto-flash zones · ON' : 'Auto-flash zones'} className=${'btn physical' + (intake.zones_armed ? ' on' : '')} hazard="Identified zone boards are updated in place; legacy sketches take the zone and point below. Cubes and stations are skipped." />
      <span class="note">${intake.cubes_armed || intake.zones_armed ? `Armed · ${running.length ? 'writing ' + running.join(', ') : 'waiting for the next board'}` : 'Off (the default at every launch)'}</span></div>
    <div class="form">
      <div><label class="lbl">Zone (legacy sketches)</label><select class="field" value=${form.profile} onChange=${(e) => { const p = profiles && profiles.profiles[e.target.value]; const point = p ? p.points[0] : 1; setForm({ profile: e.target.value, point, name: p ? p.name.replace('{point}', point) : form.name }); }}>${profiles ? Object.entries(profiles.profiles).map(([k, p]) => html`<option value=${k}>${p.label}</option>`) : html`<option value=${form.profile}>${form.profile}</option>`}</select></div>
      <div><label class="lbl">Next point</label><select class="field" value=${form.point} onChange=${(e) => { const point = Number(e.target.value); setForm({ point, name: profile ? profile.name.replace('{point}', point) : form.name }); }}>${points.map((p) => html`<option value=${p}>${p}</option>`)}</select></div>
      <div><label class="lbl">Name</label><input class="field" value=${form.name || ''} maxlength="15" onChange=${(e) => setForm({ name: e.target.value })} /></div></div>
    <div class="row">
      <label class="check"><input type="checkbox" checked=${!!options.next_point} onChange=${setOption('next_point')} /> advance the point after each legacy flash</label>
      <label class="check"><input type="checkbox" checked=${!!options.allow_unidentified} onChange=${setOption('allow_unidentified')} /> include unidentified boards (bootloader read only)</label>
      <label class="check"><input type="checkbox" checked=${!!options.database_only} onChange=${setOption('database_only')} /> database-only update for zones that are behind</label></div>
    <div class="note">Stopping either switch lets the write in progress finish; a job is never interrupted mid-flash.</div>
    ${Object.keys(results).length > 0 && html`<div><h3>Last results</h3><${KeyValue} items=${Object.entries(results).map(([k, v]) => [portOf(k), v])} /></div>`}
  </div>`;
}

export function ThisComputerPanel() {
  useSections(['devices', 'builds', 'locks', 'meta', 'settings']);
  const devices = section('devices') || [];
  const builds = section('builds') || {};
  const locks = section('locks') || {};
  const meta = section('meta') || {};
  const tools = builds.tools || {};
  const held = Object.entries(locks).filter(([, v]) => v).map(([k]) => k);
  return html`<div><${PageHead} title="This computer" subtitle=${html`<span class="mono">${meta.database}</span>`} />
    <div class="card"><h3>USB intake</h3><${Explainer} id="devices" /><${PortTable} devices=${devices} onSelect=${(id) => goDevice(id)} />
      <div class="row"><${ActionButton} name="usb.rescan" args=${{}} label="Rescan USB" className="btn small" /><span class="note">Boards are identified automatically without resetting them. Flash from each board's panel, or arm the automatic intake below.</span></div></div>
    <${Intake} />
    <div class="card"><h3>Firmware builds</h3>
      <${DataTable} columns=${[{ key: 'name', label: 'Target' }, { key: 'version', label: 'Version', mono: true }, { key: 'state', label: 'State', render: (r) => html`<${Pill} tone=${r.error ? 'warn' : 'ok'} label=${r.error ? 'rebuild' : 'verified'} tip=${r.error || 'manifest and hashes verified'} />` }, { key: 'error', label: 'Detail' }, { key: 'build', label: '', render: (r) => html`<${ActionButton} name=${r.command} args=${r.args} label="Build" className="btn small" />` }]}
        rows=${[{ name: 'Neocore cube', version: builds.cube?.version, error: builds.cube?.error, command: 'build.cube', args: {} },
          ...Object.entries(builds.zones || {}).map(([k, v]) => ({ name: k, version: v.version, error: v.error, command: 'build.zone', args: { sketch: k } })),
          { name: builds.dongle?.label || 'ESP-NOW dongle', version: builds.dongle?.version, error: builds.dongle?.state === 'current' ? null : builds.dongle?.state, command: 'build.dongle', args: { firmware: 'dongle' } },
          { name: builds.mainshow?.label || 'Mainshow controller', version: builds.mainshow?.version, error: builds.mainshow?.state === 'current' ? null : builds.mainshow?.state, command: 'build.dongle', args: { firmware: 'mainshow' } },
          { name: builds.general?.label || 'General Radio', version: builds.general?.version, error: builds.general?.state === 'current' ? null : builds.general?.state, command: 'build.dongle', args: { firmware: 'general' } }]} keyOf=${(r) => r.name} />
      <${KeyValue} items=${[['esptool', tools.esptool_ok == null ? 'not checked yet' : tools.esptool_ok ? `ok (${tools.esptool_text})` : `PROBLEM: ${tools.esptool_text}`], ['arduino-cli', tools.arduino_cli || 'not found (builds unavailable; flashing verified builds still works)'], ['ESP32 core 3.3.11', tools.core_ok ? 'installed' : 'missing']]} />
      <div class="row"><${ActionButton} name="tools.check" args=${{}} label="Check flashing tool" className="btn small" /><${ActionButton} name="builds.refresh" args=${{}} label="Re-verify manifests" className="btn small" /></div></div>
    <div class="card"><h3>Other apps on this database</h3><div class="note">${held.length ? `Held by another process: ${held.join(', ')} — web downloads wait while those apps run.` : 'No old app holds a lock; the console holds them all while it runs.'}</div></div></div>`;
}
