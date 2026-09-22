import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useSections, useCopy, useRouteTab } from '../lib/hooks.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, Tabs, StatTile } from '../components/basics.js';
import { ActionButton, HoldButton, LeaseToggle } from '../components/actions.js';
import { DataTable, Console, JobCard } from '../components/data.js';
import { LedRing, BandDiagram, Chart } from '../components/canvas.js';
import { DeviceHeader, sessionOf, rowByMac, rowByNumber, RawConsole, JobHistory } from './common.js';
import { hhmmss, crc, ago } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';

const ZONE_NAMES = { 0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow' };

function registryText(cubeId) {
  const row = rowByNumber(cubeId);
  return row ? `#${cubeId} · ${row.status}` : 'not in inventory';
}

export function Monitor({ device, s }) {
  const [selected, setSelected] = useState(null);
  const current = s.current;
  const entry = current || (selected && (s.history || []).find((h) => String(h.time) === selected)) || null;
  const cubeId = entry ? entry.cube_id : null;
  const cube = cubeId ? (s.cubes || {})[String(cubeId)] : null;
  const display = (cube && cube.display) || { label: 'unknown', colour: '--led-off', note: 'no command sent yet' };
  const zoneName = (v) => (s.zone_colors && s.zone_colors[v] ? s.zone_colors[v][0] : '?');
  const live = device.state === 'session';
  const act = (name, { label, hazard, ...extra }) => html`<${ActionButton} name=${name} args=${{ device: device.id, cube_id: cubeId, ...extra }} label=${label} className="btn small" disabled=${!cubeId || !live} hazard=${hazard} />`;
  const columns = [
    { key: 'time', label: 'Time', render: (h) => hhmmss(h.time) }, { key: 'cube_id', label: 'Cube', render: (h) => h.cube_id ? `#${h.cube_id}` : 'unknown' },
    { key: 'uid', label: 'UID', mono: true }, { key: 'mac', label: 'MAC', mono: true, render: (h) => h.mac || '—' },
    { key: 'state', label: 'Result', render: (h) => html`<${Pill} tone=${{ delivered: 'ok', pending: 'warn', 'not acknowledged': 'bad', 'unknown tag': 'warn' }[h.state] || 'muted'} label=${`${zoneName(h.zone)} · ${h.state}`} />` },
    { key: 'held_ms', label: 'Held', render: (h) => h.held_ms == null ? 'on plate' : `${(h.held_ms / 1000).toFixed(1)} s` },
    { key: 'registry', label: 'Inventory', render: (h) => h.cube_id ? registryText(h.cube_id) : '—' },
  ];
  return html`<div class="card" data-doc="zone.monitor.card"><${Explainer} id="zone.monitor" />
    <div class="row"><${Pill} tone=${s.reader ? s.reader.level : 'muted'} label=${s.reader ? s.reader.text : 'no reader status yet'} /></div>
    <div class="grid2"><div>
      <${LedRing} doc="zone.monitor.ring" colour=${display.colour} label=${cubeId ? `#${cubeId}` : '—'} sub=${display.label} blink=${cube && cube.flashing} />
      <div class="note">${display.note}</div></div>
      <div class="stack"><div class=${(current ? current.cube_id : cubeId) ? 'readout' : 'readout medium'}>${current ? (current.cube_id ? `#${current.cube_id}` : 'Unknown tag') : (cubeId ? `#${cubeId}` : 'No cube on the plate')}</div>
      ${entry && html`<${KeyValue} items=${[['NFC UID', entry.uid], ['MAC', entry.mac || '— (not in this zone\'s database)'], ['Zone sent', `${zoneName(entry.zone)} → ${entry.state}`], ['Cube shows', entry.cube_id ? `${display.label} (${display.note})` : '— (unknown tags are ignored by zones)'], ['Taps', cube ? `${cube.taps} this session` : '—'], ['Inventory', entry.cube_id ? registryText(entry.cube_id) : rowByUid(entry.uid)]]} />`}
      ${entry && !entry.cube_id && html`<div class="warn-text">This tag is not in the plate's database. See Attention for what the inventory knows about it.</div>`}
      </div></div>
    <div class="row"><span class="note">${cubeId ? `Actions apply to cube #${cubeId}` : 'Actions apply to the cube on the plate, or to a selected history row'}</span></div>
    <div class="row">
      ${act('monitor.flash', { label: 'Flash 5 s', seconds: 5 })}
      ${act('monitor.clear', { label: 'Clear (idle white)', hazard: 'Sends SET_ZONE 0 to the cube.' })}
      ${[1, 2, 3, 4].map((z) => act('monitor.zone', { label: ZONE_NAMES[z], zone: z, hazard: `Sends SET_ZONE ${z} (${ZONE_NAMES[z]}) to the cube.` }))}
      <${ActionButton} name="monitor.stop" args=${{ device: device.id }} label="Stop flashing" className="btn small" disabled=${!live} /></div>
    <h3>History</h3>
    <${DataTable} columns=${columns} rows=${s.history || []} keyOf=${(h) => String(h.time)} selected=${selected} onSelect=${(k) => setSelected(k === selected ? null : k)} empty="No taps yet" />
    <h3>Zone console</h3><${Console} device=${device.id} hint="help" /></div>`;
}

function rowByUid(uid) {
  const rows = (section('inventory') || {}).rows || [];
  const r = rows.find((x) => x.uid === uid);
  if (r) return `tag of cube ${r.cube_id != null ? '#' + r.cube_id : r.mac} (${r.status}) — not in this plate's database`;
  const p = rows.find((x) => x.pending_uid === uid);
  if (p) return `pending tag of ${p.cube_id != null ? '#' + p.cube_id : p.mac} (${p.status})`;
  return 'unknown to this computer';
}

export function FirmwareDb({ device, s }) {
  useSections(['builds', 'inventory', 'registry']);
  const copy = useCopy();
  const [profiles, setProfiles] = useState(null);
  const report = s.report || device.details || {};
  const [form, setForm] = useState(null);
  useEffect(() => { run('zone.profiles').then(setProfiles).catch((e) => notify(e.message, 'bad')); }, []);
  useEffect(() => {
    if (!profiles || form) return;
    const detection = device.detection || {};
    const profile = detection.profile || guessProfile(report, profiles);
    const p = profiles.profiles[profile] || Object.values(profiles.profiles)[0];
    const point = report.point_id || detection.point || p.points[0];
    setForm({ profile, point, name: report.name || detection.name || p.name.replace('{point}', point), params: (report.params || detection.params || p.params.map((x) => Math.round(x[1] * x[2]))), rx_gain: report.rx_gain || profiles.rx_gain_default });
  }, [profiles, device.id]);
  const inv = section('inventory') || {};
  const pub = inv.published || {};
  const state = report.db_version == null ? null : pub.version ? (report.db_version === pub.version && report.db_crc === pub.crc ? 'current' : report.db_version < pub.version ? 'behind' : 'ahead') : 'unpublished';
  const builds = section('builds') || {};
  const sketch = form && profiles ? profiles.profiles[form.profile].sketch : null;
  const build = sketch ? (builds.zones || {})[sketch] : null;
  const busy = device.state === 'job';
  const refused = device.detection && ['cube', 'station', 'other'].includes(device.detection.kind);
  const set = (k, v) => setForm({ ...form, [k]: v });
  const args = form ? { device: device.id, profile: form.profile, point: Number(form.point), name: form.name, params: form.params.map(Number), rx_gain: Number(form.rx_gain) } : null;
  return html`<div class="card"><${Explainer} id="zone.firmware" />
    <${KeyValue} items=${[['Board', report.firmware ? `${report.firmware} · ${report.name || 'unconfigured'} · type ${report.zone_type ?? '?'} point ${report.point_id ?? '?'}` : 'no zone report', 'zone.fw.identity'],
      ['Board database', report.db_version != null ? html`v${report.db_version} · ${report.db_count} records · CRC ${crc(report.db_crc)} <${Pill} status=${'zonedb.' + state} />` : '—'],
      ['Published database', pub.version ? `v${pub.version} · ${pub.count} records · CRC ${crc(pub.crc)}${inv.local_differs ? ' · local mappings differ (Sync to publish)' : ''}` : 'nothing published'],
      ['Local build', build ? (build.error ? `${sketch}: ${build.error}` : `${sketch} ${build.version}`) : '—'],
      ['RX gain', report.rx_gain ? `${report.rx_gain} dB${report.rx_gain_applied ? '' : ' (not applied)'}` : '—']]} />
    <div class="row">
      <${ActionButton} name="zone.update_db_usb" args=${{ device: device.id }} label="Update database over USB" disabled=${busy || !pub.version || state === 'current'} hazard=${copy.actions['zone.update_db_usb']?.hazard} />
      <${ActionButton} name="zone.check_report" args=${{ device: device.id }} label="Check report" disabled=${busy} />
      <${ActionButton} name="zone.detect" args=${{ device: device.id }} label="Identify via bootloader" disabled=${busy} hazard="Reads flash through the bootloader and reboots the board." />
      ${device.mac && html`<${ActionButton} name="zones.reboot" args=${{ mac: device.mac }} label="Reboot (over the air)" hazard="Sends ZONE_REBOOT over the radio." />`}</div>
    ${profiles && form && html`<div data-doc="zone.fw.form"><h3>Identity</h3><div class="form">
      <div><label class="lbl">Zone</label><select class="field" value=${form.profile} onChange=${(e) => { const p = profiles.profiles[e.target.value]; setForm({ ...form, profile: e.target.value, point: p.points[0], name: p.name.replace('{point}', p.points[0]), params: p.params.map((x) => Math.round(x[1] * x[2])) }); }}>${Object.entries(profiles.profiles).map(([k, p]) => html`<option value=${k}>${p.label}</option>`)}</select></div>
      <div><label class="lbl">Point</label><select class="field" value=${form.point} onChange=${(e) => set('point', Number(e.target.value))}>${profiles.profiles[form.profile].points.map((p) => html`<option value=${p}>${p}</option>`)}</select></div>
      <div><label class="lbl">Name</label><input class="field" value=${form.name} onInput=${(e) => set('name', e.target.value)} maxlength="15" /></div>
      ${profiles.profiles[form.profile].params.map((p, i) => html`<div><label class="lbl">${p[0]} (×${p[2]})</label><input class="field num" value=${form.params[i]} onInput=${(e) => { const params = [...form.params]; params[i] = e.target.value; set('params', params); }} /></div>`)}
      <div><label class="lbl">RX gain (dB)</label><select class="field" value=${form.rx_gain} onChange=${(e) => set('rx_gain', Number(e.target.value))}>${profiles.rx_gains.map((g) => html`<option value=${g}>${g}</option>`)}</select></div></div>
      <div class="row">
        <${ActionButton} name="zone.flash" args=${args} label="Flash firmware + identity + database" disabled=${busy || refused || !!(build && build.error)} hazard=${copy.actions['zone.flash']?.hazard} />
        ${refused && html`<${HoldButton} name="zone.flash_force" args=${args} label="Force flash" hazard=${copy.actions['zone.flash_force']?.hazard} disabled=${busy} />`}
        ${refused && html`<span class="warn-text">REFUSED: ${device.detection.label}. Force flashing a cube unregisters it.</span>`}
        ${device.state === 'session' && report.firmware && html`<${ActionButton} name="zone.rxgain_usb" args=${{ device: device.id, db: Number(form.rx_gain) }} label=${`Apply RX gain ${form.rx_gain} dB now`} hazard="Stores and applies the reader gain over the console." />`}</div>
      ${build && build.error && html`<div class="warn-text">${build.error} — build it under This computer › Firmware builds.</div>`}</div>`}
    ${Number(report.zone_type) === 3 && html`<${RadioId} device=${device} s=${s} report=${report} />`}
  </div>`;
}

function guessProfile(report, profiles) {
  const fw = report.firmware || '';
  const entries = Object.entries(profiles.profiles);
  const m = entries.find(([, p]) => (fw.startsWith('preshow-') && p.sketch === 'PreshowZone') || (fw.startsWith('desert-') && p.sketch === 'DesertZone') || (fw.startsWith('pool-') && p.sketch === 'PoolZone') || (fw.startsWith('reset-') && p.sketch === 'ResetZone') || (fw.startsWith('tagplate-') && p.sketch === 'TagPlateZone' && p.zone_type === report.zone_type));
  return m ? m[0] : entries[0][0];
}

export function Calibration({ device, s }) {
  const cal = s.calibration || {};
  const ticks = cal.ticks;
  const sample = s.sample;
  const [draft, setDraft] = useState({});
  const [tune, setTune] = useState({});
  const live = device.state === 'session';
  const rows = Array.from({ length: 23 }, (_, i) => ({ index: i + 1, mm: ticks ? ticks[i] : null, anchor: cal.anchors != null ? !!(cal.anchors & (1 << i)) : false, draft: draft[i + 1] }));
  const applyDraft = async () => { for (const [i, mm] of Object.entries(draft)) await run('pool.cal_set', { device: device.id, index: Number(i), mm: Number(mm) }); setDraft({}); notify('Control points sent; Apply & save writes them to flash', 'info'); };
  return html`<div class="card"><${Explainer} id="pool.calibration" />
    <div class="row"><${LeaseToggle} on=${s.armed} onName="pool.arm" touchName="pool.touch" offName="pool.disarm" args=${{ device: device.id }} label="Override output without a cube" disabled=${!live || !s.ready} hazard="Leased: the console pings the radio every 0.35 s; the lease lapses 1.5 s after it stops." />
      <span class="readout medium">${sample && sample.distance != null ? `${Number(sample.distance).toFixed(0)} mm · index ${sample.index > 0 ? sample.index : '—'}` : '— mm'}</span></div>
    <${BandDiagram} doc="pool.bands" ticks=${ticks} distance=${sample && sample.distance} index=${sample && sample.index} />
    <div class="note" data-doc="pool.saved">${cal.saved ? 'Saved calibration loaded' : 'Calibration is not saved on the board'} · ${s.note || ''}${s.pending ? ` · waiting for ${s.pending}` : ''}</div>
    <h3>Control points</h3>
    <${DataTable} columns=${[{ key: 'index', label: 'Member' }, { key: 'mm', label: 'mm', render: (r) => r.mm == null ? '—' : r.mm.toFixed(1) }, { key: 'anchor', label: 'Anchor', render: (r) => r.anchor ? '●' : '' },
      { key: 'draft', label: 'Set to', render: (r) => html`<input class="field num" value=${r.draft ?? ''} placeholder=${sample && sample.distance != null ? Number(sample.distance).toFixed(1) : ''} onInput=${(e) => setDraft({ ...draft, [r.index]: e.target.value })} />` },
      { key: 'capture', label: '', render: (r) => html`<button class="btn small" data-doc="pool.capture" disabled=${!sample || sample.distance == null} onClick=${() => setDraft({ ...draft, [r.index]: Number(sample.distance).toFixed(1) })}>Capture</button>` }]} rows=${rows} keyOf=${(r) => r.index} rowDoc=${(r) => `pool.point:${r.index}`} maxRows=${23} />
    <div class="row"><button class="btn primary" data-doc="pool.cal_set" disabled=${!Object.keys(draft).length || !live} onClick=${applyDraft}>Send control points</button>
      <${ActionButton} name="pool.cal_save" args=${{ device: device.id }} label="Apply & save to flash" disabled=${!live} hazard="Writes the calibration to the radio's flash." />
      <${ActionButton} name="pool.cal_load" args=${{ device: device.id }} label="Reload saved" disabled=${!live} /></div>
    <h3>Tuning ${s.tune_supported === false ? '(not supported by this firmware; update to pool-2.8.0 or newer)' : s.tuning_saved ? '· saved to flash' : s.tuning ? '· live only, not saved' : ''}</h3>
    ${s.tuning && html`<div class="form">${Object.entries(s.fields || {}).map(([k, f]) => html`<div><label class="lbl">${f[0]}</label><input class="field num" value=${tune[k] ?? s.tuning[k]} onInput=${(e) => setTune({ ...tune, [k]: e.target.value })} /></div>`)}</div>
      <div class="row"><button class="btn" data-doc="pool.tune_live" disabled=${!live} onClick=${() => run('pool.tune_apply', { device: device.id, values: merged(s.tuning, tune, s.fields), save: false }).then(() => setTune({})).catch((e) => notify(e.message, 'bad'))}>Apply live</button>
        <${ActionButton} name="pool.tune_apply" args=${{ device: device.id, values: merged(s.tuning, tune, s.fields), save: true }} label="Apply & save" disabled=${!live} hazard="Writes tuning to flash." />
        <${ActionButton} name="pool.tune_load" args=${{ device: device.id }} label="Reload saved" disabled=${!live} /><${ActionButton} name="pool.tune_defaults" args=${{ device: device.id }} label="Firmware defaults" disabled=${!live} /></div>`}
  </div>`;
}

function merged(current, edits, fields) {
  const out = { ...current };
  for (const [k, v] of Object.entries(edits)) out[k] = fields && fields[k] && fields[k][1] ? Math.round(Number(v)) : Number(v);
  return out;
}

export function Diagnostics({ device, s }) {
  const it = s.interaction || {};
  const samples = (s.samples || []).map((x) => ({ t: x[0], v: x[2] })).filter((p) => p.v != null);
  return html`<div><${Recording} device=${device} s=${s} /><div class="card"><h3>Diagnostics</h3>
    <div class="tiles"><${StatTile} label="Radio id" value=${it.radio_id} /><${StatTile} label="Central sees me" value=${it.central_sees_me == null ? '—' : it.central_sees_me ? 'yes' : 'NO'} tone=${it.central_sees_me ? 'ok' : 'warn'} />
      <${StatTile} label="Send errors" value=${it.send_errors} /><${StatTile} label="Queued" value=${it.queued} /><${StatTile} label="Override" value=${it.override ? 'on' : 'off'} /><${StatTile} label="Delivery" value=${it.delivery || '—'} /></div>
    <${KeyValue} items=${[['Central', it.central_mac ? `${it.central_mac} · seen ${it.central_seen_ms} ms ago` : '—'], ['Cube on plate', it.cube ? `#${it.cube}` : 'none'], ['Reader', s.reader ? s.reader.text : '—']]} />
    <${Chart} series=${[{ points: samples, colour: '--chart-1', label: 'filtered distance (mm)' }]} unit="mm" span=${30} /></div></div>`;
}

// Guided recording (the calibration app's wizard): Start → per step "move to tick N" / Reached → hold countdown →
// the analysis proposes tuning and measured control points, applied live, saved, or with the points.
function summary(sim) {
  if (!sim) return '—';
  return `flicker ${sim.flicker ?? '—'} · missed ${sim.missed ?? '—'} · settle ${sim.settle_ms != null ? sim.settle_ms + ' ms' : '—'}`;
}

export function Recording({ device, s }) {
  const r = s.recording || {};
  const live = r.live;
  const proposal = r.proposal;
  const [stride, setStride] = useState(4);
  const [hold, setHold] = useState(5);
  const connected = device.state === 'session';
  const fields = s.fields || {};
  const args = { device: device.id };
  const tuningRows = proposal && proposal.tuning ? Object.entries(proposal.tuning).map(([k, v]) => ({ key: k, field: fields[k] ? fields[k][0] : k, current: s.tuning && s.tuning[k] != null ? s.tuning[k] : '—', proposed: v })) : [];
  const warnings = [...((r.analysis && r.analysis.warnings) || []), ...((proposal && proposal.fit && proposal.fit.warnings) || [])];
  const reasons = (proposal && proposal.reasons) || [];
  return html`<div class="card wizard" data-doc="pool.record"><${Explainer} id="pool.recording" />
    ${!live && html`<div class="row"><label class="lbl">Stride (ticks)</label><input class="field num" value=${stride} onInput=${(e) => setStride(e.target.value)} />
      <label class="lbl">Hold (s)</label><input class="field num" value=${hold} onInput=${(e) => setHold(e.target.value)} />
      <${ActionButton} name="pool.record_start" args=${{ ...args, stride: Number(stride) || 4, hold: Number(hold) || 5 }} label="Start guided recording" className="btn primary" disabled=${!connected || !s.ready || s.tune_supported === false} hazard="Streams raw samples from the radio (RAW ON) until the recording ends or is aborted." reason=${!connected ? 'No live session' : !s.ready ? 'No calibration report yet' : s.tune_supported === false ? 'This firmware has no tuning support (pool-2.8.0 or newer)' : null} /></div>`}
    ${live && html`<div class="stack">
      <div class="note">Step ${live.step} of ${live.total} · ticks ${(live.ticks || []).join(', ')}</div>
      <div class="prompt">${live.state === 'move' ? `Move the slider to tick ${live.tick}, then press Reached this position` : `Hold still at tick ${live.tick}`}</div>
      ${live.state === 'hold' && html`<div class="countdown" data-doc="pool.record_countdown">${Number(live.remaining || 0).toFixed(1)} s</div>`}
      <div class="tiles"><${StatTile} label="Samples this step" value=${live.samples} /><${StatTile} label="Hold" value=${`${live.hold} s`} /><${StatTile} label="Live reading" value=${s.sample && s.sample.distance != null ? `${Number(s.sample.distance).toFixed(0)} mm` : '—'} /></div>
      <div class="row">
        <${ActionButton} name="pool.record_reached" args=${args} label="Reached this position" className="btn primary big" disabled=${live.state !== 'move'} reason=${live.state !== 'move' ? 'Measuring the hold; wait for the countdown' : null} />
        <${ActionButton} name="pool.record_abort" args=${args} label="Abort recording" className="btn danger small" /></div></div>`}
    ${r.note && html`<div class="note" data-doc="pool.record_note">${r.note}${r.path ? ` · saved to ${r.path}` : ''}</div>`}
    ${proposal && html`<div class="stack" data-doc="pool.record_proposal"><h3>Proposal</h3>
      <div class="tiles"><${StatTile} label="Before (current tuning)" value=${summary(proposal.before)} /><${StatTile} label="After (proposed)" value=${summary(proposal.after)} tone="ok" /></div>
      ${reasons.length > 0 && html`<div class="plan-notes">${reasons.map((n) => html`<div>${n}</div>`)}</div>`}
      ${warnings.length > 0 && html`<div class="warn-text">${warnings.map((w) => html`<div>${w}</div>`)}</div>`}
      <${DataTable} columns=${[{ key: 'field', label: 'Tuning' }, { key: 'current', label: 'Current', mono: true }, { key: 'proposed', label: 'Proposed', mono: true }]} rows=${tuningRows} keyOf=${(x) => x.key} maxRows=${20} />
      <div class="row">
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: false, points: false }} label="Apply live" disabled=${!connected} hazard="Applies the proposed tuning until the radio restarts; nothing is written to flash." />
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: true, points: false }} label="Apply & save" disabled=${!connected} hazard="Writes the proposed tuning to the radio's flash." />
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: true, points: true }} label="Apply & save + measured points" disabled=${!connected} hazard="Also replaces the control points with the measured ticks and saves the calibration." /></div></div>`}
  </div>`;
}

// Radio id (1-6): the suggestion is the lowest id no other pool radio holds; a clash is another radio on the same id.
export function RadioId({ device, s, report }) {
  useSections(['registry', 'inventory']);
  const it = s.interaction || {};
  const current = it.radio_id ?? report.point_id ?? null;
  const reg = section('registry') || {};
  const inv = section('inventory') || {};
  const pools = ((reg.zones && reg.zones.length ? reg.zones : inv.zones) || []).filter((z) => Number(z.zone_type) === 3 && z.mac !== device.mac);
  const used = new Map();
  pools.forEach((z) => { if (z.point_id != null) used.set(Number(z.point_id), z); });
  const clash = current != null ? used.get(Number(current)) : null;
  let suggested = null;
  for (let i = 1; i <= 6; i++) if (!used.has(i) && (clash || i !== Number(current))) { suggested = i; break; }
  const [id, setId] = useState(null);
  const chosen = id ?? (clash ? suggested : current) ?? suggested ?? 1;
  const chosenClash = used.get(Number(chosen));
  const busy = device.state === 'job';
  return html`<div data-doc="pool.radio_id"><h3>Radio id</h3>
    <${KeyValue} items=${[['Current', current != null ? String(current) : 'unknown (no calibration report yet)'], ['Other pool radios', pools.map((z) => `${z.point_id}: ${z.name || z.mac}`).join(' · ') || 'none known'],
      ['Suggested', suggested != null ? String(suggested) : 'none free (ids 1-6 all taken)'], ['Clash', clash ? html`<span class="bad-text">id ${current} is also held by ${clash.name || clash.mac}</span>` : 'none']]} />
    <div class="row"><label class="lbl">New id</label><select class="field" value=${chosen} onChange=${(e) => setId(Number(e.target.value))}>${[1, 2, 3, 4, 5, 6].map((i) => html`<option value=${i}>${i}${used.has(i) ? ` (taken: ${used.get(i).name || used.get(i).mac})` : ''}${Number(current) === i ? ' (current)' : ''}</option>`)}</select>
      <${ActionButton} name="pool.assign_radio_id" args=${{ device: device.id, new_id: Number(chosen), force: !!chosenClash }} label=${`Assign radio id ${chosen}`} disabled=${busy} hazard="Writes the radio id to the board over USB and reboots it; the central must not see two radios on one id." />
      ${chosenClash && html`<span class="warn-text">id ${chosen} is used by ${chosenClash.name || chosenClash.mac}: assigning it forces a clash</span>`}</div></div>`;
}


export function CueTest({ device, s }) {
  const host = s.host || {};
  const live = device.state === 'session';
  const held = host.state === 'ON' ? host.point : null;
  return html`<div class="card"><${Explainer} id="preshow.cue" />
    <div class="row"><${LeaseToggle} on=${s.armed} onName="preshow.arm" offName="preshow.disarm" args=${{ device: device.id }} label="Cue override" disabled=${!live} hazard="Leased 1.5 s: the console keeps it alive while this is on; switch it off when done." />
      <${Pill} tone=${host.mode === 'modern' ? 'ok' : 'warn'} label=${host.mode ? `${host.mode} mode` : 'no host status yet'} tip=${host.mode === 'legacy' ? 'No bridge beacon heard: the plate also sends the 2-byte packet the original bridge reads. Expected today.' : 'A bridge answers; cues are acknowledged end to end.'} /></div>
    <div class="row">${[1, 2, 3, 4].map((p) => html`<${ActionButton} name="preshow.cue" args=${{ device: device.id, point: p, on: held !== p }} label=${`POINT ${p} ${held === p ? 'OFF' : 'ON'}`} className=${'btn big' + (held === p ? ' on' : '')} disabled=${!s.armed} hazard="Raises a TouchDesigner cue." />`)}</div>
    <${KeyValue} items=${[['Cue', `${host.state || '?'} on point ${host.point ?? '?'} · acknowledged ${host.acked ? `yes, ${host.ack_ms} ms` : host.mode === 'legacy' ? 'n/a (old bridge cannot acknowledge)' : 'NO'}`, 'preshow.state'],
      ['Counters', `seq ${host.seq ?? '?'} · sent ${host.sent ?? '?'} · legacy ${host.legacy_sent ?? '?'} · retries ${host.retries ?? '?'} · acks ${host.acks ?? '?'} · failed ${host.failed ?? '?'} · errors ${host.errors ?? '?'}`],
      ['Bridge', `${host.bridge_mac || 'not heard from'} · last beacon ${host.bridge_seen_ms ?? '?'} ms ago · sees me: ${host.bridge_sees_me ? 'yes' : 'no'}`]]} /></div>`;
}

export function ZonePanel({ device }) {
  useSections(['devices', 'sessions', 'inventory', 'builds']);
  const s = sessionOf(device) || {};
  const report = s.report || device.details || {};
  const zoneType = report.zone_type ?? device.details?.zone_type;
  const tabs = [['monitor', 'Monitor'], ['firmware', 'Firmware & database']];
  if (zoneType === 3) tabs.push(['calibration', 'Calibration'], ['diagnostics', 'Diagnostics']);
  if (zoneType === 1) tabs.push(['cue', 'Cue test']);
  const [tab, setTab] = useRouteTab('monitor', tabs.map((t) => t[0]));
  const inv = section('inventory') || {};
  const pub = inv.published || {};
  const state = report.db_version == null ? null : pub.version ? (report.db_version === pub.version && report.db_crc === pub.crc ? 'current' : report.db_version < pub.version ? 'behind' : 'ahead') : 'unpublished';
  // A preshow plate's media link: mode (legacy = no bridge beacon yet) and whether the bridge lists this plate.
  const host = s.host || {};
  const media = zoneType === 1 && (host.mode || report.media_mode) ? html` <${Pill} tone=${(host.mode || report.media_mode) === 'modern' ? 'ok' : 'warn'} label=${`MEDIA mode=${host.mode || report.media_mode}`} tip=${(host.mode || report.media_mode) === 'legacy' ? 'No bridge beacon heard: the plate also sends the 2-byte packet the original bridge reads.' : 'A bridge answers; cues are acknowledged end to end.'} /> <${Pill} tone=${host.bridge_sees_me ? 'ok' : 'muted'} label=${`bridge sees me: ${host.bridge_sees_me ? 'yes' : 'no'}`} />` : null;
  const pills = html`${state && html`<${Pill} status=${'zonedb.' + state} label=${`DB v${report.db_version} · ${(state)}`} />`} ${s.reader && html`<${Pill} status=${'nfc.' + s.reader.level} />`} ${report.channel != null && html`<${Pill} tone=${report.channel === 2 ? 'ok' : 'bad'} label=${`ch ${report.channel}`} />`}${media}`;
  return html`<div>
    <${DeviceHeader} device=${device} title=${report.name || 'Zone plate (unconfigured)'} pills=${pills} kv=${[['Zone type / point', `${report.zone_type ?? '?'} / ${report.point_id ?? '?'}`], ['Stats', s.stats && s.stats.at ? `${s.stats.tags} tags · ${s.stats.unknown} unknown · ${s.stats.send_fail} send failures` : '—']]} />
    <${Tabs} tabs=${tabs} current=${tab} onChange=${setTab} />
    ${tab === 'monitor' && html`<${Monitor} device=${device} s=${s} />`}
    ${tab === 'firmware' && html`<${FirmwareDb} device=${device} s=${s} />`}
    ${tab === 'calibration' && html`<${Calibration} device=${device} s=${s} />`}
    ${tab === 'diagnostics' && html`<${Diagnostics} device=${device} s=${s} />`}
    ${tab === 'cue' && html`<${CueTest} device=${device} s=${s} />`}
    <${JobHistory} device=${device} />
  </div>`;
}
