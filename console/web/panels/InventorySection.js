import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections, useCopy, useUI } from '../lib/hooks.js';
import { section, setSearch } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, Tabs, NumberField, PageHead, Mac, StatTile, withMacs } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { DataTable, JobCard } from '../components/data.js';
import { LedRing } from '../components/canvas.js';
import { FILTERS, inventoryFilter, filterLabel } from '../lib/table.js';
import { t } from '../lib/i18n.js';
import { CubeActions, CubeDetail, registrationPill, StationBanner, History, FlashRuns } from './CubePanel.js';
import { ZoneRelay, zoneId } from './WorkstationPanel.js';
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
    { key: 'status', label: t('Registration'), render: (r) => registrationPill(r) }, { key: 'uid', label: t('Tag'), mono: true, render: (r) => r.uid || (r.pending_uid ? t('pending {uid}', { uid: r.pending_uid }) : '—') },
    { key: 'original_number', label: t('Original'), render: (r) => r.original_number != null ? `#${r.original_number}${r.nfc_seen ? ' ✓' : ''}` : '' },
    { key: 'age_s', label: t('Radio'), render: (r) => r.age_s == null ? html`<${Pill} status="radio.stale" label="—" />` : html`<${Pill} status=${r.recent ? 'radio.recent' : 'radio.stale'} label=${ago(r.age_s)} />` },
    { key: 'role', label: t('Role') }, { key: 'usb_firmware', label: t('USB firmware'), render: (r) => r.usb_firmware ? html`<${Pill} status=${'firmware.' + r.usb_firmware.status} label=${r.usb_firmware.version || '?'} />` : (r.on_usb ? t('on USB') : '') },
    { key: 'updated_at', label: t('Updated'), mono: true },
  ];
  return html`<div><${Explainer} id="inventory" />
    <div class="card"><div class="row"><div class="filters" role="radiogroup" aria-label=${t('filter')}>${FILTERS.map((f) => html`<button class=${'btn small' + (filter === f ? ' primary' : '')} role="radio" aria-checked=${filter === f ? 'true' : 'false'} onClick=${() => setFilter(f)}>${filterLabel(f)}</button>`)}</div>
      <input class="field" type="search" data-doc="inventory.search" placeholder=${t('Search inventory')} value=${ui.search} onInput=${(e) => setSearch(e.target.value)} aria-label=${t('search inventory')} />
      <span class="spacer"></span><button class="btn small quiet" onClick=${() => setView(view === 'table' ? 'grid' : 'table')}>${view === 'table' ? '▦ ' + t('Grid view') : '☰ ' + t('Table view')}</button></div>
      <div class="row"><span class="note">${t('{n} shown', { n: rows.length })}</span><span class="btn-group">
        <${ActionButton} name="pairing.transmit_originals" args=${{}} label=${t('Transmit original 32')} disabled=${!connected} hazard=${t('Sends each original mapping to its cube; refuses changed originals.')} />
        <${ActionButton} name="pairing.retry_unconfirmed" args=${{}} label=${t('Retry unconfirmed')} disabled=${!connected} hazard=${t('Retransmits every unconfirmed saved registration.')} />
        <${ActionButton} name="pairing.flash" args=${{ macs: rows.filter((r) => r.role !== 'excluded').map((r) => r.mac), sequential: true }} label=${t('Flash all shown (2 s each)')} disabled=${!connected || !rows.length} />
        <${ActionButton} name="pairing.stop" args=${{}} label=${t('Stop')} className="btn small" disabled=${!connected} /></span>
        <span class="spacer"></span><span class="menu"><${ExportMenu} /></span></div>
      ${view === 'table' ? html`<${DataTable} columns=${columns} rows=${rows} keyOf=${(r) => r.mac} doc="inventory.table" rowDoc=${(r) => `inventory.row:${r.mac}`} selected=${selected} onSelect=${(k) => setSelected(k === selected ? null : k)} empty=${t('No devices match')} />`
        : html`<div class="ring-grid" data-doc="inventory.table">${rows.map((r) => html`<div key=${r.mac} class="ring-tile" aria-current=${selected === r.mac ? 'true' : 'false'} onClick=${() => setSelected(r.mac === selected ? null : r.mac)}><${LedRing} size=${90} colour=${ledToken(r)} label=${r.cube_id != null ? `#${r.cube_id}` : '—'} sub=${r.recent ? t('heard') : ''} blink=${r.telemetry && r.telemetry.command === 'identify'} />${registrationPill(r)}</div>`)}</div>`}</div>
    <${StationBanner} />
    ${row && html`<div class="card"><h2>${row.cube_id != null ? t('Cube #{n}', { n: row.cube_id }) : t('Device without a number')} <span class="note"><${Mac} mac=${row.mac} /></span> ${row.on_usb && html`<a class="note" href="#" onClick=${(e) => { e.preventDefault(); goDevice(row.mac); }}>${t('Open USB panel →')}</a>`}</h2>
      <div class="grid2"><div><${CubeDetail} row=${row} mac=${row.mac} /></div><div><${CubeActions} row=${row} mac=${row.mac} /></div></div>
      <details><summary class="note">${t('History & sightings')}</summary><${History} mac=${row.mac} /></details></div>`}</div>`;
}

function ExportMenu() {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState('');
  const go = async (name) => { try { const p = await run(name, { path }); notify(t('Written {path}', { path: p }), 'ok'); setOpen(false); } catch (e) { notify(e.message, 'bad'); } };
  return html`<span class="relative"><button class="btn small" onClick=${() => setOpen(!open)}>${t('Export')} ▾</button>
    ${open && html`<div class="popover right"><label class="lbl">${t('File path on this computer')}</label><input class="field wide" value=${path} onInput=${(e) => setPath(e.target.value)} placeholder=${t('/path/to/devices.csv or CubeTable.h')} />
      <div class="row"><button class="btn small" onClick=${() => go('inventory.export_csv')}>CSV</button><button class="btn small" onClick=${() => go('inventory.export_header')}>${t('Reader table header')}</button><button class="btn small quiet" onClick=${() => setOpen(false)}>${t('Close')}</button></div>
      <div class="note">${t('data/devices.csv is refreshed automatically after every change.')}</div></div>`}</span>`;
}

export function ZoneDb() {
  useSections(['inventory', 'registry', 'sync']);
  const inv = section('inventory') || {};
  const reg = section('registry') || {};
  const pub = inv.published || {};
  const zones = (reg.zones && reg.zones.length ? reg.zones : inv.zones) || [];
  const columns = [{ key: 'name', label: t('Zone'), render: (z) => html`<a href="#" onClick=${(e) => { e.preventDefault(); goDevice(zoneId(z)); }}>${z.name || z.mac}</a>` }, { key: 'mac', label: 'MAC', mono: true }, { key: 'zone_type', label: t('Type') }, { key: 'point_id', label: t('Point') }, { key: 'firmware', label: t('Firmware'), mono: true },
    { key: 'db_version', label: t('Holds'), render: (z) => html`v${z.db_version} · CRC ${crc(z.db_crc)} ${z.state && html`<${Pill} status=${'zonedb.' + z.state} />`}` }, { key: 'last_seen', label: t('Last seen'), render: (z) => `${z.last_seen || '—'} (${z.source || '?'})` }, { key: 'rx_gain', label: 'RX gain' }];
  return html`<div><${Explainer} id="inventory.zonedb" />
    <div class="card"><h3>${t('Published zone database')}</h3>
      <${KeyValue} items=${[[t('Version'), pub.version ? t('v{version} · {count} records · CRC {crc}', { version: pub.version, count: pub.count, crc: crc(pub.crc) }) : t('nothing published yet')], [t('Published'), pub.published_at ? t('{at} by {who}', { at: pub.published_at, who: pub.published_by }) : '—'], [t('Universal version'), pub.universal ? t('yes (web-allocated)') : t('legacy local counter')],
        [t('This computer'), inv.local_differs ? html`<span class="warn-text">${t('local mappings differ from the published image — Sync publishes a new version')}</span>` : t('matches the published image')], [t('Problem'), inv.published_error]]} />
      <div class="row"><${ActionButton} name="sync.run" args=${{}} label=${t('Sync (inventory + zone DB)')} className="btn primary" /><${ActionButton} name="zone.publish" args=${{}} label=${t('Publish (allocates the next universal version)')} /><${ActionButton} name="zone.pull" args=${{}} label=${t('Pull from the web')} /></div></div>
    <div class="card"><h3>${t('What each zone holds')}</h3><${DataTable} columns=${columns} rows=${zones} keyOf=${(z) => z.mac} empty=${t('No zones recorded yet')} /></div>
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
    <div class="card"><h3>${t('Web inventory')}</h3><div class="row"><span class=${'chip ' + syncTone(sync.tone)}>${sync.text}</span><span class="note">${sync.detail}</span></div>
      <${KeyValue} items=${[[t('State'), st.state],
        [t('To upload'), st.zone_publish ? t('{n} inventory changes + zone database', { n: st.inventory_up ?? 0 }) : t('{n} inventory changes', { n: st.inventory_up ?? 0 })],
        [t('To download'), st.zone_pull ? t('{n} web changes + zone database v{version}', { n: st.inventory_down ?? 0, version: st.web_version }) : t('{n} web changes', { n: st.inventory_down ?? 0 })],
        [t('Waiting'), st.waiting ? t('{n} downloaded changes wait for the apps to be idle', { n: st.waiting }) : t('none')], [t('Lost'), st.lost ? t('{n} local devices would give way to a newer change', { n: st.lost }) : t('none')],
        [t('Web zone DB'), st.web_version ? `v${st.web_version}` : '—'], [t('Checked'), sync.checked_at ? hhmmss(sync.checked_at) : t('not yet')], [t('Password'), sync.password_known ? t('stored on this computer') : t('not entered (click Sync in the top bar)')]]} />
      <div class="row"><span class="btn-group"><${ActionButton} name="sync.run" args=${{}} label=${t('Sync now')} className="btn primary" disabled=${sync.busy} /><${ActionButton} name="sync.check" args=${{}} label=${t('Check')} what=${t('Compare this computer, the web and the baseline without writing: the record-by-record plan of the next Sync.')} disabled=${sync.busy || !sync.password_known} reason=${!sync.password_known ? t('Sign in first (Sync in the top bar)') : null} /><${ActionButton} name="sync.status" args=${{}} label=${t('Refresh status')} className="btn small" /></span>
        <span class="btn-group"><${ActionButton} name="sync.upload" args=${{}} label=${t('Upload only')} disabled=${sync.busy} /><${ActionButton} name="sync.download" args=${{}} label=${t('Download only')} disabled=${sync.busy} /></span>
        <span class="btn-group"><${ActionButton} name="zone.publish" args=${{}} label=${t('Publish zone DB')} /><${ActionButton} name="zone.pull" args=${{}} label=${t('Pull zone DB')} /></span>
        <span class="spacer"></span><${ActionButton} name="sync.forget" args=${{}} label=${t('Forget password')} className="btn small quiet" /></div>
      ${sync.last_error && html`<div class="bad-text">${sync.last_error.kind}: ${sync.last_error.text}</div>`}
      ${sync.summary && html`<${Banner} kind="warn" title=${t('A newer change elsewhere took priority')} detail=${sync.summary} />`}
      ${lost.length ? html`<div class="log">${lost.map((l) => html`<div>${l.text || JSON.stringify(l)}</div>`)}</div>` : null}
      ${jobs.map((j) => html`<${JobCard} key=${j.id} job=${j} compact />`)}</div>
    ${sync.plan && html`<${SyncPlan} plan=${sync.plan} />`}
    <div class="note">${t('Sync never asks for a decision: the newest change to a device wins and every decision is audited (sync_resolved). Records are never deleted.')}</div></div>`;
}


// One side of a planned sync row: the check job gives records (dicts); the documentation bench gives strings.
function planSide(v) {
  if (v == null || v === '') return '—';
  if (typeof v !== 'object') return String(v);
  const tag = v.uid || (v.pending_uid ? t('pending {uid}', { uid: v.pending_uid }) : t('no tag'));
  return `${v.cube_id != null ? '#' + v.cube_id : t('no number')} · ${tag}${v.role && v.role !== 'auto' ? ' · ' + v.role : ''}`;
}

export function SyncPlan({ plan }) {
  const rows = (plan && plan.rows) || [];
  const lost = (plan && plan.lost) || [];
  const notes = (plan && plan.notes) || [];
  const change = (c) => (c === 'both' ? t('upload + download') : c === 'upload' ? t('upload') : c === 'download' ? t('download') : c);
  const columns = [{ key: 'mac', label: 'MAC', mono: true }, { key: 'change', label: t('Change'), render: (r) => html`<${Pill} tone=${r.change === 'both' ? 'warn' : r.change === 'upload' ? 'info' : 'ok'} label=${change(r.change)} />` },
    { key: 'local', label: t('This computer'), render: (r) => planSide(r.local) }, { key: 'web', label: t('Web'), render: (r) => planSide(r.web) }, { key: 'after', label: t('After'), render: (r) => planSide(r.after) },
    { key: 'decided', label: t('Decided'), render: (r) => r.decided ? html`<${Pill} tone="warn" label=${t('newest wins')} tip=${t('Both sides changed this device; the newer change takes the number and tags whole (audited as sync_resolved).')} />` : '' }];
  return html`<div class="card"><${Explainer} id="inventory.plan" />
    <div class="row"><h3>${t('What a Sync would move')}</h3><span class="note">${t('checked {time}', { time: plan.checked_at ? hhmmss(plan.checked_at) : '—' })}${plan.revision != null ? ` · ${t('web revision {n}', { n: plan.revision })}` : ''}</span><span class="spacer"></span><${ActionButton} name="sync.plan_clear" args=${{}} label=${t('Clear')} className="btn small quiet" /></div>
    <div class="tiles"><${StatTile} label=${t('To upload')} value=${plan.upload ?? 0} /><${StatTile} label=${t('To download')} value=${plan.download ?? 0} /><${StatTile} label=${t('Lost locally')} value=${lost.length} tone=${lost.length ? 'warn' : ''} /></div>
    ${notes.length > 0 && html`<div class="plan-notes">${notes.map((n) => html`<div>${typeof n === 'string' ? n : JSON.stringify(n)}</div>`)}</div>`}
    ${lost.length > 0 && html`<div class="plan-lost"><strong class="warn-text">${t('Local devices that would give way to a newer change')}</strong>${lost.map((l) => html`<div>${withMacs(typeof l === 'string' ? l : (l.text || JSON.stringify(l)))}</div>`)}</div>`}
    <${DataTable} columns=${columns} rows=${rows} keyOf=${(r) => r.mac} doc="websync.plan" empty=${t('Nothing would move: this computer and the web agree')} /></div>`;
}

export function Events() {
  useSections(['inventory']);
  const inv = section('inventory') || {};
  return html`<div class="card"><h3>${t('Recent audit events')}</h3><${DataTable} columns=${[{ key: 'time', label: t('Time'), mono: true }, { key: 'mac', label: 'MAC', mono: true }, { key: 'action', label: t('Action') }, { key: 'detail', label: t('Detail') }]} rows=${inv.events || []} keyOf=${(e) => e.time + e.mac + e.action + e.detail} empty=${t('No events')} /></div>`;
}

export function InventorySection() {
  const ui = useUI();
  const tab = ui.route.tab || 'cubes';
  return html`<div><${PageHead} title=${t('Inventory & database')} subtitle=${t('Every cube and zone this computer knows about, the published zone database and the web copy.')} />
    <${Tabs} tabs=${[['cubes', t('Cubes')], ['zonedb', t('Zone database')], ['websync', t('Web sync')], ['flashruns', t('Flash runs')], ['events', t('Events')]]} current=${tab} onChange=${(id) => navigate('#/inventory/' + id)} />
    ${tab === 'cubes' && html`<${Cubes} />`}${tab === 'zonedb' && html`<${ZoneDb} />`}${tab === 'websync' && html`<${WebSync} />`}
    ${tab === 'flashruns' && html`<div class="card"><${FlashRuns} /></div>`}${tab === 'events' && html`<${Events} />`}</div>`;
}
