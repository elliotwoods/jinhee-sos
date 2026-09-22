// NctShowEngine: the compiled-in default show must reproduce the hard-coded timeline of cube
// firmware v1.4.1-USB.2 exactly, and the C++ renderer must agree with pairing_station/showfile.py
// (vectors generated into fixtures.h by run_firmware_tests.py).
#include <cassert>
#include <cstdio>
#include <vector>
#include "NctShowProtocol.h"
#include "fixtures.h"
#include "../../flashing_station/firmware/neocore_usb/DefaultShow.h"

using nctshow::Rgb;

// Deterministic rng, identical to showfile.TestRng and the JS test's.
struct Seq { uint32_t n = 0; };
static uint32_t seqRandom(uint32_t lo, uint32_t hi, void *ctx) {
  Seq *s = static_cast<Seq *>(ctx);
  s->n++;
  return lo + (s->n * 7919u) % (hi - lo);
}

// ---- Verbatim logic of updateMainShowTimeline() from neocore_usb.ino v1.4.1-USB.2 --------------
// (showColor/ledOff replaced by returning the colour; random() by the same rng; millis() by t.)
namespace legacy {
static uint8_t lerp8(uint8_t from, uint8_t to, uint32_t elapsed, uint32_t duration) {
  if (elapsed >= duration) return to;
  int32_t diff = (int32_t)to - (int32_t)from;
  return from + (diff * (int32_t)elapsed / (int32_t)duration);
}
static Rgb fade(uint8_t r1, uint8_t g1, uint8_t b1, uint8_t r2, uint8_t g2, uint8_t b2, uint32_t e, uint32_t d) {
  return Rgb{lerp8(r1, r2, e, d), lerp8(g1, g2, e, d), lerp8(b1, b2, e, d)};
}
static Rgb neon(uint8_t level) {
  if (level > 100) level = 100;
  return Rgb{uint8_t((uint16_t)level * 81 / 100), level, uint8_t((uint16_t)level * 23 / 100)};
}
struct State { bool init = false; uint8_t from = 20, to = 20; uint32_t start = 0, duration = 1000; Seq seq; };
static Rgb randomNeon(State &s, uint32_t now) {
  if (!s.init) {
    s.init = true; s.from = 20; s.to = seqRandom(12, 51, &s.seq); s.start = now; s.duration = seqRandom(700, 1501, &s.seq);
  }
  uint32_t elapsed = now - s.start;
  if (elapsed >= s.duration) {
    s.from = s.to; s.to = seqRandom(12, 51, &s.seq); s.start = now; s.duration = seqRandom(700, 1501, &s.seq); elapsed = 0;
  }
  return neon(lerp8(s.from, s.to, elapsed, s.duration));
}
static Rgb crystal(uint32_t local) {
  const uint32_t segment = 3000;
  uint32_t cycle = local % (segment * 3);
  if (cycle < segment) return fade(17, 17, 18, 11, 16, 18, cycle, segment);
  if (cycle < segment * 2) return fade(11, 16, 18, 18, 12, 12, cycle - segment, segment);
  return fade(18, 12, 12, 17, 17, 18, cycle - segment * 2, segment);
}
// Returns false at the end of the show.
static bool timeline(State &s, uint32_t t, Rgb &out) {
  const Rgb OFF{0, 0, 0}, MAIN{18, 20, 1}, WHITE{20, 20, 20}, WMAX{100, 100, 100};
  if (t < 31000) { out = MAIN; return true; }
  if (t < 36000) { out = OFF; return true; }
  if (t < 60000) { out = (t - 36000) % 1000 < 500 ? WHITE : OFF; return true; }
  if (t < 68000) { out = fade(20, 20, 20, 100, 100, 100, t - 60000, 8000); return true; }
  if (t < 74000) { out = MAIN; return true; }
  if (t < 74300) {
    uint32_t p = t - 74000;
    out = p < 120 ? fade(18, 20, 1, 81, 100, 23, p, 120) : fade(81, 100, 23, 18, 20, 1, p - 120, 180);
    return true;
  }
  if (t < 79000) { out = MAIN; return true; }
  if (t < 114000) { out = crystal(t - 79000); return true; }
  if (t < 119000) { out = fade(17, 17, 18, 100, 100, 100, t - 114000, 5000); return true; }
  if (t < 124000) { out = fade(81, 100, 23, 18, 20, 1, t - 119000, 5000); return true; }
  if (t < 169000) { out = randomNeon(s, t); return true; }
  if (t < 184000) { out = OFF; return true; }
  if (t < 192000) { out = fade(0, 0, 0, 24, 18, 13, t - 184000, 8000); return true; }
  if (t < 221000) { out = fade(24, 18, 13, 0, 0, 0, t - 192000, 29000); return true; }
  if (t < 231000) { out = OFF; return true; }
  if (t < 234000) { out = fade(0, 0, 0, 0, 8, 30, t - 231000, 3000); return true; }
  if (t < 237000) { out = fade(0, 8, 30, 0, 0, 0, t - 234000, 3000); return true; }
  if (t < 277000) { out = OFF; return true; }
  if (t < 287000) { out = fade(0, 0, 0, 20, 20, 20, t - 277000, 10000); return true; }
  if (t < 295000) { out = (t - 287000) % 700 < 120 ? WMAX : WHITE; return true; }
  if (t < 298000) { out = fade(20, 20, 20, 0, 0, 0, t - 295000, 3000); return true; }
  out = OFF;
  return false;
}
}  // namespace legacy

static bool same(Rgb a, Rgb b) { return a.r == b.r && a.g == b.g && a.b == b.b; }

static void compareWithLegacy(uint32_t step) {
  assert(nctshow::validImage(DEFAULT_SHOW, DEFAULT_SHOW_SIZE));
  nctshow::Player player;
  player.begin(DEFAULT_SHOW);
  Seq seq;
  legacy::State state;
  uint32_t frames = 0;
  for (uint32_t t = 0; t < 300000; t += step) {
    Rgb want, got;
    bool running = legacy::timeline(state, t, want);
    bool playing = player.render(t, seqRandom, &seq, got);
    if (running != playing || !same(want, got)) {
      std::fprintf(stderr, "t=%u legacy %d (%u,%u,%u) engine %d (%u,%u,%u)\n", t, running, want.r, want.g, want.b,
                   playing, got.r, got.g, got.b);
      assert(false);
    }
    frames++;
  }
  assert(frames > 1000);
}

int main() {
  // The compiled-in default is today's show, frame for frame (20 ms = the cube's frame interval;
  // odd steps catch boundary and phase arithmetic).
  compareWithLegacy(20);
  compareWithLegacy(7);
  compareWithLegacy(1);
  assert(nctshow::crc32(DEFAULT_SHOW, DEFAULT_SHOW_SIZE) == DEFAULT_SHOW_CRC);
  assert(DEFAULT_SHOW_SIZE == DEFAULT_IMAGE.size() && !memcmp(DEFAULT_SHOW, DEFAULT_IMAGE.data(), DEFAULT_SHOW_SIZE) &&
         "DefaultShow.h is stale: run python pairing_station/showfile.py --header");

  // Cross-engine vectors: every cue type, fanned and not, rendered by showfile.py with the same rng for
  // several cube numbers (0 = unregistered: no offsets).
  assert(nctshow::validImage(VECTOR_IMAGE.data(), VECTOR_IMAGE.size()));
  size_t differing = 0;
  for (const auto &set : VECTOR_SETS) {
    nctshow::Player player;
    player.begin(VECTOR_IMAGE.data(), set.first);
    Seq seq;
    for (size_t i = 0; i < set.second.size(); i++) {
      const auto &v = set.second[i];
      Rgb got;
      bool playing = player.render(v[0], seqRandom, &seq, got);
      if (playing != bool(v[1]) || got.r != v[2] || got.g != v[3] || got.b != v[4]) {
        std::fprintf(stderr, "cube %u vector t=%u want %u (%u,%u,%u) got %d (%u,%u,%u)\n", set.first, v[0], v[1], v[2], v[3],
                     v[4], playing, got.r, got.g, got.b);
        assert(false);
      }
      differing += v != VECTOR_SETS[0].second[i];
    }
  }
  assert(differing > 100 && "fanning changes what numbered cubes show");

  // Fan offsets, spelled out.
  {
    nctshow::Cue c{};
    c.type = nctshow::CUE_BLINK; c.fan = nctshow::FAN_SEQUENTIAL; c.aux = 4; c.params[2] = 250;
    assert(nctshow::fanOffset(c, 0) == 0 && nctshow::fanOffset(c, 1) == 0 && nctshow::fanOffset(c, 2) == 250 &&
           nctshow::fanOffset(c, 4) == 750 && nctshow::fanOffset(c, 5) == 0 && "groups of 4 repeat");
    c.fan = nctshow::FAN_SCATTER; c.aux = 0; c.params[2] = 99;
    assert(nctshow::fanOffset(c, 17) == nctshow::scatter(17) % 100 && nctshow::fanOffset(c, 17) < 100);
  }

  // Validation agrees with showfile.py on images it refuses.
  for (const auto &bad : INVALID_IMAGES) assert(!nctshow::validImage(bad.data(), bad.size()));
  assert(!nctshow::validImage(nullptr, 0));

  // Frame decoding.
  assert(nctshow::frameType(SHOW_ANNOUNCE_V5.data(), SHOW_ANNOUNCE_V5.size()) == nctshow::SHOW_ANNOUNCE);
  for (const auto &chunk : SHOW_CHUNKS_V5) assert(nctshow::frameType(chunk.data(), chunk.size()) == nctshow::SHOW_CHUNK);
  assert(nctshow::frameType(SHOW_QUERY_FRAME.data(), SHOW_QUERY_FRAME.size()) == nctshow::SHOW_QUERY);
  assert(nctshow::frameType(SHOW_TIMECODE_FRAME.data(), SHOW_TIMECODE_FRAME.size()) == nctshow::SHOW_TIMECODE);
  auto timecode = nctshow::makeTimecode(0x11223344, 5000, 7, 0xAABBCCDD);
  assert(sizeof timecode == SHOW_TIMECODE_FRAME.size() && !memcmp(&timecode, SHOW_TIMECODE_FRAME.data(), sizeof timecode));
  std::vector<uint8_t> shortChunk(SHOW_CHUNKS_V5[0].begin(), SHOW_CHUNKS_V5[0].end() - 1);
  assert(!nctshow::frameType(shortChunk.data(), shortChunk.size()));
  uint8_t packet[24] = {'N', 'Z', 1, nctshow::SHOW_TIMECODE};
  assert(!nctshow::frameType(packet, 24) && "a 24-byte frame is always a cube Packet");
  std::printf("ShowEngine OK\n");
}
