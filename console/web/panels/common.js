import { html } from '../lib/html.js';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { Pill, KeyValue, Explainer, PageHead, Mac, withMacs } from '../components/basics.js';
import { ActionButton } from '../components/actions.js';
import { Console, JobCard } from '../components/data.js';
import { deviceLabel } from '../lib/rail.js';

export function findDevice(id) {
  return (section('devices') || []).find((d) => d.id === id || d.port === id) || null;
}
export function sessionOf(device) {
  const sessions = section('sessions') || {};
  return device ? sessions[device.id] || null : null;
}
export function rowByMac(mac) { return ((section('inventory') || {}).rows || []).find((r) => r.mac === mac) || null; }
export function rowByNumber(n) { return ((section('inventory') || {}).rows || []).find((r) => r.cube_id === n) || null; }
export function jobsFor(device) { return (section('jobs') || []).filter((j) => j.device === device.id); }

// The device page header: name, USB/identity marks and connection actions, then a card of facts if any.
export function DeviceHeader({ device, title, pills, kv }) {
  useSections(['devices', 'sessions', 'jobs']);
  const running = jobsFor(device).find((j) => j.state === 'running');
  const canConnect = ['idle', 'present'].includes(device.state) && !running && device.role && device.role !== 'unknown';
  const meta = html`<${Pill} status=${'usb.' + device.state} /> ${pills}
    <span class="chip mono" title="port">${device.port}</span>
    ${device.mac && html`<span class="chip mono" title="MAC"><${Mac} mac=${device.mac} /></span>`}
    ${device.firmware && html`<span class="chip mono" title="firmware">${device.firmware}</span>`}`;
  const actions = html`
    ${device.state !== 'job' && html`<${ActionButton} name="device.probe" args=${{ device: device.id }} label="Identify again" className="btn small quiet" title="Ask the board what it is (no reset)" />`}
    ${device.pinned && html`<${ActionButton} name="device.unpin" args=${{}} label="Unpin" className="btn small" />`}
    ${device.state === 'session' && html`<${ActionButton} name="device.disconnect" args=${{ device: device.id }} label="Disconnect" className="btn small" />`}
    ${canConnect && html`<${ActionButton} name="device.connect" args=${{ device: device.id }} label="Connect" className="btn small primary" />`}`;
  const facts = (device.presumed && device.presumed.label) || device.error || kv || running;
  return html`<${PageHead} title=${title || deviceLabel(device)} meta=${meta} actions=${actions} />
    ${facts && html`<div class="card">
      ${device.presumed && device.presumed.label && html`<div class="note">Inventory: ${withMacs(device.presumed.label)}</div>`}
      ${device.error && html`<div class="warn-text">${device.error}</div>`}
      ${kv && html`<${KeyValue} items=${kv} />`}
      ${running && html`<${JobCard} job=${running} />`}
    </div>`}`;
}

export function RawConsole({ device, hint }) {
  return html`<div class="card"><h3>Console</h3><${Console} device=${device.id} hint=${hint || '?'} /></div>`;
}

export function JobHistory({ device }) {
  useSections(['jobs']);
  const jobs = jobsFor(device).filter((j) => j.state !== 'running').slice(0, 5);
  if (!jobs.length) return null;
  return html`<div class="card"><h3>Recent jobs on this port</h3><div>${jobs.map((j) => html`<${JobCard} key=${j.id} job=${j} />`)}</div></div>`;
}
