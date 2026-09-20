#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>

// Slider filtering and position-decision parameters, stored as one versioned NVS blob
// beside the calibration (namespace "pool-slider", key "tune-v1").
//
// Written to flash only by an explicit TUNE SAVE. The firmware updater verifies the nvs
// partition is unchanged across an application update, and nothing here may write on boot.
//
// Defaults deliberately keep pool-2.7.0's filter and sensor timing. Only the parameters
// that fix an outright defect differ: 2.7.0 released a member on a single disagreeing
// sample and on a single invalid sensor reading, which is what made relays flicker.
// Filter strength and sensor timing are left to be tuned against recorded data rather
// than changed blind, since smoothing trades directly against responsiveness.
struct SliderTuning {
  float minCutoffHz = 0.8f;         // One Euro cutoff at rest (2.7.0 value)
  float beta = 0.03f;               // Hz per mm/s (2.7.0 value)
  float derivativeCutoffHz = 1.0f;  // One Euro speed cutoff (2.7.0 value)
  float enterFrac = 0.33f;          // acceptance window to enter a member (2.7.0 value)
  float exitFrac = 0.45f;           // wider window to keep one: distance hysteresis
  uint16_t confirmMs = 50;          // stability required to enter (2.7.0 value)
  uint16_t releaseMs = 120;         // persistent disagreement required to leave
  uint16_t dropoutMs = 400;         // invalid readings tolerated before releasing
  uint16_t timingBudgetMs = 20;     // VL53L4CD budget, 10..200 (2.7.0 value)
  uint16_t intervalMs = 0;          // inter-measurement period, 0 = continuous
  uint8_t medianWindow = 3;         // raw median prefilter, odd, 1..9; 1 disables
  uint8_t reserved = 0;             // keeps the blob layout stable

  static bool inRange(float v, float lo, float hi) { return isfinite(v) && v >= lo && v <= hi; }

  bool valid() const {
    // enterFrac above 0.5 would make adjacent acceptance windows overlap.
    // exitFrac below enterFrac would invert the hysteresis; at or above 1.0 a held
    // member's window would swallow the neighbouring tick and could never be released.
    return inRange(minCutoffHz, .05f, 20.f) && inRange(beta, 0.f, 5.f) &&
           inRange(derivativeCutoffHz, .05f, 20.f) &&
           inRange(enterFrac, .05f, .5f) && inRange(exitFrac, enterFrac, .9f) &&
           confirmMs <= 1000 && releaseMs <= 1000 && dropoutMs >= 50 && dropoutMs <= 1000 &&
           timingBudgetMs >= 10 && timingBudgetMs <= 200 &&
           // VL53L4CD::setRangeTiming requires 0 or strictly above the budget.
           (intervalMs == 0 || intervalMs > timingBudgetMs) &&
           medianWindow >= 1 && medianWindow <= 9 && (medianWindow & 1);
  }

  // Poll at half the sensor period. Polling at exactly the sensor rate aliases: a poll
  // landing just before dataReady() costs a whole extra period and hands One Euro a
  // doubled dt. Never 0 — the I2C bus is shared with the PN532 and this is called
  // twice per loop().
  uint16_t pollIntervalMs() const {
    uint16_t period = intervalMs ? intervalMs : timingBudgetMs;
    return period > 4 ? uint16_t(period / 2) : uint16_t(2);
  }

  // Backstop for a sensor that stops delivering readings altogether, where the
  // per-sample dropout path never runs. Always above dropoutMs so that parameter
  // cannot be made inert by this watchdog firing first.
  uint32_t staleMs() const { return uint32_t(dropoutMs) + 150; }
};
static_assert(sizeof(SliderTuning) == 32, "tune-v1 blob layout changed; bump the key");
