import { html } from '../lib/html.js';
import { useState, useEffect, useRef } from 'preact/hooks';
import { useSections, useUI } from '../lib/hooks.js';
import { timeline } from '../store.js';
import { hhmmss } from '../lib/format.js';

export function Timeline({ open, onToggle }) {
  useSections(['timeline', 'ui']);
  const ui = useUI();
  const [kind, setKind] = useState('all');
  const [mine, setMine] = useState(false);
  const box = useRef(null);
  const items = timeline.items.filter((e) => e.kind !== 'line').filter((e) => kind === 'all' ? !(e.kind === 'tag' && e.level === 'info') : (e.kind === kind || e.level === kind))
    .filter((e) => !mine || !ui.route.device || e.device === ui.route.device);
  useEffect(() => { if (box.current && open) box.current.scrollTop = box.current.scrollHeight; }, [items.length, open]);
  const exportLog = () => {
    const text = timeline.items.map((e) => `${hhmmss(e.t)} ${e.kind} ${e.level || ''} ${e.device || ''} ${e.text || JSON.stringify(e.event || e)}`).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = 'nct-console-log.txt'; a.click();
  };
  return html`<div class="dock"><div class="timeline-head"><button class="dockbar" onClick=${onToggle} aria-expanded=${open ? 'true' : 'false'}>${open ? '▾' : '▴'} Timeline <span class="note">${items.length}</span></button>
    ${open && html`<select class="field" value=${kind} onChange=${(e) => setKind(e.target.value)}><option value="all">All</option><option value="log">Log</option><option value="tag">Device events</option><option value="resolved">Resolved</option><option value="warn">Warnings</option><option value="bad">Errors</option></select>
      <label class="check"><input type="checkbox" checked=${mine} onChange=${(e) => setMine(e.target.checked)} /> This device</label>
      <span class="spacer"></span><button class="btn small quiet" onClick=${exportLog}>Export…</button>`}</div>
    ${open && html`<div class="timeline-body" ref=${box}>${!items.length && html`<div class="empty">No timeline events since the console opened.</div>`}${items.slice(-800).map((e) => html`<div key=${e.seq} class=${e.level || ''}><span class="t">${hhmmss(e.t)}</span>${e.source ? html`<span class="src">[${e.source}] </span>` : ''}${e.text || (e.tag ? `${e.tag}: ${e.text}` : '')}</div>`)}</div>`}</div>`;
}
