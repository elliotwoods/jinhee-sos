// Buttons that talk to the backend. One click runs an action; destructive ones are held (server-side token).
// Every button carries data-doc (the command name unless `doc` is given) as a stable hook for documentation,
// and a Tip: what the action does, its warning, what it needs and, when disabled, why.
import { html } from '../lib/html.js';
import { useState, useEffect, useRef } from 'preact/hooks';
import { run } from '../api.js';
import { state } from '../store.js';
import { useCopy } from '../lib/hooks.js';
import { notify } from '../lib/notify.js';
import { useDocOpen } from '../lib/doc.js';

let tipSeq = 0;
const kindOf = (name) => ((state.commands || {})[name] || {}).kind || 'safe';

// Hover (after a short delay) or keyboard focus shows a panel next to the wrapped control. The wrapper is a
// span because a disabled button fires no mouse events. Text comes from props, else uitext.ACTIONS[name].
// `initialOpen` shows the panel right after mount (documentation links: ?open=<token>).
export function Tip({ name, label, what, hazard, needs, reason, disabled, children, delay = 350, initialOpen = false }) {
  const copy = (useCopy().actions || {})[name] || {};
  const [pos, setPos] = useState(null);
  const ref = useRef(null); const timer = useRef(0);
  const id = useRef(`tip-${++tipSeq}`).current;
  const body = {
    title: label || copy.label, what: what || copy.what, hazard: hazard || copy.hazard, needs: needs || copy.needs,
    reason: disabled ? (reason || copy.disabled) : null,
  };
  const has = body.what || body.hazard || body.needs || body.reason;
  const show = (now) => {
    clearTimeout(timer.current);
    if (!has) return;
    const place = () => {
      const r = ref.current && ref.current.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom > 160 || r.top < 160;
      setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - 356)), top: below ? r.bottom + 6 : null, bottom: below ? null : window.innerHeight - r.top + 6 });
    };
    if (now) place(); else timer.current = setTimeout(place, delay);
  };
  const hide = () => { clearTimeout(timer.current); setPos(null); };
  useEffect(() => {
    if (!pos) return undefined;
    const esc = (e) => { if (e.key === 'Escape') hide(); };
    window.addEventListener('keydown', esc, true); window.addEventListener('scroll', hide, true);
    return () => { window.removeEventListener('keydown', esc, true); window.removeEventListener('scroll', hide, true); };
  }, [pos]);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => { if (initialOpen) { const id = setTimeout(() => show(true), 50); return () => clearTimeout(id); } return undefined; }, [initialOpen, has]);
  const style = pos ? `left:${pos.left}px;${pos.top != null ? `top:${pos.top}px` : `bottom:${pos.bottom}px`}` : '';
  return html`<span class="tip" ref=${ref} aria-describedby=${pos ? id : undefined}
      onMouseEnter=${() => show(false)} onMouseLeave=${hide} onFocusCapture=${() => show(true)} onBlurCapture=${hide} onMouseDown=${hide}>
    ${children}
    ${pos && html`<span class="tip-panel" role="tooltip" id=${id} style=${style}>
      ${body.title && html`<strong class="tip-title">${body.title}</strong>`}
      ${body.what && html`<span class="tip-what">${body.what}</span>`}
      ${body.hazard && html`<span class="tip-hazard">▲ ${body.hazard}</span>`}
      ${body.needs && html`<span class="tip-needs"><b>Needs:</b> ${body.needs}</span>`}
      ${body.reason && html`<span class="tip-reason"><b>Unavailable:</b> ${body.reason}</span>`}</span>`}</span>`;
}

// One click runs the command (or `invoke`). Commands with a physical effect are marked `.physical`.
export function ActionButton({ name, args, label, className = 'btn', disabled, onDone, title, what, hazard, needs, reason, doc, command, invoke }) {
  const [busy, setBusy] = useState(false);
  const key = command || name;
  const click = async () => {
    setBusy(true);
    try { const r = invoke ? await invoke() : await run(name, args); onDone && onDone(r); } catch (e) { notify(e.message, 'bad'); } finally { setBusy(false); }
  };
  const physical = kindOf(key) !== 'safe';
  const docOpen = useDocOpen(doc || key);
  return html`<${Tip} name=${doc || key} label=${label} what=${what || title} hazard=${hazard} needs=${needs} reason=${reason} disabled=${disabled} initialOpen=${docOpen}>
    <button class=${className + (physical ? ' physical' : '')} data-doc=${doc || key} disabled=${disabled || busy} aria-busy=${busy ? 'true' : 'false'} onClick=${click}>${busy ? `${label}…` : label}</button></${Tip}>`;
}

// Hold for `ms` (mouse, touch, Space or Enter) to confirm. Destructive commands also get a server-side token.
export function HoldButton({ name, args, label, className = 'btn danger', disabled, onDone, what, hazard, needs, reason, ms = 700, doc, command, invoke }) {
  const key = command || name;
  // A documentation link (?open=<token>) shows the button mid-hold.
  const docOpen = useDocOpen(doc || key);
  const [fill, setFill] = useState(docOpen ? 0.6 : 0);
  const [busy, setBusy] = useState(false);
  const start = useRef(0); const raf = useRef(0);
  const stop = () => { cancelAnimationFrame(raf.current); start.current = 0; setFill(0); };
  const tick = () => {
    if (!start.current) return;
    const f = Math.min(1, (performance.now() - start.current) / ms);
    setFill(f);
    if (f >= 1) { stop(); fire(); } else raf.current = requestAnimationFrame(tick);
  };
  const begin = (e) => { e.preventDefault(); if (disabled || busy || start.current) return; start.current = performance.now(); raf.current = requestAnimationFrame(tick); };
  const fire = async () => {
    setBusy(true);
    try { const r = invoke ? await invoke() : await run(name, args, { confirmed: kindOf(name) === 'destructive' }); onDone && onDone(r); } catch (e) { notify(e.message, 'bad'); } finally { setBusy(false); }
  };
  useEffect(() => () => cancelAnimationFrame(raf.current), []);
  const isKey = (e) => e.key === ' ' || e.key === 'Enter';
  return html`<${Tip} name=${doc || key} label=${label} what=${what} hazard=${hazard} needs=${needs} reason=${reason} disabled=${disabled} initialOpen=${docOpen}>
    <button class=${className + (fill ? ' holding' : '')} data-doc=${doc || key} style=${`--fill:${fill * 100}%`} disabled=${disabled || busy} aria-busy=${busy ? 'true' : 'false'}
    onMouseDown=${begin} onMouseUp=${stop} onMouseLeave=${stop} onTouchStart=${begin} onTouchEnd=${stop}
    onKeyDown=${(e) => { if (isKey(e)) begin(e); }} onKeyUp=${(e) => { if (isKey(e)) stop(); }}>${busy ? `${label}…` : `Hold: ${label}`}</button></${Tip}>`;
}

// A leased toggle: turning it on starts the device's host override, then pings `touch` until it is turned off.
export function LeaseToggle({ on, onName, touchName, offName, args, label, disabled, what, hazard, needs, reason, interval = 300 }) {
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!on || !touchName) return;
    const id = setInterval(() => run(touchName, args).catch(() => {}), interval);
    return () => clearInterval(id);
  }, [on, JSON.stringify(args)]);
  useEffect(() => () => { if (on && offName) run(offName, args).catch(() => {}); }, []);
  const click = async () => {
    setBusy(true);
    try { if (on) await run(offName, args); else await run(onName, args); } catch (e) { notify(e.message, 'bad'); } finally { setBusy(false); }
  };
  return html`<${Tip} name=${onName} label=${label} what=${what} hazard=${hazard} needs=${needs} reason=${reason} disabled=${disabled}>
    <button class=${'btn physical' + (on ? ' on' : '')} data-doc=${onName} aria-pressed=${on ? 'true' : 'false'} aria-busy=${busy ? 'true' : 'false'} disabled=${disabled || busy} onClick=${click}>${on ? `${label} · ON (leased)` : label}</button></${Tip}>`;
}
