import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useCopy, useUI } from '../lib/hooks.js';
import { section, setSearch } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, Tabs, NumberField, PageHead, Mac, StatTile, withMacs } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { DataTable, JobCard } from '../components/data.js';
import { LedRing } from '../components/canvas.js';
import { FILTERS, inventoryFilter } from '../lib/table.js';
import { CubeActions, CubeDetail, registrationPill, StationBanner, History, FlashRuns } from './CubePanel.js';
import { ZoneRelay, zoneId } from './PairingStationPanel.js';
import { crc, ago, hhmmss } from '../lib/format.js';
import { syncTone } from '../lib/tones.js';
import { ledToken } from '../lib/theme.js';
import { navigate, goDevice } from '../router.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';

export function Cubes() {
  useSections(['inventory', 'station', 'ui']);
  const ui = useUI();
  const inv = section('inventory') || {};
  const st = section('station') || {};
  const [filter, setFilter] = useState('All devices');
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState('table');
  const rows = (inv.rows || []).filter((r) => inventoryFilter(r, filter, ui.search));
  const row = rows.find((r) => r.mac === selected) || (inv.rows || []).find((r) => r.mac === selected);
  const connected = st.present && st.connected;
  const columns = [
    { key: 'cube_id', label: '#', render: (r) => r.cube_id != null ? `#${r.cube_id}` : '—' }, { key: 'mac', label: 'MAC', mono: true },
    { key: 'status', label: 'Registration', render: (r) => registrationPill(r) }, { key: 'uid', label: 'Tag', mono: true, render: (r) => r.uid || (r.pending_uid ? `pending ${r.pending_uid}` : '—') },
    { key: 'original_number', label: 'Original', render: (r) => r.original_number != null ? `#${r.original_number}${r.nfc_seen ? ' ✓' : ''}` : '' },
    { key: 'age_s', label: 'Radio', render: (r) => r.age_s == null ? html`<${Pill} status="radio.stale" label="—" />` : html`<${Pill} status=${r.recent ? 'radio.recent' : 'radio.stale'} label=${ago(r.age_s)} />` },
    { key: 'role', label: 'Role' }, { key: 'usb_firmware', label: 'USB firmware', render: (r) => r.usb_firmware ? html`<${Pill} status=${'firmware.' + r.usb_firmware.status} label=${r.usb_firmware.version || '?'} />` : (r.on_usb ? 'on USB' : '') },
    { key: 'updated_at', label: 'Updated', mono: true },
  ];
  return html`<div><${Explainer} id="inventory" />
    <div class="card"><div class="row"><div class="filters" role="radiogroup" aria-label="filter">${FILTERS.map((f) => html`<button class=${'btn small' + (filter === f ? ' primary' : '')} role="radio" aria-checked=${filter === f ? 'true' : 'false'} onClick=${() => setFilter(f)}>${f}</button>`)}</div>
      <input class="field" type="search" data-doc="inventory.search" placeholder="Search number, MAC, UID, original number" value=${ui.search} onInput=${(e) => setSearch(e.target.value)} aria-label="search inventory" />
      <span class="spacer"></span><button class="btn small quiet" onClick=${() => setView(view === 'table' ? 'grid' : 'table')}>${view === 'table' ? '▦ Grid view' : '☰ Table view'}</button></div>
      <div class="row"><span class="note">${rows.length} shown</span><span class="btn-group">
        <${ActionButton} name="pairing.transmit_originals" args=${{}} label="Transmit original 32" disabled=${!connected} hazard="Sends each original mapping to its cube; refuses changed originals." />
        <${ActionButton} name="pairing.retry_unconfirmed" args=${{}} label="Retry unconfirmed" disabled=${!connected} hazard="Retransmits every unconfirmed saved registration." />
        <${ActionButton} name="pairing.flash" args=${{ macs: rows.filter((r) => r.role !== 'excluded').map((r) => r.mac), sequential: true }} label="Flash all shown (2 s each)" disabled=${!connected || !rows.length} />
        <${ActionButton} name="pairing.stop" args=${{}} label="Stop" className="btn small" disabled=${!connected} /></span>
        <span class="spacer"></span><span class="menu"><${ExportMenu} /></span></div>
      ${view === 'table' ? html`<${DataTable} columns=${columns} rows=${rows} keyOf=${(r) => r.mac} doc="inventory.table" rowDoc=${(r) => `inventory.row:${r.mac}`} selected=${selected} onSelect=${(k) => setSelected(k === selected ? null : k)} empty="No devices match" />`
        : html`<div class="ring-grid" data-doc="inventory.table">${rows.map((r) => html`<div key=${r.mac} class="ring-tile" aria-current=${selected === r.mac ? 'true' : 'false'} onClick=${() => setSelected(r.mac === selected ? null : r.mac)}><${LedRing} size=${90} colour=${ledToken(r)} label=${r.cube_id != null ? `#${r.cube_id}` : '—'} sub=${r.recent ? 'heard' : ''} blink=${r.telemetry && r.telemetry.command === 'identify'} />${registrationPill(r)}</div>`)}</div>`}</div>
    <${StationBanner} />
    ${row && html`<div class="card"><h2>${row.cube_id != null ? `Cube #${row.cube_id}` : 'Device without a number'} <span class="note"><${Mac} mac=${row.mac} /></span> ${row.on_usb && html`<a class="note" href="#" onClick=${(e) => { e.preventDefault(); goDevice(row.mac); }}>Open USB panel →</a>`}</h2>
      <div class="grid2"><div><${CubeDetail} row=${row} mac=${row.mac} /></div><div><${CubeActions} row=${row} mac=${row.mac} /></div></div>
      <details><summary class="note">History & sightings</summary><${History} mac=${row.mac} /></details></div>`}</div>`;
}

function ExportMenu() {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState('');
  const go = async (name) => { try { const p = await run(name, { path }); notify(`Written ${p}`, 'ok'); setOpen(false); } catch (e) { notify(e.message, 'bad'); } };
  return html`<span class="relative"><button class="btn small" onClick=${() => setOpen(!open)}>Export ▾</button>
    ${open && html`<div class="popover right"><label class="lbl">File path on this computer</label><input class="field wide" value=${path} onInput=${(e) => setPath(e.target.value)} placeholder="/path/to/devices.csv or CubeTable.h" />
      <div class="row"><button class="btn small" onClick=${() => go('inventory.export_csv')}>CSV</button><button class="btn small" onClick=${() => go('inventory.export_header')}>Reader table header</button><button class="btn small quiet" onClick=${() => setOpen(false)}>Close</button></div>
      <div class="note">data/devices.csv is refreshed automatically after every change.</div></div>`}</span>`;
}

export function ZoneDb() {
  useSections(['inventory', 'registry', 'sync']);
  const inv = section('inventory') || {};
  const reg = section('registry') || {};
  const pub = inv.published || {};
  const zones = (reg.zones && reg.zones.length ? reg.zones : inv.zones) || [];
  const columns = [{ key: 'name', label: 'Zone', render: (z) => html`<a href="#" onClick=${(e) => { e.preventDefault(); goDevice(zoneId(z)); }}>${z.name || z.mac}</a>` }, { key: 'mac', label: 'MAC', mono: true }, { key: 'zone_type', label: 'Type' }, { key: 'point_id', label: 'Point' }, { key: 'firmware', label: 'Firmware', mono: true },
    { key: 'db_version', label: 'Holds', render: (z) => html`v${z.db_version} · CRC ${crc(z.db_crc)} ${z.state && html`<${Pill} status=${'zonedb.' + z.state} />`}` }, { key: 'last_seen', label: 'Last seen', render: (z) => `${z.last_seen || '—'} (${z.source || '?'})` }, { key: 'rx_gain', label: 'RX gain' }];
  return html`<div><${Explainer} id="inventory.zonedb" />
    <div class="card"><h3>Published zone database</h3>
      <${KeyValue} items=${[['Version', pub.version ? `v${pub.version} · ${pub.count} records · CRC ${crc(pub.crc)}` : 'nothing published yet'], ['Published', pub.published_at ? `${pub.published_at} by ${pub.published_by}` : '—'], ['Universal version', pub.universal ? 'yes (web-allocated)' : 'legacy local counter'],
        ['This computer', inv.local_differs ? html`<span class="warn-text">local mappings differ from the published image — Sync publishes a new version</span>` : 'matches the published image'], ['Problem', inv.published_error]]} />
      <div class="row"><${ActionButton} name="sync.run" args=${{}} label="Sync (inventory + zone DB)" className="btn primary" /><${ActionButton} name="zone.publish" args=${{}} label="Publish (allocates the next universal version)" /><${ActionButton} name="zone.pull" args=${{}} label="Pull from the web" /></div></div>
    <div class="card"><h3>What each zone holds</h3><${DataTable} columns=${columns} rows=${zones} keyOf=${(z) => z.mac} empty="No zones recorded yet" /></div>
    ${reg.present && html`<${ZoneRelay} />`}</div>`;
}

export function WebSync() {
  useSections(['sync', 'jobs']);
  const sync = section('sync') || {};
  const st = sync.status || {};
  const last = sync.last_result || {};
  const lost = (last.sync && last.sync.lost) || [];
  const jobs = (section('jobs') || []).filter((j) => j.kind.startsWith('sync') || j.kind.startsWith('zone.p')).slice(0, 3);
  return html`<div><${Explainer} id="inventory.websync" />
    <div class="card"><h3>Web inventory</h3><div class="row"><span class=${'chip ' + syncTone(sync.tone)}>${sync.text}</span><span class="note">${sync.detail}</span></div>
      <${KeyValue} items=${[['State', st.state], ['To upload', `${st.inventory_up ?? 0} inventory changes${st.zone_publish ? ' + zone database' : ''}`], ['To download', `${st.inventory_down ?? 0} web changes${st.zone_pull ? ` + zone database v${st.web_version}` : ''}`], ['Waiting', st.waiting ? `${st.waiting} downloaded changes wait for the apps to be idle` : 'none'], ['Lost', st.lost ? `${st.lost} local devices would give way to a newer change` : 'none'], ['Web zone DB', st.web_version ? `v${st.web_version}` : '—'], ['Checked', sync.checked_at ? hhmmss(sync.checked_at) : 'not yet'], ['Password', sync.password_known ? 'stored on this computer' : 'not entered (click Sync in the top bar)']]} />
      <div class="row"><span class="btn-group"><${ActionButton} name="sync.run" args=${{}} label="Sync now" className="btn primary" disabled=${sync.busy} /><${ActionButton} name="sync.check" args=${{}} label="Check" what="Compare this computer, the web and the baseline without writing: the record-by-record plan of the next Sync." disabled=${sync.busy || !sync.password_known} reason=${!sync.password_known ? 'Sign in first (Sync in the top bar)' : null} /><${ActionButton} name="sync.status" args=${{}} label="Refresh status" className="btn small" /></span>
        <span class="btn-group"><${ActionButton} name="sync.upload" args=${{}} label="Upload only" disabled=${sync.busy} /><${ActionButton} name="sync.download" args=${{}} label="Download only" disabled=${sync.busy} /></span>
        <span class="btn-group"><${ActionButton} name="zone.publish" args=${{}} label="Publish zone DB" /><${ActionButton} name="zone.pull" args=${{}} label="Pull zone DB" /></span>
        <span class="spacer"></span><${ActionButton} name="sync.forget" args=${{}} label="Forget password" className="btn small quiet" /></div>
      ${sync.last_error && html`<div class="bad-text">${sync.last_error.kind}: ${sync.last_error.text}</div>`}
      ${sync.summary && html`<${Banner} kind="warn" title="A newer change elsewhere took priority" detail=${sync.summary} />`}
      ${lost.length ? html`<div class="log">${lost.map((l) => html`<div>${l.text || JSON.stringify(l)}</div>`)}</div>` : null}
      ${jobs.map((j) => html`<${JobCard} key=${j.id} job=${j} compact />`)}</div>
    ${sync.plan && html`<${SyncPlan} plan=${sync.plan} />`}
    <div class="note">Sync never asks for a decision: the newest change to a device wins and every decision is audited (sync_resolved). Records are never deleted.</div></div>`;
}


// One side of a planned sync row: the check job gives records (dicts); the documentation bench gives strings.
function planSide(v) {
  if (v == null || v === '') return '—';
  if (typeof v !== 'object') return String(v);
  const tag = v.uid || (v.pending_uid ? `pending ${v.pending_uid}` : 'no tag');
  return `${v.cube_id != null ? '#' + v.cube_id : 'no number'} · ${tag}${v.role && v.role !== 'auto' ? ' · ' + v.role : ''}`;
}

export function SyncPlan({ plan }) {
  const rows = (plan && plan.rows) || [];
  const lost = (plan && plan.lost) || [];
  const notes = (plan && plan.notes) || [];
  const columns = [{ key: 'mac', label: 'MAC', mono: true }, { key: 'change', label: 'Change', render: (r) => html`<${Pill} tone=${r.change === 'both' ? 'warn' : r.change === 'upload' ? 'info' : 'ok'} label=${r.change === 'both' ? 'upload + download' : r.change} />` },
    { key: 'local', label: 'This computer', render: (r) => planSide(r.local) }, { key: 'web', label: 'Web', render: (r) => planSide(r.web) }, { key: 'after', label: 'After', render: (r) => planSide(r.after) },
    { key: 'decided', label: 'Decided', render: (r) => r.decided ? html`<${Pill} tone="warn" label="newest wins" tip="Both sides changed this device; the newer change takes the number and tags whole (audited as sync_resolved)." />` : '' }];
  return html`<div class="card"><${Explainer} id="inventory.plan" />
    <div class="row"><h3>What a Sync would move</h3><span class="note">checked ${plan.checked_at ? hhmmss(plan.checked_at) : '—'}${plan.revision != null ? ` · web revision ${plan.revision}` : ''}</span><span class="spacer"></span><${ActionButton} name="sync.plan_clear" args=${{}} label="Clear" className="btn small quiet" /></div>
    <div class="tiles"><${StatTile} label="To upload" value=${plan.upload ?? 0} /><${StatTile} label="To download" value=${plan.download ?? 0} /><${StatTile} label="Lost locally" value=${lost.length} tone=${lost.length ? 'warn' : ''} /></div>
    ${notes.length > 0 && html`<div class="plan-notes">${notes.map((n) => html`<div>${typeof n === 'string' ? n : JSON.stringify(n)}</div>`)}</div>`}
    ${lost.length > 0 && html`<div class="plan-lost"><strong class="warn-text">Local devices that would give way to a newer change</strong>${lost.map((l) => html`<div>${withMacs(typeof l === 'string' ? l : (l.text || JSON.stringify(l)))}</div>`)}</div>`}
    <${DataTable} columns=${columns} rows=${rows} keyOf=${(r) => r.mac} doc="websync.plan" empty="Nothing would move: this computer and the web agree" /></div>`;
}

export function Events() {
  useSections(['inventory']);
  const inv = section('inventory') || {};
  return html`<div class="card"><h3>Recent audit events</h3><${DataTable} columns=${[{ key: 'time', label: 'Time', mono: true }, { key: 'mac', label: 'MAC', mono: true }, { key: 'action', label: 'Action' }, { key: 'detail', label: 'Detail' }]} rows=${inv.events || []} keyOf=${(e) => e.time + e.mac + e.action + e.detail} empty="No events" /></div>`;
}

export function InventorySection() {
  const ui = useUI();
  const tab = ui.route.tab || 'cubes';
  return html`<div><${PageHead} title="Inventory & database" subtitle="Every cube and zone this computer knows about, the published zone database and the web copy." />
    <${Tabs} tabs=${[['cubes', 'Cubes'], ['zonedb', 'Zone database'], ['websync', 'Web sync'], ['flashruns', 'Flash runs'], ['events', 'Events']]} current=${tab} onChange=${(t) => navigate('#/inventory/' + t)} />
    ${tab === 'cubes' && html`<${Cubes} />`}${tab === 'zonedb' && html`<${ZoneDb} />`}${tab === 'websync' && html`<${WebSync} />`}
    ${tab === 'flashruns' && html`<div class="card"><${FlashRuns} /></div>`}${tab === 'events' && html`<${Events} />`}</div>`;
}
