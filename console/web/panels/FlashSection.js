// Guided cube flashing over USB (console/flashflow.py): plug in a cube → firmware → show, one after another.
import { html } from '../lib/html.js';
import { useEffect, useRef } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { Explainer, PageHead, Mac, ActivateSwitch, ProgressBar, Banner } from '../components/basics.js';
import { ActionButton } from '../components/actions.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { hhmmss } from '../lib/format.js';
import { stepStates } from '../lib/register.js';
import { t, tk } from '../lib/i18n.js';

const LABELS = { usb: 'USB', firmware: tk('Firmware'), show: tk('Show') };

function Stepper({ f }) {
  // A cube that cannot answer "?" has no MAC until esptool reads it: the port key stands in for it.
  const states = stepStates({ ...f, mac: f.key });
  return html`<ol class="reg-steps" aria-label=${t('flashing steps')}>${(f.steps || []).map((s, i) => html`<li class=${'reg-step ' + states[s]} aria-current=${states[s] === 'current' ? 'step' : undefined}>
    <span class="n">${states[s] === 'done' ? '✓' : states[s] === 'failed' ? '✕' : i + 1}</span><span>${LABELS[s] ? t(LABELS[s]) : s}</span></li>`)}</ol>`;
}

// Tell the operator once per result, whichever page is open.
export function FlashNotices() {
  useSections(['flash']);
  const f = section('flash') || {};
  const seen = useRef(null);
  const n = f.notice;
  useEffect(() => {
    if (!n) return;
    if (seen.current === null) { seen.current = n.id; return; }   // the page just loaded: not news
    if (n.id !== seen.current) { seen.current = n.id; notify(n.text, n.tone, n.tone === 'ok' ? 8000 : 6000); }
  }, [n && n.id]);
  return null;
}

const SHOW_TEXT = {
  current: (v) => t('Show v{v} was already on the cube', { v }),
  written: (v) => t('Show v{v} written to NVS, read back, and reported by the cube', { v }),
  newer: (v) => t('The cube holds show v{v}, newer than the published one; kept', { v }),
  unsupported: () => t('Firmware too old to hold a show; the built-in show is kept'),
};

function Prompt({ f }) {
  const who = f.number != null ? t('Cube #{number}', { number: f.number }) : t('The cube');
  if (!f.key) return html`<div class="prompt">${f.enabled ? t('Plug in a cube over USB') : t('Switch on, then plug in a cube over USB')}</div>`;
  if (f.step === 'done') return html`<div class="prompt ok-text">✓ ${t('{who} is up to date. Unplug it and plug in the next cube.', { who })}</div>`;
  if (f.step === 'failed') return html`<div class="prompt bad-text">${f.error}</div>`;
  if (f.step === 'show') return html`<div class="prompt">${t('{who}: checking the show in its storage…', { who })}</div>`;
  return html`<div class="prompt">${t('{who}: firmware… keep it plugged in', { who })}</div>`;
}

function Result({ f }) {
  const r = f.result || {};
  if (f.step !== 'done' || !r.ui_result) return null;
  return html`<div class="stack">
    <div class="row"><span class="lbl">${t('Firmware')}</span><span>${r.ui_result === 'success' ? t('{version} written and verified', { version: r.version }) : t('{version} already on this cube', { version: r.version })}</span></div>
    <div class="row"><span class="lbl">${t('Show')}</span><span class=${r.show_result === 'newer' || r.show_result === 'unsupported' ? 'warn-text' : ''}>
      ${f.show ? (SHOW_TEXT[r.show_result] || (() => r.show_result))(r.show_version) : t('No published show on this computer; the built-in show is kept')}</span></div>
  </div>`;
}

function History({ items }) {
  if (!items || !items.length) return null;
  const tone = { flashed: 'ok', failed: 'bad' };
  return html`<div class="card"><h3>${t('This session')}</h3><table class="data"><thead><tr><th>${t('Number')}</th><th>MAC</th><th>${t('Firmware')}</th><th>${t('Show')}</th><th>${t('Result')}</th><th>${t('Time')}</th><th>${t('Detail')}</th></tr></thead>
    <tbody>${items.map((h, i) => html`<tr key=${h.mac || h.port || i}><td>${h.number != null ? '#' + h.number : '—'}</td><td>${h.mac ? html`<${Mac} mac=${h.mac} />` : h.port}</td>
      <td>${h.firmware === 'success' ? t('written') : h.firmware === 'skipped' ? t('already current') : h.firmware || ''}</td>
      <td>${h.show ? `${h.show}${h.show_version ? ' · v' + h.show_version : ''}` : ''}</td>
      <td class=${(tone[h.result] || '') + '-text'}>${h.result}</td><td>${hhmmss(h.at)}</td><td class="note">${h.detail || ''}</td></tr>`)}</tbody></table></div>`;
}

export function FlashSection() {
  useSections(['flash']);
  const f = section('flash') || {};
  const toggle = (on) => run('flash.enable', { on }).catch((x) => notify(x.message, 'bad'));
  const fw = f.firmware || {};
  const running = ['firmware', 'show'].includes(f.step);
  const job = f.job || {};
  return html`<div><${PageHead} title=${t('Flash cubes')} subtitle=${t('Plug in → firmware → show, over USB')}
      meta=${html`<span class=${'chip ' + (fw.error ? 'bad' : 'ok')} title=${fw.error || ''}>${fw.error ? t('Firmware build not ready') : t('Firmware {version}', { version: fw.version || '—' })}</span>
        <span class=${'chip ' + (f.published ? 'ok' : 'warn')}>${f.published ? t('Show v{v}', { v: f.published.version }) : t('No published show')}</span>`} />
    <${ActivateSwitch} on=${!!f.enabled} onChange=${toggle} doc="flash.enable" label=${t('Flash cubes as they are plugged in')}
      detail=${f.enabled ? t('Every cube on USB, now or plugged in later, gets the firmware (skipped if it already has this build) and the published show, once per plug-in.')
        : t('Off: plugging in a cube does nothing here. It is off every time the console starts.')} />
    <${Explainer} id="flash" />
    ${fw.error && html`<${Banner} kind="bad" title=${t('The cube firmware build is not ready')} detail=${fw.error} />`}
    <div class="card wizard" data-doc="flash.flow">
      <${Stepper} f=${f} />
      <${Prompt} f=${f} />
      ${f.key && html`<div class="row"><span class="lbl">${t('Cube')}</span>${f.mac ? html`<${Mac} mac=${f.mac} />` : html`<span class="note">${t('MAC not read yet')}</span>`}<span class="note">${f.port || ''}</span></div>`}
      ${running && html`<div class="stack"><div class="note">${job.stage || t('Starting')}</div><${ProgressBar} value=${job.progress} indeterminate=${job.progress == null} /></div>`}
      <${Result} f=${f} />
      <div class="row">
        ${f.step === 'failed' && html`<${ActionButton} name="flash.retry" label=${t('Retry (rewrite the firmware)')} className="btn primary" />`}
      </div>
    </div>
    <${History} items=${f.history} />
  </div>`;
}
