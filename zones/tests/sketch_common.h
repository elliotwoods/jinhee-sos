#pragma once
// Helpers usable by any host sketch test, including sketches that are not zone boards and
// therefore know nothing about the cube Packet or the zone database. Include after the
// sketch. Zone-board tests include sketch_test.h instead, which adds the zone-only helpers.
#include "zone_stubs.h"

static const uint8_t REGISTRY[6] = {0x3C, 0x0F, 0x02, 0xAD, 0x83, 0x24};
static const uint8_t SELF[6] = {0x02, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE};
static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

void setup();
void loop();

static void run(uint32_t ms) {
  uint32_t end = fakeNow + ms;
  while (fakeNow < end) {
    uint32_t before = fakeNow;
    loop();
    if (fakeNow == before) fakeNow++;  // sketches without delay() still advance time
  }
}

static std::vector<SentFrame> framesTo(const uint8_t *mac, size_t from = 0) {
  std::vector<SentFrame> out;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (!memcmp(sentFrames[i].dest.data(), mac, 6)) out.push_back(sentFrames[i]);
  return out;
}

static void radioFrom(const uint8_t *source, const uint8_t *frame, size_t length, bool broadcast = true) {
  uint8_t src[6], dst[6];
  memcpy(src, source, 6);
  memcpy(dst, broadcast ? BROADCAST : SELF, 6);
  esp_now_recv_info_t info{src, dst};
  recvCallback(&info, frame, int(length));
}

static void radio(const std::vector<uint8_t> &frame, bool broadcast = true) {
  radioFrom(REGISTRY, frame.data(), frame.size(), broadcast);
}

static std::string serial(const char *line, uint32_t ms = 20) {
  Serial.output.clear();
  Serial.input = std::string(line) + "\n";
  run(ms);
  return Serial.output;
}

static bool has(const std::string &text, const char *needle) { return text.find(needle) != std::string::npos; }
