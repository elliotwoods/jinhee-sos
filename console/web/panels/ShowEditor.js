// Show editor: the main show as cues (what cube firmware v1.5.0+ plays), a rendered preview identical
// to the cube's, web publishing (universal versions) and the wireless update of cubes in range.
// Every cube gets the same show; the preview renders several cube numbers at once because fanned
// cues (v1.6.0+) offset each cube by its number and random cues differ per cube.
// The timeline is edited by direct manipulation, has a transport (rate, loop, cue jumps, keys), can mirror
// the playhead on real bench cubes (show.live, cube firmware v1.7.0+) and plays a reference video in step.
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
import {
  layout, hitTest, msAt, xOf, snap, cueEnd, rulerStep, tickLabel, setStart, moveBlock, insertCue, removeCue, cueSwatch,
  playRange, advance, keySeek, prevCueStart, nextCueStart, followScroll, fwAtLeast, RATES, OVERVIEW, MAX_CANVAS_PX,
  zoomLimits, clampZoom, viewWindow, overviewHit, edgeZoom, zoomAround, cubeRanges, bandCubes,
} from '../lib/showtimeline.js';
import { videoTarget, videoPhase, clockStep, maySeek, stillNeedsSeek, isVideoFile, offsetKey, DRIFT_MS } from '../lib/showvideo.js';

const clone = (x) => JSON.parse(JSON.stringify(x));
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
// Ruler (click or drag to scrub), the colour band (one row per previewed cube, also scrubbable) and the
// cue lane: one block per cue with its colours on a swatch strip. Click a block to select it, drag it to
// move it (its length is kept), drag a start edge to move just that boundary, double-click to add a cue.
const SANS = '-apple-system, "Segoe UI", sans-serif';

// Small line icons (16 px, currentColor so they follow the theme). Each icon-only button has a title and
// an aria-label carrying its keyboard shortcut.
const ICONS = {
  stop: { fill: 'M4 4h8v8H4z' },
  prev: { fill: 'M3 3h2v10H3zM13 3v10L6 8z' },
  next: { fill: 'M11 3h2v10h-2zM3 3v10l7-5z' },
  play: { fill: 'M4.5 2.5v11l9-5.5z' },
  pause: { fill: 'M4 3h3v10H4zM9 3h3v10H9z' },
  add: { stroke: 'M8 2.5v11M2.5 8h11' },
  trash: { stroke: 'M2.5 4.5h11M6.5 4.5V2.8h3v1.7M4.2 4.5l.8 9h6l.8-9M6.8 7v4.3M9.2 7v4.3' },
  undo: { stroke: 'M5.5 3.5 2.5 6.5l3 3M2.5 6.5h7a3.3 3.3 0 0 1 0 6.6H7' },
  redo: { stroke: 'M10.5 3.5l3 3-3 3M13.5 6.5h-7a3.3 3.3 0 0 0 0 6.6H9' },
  fit: { stroke: 'M1.8 3v10M14.2 3v10M4.3 8h7.4M6.3 6 4.3 8l2 2M9.7 6l2 2-2 2' },
};
function Icon({ name }) {
  const i = ICONS[name];
  return html`<svg class="show-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
    ${i.fill && html`<path d=${i.fill} fill="currentColor" />`}
    ${i.stroke && html`<path d=${i.stroke} fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />`}</svg>`;
}
function IconButton({ icon, tip, onClick, disabled, className = 'btn small icon' }) {
  return html`<button class=${className} onClick=${onClick} disabled=${disabled} title=${tip} aria-label=${tip}><${Icon} name=${icon} /></button>`;
}

// The static picture (ruler, band, blocks), kept in an offscreen canvas: the band renders every pixel
// column for every previewed cube, far too slow to repeat on every animation frame.
function drawBase(ctx, w, lay, doc, zoom, cubes) {
  const { ruler, band, laneTop, lane, height } = lay;
  ctx.clearRect(0, 0, w, height);
  // Ruler.
  ctx.fillStyle = cssVar('--surface-raised'); ctx.fillRect(0, 0, w, ruler);
  const { major, minor } = rulerStep(zoom);
  ctx.font = `10px ${SANS}`; ctx.lineWidth = 1;
  for (let ms = 0; ms <= doc.length_ms; ms += minor) {
    const x = Math.round(xOf(ms, zoom)) + 0.5, isMajor = ms % major === 0;
    ctx.strokeStyle = cssVar(isMajor ? '--text-faint' : '--border-strong');
    ctx.beginPath(); ctx.moveTo(x, isMajor ? ruler - 9 : ruler - 4); ctx.lineTo(x, ruler); ctx.stroke();
    if (isMajor) { ctx.fillStyle = cssVar('--text-muted'); ctx.fillText(tickLabel(ms, major), x + 3, 11); }
  }
  // Cue starts marked on the ruler.
  ctx.fillStyle = cssVar('--text-faint');
  doc.cues.forEach((c) => { const x = Math.round(xOf(c.start_ms, zoom)); ctx.beginPath(); ctx.moveTo(x - 3, ruler - 4); ctx.lineTo(x + 3, ruler - 4); ctx.lineTo(x, ruler); ctx.fill(); });
  // Band: the show rendered pixel by pixel, exactly as each previewed cube plays it.
  ctx.fillStyle = cssVar('--surface-sunken'); ctx.fillRect(0, ruler, w, band);
  const rowH = band / cubes.length;
  cubes.forEach((cube, row) => {
    const player = new Player(doc, cube), rng = cubeRng(cube);
    const y = ruler + Math.round(row * rowH), hh = Math.round((row + 1) * rowH) - Math.round(row * rowH) - (cubes.length > 1 ? 1 : 0);
    for (let x = 0; x < w; x++) {
      const rgb = player.render(Math.floor((x * 1000) / zoom), rng);
      if (!rgb) break;
      ctx.fillStyle = levelHex(rgb);
      ctx.fillRect(x, y, 1, hh);
    }
  });
  // Section boundaries carried across the band.
  ctx.save(); ctx.globalAlpha = 0.35; ctx.fillStyle = cssVar('--text');
  doc.cues.forEach((c, i) => { if (i) ctx.fillRect(Math.round(xOf(c.start_ms, zoom)), ruler, 1, band); });
  ctx.restore();
  // Cue lane: alternating blocks, a swatch strip of the cue's colours, number + label, type + start time.
  ctx.fillStyle = cssVar('--surface-sunken'); ctx.fillRect(0, laneTop, w, lane);
  doc.cues.forEach((cue, i) => {
    const x0 = Math.round(xOf(cue.start_ms, zoom)), x1 = Math.round(xOf(cueEnd(doc, i), zoom)), bw = Math.max(1, x1 - x0);
    ctx.fillStyle = cssVar(i % 2 ? '--band-b' : '--band-a'); ctx.fillRect(x0, laneTop + 1, bw, lane - 2);
    const sw = cueSwatch(cue), seg = bw / sw.length;
    sw.forEach((rgb, k) => { ctx.fillStyle = levelHex(rgb); ctx.fillRect(x0 + Math.round(k * seg), laneTop + 1, Math.ceil(seg), 6); });
    ctx.fillStyle = cssVar('--border-strong'); ctx.fillRect(x0, laneTop, 1, lane);
    if (i > 0 && bw > 12) { ctx.fillStyle = cssVar('--text-faint'); ctx.fillRect(x0 + 3, laneTop + 17, 1, 14); }
    if (bw > 18) {
      ctx.save(); ctx.beginPath(); ctx.rect(x0 + 2, laneTop, bw - 4, lane); ctx.clip();
      ctx.fillStyle = cssVar('--text'); ctx.font = `600 11px ${SANS}`; ctx.fillText(`${i + 1} ${cue.label || cue.type}`, x0 + 7, laneTop + 21);
      ctx.fillStyle = cssVar('--text-muted'); ctx.font = `10px ${SANS}`;
      ctx.fillText(`${cue.type}${cue.fan ? ' · fan' : ''} · ${fmtTime(cue.start_ms)}`, x0 + 7, laneTop + 35);
      ctx.restore();
    }
  });
}

// Per frame: loop range, the current cue, the selected cue, the edge under the pointer, the playhead.
function drawOverlay(ctx, lay, doc, zoom, t, sel, loop, range, hoverEdge) {
  const { ruler, laneTop, lane, height } = lay;
  const X = (ms) => Math.round(xOf(ms, zoom));
  if (loop !== 'off') {
    ctx.save(); ctx.globalAlpha = 0.28; ctx.fillStyle = cssVar('--accent'); ctx.fillRect(X(range[0]), 0, X(range[1]) - X(range[0]), ruler); ctx.restore();
  }
  if (t < doc.length_ms) {
    const cur = cueAt(doc, t), a = X(doc.cues[cur].start_ms), b = X(cueEnd(doc, cur));
    ctx.fillStyle = cssVar('--accent-live'); ctx.fillRect(a + 1, laneTop + lane - 5, Math.max(1, b - a - 1), 4);
  }
  if (doc.cues[sel]) {
    const a = X(doc.cues[sel].start_ms), b = X(cueEnd(doc, sel));
    ctx.save(); ctx.globalAlpha = 0.16; ctx.fillStyle = cssVar('--accent'); ctx.fillRect(a, laneTop, b - a, lane); ctx.restore();
    ctx.strokeStyle = cssVar('--accent'); ctx.lineWidth = 2; ctx.strokeRect(a + 1, laneTop + 1, Math.max(1, b - a - 2), lane - 2);
    ctx.save(); ctx.globalAlpha = 0.9; ctx.fillStyle = cssVar('--accent'); ctx.fillRect(a, ruler, 1, laneTop - ruler); ctx.fillRect(b - 1, ruler, 1, laneTop - ruler); ctx.restore();
  }
  if (hoverEdge > 0 && doc.cues[hoverEdge]) { ctx.fillStyle = cssVar('--accent-strong'); ctx.fillRect(X(doc.cues[hoverEdge].start_ms) - 1, laneTop, 3, lane); }
  const px = Math.round(xOf(t, zoom)) + 0.5;
  ctx.strokeStyle = cssVar('--accent-strong'); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, height); ctx.stroke();
  ctx.fillStyle = cssVar('--accent-strong');
  ctx.beginPath(); ctx.moveTo(px - 6, 0); ctx.lineTo(px + 6, 0); ctx.lineTo(px, 8); ctx.fill();
  ctx.lineWidth = 1;
}

const cursorFor = (hit) => (hit.area === 'ruler' || hit.area === 'band' ? 'col-resize' : hit.area === 'edge' ? 'ew-resize' : hit.index > 0 ? 'grab' : 'pointer');

function Strip({ doc, zoom, t, sel, cubes, loop, range, onSeek, onScrub, onSelect, onPreview, onCommit, onAddAt, onZoom }) {
  const lay = layout(cubes.length);
  const ref = useRef(null), wrap = useRef(null), drag = useRef(null);
  const [theme, setTheme] = useState(0);
  const [hoverEdge, setHoverEdge] = useState(-1);
  const [view, setView] = useState({ left: 0, width: 0 });
  const want = useRef(null);       // a scroll position waiting for the canvas at a new zoom
  const panning = useRef(false);   // the overview is being dragged: the playhead must not pull the view
  useEffect(() => onThemeChange(() => setTheme((n) => n + 1)), []);
  // The zoom, always between "the whole show fits" and the cap (lib/showtimeline.js zoomLimits).
  const z = clampZoom(zoom, doc.length_ms, view.width);
  const width = Math.max(200, Math.ceil(xOf(doc.length_ms, z)) + 1);
  const dpr = Math.max(1, Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, Math.floor(MAX_CANVAS_PX / width) || 1));
  const base = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = width * dpr; c.height = lay.height * dpr;
    const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawBase(ctx, width, lay, doc, z, cubes);
    return c;
  }, [doc, z, cubes.join(','), theme, width, dpr]);
  useEffect(() => {
    const c = ref.current; if (!c) return;
    const ctx = c.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(base, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawOverlay(ctx, lay, doc, z, t, sel, loop, range, hoverEdge);
  });
  // A zoom from the overview or the wheel lands its scroll position once the canvas has its new width;
  // otherwise keep the playhead in view (playing, keys, jumps), except while the pointer is dragging.
  useEffect(() => {
    const w = wrap.current; if (!w) return;
    if (want.current != null) { w.scrollLeft = want.current; want.current = null; return; }
    if (drag.current || panning.current) return;
    const next = followScroll(xOf(t, z), w.scrollLeft, w.clientWidth);
    if (next != null) w.scrollLeft = next;
  }, [Math.round(xOf(t, z)), z]);
  useEffect(() => {
    const w = wrap.current; if (!w) return undefined;
    const measure = () => setView({ left: w.scrollLeft, width: w.clientWidth });
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(w);
    w.addEventListener('scroll', measure, { passive: true });
    return () => { if (ro) ro.disconnect(); w.removeEventListener('scroll', measure); };
  }, []);
  // Zoom to `nz` with the view's left edge at `left` px (of the canvas at the new zoom).
  const zoomTo = (nz, left) => {
    const w = wrap.current; if (!w) return;
    if (Math.abs(nz - live.current.z) < 1e-9) { w.scrollLeft = left; return; }
    live.current.z = nz; want.current = Math.max(0, Math.round(left));
    onZoom(nz);
  };
  const live = useRef({});
  live.current = { ...live.current, z, len: doc.length_ms, zoomTo };
  // Ctrl/Cmd + wheel (a trackpad pinch) zooms around the pointer; a plain wheel scrolls as usual.
  useEffect(() => {
    const w = wrap.current; if (!w) return undefined;
    const wheel = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const s = live.current, r = w.getBoundingClientRect();
      const out = zoomAround({ zoom: s.z, factor: Math.exp(-e.deltaY * 0.01), anchorPx: e.clientX - r.left,
        scrollLeft: want.current != null ? want.current : w.scrollLeft, lengthMs: s.len, viewPx: w.clientWidth });
      s.zoomTo(out.zoom, out.scrollLeft);
    };
    w.addEventListener('wheel', wheel, { passive: false });
    return () => w.removeEventListener('wheel', wheel);
  }, []);
  const at = (e) => { const r = ref.current.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const down = (e) => {
    if (e.button !== 0) return;
    const { x, y } = at(e);
    const hit = hitTest(doc, z, lay, x, y);
    try { ref.current.setPointerCapture(e.pointerId); } catch (err) { /* synthetic event */ }
    if (hit.area === 'ruler' || hit.area === 'band') { drag.current = { kind: 'seek' }; onScrub(true); onSeek(msAt(doc, z, x)); return; }
    onSelect(hit.index);
    if (e.detail >= 2) { drag.current = null; return; }  // the second click of a double-click adds a cue
    drag.current = hit.area === 'edge' ? { kind: 'edge', index: hit.index, doc }
      : hit.index > 0 ? { kind: 'block', index: hit.index, doc, x0: x, moved: false } : { kind: 'none' };
  };
  const move = (e) => {
    const { x, y } = at(e);
    const d = drag.current;
    if (!d) {
      const hit = hitTest(doc, z, lay, x, y);
      ref.current.style.cursor = cursorFor(hit);
      const edge = hit.area === 'edge' ? hit.index : -1;
      if (edge !== hoverEdge) setHoverEdge(edge);
      return;
    }
    if (d.kind === 'seek') onSeek(msAt(doc, z, x));
    else if (d.kind === 'edge') onPreview(setStart(d.doc, d.index, snap(msAt(d.doc, z, x))));
    else if (d.kind === 'block') {
      if (!d.moved && Math.abs(x - d.x0) < 3) return;
      d.moved = true; ref.current.style.cursor = 'grabbing';
      onPreview(moveBlock(d.doc, d.index, snap(((x - d.x0) * 1000) / z)));
    }
  };
  const up = () => {
    const d = drag.current; drag.current = null;
    if (!d) return;
    if (d.kind === 'seek') onScrub(false);
    else if (d.kind === 'edge' || d.kind === 'block') onCommit();
  };
  const cancel = () => { const d = drag.current; drag.current = null; if (d && d.kind === 'seek') onScrub(false); else if (d) onPreview(null); };
  const leave = () => { if (!drag.current && hoverEdge !== -1) setHoverEdge(-1); };
  const dbl = (e) => { const { x, y } = at(e); if (y >= lay.laneTop) onAddAt(snap(msAt(doc, z, x))); };
  return html`<div class="stack show-timeline">
    ${view.width > 0 && html`<${Overview} doc=${doc} zoom=${z} t=${t} sel=${sel} view=${view} theme=${theme}
      onScroll=${(left) => { if (wrap.current) wrap.current.scrollLeft = left; }} onZoomTo=${zoomTo}
      onFit=${() => zoomTo(zoomLimits(doc.length_ms, view.width).min, 0)} onPanning=${(on) => { panning.current = on; }} />`}
    <div class="show-strip" ref=${wrap}><canvas ref=${ref} width=${width * dpr} height=${lay.height * dpr} style=${`width:${width}px;height:${lay.height}px`}
      role="img" aria-label=${`show timeline: ruler and colour band (rows: cubes ${cubeRanges(cubes)}) scrub the playhead; cue blocks below: click to select, drag to move, drag an edge to move a start, double-click to add a cue; Ctrl or Cmd + wheel zooms`}
      onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${cancel} onPointerLeave=${leave} onDblClick=${dbl}></canvas></div></div>`;
}

// Whole-show overview, always shown: cue blocks in their colour, the visible window and the playhead.
// Drag the window's left or right edge to zoom (the other edge stays), drag inside it or click elsewhere
// to move the view, double-click to fit the whole show.
function Overview({ doc, zoom, t, sel, view, theme, onScroll, onZoomTo, onFit, onPanning }) {
  const ref = useRef(null), drag = useRef(null);
  const w = Math.max(100, Math.floor(view.width)), h = OVERVIEW, len = doc.length_ms, k = w / len;
  const [a, b] = viewWindow(view.left, view.width, zoom);
  const vx = a * k, vw = Math.max(8, Math.min(len, b) * k - vx);
  useEffect(() => {
    const c = ref.current; if (!c) return;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = cssVar('--surface-sunken'); ctx.fillRect(0, 0, w, h);
    doc.cues.forEach((cue, i) => {
      const x0 = Math.round(cue.start_ms * k), x1 = Math.round(cueEnd(doc, i) * k);
      ctx.fillStyle = levelHex(cueSwatch(cue)[0]); ctx.fillRect(x0, 4, Math.max(1, x1 - x0), h - 8);
      ctx.fillStyle = cssVar(i === sel ? '--accent' : '--border-strong'); ctx.fillRect(x0, 0, 1, h);
    });
    // The window: outside it dimmed, its frame, and a grip on each edge.
    ctx.save(); ctx.globalAlpha = 0.45; ctx.fillStyle = cssVar('--surface-sunken');
    ctx.fillRect(0, 0, vx, h); ctx.fillRect(vx + vw, 0, w - vx - vw, h); ctx.restore();
    ctx.strokeStyle = cssVar('--accent'); ctx.lineWidth = 2; ctx.strokeRect(vx + 1, 1, vw - 2, h - 2);
    ctx.fillStyle = cssVar('--accent');
    ctx.fillRect(vx, 0, 4, h); ctx.fillRect(vx + vw - 4, 0, 4, h);
    ctx.fillStyle = cssVar('--on-accent');
    [vx + 2, vx + vw - 2].forEach((gx) => ctx.fillRect(Math.round(gx) - 0.5, h / 2 - 4, 1, 8));
    ctx.fillStyle = cssVar('--accent-strong'); ctx.fillRect(Math.round(t * k), 0, 2, h);
    ctx.lineWidth = 1;
  });
  const px = (e) => { const r = ref.current.getBoundingClientRect(); return ((e.clientX - r.left) * w) / Math.max(1, r.width); };
  const pan = (x, grab) => onScroll((((x - grab) / w) * len * zoom) / 1000);
  const down = (e) => {
    if (e.button !== 0) return;
    const x = px(e), hit = overviewHit(x, vx, vw);
    try { ref.current.setPointerCapture(e.pointerId); } catch (err) { /* synthetic event */ }
    onPanning(true);
    if (hit === 'left' || hit === 'right') { drag.current = { kind: hit, window: [a, Math.min(len, b)] }; return; }
    drag.current = { kind: 'pan', grab: hit === 'inside' ? x - vx : vw / 2 };
    if (hit === 'outside') pan(x, drag.current.grab);
  };
  const move = (e) => {
    const x = px(e), d = drag.current;
    if (!d) {
      const hit = overviewHit(x, vx, vw);
      ref.current.style.cursor = hit === 'left' || hit === 'right' ? 'ew-resize' : hit === 'inside' ? 'grab' : 'pointer';
      return;
    }
    if (d.kind === 'pan') { ref.current.style.cursor = 'grabbing'; pan(x, d.grab); return; }
    const r = edgeZoom({ edge: d.kind, x, overviewPx: w, window: d.window, lengthMs: len, viewPx: view.width });
    onZoomTo(r.zoom, (r.startMs * r.zoom) / 1000);
  };
  const up = () => { drag.current = null; onPanning(false); if (ref.current) ref.current.style.cursor = ''; };
  return html`<canvas class="show-overview" ref=${ref} width=${w} height=${h} data-theme-rev=${theme} role="img"
    title="Whole show: drag the window's edges to zoom, drag it (or click) to scroll, double-click to fit"
    aria-label="whole-show overview: drag the window's left or right edge to zoom, drag inside it or click to move the view, double-click to fit the whole show"
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onDblClick=${onFit}></canvas>`;
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

function Inspector({ doc, index, cubes, onCue, onStart, onRetype }) {
  const cue = doc.cues[index];
  if (!cue) return html`<div class="note">Select a cue in the lane below the colour band.</div>`;
  const end = index + 1 < doc.cues.length ? doc.cues[index + 1].start_ms : doc.length_ms;
  const spec = TYPES[cue.type];
  const set = (patch) => onCue({ ...clone(cue), ...patch });
  const colourCount = spec.colours === null ? cue.colours.length : spec.colours;
  const names = cue.type === 'fade' || cue.type === 'pulse' ? ['From', 'To'] : cue.type === 'blink' ? ['On', 'Off'] : null;
  return html`<div class="stack">
    <div class="row"><label class="lbl">Cue ${index + 1}</label><input class="field" value=${cue.label} placeholder="label" onChange=${(e) => set({ label: e.target.value })} />
      <select class="field" value=${cue.type} onChange=${(e) => onRetype(e.target.value)} aria-label="cue type">
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
      ['Auto update', se.walkaround ? 'on: cubes in range on an older show are updated (saved; Settings › Automatic updates)' : 'off (saved; Settings › Automatic updates)']]} />
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

// ---------------------------------------------------------------- reference video
// A video dropped on the player plays in step with the timeline (lib/showvideo.js explains the clocks).
// It is played from this computer through an object URL, never uploaded; the choice lasts until the
// console restarts (module state survives switching pages), the offset is remembered per file name.
const media = { url: null, name: '', el: null, offset: 0, muted: false, large: false, lastSeekAt: null, pending: null };
// The playhead also survives switching pages.
const session = { t: 0 };

function storedOffset(name) {
  try { return parseInt(localStorage.getItem(offsetKey(name)) || '0', 10) || 0; } catch (e) { return 0; }
}

// Paused or scrubbing: a still frame at the playhead.
function stillVideo(t) {
  const v = media.el;
  if (!v || !media.url) return;
  if (!v.paused) v.pause();
  const target = videoTarget(t, media.offset), phase = videoPhase(target, v.duration);
  if (phase === 'after') return;
  const want = phase === 'before' ? 0 : target;
  if (v.seeking) { media.pending = want; return; }
  if (stillNeedsSeek(v.currentTime, want)) v.currentTime = want;
}

// Playing: follow the show clock; `force` when the clock step found the video out of step.
function playVideo(t, rate, force, now) {
  const v = media.el;
  if (!v || !media.url) return;
  if (v.playbackRate !== rate) v.playbackRate = rate;
  const target = videoTarget(t, media.offset), phase = videoPhase(target, v.duration);
  if (phase !== 'in') {
    if (!v.paused) v.pause();
    if (phase === 'before' && v.currentTime > 0.05 && !v.seeking) v.currentTime = 0;
    return;
  }
  if (v.paused) {
    if (stillNeedsSeek(v.currentTime, target, DRIFT_MS) && maySeek(now, media.lastSeekAt, v.seeking)) { v.currentTime = target; media.lastSeekAt = now; }
    v.play().catch(() => { /* not ready or refused; retried next frame */ });
  } else if (force && maySeek(now, media.lastSeekAt, v.seeking)) {
    v.currentTime = target; media.lastSeekAt = now;
  }
}

// The video's position as show time while it plays smoothly inside its range, else null (clockStep's videoMs).
function videoClock() {
  const v = media.el;
  if (!v || !media.url || v.paused || v.seeking || v.ended || v.readyState < 3) return null;
  return v.currentTime * 1000 - media.offset;
}

function VideoPanel({ t, playing }) {
  const [, bump] = useState(0);
  const refresh = () => bump((n) => n + 1);
  const [over, setOver] = useState(false);
  const [duration, setDuration] = useState(media.el ? media.el.duration : NaN);
  const input = useRef(null);
  const take = (file) => {
    if (!isVideoFile(file)) { notify('Drop a video file (mp4, mov, webm…)', 'warn'); return; }
    if (media.url) URL.revokeObjectURL(media.url);
    media.url = URL.createObjectURL(file); media.name = file.name; media.offset = storedOffset(file.name);
    media.lastSeekAt = null; media.pending = null;
    setDuration(NaN); refresh();
  };
  const clear = () => { if (media.url) URL.revokeObjectURL(media.url); media.url = null; media.name = ''; setDuration(NaN); refresh(); };
  const setOffset = (v) => {
    media.offset = Math.round(Number(v) || 0);
    try { localStorage.setItem(offsetKey(media.name), String(media.offset)); } catch (e) { /* private mode */ }
    if (!playing) stillVideo(t);
    refresh();
  };
  const drop = (e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) take(f); };
  const target = videoTarget(t, media.offset), phase = media.url ? videoPhase(target, duration) : null;
  const cls = 'show-video' + (media.url ? ' loaded' : '') + (over ? ' over' : '');
  const zero = media.offset >= 0 ? fmtTime(media.offset) : '−' + fmtTime(-media.offset);
  return html`<div class=${'stack show-video-slot' + (media.large ? ' large' : '')}>
    <div class=${cls} onDragOver=${(e) => { e.preventDefault(); if (!over) setOver(true); }} onDragEnter=${(e) => e.preventDefault()}
      onDragLeave=${(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(false); }} onDrop=${drop}>
      ${media.url && html`<video ref=${(el) => { media.el = el; }} src=${media.url} muted=${media.muted} playsInline preload="auto"
        onLoadedMetadata=${(e) => { setDuration(e.currentTarget.duration); if (!playing) stillVideo(t); }}
        onSeeked=${() => { if (media.pending != null && media.el) { const p = media.pending; media.pending = null; if (stillNeedsSeek(media.el.currentTime, p)) media.el.currentTime = p; } }}></video>`}
      ${!media.url && html`<div class="veil" title="Play, pause, scrubbing, rate and loop drive the video. It plays from this computer and is never uploaded.">
        <span class="drop-glyph" aria-hidden="true">▶</span>
        <span class="drop-title">${over ? 'Drop to load the video' : 'Reference video'}</span>
        <span>Drag a video file here: it plays in step with the timeline, from this computer (never uploaded).</span>
        <button class="btn small" onClick=${() => input.current && input.current.click()}>Choose file…</button></div>`}
      ${media.url && over && html`<div class="veil"><span class="drop-title">Drop to replace ${media.name}</span></div>`}
      ${phase === 'before' && !over && html`<div class="veil"><span class="drop-title">Video starts at show time ${fmtTime(-media.offset)}</span><span>The offset puts the video's 0:00 after the show's.</span></div>`}
      ${phase === 'after' && !over && html`<div class="veil"><span class="drop-title">Video ended</span><span>${fmtTime(duration * 1000)} long; the show continues.</span></div>`}
    </div>
    <input type="file" accept="video/*" ref=${input} hidden onChange=${(e) => { const f = e.target.files && e.target.files[0]; if (f) take(f); e.target.value = ''; }} />
    ${media.url ? html`<div class="row show-video-tools">
        <label class="lbl" title=${`The show's 0:00 is at ${zero} in the video (remembered per file name)`}>Offset</label>
        <input class="field num" type="number" step="10" value=${media.offset} aria-label="video offset in milliseconds (the show's 0:00 in the video)"
          title=${`ms: the show's 0:00 is at ${zero} in the video`} onChange=${(e) => setOffset(e.target.value)} />
        <button class="btn small" aria-pressed=${media.muted ? 'true' : 'false'} onClick=${() => { media.muted = !media.muted; if (media.el) media.el.muted = media.muted; refresh(); }}>${media.muted ? 'Unmute' : 'Mute'}</button>
        <button class="btn small" onClick=${() => { media.large = !media.large; refresh(); }}>${media.large ? 'Smaller' : 'Larger'}</button>
        <button class="btn small" onClick=${() => input.current && input.current.click()} title="Choose another video file">Replace…</button>
        <button class="btn small quiet" onClick=${clear} title="Remove the video" aria-label="Remove the video">✕</button></div>
      <div class="note mono show-video-name" title=${media.name}>${media.name}${Number.isFinite(duration) ? ` · ${fmtTime(duration * 1000)}` : ''}</div>`
      : null}
  </div>`;
}

// ---------------------------------------------------------------- mirroring on real cubes
const LIVE_EVERY_MS = 60, LIVE_LEASE_MS = 600;
const liveEntries = (colours) => colours.filter(({ cube }) => cube >= 1 && cube <= 65535).map(({ cube, rgb }) => [cube, rgb || [0, 0, 0]]);

// The previewed cube numbers (quick sets One / 1-8 / 1-24) and mirroring them on the real cubes, in one box.
// The colour band always shows 16 rows (the selection first); the rings and the mirroring use the selection.
const QUICK_CUBES = [['1', 'One'], ['1-8', '1-8'], ['1-24', '1-24']];
function CubeBox({ se, cubeText, cubes, valid, band, onCubes, on, held, onStart, onStop }) {
  const relay = se.relay || {};
  const live = se.live || {};
  const oldRadio = fwAtLeast(relay.firmware, 'general-radio', [1, 2, 0]) === false;
  const shown = cubes.filter((n) => n >= 1);
  const names = cubeRanges(shown);
  const bandNote = band.length > cubes.length ? ` · band rows ${cubeRanges(band)}` : '';
  return html`<div class=${'show-cubes' + (on ? ' on' : '')} role="group" aria-label="previewed cubes and mirroring on the real cubes">
    <div class="row">
      <label class="lbl">Preview cubes</label>
      <input class="field" value=${cubeText} onInput=${(e) => onCubes(e.target.value)} placeholder="e.g. 1-8, 12" aria-label="cube numbers to preview" />
      <span class="show-seg" role="group" aria-label="quick cube sets">${QUICK_CUBES.map(([v, label]) => html`<button aria-pressed=${cubeText.trim() === v ? 'true' : 'false'}
        onClick=${() => onCubes(v)} title=${`Preview cube${v === '1' ? '' : 's'} #${v.replace('-', '-#')}`}>${label}</button>`)}</span>
      <span class="spacer"></span>
      ${on ? html`<span class="show-live" aria-live="polite">● Live on ${names}</span>
          <button class="btn danger" aria-pressed="true" onClick=${onStop} title="Stop sending; each cube falls back when its last colour lapses (0.6 s)">■ Stop sending</button>`
        : html`<${ActionButton} name="show.live" invoke=${onStart} label=${`Send to real cubes ${names}`} className="btn primary" disabled=${!relay.present || !shown.length}
          hazard="While on, cubes in range whose number is previewed show the editor's colour at the playhead (playing, scrubbing or paused)." />`}
    </div>
    <div class="note show-cubes-note">${valid ? `${cubes.length} cube${cubes.length === 1 ? '' : 's'} previewed${bandNote} · ` : html`<span class="warn-text">Numbers and ranges, e.g. 1-8, 12 · </span>`}${on
      ? `mirrored every ${LIVE_EVERY_MS} ms (cube firmware v1.7.0-USB.1; a cube playing a real show ignores it)`
      : relay.present ? 'Send makes those real cubes follow the playhead (cube firmware v1.7.0-USB.1)' : 'mirroring needs a General Radio (general-radio-1.2.0) connected'}</div>
    ${on && held && html`<div class="warn-text">${held}</div>`}
    ${live.error && html`<div class="warn-text">The radio refused live colours (${live.error})</div>`}
    ${oldRadio && html`<div class="warn-text">${relay.firmware} cannot relay live colours: flash general-radio-1.2.0.</div>`}</div>`;
}

// ---------------------------------------------------------------- page
function GoTo({ onGo }) {
  const [text, setText] = useState('');
  const go = () => { const ms = parseTime(text); if (ms == null) { notify('Time is m:ss.mmm', 'bad'); return; } onGo(ms); setText(''); };
  return html`<input class="field num mono" value=${text} placeholder="go to m:ss" aria-label="go to time (m:ss.mmm), Enter"
    onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter') { go(); e.currentTarget.blur(); } }} />`;
}

const typingIn = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' ||
  (el.tagName === 'INPUT' && !['checkbox', 'radio', 'button', 'color', 'range'].includes(el.type)));

export function ShowEditorSection() {
  useSections(['showedit', 'jobs']);
  const se = section('showedit');
  const [doc, setDoc] = useState(null);
  const [preview, setPreview] = useState(null);   // a cue drag in progress: committed on release
  const [dirty, setDirty] = useState(false);
  const [undo, setUndo] = useState([]);
  const [redo, setRedo] = useState([]);
  const [sel, setSel] = useState(0);
  const [t, setT] = useState(() => session.t);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [loop, setLoop] = useState('off');         // 'off' | 'cue' (the selected cue) | 'show'
  const [zoom, setZoom] = useState(0);            // px per second; the timeline clamps it (0 = the whole show fits)
  const [saveError, setSaveError] = useState(null);
  const [importText, setImportText] = useState(null);
  const [mirror, setMirror] = useState(false);
  const [mirrorHeld, setMirrorHeld] = useState(null);
  // Cube numbers to preview side by side (every cube gets the same show; fanning and random differ).
  const [cubeText, setCubeText] = useState(() => { try { return localStorage.getItem('nct.show.preview') || '1-8'; } catch (e) { return '1-8'; } });
  const cubes = parseCubes(cubeText) || [1];
  const band = bandCubes(cubes);   // the colour band's rows: always 16, the selection first
  const setCubes = (text) => { setCubeText(text); try { localStorage.setItem('nct.show.preview', text); } catch (e) { /* private mode */ } };
  const saveTimer = useRef(0);
  const player = useRef(null);
  const tRef = useRef(session.t);     // the show clock (ms); `t` is its rendered copy
  const scrubbing = useRef(false);    // the pointer holds the playhead
  const typeMemory = useRef(new Map());  // "index:start" -> {type: cue} for retypeCue
  const latest = useRef({});          // what the animation frame and key handler need from the last render
  const coloursRef = useRef([]);

  // Take the server's working copy whenever there are no local edits (first load, revert, import, another window).
  useEffect(() => { if (se && se.draft && !dirty) setDoc(clone(se.draft)); }, [se && JSON.stringify(se.draft)]);

  const commit = (next, record = true) => {
    if (record) { setUndo([...undo.slice(-99), doc]); setRedo([]); }
    setDoc(next); setDirty(true); setPreview(null);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => save(next), 1200);
  };
  const save = async (next) => {
    const why = problem(next);
    if (why) { setSaveError(why); return false; }
    try { await run('show.save', { doc: next }); setSaveError(null); setDirty(false); return true; } catch (e) { setSaveError(e.message); return false; }
  };
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  const shown = preview || doc;   // what is drawn, previewed and mirrored
  const selIndex = shown ? Math.min(sel, shown.cues.length - 1) : 0;
  const seek = (ms) => {
    const d = latest.current.doc; if (!d) return;
    const v = Math.max(0, Math.min(d.length_ms - 1, Math.round(ms)));
    tRef.current = v; setT(v);
  };

  // Playback: the show clock advances every animation frame at the playback rate, or follows the reference
  // video while that plays smoothly (lib/showvideo.js); the range loops or playback stops at the end.
  useEffect(() => {
    if (!playing) return undefined;
    let raf = 0, last = performance.now();
    const s0 = latest.current;
    if (s0.doc) {
      const [a, b] = playRange(s0.doc, s0.loop, s0.sel);
      if (tRef.current < a || tRef.current >= b - 1) seek(s0.loop === 'off' && tRef.current < b - 1 ? tRef.current : a);
    }
    const step = (now) => {
      const dt = now - last; last = now;
      const s = latest.current;
      if (!s.doc || scrubbing.current) { if (s.doc) stillVideo(tRef.current); raf = requestAnimationFrame(step); return; }
      const range = playRange(s.doc, s.loop, s.sel);
      const clock = clockStep({ prev: tRef.current, dt, rate: s.rate, videoMs: videoClock() });
      let next = clock.t, wrapped = false;
      if (s.loop === 'cue' && next < range[0]) { next = range[0]; wrapped = true; }
      const adv = advance(next, range, s.loop);
      tRef.current = adv.t; setT(adv.t);
      if (adv.stop) { setPlaying(false); return; }
      playVideo(adv.t, s.rate, clock.seek || adv.wrapped || wrapped, now);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing]);
  // Paused (or scrubbing): the video holds the frame at the playhead.
  useEffect(() => { session.t = t; if (!playing) stillVideo(t); }, [t, playing]);

  // One persistent player per previewed cube, like each cube's own: restarted on a backwards seek, a loop
  // and any edit (a new doc), so random cues walk as they would on the cube.
  const colours = useMemo(() => {
    if (!shown) return [];
    const ms = Math.floor(t);
    const key = cubes.join(',');
    if (!player.current || player.current.doc !== shown || player.current.key !== key || ms < player.current.at) {
      player.current = { doc: shown, key, at: 0, players: cubes.map((n) => ({ cube: n, player: new Player(shown, n), rng: cubeRng(n) })) };
    }
    player.current.at = ms;
    return player.current.players.map((p) => ({ cube: p.cube, rgb: p.player.render(ms, p.rng) }));
  }, [shown, Math.floor(t / 20), cubes.join(',')]);
  coloursRef.current = colours;

  // Mirror on real cubes: the colours above, ~16 times a second, while on (playing, scrubbing or paused).
  useEffect(() => {
    if (!mirror) { setMirrorHeld(null); return undefined; }
    let busy = false, stopped = false;
    const send = async () => {
      if (busy || stopped) return;
      busy = true;
      try {
        const r = await run('show.live', { entries: liveEntries(coloursRef.current), lease_ms: LIVE_LEASE_MS });
        if (!stopped) setMirrorHeld((r && r.held) || null);
      } catch (e) {
        if (!stopped) { setMirror(false); notify(`Mirroring stopped: ${e.message}`, 'bad'); }
      } finally { busy = false; }
    };
    const id = setInterval(send, LIVE_EVERY_MS);
    return () => { stopped = true; clearInterval(id); };
  }, [mirror]);

  // A file dropped outside the video player must not replace the console page.
  useEffect(() => {
    const guard = (e) => { if (e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files')) e.preventDefault(); };
    window.addEventListener('dragover', guard); window.addEventListener('drop', guard);
    return () => { window.removeEventListener('dragover', guard); window.removeEventListener('drop', guard); };
  }, []);

  // Keys (not while typing): Space play/pause, arrows ±100 ms (Shift ±1 s), Home/End, Delete removes the cue.
  useEffect(() => {
    const key = (e) => {
      const s = latest.current;
      // Cmd/Ctrl+Z undo, Shift+Cmd/Ctrl+Z or Cmd/Ctrl+Y redo (a text field keeps its own undo).
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !typingIn(document.activeElement) && ['z', 'y'].includes(e.key.toLowerCase())) {
        e.preventDefault();
        if (e.key.toLowerCase() === 'y' || e.shiftKey) s.fwd(); else s.back();
        return;
      }
      if (!s.doc || e.metaKey || e.ctrlKey || e.altKey || typingIn(document.activeElement)) return;
      const el = document.activeElement;
      if (e.key === ' ') {
        e.preventDefault();
        if (el && el.tagName === 'BUTTON') el.blur();  // not also a click on the focused button
        s.toggle(); return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); s.remove(); return; }
      const ms = keySeek(tRef.current, e.key, e.shiftKey, s.doc.length_ms);
      if (ms != null) { e.preventDefault(); seek(ms); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);

  const toggle = () => setPlaying((p) => !p);
  const addAt = (ms) => {
    const at = snap(Math.floor(ms));
    const made = insertCue(doc, at, (c) => retype(c, c.type));
    if (!made) { notify(at <= 0 ? 'The first cue already starts at 0:00' : 'A cue already starts there; move the playhead', 'warn'); return; }
    commit(made.doc); setSel(made.index);
  };
  const remove = (index = selIndex) => {
    const d = removeCue(doc, index);
    if (!d) { notify('The first cue cannot be removed (the show starts with it)', 'warn'); return; }
    commit(d); setSel(Math.max(0, index - 1));
  };
  latest.current = { doc: shown, rate, loop, sel: selIndex, toggle, remove: () => remove(), back: () => back(), fwd: () => fwd() };

  if (!se || !doc) return html`<div><${PageHead} title="Show editor" subtitle="Loading…" /></div>`;
  const tt = Math.floor(t);
  const cur = cueAt(shown, tt);
  const why = problem(doc);
  const p = se.published || {};
  const setCue = (next) => { const d = clone(doc); d.cues[selIndex] = next; commit(d); };
  // Changing a cue's type keeps what it had under its other types (colours, parameters, fan) for
  // this editing session, so switching away and back restores them. Undo also steps back.
  const retypeCue = (type) => {
    const cue = doc.cues[selIndex];
    if (!cue || cue.type === type) return;
    const key = `${selIndex}:${cue.start_ms}`;
    const kept = typeMemory.current.get(key) || {};
    kept[cue.type] = clone(cue);
    typeMemory.current.set(key, kept);
    const back = kept[type];
    setCue(back ? { ...clone(back), start_ms: cue.start_ms, label: cue.label } : retype(cue, type));
  };
  const moveStart = (index, ms) => { const d = setStart(doc, index, ms); if (d) commit(d); };
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
  const next = nextCueStart(shown, tt);
  const range = playRange(shown, loop, selIndex);
  const startMirror = async () => {
    const r = await run('show.live', { entries: liveEntries(coloursRef.current), lease_ms: LIVE_LEASE_MS });
    setMirror(true);
    return r;
  };
  const meta = html`<span class="row">
    <${Pill} tone=${dirty ? 'warn' : 'ok'} label=${dirty ? 'unsaved edits' : 'saved on this computer'} />
    <${Pill} tone=${se.draft_published ? 'ok' : 'info'} label=${se.draft_published ? `same as published v${p.version}` : p.version ? `differs from published v${p.version}` : 'not published yet'} />
    <span class="note">${doc.cues.length} cues · ${fmtTime(doc.length_ms)} · started from ${se.origin} · image ${se.summary.bytes} B ${crcText(se.summary.crc)}${se.summary.crc === se.default_crc ? ' (the compiled-in default)' : ''}</span></span>`;
  // Revert to the last version: the published show, or the cube's compiled-in default if none is
  // published yet. It is an ordinary edit, so Undo brings the working copy back.
  const lastVersion = se.published_source || null;
  const revertLast = () => {
    const target = lastVersion || se.default_doc;
    if (!target) { notify('No earlier version to revert to', 'warn'); return; }
    if (JSON.stringify(target) === JSON.stringify(doc)) { notify('Already the same as the last version', 'info'); return; }
    commit(clone(target));
    notify(lastVersion ? `Reverted to published v${p.version} (Undo brings your edits back)` : 'Reverted to the compiled-in default (Undo brings your edits back)', 'info');
  };
  const actions = html`<button class="btn" data-doc="show.revert" onClick=${revertLast} disabled=${se.draft_published && !dirty}
      title=${lastVersion ? `Replace the working copy with published v${p.version}; Undo brings it back` : 'Nothing published yet: replace the working copy with the compiled-in default; Undo brings it back'}>↺ Revert to ${lastVersion ? `v${p.version}` : 'default'}</button>
    <button class="btn primary" data-doc="show.publish" disabled=${!!why} onClick=${publish} title="Publish this show on the web as the next version (cubes are not touched)">Publish</button>
    <${ActionButton} name="show.pull" args=${{}} label="Pull" title="Fetch the published show from the web" />`;
  return html`<div>
    <${PageHead} title="Show editor" subtitle="The main show the cubes play (cube firmware v1.5.0+). Edit, publish a version, then update the cubes over the radio." meta=${meta} actions=${actions} />
    ${(why || saveError) && html`<${Banner} kind="bad" title="The cubes would refuse this show" detail=${why || saveError} />`}
    <div class="card">
      <div class="show-head">
        <div class="stack show-deck">
          <div class="row show-transport">
            <${IconButton} icon="stop" tip="Stop and return to 0:00 (Home)" onClick=${() => { setPlaying(false); seek(0); }} />
            <${IconButton} icon="prev" tip="Previous cue start (again within 0.25 s: the one before)" onClick=${() => seek(prevCueStart(shown, tt))} />
            <button class="btn primary show-play" onClick=${toggle} aria-pressed=${playing ? 'true' : 'false'} title=${playing ? 'Pause (Space)' : 'Play (Space)'} aria-label=${playing ? 'Pause (Space)' : 'Play (Space)'}>
              <${Icon} name=${playing ? 'pause' : 'play'} /></button>
            <${IconButton} icon="next" tip="Next cue start" onClick=${() => next != null && seek(next)} disabled=${next == null} />
            <span class="readout mono" aria-live="off">${fmtTime(tt)}</span>
            <span class="stack show-where"><span class="note mono">/ ${fmtTime(shown.length_ms)}</span>
              <span class="note">${tt < shown.length_ms ? `cue ${cur + 1} · ${shown.cues[cur].label || shown.cues[cur].type}` : 'ended'}</span></span></div>
          <div class="row">
            <span class="show-seg" role="group" aria-label="playback rate">${RATES.map((r) => html`<button aria-pressed=${rate === r ? 'true' : 'false'} onClick=${() => setRate(r)} title=${`Play at ${r}× speed`}>${r}×</button>`)}</span>
            <label class="lbl">Loop</label>
            <select class="field" value=${loop} onChange=${(e) => setLoop(e.target.value)} aria-label="loop">
              <option value="off">off: stop at the end</option>
              <option value="cue">the selected cue</option>
              <option value="show">the whole show</option></select>
            <${GoTo} onGo=${seek} /></div>
          <div class="row show-tools">
            <${IconButton} icon="add" tip="Add a cue at the playhead, copying the cue it splits (or double-click the cue lane)" onClick=${() => addAt(tt)} />
            <${IconButton} icon="trash" tip="Delete the selected cue (Delete)" onClick=${() => remove()} disabled=${selIndex === 0} />
            <span class="show-sep" aria-hidden="true"></span>
            <${IconButton} icon="undo" tip="Undo the last edit (⌘Z / Ctrl+Z)" onClick=${back} disabled=${!undo.length} />
            <${IconButton} icon="redo" tip="Redo (⇧⌘Z / Ctrl+Y)" onClick=${fwd} disabled=${!redo.length} />
            <span class="show-sep" aria-hidden="true"></span>
            <${IconButton} icon="fit" tip="Fit the whole show in view (or double-click the overview)" onClick=${() => setZoom(0)} />
            <span class="show-keys"><kbd>Space</kbd> play · <kbd>←</kbd><kbd>→</kbd> 0.1 s (<kbd>⇧</kbd> 1 s) · <kbd>Home</kbd><kbd>End</kbd></span></div>
        </div>
        <${VideoPanel} t=${tt} playing=${playing} />
      </div>
      <${CubeBox} se=${se} cubeText=${cubeText} cubes=${cubes} valid=${!!parseCubes(cubeText)} band=${band} onCubes=${setCubes}
        on=${mirror} held=${mirrorHeld} onStart=${startMirror} onStop=${() => setMirror(false)} />
      <${Strip} doc=${shown} zoom=${zoom} t=${tt} sel=${selIndex} cubes=${band} loop=${loop} range=${range}
        onSeek=${seek} onScrub=${(on) => { scrubbing.current = on; }} onSelect=${setSel}
        onPreview=${(d) => setPreview(d)} onCommit=${() => { if (preview && JSON.stringify(preview) !== JSON.stringify(doc)) commit(preview); else setPreview(null); }}
        onAddAt=${addAt} onZoom=${setZoom} />
      <div class="note">Top: the whole-show overview; drag its window's edges to zoom (or Ctrl/⌘ + wheel over the timeline), drag the window to scroll, double-click it to fit. Then the ruler and the colour band (the show as cubes ${cubeRanges(band)} play it, one row each, top to bottom; fanning offsets each by its number and random cues differ per cube; 100, the cube's cap, is full brightness). Click or drag either to scrub. Below: one block per cue with its colours on top and the cue under the playhead underlined. Click a block to select it, drag it to move it, drag its left edge to move only its start (10 ms steps), double-click to add a cue there.</div></div>
    <div class="grid2">
      <div class="card"><h2>Cue</h2><${Inspector} doc=${shown} index=${selIndex} cubes=${cubes} onCue=${setCue} onStart=${moveStart} onRetype=${retypeCue} />
        <h3>Show</h3><div class="row"><${TimeField} label="Length" value=${doc.length_ms} onCommit=${(ms) => commit({ ...clone(doc), length_ms: ms })} />
          <span class="note">At the end the cube turns off and leaves mainshow-ready, as before.</span></div></div>
      <div class="stack">
        <div class="card"><h2>Preview <span class="note">at the playhead</span></h2>
          <div class="note">${fmtTime(tt)} · ${tt < shown.length_ms ? (shown.cues[cur].label || shown.cues[cur].type) : 'show ended'}${mirror ? ' · mirrored on the real cubes' : ''}</div>
          <div class="ring-grid">${colours.map(({ cube, rgb: c }) => html`<div class="ring-tile" key=${cube} title=${c ? `#${cube}: levels R${c[0]} G${c[1]} B${c[2]}` : `#${cube}: show ended`}>
            <${LedRing} pixels=${c ? Array(8).fill(levelHex(c).slice(1)) : Array(8).fill('000000')} label=${'#' + cube} sub=${c ? `${c[0]} ${c[1]} ${c[2]}` : 'off'} size=${colours.length > 8 ? 90 : 120} /></div>`)}</div>
          <h3>Working copy</h3>
          <div class="row">
            <${HoldButton} name="show.revert" invoke=${() => { setDirty(false); return run('show.revert', { source: 'published' }); }} label="Revert to published" disabled=${!p.version} hazard="Discards this computer's edits." />
            <${HoldButton} name="show.revert" invoke=${() => { setDirty(false); return run('show.revert', { source: 'default' }); }} label="Start from the default" hazard="The compiled-in v1.4.1 show. Discards this computer's edits." />
            <button class="btn small" onClick=${exportJson}>Export JSON</button>
            <button class="btn small" onClick=${() => setImportText(importText == null ? '' : null)}>Import JSON…</button></div>
          ${importText != null && html`<div class="stack"><textarea class="field" rows="6" value=${importText} onInput=${(e) => setImportText(e.target.value)} placeholder="Paste a show JSON (shows/mainshow.json format)"></textarea>
            <div class="row"><${ActionButton} name="show.import" args=${{ text: importText }} label="Replace the working copy" onDone=${() => { setDirty(false); setImportText(null); }} /></div></div>`}</div></div></div>
    <${CubeShows} se=${se} /></div>`;
}
