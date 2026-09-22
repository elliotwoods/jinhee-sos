import { html } from '../lib/html.js';
import { useEffect, useRef, useState } from 'preact/hooks';
import { cssVar, colour as resolve, onThemeChange } from '../lib/theme.js';
import { docStill } from '../lib/doc.js';

// Redraw on the given deps and whenever the theme changes. Colours come from the CSS tokens.
function useCanvas(draw, deps) {
  const ref = useRef(null);
  const [theme, setTheme] = useState(0);
  useEffect(() => onThemeChange(() => setTheme((n) => n + 1)), []);
  useEffect(() => { const c = ref.current; if (!c) return; const ctx = c.getContext('2d'); draw(ctx, c.width, c.height); }, [...deps, theme]);
  return ref;
}

const SANS = '-apple-system, "Segoe UI", sans-serif';

// The cube's 8-LED ring in the colour it was last commanded to show. `colour` may be a token ('--led-off').
export function LedRing({ colour = '--led-off', label = '', sub = '', size = 200, pixels, blink, doc }) {
  if (docStill()) blink = false;   // a documentation still: one static frame, no blinking
  const ref = useCanvas((ctx, w, h) => {
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2 - 8, r = w * 0.34;
    const on = blink && (Math.floor(Date.now() / 500) % 2);
    const base = resolve(colour, cssVar('--led-off'));
    for (let k = 0; k < 8; k++) {
      const a = k * Math.PI / 4;
      const c = on ? cssVar('--led-blink') : pixels ? '#' + pixels[k] : base;
      ctx.beginPath(); ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, w * 0.075, 0, Math.PI * 2);
      ctx.fillStyle = c; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = cssVar('--border-strong'); ctx.stroke();
    }
    ctx.fillStyle = cssVar('--text');
    ctx.textAlign = 'center'; ctx.font = `600 ${w * 0.16}px ${SANS}`; ctx.fillText(label, cx, cy + w * 0.06);
    ctx.fillStyle = cssVar('--text-muted');
    ctx.font = `600 ${w * 0.055}px ${SANS}`; ctx.fillText(sub.toUpperCase(), cx, cy + w * 0.16);
    if (size >= 140) { ctx.fillStyle = cssVar('--text-faint'); ctx.font = `${w * 0.045}px ${SANS}`; ctx.fillText('LED ring = last commanded colour', cx, h - 6); }
  }, [colour, label, sub, pixels && pixels.join(','), blink, blink ? Math.floor(Date.now() / 500) : 0]);
  return html`<canvas class="ring" ref=${ref} data-doc=${doc} width=${size} height=${size + 10} role="img" aria-label=${`LED ring ${label} ${sub}`}></canvas>`;
}

// Time series: `series` = [{points: [{t, v}], colour, label}]; colour may be a token ('--chart-1').
export function Chart({ series, width = 420, height = 140, min, max, unit = '', span }) {
  const ref = useCanvas((ctx, w, h) => {
    ctx.clearRect(0, 0, w, h);
    const line = cssVar('--border');
    const muted = cssVar('--text-faint');
    ctx.font = `10px ${SANS}`;
    const all = series.flatMap((s) => s.points);
    if (!all.length) { ctx.fillStyle = muted; ctx.fillText('No data yet', 8, 16); return; }
    const t1 = Math.max(...all.map((p) => p.t)); const t0 = span ? t1 - span : Math.min(...all.map((p) => p.t));
    const lo = min ?? Math.min(...all.map((p) => p.v)), hi = max ?? Math.max(...all.map((p) => p.v));
    const X = (t) => 36 + (w - 44) * (t1 === t0 ? 1 : (t - t0) / (t1 - t0));
    const Y = (v) => h - 18 - (h - 28) * (hi === lo ? 0.5 : (v - lo) / (hi - lo));
    ctx.strokeStyle = line; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const y = 10 + (h - 28) * i / 4; ctx.beginPath(); ctx.moveTo(36, y); ctx.lineTo(w - 8, y); ctx.stroke(); }
    ctx.fillStyle = muted; ctx.textAlign = 'right';
    ctx.fillText(`${hi.toFixed(0)}${unit}`, 32, 14); ctx.fillText(`${lo.toFixed(0)}${unit}`, 32, h - 16);
    for (const s of series) {
      ctx.strokeStyle = resolve(s.colour, cssVar('--chart-1')); ctx.lineWidth = 1.5; ctx.beginPath();
      s.points.filter((p) => p.t >= t0).forEach((p, i) => { i ? ctx.lineTo(X(p.t), Y(p.v)) : ctx.moveTo(X(p.t), Y(p.v)); });
      ctx.stroke();
    }
  }, [series, width, height, min, max]);
  const swatch = (c) => (c && c.startsWith('--') ? `var(${c})` : c);
  return html`<div><canvas class="chart" ref=${ref} width=${width} height=${height}></canvas>
    <div class="legend">${series.map((s) => html`<span><span class="swatch" style=${`background:${swatch(s.colour)}`}></span>${s.label}</span>`)}</div></div>`;
}

// Slider distance → member index band diagram (23 ticks between two calibration distances).
export function BandDiagram({ ticks, distance, index, width = 640, height = 90, doc }) {
  const ref = useCanvas((ctx, w, h) => {
    ctx.clearRect(0, 0, w, h);
    const muted = cssVar('--text-muted');
    const t = (ticks && ticks.length === 23) ? ticks : null;
    const lo = t ? Math.min(...t) : 43, hi = t ? Math.max(...t) : 383;
    const X = (mm) => 10 + (w - 20) * (mm - lo) / (hi - lo || 1);
    for (let i = 0; i < 23; i++) {
      const mm = t ? t[i] : lo + (hi - lo) * i / 22;
      ctx.fillStyle = index === i + 1 ? cssVar('--accent') : cssVar(i % 2 ? '--band-a' : '--band-b');
      const x0 = X(mm), x1 = X(t ? (t[i + 1] ?? mm) : mm + (hi - lo) / 22);
      ctx.fillRect(Math.min(x0, x1), 20, Math.abs(x1 - x0) || 2, 40);
      ctx.fillStyle = index === i + 1 ? cssVar('--text') : muted; ctx.font = `9px ${SANS}`; ctx.textAlign = 'center'; ctx.fillText(String(i + 1), (x0 + x1) / 2, 74);
    }
    if (distance != null) { ctx.strokeStyle = cssVar('--warn'); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(X(distance), 12); ctx.lineTo(X(distance), 66); ctx.stroke(); }
    ctx.fillStyle = muted; ctx.font = `10px ${SANS}`; ctx.textAlign = 'left'; ctx.fillText(`${lo} mm`, 10, 12); ctx.textAlign = 'right'; ctx.fillText(`${hi} mm`, w - 10, 12);
  }, [ticks && ticks.join(','), distance, index]);
  return html`<canvas class="band" ref=${ref} data-doc=${doc} width=${width} height=${height}></canvas>`;
}

export function MemberGrid({ slots, onToggle, disabled }) {
  const held = new Set((slots || []).filter(Boolean));
  return html`<div class="members">${Array.from({ length: 23 }, (_, i) => i + 1).map((m) => html`<button class=${'btn' + (held.has(m) ? ' on' : '')} data-doc="member" disabled=${disabled} onClick=${() => onToggle(m)} aria-pressed=${held.has(m) ? 'true' : 'false'}>${String(m).padStart(2, '0')}<small>${held.has(m) ? 'ON' : 'OFF'}</small></button>`)}</div>`;
}
