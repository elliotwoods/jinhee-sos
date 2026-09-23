// The top of the right sidebar, "Automatic updates" (one line when idle): firmware builds, USB boards being brought up to date, and what the
// radios report (zone databases, cube shows, firmware heard over the air). Everything here runs by itself
// (autoupgrade.py, the zone and show registries); the operator can pause it, skip a board or retry.
import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { t, tk } from '../lib/i18n.js';
import { Pill, ProgressBar } from './basics.js';
import { ActionButton } from './actions.js';

const STATES = {
  queued: ['pending', tk('queued')], building: ['info', tk('building')], failed: ['bad', tk('failed')],
  no_tools: ['warn', tk('no build tools')], running: ['info', tk('upgrading')], waiting: ['pending', tk('waiting')],
  settling: ['pending', tk('waiting')], checking: ['info', tk('checking')], build: ['pending', tk('needs build')],
  skipped: ['muted', tk('skipped')], paused: ['muted', tk('paused')], off: ['muted', tk('off')], report: ['warn', tk('by hand')],
};

function StatePill({ state }) {
  const [tone, label] = STATES[state] || ['muted', state];
  return html`<${Pill} tone=${tone} label=${t(label)} />`;
}

function Row({ title, sub, state, reason, progress, stage, children }) {
  const live = state === 'running' || state === 'building';
  return html`<div class="auto-row"><div class="head"><strong>${title}</strong><${StatePill} state=${state} /></div>
    ${sub && html`<div class="note mono">${sub}</div>`}
    ${live && stage && html`<div class="stage">${stage}</div>`}
    ${live && html`<${ProgressBar} value=${progress} indeterminate=${progress == null} />`}
    ${!live && reason && html`<div class="note">${reason}</div>`}
    ${children && html`<div class="actions">${children}</div>`}</div>`;
}

function count(counts, key) { return (counts || {})[key] || 0; }

function Heard({ firmware }) {
  if (!(firmware || []).length) return null;
  return html`<details class="auto-air"><summary>${t('{n} heard over the air in the last day with older firmware: plug in over USB to upgrade', { n: firmware.length })}</summary>
    ${firmware.map((f) => html`<div class="note mono">${f.label} · ${f.current} → ${f.version}</div>`)}</details>`;
}

function Air({ air, quiet }) {
  const zones = air.zones;
  const show = air.show;
  const lines = [];
  if (quiet) {   // up to date: only what still needs someone (out of range, older firmware heard over the air)
    const away = count((zones || {}).counts, 'away') + count((show || {}).counts, 'away');
    if (away) lines.push(html`<div class="auto-air note">${t('{n} more behind, out of range: updated when a radio next hears them', { n: away })}</div>`);
    lines.push(html`<${Heard} firmware=${air.firmware} />`);
    return lines;
  }
  if (zones) {
    const behind = count(zones.counts, 'nearby');
    const updating = count(zones.counts, 'updating');
    const walking = (zones.walking || []).find((w) => w.publishing);
    lines.push(html`<div class="auto-air"><span>${t('Zone databases')}</span><span class=${behind ? 'warn-text' : ''}>${
      t('v{version}: {current} current · {behind} behind · {updating} updating', { version: zones.published || 0, current: count(zones.counts, 'current'), behind, updating })}</span>
      ${walking && html`<div class="note">${walking.label}: ${walking.message}</div>`}
      ${count(zones.counts, 'away') ? html`<div class="note">${t('{n} more behind, out of range: updated when a radio next hears them', { n: count(zones.counts, 'away') })}</div>` : ''}
      ${!zones.auto && behind ? html`<div class="note">${t('Over-the-air zone updates are off (Settings › Automatic updates)')}</div>` : ''}</div>`);
  }
  if (show) {
    const behind = count(show.counts, 'nearby');
    lines.push(html`<div class="auto-air"><span>${t('Main show')}</span><span class=${behind ? 'warn-text' : ''}>${
      t('v{version}: {current} current · {behind} behind', { version: show.published || 0, current: count(show.counts, 'current'), behind })}</span>
      ${show.publishing && html`<div class="note">${show.message}</div>`}
      ${count(show.counts, 'away') ? html`<div class="note">${t('{n} more behind, out of range: updated when a radio next hears them', { n: count(show.counts, 'away') })}</div>` : ''}</div>`);
  }
  lines.push(html`<${Heard} firmware=${air.firmware} />`);
  return lines;
}

// Something the console is doing or waiting on now. Boards out of radio range and firmware heard over the air
// are still listed below the line, but do not keep the block from saying it is up to date.
function pending(data) {
  const air = data.air || {};
  return (data.builds || []).some((b) => b.state !== 'current') || (data.devices || []).length > 0 ||
    count((air.zones || {}).counts, 'nearby') + count((air.zones || {}).counts, 'updating') + count((air.show || {}).counts, 'nearby') > 0;
}

export function AutoUpdates() {
  useSections(['autoupdate']);
  const data = section('autoupdate');
  const [open, setOpen] = useState(false);
  if (!data) return null;
  const builds = (data.builds || []).filter((b) => b.state !== 'current');
  const devices = data.devices || [];
  const busy = data.running > 0;
  const off = !data.auto_build && !data.auto_firmware_usb;
  const summary = data.paused ? t('Paused') : busy ? t('Working') : off ? t('Off') : '';
  const expanded = open || busy || devices.some((d) => d.state !== 'report');
  return html`<section aria-label=${t('Automatic updates')} data-doc="autoupdate"><h4><span>${t('Automatic updates')}</span>
      <span class="badges">${summary && html`<span class=${busy ? 'info-text' : 'note'}>${summary}</span>`}
        <${ActionButton} name="autoupgrade.pause" args=${{ paused: !data.paused }} label=${data.paused ? t('Resume') : t('Pause')} className="btn small quiet" /></span></h4>
    ${!pending(data) ? html`<div class="empty">${t('✓ Everything up to date')}</div><${Air} air=${data.air || {}} quiet />` : html`<div class="auto">
      ${builds.map((b) => html`<${Row} key=${b.target} title=${t('Build {label}', { label: b.label })} sub=${b.version} state=${b.state} reason=${b.reason}
          progress=${b.progress} stage=${b.stage}>${b.state === 'failed' ? html`<${ActionButton} name="autoupgrade.retry" args=${{ target: b.target }} label=${t('Retry')} className="btn small" />` : ''}</${Row}>`)}
      ${(expanded ? devices : devices.filter((d) => d.state !== 'report')).map((d) => html`<${Row} key=${d.key} title=${d.label}
          sub=${`${d.port} · ${d.current || '?'} → ${d.version || '?'}`} state=${d.state} reason=${d.reason} progress=${d.progress} stage=${d.stage}>
        ${['waiting', 'settling', 'build', 'paused', 'off'].includes(d.state) ? html`<${ActionButton} name="autoupgrade.skip" args=${{ device: d.device }} label=${t('Skip')} className="btn small quiet" />` : ''}
        ${['skipped', 'failed'].includes(d.state) ? html`<${ActionButton} name="autoupgrade.retry" args=${{ device: d.device }} label=${t('Retry')} className="btn small" />` : ''}</${Row}>`)}
      ${!expanded && devices.length ? html`<button class="btn small quiet" onClick=${() => setOpen(true)}>${t('{n} to upgrade by hand', { n: devices.length })}</button>` : ''}
      <${Air} air=${data.air || {}} /></div>`}
    ${(data.history || []).length ? html`<details class="auto-history"><summary class="note">${t('Recent ({n})', { n: data.history.length })}</summary>
      ${data.history.map((h) => html`<div class=${'note ' + (h.ok ? '' : 'bad-text')}>${h.ok ? '✓' : '✕'} ${h.label} ${h.version || ''}${h.port ? ` · ${h.port}` : ''}${h.ok ? '' : ` · ${h.text}`}</div>`)}</details>` : ''}
  </section>`;
}
