// Reference-video sync for the Show editor. Pure decisions (tested in web/tests/showvideo.test.js); the
// editor applies them to its <video> element.
//
// Clocks. The show clock `t` (ms) drives everything the editor draws and mirrors. The video is at
// (t + offset) / 1000 s. While playing, each animation frame:
//   1. The show clock predicts where it should be: free = prev + dt × rate.
//   2. If the video is playing smoothly and covers that moment, the VIDEO IS THE MASTER: the show clock
//      takes the video's position (never stepping backwards, so the per-cube players are not restarted
//      by frame jitter). Audio and picture are never touched, so they cannot stutter.
//   3. If the video disagrees with the prediction by more than DRIFT_MS (the operator scrubbed, a loop
//      wrapped, the rate changed, the video stalled or was not yet playing) the SHOW CLOCK IS THE MASTER:
//      it keeps free-running and the video is sought to it once (then SEEK_COOLDOWN_MS without another
//      seek, so a slow seek cannot start a storm of seeks).
//   4. Before the video's first frame (negative target) or past its end, the show clock free-runs and the
//      panel shows a waiting / ended state.
// While paused or scrubbing the video is paused and sought to the playhead (frame-accurate still).
export const DRIFT_MS = 80;
export const SEEK_COOLDOWN_MS = 300;
export const STILL_TOLERANCE_MS = 25;

// The video position (s) for show time t (ms) with the offset (ms) at which the show's 0:00 sits in the video.
export const videoTarget = (t, offsetMs) => (t + (offsetMs || 0)) / 1000;

// 'before' the video starts, 'in' it, or 'after' its end ('in' while the duration is still unknown).
export function videoPhase(targetSec, duration) {
  if (targetSec < 0) return 'before';
  if (Number.isFinite(duration) && duration > 0 && targetSec >= duration) return 'after';
  return 'in';
}

// One playing frame. `videoMs`: the video's position as show time (currentTime × 1000 − offset) when it is
// playing smoothly inside its range, else null. Returns the new show time and whether to seek the video.
export function clockStep({ prev, dt, rate, videoMs, drift = DRIFT_MS }) {
  const free = prev + Math.max(0, dt) * rate;
  if (videoMs == null) return { t: free, seek: false };
  if (Math.abs(videoMs - free) > drift) return { t: free, seek: true };
  return { t: Math.max(prev, videoMs), seek: false };
}

// Whether a seek may be issued now (not while one is in flight, and not within the cooldown).
export function maySeek(now, lastSeekAt, seeking, cooldown = SEEK_COOLDOWN_MS) {
  return !seeking && (lastSeekAt == null || now - lastSeekAt >= cooldown);
}

// Paused or scrubbing: seek the still frame only when it is visibly off.
export function stillNeedsSeek(videoSec, targetSec, tolerance = STILL_TOLERANCE_MS) {
  return Math.abs(videoSec - targetSec) * 1000 > tolerance;
}

// A dropped or chosen file that looks like a video.
export function isVideoFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith('video/')) return true;
  return /\.(mp4|m4v|mov|webm|mkv|ogv|avi)$/i.test(file.name || '');
}

// The per-file offset kept in localStorage (the file itself is never stored or uploaded).
export const offsetKey = (name) => `nct.show.videoOffset.${name}`;
