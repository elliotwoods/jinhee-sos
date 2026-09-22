// Guided cube registration (console/regflow.py): plug in a cube → number → NFC scan → sync, one after another.
import { html } from '../lib/html.js';
import { useEffect, useRef } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { Explainer, PageHead, Mac, NumberField, Banner } from '../components/basics.js';
import { ActionButton } from '../components/actions.js';
import { StationBanner } from './CubePanel.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { hhmmss } from '../lib/format.js';
import { stepStates } from '../lib/register.js';

const LABELS = { usb: 'USB', number: 'Number', nfc: 'NFC scan', sync: 'Sync' };

function Stepper({ r }) {
  const states = stepStates(r);
  return html`<ol class="reg-steps" aria-label="registration steps">${(r.steps || []).map((s, i) => html`<li class=${'reg-step ' + states[s]} aria-current=${states[s] === 'current' || states[s] === 'waiting' ? 'step' : undefined}>
    <span class="n">${states[s] === 'done' ? '✓' : states[s] === 'failed' ? '✕' : i + 1}</span><span>${LABELS[s] || s}</span></li>`)}</ol>`;
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
  if (!r.mac) return html`<div class="prompt">Plug in a cube over USB</div>`;
  if (r.step === 'done') return html`<div class="prompt ok-text">✓ Cube #${r.number} registered and synced. Unplug it and plug in the next cube.</div>`;
  if (r.step === 'failed') return html`<div class="prompt bad-text">${r.error}</div>`;
  if (r.wait) return html`<div class="prompt">${r.wait}</div>`;
  if (r.step === 'nfc') return html`<div class="prompt">Cube #${r.number} is flashing: hold its NFC tag on the pairing station reader</div>`;
  if (r.step === 'sync') return html`<div class="prompt">Syncing…</div>`;
  return html`<div class="prompt">Working…</div>`;
}

function NumberCard({ r }) {
  if (r.number == null) return null;
  const fresh = r.number_new === 'assigned';
  const canChange = r.step === 'nfc' || (r.step === 'failed' && r.failed_step === 'nfc');
  return html`<div class=${'reg-number' + (fresh ? ' fresh' : '')}>
    <div class="big">#${r.number}</div>
    <div class="stack">
      ${fresh ? html`<strong>NEW NUMBER: write #${r.number} on the cube's label</strong>`
        : r.number_new === 'label' ? html`<span>Number from the label</span>` : html`<span>This cube already had number #${r.number}</span>`}
      ${canChange && html`<${NumberField} key=${r.mac + ':' + r.number} value=${r.number} label="Label says" onSubmit=${(n) => run('register.renumber', { number: n })} />`}
    </div></div>`;
}

function History({ items }) {
  if (!items || !items.length) return null;
  const tone = { registered: 'ok', failed: 'bad', cancelled: 'warn', interrupted: 'warn' };
  return html`<div class="card"><h3>This session</h3><table class="data"><thead><tr><th>Number</th><th>MAC</th><th>New</th><th>Result</th><th>Time</th><th>Detail</th></tr></thead>
    <tbody>${items.map((h) => html`<tr key=${h.mac}><td>${h.number != null ? '#' + h.number : '—'}</td><td><${Mac} mac=${h.mac} /></td><td>${h.new ? 'new' : ''}</td>
      <td class=${(tone[h.result] || '') + '-text'}>${h.result}</td><td>${hhmmss(h.at)}</td><td class="note">${h.detail || ''}</td></tr>`)}</tbody></table></div>`;
}

export function RegisterSection() {
  useSections(['register', 'station', 'sync']);
  const r = section('register') || {};
  const st = section('station') || {};
  const active = ['number', 'nfc', 'sync'].includes(r.step);
  const toggle = (e) => run('register.enable', { on: e.target.checked }).catch((x) => notify(x.message, 'bad'));
  const stationText = !st.present ? 'No pairing station' : !st.connected ? 'Station connecting' : st.reader_ok ? 'Station ready · NFC ok' : 'Station connected · NFC reader not ready';
  return html`<div><${PageHead} title="Register cubes" subtitle="Plug in → number → scan the tag → sync"
      meta=${html`<span class=${'chip ' + (st.present && st.connected && st.reader_ok ? 'ok' : 'warn')}>${stationText}</span>`}
      actions=${html`<label class="check big-toggle"><input type="checkbox" checked=${!!r.enabled} onChange=${toggle} data-doc="register.enable" /> Register cubes as they are plugged in</label>`} />
    <${Explainer} id="register" />
    ${!r.enabled && html`<${Banner} kind="info" title="Switched off" detail="Switch it on, then plug in a cube over USB. A cube already plugged in is registered straight away." />`}
    <div class="card wizard" data-doc="register.flow">
      <${Stepper} r=${r} />
      <${Prompt} r=${r} />
      ${r.mac && html`<div class="row"><span class="lbl">Cube</span><${Mac} mac=${r.mac} /><span class="note">${r.port || ''}${r.unplugged ? ' · unplugged' : ''}</span>
        ${r.usb_confirmed != null && html`<span class="chip ok" title="The cube printed REGISTERED over USB">cube confirmed #${r.usb_confirmed} over USB</span>`}</div>`}
      <${NumberCard} r=${r} />
      ${r.step === 'nfc' && r.armed && html`<${StationBanner} />`}
      ${r.sync_summary && html`<div class="note">Sync: ${r.sync_summary}</div>`}
      ${r.sync_warning && html`<div class="warn-text">${r.sync_warning}</div>`}
      ${r.step === 'done' && html`<div class="note">Zones learn the tag once they hold the published database: automatic zone updates bring it to zones in range (Update all is the manual path).</div>`}
      <div class="row">
        ${r.step === 'failed' && html`<${ActionButton} name="register.retry" label=${r.failed_step === 'sync' ? 'Sync again' : 'Retry'} className="btn primary" />`}
        ${r.mac && !active && html`<${ActionButton} name="register.restart" label="Start again for this cube" disabled=${r.unplugged} reason="The cube is unplugged" />`}
        ${active && html`<${ActionButton} name="register.cancel" label="Cancel" className="btn quiet" />`}
      </div>
    </div>
    <${History} items=${r.history} />
  </div>`;
}
