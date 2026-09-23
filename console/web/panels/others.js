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
import { t } from '../lib/i18n.js';

export function MainshowPanel({ device }) {
  useSections(['devices', 'sessions', 'show']);
  const s = sessionOf(device) || {};
  const info = s.info || {};
  const pills = html`<${Pill} tone=${s.usable ? 'ok' : 'warn'} label=${s.usable ? t('controller ready') : s.connected ? t('wrong firmware') : t('not answering')} /> ${info.channel != null && html`<${Pill} tone=${info.channel === 2 ? 'ok' : 'bad'} label=${t('ch {n}', { n: info.channel })} />`}`;
  return html`<div><${DeviceHeader} device=${device} title="Mainshow controller" pills=${pills} kv=${[[t('Firmware'), info.firmware], [t('Shows started'), info.shows], [t('Last show id'), info.last_show_id], [t('Lockout / rearm'), info.lockout_ms != null ? `${info.lockout_ms} ms / ${info.rearm_ms} ms` : '—'], [t('Problem'), s.problem]]} />
    ${s.problem && html`<${Banner} kind="warn" title=${t('Controller problem')} detail=${s.problem} />`}
    <${ShowControl} />
    <div class="card"><h3>${t('Controller')}</h3><div class="row"><${ActionButton} name="mainshow.led_test" args=${{ on: true }} label=${t('LED test on')} hazard=${t('Lights the controller\'s LED.')} /><${ActionButton} name="mainshow.led_test" args=${{ on: false }} label=${t('LED test off')} />
      <${ActionButton} name="dongle.flash" args=${{ device: device.id, firmware: 'mainshow' }} label=${t('Rewrite controller firmware')} disabled=${device.state === 'job'} hazard=${t('Writes flash; a first-time full backup is taken.')} /></div></div>
    <${JobHistory} device=${device} /></div>`;
}

export function PoolCentralPanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  const mask = (m) => Array.from({ length: 23 }, (_, i) => (m >> i) & 1);
  const strip = (m, on) => html`<span class="mono">${mask(m || 0).map((b) => (b ? on : '·')).join('')}</span>`;
  const columns = [{ key: 'id', label: t('Id') }, { key: 'mac', label: 'MAC', mono: true }, { key: 'holding', label: t('Holding') }, { key: 'member', label: t('Member') }, { key: 'seq', label: t('Seq') }, { key: 'lease_ms', label: t('Lease') }, { key: 'legacy', label: t('Legacy'), render: (r) => r.legacy ? html`<${Pill} tone="warn" label=${t('legacy packet')} />` : '' }, { key: 'seen_ms', label: t('Seen'), render: (r) => t('{n} ms ago', { n: r.seen_ms }) }];
  return html`<div><${DeviceHeader} device=${device} title=${t('Pool central controller')} pills=${html`<${Pill} tone=${st.radio_ready ? 'ok' : 'warn'} label=${st.radio_ready ? t('radio ready') : t('radio?')} /> ${s.status_age_s != null && html`<${Pill} tone=${s.status_age_s < 3 ? 'ok' : 'warn'} label=${t('status {n} s ago', { n: s.status_age_s })} />`}`} />
    <div class="card"><h3>${t('Telemetry')}</h3><div class="tiles"><${StatTile} label=${t('RX packets')} value=${st.rx_packets} /><${StatTile} label=${t('Legacy')} value=${st.rx_legacy} tone=${st.rx_legacy ? 'warn' : ''} /><${StatTile} label=${t('Rejected')} value=${st.rx_rejected} /><${StatTile} label=${t('Id clashes')} value=${st.id_clashes} tone=${st.id_clashes ? 'bad' : ''} /><${StatTile} label=${t('I²C errors')} value=${st.i2c_errors} tone=${st.i2c_errors ? 'bad' : ''} /><${StatTile} label=${t('Mismatches')} value=${st.mismatches} tone=${st.mismatches ? 'bad' : ''} /><${StatTile} label=${t('Recoveries')} value=${st.recoveries} /><${StatTile} label=${t('Log drops')} value=${st.log_drops} /></div>
      <${KeyValue} items=${[[t('Desired'), strip(st.desired, '█')], [t('Verified'), strip(st.verified, '█')], [t('Known'), strip(st.known, '█')], [t('Boards'), (st.boards || []).map((b) => `${b.addr || b.address || '?'}: ${b.online ? t('online') : t('OFFLINE')}`).join(' · ') || '—'], ['SDA / SCL', `${st.sda ?? '?'} / ${st.scl ?? '?'}`]]} />
      <div class="row"><${ActionButton} name="central.recover" args=${{ device: device.id }} label=${t('Recover I²C')} hazard=${t('Re-initialises both PCA9685 boards.')} /></div></div>
    <div class="card"><h3>${t('Radios')}</h3><${DataTable} columns=${columns} rows=${s.radios || []} keyOf=${(r) => r.mac} empty=${t('No radios heard')} /></div>
    <${RawConsole} device=${device} hint="STATUS" /><${JobHistory} device=${device} /></div>`;
}

export function PoolTestBridgePanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  const [channel, setChannel] = useState(st.channel || 2);
  const [interval, setInterval_] = useState(s.interval || 1);
  const live = device.state === 'session';
  return html`<div><${DeviceHeader} device=${device} title=${t('Pool light test bridge')} pills=${html`<${Pill} tone=${s.ready ? 'ok' : 'warn'} label=${s.ready ? t('ready · channel {n}', { n: st.channel }) : t('not ready')} />`} />
    <div class="card"><${Explainer} id="pooltest" /><${Banner} kind="warn" title=${t('This bridge emulates pool radios 1-6')} detail=${t('Power off the real pool radios before testing; the central will hear this bridge instead.')} />
      <${MemberGrid} slots=${s.slots || []} disabled=${!live || !s.ready} onToggle=${(m) => run('pooltest.toggle', { device: device.id, member: m }).catch((e) => notify(e.message, 'bad'))} />
      <div class="note">${t('RADIO SLOTS')} ${(s.slots || []).map((m, i) => `${i + 1}: ${m ? String(m).padStart(2, '0') : '—'}`).join('   ')} · ${s.notice || ''}</div>
      <div class="row"><${ActionButton} name="pooltest.all_off" args=${{ device: device.id }} label=${t('ALL OFF (Esc)')} className="btn danger" disabled=${!live} />
        <${ActionButton} name="pooltest.sequential" args=${{ device: device.id, on: !s.scanning, interval: Number(interval) }} label=${s.scanning ? t('Stop sequential test') : t('Sequential test')} hazard=${t('Lights each member in turn.')} disabled=${!live || !s.ready} />
        <label class="lbl">${t('seconds per light')}</label><input class="field num" value=${interval} onInput=${(e) => setInterval_(e.target.value)} />
        <label class="lbl">${t('channel')}</label><input class="field num" value=${channel} onInput=${(e) => setChannel(e.target.value)} /><${ActionButton} name="pooltest.channel" args=${{ device: device.id, channel: Number(channel) }} label=${t('Apply channel')} hazard=${t('Refused while any light is on.')} disabled=${!live} /></div>
      <${KeyValue} items=${[[t('Bridge'), st.mac ? t('{mac} · queued {queued} · errors {errors}', { mac: st.mac, queued: st.queued, errors: st.errors }) : '—'], [t('Central'), st.central_mac ? t('{mac} · beacon {ms} ms · radio mask {mask}', { mac: st.central_mac, ms: st.beacon_ms, mask: st.radio_mask }) : t('no beacon heard')]]} /></div>
    <${RawConsole} device=${device} hint="STATUS" /></div>`;
}

export function PreshowBridgePanel({ device }) {
  useSections(['devices', 'sessions']);
  const s = sessionOf(device) || {};
  const st = s.status || {};
  return html`<div><${DeviceHeader} device=${device} title=${t('Preshow media bridge (TouchDesigner)')} pills=${html`<${Pill} tone=${st.radio === 'ready' || st.radio_ok ? 'ok' : 'muted'} label=${st.version || t('bridge')} />`} />
    <div class="card"><h3>${t('Status')}</h3><${KeyValue} items=${Object.entries(st).filter(([k]) => !['device', 'type'].includes(k)).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)])} />
      <h3>${t('Points')}</h3><${DataTable} columns=${[{ key: 'point', label: t('Point') }, { key: 'state', label: t('State') }, { key: 'plate', label: t('Plate'), mono: true }, { key: 'seq', label: t('Seq') }]} rows=${Object.values(s.points || {})} keyOf=${(p) => p.point} empty=${t('No point status yet')} />
      <h3>${t('Plates')}</h3><${DataTable} columns=${[{ key: 'mac', label: 'MAC', mono: true }, { key: 'point', label: t('Point') }, { key: 'seen_ms', label: t('Seen') }, { key: 'legacy', label: t('Legacy') }]} rows=${s.plates || []} keyOf=${(p) => p.mac} empty=${t('No plates heard')} />
      <div class="row">${[1, 2, 3, 4].map((p) => html`<${ActionButton} name="bridge.test" args=${{ device: device.id, point: p, on: true }} label=${t('TEST {n} ON', { n: p })} hazard=${t('Writes PRESHOW,n,ON to TouchDesigner.')} /><${ActionButton} name="bridge.test" args=${{ device: device.id, point: p, on: false }} label=${t('{n} OFF', { n: p })} className="btn small" />`)}</div>
      <h3>${t('Recent cues')}</h3><div class="log short">${(s.cues || []).map((c) => html`<div>${hhmmss(c.t)} PRESHOW,${c.point},${c.state}</div>`)}</div></div>
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
  return html`<div><${DeviceHeader} device=${device} title=${t('Range test {role}', { role: stat.role || (s.banner && s.banner.Role) || '' })} pills=${html`<${Pill} tone="info" label=${t('nothing written to disk')} />`} />
    <div class="card"><${Explainer} id="rangetest" /><div class="tiles"><${StatTile} label=${t('Loss %')} value=${stat.loss_pct} tone=${Number(stat.loss_pct) > 5 ? 'warn' : 'ok'} /><${StatTile} label=${t('RSSI avg')} value=${stat.rssi_avg} /><${StatTile} label=${t('Noise floor')} value=${stat.nf_avg} /><${StatTile} label=${t('Packets')} value=${stat.rx ?? stat.packets} /></div>
      <div class="row"><label class="check">${t('Span')} <select class="field" value=${span} onChange=${(e) => setSpan(Number(e.target.value))}><option value="60">${t('last minute')}</option><option value="1800">${t('last 30 min')}</option></select></label></div>
      <div class="grid2"><${Chart} series=${[{ points: rssi, colour: '--chart-1', label: t('RSSI (dBm)') }]} span=${span} unit="" /><${Chart} series=${[{ points: loss, colour: '--chart-2', label: t('loss %') }]} span=${span} min=${0} max=${100} /></div>
      <div class="row"><${LedRing} pixels=${s.pixels} size=${110} label="" sub="" /><div class="note">${t('The board\'s own 8-LED comet, mirrored. Red = this receiver, blue = the transmitter.')}</div></div>
      <${KeyValue} items=${Object.entries(s.banner || {}).map(([k, v]) => [k, v])} />
      <div class="row">${['STATUS', 'VERBOSE ON', 'VERBOSE OFF', 'LEDS ON', 'LEDS OFF', 'MUTE', 'RESET'].map((c) => cmd(c))}</div>
      <div class="note">${t('Marks:')} ${(s.marks || []).map((m) => `${hhmmss(m.t)} ${m.label}`).join(' · ') || t('none (send MARK <label> in the console)')}</div></div>
    <${RawConsole} device=${device} hint="MARK back room" /></div>`;
}

export function UnknownBoardPanel({ device }) {
  useSections(['devices', 'sessions']);
  const copy = useCopy();
  return html`<div><${DeviceHeader} device=${device} title=${device.role_label || t('Unidentified USB board')} />
    <div class="card"><h3>${t('What the probe saw')}</h3><${KeyValue} items=${[['USB', `${device.description || ''} · ${t('serial {serial}', { serial: device.serial || '—' })} · ${device.native_usb ? t('native ESP32 USB') : t('adapter')}`], [t('Candidate ESP32'), device.candidate ? t('yes') : t('no (not flashable)')], [t('Attempts'), device.attempts], [t('Inventory'), device.presumed && device.presumed.label], [t('Bootloader detection'), device.detection ? `${device.detection.label} (${device.detection.source})` : t('not read')]]} />
      <div class="log short">${(device.transcript || []).length ? device.transcript.map((l) => html`<div>${l}</div>`) : t('no answer on serial')}</div>
      <div class="row"><${ActionButton} name="device.probe" args=${{ device: device.id }} label=${t('Probe again (no reset)')} />
        <${ActionButton} name="zone.detect" args=${{ device: device.id }} label=${t('Identify via bootloader')} hazard=${t('Reboots the board.')} disabled=${!device.candidate || device.state === 'job'} />
        <${ActionButton} name="zone.check_report" args=${{ device: device.id }} label=${t('Read zone report')} hazard=${t('Opens the port and sends ?')} disabled=${device.state === 'job'} /></div></div>
    <div class="card"><h3>${t('Make this board a…')}</h3><div class="row">
      <${HoldButton} name="dongle.flash" args=${{ device: device.id, firmware: 'workstation' }} label=${t('Workstation: pairing reader + zone relay + cube colours + show + pool lamp + preshow cue')} hazard=${copy.actions['dongle.flash']?.hazard} disabled=${!device.candidate || device.state === 'job'} />
      <${HoldButton} name="dongle.flash" args=${{ device: device.id, firmware: 'mainshow' }} label="Mainshow controller" hazard=${copy.actions['dongle.flash']?.hazard} disabled=${!device.candidate || device.state === 'job'} />
      <${HoldButton} name="cube.flash_firmware" args=${{ device: device.id, manual: true }} label=${t('Neocore cube')} hazard=${copy.actions['cube.flash_firmware']?.hazard} disabled=${!device.candidate || device.state === 'job'} /></div>
      <div class="note">${t('For a zone plate, open the zone identity form: Read zone report first, then the Firmware & database tab appears once the board is identified as a zone. Unidentified boards can also be flashed from the zone form after "Identify via bootloader".')}</div></div>
    <${JobHistory} device=${device} /></div>`;
}


// Automatic USB intake (This computer): auto-flash cubes / zones for boards plugged in from now on, the zone form
// the legacy sketches take, and the last result per port. Both switches are off at every launch.
export function Intake() {
  useSections(['inventory', 'devices', 'builds']);
  const intake = (section('inventory') || {}).intake || {};
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
  const portOf = (key) => { const d = devices.find((x) => x.key === key || x.id === key || x.port === key); return d ? d.port : key; };
  const running = devices.filter((d) => d.state === 'job').map((d) => d.port);
  return html`<div class="card" data-doc="computer.intake"><h3>${t('Automatic intake')}</h3><${Explainer} id="computer.intake" />
    <div class="row">
      <a class=${'btn physical' + (intake.cubes_armed ? ' on' : '')} href="#/flash" title=${t('Cubes are flashed from the Flash page: firmware and the published show')}>${intake.cubes_armed ? t('Flash cubes · ON (Flash page)') : t('Flash cubes → Flash page')}</a>
      <${ActionButton} name="usb.auto_zones" args=${{ enabled: !intake.zones_armed }} label=${intake.zones_armed ? t('Auto-flash zones · ON') : t('Auto-flash zones')} className=${'btn physical' + (intake.zones_armed ? ' on' : '')} hazard=${t('Identified zone boards are updated in place; legacy sketches take the zone and point below. Cubes and stations are skipped.')} />
      <span class="note">${intake.cubes_armed || intake.zones_armed ? (running.length ? t('Armed · writing {ports}', { ports: running.join(', ') }) : t('Armed · waiting for the next board')) : t('Off (the default at every launch)')}</span></div>
    <div class="form">
      <div><label class="lbl">${t('Zone (legacy sketches)')}</label><select class="field" value=${form.profile} onChange=${(e) => { const p = profiles && profiles.profiles[e.target.value]; const point = p ? p.points[0] : 1; setForm({ profile: e.target.value, point, name: p ? p.name.replace('{point}', point) : form.name }); }}>${profiles ? Object.entries(profiles.profiles).map(([k, p]) => html`<option value=${k}>${p.label}</option>`) : html`<option value=${form.profile}>${form.profile}</option>`}</select></div>
      <div><label class="lbl">${t('Next point')}</label><select class="field" value=${form.point} onChange=${(e) => { const point = Number(e.target.value); setForm({ point, name: profile ? profile.name.replace('{point}', point) : form.name }); }}>${points.map((p) => html`<option value=${p}>${p}</option>`)}</select></div>
      <div><label class="lbl">${t('Name')}</label><input class="field" value=${form.name || ''} maxlength="15" onChange=${(e) => setForm({ name: e.target.value })} /></div></div>
    <div class="row">
      <label class="check"><input type="checkbox" checked=${!!options.next_point} onChange=${setOption('next_point')} /> ${t('advance the point after each legacy flash')}</label>
      <label class="check"><input type="checkbox" checked=${!!options.allow_unidentified} onChange=${setOption('allow_unidentified')} /> ${t('include unidentified boards (bootloader read only)')}</label>
      <label class="check"><input type="checkbox" checked=${!!options.database_only} onChange=${setOption('database_only')} /> ${t('database-only update for zones that are behind')}</label></div>
    <div class="note">${t('Stopping either switch lets the write in progress finish; a job is never interrupted mid-flash.')}</div>
    ${Object.keys(results).length > 0 && html`<div><h3>${t('Last results')}</h3><${KeyValue} items=${Object.entries(results).map(([k, v]) => [portOf(k), v])} /></div>`}
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
  return html`<div><${PageHead} title=${t('This computer')} subtitle=${html`<span class="mono">${meta.database}</span>`} />
    <div class="card"><h3>${t('USB intake')}</h3><${Explainer} id="devices" /><${PortTable} devices=${devices} onSelect=${(id) => goDevice(id)} />
      <div class="row"><${ActionButton} name="usb.rescan" args=${{}} label=${t('Rescan USB')} className="btn small" /><span class="note">${t('Boards are identified automatically without resetting them. Flash from each board\'s panel, or arm the automatic intake below.')}</span></div></div>
    <${Intake} />
    <div class="card"><h3>${t('Firmware builds')}</h3>
      <${DataTable} columns=${[{ key: 'name', label: t('Target') }, { key: 'version', label: t('Version'), mono: true }, { key: 'state', label: t('State'), render: (r) => html`<${Pill} tone=${r.error ? 'warn' : 'ok'} label=${r.error ? t('rebuild') : t('verified')} tip=${r.error || t('manifest and hashes verified')} />` }, { key: 'error', label: t('Detail') }, { key: 'build', label: '', render: (r) => html`<${ActionButton} name=${r.command} args=${r.args} label=${t('Build')} className="btn small" />` }]}
        rows=${[{ name: t('Neocore cube'), version: builds.cube?.version, error: builds.cube?.error, command: 'build.cube', args: {} },
          ...Object.entries(builds.zones || {}).map(([k, v]) => ({ name: k, version: v.version, error: v.error, command: 'build.zone', args: { sketch: k } })),
          { name: builds.workstation?.label || 'Workstation', version: builds.workstation?.version, error: builds.workstation?.state === 'current' ? null : builds.workstation?.state, command: 'build.dongle', args: { firmware: 'workstation' } },
          { name: builds.mainshow?.label || 'Mainshow controller', version: builds.mainshow?.version, error: builds.mainshow?.state === 'current' ? null : builds.mainshow?.state, command: 'build.dongle', args: { firmware: 'mainshow' } }]} keyOf=${(r) => r.name} />
      <${KeyValue} items=${[['esptool', tools.esptool_ok == null ? t('not checked yet') : tools.esptool_ok ? t('ok ({text})', { text: tools.esptool_text }) : t('PROBLEM: {text}', { text: tools.esptool_text })], ['arduino-cli', tools.arduino_cli || t('not found (builds unavailable; flashing verified builds still works)')], ['ESP32 core 3.3.11', tools.core_ok ? t('installed') : t('missing')]]} />
      <div class="row"><${ActionButton} name="tools.check" args=${{}} label=${t('Check flashing tool')} className="btn small" /><${ActionButton} name="builds.refresh" args=${{}} label=${t('Re-verify manifests')} className="btn small" /></div></div>
    <div class="card"><h3>${t('Other apps on this database')}</h3><div class="note">${held.length ? t('Held by another process: {apps} — web downloads wait while those apps run.', { apps: held.join(', ') }) : t('No old app holds a lock; the console holds them all while it runs.')}</div></div></div>`;
}
