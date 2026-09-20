#pragma once
#include <math.h>
#include <stdint.h>

// Stored as one versioned NVS blob. Indexes follow physical order in either direction.
struct SliderCalibration {
  float mm[23] = {};
  uint32_t anchors = (1u << 22) | 1u;
  bool valid() const {
    if (anchors > 0x7fffff || !(anchors & 1) || !(anchors & (1u<<22))) return false;
    const bool ascending = mm[22] > mm[0];
    for (int i=0; i<23; ++i) {
      if (!isfinite(mm[i]) || mm[i] < 10 || mm[i] > 1000) return false;
      if (i && (ascending ? mm[i]-mm[i-1] : mm[i-1]-mm[i]) < 1.0f) return false;
    }
    return true;
  }
  // Tolerance around tick `index` (0-based), toward the neighbor on the reading's side
  // (outer edges use their sole neighbor). Uses the local step, so uneven calibrations
  // get a window proportional to their own spacing.
  float window(int index, float distance, float frac) const {
    int neighbor = index + ((distance-mm[index]) * (mm[22]-mm[0]) >= 0 ? 1 : -1);
    if (neighbor < 0) neighbor=1;
    if (neighbor > 22) neighbor=21;
    return fabsf(mm[neighbor]-mm[index]) * frac;
  }
  // Hysteresis: `held` (1-based, or -1) is the member currently confirmed, and keeps a
  // wider window than it needed to be entered, so noise at a window edge cannot toggle
  // the output. The held member's own window is tested FIRST: testing the nearest tick
  // first would cap exitFrac at 0.5, because past the midpoint the neighbor becomes
  // nearest and the widening would silently stop applying.
  // exitFrac < 1 guarantees the window never reaches the adjacent tick's centre, so a
  // held member can always be released by moving onto its neighbour.
  int select(float distance, int held, float enterFrac, float exitFrac) const {
    if (!valid() || !isfinite(distance)) return -1;
    if (!(enterFrac > 0) || enterFrac > .5f) enterFrac = .33f;
    if (!(exitFrac >= enterFrac)) exitFrac = enterFrac;  // never anti-hysteresis
    if (exitFrac > .9f) exitFrac = .9f;                  // never un-releasable
    if (held >= 1 && held <= 23 && fabsf(distance-mm[held-1]) <= window(held-1, distance, exitFrac) + .0001f)
      return held;
    int nearest = 0;
    for (int i=1; i<23; ++i)
      if (fabsf(distance-mm[i]) < fabsf(distance-mm[nearest])) nearest=i;
    return fabsf(distance-mm[nearest]) <= window(nearest, distance, enterFrac) + .0001f ? nearest+1 : -1;
  }
  // Symmetric +/-33% form with no member held: the original mapping.
  int select(float distance) const { return select(distance, -1, .33f, .33f); }
};
