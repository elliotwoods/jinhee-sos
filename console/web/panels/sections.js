// Bench launcher, settings, and panels for things seen only over the radio (cubes, zones).
import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useUI } from '../lib/hooks.js';
import { section, state, touch, setLang } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, PageHead, Mac, withMacs } from '../components/basics.js';
import { applyTheme, ledToken } from '../lib/theme.js';
import { ActionButton } from '../components/actions.js';
import { LedRing } from '../components/canvas.js';
import { CubeActions, CubeDetail, registrationPill, StationBanner, History } from './CubePanel.js';
import { goDevice } from '../router.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { crc, ago } from '../lib/format.js';
import { t } from '../lib/i18n.js';

// Built per render so the labels follow a live language change.
const tools = () => [
  [t('Pool light test'), 'pooltest', t('PoolRadioTest bridge (emulates radios 1-6)')], [t('Pool central diagnostics'), 'poolcentral', t('Pool central controller')],
  [t('Pool slider calibration'), 'zone:3', t('A PoolZone radio (zone type 3)')], [t('Preshow cue test'), 'zone:1', t('A PreshowZone plate (zone type 1)')],
  [t('Preshow bridge status'), 'preshowbridge', t('The TouchDesigner media bridge')], [t('ESP-NOW range test'), 'rangetest', t('A range-test board (RX unit)')],
];

export function BenchSection() {
  useSections(['devices']);
  const devices = section('devices') || [];
  const find = (want) => devices.filter((d) => want.startsWith('zone:') ? d.role === 'zone' && String((d.details || {}).zone_type) === want.slice(5) : d.role === want);
  return html`<div><${PageHead} title=${t('Bench tools')} subtitle=${t('Diagnostics that need a particular board on USB.')} /><${Explainer} id="bench" />
    ${tools().map(([label, want, needs]) => { const found = find(want); return html`<div class="card" key=${want}><div class="row between"><div><strong>${label}</strong><div class="note">${t('needs:')} ${needs}</div></div>
      <div>${found.length ? found.map((d) => html`<button class="btn primary small" onClick=${() => goDevice(d.id)}>${t('Open')} · <span class="mono">${d.port}</span></button>`) : html`<${Pill} tone="muted" label=${t('not attached')} />`}</div></div></div>`; })}</div>`;
}

export function SettingsSection() {
  useSections(['settings', 'meta']);
  const s = section('settings') || {};
  const meta = section('meta') || {};
  const ui = useUI();
  const setTheme = (theme) => { state.ui.theme = applyTheme(theme); touch('ui'); };
  const toggle = (key) => (e) => run('console.settings', { key, value: e.target.checked }).catch((x) => notify(x.message, 'bad'));
  return html`<div><${PageHead} title=${t('Settings')} /><${Explainer} id="settings" />
    <div class="card"><h3>${t('Appearance')}</h3><div class="row"><label class="lbl">${t('Theme')}</label><select class="field" value=${ui.theme} onChange=${(e) => setTheme(e.target.value)}><option value="dark">${t('Dark')}</option><option value="light">${t('Light')}</option><option value="system">${t('Match the system')}</option></select></div>
      <div class="row"><label class="lbl">Language · 언어</label><select class="field" data-doc="settings.lang" value=${ui.lang} onChange=${(e) => setLang(e.target.value)}><option value="en">English</option><option value="ko">한국어</option></select></div>
      <div class="note">${t('Messages from devices, suggestion cards, job stages and errors stay in English.')}</div></div>
    <div class="card"><h3>${t('Behaviour')}</h3><div class="stack">
      <label class="check"><input type="checkbox" checked=${!!s.auto_sessions} onChange=${toggle('auto_sessions')} /> ${t('Open a live session automatically for every identified board')}</label>
      <label class="check"><input type="checkbox" checked=${!!s.preview_flash} onChange=${toggle('preview_flash')} /> ${t('Preview the selected cube with a 1 s flash (pairing station)')}</label>
      <div class="row"><label class="check"><input type="checkbox" checked=${!!s.audio} onChange=${toggle('audio')} /> ${t('Audio cues for USB cube flashing (the cube flasher\'s sounds: plugged in, start, each stage, success, failure)')}</label>
        <${ActionButton} name="audio.test" args=${{ cue: 'success' }} label=${t('Test sound')} className="btn quiet" /></div></div></div>
    <div class="card" data-doc="settings.auto"><h3>${t('Automatic updates')}</h3><div class="stack">
      <label class="check"><input type="checkbox" checked=${!!s.auto_zone_db_radio} onChange=${toggle('auto_zone_db_radio')} /> ${t('Zone databases over the air: the link with an NFC reader (else the first zone relay) walks the zone database to every out-of-date zone in range')}</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_zone_db_usb} onChange=${toggle('auto_zone_db_usb')} /> ${t('Zone databases over USB: database-only update for any configured zone board plugged in that is behind')}</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_show} onChange=${toggle('auto_show')} /> ${t('Main show over the air: cubes in range on an older show are updated (a Workstation or General Radio; never mid-show)')}</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_pull} onChange=${toggle('auto_pull')} /> ${t('Pull a newer zone database and show from the web (needs the web password)')}</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_build} onChange=${toggle('auto_build')} /> ${t('Firmware builds: rebuild any cube, zone or dongle firmware that is missing or older than its source (needs the Arduino tools; never uploads)')}</label>
      <div class="note">${t('Saved on this computer; on by default.')}</div></div></div>
    <div class="card"><h3>${t('Keyboard')}</h3><div class="stack note"><div><kbd>Esc</kbd> ${t('close a tooltip, else stop every active operation')}</div><div><kbd>/</kbd> ${t('search')}</div><div><kbd>⌘1</kbd>–<kbd>⌘4</kbd> ${t('sections')}</div><div><kbd>j</kbd>/<kbd>k</kbd> ${t('move the rail selection')}</div><div><kbd>?</kbd> ${t('this list')}</div></div></div>
    <div class="card"><h3>${t('About')}</h3><${KeyValue} items=${[[t('Console'), meta.console_version], [t('Database'), meta.database], ['Python API', meta.api_url || t('disabled')], [t('Mode'), meta.simulate ? t('SIMULATION (fake boards, temporary database copy)') : t('live')], [t('Repository'), meta.root]]} /></div></div>`;
}

export function RadioCubePanel({ mac }) {
  useSections(['inventory', 'station']);
  const row = ((section('inventory') || {}).rows || []).find((r) => r.mac === mac);
  if (!row) return html`<${PageHead} title=${t('Unknown cube')} subtitle=${html`${t('No inventory record for')} <${Mac} mac=${mac} />`} />`;
  return html`<div><${PageHead} title=${row.cube_id != null ? t('Cube #{n}', { n: row.cube_id }) : t('Cube without a number')}
      meta=${html`${registrationPill(row)} <${Pill} status=${row.recent ? 'radio.recent' : 'radio.stale'} label=${row.age_s != null ? t('heard {ago} ago', { ago: ago(row.age_s) }) : t('not heard this session')} /> ${row.pinned && html`<${Pill} tone="info" label=${t('USB pinned')} />`} <span class="chip mono" title="MAC"><${Mac} mac=${mac} /></span>`} />
    <${StationBanner} />
    <div class="card"><${Explainer} id="cube.overview" /><div class="grid2"><div><${LedRing} colour=${ledToken(row)} label=${row.cube_id != null ? `#${row.cube_id}` : '—'} sub=${row.status} blink=${row.telemetry && row.telemetry.command === 'identify'} /></div><div><${CubeDetail} row=${row} mac=${mac} /></div></div>
      <h3>${t('Registration')}</h3><${CubeActions} row=${row} mac=${mac} /></div>
    <${History} mac=${mac} /></div>`;
}

export function RadioZonePanel({ mac }) {
  useSections(['registry', 'inventory']);
  const reg = section('registry') || {};
  const z = (reg.zones || (section('inventory') || {}).zones || []).find((x) => x.mac === mac);
  const [gain, setGain] = useState(null);
  if (!z) return html`<${PageHead} title=${t('Unknown zone')} subtitle=${html`${t('No registry record for')} <${Mac} mac=${mac} />`} />`;
  const rxGain = gain ?? (z.rx_gain || 48);
  const log = z.log;
  return html`<div><${PageHead} title=${z.name || html`<${Mac} mac=${mac} />`}
      meta=${html`<${Pill} status=${'zonedb.' + z.state} label=${`DB v${z.db_version} · ${z.state}`} /> <${Pill} tone=${z.in_range ? 'ok' : 'muted'} label=${z.in_range ? t('in range {rssi}', { rssi: z.rssi != null ? Math.round(z.rssi) + ' dBm' : '' }) : t('last seen {when}', { when: z.last_seen || t('never') })} /> ${z.error_text && html`<${Pill} tone="bad" label=${z.error_text} />`} <span class="chip mono" title="MAC"><${Mac} mac=${mac} /></span>`} />
    <div class="card"><${KeyValue} items=${[[t('Type / point'), `${z.zone_label} / ${z.point_id}`], [t('Firmware'), z.firmware], [t('Holds'), t('v{v} · {n} records · CRC {crc}', { v: z.db_version, n: z.db_count, crc: crc(z.db_crc) })], [t('Staging'), z.staging_total ? `v${z.staging_version} ${z.staging_chunks}/${z.staging_total}` : '—'], [t('Stats'), t('{tags} tags · {unknown} unknown · {fail} send failures · uptime {uptime}', { tags: z.tags, unknown: z.unknown_tags, fail: z.send_fail, uptime: ago(z.uptime) })], ['RX gain', z.rx_gain_pending ? `→ ${z.rx_gain_pending} dB …` : z.rx_gain ? `${z.rx_gain} dB${z.rx_gain_applied ? '' : ' ' + t('(not applied)')}` : t('never reported')], [t('Seen'), t('{when} via {source}', { when: z.last_seen, source: z.source })]]} /></div>
    <div class="card"><h3>${t('Over the air (via the station / dongle)')}</h3><div class="row">
      <${ActionButton} name="zones.update" args=${{ mac }} label=${t('Update database over the air')} disabled=${z.state !== 'behind' || !reg.connected} hazard=${t('Unicast announce + broadcast chunks until the zone reports the new version and CRC.')} />
      <${ActionButton} name="zones.identify" args=${{ mac, seconds: 10 }} label=${t('Identify (10 s)')} disabled=${!reg.connected} /><${ActionButton} name="zones.request_log" args=${{ mac }} label=${t('Request tap log')} disabled=${!reg.connected} />
      <${ActionButton} name="zones.reboot" args=${{ mac }} label=${t('Reboot')} hazard=${t('ZONE_REBOOT over the radio.')} disabled=${!reg.connected} />
      <label class="lbl">RX gain</label><select class="field" value=${rxGain} onChange=${(e) => setGain(Number(e.target.value))}>${[18, 23, 33, 38, 43, 48].map((g) => html`<option value=${g}>${g} dB</option>`)}</select><${ActionButton} name="zones.set_rx_gain" args=${{ mac, db: Number(rxGain) }} label=${t('Set RX gain')} hazard=${t("ZONE_SET_CONFIG; confirmed only by the zone's next settings report.")} disabled=${!reg.connected} /></div>
      ${!reg.connected && html`<div class="note warn-text">${t('Connect a pairing station or ESP-NOW dongle with zone support to talk to this zone.')}</div>`}</div>
    ${log && html`<div class="card"><h3>${t('Tap log ({n})', { n: log.received })}</h3><div class="log">${(log.entries || []).map((e) => html`<div>${t('{s} s ago', { s: e.age_s })} · ${e.cube_id ? '#' + e.cube_id : t('unknown')} · ${e.uid} · ${e.result}</div>`)}</div></div>`}</div>`;
}
