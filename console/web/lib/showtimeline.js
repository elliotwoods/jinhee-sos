// Pure timeline helpers for the Show editor (panels/ShowEditor.js): canvas layout and hit-testing, cue
// edits that keep the cue order valid, and the transport's clock arithmetic. No DOM; tested in
// web/tests/showtimeline.test.js.
import { cueAt } from './showengine.js';

export const RULER = 20, LANE = 46, OVERVIEW = 22, EDGE_PX = 5, SNAP_MS = 10;
export const RATES = [0.25, 0.5, 1, 2];
export const MAX_CANVAS_PX = 32000;  // browsers refuse wider canvases

// The colour band: one row per previewed cube.
export const BAND_ROWS = 16;
export const bandFor = (n) => (n <= 1 ? 40 : n * (n <= 4 ? 14 : n <= 12 ? 9 : n <= BAND_ROWS ? 6 : 5));

// The band's cube rows: the selected numbers in their order, then the numbers after the highest one
// until there are `rows` (all of the selection when it is longer). "17" -> 17..32, "1-8" -> 1..16.
export function bandCubes(selected, rows = BAND_ROWS) {
  const out = [];
  selected.forEach((n) => { if (!out.includes(n)) out.push(n); });
  let next = (out.length ? Math.max(...out) : 0) + 1;
  while (out.length < rows && next <= 65535) out.push(next++);
  return out;
}
export function layout(cubeCount) {
  const band = bandFor(cubeCount);
  return { ruler: RULER, band, lane: LANE, laneTop: RULER + band, height: RULER + band + LANE };
}

// The largest zoom (px per second) whose canvas still fits a browser canvas.
export function maxZoom(lengthMs, ceiling = 60) {
  return Math.max(1, Math.min(ceiling, Math.floor(MAX_CANVAS_PX / Math.max(1, lengthMs / 1000))));
}

export const snap = (ms, step = SNAP_MS) => Math.round(ms / step) * step;
export const cueEnd = (doc, i) => (i + 1 < doc.cues.length ? doc.cues[i + 1].start_ms : doc.length_ms);
export const xOf = (ms, zoom) => (ms / 1000) * zoom;
export function msAt(doc, zoom, x) {
  return Math.max(0, Math.min(doc.length_ms - 1, Math.round((x * 1000) / zoom)));
}

// What is under the pointer: {area: 'ruler' | 'band' | 'edge' | 'block', index}. An edge is the start of
// any cue but the first (the nearest within EDGE_PX); a block is the cue whose span contains x.
export function hitTest(doc, zoom, lay, x, y) {
  if (y < lay.ruler) return { area: 'ruler', index: cueAt(doc, msAt(doc, zoom, x)) };
  if (y < lay.laneTop) return { area: 'band', index: cueAt(doc, msAt(doc, zoom, x)) };
  let edge = -1, best = EDGE_PX + 1;
  doc.cues.forEach((c, i) => {
    const d = Math.abs(xOf(c.start_ms, zoom) - x);
    if (i > 0 && d <= EDGE_PX && d < best) { edge = i; best = d; }
  });
  if (edge > 0) return { area: 'edge', index: edge };
  return { area: 'block', index: cueAt(doc, msAt(doc, zoom, x)) };
}

// Ruler ticks: a labelled major step at least `minPx` apart, and minor ticks between.
const STEPS = [100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
export function rulerStep(zoom, minPx = 64) {
  const major = STEPS.find((ms) => xOf(ms, zoom) >= minPx) || STEPS[STEPS.length - 1];
  const minor = major >= 60000 ? major / 6 : major % 3000 === 0 && major !== 30000 ? major / 3 : major / 5;
  return { major, minor };
}
export function tickLabel(ms, major) {
  const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000);
  const base = `${m}:${String(s).padStart(2, '0')}`;
  return major < 1000 ? `${base}.${String(Math.floor(ms % 1000)).padStart(3, '0').slice(0, major % 100 === 0 ? 1 : 2)}` : base;
}

// ---------------------------------------------------------------- cue edits (return a new doc, or null)
const clone = (x) => JSON.parse(JSON.stringify(x));

// Move one cue's start between its neighbours (never the first cue's).
export function setStart(doc, index, ms) {
  if (index <= 0 || index >= doc.cues.length) return null;
  const d = clone(doc);
  const lo = d.cues[index - 1].start_ms + 1, hi = cueEnd(d, index) - 1;
  d.cues[index].start_ms = Math.max(lo, Math.min(hi, Math.round(ms)));
  return d;
}

// Move a whole cue block by `delta` ms, keeping its length: its start and the next cue's start shift
// together, clamped so no cue collapses. The last cue ends with the show, so only its start moves.
export function moveBlock(doc, index, delta) {
  if (index <= 0 || index >= doc.cues.length) return null;
  if (index === doc.cues.length - 1) return setStart(doc, index, doc.cues[index].start_ms + delta);
  const d = clone(doc), c = d.cues;
  const lo = c[index - 1].start_ms + 1 - c[index].start_ms;
  const hi = cueEnd(d, index + 1) - 1 - c[index + 1].start_ms;
  const k = Math.max(lo, Math.min(hi, Math.round(delta)));
  c[index].start_ms += k; c[index + 1].start_ms += k;
  return d;
}

// Split the cue under `at` with a copy starting there: {doc, index} or null when one already starts there.
export function insertCue(doc, at, make) {
  if (at <= 0 || at >= doc.length_ms) return null;
  const index = cueAt(doc, at);
  if (doc.cues[index].start_ms === at) return null;
  const d = clone(doc);
  d.cues.splice(index + 1, 0, { ...make(doc.cues[index]), start_ms: at, label: '' });
  return { doc: d, index: index + 1 };
}

export function removeCue(doc, index) {
  if (index <= 0 || index >= doc.cues.length) return null;
  const d = clone(doc); d.cues.splice(index, 1);
  return d;
}

// Colours that represent a cue on its block's swatch strip (cube levels).
export function cueSwatch(cue) {
  if (cue.type === 'off' || !cue.colours.length) return [[0, 0, 0]];
  return cue.colours;
}

// ---------------------------------------------------------------- transport
// The playback range: the selected cue, or the whole show.
export function playRange(doc, loop, sel) {
  if (loop === 'cue' && doc.cues[sel]) return [doc.cues[sel].start_ms, cueEnd(doc, sel)];
  return [0, doc.length_ms];
}

// Where the clock goes after reaching `t`: wraps inside the range when looping, else stops at the end.
export function advance(t, range, loop) {
  const [a, b] = range;
  if (t < b) return { t, stop: false, wrapped: false };
  if (loop !== 'off' && b > a) return { t: a + ((t - a) % (b - a)), stop: false, wrapped: true };
  return { t: b - 1, stop: true, wrapped: false };
}

// Keyboard seeking: arrows ±100 ms (Shift ±1 s), Home/End. null for other keys.
export function keySeek(t, key, shift, length) {
  const step = shift ? 1000 : 100;
  const clamp = (v) => Math.max(0, Math.min(length - 1, v));
  if (key === 'ArrowLeft') return clamp(Math.round(t) - step);
  if (key === 'ArrowRight') return clamp(Math.round(t) + step);
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  return null;
}

// Previous cue start: the current cue's start, or the one before when already within `grace` ms of it.
export function prevCueStart(doc, t, grace = 250) {
  let i = cueAt(doc, t);
  if (t - doc.cues[i].start_ms <= grace && i > 0) i -= 1;
  return doc.cues[i].start_ms;
}
export function nextCueStart(doc, t) {
  const next = doc.cues.find((c) => c.start_ms > t);
  return next ? next.start_ms : null;
}

// A new scrollLeft that keeps x visible (null when it already is): the playhead lands a fifth in.
export function followScroll(x, scrollLeft, width, margin = 0.08) {
  if (width <= 0) return null;
  if (x >= scrollLeft + width * margin && x <= scrollLeft + width * (1 - margin)) return null;
  return Math.max(0, Math.round(x - width * 0.2));
}

// Is `firmware` ("general-radio-1.2.0") at least `min` ([1, 2, 0])? null when it is not that family.
export function fwAtLeast(firmware, family, min) {
  const m = new RegExp(`^${family}-(\\d+)\\.(\\d+)\\.(\\d+)`).exec(firmware || '');
  if (!m) return null;
  const v = [1, 2, 3].map((i) => parseInt(m[i], 10));
  for (let i = 0; i < 3; i++) if (v[i] !== min[i]) return v[i] > min[i];
  return true;
}

// ---------------------------------------------------------------- zoom (px per second)
// The zoom range for a viewport `viewPx` wide: the smallest shows the whole show (never above the cap),
// the largest is maxZoom's. Before the viewport is measured the smallest is 1 px/s.
export function zoomLimits(lengthMs, viewPx) {
  const max = maxZoom(lengthMs);
  const fit = viewPx > 2 ? ((viewPx - 2) * 1000) / Math.max(1, lengthMs) : 1;
  return { min: Math.min(fit, max), max };
}
export function clampZoom(zoom, lengthMs, viewPx) {
  const { min, max } = zoomLimits(lengthMs, viewPx);
  return Math.max(min, Math.min(max, zoom));
}

// The visible window in show ms for a scroll position.
export function viewWindow(scrollLeft, viewPx, zoom) {
  return [(scrollLeft * 1000) / zoom, ((scrollLeft + viewPx) * 1000) / zoom];
}

// What the overview pointer is on: the window's 'left' or 'right' edge (within `grip` px), 'inside' it,
// or 'outside'. `vx`, `vw`: the window box on the overview (px).
export function overviewHit(x, vx, vw, grip = 6) {
  const g = Math.min(grip, vw / 3);
  if (Math.abs(x - vx) <= g) return 'left';
  if (Math.abs(x - (vx + vw)) <= g) return 'right';
  return x > vx && x < vx + vw ? 'inside' : 'outside';
}

// Dragging an edge of the overview's window to overview x: the other edge stays put and the window's
// duration sets the zoom (viewport width / duration), clamped to the limits. {zoom, startMs}.
export function edgeZoom({ edge, x, overviewPx, window: [a, b], lengthMs, viewPx }) {
  const ms = Math.max(0, Math.min(lengthMs, (x / Math.max(1, overviewPx)) * lengthMs));
  const dur = edge === 'left' ? b - ms : ms - a;
  let zoom = clampZoom((viewPx * 1000) / Math.max(1, dur), lengthMs, viewPx);
  if ((zoom * lengthMs) / 1000 <= viewPx) zoom = zoomLimits(lengthMs, viewPx).min;  // the whole show: fit exactly
  const shown = (viewPx * 1000) / zoom;
  return { zoom, startMs: Math.max(0, edge === 'left' ? b - shown : a) };
}

// Zooming by `factor` around a pointer `anchorPx` into the viewport: the show time under the pointer
// stays under it. {zoom, scrollLeft}.
export function zoomAround({ zoom, factor, anchorPx, scrollLeft, lengthMs, viewPx }) {
  const next = clampZoom(zoom * factor, lengthMs, viewPx);
  const ms = ((scrollLeft + anchorPx) * 1000) / zoom;
  return { zoom: next, scrollLeft: Math.max(0, Math.round((ms * next) / 1000 - anchorPx)) };
}

// Cube numbers as short ranges: [1,2,3,4,12] -> "#1-#4, #12".
// Append cube numbers to a "Preview cubes" text (e.g. "1-8, 12") without repeating any already in it.
// `parsed` is the text's current numbers (parseCubes); returns the new text, or the same text if nothing new.
export function addCubeNumbers(text, parsed, numbers) {
  const have = new Set(parsed || []);
  const extra = [...new Set(numbers)].filter((n) => Number.isInteger(n) && n >= 1 && !have.has(n)).sort((a, b) => a - b);
  if (!extra.length) return text;
  const base = String(text || '').trim().replace(/[\s,]+$/, '');
  return (base ? base + ', ' : '') + extra.join(', ');
}

export function cubeRanges(nums) {
  const out = [];
  [...nums].sort((a, b) => a - b).forEach((n) => {
    const last = out[out.length - 1];
    if (last && n === last[1] + 1) last[1] = n; else if (!last || n !== last[1]) out.push([n, n]);
  });
  return out.map(([a, b]) => (a === b ? `#${a}` : `#${a}-#${b}`)).join(', ');
}
