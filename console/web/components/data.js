import { html } from '../lib/html.js';
import { useState, useEffect, useRef, useMemo } from 'preact/hooks';
import { sortRows } from '../lib/table.js';
import { hhmmss } from '../lib/format.js';
import { outcomeText, outcomeTone } from '../lib/ladder.js';
import { useCopy, useSections } from '../lib/hooks.js';
import { ring } from '../store.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { ProgressBar, Pill, Mac, withMacs } from './basics.js';
import { isMac } from '../lib/mac.js';
import { ActionButton } from './actions.js';

// A cell: the column's renderer, else the value; MACs get the large-tail treatment (stacked in a MAC column).
function cell(c, r) {
  const v = c.render ? c.render(r) : r[c.key];
  if (isMac(v)) return html`<${Mac} mac=${v} stacked=${c.key === 'mac'} />`;
  return withMacs(v) ?? '—';
}

// `doc` names the table for the documentation outlines; `rowDoc(row)` names each row (e.g. relay.zone:<mac>).
export function DataTable({ columns, rows, keyOf, selected, onSelect, toneOf, empty = 'Nothing to show', maxRows = 400, doc, rowDoc }) {
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const sorted = useMemo(() => sortRows(rows, sort.key, sort.dir), [rows, sort.key, sort.dir]);
  const shown = sorted.slice(0, maxRows);
  return html`<div class="table-wrap" data-doc=${doc}><table class="data"><thead><tr>${columns.map((c) => html`<th onClick=${() => setSort({ key: c.key, dir: sort.key === c.key ? -sort.dir : 1 })} scope="col">${c.label}${sort.key === c.key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`)}</tr></thead>
    <tbody>${shown.length ? shown.map((r) => { const k = keyOf(r); return html`<tr key=${k} data-doc=${rowDoc ? rowDoc(r) : undefined} class=${(onSelect ? 'clickable ' : '') + (selected === k ? 'selected' : '') + (toneOf ? ' tone-' + toneOf(r) : '')} onClick=${() => onSelect && onSelect(k, r)}>
      ${columns.map((c) => html`<td class=${c.mono ? 'mono' : ''}>${cell(c, r)}</td>`)}</tr>`; })
      : html`<tr><td colspan=${columns.length} class="note">${empty}</td></tr>`}</tbody>
    ${sorted.length > maxRows && html`<tfoot><tr><td colspan=${columns.length} class="note">${sorted.length - maxRows} more rows (narrow the filter)</td></tr></tfoot>`}</table></div>`;
}

// Append-only log pane fed from a store ring. Pauses when scrolled up.
export function LogPane({ device, kind = 'line', filter, height = 220, items }) {
  useSections(device ? [`lines:${device}`] : ['timeline']);
  const box = useRef(null);
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState(0);
  const list = items || (device ? ring(device).items : []);
  const rows = filter ? list.filter(filter) : list;
  useEffect(() => {
    const el = box.current; if (!el) return;
    if (!paused) { el.scrollTop = el.scrollHeight; setPending(0); } else setPending((n) => n + 1);
  }, [rows.length]);
  const onScroll = () => { const el = box.current; const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 8; setPaused(!atBottom); if (atBottom) setPending(0); };
  return html`<div class="log-wrap"><div class="log" ref=${box} style=${`height:${height}px`} onScroll=${onScroll}>
    ${rows.slice(-1500).map((e) => html`<div key=${e.seq} class=${e.dir === 'tx' ? 'tx' : (e.level || '')}><span class="t">${hhmmss(e.t)}</span>${e.dir === 'tx' ? '> ' : ''}${e.text}</div>`)}
    ${!rows.length && html`<div class="muted">Nothing yet</div>`}</div>
    ${paused && pending > 0 && html`<button class="btn small log-new" onClick=${() => { box.current.scrollTop = box.current.scrollHeight; setPaused(false); setPending(0); }}>${pending} new lines ↓</button>`}</div>`;
}

export function Console({ device, hint = 'help', height = 240, filter }) {
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  const history = useRef([]); const idx = useRef(-1);
  const send = async (e) => {
    e.preventDefault();
    const line = text.trim(); if (!line) return;
    try { await run('device.console', { device, line }); history.current.unshift(line); idx.current = -1; setText(''); } catch (x) { notify(x.message, 'bad'); }
  };
  const key = (e) => {
    if (e.key === 'ArrowUp') { idx.current = Math.min(history.current.length - 1, idx.current + 1); setText(history.current[idx.current] || ''); e.preventDefault(); }
    if (e.key === 'ArrowDown') { idx.current = Math.max(-1, idx.current - 1); setText(history.current[idx.current] || ''); e.preventDefault(); }
  };
  const f = (e) => (!q || e.text.toLowerCase().includes(q.toLowerCase())) && (!filter || filter(e));
  return html`<div class="console"><div class="row"><input class="field filter" placeholder="Filter lines" value=${q} onInput=${(e) => setQ(e.target.value)} /></div>
    <${LogPane} device=${device} height=${height} filter=${f} />
    <form class="console-input" onSubmit=${send}><input value=${text} onInput=${(e) => setText(e.target.value)} onKeyDown=${key} placeholder=${'Send a line (e.g. ' + hint + ')'} spellcheck="false" autocomplete="off" /><button class="btn" data-doc="device.console">Send</button></form></div>`;
}

export function JobCard({ job, compact }) {
  const copy = useCopy();
  if (!job) return null;
  const tone = job.state === 'running' ? 'info' : job.state === 'done' ? outcomeTone(job.outcome) : job.state === 'cancelled' ? 'warn' : 'bad';
  const outcome = job.state !== 'running' && (outcomeText(job.outcome, copy.ladder) || job.error || '');
  return html`<div class=${'job ' + (job.state === 'running' ? 'running' : tone)} data-doc=${`job:${job.kind}`}><div class="head"><strong>${job.title}</strong><${Pill} tone=${tone} label=${job.state} /></div>
    ${job.stage && html`<div class="stage">${job.stage}</div>`}
    ${job.state === 'running' && html`<${ProgressBar} value=${job.progress} indeterminate=${job.progress == null} />`}
    ${outcome && html`<div class=${'outcome ' + outcomeTone(job.outcome) + '-text'}>${outcome}</div>`}
    ${!compact && job.log_tail && job.log_tail.length ? html`<details><summary class="note">Log (${job.log_tail.length})</summary><div class="log short">${job.log_tail.map((l) => html`<div>${l}</div>`)}</div></details>` : null}
    ${job.state === 'running' && job.cancellable && html`<${ActionButton} name="jobs.cancel" args=${{ job: job.id }} label="Cancel" className="btn small" />`}</div>`;
}

export function PortTable({ devices, onSelect, selected }) {
  const columns = [
    { key: 'port', label: 'Port', mono: true }, { key: 'role_label', label: 'Identified as' },
    { key: 'mac', label: 'MAC', mono: true, render: (d) => d.mac || d.usb_mac || '—' },
    { key: 'firmware', label: 'Firmware', mono: true },
    { key: 'state', label: 'State', render: (d) => html`<${Pill} status=${'usb.' + d.state} />` },
    { key: 'presumed', label: 'Inventory says', render: (d) => (d.presumed && d.presumed.label) || '—' },
    { key: 'error', label: 'Note', render: (d) => d.error || '' },
  ];
  return html`<${DataTable} columns=${columns} rows=${devices} keyOf=${(d) => d.id} selected=${selected} onSelect=${onSelect} empty="No USB serial devices" />`;
}
