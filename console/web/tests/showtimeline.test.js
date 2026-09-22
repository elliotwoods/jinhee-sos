// Show editor timeline and transport helpers, and the reference-video sync decisions.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  layout, hitTest, setStart, moveBlock, insertCue, removeCue, playRange, advance, keySeek, prevCueStart, nextCueStart,
  followScroll, rulerStep, tickLabel, maxZoom, snap, fwAtLeast, cueSwatch,
  zoomLimits, clampZoom, viewWindow, overviewHit, edgeZoom, zoomAround, cubeRanges, bandCubes, bandFor,
} from '../lib/showtimeline.js';
import { clockStep, videoPhase, videoTarget, maySeek, stillNeedsSeek, isVideoFile } from '../lib/showvideo.js';

const cue = (start_ms, type = 'solid') => ({ start_ms, label: '', type, colours: [[1, 2, 3]], params: {} });
const doc = { length_ms: 10000, cues: [cue(0), cue(2000), cue(5000), cue(8000)] };

test('hit-testing: ruler, band, cue edges (never the first) and blocks', () => {
  const lay = layout(1), zoom = 10;  // 10 px per second: cue 2 starts at x = 20
  assert.equal(hitTest(doc, zoom, lay, 30, 5).area, 'ruler');
  assert.equal(hitTest(doc, zoom, lay, 30, lay.ruler + 3).area, 'band');
  const y = lay.laneTop + 10;
  assert.deepEqual(hitTest(doc, zoom, lay, 22, y), { area: 'edge', index: 1 });
  assert.deepEqual(hitTest(doc, zoom, lay, 1, y), { area: 'block', index: 0 });
  assert.deepEqual(hitTest(doc, zoom, lay, 35, y), { area: 'block', index: 1 });
  assert.deepEqual(hitTest(doc, zoom, lay, 79, y), { area: 'edge', index: 3 });
});

test('cue edits keep the order and never move the first cue', () => {
  assert.equal(setStart(doc, 0, 100), null);
  assert.equal(setStart(doc, 1, -50).cues[1].start_ms, 1);
  assert.equal(setStart(doc, 1, 9999).cues[1].start_ms, 4999);
  // A block keeps its length and stops at its neighbours.
  const moved = moveBlock(doc, 1, 500);
  assert.deepEqual(moved.cues.map((c) => c.start_ms), [0, 2500, 5500, 8000]);
  assert.deepEqual(moveBlock(doc, 1, -9000).cues.map((c) => c.start_ms), [0, 1, 3001, 8000]);
  assert.deepEqual(moveBlock(doc, 1, 9000).cues.map((c) => c.start_ms), [0, 4999, 7999, 8000]);
  assert.deepEqual(moveBlock(doc, 3, 5000).cues.map((c) => c.start_ms), [0, 2000, 5000, 9999], 'the last cue ends with the show');
  assert.equal(moveBlock(doc, 0, 100), null);
  assert.deepEqual(doc.cues.map((c) => c.start_ms), [0, 2000, 5000, 8000], 'the original is untouched');
  const added = insertCue(doc, 3000, (c) => ({ ...c }));
  assert.equal(added.index, 2);
  assert.deepEqual(added.doc.cues.map((c) => c.start_ms), [0, 2000, 3000, 5000, 8000]);
  assert.equal(insertCue(doc, 2000, (c) => c), null);
  assert.equal(removeCue(doc, 0), null);
  assert.equal(removeCue(doc, 2).cues.length, 3);
  assert.equal(snap(1234), 1230);
  assert.deepEqual(cueSwatch(cue(0, 'off')), [[0, 0, 0]]);
});

test('transport: ranges, loop wrap, stop at the end, keys and cue jumps', () => {
  assert.deepEqual(playRange(doc, 'cue', 1), [2000, 5000]);
  assert.deepEqual(playRange(doc, 'show', 1), [0, 10000]);
  assert.deepEqual(advance(4000, [2000, 5000], 'cue'), { t: 4000, stop: false, wrapped: false });
  assert.deepEqual(advance(5300, [2000, 5000], 'cue'), { t: 2300, stop: false, wrapped: true });
  assert.deepEqual(advance(10020, [0, 10000], 'off'), { t: 9999, stop: true, wrapped: false });
  assert.equal(keySeek(500, 'ArrowLeft', false, 10000), 400);
  assert.equal(keySeek(500, 'ArrowLeft', true, 10000), 0);
  assert.equal(keySeek(9500, 'ArrowRight', true, 10000), 9999);
  assert.equal(keySeek(500, 'End', false, 10000), 9999);
  assert.equal(keySeek(500, 'x', false, 10000), null);
  assert.equal(prevCueStart(doc, 5600), 5000);
  assert.equal(prevCueStart(doc, 5100), 2000, 'just after a cue start goes to the one before');
  assert.equal(nextCueStart(doc, 5000), 8000);
  assert.equal(nextCueStart(doc, 8000), null);
  assert.equal(followScroll(500, 0, 1000), null);
  assert.equal(followScroll(990, 0, 1000), 790);
  assert.equal(followScroll(10, 400, 1000), 0);
});

test('ruler steps stay readable and the canvas stays within browser limits', () => {
  assert.deepEqual(rulerStep(4), { major: 30000, minor: 6000 });
  assert.equal(rulerStep(60).major, 2000);
  assert.equal(rulerStep(1000).major, 100);
  assert.equal(tickLabel(65000, 5000), '1:05');
  assert.equal(tickLabel(1500, 500), '0:01.5');
  assert.equal(tickLabel(1250, 250), '0:01.25');
  assert.equal(maxZoom(298000), 60);
  assert.equal(maxZoom(3600000), 8);
  assert.equal(fwAtLeast('general-radio-1.2.0', 'general-radio', [1, 2, 0]), true);
  assert.equal(fwAtLeast('general-radio-1.1.9', 'general-radio', [1, 2, 0]), false);
  assert.equal(fwAtLeast('general-radio-2.0.0', 'general-radio', [1, 2, 0]), true);
  assert.equal(fwAtLeast('nct-pairing-1.8', 'general-radio', [1, 2, 0]), null);
});

test('video sync: the video leads while smooth, the show clock leads after a jump', () => {
  // No usable video: free-run at the playback rate.
  assert.deepEqual(clockStep({ prev: 1000, dt: 20, rate: 0.5, videoMs: null }), { t: 1010, seek: false });
  // Smooth video within the drift window: the show takes the video's time...
  assert.deepEqual(clockStep({ prev: 1000, dt: 16, rate: 1, videoMs: 1030 }), { t: 1030, seek: false });
  // ...but never steps backwards on jitter.
  assert.deepEqual(clockStep({ prev: 1000, dt: 16, rate: 1, videoMs: 990 }), { t: 1000, seek: false });
  // A scrub or wrap: the video is far away, so it is sought to the show clock.
  assert.deepEqual(clockStep({ prev: 5000, dt: 16, rate: 1, videoMs: 1200 }), { t: 5016, seek: true });
  assert.equal(videoTarget(1500, 2000), 3.5);
  assert.equal(videoPhase(-0.1, 10), 'before');
  assert.equal(videoPhase(10, 10), 'after');
  assert.equal(videoPhase(3, NaN), 'in');
  assert.equal(maySeek(1000, 800, false), false);
  assert.equal(maySeek(1000, 600, false), true);
  assert.equal(maySeek(1000, null, true), false);
  assert.equal(stillNeedsSeek(1.0, 1.01), false);
  assert.equal(stillNeedsSeek(1.0, 1.1), true);
  assert.equal(isVideoFile({ name: 'a.MOV', type: '' }), true);
  assert.equal(isVideoFile({ name: 'a.txt', type: 'text/plain' }), false);
});

test('zoom: limits fit the whole show, overview edges and pointer zoom keep their anchors', () => {
  // 100 s show in a 1002 px viewport: the whole show fits at 10 px/s; the cap is 60.
  assert.deepEqual(zoomLimits(100000, 1002), { min: 10, max: 60 });
  assert.deepEqual(zoomLimits(100000, 0), { min: 1, max: 60 }, 'unmeasured viewport');
  assert.equal(zoomLimits(5000, 1002).min, 60, 'a short show never goes past the cap');
  assert.equal(clampZoom(2, 100000, 1002), 10);
  assert.equal(clampZoom(500, 100000, 1002), 60);
  assert.deepEqual(viewWindow(200, 1000, 20), [10000, 60000]);
  assert.equal(overviewHit(100, 100, 50), 'left');
  assert.equal(overviewHit(148, 100, 50), 'right');
  assert.equal(overviewHit(125, 100, 50), 'inside');
  assert.equal(overviewHit(20, 100, 50), 'outside');
  // Overview 1000 px for 100 s (1 px = 100 ms), window 10-60 s at 20 px/s in a 1000 px view.
  const base = { overviewPx: 1000, window: [10000, 60000], lengthMs: 100000, viewPx: 1000 };
  // Right edge in to 35 s: the window halves (25 s), zoom doubles, the start stays.
  assert.deepEqual(edgeZoom({ ...base, edge: 'right', x: 350 }), { zoom: 40, startMs: 10000 });
  // Left edge out to 0: 60 s shown, the end stays at 60 s.
  const out = edgeZoom({ ...base, edge: 'left', x: 0 });
  assert.ok(Math.abs(out.zoom - 1000 / 60) < 1e-9);
  assert.ok(Math.abs(out.startMs) < 1e-6);
  // Dragged past the other edge or to a sliver: clamped to the cap.
  assert.equal(edgeZoom({ ...base, edge: 'right', x: 90 }).zoom, 60);
  assert.equal(edgeZoom({ ...base, edge: 'left', x: 599 }).zoom, 60);
  assert.ok(Math.abs(edgeZoom({ ...base, edge: 'left', x: 599 }).startMs - (60000 - 1000000 / 60)) < 1e-6);
  // Out to the whole show: never below the fit zoom.
  assert.equal(edgeZoom({ ...base, window: [0, 60000], edge: 'right', x: 1000 }).zoom, 9.98);
  assert.equal(edgeZoom({ ...base, viewPx: 1002, window: [0, 60000], edge: 'right', x: 1000 }).zoom, 10);
  // Pointer zoom: the time under the pointer (x 300 of the view at scroll 200, 20 px/s: 25 s) stays put.
  const z = zoomAround({ zoom: 20, factor: 2, anchorPx: 300, scrollLeft: 200, lengthMs: 100000, viewPx: 1000 });
  assert.deepEqual(z, { zoom: 40, scrollLeft: 700 });
  assert.equal(zoomAround({ zoom: 20, factor: 0.01, anchorPx: 300, scrollLeft: 200, lengthMs: 100000, viewPx: 1000 }).zoom, 9.98);
  assert.equal(cubeRanges([1, 2, 3, 4, 5, 6, 7, 8]), '#1-#8');
  assert.equal(cubeRanges([12, 1, 2, 5, 5]), '#1-#2, #5, #12');
});

test('the colour band always shows 16 cube rows: the selection first, then the numbers after it', () => {
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
  assert.deepEqual(bandCubes([17]), range(17, 32));
  assert.deepEqual(bandCubes(range(1, 8)), range(1, 16));
  assert.deepEqual(bandCubes([12, 3]), [12, 3, ...range(13, 26)], 'the selection keeps its order');
  assert.deepEqual(bandCubes([5, 5, 6]), range(5, 20), 'duplicates once');
  assert.deepEqual(bandCubes(range(1, 24)), range(1, 24), 'a longer selection is shown whole');
  assert.deepEqual(bandCubes([65530]), range(65530, 65535), 'never past the last cube number');
  assert.equal(bandFor(16), 96);
});

test('plugged-in cubes are appended to the preview selection once', async () => {
  const { addCubeNumbers } = await import('../lib/showtimeline.js');
  assert.equal(addCubeNumbers('1-8', [1, 2, 3, 4, 5, 6, 7, 8], [17, 3]), '1-8, 17');
  assert.equal(addCubeNumbers('1-8, 17', [1, 2, 3, 4, 5, 6, 7, 8, 17], [17]), '1-8, 17');
  assert.equal(addCubeNumbers('', [], [44, 12, 12]), '12, 44');
  assert.equal(addCubeNumbers('5,', [5], [0, null, 6]), '5, 6');
});
