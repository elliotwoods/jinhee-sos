import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section, timeline } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, ProgressBar, PageHead, Mac, Ladder } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { mmss } from '../lib/format.js';
import { rowByNumber, findDevice } from './common.js';
import { docCube } from '../lib/doc.js';

const SOURCES = { usb: 'from this app', app: 'from this app', button: 'by the BOOT button', boot: 'by the BOOT button', pin: 'by the trigger input', trigger: 'by the trigger input' };
const startedBy = (source) => (source ? SOURCES[String(source).toLowerCase()] || `by ${source}` : '');
const CONTROLLERS = { mainshow: 'Mainshow controller', generalradio: 'General Radio' };
import { registrationPill } from './CubePanel.js';

// Where the last controller command sits on the truth ladder: the controller's radio ACK is 'delivered'; cubes report
// nothing about the show, so nothing here ever reads acknowledged.
function showLevel(show) {
  if (!show.present) return { level: null, note: 'no controller connected' };
  if (show.pending) return { level: 'sent', note: `waiting for the controller to answer ${show.pending.cmd}` };
  const last = [...timeline.items].reverse().find((e) => e.device === show.device && e.kind === 'log' && /deliver/i.test(e.text || ''));
  if (!last) return { level: null, note: 'nothing sent from this computer yet' };
  if (/not delivered|no delivery|failed/i.test(last.text)) return { level: 'sent', failed: true, note: last.text };
  return { level: 'delivered', note: `${last.text} · the cube reports nothing about the show` };
}

export function ShowControl() {
  useSections(['show', 'inventory', 'timeline']);
  const show = section('show') || {};
  const [number, setNumber] = useState(docCube() ? String(docCube()) : '');
  const n = parseInt(number, 10);
  const row = n > 0 ? rowByNumber(n) : null;
  const usable = show.present && show.usable;
  const s = show.show;
  const board = show.device ? findDevice(show.device) : null;
  const controller = show.present ? `${CONTROLLERS[show.via] || show.via || 'controller'}${board ? ` on ${board.port}` : ''}${usable ? ' · ready' : show.connected ? ' · wrong firmware' : ' · not answering'}` : 'none connected';
  return html`<div class="card"><${Explainer} id="show" />
    ${!show.present && html`<${Banner} kind="warn" title="No Mainshow controller connected" detail="Plug in the controller board (or make a spare dongle one from its panel)." />`}
    ${show.problem && html`<div class="warn-text">${show.problem}</div>`}
    <${KeyValue} items=${[['Controller', controller, 'show.controller']]} />
    <div class="row" data-doc="show.cube"><label class="lbl">Cube #</label><input class="field num" inputmode="numeric" placeholder="e.g. 44" value=${number} onInput=${(e) => setNumber(e.target.value)} />
      ${row ? html`<${Mac} mac=${row.mac} /> ${registrationPill(row)} ${row.recent ? html`<${Pill} status="radio.recent" />` : html`<${Pill} status="radio.stale" />`}` : (n > 0 ? html`<span class="warn-text">No cube #${n} in the inventory</span>` : html`<span class="note">Enter the number on the cube's label</span>`)}</div>
    <div class="row">
      <${ActionButton} name="mainshow.ready" args=${{ cube: n }} label="① Mainshow ready" className="btn big" disabled=${!usable || !row} hazard="SET_ZONE 4: the cube turns neon and becomes eligible for the show." />
      <${ActionButton} name="mainshow.trigger" args=${{ cube: n }} label="② Trigger mainshow" className="btn big primary" disabled=${!usable || !row} hazard="Fresh showId ×5 to this cube; only a mainshow-ready cube starts." />
      <${HoldButton} name="mainshow.trigger_all" args=${{}} label="② Trigger all ready cubes" className="btn big danger" disabled=${!usable} hazard="Broadcast, no acknowledgment; cannot be undone." />
      <${ActionButton} name="mainshow.idle" args=${{ cube: n }} label="Stop → idle" className="btn big" disabled=${!usable || !row} hazard="SET_ZONE 0 ends the show on this cube." /></div>
    <${Ladder} doc="show.ladder" ...${showLevel(show)} />
    <div class="note">Delivered means the cube's radio acknowledged; the cube reports nothing about the show itself. The BOOT button and trigger input also start the show without this computer (their triggers appear in the timeline).</div>
    <h3>Show clock</h3>
    ${s ? html`<div class="stack" data-doc="show.clock"><div class="row"><span class="readout">${mmss(s.elapsed_s)}</span><span class="note">${s.segment}</span></div><${ProgressBar} value=${100 * s.elapsed_s * 1000 / (s.length_ms || 1)} /><div class="note">Show ${s.show_id} · ${s.name} · started ${startedBy(s.source)}</div></div>` : html`<div class="note" data-doc="show.clock">No show started from this controller yet.</div>`}
    ${show.pending && html`<div class="note">Waiting for the controller to answer ${show.pending.cmd}…</div>`}</div>`;
}

export function ShowSection() {
  return html`<div><${PageHead} title="Show control" subtitle="Make a cube mainshow-ready and start the main show." /><${ShowControl} /></div>`;
}
