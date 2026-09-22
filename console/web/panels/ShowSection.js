import { html } from '../lib/html.js';
import { useState } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section, timeline } from '../store.js';
import { Pill, KeyValue, Explainer, Banner, ProgressBar, PageHead, Mac, Ladder } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { mmss } from '../lib/format.js';
import { rowByNumber, findDevice } from './common.js';
import { docCube } from '../lib/doc.js';

import { t } from '../lib/i18n.js';

// Translated when shown (the language can change live), not when the module loads.
const SOURCES = { usb: () => t('from this app'), app: () => t('from this app'), button: () => t('by the BOOT button'), boot: () => t('by the BOOT button'), pin: () => t('by the trigger input'), trigger: () => t('by the trigger input') };
const startedBy = (source) => {
  if (!source) return '';
  const known = SOURCES[String(source).toLowerCase()];
  return known ? known() : t('by {source}', { source });
};
// The controller's name from what it is: the Mainshow controller, else the family of the workstation board carrying it.
const controllerName = (via, board) => (via === 'mainshow' ? 'Mainshow controller' : via === 'workstation' ? workstationLabel(board && board.details) : via || t('controller'));
import { registrationPill } from './CubePanel.js';
import { workstationLabel } from '../lib/rail.js';

// Where the last controller command sits on the truth ladder: the controller's radio ACK is 'delivered'; cubes report
// nothing about the show, so nothing here ever reads acknowledged.
function showLevel(show) {
  if (!show.present) return { level: null, note: t('no controller connected') };
  if (show.pending) return { level: 'sent', note: t('waiting for the controller to answer {cmd}', { cmd: show.pending.cmd }) };
  const last = [...timeline.items].reverse().find((e) => e.device === show.device && e.kind === 'log' && /deliver/i.test(e.text || ''));
  if (!last) return { level: null, note: t('nothing sent from this computer yet') };
  if (/not delivered|no delivery|failed/i.test(last.text)) return { level: 'sent', failed: true, note: last.text };
  return { level: 'delivered', note: t('{text} · the cube reports nothing about the show', { text: last.text }) };
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
  const name = controllerName(show.via, board);
  const state = usable ? t('ready') : show.connected ? t('wrong firmware') : t('not answering');
  const controller = show.present ? (board ? t('{name} on {port} · {state}', { name, port: board.port, state }) : t('{name} · {state}', { name, state })) : t('none connected');
  return html`<div class="card"><${Explainer} id="show" />
    ${!show.present && html`<${Banner} kind="warn" title=${t('No Mainshow controller connected')} detail=${t('Plug in the controller board (or make a spare dongle one from its panel).')} />`}
    ${show.problem && html`<div class="warn-text">${show.problem}</div>`}
    <${KeyValue} items=${[[t('Controller'), controller, 'show.controller']]} />
    <div class="row" data-doc="show.cube"><label class="lbl">${t('Cube #')}</label><input class="field num" inputmode="numeric" placeholder=${t('e.g. 44')} value=${number} onInput=${(e) => setNumber(e.target.value)} />
      ${row ? html`<${Mac} mac=${row.mac} /> ${registrationPill(row)} ${row.recent ? html`<${Pill} status="radio.recent" />` : html`<${Pill} status="radio.stale" />`}` : (n > 0 ? html`<span class="warn-text">${t('No cube #{n} in the inventory', { n })}</span>` : html`<span class="note">${t("Enter the number on the cube's label")}</span>`)}</div>
    <div class="row">
      <${ActionButton} name="mainshow.ready" args=${{ cube: n }} label=${t('① Mainshow ready')} className="btn big" disabled=${!usable || !row} hazard=${t('SET_ZONE 4: the cube turns neon and becomes eligible for the show.')} />
      <${ActionButton} name="mainshow.trigger" args=${{ cube: n }} label=${t('② Trigger mainshow')} className="btn big primary" disabled=${!usable || !row} hazard=${t('Fresh showId ×5 to this cube; only a mainshow-ready cube starts.')} />
      <${HoldButton} name="mainshow.trigger_all" args=${{}} label=${t('② Trigger all ready cubes')} className="btn big danger" disabled=${!usable} hazard=${t('Broadcast, no acknowledgment; cannot be undone.')} />
      <${ActionButton} name="mainshow.idle" args=${{ cube: n }} label=${t('Stop → idle')} className="btn big" disabled=${!usable || !row} hazard=${t('SET_ZONE 0 ends the show on this cube.')} /></div>
    <${Ladder} doc="show.ladder" ...${showLevel(show)} />
    <div class="note">${t("Delivered means the cube's radio acknowledged; the cube reports nothing about the show itself. The BOOT button and trigger input also start the show without this computer (their triggers appear in the timeline).")}</div>
    <h3>${t('Show clock')}</h3>
    ${s ? html`<div class="stack" data-doc="show.clock"><div class="row"><span class="readout">${mmss(s.elapsed_s)}</span><span class="note">${s.segment}</span></div><${ProgressBar} value=${100 * s.elapsed_s * 1000 / (s.length_ms || 1)} /><div class="note">${t('Show {id} · {name} · started {by}', { id: s.show_id, name: s.name, by: startedBy(s.source) })}</div></div>` : html`<div class="note" data-doc="show.clock">${t('No show started from this controller yet.')}</div>`}
    ${show.pending && html`<div class="note">${t('Waiting for the controller to answer {cmd}…', { cmd: show.pending.cmd })}</div>`}</div>`;
}

export function ShowSection() {
  return html`<div><${PageHead} title=${t('Show control')} subtitle=${t('Make a cube mainshow-ready and start the main show.')} /><${ShowControl} /></div>`;
}
