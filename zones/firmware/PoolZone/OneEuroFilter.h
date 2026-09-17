#pragma once
#include <math.h>
#include <stdint.h>

// Casiez et al., CHI 2012: https://gery.casiez.net/1euro/
// Distance in mm; speed in mm/s. Uses actual elapsed time (NFC polling is variable).
class OneEuroFilter {
 public:
  static constexpr float MIN_CUTOFF_HZ = 0.8f;
  static constexpr float BETA = 0.03f;  // Hz per mm/s
  static constexpr float DERIVATIVE_CUTOFF_HZ = 1.0f;
  void reset() { initialized_ = false; }
  float update(float raw, uint32_t now) {
    if (!isfinite(raw)) { reset(); return NAN; }
    uint32_t elapsed = now - previousTime_;
    if (!initialized_ || elapsed > 400) {
      initialized_ = true;
      previousTime_ = now;
      previousRaw_ = filtered_ = raw;
      speed_ = 0;
      return raw;
    }
    if (!elapsed) return filtered_;
    float dt = elapsed / 1000.0f;
    float derivative = (raw - previousRaw_) / dt;
    speed_ += alpha(DERIVATIVE_CUTOFF_HZ, dt) * (derivative - speed_);
    float cutoff = MIN_CUTOFF_HZ + BETA * fabsf(speed_);
    filtered_ += alpha(cutoff, dt) * (raw - filtered_);
    previousRaw_ = raw;
    previousTime_ = now;
    return filtered_;
  }
 private:
  static float alpha(float cutoff, float dt) {
    float r = 6.28318530718f * cutoff * dt;
    return r / (1.0f + r);
  }
  bool initialized_ = false;
  uint32_t previousTime_ = 0;
  float previousRaw_ = 0, filtered_ = 0, speed_ = 0;
};
