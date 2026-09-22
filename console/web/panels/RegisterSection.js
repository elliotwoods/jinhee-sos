// Guided cube registration (console/regflow.py): plug in a cube → number → NFC scan → sync, one after another.
import { html } from '../lib/html.js';
import { useEffect, useRef } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { Explainer, PageHead, Mac, NumberField, ActivateSwitch } from '../components/basics.js';
import { ActionButton } from '../components/actions.js';
import { StationBanner } from './CubePanel.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { hhmmss } from '../lib/format.js';
import { stepStates } from '../lib/register.js';
import { t, tk } from '../lib/i18n.js';

const LABELS = { usb: 'USB', number: tk('Number'), nfc: tk('NFC scan'), sync: tk('Sync') };

function Stepper({ r }) {
  const states = stepStates(r);
  return html`<ol class="reg-steps" aria-label=${t('registration steps')}>${(r.steps || []).map((s, i) => html`<li class=${'reg-step ' + states[s]} aria-current=${states[s] === 'current' || states[s] === 'waiting' ? 'step' : undefined}>
    <span class="n">${states[s] === 'done' ? '✓' : states[s] === 'failed' ? '✕' : i + 1}</span><span>${LABELS[s] ? t(LABELS[s]) : s}</span></li>`)}</ol>`;
}

// Tell the operator once per notice (a new number, a result), whichever page is open.
export function RegisterNotices() {
  useSections(['register']);
  const r = section('register') || {};
  const seen = useRef(null);
  const n = r.notice;
  useEffect(() => {
    if (!n) return;
    if (seen.current === null) { seen.current = n.id; return; }   // the page just loaded: not news
    if (n.id !== seen.current) { seen.current = n.id; notify(n.text, n.tone, n.tone === 'ok' ? 8000 : 5000); }
  }, [n && n.id]);
  return null;
}

function Prompt({ r }) {
  if (!r.mac) return html`<div class="prompt">${t('Plug in a cube over USB')}</div>`;
  if (r.step === 'done') return html`<div class="prompt ok-text">✓ ${t('Cube #{number} registered and synced. Unplug it and plug in the next cube.', { number: r.number })}</div>`;
  if (r.step === 'failed') return html`<div class="prompt bad-text">${r.error}</div>`;
  if (r.wait) return html`<div class="prompt">${r.wait}</div>`;
  if (r.step === 'nfc') return html`<div class="prompt">${t('Cube #{number} is flashing: hold its NFC tag on the pairing station reader', { number: r.number })}</div>`;
  if (r.step === 'sync') return html`<div class="prompt">${t('Syncing…')}</div>`;
  return html`<div class="prompt">${t('Working…')}</div>`;
}

function NumberCard({ r }) {
  if (r.number == null) return null;
  const fresh = r.number_new === 'assigned';
  const canChange = r.step === 'nfc' || (r.step === 'failed' && r.failed_step === 'nfc');
  return html`<div class=${'reg-number' + (fresh ? ' fresh' : '')}>
    <div class="big">#${r.number}</div>
    <div class="stack">
      ${fresh ? html`<strong>${t("NEW NUMBER: write #{number} on the cube's label", { number: r.number })}</strong>`
        : r.number_new === 'label' ? html`<span>${t('Number from the label')}</span>` : html`<span>${t('This cube already had number #{number}', { number: r.number })}</span>`}
      ${canChange && html`<${NumberField} key=${r.mac + ':' + r.number} value=${r.number} label=${t('Label says')} onSubmit=${(n) => run('register.renumber', { number: n })} />`}
    </div></div>`;
}

function History({ items }) {
  if (!items || !items.length) return null;
  const tone = { registered: 'ok', failed: 'bad', cancelled: 'warn', interrupted: 'warn' };
  return html`<div class="card"><h3>${t('This session')}</h3><table class="data"><thead><tr><th>${t('Number')}</th><th>MAC</th><th>${t('New')}</th><th>${t('Result')}</th><th>${t('Time')}</th><th>${t('Detail')}</th></tr></thead>
    <tbody>${items.map((h) => html`<tr key=${h.mac}><td>${h.number != null ? '#' + h.number : '—'}</td><td><${Mac} mac=${h.mac} /></td><td>${h.new ? t('new') : ''}</td>
      <td class=${(tone[h.result] || '') + '-text'}>${h.result}</td><td>${hhmmss(h.at)}</td><td class="note">${h.detail || ''}</td></tr>`)}</tbody></table></div>`;
}

export function RegisterSection() {
  useSections(['register', 'station', 'sync']);
  const r = section('register') || {};
  const st = section('station') || {};
  const active = ['number', 'nfc', 'sync'].includes(r.step);
  const toggle = (on) => run('register.enable', { on }).catch((x) => notify(x.message, 'bad'));
  const stationText = !st.present ? t('No pairing station') : !st.connected ? t('Station connecting') : st.reader_ok ? t('Station ready · NFC ok') : t('Station connected · NFC reader not ready');
  return html`<div><${PageHead} title=${t('Register cubes')} subtitle=${t('Plug in → number → scan the tag → sync')}
      meta=${html`<span class=${'chip ' + (st.present && st.connected && st.reader_ok ? 'ok' : 'warn')}>${stationText}</span>`} />
    <${ActivateSwitch} on=${!!r.enabled} onChange=${toggle} doc="register.enable" label=${t('Register cubes as they are plugged in')}
      detail=${r.enabled ? t('Plug in a cube over USB; it is taken through number, tag scan and sync.') : t('Off: plugging in a cube does nothing here. Switch on to start; a cube already plugged in is registered straight away.')} />
    <${Explainer} id="register" />
    <div class="card wizard" data-doc="register.flow">
      <${Stepper} r=${r} />
      <${Prompt} r=${r} />
      ${r.mac && html`<div class="row"><span class="lbl">${t('Cube')}</span><${Mac} mac=${r.mac} /><span class="note">${r.port || ''}${r.unplugged ? ' · ' + t('unplugged') : ''}</span>
        ${r.usb_confirmed != null && html`<span class="chip ok" title=${t('The cube printed REGISTERED over USB')}>${t('cube confirmed #{number} over USB', { number: r.usb_confirmed })}</span>`}</div>`}
      <${NumberCard} r=${r} />
      ${r.step === 'nfc' && r.armed && html`<${StationBanner} />`}
      ${r.sync_summary && html`<div class="note">${t('Sync: {summary}', { summary: r.sync_summary })}</div>`}
      ${r.sync_warning && html`<div class="warn-text">${r.sync_warning}</div>`}
      ${r.step === 'done' && html`<div class="note">${t('Zones learn the tag once they hold the published database: automatic zone updates bring it to zones in range (Update all is the manual path).')}</div>`}
      <div class="row">
        ${r.step === 'failed' && html`<${ActionButton} name="register.retry" label=${r.failed_step === 'sync' ? t('Sync again') : t('Retry')} className="btn primary" />`}
        ${r.mac && !active && html`<${ActionButton} name="register.restart" label=${t('Start again for this cube')} disabled=${r.unplugged} reason=${t('The cube is unplugged')} />`}
        ${active && html`<${ActionButton} name="register.cancel" label=${t('Cancel')} className="btn quiet" />`}
      </div>
    </div>
    <${History} items=${r.history} />
  </div>`;
}
