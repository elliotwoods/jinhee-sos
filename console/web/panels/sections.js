// Bench launcher, settings, and panels for things seen only over the radio (cubes, zones).
import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useUI } from '../lib/hooks.js';
import { section, state, touch } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, PageHead, Mac, withMacs } from '../components/basics.js';
import { applyTheme, ledToken } from '../lib/theme.js';
import { ActionButton } from '../components/actions.js';
import { LedRing } from '../components/canvas.js';
import { CubeActions, CubeDetail, registrationPill, StationBanner, History } from './CubePanel.js';
import { goDevice } from '../router.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { crc, ago } from '../lib/format.js';

const TOOLS = [
  ['Pool light test', 'pooltest', 'PoolRadioTest bridge (emulates radios 1-6)'], ['Pool central diagnostics', 'poolcentral', 'Pool central controller'],
  ['Pool slider calibration', 'zone:3', 'A PoolZone radio (zone type 3)'], ['Preshow cue test', 'zone:1', 'A PreshowZone plate (zone type 1)'],
  ['Preshow bridge status', 'preshowbridge', 'The TouchDesigner media bridge'], ['ESP-NOW range test', 'rangetest', 'A range-test board (RX unit)'],
];

export function BenchSection() {
  useSections(['devices']);
  const devices = section('devices') || [];
  const find = (want) => devices.filter((d) => want.startsWith('zone:') ? d.role === 'zone' && String((d.details || {}).zone_type) === want.slice(5) : d.role === want);
  return html`<div><${PageHead} title="Bench tools" subtitle="Diagnostics that need a particular board on USB." /><${Explainer} id="bench" />
    ${TOOLS.map(([label, want, needs]) => { const found = find(want); return html`<div class="card" key=${want}><div class="row between"><div><strong>${label}</strong><div class="note">needs: ${needs}</div></div>
      <div>${found.length ? found.map((d) => html`<button class="btn primary small" onClick=${() => goDevice(d.id)}>Open · <span class="mono">${d.port}</span></button>`) : html`<${Pill} tone="muted" label="not attached" />`}</div></div></div>`; })}</div>`;
}

export function SettingsSection() {
  useSections(['settings', 'meta']);
  const s = section('settings') || {};
  const meta = section('meta') || {};
  const ui = useUI();
  const setTheme = (t) => { state.ui.theme = applyTheme(t); touch('ui'); };
  const toggle = (key) => (e) => run('console.settings', { key, value: e.target.checked }).catch((x) => notify(x.message, 'bad'));
  return html`<div><${PageHead} title="Settings" /><${Explainer} id="settings" />
    <div class="card"><h3>Appearance</h3><div class="row"><label class="lbl">Theme</label><select class="field" value=${ui.theme} onChange=${(e) => setTheme(e.target.value)}><option value="dark">Dark</option><option value="light">Light</option><option value="system">Match the system</option></select></div></div>
    <div class="card"><h3>Behaviour</h3><div class="stack">
      <label class="check"><input type="checkbox" checked=${!!s.auto_sessions} onChange=${toggle('auto_sessions')} /> Open a live session automatically for every identified board</label>
      <label class="check"><input type="checkbox" checked=${!!s.preview_flash} onChange=${toggle('preview_flash')} /> Preview the selected cube with a 1 s flash (pairing station)</label>
      <label class="check"><input type="checkbox" checked=${!!s.audio} onChange=${toggle('audio')} /> Audio cues (not yet wired)</label></div></div>
    <div class="card" data-doc="settings.auto"><h3>Automatic updates</h3><div class="stack">
      <label class="check"><input type="checkbox" checked=${!!s.auto_zone_db_radio} onChange=${toggle('auto_zone_db_radio')} /> Zone databases over the air: the pairing station (else a General Radio) walks every out-of-date zone in range</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_zone_db_usb} onChange=${toggle('auto_zone_db_usb')} /> Zone databases over USB: database-only update for any configured zone board plugged in that is behind</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_show} onChange=${toggle('auto_show')} /> Main show over the air: cubes in range on an older show are updated (General Radio; never mid-show)</label>
      <label class="check"><input type="checkbox" checked=${!!s.auto_pull} onChange=${toggle('auto_pull')} /> Pull a newer zone database and show from the web (needs the web password)</label>
      <div class="note">Saved on this computer; on by default.</div></div></div>
    <div class="card"><h3>Keyboard</h3><div class="stack note"><div><kbd>Esc</kbd> close a tooltip, else stop every active operation</div><div><kbd>/</kbd> search</div><div><kbd>⌘1</kbd>–<kbd>⌘4</kbd> sections</div><div><kbd>j</kbd>/<kbd>k</kbd> move the rail selection</div><div><kbd>?</kbd> this list</div></div></div>
    <div class="card"><h3>About</h3><${KeyValue} items=${[['Console', meta.console_version], ['Database', meta.database], ['Python API', meta.api_url || 'disabled'], ['Mode', meta.simulate ? 'SIMULATION (fake boards, temporary database copy)' : 'live'], ['Repository', meta.root]]} /></div></div>`;
}

export function RadioCubePanel({ mac }) {
  useSections(['inventory', 'station']);
  const row = ((section('inventory') || {}).rows || []).find((r) => r.mac === mac);
  if (!row) return html`<${PageHead} title="Unknown cube" subtitle=${html`No inventory record for <${Mac} mac=${mac} />`} />`;
  return html`<div><${PageHead} title=${row.cube_id != null ? `Cube #${row.cube_id}` : 'Cube without a number'}
      meta=${html`${registrationPill(row)} <${Pill} status=${row.recent ? 'radio.recent' : 'radio.stale'} label=${row.age_s != null ? `heard ${ago(row.age_s)} ago` : 'not heard this session'} /> ${row.pinned && html`<${Pill} tone="info" label="USB pinned" />`} <span class="chip mono" title="MAC"><${Mac} mac=${mac} /></span>`} />
    <${StationBanner} />
    <div class="card"><${Explainer} id="cube.overview" /><div class="grid2"><div><${LedRing} colour=${ledToken(row)} label=${row.cube_id != null ? `#${row.cube_id}` : '—'} sub=${row.status} blink=${row.telemetry && row.telemetry.command === 'identify'} /></div><div><${CubeDetail} row=${row} mac=${mac} /></div></div>
      <h3>Registration</h3><${CubeActions} row=${row} mac=${mac} /></div>
    <${History} mac=${mac} /></div>`;
}

export function RadioZonePanel({ mac }) {
  useSections(['registry', 'inventory']);
  const reg = section('registry') || {};
  const z = (reg.zones || (section('inventory') || {}).zones || []).find((x) => x.mac === mac);
  const [gain, setGain] = useState(null);
  if (!z) return html`<${PageHead} title="Unknown zone" subtitle=${html`No registry record for <${Mac} mac=${mac} />`} />`;
  const rxGain = gain ?? (z.rx_gain || 48);
  const log = z.log;
  return html`<div><${PageHead} title=${z.name || html`<${Mac} mac=${mac} />`}
      meta=${html`<${Pill} status=${'zonedb.' + z.state} label=${`DB v${z.db_version} · ${z.state}`} /> <${Pill} tone=${z.in_range ? 'ok' : 'muted'} label=${z.in_range ? `in range ${z.rssi != null ? Math.round(z.rssi) + ' dBm' : ''}` : `last seen ${z.last_seen || 'never'}`} /> ${z.error_text && html`<${Pill} tone="bad" label=${z.error_text} />`} <span class="chip mono" title="MAC"><${Mac} mac=${mac} /></span>`} />
    <div class="card"><${KeyValue} items=${[['Type / point', `${z.zone_label} / ${z.point_id}`], ['Firmware', z.firmware], ['Holds', `v${z.db_version} · ${z.db_count} records · CRC ${crc(z.db_crc)}`], ['Staging', z.staging_total ? `v${z.staging_version} ${z.staging_chunks}/${z.staging_total}` : '—'], ['Stats', `${z.tags} tags · ${z.unknown_tags} unknown · ${z.send_fail} send failures · uptime ${ago(z.uptime)}`], ['RX gain', z.rx_gain_pending ? `→ ${z.rx_gain_pending} dB …` : z.rx_gain ? `${z.rx_gain} dB${z.rx_gain_applied ? '' : ' (not applied)'}` : 'never reported'], ['Seen', `${z.last_seen} via ${z.source}`]]} /></div>
    <div class="card"><h3>Over the air (via the station / dongle)</h3><div class="row">
      <${ActionButton} name="zones.update" args=${{ mac }} label="Update database over the air" disabled=${z.state !== 'behind' || !reg.connected} hazard="Unicast announce + broadcast chunks until the zone reports the new version and CRC." />
      <${ActionButton} name="zones.identify" args=${{ mac, seconds: 10 }} label="Identify (10 s)" disabled=${!reg.connected} /><${ActionButton} name="zones.request_log" args=${{ mac }} label="Request tap log" disabled=${!reg.connected} />
      <${ActionButton} name="zones.reboot" args=${{ mac }} label="Reboot" hazard="ZONE_REBOOT over the radio." disabled=${!reg.connected} />
      <label class="lbl">RX gain</label><select class="field" value=${rxGain} onChange=${(e) => setGain(Number(e.target.value))}>${[18, 23, 33, 38, 43, 48].map((g) => html`<option value=${g}>${g} dB</option>`)}</select><${ActionButton} name="zones.set_rx_gain" args=${{ mac, db: Number(rxGain) }} label="Set RX gain" hazard="ZONE_SET_CONFIG; confirmed only by the zone's next settings report." disabled=${!reg.connected} /></div>
      ${!reg.connected && html`<div class="note warn-text">Connect a pairing station or ESP-NOW dongle with zone support to talk to this zone.</div>`}</div>
    ${log && html`<div class="card"><h3>Tap log (${log.received})</h3><div class="log">${(log.entries || []).map((e) => html`<div>${e.age_s} s ago · ${e.cube_id ? '#' + e.cube_id : 'unknown'} · ${e.uid} · ${e.result}</div>`)}</div></div>`}</div>`;
}
