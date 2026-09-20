#pragma once
#include <math.h>
#include <stdint.h>

// Median of the last N raw readings, ahead of the One Euro stage. An EMA cannot reject
// a single wild VL53L4CD sample; a short median can, without adding steady-state lag.
class MedianFilter {
 public:
  static constexpr uint8_t MAX_WINDOW = 9;
  void configure(uint8_t window) {
    if (window < 1) window = 1;
    if (window > MAX_WINDOW) window = MAX_WINDOW;
    if (!(window & 1)) --window;  // an even window has no single middle sample
    if (window != window_) { window_ = window; reset(); }
  }
  void reset() { count_ = 0; next_ = 0; }
  uint8_t window() const { return window_; }
  float update(float raw) {
    if (!isfinite(raw)) return raw;
    ring_[next_] = raw;
    next_ = uint8_t((next_ + 1) % window_);
    if (count_ < window_) ++count_;
    if (count_ < 2) return raw;
    float sorted[MAX_WINDOW];
    for (uint8_t i = 0; i < count_; ++i) sorted[i] = ring_[i];
    for (uint8_t i = 1; i < count_; ++i) {  // insertion sort; count_ <= 9
      float v = sorted[i];
      int8_t j = int8_t(i) - 1;
      while (j >= 0 && sorted[j] > v) { sorted[j+1] = sorted[j]; --j; }
      sorted[j+1] = v;
    }
    // While the ring is still filling, an even count has no middle sample: average the
    // two central values rather than biasing consistently to one side.
    return (count_ & 1) ? sorted[count_/2] : (sorted[count_/2 - 1] + sorted[count_/2]) * 0.5f;
  }

 private:
  uint8_t window_ = 1, count_ = 0, next_ = 0;
  float ring_[MAX_WINDOW] = {};
};

// Casiez et al., CHI 2012: https://gery.casiez.net/1euro/
// Distance in mm; speed in mm/s. Uses actual elapsed time (NFC polling is variable).
class OneEuroFilter {
 public:
  static constexpr float MIN_CUTOFF_HZ = 0.8f;
  static constexpr float BETA = 0.03f;  // Hz per mm/s
  static constexpr float DERIVATIVE_CUTOFF_HZ = 1.0f;
  static constexpr uint32_t GAP_MS = 400;
  // Tuning is applied live; changing cutoffs must not discard filter history.
  void configure(float minCutoff, float beta, float derivativeCutoff, uint32_t gapMs = GAP_MS) {
    if (isfinite(minCutoff) && minCutoff > 0) minCutoff_ = minCutoff;
    if (isfinite(beta) && beta >= 0) beta_ = beta;
    if (isfinite(derivativeCutoff) && derivativeCutoff > 0) derivativeCutoff_ = derivativeCutoff;
    gapMs_ = gapMs ? gapMs : GAP_MS;
  }
  void reset() { initialized_ = false; }
  float update(float raw, uint32_t now) {
    if (!isfinite(raw)) { reset(); return NAN; }
    uint32_t elapsed = now - previousTime_;
    if (!initialized_ || elapsed > gapMs_) {
      initialized_ = true;
      previousTime_ = now;
      previousRaw_ = filtered_ = raw;
      speed_ = 0;
      return raw;
    }
    if (!elapsed) return filtered_;
    float dt = elapsed / 1000.0f;
    float derivative = (raw - previousRaw_) / dt;
    speed_ += alpha(derivativeCutoff_, dt) * (derivative - speed_);
    float cutoff = minCutoff_ + beta_ * fabsf(speed_);
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
  uint32_t previousTime_ = 0, gapMs_ = GAP_MS;
  float minCutoff_ = MIN_CUTOFF_HZ, beta_ = BETA, derivativeCutoff_ = DERIVATIVE_CUTOFF_HZ;
  float previousRaw_ = 0, filtered_ = 0, speed_ = 0;
};
