// Local (non-wire) types for the range test sketch. These live in a header
// because the Arduino preprocessor injects function prototypes at the top of
// the .ino, before any struct declared in the sketch body would be visible.
#pragma once
#include <stdint.h>
#include "RangeTestPacket.h"

// Declared here, ahead of the prototypes the Arduino preprocessor injects, so
// the format attribute is in scope for every call site. Without it a mismatched
// argument list silently shifts every field after the mistake, which is how a
// STAT line ends up full of plausible-looking wrong numbers.
void logLine(const char *format, ...) __attribute__((format(printf, 1, 2)));

// One received frame, with everything copied out of the driver's short-lived
// esp_now_recv_info_t. The callback stores these; the main loop consumes them.
struct RxEvent {
  rangetest::RangeTestPacket packet;
  uint8_t src[6];
  int8_t rssi;
  int8_t noiseFloor;
  uint8_t channel;
  uint32_t rxMicros;
  uint32_t rxMillis;
};

// Default role for a known board, resolved from the Wi-Fi MAC at boot.
struct RoleDefault {
  uint8_t mac[6];
  uint8_t role;
};

// Rolling min/mean/max over a reporting window. RSSI_UNKNOWN samples are skipped
// so an unmeasured frame never drags the average toward zero.
struct RssiStats {
  int32_t sum = 0;
  int16_t min = 0, max = 0;
  uint32_t count = 0;

  void add(int8_t value) {
    if (value == rangetest::RSSI_UNKNOWN) return;
    if (count == 0 || value < min) min = value;
    if (count == 0 || value > max) max = value;
    sum += value;
    ++count;
  }
  void reset() {
    sum = 0;
    min = 0;
    max = 0;
    count = 0;
  }
  float average() const { return count ? float(sum) / float(count) : 0.0f; }
};
