// Show editor: the main show as cues (what cube firmware v1.5.0+ plays), a rendered preview identical
// to the cube's, web publishing (universal versions) and the wireless update of cubes in range.
// Every cube gets the same show; the preview renders several cube numbers at once because fanned
// cues (v1.6.0+) offset each cube by its number and random cues differ per cube.
import { html } from '../lib/html.js';
import { useState, useEffect, useRef, useMemo } from 'preact/hooks';
import { useSections } from '../lib/hooks.js';
import { section } from '../store.js';
import { run } from '../api.js';
import { notify } from '../lib/notify.js';
import { cssVar, onThemeChange } from '../lib/theme.js';
import { PageHead, Pill, Banner, KeyValue, ProgressBar, Mac } from '../components/basics.js';
import { ActionButton, HoldButton } from '../components/actions.js';
import { LedRing } from '../components/canvas.js';
import { ago, crc as crcText, signalBars } from '../lib/format.js';
import { TYPES, FANNABLE, Player, levelHex, hexLevels, retype, problem, fmtTime, parseTime, cueAt, fanOffset, parseCubes, cubeRng } from '../lib/showengine.js';

const clone = (x) => JSON.parse(JSON.stringify(x));
const SNAP_MS = 10;
const TYPE_HELP = {
  off: 'LEDs off.',
  solid: 'One steady colour.',
  fade: 'From the first colour to the second over the fade time, then holds the second.',
  blink: 'First colour for the on time of every period, the second colour for the rest.',
  pulse: 'Up from the first colour to the second, then back down; holds the first after.',
  cycle: 'Crossfades through the colours in a loop, one step time per colour.',
  random: 'A random walk of brightness (level × the colour / 100); every cube moves differently.',
};
const PARAM_LABEL = {
  duration_ms: ['Fade time', 'ms'], period_ms: ['Period', 'ms'], on_ms: ['On time', 'ms'], attack_ms: ['Up time', 'ms'],
  release_ms: ['Down time', 'ms'], step_ms: ['Step time', 'ms'], level_min: ['Level min', '0-100'], level_max: ['Level max', '0-100'],
  dur_min_ms: ['Shortest step', 'ms'], dur_max_ms: ['Longest step', 'ms'], start_level: ['Start level', '0-100'],
};
const STATE_TONE = { current: 'ok', updating: 'info', pending: 'info', behind: 'warn', ahead: 'warn', unpublished: 'muted' };

// ---------------------------------------------------------------- timeline strip
const RULER = 18, LANE = 34;
// The colour band: one row per previewed cube.
const bandFor = (n) => (n <= 1 ? 40 : n * (n <= 4 ? 14 : n <= 12 ? 9 : 5));

function drawStrip(ctx, w, doc, zoom, t, sel, cubes) {
  const BAND = bandFor(cubes.length);
  const h = RULER + BAND + LANE;
  ctx.clearRect(0, 0, w, h);
  ctx.font = '10px -apple-system, "Segoe UI", sans-serif';
  // Ruler: a tick every 5 s, labelled every 30 s (every 10 s when zoomed in).
  const every = zoom >= 12 ? 10 : 30;
  ctx.fillStyle = cssVar('--text-faint'); ctx.strokeStyle = cssVar('--border');
  for (let s = 0; s * 1000 <= doc.length_ms; s += 5) {
    const x = Math.round(s * zoom) + 0.5;
    ctx.beginPath(); ctx.moveTo(x, s % every ? RULER - 4 : RULER - 9); ctx.lineTo(x, RULER); ctx.stroke();
    if (!(s % every)) ctx.fillText(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`, x + 2, 10);
  }
  // Band: the show rendered pixel by pixel, exactly as each previewed cube plays it (fanning by its
  // number; random cues with a per-cube preview rng), one row per cube.
  const rowH = BAND / cubes.length;
  cubes.forEach((cube, row) => {
    const player = new Player(doc, cube), rng = cubeRng(cube);
    const y = RULER + Math.round(row * rowH), hh = Math.round((row + 1) * rowH) - Math.round(row * rowH) - (cubes.length > 1 ? 1 : 0);
    for (let x = 0; x < w; x++) {
      const rgb = player.render(Math.floor((x * 1000) / zoom), rng);
      ctx.fillStyle = rgb ? levelHex(rgb) : cssVar('--surface-sunken');
      ctx.fillRect(x, y, 1, hh);
    }
  });
  // Cue lane: boundaries and labels; the selected cue outlined.
  ctx.fillStyle = cssVar('--surface-sunken'); ctx.fillRect(0, RULER + BAND, w, LANE);
  doc.cues.forEach((cue, i) => {
    const x0 = Math.round((cue.start_ms / 1000) * zoom);
    const end = i + 1 < doc.cues.length ? doc.cues[i + 1].start_ms : doc.length_ms;
    const x1 = Math.round((end / 1000) * zoom);
    ctx.strokeStyle = i === sel ? cssVar('--accent') : cssVar('--border-strong');
    ctx.lineWidth = i === sel ? 2 : 1;
    ctx.strokeRect(x0 + 0.5, RULER + BAND + 0.5, Math.max(1, x1 - x0 - 1), LANE - 1);
    ctx.fillStyle = i === sel ? cssVar('--text') : cssVar('--text-muted');
    const label = `${i + 1} ${cue.label || cue.type}`;
    if (x1 - x0 > 18) { ctx.save(); ctx.beginPath(); ctx.rect(x0 + 2, RULER + BAND, x1 - x0 - 4, LANE); ctx.clip(); ctx.fillText(label, x0 + 4, RULER + BAND + 14); ctx.fillText(cue.type, x0 + 4, RULER + BAND + 27); ctx.restore(); }
  });
  ctx.lineWidth = 1;
  // Playhead.
  const px = Math.round((t / 1000) * zoom) + 0.5;
  ctx.strokeStyle = cssVar('--accent-strong'); ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke();
}

function Strip({ doc, zoom, t, sel, cubes, onSeek, onSelect, onMove }) {
  const BAND = bandFor(cubes.length);
  const ref = useRef(null);
  const drag = useRef(null);
  const [theme, setTheme] = useState(0);
  useEffect(() => onThemeChange(() => setTheme((n) => n + 1)), []);
  const width = Math.max(200, Math.ceil((doc.length_ms / 1000) * zoom) + 1);
  useEffect(() => { const c = ref.current; if (c) drawStrip(c.getContext('2d'), c.width, doc, zoom, t, sel, cubes); }, [doc, zoom, t, sel, theme, cubes.join(',')]);
  const at = (e) => { const r = ref.current.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const msAt = (x) => Math.max(0, Math.min(doc.length_ms - 1, Math.round((x * 1000) / zoom)));
  const down = (e) => {
    const { x, y } = at(e);
    if (y < RULER + BAND) { drag.current = { kind: 'seek' }; onSeek(msAt(x)); return; }
    // Near a boundary (not the first cue's): drag that cue's start. Otherwise select the cue under the pointer.
    const edge = doc.cues.findIndex((c, i) => i > 0 && Math.abs((c.start_ms / 1000) * zoom - x) <= 4);
    if (edge > 0) { drag.current = { kind: 'move', index: edge }; onSelect(edge); return; }
    onSelect(cueAt(doc, msAt(x)));
  };
  const move = (e) => {
    const d = drag.current; if (!d) return;
    const { x } = at(e);
    if (d.kind === 'seek') onSeek(msAt(x));
    else onMove(d.index, Math.round(msAt(x) / SNAP_MS) * SNAP_MS);
  };
  const up = () => { drag.current = null; };
  return html`<div class="table-wrap"><canvas ref=${ref} width=${width} height=${RULER + BAND + LANE} role="img"
    aria-label="show timeline: colour band as the cubes play it, cues below; drag a cue edge to move it"
    onMouseDown=${down} onMouseMove=${move} onMouseUp=${up} onMouseLeave=${up}></canvas></div>`;
}

// ---------------------------------------------------------------- cue inspector
function Colour({ rgb, onChange, label }) {
  const set = (k, v) => { const next = [...rgb]; next[k] = Math.max(0, Math.min(100, parseInt(v, 10) || 0)); onChange(next); };
  return html`<div class="row show-rgb"><label class="lbl">${label}</label>
    <input type="color" value=${levelHex(rgb)} onInput=${(e) => onChange(hexLevels(e.target.value))} aria-label=${label + ' colour'} />
    ${['R', 'G', 'B'].map((c, k) => html`<input class="field num" type="number" min="0" max="100" value=${rgb[k]} aria-label=${label + ' ' + c}
      onChange=${(e) => set(k, e.target.value)} title=${c + ' level 0-100 (the cube caps LEDs at 100)'} />`)}</div>`;
}

function TimeField({ value, onCommit, label, disabled }) {
  const [text, setText] = useState(fmtTime(value));
  useEffect(() => setText(fmtTime(value)), [value]);
  const commit = () => { const ms = parseTime(text); if (ms == null) { setText(fmtTime(value)); notify('Time is m:ss.mmm', 'bad'); } else onCommit(ms); };
  return html`<span class="row"><label class="lbl">${label}</label><input class="field num mono" value=${text} disabled=${disabled}
    onInput=${(e) => setText(e.target.value)} onBlur=${commit} onKeyDown=${(e) => { if (e.key === 'Enter') commit(); }} /></span>`;
}

function Inspector({ doc, index, cubes, onCue, onStart }) {
  const cue = doc.cues[index];
  if (!cue) return html`<div class="note">Select a cue in the lane below the colour band.</div>`;
  const end = index + 1 < doc.cues.length ? doc.cues[index + 1].start_ms : doc.length_ms;
  const spec = TYPES[cue.type];
  const set = (patch) => onCue({ ...clone(cue), ...patch });
  const colourCount = spec.colours === null ? cue.colours.length : spec.colours;
  const names = cue.type === 'fade' || cue.type === 'pulse' ? ['From', 'To'] : cue.type === 'blink' ? ['On', 'Off'] : null;
  return html`<div class="stack">
    <div class="row"><label class="lbl">Cue ${index + 1}</label><input class="field" value=${cue.label} placeholder="label" onChange=${(e) => set({ label: e.target.value })} />
      <select class="field" value=${cue.type} onChange=${(e) => onCue(retype(cue, e.target.value))} aria-label="cue type">
        ${Object.keys(TYPES).map((k) => html`<option value=${k}>${k}</option>`)}</select></div>
    <div class="note">${TYPE_HELP[cue.type]}</div>
    <div class="row"><${TimeField} label="Start" value=${cue.start_ms} disabled=${index === 0} onCommit=${(ms) => onStart(index, ms)} />
      <span class="note">ends ${fmtTime(end)} · lasts ${((end - cue.start_ms) / 1000).toFixed(3)} s</span></div>
    ${Array.from({ length: colourCount }, (_, i) => html`<${Colour} label=${names ? names[i] : `Colour ${i + 1}`} rgb=${cue.colours[i]}
      onChange=${(rgb) => { const colours = clone(cue.colours); colours[i] = rgb; set({ colours }); }} />`)}
    ${spec.colours === null && html`<div class="row">
      <button class="btn small" disabled=${cue.colours.length >= 3} onClick=${() => set({ colours: [...clone(cue.colours), [...cue.colours[cue.colours.length - 1]]] })}>+ colour</button>
      <button class="btn small" disabled=${cue.colours.length <= 1} onClick=${() => set({ colours: clone(cue.colours).slice(0, -1) })}>− colour</button></div>`}
    ${spec.params.map((k) => html`<div class="row"><label class="lbl">${PARAM_LABEL[k][0]}</label>
      <input class="field num" type="number" value=${cue.params[k]} onChange=${(e) => set({ params: { ...cue.params, [k]: parseInt(e.target.value, 10) || 0 } })} />
      <span class="note">${PARAM_LABEL[k][1]}</span></div>`)}
    ${FANNABLE.includes(cue.type) && html`<${Fan} cue=${cue} cubes=${cubes} onFan=${(fan) => { const next = clone(cue); if (fan) next.fan = fan; else delete next.fan; onCue(next); }} />`}</div>`;
}

// Fanning: the same cue offset per cube by its registered number (cube firmware v1.6.0+).
function Fan({ cue, cubes, onFan }) {
  const fan = cue.fan || null;
  const mode = fan ? fan.mode : 'none';
  const num = (v) => Math.max(1, parseInt(v, 10) || 1);
  const choose = (m) => onFan(m === 'none' ? null : m === 'sequential' ? { mode: m, step_ms: 100, groups: 8 } : { mode: m, spread_ms: 500 });
  const shown = cubes.slice(0, 8).map((n) => `#${n} ${fanOffset(cue, n)} ms`).join(' · ');
  return html`<div class="stack"><h3>Fanning <span class="note">per-cube offset by cube number</span></h3>
    <div class="row"><label class="lbl">Fan</label>
      <select class="field" value=${mode} onChange=${(e) => choose(e.target.value)} aria-label="fan mode">
        <option value="none">none: every cube together</option>
        <option value="sequential">sequential: step × position in a group</option>
        <option value="scatter">scatter: fixed random spread</option></select></div>
    ${mode === 'sequential' && html`<div class="row"><label class="lbl">Step</label>
        <input class="field num" type="number" min="1" max="65535" value=${fan.step_ms} onChange=${(e) => onFan({ ...fan, step_ms: num(e.target.value) })} /><span class="note">ms per cube</span>
        <label class="lbl">Group of</label>
        <input class="field num" type="number" min="1" max="255" value=${fan.groups} onChange=${(e) => onFan({ ...fan, groups: Math.min(255, num(e.target.value)) })} /><span class="note">cubes, then it repeats</span></div>`}
    ${mode === 'scatter' && html`<div class="row"><label class="lbl">Spread</label>
        <input class="field num" type="number" min="1" max="65535" value=${fan.spread_ms} onChange=${(e) => onFan({ ...fan, spread_ms: num(e.target.value) })} /><span class="note">ms: each cube gets a fixed offset in 0-spread</span></div>`}
    ${fan && html`<div class="note">${cue.type === 'fade' || cue.type === 'pulse' ? 'Each cube starts this cue later by its offset, holding the first colour until then.' : 'Each cube runs this cue shifted by its offset.'} Offsets: ${shown}${cubes.length > 8 ? ' …' : ''}. A cube with no number has none. Needs cube firmware v1.6.0; an older cube refuses the whole show and keeps its current one.</div>`}</div>`;
}

// ---------------------------------------------------------------- cubes and distribution
function CubeShows({ se }) {
  const [picked, setPicked] = useState([]);
  const p = se.published || {};
  const pub = se.publishing;
  const relay = se.relay || {};
  const cubes = se.cubes || [];
  const counts = cubes.reduce((m, c) => ({ ...m, [c.state]: (m[c.state] || 0) + 1 }), {});
  return html`<div class="card"><h2>Cubes <span class="note">show held by each cube (v0 = compiled-in default)</span></h2>
    ${!relay.present && html`<${Banner} kind="warn" title="No show relay connected" detail="Updating cube shows needs a General Radio running general-radio-1.1.0 or later. Publishing to the web works without one." />`}
    ${relay.error && html`<div class="warn-text">${relay.error}</div>`}
    ${se.show_running && html`<${Banner} kind="info" title="A show is running" detail="Cube updates wait until the controller's show ends; a cube never switches shows mid-show." />`}
    <${KeyValue} items=${[['Published', p.version ? `v${p.version} · ${crcText(p.crc)} · ${p.length} bytes · ${p.published_by || ''}` : 'nothing yet'],
      ['Cubes', cubes.length ? Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(' · ') : 'none heard yet (Query)'],
      ['Auto update', se.walkaround ? 'on: cubes in range on an older show are updated' : 'off']]} />
    ${pub && html`<div class="stack"><div class="row"><span>${se.message}</span></div>
      <${ProgressBar} value=${pub.expected.length ? 100 * (pub.expected.length - pub.pending.length) / pub.expected.length : 0} indeterminate=${!pub.expected.length} />
      <div class="note">${pub.expected.length - pub.pending.length}/${pub.expected.length} confirmed · cycle ${pub.cycles + 1} · ${pub.elapsed_s} s${pub.held ? ' · waiting for the show to end' : ''}</div></div>`}
    ${!pub && se.message && html`<div class="note">${se.message}</div>`}
    <div class="row">
      <${ActionButton} name="show.query" args=${{}} label="Query cubes" disabled=${!relay.present} hazard="Broadcast SHOW_QUERY: every v1.5.0+ cube in range answers within 2 s." />
      <${ActionButton} name="show.update_all" args=${{}} label=${p.version ? `Update all to v${p.version}` : 'Update all'} className="btn primary" disabled=${!relay.present || !p.version || !!pub}
        hazard="Broadcasts the published show until every cube heard recently confirms it. Cubes playing a show commit it when their show ends." />
      ${se.walkaround ? html`<${ActionButton} name="show.auto_update" args=${{ enabled: false }} label="Auto update off" />`
        : html`<${ActionButton} name="show.auto_update" args=${{ enabled: true }} label="Auto update on" disabled=${!relay.present || !p.version} hazard="Walk around: any cube in range on an older show is updated automatically." />`}
      <${ActionButton} name="show.update_selected" args=${{ macs: picked }} label=${`Update selected (${picked.length})`} disabled=${!relay.present || !p.version || !!pub || !picked.length}
        hazard="Sends the published show until the ticked cubes confirm it (other cubes in range on an older show take it too: every cube gets the same show)." onDone=${() => setPicked([])} />
      ${pub && html`<${ActionButton} name="show.stop" args=${{}} label="Stop sending" className="btn danger" />`}
      <${ActionButton} name="show.push_config" args=${{}} label="Send length to controller" disabled=${!p.version} hazard="show_config: the Mainshow controller (mainshow-1.3.0+) bounds its timecode by the published show's length." /></div>
    <div class="table-wrap"><table class="data"><thead><tr><th><input type="checkbox" aria-label="select every cube behind" checked=${picked.length > 0 && picked.length === cubes.filter((c) => c.state === 'behind').length}
        onChange=${(e) => setPicked(e.target.checked ? cubes.filter((c) => c.state === 'behind').map((c) => c.mac) : [])} /></th><th>#</th><th>MAC</th><th>Firmware</th><th>Show</th><th>State</th><th>Staging</th><th>Signal</th><th>Seen</th><th></th></tr></thead>
      <tbody>${cubes.length ? cubes.map((c) => html`<tr key=${c.mac}>
        <td><input type="checkbox" aria-label=${'select ' + c.mac} checked=${picked.includes(c.mac)}
          onChange=${(e) => setPicked(e.target.checked ? [...picked, c.mac] : picked.filter((m) => m !== c.mac))} /></td>
        <td>${c.number != null ? '#' + c.number : '—'}</td><td><${Mac} mac=${c.mac} /></td><td class="mono">${c.fw}</td>
        <td>v${c.version} <span class="note">${c.source}</span></td>
        <td><${Pill} tone=${STATE_TONE[c.state] || 'muted'} label=${c.state} tip=${c.error_text || undefined} /></td>
        <td>${c.staging_total ? `v${c.staging_version} ${c.staging_chunks}/${c.staging_total}${c.pending_commit ? ' · waits for show end' : ''}` : '—'}</td>
        <td>${signalBars(c.rssi, '—')}</td><td>${c.age_s != null ? ago(c.age_s) : '—'}</td>
        <td>${c.state === 'behind' && html`<${ActionButton} name="show.update" args=${{ mac: c.mac }} label="Update" className="btn small" disabled=${!relay.present || !!pub} />`}</td></tr>`)
      : html`<tr><td class="note" colspan="10">No cube has answered a show query yet.</td></tr>`}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- page
export function ShowEditorSection() {
  useSections(['showedit', 'jobs']);
  const se = section('showedit');
  const [doc, setDoc] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [undo, setUndo] = useState([]);
  const [redo, setRedo] = useState([]);
  const [sel, setSel] = useState(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(4);
  const [saveError, setSaveError] = useState(null);
  const [importText, setImportText] = useState(null);
  // Cube numbers to preview side by side (every cube gets the same show; fanning and random differ).
  const [cubeText, setCubeText] = useState(() => { try { return localStorage.getItem('nct.show.preview') || '1-8'; } catch (e) { return '1-8'; } });
  const cubes = parseCubes(cubeText) || [1];
  const setCubes = (text) => { setCubeText(text); try { localStorage.setItem('nct.show.preview', text); } catch (e) { /* private mode */ } };
  const saveTimer = useRef(0);
  const player = useRef(null);
  const last = useRef(0);

  // Take the server's working copy whenever there are no local edits (first load, revert, import, another window).
  useEffect(() => { if (se && se.draft && !dirty) setDoc(clone(se.draft)); }, [se && JSON.stringify(se.draft)]);

  const commit = (next, record = true) => {
    if (record) { setUndo([...undo.slice(-99), doc]); setRedo([]); }
    setDoc(next); setDirty(true);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => save(next), 1200);
  };
  const save = async (next) => {
    const why = problem(next);
    if (why) { setSaveError(why); return false; }
    try { await run('show.save', { doc: next }); setSaveError(null); setDirty(false); return true; } catch (e) { setSaveError(e.message); return false; }
  };
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  // Playback: advance the playhead in real time; the ring renders with a persistent player (like a cube).
  useEffect(() => {
    if (!playing) return undefined;
    let raf = 0; last.current = performance.now();
    const step = (now) => {
      setT((v) => { const n = v + (now - last.current); last.current = now; if (doc && n >= doc.length_ms) { setPlaying(false); return doc.length_ms - 1; } return n; });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, doc]);
  // One persistent player per previewed cube, like each cube's own (restarted on a backwards seek).
  const colours = useMemo(() => {
    if (!doc) return [];
    const ms = Math.floor(t);
    const key = cubes.join(',');
    if (!player.current || player.current.doc !== doc || player.current.key !== key || ms < player.current.at) {
      player.current = { doc, key, at: 0, players: cubes.map((n) => ({ cube: n, player: new Player(doc, n), rng: cubeRng(n) })) };
    }
    player.current.at = ms;
    return player.current.players.map((p) => ({ cube: p.cube, rgb: p.player.render(ms, p.rng) }));
  }, [doc, Math.floor(t / 20), cubes.join(',')]);
  const rgb = colours.length ? colours[0].rgb : null;

  if (!se || !doc) return html`<div><${PageHead} title="Show editor" subtitle="Loading…" /></div>`;
  const cue = doc.cues[sel];
  const why = problem(doc);
  const p = se.published || {};
  const setCue = (next) => { const d = clone(doc); d.cues[sel] = next; commit(d); };
  const moveStart = (index, ms) => {
    const d = clone(doc);
    const lo = d.cues[index - 1].start_ms + 1, hi = (index + 1 < d.cues.length ? d.cues[index + 1].start_ms : d.length_ms) - 1;
    d.cues[index].start_ms = Math.max(lo, Math.min(hi, ms));
    commit(d);
  };
  const add = () => {
    const at = Math.round(Math.floor(t) / SNAP_MS) * SNAP_MS;
    const index = cueAt(doc, at);
    if (doc.cues[index].start_ms === at) { notify('A cue already starts at the playhead; move the playhead', 'warn'); return; }
    const d = clone(doc);
    const fresh = { ...retype(doc.cues[index], doc.cues[index].type), start_ms: at, label: '' };
    d.cues.splice(index + 1, 0, fresh);
    commit(d); setSel(index + 1);
  };
  const remove = () => {
    if (sel === 0) { notify('The first cue cannot be removed (the show starts with it)', 'warn'); return; }
    const d = clone(doc); d.cues.splice(sel, 1); commit(d); setSel(Math.max(0, sel - 1));
  };
  const back = () => { if (!undo.length) return; setRedo([...redo, doc]); const prev = undo[undo.length - 1]; setUndo(undo.slice(0, -1)); commit(prev, false); };
  const fwd = () => { if (!redo.length) return; setUndo([...undo, doc]); const next = redo[redo.length - 1]; setRedo(redo.slice(0, -1)); commit(next, false); };
  const publish = async () => {
    clearTimeout(saveTimer.current);
    if (!(await save(doc))) { notify('Fix the show before publishing', 'bad'); return; }
    try { await run('show.publish', {}); notify('Publishing the show…', 'info'); } catch (e) { notify(e.message, 'bad'); }
  };
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(doc, null, 2) + '\n'], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'mainshow.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const meta = html`<span class="row">
    <${Pill} tone=${dirty ? 'warn' : 'ok'} label=${dirty ? 'unsaved edits' : 'saved on this computer'} />
    <${Pill} tone=${se.draft_published ? 'ok' : 'info'} label=${se.draft_published ? `same as published v${p.version}` : p.version ? `differs from published v${p.version}` : 'not published yet'} />
    <span class="note">${doc.cues.length} cues · ${fmtTime(doc.length_ms)} · started from ${se.origin} · image ${se.summary.bytes} B ${crcText(se.summary.crc)}${se.summary.crc === se.default_crc ? ' (the compiled-in default)' : ''}</span></span>`;
  const actions = html`<button class="btn primary" data-doc="show.publish" disabled=${!!why} onClick=${publish} title="Publish this show on the web as the next version (cubes are not touched)">Publish</button>
    <${ActionButton} name="show.pull" args=${{}} label="Pull" title="Fetch the published show from the web" />`;
  return html`<div>
    <${PageHead} title="Show editor" subtitle="The main show the cubes play (cube firmware v1.5.0+). Edit, publish a version, then update the cubes over the radio." meta=${meta} actions=${actions} />
    ${(why || saveError) && html`<${Banner} kind="bad" title="The cubes would refuse this show" detail=${why || saveError} />`}
    <div class="card">
      <div class="row">
        <button class="btn" onClick=${() => setPlaying(!playing)} aria-pressed=${playing ? 'true' : 'false'}>${playing ? '❚❚ Pause' : '▶ Play'}</button>
        <button class="btn small" onClick=${() => { setPlaying(false); setT(0); }}>⏮</button>
        <span class="readout mono">${fmtTime(Math.floor(t))}</span>
        <span class="note">${cue ? `cue ${cueAt(doc, Math.floor(t)) + 1}` : ''}</span>
        <span class="spacer"></span>
        <label class="lbl">Zoom</label>
        <input type="range" min="1" max="60" value=${zoom} onInput=${(e) => setZoom(parseInt(e.target.value, 10))} aria-label="zoom (pixels per second)" />
        <button class="btn small" onClick=${add} title="New cue at the playhead, copying the cue it splits">+ Cue at playhead</button>
        <button class="btn small" onClick=${remove} disabled=${sel === 0}>Delete cue</button>
        <button class="btn small" onClick=${back} disabled=${!undo.length}>Undo</button>
        <button class="btn small" onClick=${fwd} disabled=${!redo.length}>Redo</button></div>
      <div class="row"><label class="lbl">Preview cubes</label>
        <input class="field" value=${cubeText} onInput=${(e) => setCubes(e.target.value)} placeholder="e.g. 1-8, 12" aria-label="cube numbers to preview" />
        ${parseCubes(cubeText) ? html`<span class="note">${cubes.length} cube${cubes.length === 1 ? '' : 's'}: one band row each, top to bottom #${cubes.join(', #')}</span>`
          : html`<span class="warn-text">Numbers and ranges, e.g. 1-8, 12</span>`}
        <button class="btn small" onClick=${() => setCubes('1')}>One</button>
        <button class="btn small" onClick=${() => setCubes('1-8')}>1-8</button>
        <button class="btn small" onClick=${() => setCubes('1-24')}>1-24</button></div>
      <${Strip} doc=${doc} zoom=${zoom} t=${Math.floor(t)} sel=${sel} cubes=${cubes} onSeek=${(ms) => { setT(ms); }} onSelect=${setSel} onMove=${moveStart} />
      <div class="note">Top: the colour band is the show as the previewed cubes play it (one row per cube; fanning offsets each by its number, and random cues differ per cube). 100, the cube's cap, is shown at full brightness. Click the band to move the playhead. Bottom: the cues. Click a cue to select it; drag a cue's left edge to move its start (10 ms steps).</div></div>
    <div class="grid2">
      <div class="card"><h2>Cue</h2><${Inspector} doc=${doc} index=${sel} cubes=${cubes} onCue=${setCue} onStart=${moveStart} />
        <h3>Show</h3><div class="row"><${TimeField} label="Length" value=${doc.length_ms} onCommit=${(ms) => commit({ ...clone(doc), length_ms: ms })} />
          <span class="note">At the end the cube turns off and leaves mainshow-ready, as before.</span></div></div>
      <div class="card"><h2>Preview <span class="note">at the playhead</span></h2>
        <div class="note">${fmtTime(Math.floor(t))} · ${cue ? (doc.cues[cueAt(doc, Math.floor(t))].label || doc.cues[cueAt(doc, Math.floor(t))].type) : ''}</div>
        <div class="ring-grid">${colours.map(({ cube, rgb: c }) => html`<div class="ring-tile" key=${cube} title=${c ? `#${cube}: levels R${c[0]} G${c[1]} B${c[2]}` : `#${cube}: show ended`}>
          <${LedRing} pixels=${c ? Array(8).fill(levelHex(c).slice(1)) : Array(8).fill('000000')} label=${'#' + cube} sub=${c ? `${c[0]} ${c[1]} ${c[2]}` : 'off'} size=${colours.length > 8 ? 90 : 120} /></div>`)}</div>
        <h3>Working copy</h3>
        <div class="row">
          <${HoldButton} name="show.revert" invoke=${() => { setDirty(false); return run('show.revert', { source: 'published' }); }} label="Revert to published" disabled=${!p.version} hazard="Discards this computer's edits." />
          <${HoldButton} name="show.revert" invoke=${() => { setDirty(false); return run('show.revert', { source: 'default' }); }} label="Start from the default" hazard="The compiled-in v1.4.1 show. Discards this computer's edits." />
          <button class="btn small" onClick=${exportJson}>Export JSON</button>
          <button class="btn small" onClick=${() => setImportText(importText == null ? '' : null)}>Import JSON…</button></div>
        ${importText != null && html`<div class="stack"><textarea class="field" rows="6" value=${importText} onInput=${(e) => setImportText(e.target.value)} placeholder="Paste a show JSON (shows/mainshow.json format)"></textarea>
          <div class="row"><${ActionButton} name="show.import" args=${{ text: importText }} label="Replace the working copy" onDone=${() => { setDirty(false); setImportText(null); }} /></div></div>`}</div></div>
    <${CubeShows} se=${se} /></div>`;
}
