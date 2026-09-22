import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useSections, useCopy, useRouteTab } from '../lib/hooks.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, Tabs, StatTile } from '../components/basics.js';
import { ActionButton, HoldButton, LeaseToggle } from '../components/actions.js';
import { DataTable, Console, JobCard } from '../components/data.js';
import { LedRing, BandDiagram, Chart } from '../components/canvas.js';
import { DeviceHeader, sessionOf, rowByMac, rowByNumber, RawConsole, JobHistory } from './common.js';
import { statusLabel } from './CubePanel.js';
import { hhmmss, crc, ago } from '../lib/format.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { t } from '../lib/i18n.js';

const ZONE_NAMES = { 0: 'idle', 1: 'preshow', 2: 'desert', 3: 'pool', 4: 'mainshow' };

function registryText(cubeId) {
  const row = rowByNumber(cubeId);
  return row ? `#${cubeId} · ${statusLabel(row.status)}` : t('not in inventory');
}

export function Monitor({ device, s }) {
  const [selected, setSelected] = useState(null);
  const current = s.current;
  const entry = current || (selected && (s.history || []).find((h) => String(h.time) === selected)) || null;
  const cubeId = entry ? entry.cube_id : null;
  const cube = cubeId ? (s.cubes || {})[String(cubeId)] : null;
  const display = (cube && cube.display) || { label: t('unknown'), colour: '--led-off', note: t('no command sent yet') };
  const zoneName = (v) => (s.zone_colors && s.zone_colors[v] ? s.zone_colors[v][0] : '?');
  const live = device.state === 'session';
  const act = (name, { label, hazard, ...extra }) => html`<${ActionButton} name=${name} args=${{ device: device.id, cube_id: cubeId, ...extra }} label=${label} className="btn small" disabled=${!cubeId || !live} hazard=${hazard} />`;
  const columns = [
    { key: 'time', label: t('Time'), render: (h) => hhmmss(h.time) }, { key: 'cube_id', label: t('Cube'), render: (h) => h.cube_id ? `#${h.cube_id}` : t('unknown') },
    { key: 'uid', label: 'UID', mono: true }, { key: 'mac', label: 'MAC', mono: true, render: (h) => h.mac || '—' },
    { key: 'state', label: t('Result'), render: (h) => html`<${Pill} tone=${{ delivered: 'ok', pending: 'warn', 'not acknowledged': 'bad', 'unknown tag': 'warn' }[h.state] || 'muted'} label=${`${zoneName(h.zone)} · ${h.state}`} />` },
    { key: 'held_ms', label: t('Held'), render: (h) => h.held_ms == null ? t('on plate') : `${(h.held_ms / 1000).toFixed(1)} s` },
    { key: 'registry', label: t('Inventory'), render: (h) => h.cube_id ? registryText(h.cube_id) : '—' },
  ];
  return html`<div class="card" data-doc="zone.monitor.card"><${Explainer} id="zone.monitor" />
    <div class="row"><${Pill} tone=${s.reader ? s.reader.level : 'muted'} label=${s.reader ? s.reader.text : t('no reader status yet')} /></div>
    <div class="grid2"><div>
      <${LedRing} doc="zone.monitor.ring" colour=${display.colour} label=${cubeId ? `#${cubeId}` : '—'} sub=${display.label} blink=${cube && cube.flashing} />
      <div class="note">${display.note}</div></div>
      <div class="stack"><div class=${(current ? current.cube_id : cubeId) ? 'readout' : 'readout medium'}>${current ? (current.cube_id ? `#${current.cube_id}` : t('Unknown tag')) : (cubeId ? `#${cubeId}` : t('No cube on the plate'))}</div>
      ${entry && html`<${KeyValue} items=${[['NFC UID', entry.uid], ['MAC', entry.mac || t("— (not in this zone's database)")], [t('Zone sent'), `${zoneName(entry.zone)} → ${entry.state}`], [t('Cube shows'), entry.cube_id ? `${display.label} (${display.note})` : t('— (unknown tags are ignored by zones)')], [t('Taps'), cube ? t('{n} this session', { n: cube.taps }) : '—'], [t('Inventory'), entry.cube_id ? registryText(entry.cube_id) : rowByUid(entry.uid)]]} />`}
      ${entry && !entry.cube_id && html`<div class="warn-text">${t("This tag is not in the plate's database. See Attention for what the inventory knows about it.")}</div>`}
      </div></div>
    <div class="row"><span class="note">${cubeId ? t('Actions apply to cube #{n}', { n: cubeId }) : t('Actions apply to the cube on the plate, or to a selected history row')}</span></div>
    <div class="row">
      ${act('monitor.flash', { label: t('Flash 5 s'), seconds: 5 })}
      ${act('monitor.clear', { label: t('Clear (idle white)'), hazard: t('Sends SET_ZONE 0 to the cube.') })}
      ${[1, 2, 3, 4].map((z) => act('monitor.zone', { label: ZONE_NAMES[z], zone: z, hazard: t('Sends SET_ZONE {zone} ({name}) to the cube.', { zone: z, name: ZONE_NAMES[z] }) }))}
      <${ActionButton} name="monitor.stop" args=${{ device: device.id }} label=${t('Stop flashing')} className="btn small" disabled=${!live} /></div>
    <h3>${t('History')}</h3>
    <${DataTable} columns=${columns} rows=${s.history || []} keyOf=${(h) => String(h.time)} selected=${selected} onSelect=${(k) => setSelected(k === selected ? null : k)} empty=${t('No taps yet')} />
    <h3>${t('Zone console')}</h3><${Console} device=${device.id} hint="help" /></div>`;
}

function rowByUid(uid) {
  const rows = (section('inventory') || {}).rows || [];
  const r = rows.find((x) => x.uid === uid);
  if (r) return t("tag of cube {cube} ({status}) — not in this plate's database", { cube: r.cube_id != null ? '#' + r.cube_id : r.mac, status: statusLabel(r.status) });
  const p = rows.find((x) => x.pending_uid === uid);
  if (p) return t('pending tag of {cube} ({status})', { cube: p.cube_id != null ? '#' + p.cube_id : p.mac, status: statusLabel(p.status) });
  return t('unknown to this computer');
}

export function FirmwareDb({ device, s }) {
  useSections(['builds', 'inventory', 'registry', 'settings']);
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
    const point = report.point_id || detection.point || freePoint(p, device.mac);
    setForm({ profile, point, name: report.name || detection.name || p.name.replace('{point}', point), params: (report.params || detection.params || p.params.map((x) => Math.round(x[1] * x[2]))), rx_gain: report.rx_gain || profiles.rx_gain_default });
  }, [profiles, device.id]);
  const inv = section('inventory') || {};
  const pub = inv.published || {};
  const state = report.db_version == null ? null : pub.version ? (report.db_version === pub.version && report.db_crc === pub.crc ? 'current' : report.db_version < pub.version ? 'behind' : 'ahead') : 'unpublished';
  const builds = section('builds') || {};
  const sketch = form && profiles ? profiles.profiles[form.profile].sketch : null;
  const build = sketch ? (builds.zones || {})[sketch] : null;
  const busy = device.state === 'job';
  const autoResult = ((inv.intake || {}).results || {})[device.key];
  const autoText = !(section('settings') || {}).auto_zone_db_usb ? t('off (Settings › Automatic updates)')
    : state === 'current' ? t('on · current') : autoResult ? t('on · {result}', { result: autoResult }) : state === 'behind' ? t('on · starting') : t('on');
  const refused = device.detection && ['cube', 'station', 'other'].includes(device.detection.kind);
  const set = (k, v) => setForm({ ...form, [k]: v });
  const args = form ? { device: device.id, profile: form.profile, point: Number(form.point), name: form.name, params: form.params.map(Number), rx_gain: Number(form.rx_gain) } : null;
  return html`<div class="card"><${Explainer} id="zone.firmware" />
    <${KeyValue} items=${[[t('Board'), report.firmware ? t('{firmware} · {name} · type {type} point {point}', { firmware: report.firmware, name: report.name || t('unconfigured'), type: report.zone_type ?? '?', point: report.point_id ?? '?' }) : t('no zone report'), 'zone.fw.identity'],
      [t('Board database'), report.db_version != null ? html`${t('v{v} · {n} records · CRC {crc}', { v: report.db_version, n: report.db_count, crc: crc(report.db_crc) })} <${Pill} status=${'zonedb.' + state} />` : '—'],
      [t('Published database'), pub.version ? t('v{v} · {n} records · CRC {crc}', { v: pub.version, n: pub.count, crc: crc(pub.crc) }) + (inv.local_differs ? ' · ' + t('local mappings differ (Sync to publish)') : '') : t('nothing published')],
      [t('Automatic database update'), autoText],
      [t('Local build'), build ? (build.error ? `${sketch}: ${build.error}` : `${sketch} ${build.version}`) : '—'],
      ['RX gain', report.rx_gain ? `${report.rx_gain} dB${report.rx_gain_applied ? '' : ' ' + t('(not applied)')}` : '—']]} />
    <div class="row">
      <${ActionButton} name="zone.update_db_usb" args=${{ device: device.id }} label=${t('Update database over USB')} disabled=${busy || !pub.version || state === 'current'} hazard=${copy.actions['zone.update_db_usb']?.hazard} />
      <${ActionButton} name="zone.check_report" args=${{ device: device.id }} label=${t('Check report')} disabled=${busy} />
      <${ActionButton} name="zone.detect" args=${{ device: device.id }} label=${t('Identify via bootloader')} disabled=${busy} hazard=${t('Reads flash through the bootloader and reboots the board.')} />
      ${device.mac && html`<${ActionButton} name="zones.reboot" args=${{ mac: device.mac }} label=${t('Reboot (over the air)')} hazard=${t('Sends ZONE_REBOOT over the radio.')} />`}</div>
    ${profiles && form && html`<div data-doc="zone.fw.form"><h3>${t('Identity')}</h3><div class="form">
      <div><label class="lbl">${t('Zone')}</label><select class="field" value=${form.profile} onChange=${(e) => { const p = profiles.profiles[e.target.value]; const point = freePoint(p, device.mac); setForm({ ...form, profile: e.target.value, point, name: p.name.replace('{point}', point), params: p.params.map((x) => Math.round(x[1] * x[2])) }); }}>${Object.entries(profiles.profiles).map(([k, p]) => html`<option value=${k}>${p.label}</option>`)}</select></div>
      <div><label class="lbl">${t('Point')}</label><select class="field" value=${form.point} onChange=${(e) => set('point', Number(e.target.value))}>${profiles.profiles[form.profile].points.map((p) => html`<option value=${p}>${p}</option>`)}</select></div>
      <div><label class="lbl">${t('Name')}</label><input class="field" value=${form.name} onInput=${(e) => set('name', e.target.value)} maxlength="15" /></div>
      ${profiles.profiles[form.profile].params.map((p, i) => html`<div><label class="lbl">${p[0]} (×${p[2]})</label><input class="field num" value=${form.params[i]} onInput=${(e) => { const params = [...form.params]; params[i] = e.target.value; set('params', params); }} /></div>`)}
      <div><label class="lbl">RX gain (dB)</label><select class="field" value=${form.rx_gain} onChange=${(e) => set('rx_gain', Number(e.target.value))}>${profiles.rx_gains.map((g) => html`<option value=${g}>${g}</option>`)}</select></div></div>
      <div class="row">
        <${ActionButton} name="zone.flash" args=${args} label=${t('Flash firmware + identity + database')} disabled=${busy || refused || !!(build && build.error)} hazard=${copy.actions['zone.flash']?.hazard} />
        ${refused && html`<${HoldButton} name="zone.flash_force" args=${args} label=${t('Force flash')} hazard=${copy.actions['zone.flash_force']?.hazard} disabled=${busy} />`}
        ${refused && html`<span class="warn-text">${t('REFUSED: {label}. Force flashing a cube unregisters it.', { label: device.detection.label })}</span>`}
        ${device.state === 'session' && report.firmware && html`<${ActionButton} name="zone.rxgain_usb" args=${{ device: device.id, db: Number(form.rx_gain) }} label=${t('Apply RX gain {db} dB now', { db: form.rx_gain })} hazard=${t('Stores and applies the reader gain over the console.')} />`}</div>
      ${build && build.error && html`<div class="warn-text">${build.error} — ${t('build it under This computer › Firmware builds.')}</div>`}</div>`}
    ${Number(report.zone_type) === 3 && html`<${RadioId} device=${device} s=${s} report=${report} />`}
  </div>`;
}

// The lowest point of a profile that no other known zone of that kind holds (registry, else the inventory's zones).
function freePoint(profile, ownMac) {
  const zones = [...(((section('registry') || {}).zones) || []), ...(((section('inventory') || {}).zones) || [])];   // radio + recorded
  const used = new Set(zones.filter((z) => z.mac !== ownMac && Number(z.zone_type) === Number(profile.zone_type)).map((z) => Number(z.point_id)));
  return profile.points.find((pt) => !used.has(Number(pt))) ?? profile.points[0];
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
  const applyDraft = async () => { for (const [i, mm] of Object.entries(draft)) await run('pool.cal_set', { device: device.id, index: Number(i), mm: Number(mm) }); setDraft({}); notify(t('Control points sent; Apply & save writes them to flash'), 'info'); };
  return html`<div class="card"><${Explainer} id="pool.calibration" />
    <div class="row"><${LeaseToggle} on=${s.armed} onName="pool.arm" touchName="pool.touch" offName="pool.disarm" args=${{ device: device.id }} label=${t('Override output without a cube')} disabled=${!live || !s.ready} hazard=${t('Leased: the console pings the radio every 0.35 s; the lease lapses 1.5 s after it stops.')} />
      <span class="readout medium">${sample && sample.distance != null ? t('{mm} mm · index {index}', { mm: Number(sample.distance).toFixed(0), index: sample.index > 0 ? sample.index : '—' }) : '— mm'}</span></div>
    <${BandDiagram} doc="pool.bands" ticks=${ticks} distance=${sample && sample.distance} index=${sample && sample.index} />
    <div class="note">${[s.note, s.pending ? t('waiting for {what}', { what: s.pending }) : ''].filter(Boolean).join(' · ') || (cal.saved ? t('Saved calibration loaded') : t('Calibration is not saved on the board'))}</div>
    <h3>${t('Control points')}</h3>
    <${DataTable} columns=${[{ key: 'index', label: t('Member') }, { key: 'mm', label: 'mm', render: (r) => r.mm == null ? '—' : r.mm.toFixed(1) }, { key: 'anchor', label: t('Anchor'), render: (r) => r.anchor ? '●' : '' },
      { key: 'draft', label: t('Set to'), render: (r) => html`<input class="field num" value=${r.draft ?? ''} placeholder=${sample && sample.distance != null ? Number(sample.distance).toFixed(1) : ''} onInput=${(e) => setDraft({ ...draft, [r.index]: e.target.value })} />` },
      { key: 'capture', label: '', render: (r) => html`<button class="btn small" data-doc="pool.capture" disabled=${!sample || sample.distance == null} onClick=${() => setDraft({ ...draft, [r.index]: Number(sample.distance).toFixed(1) })}>${t('Capture')}</button>` }]} rows=${rows} keyOf=${(r) => r.index} rowDoc=${(r) => `pool.point:${r.index}`} maxRows=${23} />
    <div class="row"><button class="btn primary" data-doc="pool.cal_set" disabled=${!Object.keys(draft).length || !live} onClick=${applyDraft}>${t('Send control points')}</button>
      <${ActionButton} name="pool.cal_save" args=${{ device: device.id }} label=${t('Apply & save to flash')} disabled=${!live} hazard=${t("Writes the calibration to the radio's flash.")} />
      <${ActionButton} name="pool.cal_load" args=${{ device: device.id }} label=${t('Reload saved')} disabled=${!live} />
      <span class=${'note ' + (cal.saved ? 'ok-text' : 'warn-text')} data-doc="pool.saved">${cal.saved ? t('Saved calibration loaded (saved=true)') : t('Calibration is not saved on the board')}</span></div>
    <h3>${t('Tuning')} ${s.tune_supported === false ? t('(not supported by this firmware; update to pool-2.8.0 or newer)') : s.tuning_saved ? '· ' + t('saved to flash') : s.tuning ? '· ' + t('live only, not saved') : ''}</h3>
    ${s.tuning && html`<div class="form">${Object.entries(s.fields || {}).map(([k, f]) => html`<div><label class="lbl">${f[0]}</label><input class="field num" value=${tune[k] ?? s.tuning[k]} onInput=${(e) => setTune({ ...tune, [k]: e.target.value })} /></div>`)}</div>
      <div class="row"><button class="btn" data-doc="pool.tune_live" disabled=${!live} onClick=${() => run('pool.tune_apply', { device: device.id, values: merged(s.tuning, tune, s.fields), save: false }).then(() => setTune({})).catch((e) => notify(e.message, 'bad'))}>${t('Apply live')}</button>
        <${ActionButton} name="pool.tune_apply" args=${{ device: device.id, values: merged(s.tuning, tune, s.fields), save: true }} label=${t('Apply & save')} disabled=${!live} hazard=${t('Writes tuning to flash.')} />
        <${ActionButton} name="pool.tune_load" args=${{ device: device.id }} label=${t('Reload saved')} disabled=${!live} /><${ActionButton} name="pool.tune_defaults" args=${{ device: device.id }} label=${t('Firmware defaults')} disabled=${!live} /></div>`}
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
  return html`<div><${Recording} device=${device} s=${s} /><div class="card"><h3>${t('Diagnostics')}</h3>
    <div class="tiles"><${StatTile} label=${t('Radio id')} value=${it.radio_id} /><${StatTile} label=${t('Central sees me')} value=${it.central_sees_me == null ? '—' : it.central_sees_me ? t('yes') : t('NO')} tone=${it.central_sees_me ? 'ok' : 'warn'} />
      <${StatTile} label=${t('Send errors')} value=${it.send_errors} /><${StatTile} label=${t('Queued')} value=${it.queued} /><${StatTile} label=${t('Override')} value=${it.override ? t('on') : t('off')} /><${StatTile} label=${t('Delivery')} value=${it.delivery || '—'} /></div>
    <${KeyValue} items=${[[t('Central'), it.central_mac ? t('{mac} · seen {ms} ms ago', { mac: it.central_mac, ms: it.central_seen_ms }) : '—'], [t('Cube on plate'), it.cube ? `#${it.cube}` : t('none')], [t('Reader'), s.reader ? s.reader.text : '—']]} />
    <${Chart} series=${[{ points: samples, colour: '--chart-1', label: t('filtered distance (mm)') }]} unit="mm" span=${30} /></div></div>`;
}

// Guided recording (the calibration app's wizard): Start → per step "move to tick N" / Reached → hold countdown →
// the analysis proposes tuning and measured control points, applied live, saved, or with the points.
function summary(sim) {
  if (!sim) return '—';
  return t('flicker {flicker} · missed {missed} · settle {settle}', { flicker: sim.flicker ?? '—', missed: sim.missed ?? '—', settle: sim.settle_ms != null ? sim.settle_ms + ' ms' : '—' });
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
    ${!live && html`<div class="row"><label class="lbl">${t('Stride (ticks)')}</label><input class="field num" value=${stride} onInput=${(e) => setStride(e.target.value)} />
      <label class="lbl">${t('Hold (s)')}</label><input class="field num" value=${hold} onInput=${(e) => setHold(e.target.value)} />
      <${ActionButton} name="pool.record_start" args=${{ ...args, stride: Number(stride) || 4, hold: Number(hold) || 5 }} label=${t('Start guided recording')} className="btn primary" disabled=${!connected || !s.ready || s.tune_supported === false} hazard=${t('Streams raw samples from the radio (RAW ON) until the recording ends or is aborted.')} reason=${!connected ? t('No live session') : !s.ready ? t('No calibration report yet') : s.tune_supported === false ? t('This firmware has no tuning support (pool-2.8.0 or newer)') : null} /></div>`}
    ${live && html`<div class="stack">
      <div class="note">${t('Step {step} of {total} · ticks {ticks}', { step: live.step, total: live.total, ticks: (live.ticks || []).join(', ') })}</div>
      <div class="prompt">${live.state === 'move' ? t('Move the slider to tick {tick}, then press Reached this position', { tick: live.tick }) : t('Hold still at tick {tick}', { tick: live.tick })}</div>
      ${live.state === 'hold' && html`<div class="countdown" data-doc="pool.record_countdown">${Number(live.remaining || 0).toFixed(1)} s</div>`}
      <div class="tiles"><${StatTile} label=${t('Samples this step')} value=${live.samples} /><${StatTile} label=${t('Hold')} value=${`${live.hold} s`} /><${StatTile} label=${t('Live reading')} value=${s.sample && s.sample.distance != null ? `${Number(s.sample.distance).toFixed(0)} mm` : '—'} /></div>
      <div class="row">
        <${ActionButton} name="pool.record_reached" args=${args} label=${t('Reached this position')} className="btn primary big" disabled=${live.state !== 'move'} reason=${live.state !== 'move' ? t('Measuring the hold; wait for the countdown') : null} />
        <${ActionButton} name="pool.record_abort" args=${args} label=${t('Abort recording')} className="btn danger small" /></div></div>`}
    ${r.note && html`<div class="note" data-doc="pool.record_note">${r.note}${r.path ? ' · ' + t('saved to {path}', { path: r.path }) : ''}</div>`}
    ${proposal && html`<div class="stack" data-doc="pool.record_proposal"><h3>${t('Proposal')}</h3>
      <div class="tiles"><${StatTile} label=${t('Before (current tuning)')} value=${summary(proposal.before)} /><${StatTile} label=${t('After (proposed)')} value=${summary(proposal.after)} tone="ok" /></div>
      ${reasons.length > 0 && html`<div class="plan-notes">${reasons.map((n) => html`<div>${n}</div>`)}</div>`}
      ${warnings.length > 0 && html`<div class="warn-text">${warnings.map((w) => html`<div>${w}</div>`)}</div>`}
      <${DataTable} columns=${[{ key: 'field', label: t('Tuning') }, { key: 'current', label: t('Current'), mono: true }, { key: 'proposed', label: t('Proposed'), mono: true }]} rows=${tuningRows} keyOf=${(x) => x.key} maxRows=${20} />
      <div class="row">
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: false, points: false }} label=${t('Apply live')} disabled=${!connected} hazard=${t('Applies the proposed tuning until the radio restarts; nothing is written to flash.')} />
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: true, points: false }} label=${t('Apply & save')} disabled=${!connected} hazard=${t("Writes the proposed tuning to the radio's flash.")} />
        <${ActionButton} name="pool.record_apply" args=${{ ...args, save: true, points: true }} label=${t('Apply & save + measured points')} disabled=${!connected} hazard=${t('Also replaces the control points with the measured ticks and saves the calibration.')} /></div></div>`}
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
  // Keep the current id when nobody else holds it; otherwise the lowest free id.
  let suggested = current != null && !clash ? Number(current) : null;
  if (suggested == null) for (let i = 1; i <= 6; i++) if (!used.has(i)) { suggested = i; break; }
  const [id, setId] = useState(null);
  const chosen = id ?? (clash ? suggested : current) ?? suggested ?? 1;
  const chosenClash = used.get(Number(chosen));
  const busy = device.state === 'job';
  return html`<div data-doc="pool.radio_id"><h3>${t('Radio id')}</h3>
    <${KeyValue} items=${[[t('Current'), current != null ? String(current) : t('unknown (no calibration report yet)')], [t('Other pool radios'), pools.map((z) => `${z.point_id}: ${z.name || z.mac}`).join(' · ') || t('none known')],
      [t('Suggested'), suggested != null ? String(suggested) : t('none free (ids 1-6 all taken)')], [t('Clash'), clash ? html`<span class="bad-text">${t('id {id} is also held by {holder}', { id: current, holder: clash.name || clash.mac })}</span>` : t('none')]]} />
    <div class="row"><label class="lbl">${t('New id')}</label><select class="field" value=${chosen} onChange=${(e) => setId(Number(e.target.value))}>${[1, 2, 3, 4, 5, 6].map((i) => html`<option value=${i}>${i}${used.has(i) ? ' ' + t('(taken: {holder})', { holder: used.get(i).name || used.get(i).mac }) : ''}${Number(current) === i ? ' ' + t('(current)') : ''}</option>`)}</select>
      <${ActionButton} name="pool.assign_radio_id" args=${{ device: device.id, new_id: Number(chosen), force: !!chosenClash }} label=${t('Assign radio id {id}', { id: chosen })} disabled=${busy} hazard=${t('Writes the radio id to the board over USB and reboots it; the central must not see two radios on one id.')} />
      ${chosenClash && html`<span class="warn-text">${t('id {id} is used by {holder}: assigning it forces a clash', { id: chosen, holder: chosenClash.name || chosenClash.mac })}</span>`}</div></div>`;
}


export function CueTest({ device, s }) {
  const host = s.host || {};
  const live = device.state === 'session';
  const held = host.state === 'ON' ? host.point : null;
  return html`<div class="card"><${Explainer} id="preshow.cue" />
    <div class="row"><${LeaseToggle} on=${s.armed} onName="preshow.arm" offName="preshow.disarm" args=${{ device: device.id }} label=${t('Cue override')} disabled=${!live} hazard=${t('Leased 1.5 s: the console keeps it alive while this is on; switch it off when done.')} />
      <${Pill} tone=${host.mode === 'modern' ? 'ok' : 'warn'} label=${host.mode ? t('{mode} mode', { mode: host.mode }) : t('no host status yet')} tip=${host.mode === 'legacy' ? t('No bridge beacon heard: the plate also sends the 2-byte packet the original bridge reads. Expected today.') : t('A bridge answers; cues are acknowledged end to end.')} /></div>
    <div class="row point-row">${[1, 2, 3, 4].map((p) => html`<${ActionButton} name="preshow.cue" args=${{ device: device.id, point: p, on: held !== p }} label=${t('POINT {p} {state}', { p, state: held === p ? 'OFF' : 'ON' })} className=${'btn big' + (held === p ? ' on' : '')} disabled=${!s.armed} hazard=${t('Raises a TouchDesigner cue.')} />`)}</div>
    <${KeyValue} items=${[[t('Cue'), t('{state} on point {point} · acknowledged {ack}', { state: host.state || '?', point: host.point ?? '?', ack: host.acked ? t('yes, {ms} ms', { ms: host.ack_ms }) : host.mode === 'legacy' ? t('n/a (old bridge cannot acknowledge)') : t('NO') }), 'preshow.state'],
      [t('Counters'), `seq ${host.seq ?? '?'} · sent ${host.sent ?? '?'} · legacy ${host.legacy_sent ?? '?'} · retries ${host.retries ?? '?'} · acks ${host.acks ?? '?'} · failed ${host.failed ?? '?'} · errors ${host.errors ?? '?'}`],
      [t('Bridge'), t('{mac} · last beacon {ms} ms ago · sees me: {seen}', { mac: host.bridge_mac || t('not heard from'), ms: host.bridge_seen_ms ?? '?', seen: host.bridge_sees_me ? t('yes') : t('no') })]]} /></div>`;
}

export function ZonePanel({ device }) {
  useSections(['devices', 'sessions', 'inventory', 'builds']);
  const s = sessionOf(device) || {};
  const report = s.report || device.details || {};
  const zoneType = report.zone_type ?? device.details?.zone_type;
  const tabs = [['monitor', t('Monitor')], ['firmware', t('Firmware & database')]];
  if (zoneType === 3) tabs.push(['calibration', t('Calibration')], ['diagnostics', t('Diagnostics')]);
  if (zoneType === 1) tabs.push(['cue', t('Cue test')]);
  const [tab, setTab] = useRouteTab('monitor', tabs.map((x) => x[0]));
  const inv = section('inventory') || {};
  const pub = inv.published || {};
  const state = report.db_version == null ? null : pub.version ? (report.db_version === pub.version && report.db_crc === pub.crc ? 'current' : report.db_version < pub.version ? 'behind' : 'ahead') : 'unpublished';
  // A preshow plate's media link: mode (legacy = no bridge beacon yet) and whether the bridge lists this plate.
  const host = s.host || {};
  const media = zoneType === 1 && (host.mode || report.media_mode) ? html` <${Pill} tone=${(host.mode || report.media_mode) === 'modern' ? 'ok' : 'warn'} label=${`MEDIA mode=${host.mode || report.media_mode}`} tip=${(host.mode || report.media_mode) === 'legacy' ? t('No bridge beacon heard: the plate also sends the 2-byte packet the original bridge reads.') : t('A bridge answers; cues are acknowledged end to end.')} /> <${Pill} tone=${host.bridge_sees_me ? 'ok' : 'muted'} label=${t('bridge sees me: {seen}', { seen: host.bridge_sees_me ? t('yes') : t('no') })} />` : null;
  const pills = html`${state && html`<${Pill} status=${'zonedb.' + state} label=${`DB v${report.db_version} · ${(state)}`} />`} ${s.reader && html`<${Pill} status=${'nfc.' + s.reader.level} />`} ${report.channel != null && html`<${Pill} tone=${report.channel === 2 ? 'ok' : 'bad'} label=${`ch ${report.channel}`} />`}${media}`;
  return html`<div>
    <${DeviceHeader} device=${device} title=${report.name || t('Zone plate (unconfigured)')} pills=${pills} kv=${[[t('Zone type / point'), `${report.zone_type ?? '?'} / ${report.point_id ?? '?'}`], [t('Stats'), s.stats && s.stats.at ? t('{tags} tags · {unknown} unknown · {fail} send failures', { tags: s.stats.tags, unknown: s.stats.unknown, fail: s.stats.send_fail }) : '—']]} />
    <${Tabs} tabs=${tabs} current=${tab} onChange=${setTab} />
    ${tab === 'monitor' && html`<${Monitor} device=${device} s=${s} />`}
    ${tab === 'firmware' && html`<${FirmwareDb} device=${device} s=${s} />`}
    ${tab === 'calibration' && html`<${Calibration} device=${device} s=${s} />`}
    ${tab === 'diagnostics' && html`<${Diagnostics} device=${device} s=${s} />`}
    ${tab === 'cue' && html`<${CueTest} device=${device} s=${s} />`}
    <${JobHistory} device=${device} />
  </div>`;
}
