import { html } from '../lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { useCopy } from '../lib/hooks.js';
import { glyph } from '../lib/tones.js';
import { dismiss } from '../lib/notify.js';
import { isMac, knownTail, splitMac } from '../lib/mac.js';
import { useDocOpen, docExplainers } from '../lib/doc.js';

export function Pill({ status, tone, label, tip }) {
  const copy = useCopy();
  const [open, setOpen] = useState(false);
  const entry = status ? copy.status[status] : null;
  const t = tone || (entry && entry.tone) || 'muted';
  const text = label || (entry && entry.label) || status || '';
  const help = tip || (entry && entry.tip);
  return html`<span class=${'pill ' + t} title=${open ? '' : (help || '')}>${glyph(t)} ${text}
    ${help && html`<button class="why" aria-label="explain" aria-expanded=${open ? 'true' : 'false'} onClick=${(e) => { e.stopPropagation(); setOpen(!open); }} onBlur=${() => setOpen(false)}>?</button>`}
    ${open && help && html`<span class="pill-tip" role="note">${help}</span>`}</span>`;
}

// A MAC address with its identifying tail large and the rest small. `stacked` puts the head above
// the tail (tables); otherwise they sit inline. Click copies the full address.
export function Mac({ mac, stacked }) {
  if (!isMac(mac)) return mac ?? '—';
  const [head, tail] = splitMac(mac, knownTail());
  const copy = (e) => { e.stopPropagation(); try { navigator.clipboard.writeText(mac.toUpperCase()); } catch (x) { /* ignore */ } };
  return html`<span class=${'mac' + (stacked ? ' stacked' : '')} title=${`${mac.toUpperCase()} · click to copy`} onClick=${copy}>${head && html`<span class="mac-head">${head}</span>`}<span class="mac-tail">${tail}</span></span>`;
}

// Exactly six bytes: longer colon-separated hex (7-byte NFC UIDs) is left alone.
const MAC_IN_TEXT = /(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])/g;

// Text with every MAC in it rendered as <Mac>; other values pass through unchanged.
export function withMacs(value) {
  if (typeof value !== 'string' || !MAC_IN_TEXT.test(value)) return value;
  MAC_IN_TEXT.lastIndex = 0;
  const out = [];
  let last = 0;
  for (const m of value.matchAll(MAC_IN_TEXT)) {
    if (m.index > last) out.push(value.slice(last, m.index));
    out.push(html`<${Mac} mac=${m[0]} />`);
    last = m.index + m[0].length;
  }
  if (last < value.length) out.push(value.slice(last));
  return out;
}

// Items are [key, value] or [key, value, docToken] (the token lands on the value cell for the documentation outlines).
export function KeyValue({ items }) {
  return html`<dl class="kv">${items.filter(Boolean).map(([k, v, doc]) => html`<dt>${k}</dt><dd data-doc=${doc}>${withMacs(v) ?? '—'}</dd>`)}</dl>`;
}

// The truth ladder as a row of steps: sent → delivered → acknowledged → verified. `level` is the step reached
// (null: nothing in flight), `failed` paints the reached step red. Labels come from uitext.LADDER.
export function Ladder({ level, failed, note, doc }) {
  const copy = useCopy();
  const steps = ['sent', 'delivered', 'acknowledged', 'verified'];
  const idx = steps.indexOf(level);
  const bad = failed || level === 'failed';
  return html`<div class=${'ladder' + (bad ? ' failed' : '')} data-doc=${doc} aria-label="delivery ladder">
    ${steps.map((s, i) => html`${i > 0 && html`<span class="arrow">→</span>`}<span class=${'step' + (idx > i ? ' done' : idx === i ? ' current' : '')}>${(copy.ladder || {})[s] || s}</span>`)}
    ${note && html`<span class="note">${note}</span>`}</div>`;
}

export function Banner({ kind, title, detail, children, doc }) {
  return html`<div class=${'banner ' + (kind || '')} role="status" data-doc=${doc}><div class="title">${title}</div>${detail && html`<div class="detail">${detail}</div>`}${children}</div>`;
}

export function Explainer({ id }) {
  const copy = useCopy();
  const p = copy.panels[id];
  const key = 'nct.explainer.' + id;
  let open = true;
  try { open = localStorage.getItem(key) !== '0'; } catch (e) { /* private mode */ }
  if (docExplainers() || useDocOpen('explainer:' + id)) open = true;
  if (!p) return null;
  return html`<details class="explainer" data-doc=${'explainer:' + id} open=${open} onToggle=${(e) => { try { localStorage.setItem(key, e.target.open ? '1' : '0'); } catch (x) { /* ignore */ } }}>
    <summary>${p.title}</summary><div>${p.what}</div><div class="check">Check: ${p.check}</div></details>`;
}

// Title + status marks on the left, actions on the right. Used by sections and device panels alike.
export function PageHead({ title, subtitle, meta, actions }) {
  return html`<header class="page-head"><div><h1 class="title">${title}</h1>
      ${subtitle && html`<div class="subtitle">${subtitle}</div>`}
      ${meta && html`<div class="page-meta">${meta}</div>`}</div>
    ${actions && html`<div class="page-actions">${actions}</div>`}</header>`;
}

export function StatTile({ label, value, tone }) {
  return html`<div class="tile"><div class=${'v ' + (tone ? tone + '-text' : '')}>${value ?? '—'}</div><div class="l">${label}</div></div>`;
}

export function ProgressBar({ value, indeterminate }) {
  return html`<div class=${'progress' + (indeterminate ? ' indeterminate' : '')} role="progressbar" aria-valuenow=${indeterminate ? undefined : Math.round(value || 0)}><div style=${`width:${indeterminate ? 30 : Math.max(0, Math.min(100, value || 0))}%`}></div></div>`;
}

export function Tabs({ tabs, current, onChange }) {
  return html`<div class="tabs" role="tablist">${tabs.map(([id, label]) => html`<button role="tab" data-doc=${'tab:' + id} aria-selected=${current === id ? 'true' : 'false'} aria-current=${current === id ? 'true' : 'false'} onClick=${() => onChange(id)}>${label}</button>`)}</div>`;
}

export function NumberField({ value, suggested, onSubmit, label = 'Number', busy }) {
  const [text, setText] = useState(value != null ? String(value) : suggested != null ? String(suggested) : '');
  const [err, setErr] = useState(null);
  useEffect(() => { if (value == null && suggested != null && !text) setText(String(suggested)); }, [suggested]);
  const submit = async (e) => {
    e && e.preventDefault();
    const n = parseInt(text, 10);
    if (!(n > 0)) return setErr('Enter a whole number');
    try { setErr(null); await onSubmit(n); } catch (x) { setErr(x.message); }
  };
  return html`<form class="row" onSubmit=${submit}>${label && html`<label class="lbl">${label}</label>`}
    <input class="field num" inputmode="numeric" value=${text} onInput=${(e) => setText(e.target.value)} placeholder=${suggested != null ? String(suggested) : ''} />
    <button class="btn small primary" data-doc="inventory.number" disabled=${busy}>Set</button>
    ${suggested != null && value == null && html`<span class="note">Enter accepts the suggested free number ${suggested}</span>`}
    ${err && html`<span class="bad-text">${err}</span>`}</form>`;
}

// The newest three notifications; errors stay until dismissed.
export function Toasts({ items }) {
  if (!items.length) return null;
  return html`<div class="toasts">${items.slice(-3).map((t) => html`<div key=${t.id} class=${'toast ' + (t.tone || '')} role=${t.tone === 'bad' ? 'alert' : 'status'}>
    <span class="text">${t.text}</span><button class="close" aria-label="dismiss" onClick=${() => dismiss(t.id)}>×</button></div>`)}</div>`;
}

export function Copyable({ text }) {
  const [done, setDone] = useState(false);
  const copy = () => { try { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); } catch (e) { /* ignore */ } };
  return html`<span class="mono copyable" title=${done ? 'copied' : 'click to copy'} onClick=${copy}>${text}</span>`;
}
