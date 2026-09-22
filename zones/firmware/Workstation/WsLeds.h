#pragma once
// Status on the ex-cube's eight WS2812s (XIAO D10 = GPIO10), as the Mainshow controller shows
// it: a faint scroll while waiting (red: no host, green: a host is holding the lease), a strong
// green scroll while a main show it triggered should be running, and a colour cycle for
// `led_test`, a bench check that every pixel and channel is alive.
#include <Adafruit_NeoPixel.h>

namespace ws {
namespace leds {

constexpr int LED_PIN = 10;
constexpr int LED_COUNT = 8;
constexpr uint8_t WAIT_LEVEL = 12, RUN_LEVEL = 100;  // the cube caps its LEDs at 100 of 255
constexpr uint32_t WAIT_PIXEL_MS = 180, RUN_PIXEL_MS = 60;
constexpr uint32_t SCROLL_TAIL = 3;
constexpr uint32_t LED_FRAME_MS = 20;
constexpr uint8_t LED_LEVEL = 60;  // led_test
constexpr uint32_t LED_COLOUR_MS = 1000, LED_CHASE_MS = 250;

inline Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
inline bool ledTest = false;
inline uint32_t ledStep = 0, ledStepAt = 0, ledFrameAt = 0;

// One step of the test cycle: red, green, blue, white (whole strip, 1 s each), then each pixel
// alone in white (250 ms each).
inline void showLedStep(uint32_t step) {
  pixels.clear();
  const uint8_t L = LED_LEVEL;
  static const uint8_t COLOURS[4][3] = {{L, 0, 0}, {0, L, 0}, {0, 0, L}, {L, L, L}};
  if (step < 4) {
    for (int i = 0; i < LED_COUNT; i++) pixels.setPixelColor(i, COLOURS[step][0], COLOURS[step][1], COLOURS[step][2]);
  } else {
    pixels.setPixelColor(int(step - 4), L, L, L);
  }
  pixels.show();
}

// A head moving round the ring with a fading tail, positioned in 1/256 pixel steps so it glides.
inline void drawScroll(uint32_t now, uint8_t red, uint8_t green, uint32_t pixelMs) {
  const uint32_t ring = LED_COUNT * 256, tail = SCROLL_TAIL * 256;
  uint32_t head = uint32_t((uint64_t(now) * 256 / pixelMs) % ring);
  for (int i = 0; i < LED_COUNT; i++) {
    uint32_t behind = (head + ring - uint32_t(i) * 256) % ring;
    uint32_t scale = behind < tail ? tail - behind : 0;
    pixels.setPixelColor(i, uint8_t(red * scale / tail), uint8_t(green * scale / tail), 0);
  }
  pixels.show();
}

inline void poll(uint32_t now, bool hostFresh, bool showRunning) {
  if (!ledTest) {
    if (uint32_t(now - ledFrameAt) < LED_FRAME_MS) return;
    ledFrameAt = now;
    if (showRunning) drawScroll(now, 0, RUN_LEVEL, RUN_PIXEL_MS);
    else if (hostFresh) drawScroll(now, 0, WAIT_LEVEL, WAIT_PIXEL_MS);
    else drawScroll(now, WAIT_LEVEL, 0, WAIT_PIXEL_MS);
    return;
  }
  uint32_t hold = ledStep < 4 ? LED_COLOUR_MS : LED_CHASE_MS;
  if (uint32_t(now - ledStepAt) < hold) return;
  ledStep = (ledStep + 1) % (4 + LED_COUNT);
  ledStepAt = now;
  showLedStep(ledStep);
}

inline void setTest(bool on) {
  ledTest = on;
  ledStep = 0;
  ledStepAt = millis();
  ledFrameAt = 0;
  if (on) showLedStep(0);  // off: the status scroll resumes on the next frame
}

inline void begin() {
  pixels.begin();
  pixels.clear();
  pixels.show();  // WS2812s keep their last colour through a reflash: clear it before the status scroll
}

}  // namespace leds
}  // namespace ws
