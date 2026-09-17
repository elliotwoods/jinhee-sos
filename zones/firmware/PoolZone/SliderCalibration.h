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
  int select(float distance) const {
    if (!valid() || !isfinite(distance)) return -1;
    int nearest = 0;
    for (int i=1; i<23; ++i)
      if (fabsf(distance-mm[i]) < fabsf(distance-mm[nearest])) nearest=i;
    // Use the neighbor on the reading's side (outer edges use their sole neighbor).
    int neighbor = nearest + ((distance-mm[nearest]) * (mm[22]-mm[0]) >= 0 ? 1 : -1);
    if (neighbor < 0) neighbor=1;
    if (neighbor > 22) neighbor=21;
    float tolerance = fabsf(mm[neighbor]-mm[nearest]) * .33f;
    return fabsf(distance-mm[nearest]) <= tolerance + .0001f ? nearest+1 : -1;
  }
};
