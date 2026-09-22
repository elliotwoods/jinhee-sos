import { html } from '../lib/html.js';
import { useState, useEffect, useRef } from 'preact/hooks';
import { useSections, useUI, useCopy } from '../lib/hooks.js';
import { section } from '../store.js';
import { order, group } from '../lib/suggestions.js';
import { run, api } from '../api.js';
import { notify } from '../lib/notify.js';
import { hhmmss } from '../lib/format.js';
import { JobCard } from './data.js';
import { ActionButton, HoldButton } from './actions.js';
import { goDevice } from '../router.js';
import { withMacs } from './basics.js';
import { useDocOpen } from '../lib/doc.js';

function useJob(jobId) {
  useSections(['jobs']);
  return (section('jobs') || []).find((j) => j.id === jobId);
}

function ActionRow({ suggestion, action }) {
  const [job, setJob] = useState(null);
  const [stale, setStale] = useState(null);
  const actionId = `${suggestion.id}#${action.id}`;
  const copy = useCopy();
  const live = useJob(job);
  const { what, hazard, needs } = copy.actions[action.command] || {};
  // advisor.act answers {ok:false, explanation} when the suggestion no longer applies, else the command's result.
  const invoke = async () => {
    const args = { action_id: actionId };
    let payload = args;
    if (action.kind === 'destructive') { const t = await api.confirm('advisor.act', args); if (!t || !t.token) throw new Error((t && t.error) || 'Could not confirm the action'); payload = { ...args, token: t.token }; }
    const r = await api.call('advisor.act', payload);
    if (!r.ok) throw new Error(r.error);
    return r.result;
  };
  const done = (result) => {
    if (result && result.ok === false) { setStale(result.explanation); return; }
    const inner = result && result.result;
    if (inner && inner.job) setJob(inner.job);
    else notify(`${action.label}: done`, 'ok');
  };
  const common = { label: action.label, what, hazard, needs, invoke, onDone: done, doc: `attention.action:${action.command}`, command: action.command };
  const button = action.kind === 'destructive' ? html`<${HoldButton} ...${common} className="btn danger small" />`
    : action.kind === 'hardware' ? html`<${ActionButton} ...${common} className="btn small" />`
    : html`<${SafeButton} ...${common} />`;
  return html`<span class="stack tight">${button}
    ${stale && html`<span class="note warn-text">Not run: ${stale}</span>`}
    ${live && html`<${JobCard} job=${live} compact />`}</span>`;
}

function SafeButton({ label, invoke, onDone, doc }) {
  const [busy, setBusy] = useState(false);
  const click = async () => { setBusy(true); try { onDone(await invoke()); } catch (e) { notify(e.message, 'bad'); } finally { setBusy(false); } };
  return html`<button class="btn small primary" data-doc=${doc} disabled=${busy} aria-busy=${busy ? 'true' : 'false'} onClick=${click}>${busy ? `${label}…` : label}</button>`;
}

export function SuggestionCard({ s, flash }) {
  const [details, setDetails] = useState(false);
  const [menu, setMenu] = useState(useDocOpen(`attention.menu:${s.rule}`));
  const dismiss = async (scope) => { setMenu(false); try { await run('advisor.dismiss', { id: s.group ? s.group[0].id : s.id, scope }); } catch (e) { notify(e.message, 'bad'); } };
  return html`<article class=${'sugg ' + s.severity + (flash ? ' flash' : '')} aria-label=${s.title} data-doc=${`attention.card:${s.rule}`}>
    <div class="head"><div class="head-text"><span class=${'sev ' + s.severity + '-text'}>${s.severity.toUpperCase()}</span><span class="title">${s.title}</span>
        ${s.device && html`<div class="scope"><a href="#" onClick=${(e) => { e.preventDefault(); goDevice(s.device); }}>${withMacs(s.device)}</a></div>`}</div>
      <span class="menu"><button class="btn small quiet" data-doc=${`attention.menu:${s.rule}`} onClick=${() => setMenu(!menu)} aria-haspopup="true" aria-expanded=${menu ? 'true' : 'false'} title="dismiss">Dismiss ▾</button>
        ${menu && html`<div class="pop"><button data-doc="attention.dismiss" onClick=${() => dismiss('once')}>Dismiss this occurrence</button><button onClick=${() => dismiss('scope')}>Dismiss for this device</button><button onClick=${() => dismiss('rule')}>Don't show this rule again</button></div>`}</span></div>
    ${s.group && html`<p class="note">${withMacs((s.members || []).join(' · '))}</p>`}
    ${s.know && html`<p><span class="lbl">What we know: </span>${withMacs(s.know)}</p>`}
    ${s.why && html`<p><span class="lbl">Why it matters: </span>${s.why}</p>`}
    ${s.check && html`<p><span class="lbl">What to check: </span>${s.check}</p>`}
    <div class="actions">${(s.actions || []).map((a) => html`<${ActionRow} key=${a.id} suggestion=${s.group ? s.group[0] : s} action=${a} />`)}
      <button class="btn small quiet" onClick=${() => setDetails(!details)}>${details ? 'Hide details' : 'Details'}</button></div>
    ${details && html`<div class="evidence">rule ${s.rule} · id ${s.id}\n${(s.evidence || []).map((e) => `${hhmmss(e.at)} ${e.source}: ${e.text}`).join('\n')}</div>`}</article>`;
}

export function Attention() {
  useSections(['advisor', 'ui']);
  const ui = useUI();
  const advisor = section('advisor') || { suggestions: [], counts: {} };
  const [expanded, setExpanded] = useState(false);
  const seen = useRef(new Set());
  const list = group(order(advisor.suggestions, ui.route.device));
  const visible = expanded ? list : list.slice(0, 6);
  useEffect(() => { list.forEach((s) => seen.current.add(s.id)); }, [list.length]);
  const c = advisor.counts || {};
  return html`<section aria-label="attention" data-doc="attention"><h4><span>Attention · ${list.length}</span><span class="badges">${c.bad ? html`<span class="badge bad">${c.bad}</span>` : ''}${c.warn ? html`<span class="badge warn">${c.warn}</span>` : ''}</span></h4>
    ${!list.length && html`<div class="empty">Nothing needs attention.</div>`}
    ${visible.map((s) => html`<${SuggestionCard} key=${s.id} s=${s} flash=${!seen.current.has(s.id)} />`)}
    ${list.length > 6 && html`<button class="btn small quiet" onClick=${() => setExpanded(!expanded)}>${expanded ? 'Show fewer' : `${list.length - 6} more`}</button>`}</section>`;
}

export function Jobs() {
  useSections(['jobs']);
  const jobs = (section('jobs') || []).filter((j) => !['sync.status', 'tools.check'].includes(j.kind) || j.state === 'failed');
  const running = jobs.filter((j) => j.state === 'running');
  const recent = jobs.filter((j) => j.state !== 'running').slice(0, 4);
  return html`<section aria-label="jobs" data-doc="jobs"><h4><span>Jobs</span><span>${running.length ? `${running.length} running` : ''}</span></h4>
    ${running.map((j) => html`<${JobCard} key=${j.id} job=${j} compact />`)}
    ${recent.map((j) => html`<${JobCard} key=${j.id} job=${j} compact />`)}
    ${!jobs.length && html`<div class="empty">No jobs yet.</div>`}</section>`;
}

// Attention count for the narrow-window drawer toggle.
export function attentionCount() {
  const advisor = section('advisor') || { suggestions: [] };
  return group(order(advisor.suggestions)).length;
}
