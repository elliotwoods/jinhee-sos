// Main show renderer for the editor preview. Mirrors nctshow::Player (zones/firmware/libraries/NctShow/
// src/NctShowEngine.h) and showfile.Player (pairing_station/showfile.py) on the JSON show document; change
// them together. web/tests/showengine.test.js renders the vectors the C++ test checks.

export const TYPES = {
  off: { colours: 0, params: [] },
  solid: { colours: 1, params: [] },
  fade: { colours: 2, params: ['duration_ms'] },
  blink: { colours: 2, params: ['period_ms', 'on_ms'] },
  pulse: { colours: 2, params: ['attack_ms', 'release_ms'] },
  cycle: { colours: null, params: ['step_ms'] },
  random: { colours: 1, params: ['level_min', 'level_max', 'dur_min_ms', 'dur_max_ms', 'start_level'] },
};
export const LEVEL_MAX = 100;
// Fanning (cube firmware v1.6.0+): each cube offsets these cues by its registered number.
export const FANNABLE = ['fade', 'blink', 'pulse', 'cycle'];

// Deterministic per-cube spread (nctshow::scatter): (cube * 2654435761) >> 16 in uint32.
export function scatter(cube) { return Math.imul(cube, 2654435761 | 0) >>> 16; }

export function fanOffset(cue, cube) {
  const fan = cue.fan;
  if (!cube || !fan) return 0;
  if (fan.mode === 'sequential') return ((cube - 1) % fan.groups) * fan.step_ms;
  return scatter(cube) % (fan.spread_ms + 1);
}

// Integer interpolation exactly as the cube: truncates toward zero.
export function lerp8(from, to, elapsed, duration) {
  if (elapsed >= duration) return to;
  return from + Math.trunc(((to - from) * elapsed) / duration);
}

const fade = (a, b, e, d) => [lerp8(a[0], b[0], e, d), lerp8(a[1], b[1], e, d), lerp8(a[2], b[2], e, d)];

// Deterministic rng shared with the C++ and Python vector tests: lo + (n * 7919) % (hi - lo).
export function testRng() {
  let n = 0;
  return (lo, hi) => { n += 1; return lo + ((n * 7919) % (hi - lo)); };
}

export function cueAt(doc, t) {
  let found = 0;
  for (let i = 1; i < doc.cues.length; i++) {
    if (doc.cues[i].start_ms > t) break;
    found = i;
  }
  return found;
}

export class Player {
  // `cube`: the registered cube number (0 = none), which sets its fanning offsets.
  constructor(doc, cube = 0) { this.doc = doc; this.cube = cube; this.restart(); }
  restart() { this.randomCue = -1; this.from = 0; this.to = 0; this.start = 0; this.duration = 1; }

  // [r, g, b] in cube levels (0..100), or null once t reaches the show length.
  render(t, rng) {
    const doc = this.doc;
    if (t >= doc.length_ms) return null;
    const index = cueAt(doc, t);
    const cue = doc.cues[index];
    const local = t - cue.start_ms, p = cue.params, c = cue.colours;
    const offset = fanOffset(cue, this.cube);
    const delayed = Math.max(0, local - offset);  // one-shot effects wait; periodic ones shift phase
    switch (cue.type) {
      case 'off': return [0, 0, 0];
      case 'solid': return [...c[0]];
      case 'fade': return fade(c[0], c[1], delayed, p.duration_ms);
      case 'blink': return [...((local + p.period_ms - (offset % p.period_ms)) % p.period_ms < p.on_ms ? c[0] : c[1])];
      case 'pulse': return delayed < p.attack_ms ? fade(c[0], c[1], delayed, p.attack_ms) : fade(c[1], c[0], delayed - p.attack_ms, p.release_ms);
      case 'cycle': {
        const n = c.length, period = p.step_ms * n;
        const cycle = (local + period - (offset % period)) % period, step = Math.floor(cycle / p.step_ms);
        return fade(c[step], c[(step + 1) % n], cycle - step * p.step_ms, p.step_ms);
      }
      case 'random': {
        const level = Math.min(this.randomLevel(p, index, t, rng), LEVEL_MAX);
        return c[0].map((v) => Math.floor((level * v) / 100));
      }
      default: return [0, 0, 0];
    }
  }

  randomLevel(p, index, t, rng) {
    const transition = () => {
      this.to = rng(p.level_min, p.level_max + 1);
      this.start = t;
      this.duration = rng(p.dur_min_ms, p.dur_max_ms + 1);
    };
    if (this.randomCue !== index) { this.randomCue = index; this.from = p.start_level; transition(); }
    let elapsed = (t - this.start) >>> 0;  // a backwards jump wraps, like the cube's uint32
    if (elapsed >= this.duration) { this.from = this.to; transition(); elapsed = 0; }
    return lerp8(this.from, this.to, elapsed, this.duration);
  }
}

// Display colour of a cube level triple: 100 (the cube's cap) shown as full brightness.
export function levelHex(rgb) {
  return '#' + rgb.map((v) => Math.round((Math.max(0, Math.min(LEVEL_MAX, v)) * 255) / LEVEL_MAX).toString(16).padStart(2, '0')).join('');
}
export function hexLevels(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
  return m ? [1, 2, 3].map((i) => Math.round((parseInt(m[i], 16) * LEVEL_MAX) / 255)) : [0, 0, 0];
}

// A fresh cue of `type` keeping what it can of `from` (colours, start, label).
export function retype(from, type) {
  const spec = TYPES[type];
  const base = from.colours.length ? from.colours : [[18, 20, 1]];
  const count = spec.colours === null ? Math.max(1, Math.min(3, base.length)) : spec.colours;
  const colours = Array.from({ length: count }, (_, i) => [...(base[i] || base[base.length - 1] || [0, 0, 0])]);
  const defaults = { duration_ms: 1000, period_ms: 1000, on_ms: 500, attack_ms: 120, release_ms: 180, step_ms: 1000,
    level_min: 12, level_max: 50, dur_min_ms: 700, dur_max_ms: 1500, start_level: 20 };
  const params = Object.fromEntries(spec.params.map((k) => [k, from.params && from.params[k] != null ? from.params[k] : defaults[k]]));
  const cue = { start_ms: from.start_ms, label: from.label || '', type, colours, params };
  if (from.fan && FANNABLE.includes(type)) cue.fan = { ...from.fan };
  return cue;
}

// First problem the cube would refuse, or null. The backend (showfile.validate) is the authority.
export function problem(doc) {
  if (!(doc.length_ms >= 1 && doc.length_ms <= 3600000)) return 'Show length must be 1 ms to 1 hour';
  if (!doc.cues.length || doc.cues.length > 128) return 'A show needs 1 to 128 cues';
  let previous = -1;
  for (let i = 0; i < doc.cues.length; i++) {
    const c = doc.cues[i], where = `Cue ${i + 1}`;
    if (i === 0 && c.start_ms !== 0) return 'The first cue must start at 0:00.000';
    if (c.start_ms <= previous) return `${where} must start after cue ${i}`;
    if (c.start_ms >= doc.length_ms) return `${where} starts after the show ends`;
    previous = c.start_ms;
    for (const rgb of c.colours) if (rgb.some((v) => !(Number.isInteger(v) && v >= 0 && v <= LEVEL_MAX))) return `${where}: colour levels are 0-100`;
    for (const [k, v] of Object.entries(c.params)) {
      const level = ['level_min', 'level_max', 'start_level'].includes(k);
      const low = level || k === 'on_ms' ? 0 : 1;
      if (!(Number.isInteger(v) && v >= low && v <= (level ? LEVEL_MAX : 65535))) return `${where}: ${k} must be ${low}-${level ? LEVEL_MAX : 65535}`;
    }
    if (c.type === 'blink' && c.params.on_ms > c.params.period_ms) return `${where}: on time cannot exceed the period`;
    if (c.fan) {
      if (!FANNABLE.includes(c.type)) return `${where}: ${c.type} cannot fan`;
      const [k, hi] = c.fan.mode === 'sequential' ? ['step_ms', 65535] : ['spread_ms', 65535];
      if (!(Number.isInteger(c.fan[k]) && c.fan[k] >= 1 && c.fan[k] <= hi)) return `${where}: fan ${k} must be 1-${hi}`;
      if (c.fan.mode === 'sequential' && !(Number.isInteger(c.fan.groups) && c.fan.groups >= 1 && c.fan.groups <= 255)) return `${where}: fan group size must be 1-255`;
    }
    if (c.type === 'random' && c.params.level_min > c.params.level_max) return `${where}: level min cannot exceed level max`;
    if (c.type === 'random' && c.params.dur_min_ms > c.params.dur_max_ms) return `${where}: shortest step cannot exceed longest`;
  }
  return null;
}

// Cube numbers from text like "1-8, 12, 20-22" (at most `max`).
export function parseCubes(text, max = 48) {
  const out = [];
  for (const part of String(text || '').split(/[\s,]+/).filter(Boolean)) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) return null;
    const a = parseInt(m[1], 10), b = m[2] ? parseInt(m[2], 10) : a;
    for (let n = Math.min(a, b); n <= Math.max(a, b) && out.length < max; n++) if (!out.includes(n)) out.push(n);
  }
  return out;
}

// A preview rng per cube: deterministic, different for every cube (the real cubes use hardware randomness).
export function cubeRng(cube) {
  let s = (Math.imul(cube + 1, 2654435761) >>> 0) || 1;
  return (lo, hi) => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return lo + (s % (hi - lo)); };
}

export function fmtTime(ms) {
  const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000), r = Math.floor(ms % 1000);
  return `${m}:${String(s).padStart(2, '0')}.${String(r).padStart(3, '0')}`;
}
export function parseTime(text) {
  const m = /^\s*(?:(\d+):)?(\d+(?:\.\d{0,3})?)\s*$/.exec(text || '');
  if (!m) return null;
  return Math.round((parseInt(m[1] || '0', 10) * 60 + parseFloat(m[2])) * 1000);
}
