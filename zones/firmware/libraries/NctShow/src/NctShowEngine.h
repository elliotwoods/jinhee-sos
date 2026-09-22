#pragma once
// Main show image format and renderer. Header-only and free of Arduino APIs: the neocube
// firmware, the host C++ tests and (by transcription) pairing_station/showfile.py and
// console/web/lib/showengine.js all render the same image the same way. Change all three
// together; run_firmware_tests.py cross-checks them with generated vectors.
//
// An image is an ImageHeader followed by cueCount fixed-size Cues, little-endian. A cue runs
// from its startMs to the next cue's startMs (the last one to lengthMs). At lengthMs the show
// is over: the cube turns its LEDs off and leaves the mainshow zone, as the compiled-in show
// always did. Version and CRC travel beside the image (radio announce, NVS keys), not in it.
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace nctshow {

constexpr uint8_t FORMAT = 1;
constexpr uint16_t MAX_CUES = 128;
constexpr uint32_t MAX_LENGTH_MS = 3600000;  // one hour
constexpr uint8_t LEVEL_MAX = 100;           // the cube's absolute per-channel cap
constexpr uint8_t MAX_COLOURS = 3;

enum CueType : uint8_t {
  CUE_OFF = 0,     // LEDs off
  CUE_SOLID = 1,   // colours[0]
  CUE_FADE = 2,    // colours[0] -> colours[1] over params[0] ms, then holds colours[1]
  CUE_BLINK = 3,   // colours[0] for the first params[1] ms of every params[0] ms period, else colours[1]
  CUE_PULSE = 4,   // colours[0] -> colours[1] over params[0] ms, back over params[1] ms, then colours[0]
  CUE_CYCLE = 5,   // crossfade colours[0] -> [1] -> ... -> [0], params[0] ms per step, looping
  CUE_RANDOM = 6,  // random walk of a level 0..100 scaling colours[0]; each cube differs
};
// CUE_RANDOM packing: params[0] = level_min | level_max << 8, params[1] = dur_min ms,
// params[2] = dur_max ms, aux = start level. A transition goes from the current level to a
// random level in [level_min, level_max] over a random duration in [dur_min, dur_max].
//
// Fanning (FADE, BLINK, PULSE, CYCLE; firmware v1.6.0+): every cube gets the same show and derives
// its own offset from its registered cube number, so a row of cubes can ripple. Cue.fan selects:
//   FAN_SEQUENTIAL: offset = ((cube - 1) % aux) * params[2] ms   (aux = group size 1..255)
//   FAN_SCATTER:    offset = scatter(cube) % (params[2] + 1) ms  (a fixed pseudo-random spread)
// A cube with no number (0) has offset 0. Periodic effects (blink, cycle) are phase-shifted by the
// offset; one-shot effects (fade, pulse) start that much later and hold their first colour until then.
// A v1.5.0 cube refuses a fanned cue (the byte was reserved), so unfanned images are unchanged.

#pragma pack(push, 1)
struct ImageHeader {
  char magic[4];  // "NSHW"
  uint8_t format;
  uint8_t reserved;
  uint16_t cueCount;
  uint32_t lengthMs;
};
struct Cue {
  uint32_t startMs;
  uint8_t type;
  uint8_t nColours;
  uint8_t aux;       // RANDOM: start level; fanned cue: FAN_SEQUENTIAL group size
  uint8_t fan;       // FanMode (was reserved = 0 before v1.6.0)
  uint8_t colours[MAX_COLOURS][3];
  uint8_t pad;
  uint16_t params[3];
};
#pragma pack(pop)
static_assert(sizeof(ImageHeader) == 12, "show image header layout");
static_assert(sizeof(Cue) == 24, "show cue layout");

enum FanMode : uint8_t { FAN_NONE = 0, FAN_SEQUENTIAL = 1, FAN_SCATTER = 2 };

inline bool fannable(uint8_t type) { return type == CUE_FADE || type == CUE_BLINK || type == CUE_PULSE || type == CUE_CYCLE; }

// Deterministic per-cube spread, identical in showfile.py and showengine.js.
inline uint32_t scatter(uint32_t cube) { return (cube * 2654435761u) >> 16; }

constexpr size_t imageSize(uint16_t cues) { return sizeof(ImageHeader) + sizeof(Cue) * size_t(cues); }
constexpr size_t MAX_IMAGE = imageSize(MAX_CUES);

// zlib-compatible CRC-32 (same as nctzone::crc32, repeated so the cube needs no .cpp).
inline uint32_t crc32(const uint8_t *data, size_t len, uint32_t crc = 0) {
  crc = ~crc;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}

inline ImageHeader header(const uint8_t *image) { ImageHeader h; memcpy(&h, image, sizeof h); return h; }
inline Cue cue(const uint8_t *image, uint16_t i) {
  Cue c; memcpy(&c, image + sizeof(ImageHeader) + sizeof(Cue) * size_t(i), sizeof c); return c;
}

inline uint8_t expectedColours(uint8_t type, uint8_t n) {
  switch (type) {
    case CUE_OFF: return 0;
    case CUE_SOLID: case CUE_RANDOM: return 1;
    case CUE_FADE: case CUE_BLINK: case CUE_PULSE: return 2;
    case CUE_CYCLE: return (n >= 1 && n <= MAX_COLOURS) ? n : 0xFF;
    default: return 0xFF;
  }
}

inline bool validCue(const Cue &c) {
  if (c.type > CUE_RANDOM || c.pad || c.fan > FAN_SCATTER) return false;
  if (c.fan && !fannable(c.type)) return false;
  if (expectedColours(c.type, c.nColours) != c.nColours) return false;
  for (int i = 0; i < MAX_COLOURS; i++)
    for (int k = 0; k < 3; k++) {
      if (c.colours[i][k] > LEVEL_MAX) return false;
      if (i >= c.nColours && c.colours[i][k]) return false;
    }
  const uint16_t *p = c.params;
  // Fan fields: FAN_SEQUENTIAL needs a group size (aux) and a step (params[2]); FAN_SCATTER a spread
  // (params[2]) and no aux; no fan, neither.
  if (c.type != CUE_RANDOM) {
    if (c.fan == FAN_SEQUENTIAL ? (!c.aux || !p[2]) : c.fan == FAN_SCATTER ? (c.aux || !p[2]) : (c.aux || p[2])) return false;
  }
  switch (c.type) {
    case CUE_OFF: case CUE_SOLID: return !p[0] && !p[1] && !p[2];
    case CUE_FADE: case CUE_CYCLE: return p[0] && !p[1];
    case CUE_BLINK: return p[0] && p[1] <= p[0];
    case CUE_PULSE: return p[0] && p[1];
    case CUE_RANDOM: {
      uint8_t lo = p[0] & 0xFF, hi = p[0] >> 8;
      return lo <= hi && hi <= LEVEL_MAX && c.aux <= LEVEL_MAX && p[1] && p[1] <= p[2];
    }
  }
  return false;
}

inline bool validImage(const uint8_t *image, size_t len) {
  if (!image || len < sizeof(ImageHeader)) return false;
  ImageHeader h = header(image);
  if (memcmp(h.magic, "NSHW", 4) || h.format != FORMAT || h.reserved) return false;
  if (h.cueCount < 1 || h.cueCount > MAX_CUES || len != imageSize(h.cueCount)) return false;
  if (h.lengthMs < 1 || h.lengthMs > MAX_LENGTH_MS) return false;
  uint32_t previous = 0;
  for (uint16_t i = 0; i < h.cueCount; i++) {
    Cue c = cue(image, i);
    if (i == 0 ? c.startMs != 0 : c.startMs <= previous) return false;
    if (c.startMs >= h.lengthMs || !validCue(c)) return false;
    previous = c.startMs;
  }
  return true;
}

// Integer interpolation exactly as the original cube firmware: truncates toward zero.
inline uint8_t lerp8(uint8_t from, uint8_t to, uint32_t elapsed, uint32_t duration) {
  if (elapsed >= duration) return to;
  int32_t diff = int32_t(to) - int32_t(from);
  return uint8_t(from + diff * int32_t(elapsed) / int32_t(duration));
}

struct Rgb { uint8_t r, g, b; };

inline Rgb colour(const Cue &c, int i) { return Rgb{c.colours[i][0], c.colours[i][1], c.colours[i][2]}; }
inline Rgb fade(Rgb a, Rgb b, uint32_t elapsed, uint32_t duration) {
  return Rgb{lerp8(a.r, b.r, elapsed, duration), lerp8(a.g, b.g, elapsed, duration), lerp8(a.b, b.b, elapsed, duration)};
}
inline Rgb scaled(Rgb c, uint8_t level) {
  if (level > LEVEL_MAX) level = LEVEL_MAX;
  return Rgb{uint8_t(uint16_t(level) * c.r / 100), uint8_t(uint16_t(level) * c.g / 100), uint8_t(uint16_t(level) * c.b / 100)};
}

// Returns a value in [lo, hiExclusive). The cube passes Arduino random(); tests pass a fixed sequence.
typedef uint32_t (*RandomFn)(uint32_t lo, uint32_t hiExclusive, void *ctx);

// Renders one valid image. Holds only the random-walk state, which restart() clears at every
// show start (the original firmware reset it in startMainShow).
// This cube's offset for a cue, in ms.
inline uint32_t fanOffset(const Cue &c, uint32_t cube) {
  if (!cube || !c.fan) return 0;
  if (c.fan == FAN_SEQUENTIAL) return ((cube - 1) % c.aux) * uint32_t(c.params[2]);
  return scatter(cube) % (uint32_t(c.params[2]) + 1);
}

class Player {
 public:
  // `cube`: this cube's registered number (0 = none), which sets its fanning offsets.
  void begin(const uint8_t *image, uint32_t cube = 0) { image_ = image; header_ = header(image); cube_ = cube; restart(); }
  void setCube(uint32_t cube) { cube_ = cube; }
  uint32_t cube() const { return cube_; }
  void restart() { randomCue_ = -1; }
  uint32_t lengthMs() const { return header_.lengthMs; }
  uint16_t cueCount() const { return header_.cueCount; }

  int cueAt(uint32_t t) const {
    int found = 0;
    for (uint16_t i = 1; i < header_.cueCount; i++) {
      if (cue(image_, i).startMs > t) break;
      found = i;
    }
    return found;
  }

  // False once t reaches the show length (the caller ends the show); out is then black.
  bool render(uint32_t t, RandomFn rng, void *ctx, Rgb &out) {
    out = Rgb{0, 0, 0};
    if (!image_ || t >= header_.lengthMs) return false;
    int index = cueAt(t);
    Cue c = cue(image_, uint16_t(index));
    uint32_t local = t - c.startMs;
    const uint16_t *p = c.params;
    uint32_t offset = fanOffset(c, cube_);
    // One-shot effects wait for the offset (holding their first colour); periodic ones shift phase.
    uint32_t delayed = local > offset ? local - offset : 0;
    switch (c.type) {
      case CUE_OFF: break;
      case CUE_SOLID: out = colour(c, 0); break;
      case CUE_FADE: out = fade(colour(c, 0), colour(c, 1), delayed, p[0]); break;
      case CUE_BLINK: out = ((local + p[0] - offset % p[0]) % p[0]) < p[1] ? colour(c, 0) : colour(c, 1); break;
      case CUE_PULSE:
        if (delayed < p[0]) out = fade(colour(c, 0), colour(c, 1), delayed, p[0]);
        else out = fade(colour(c, 1), colour(c, 0), delayed - p[0], p[1]);
        break;
      case CUE_CYCLE: {
        uint32_t period = uint32_t(p[0]) * c.nColours;
        uint32_t cycle = (local + period - offset % period) % period;
        uint32_t step = cycle / p[0];
        out = fade(colour(c, int(step)), colour(c, int((step + 1) % c.nColours)), cycle - step * p[0], p[0]);
        break;
      }
      case CUE_RANDOM: out = scaled(colour(c, 0), randomLevel(c, index, t, rng, ctx)); break;
    }
    return true;
  }

 private:
  uint8_t randomLevel(const Cue &c, int index, uint32_t t, RandomFn rng, void *ctx) {
    uint8_t lo = c.params[0] & 0xFF, hi = c.params[0] >> 8;
    if (randomCue_ != index) {
      randomCue_ = index;
      from_ = c.aux;
      to_ = uint8_t(rng(lo, uint32_t(hi) + 1, ctx));
      start_ = t;
      duration_ = rng(c.params[1], uint32_t(c.params[2]) + 1, ctx);
    }
    uint32_t elapsed = t - start_;  // a backwards jump wraps to a large value: a new transition
    if (elapsed >= duration_) {
      from_ = to_;
      to_ = uint8_t(rng(lo, uint32_t(hi) + 1, ctx));
      start_ = t;
      duration_ = rng(c.params[1], uint32_t(c.params[2]) + 1, ctx);
      elapsed = 0;
    }
    return lerp8(from_, to_, elapsed, duration_);
  }

  const uint8_t *image_ = nullptr;
  ImageHeader header_{};
  uint32_t cube_ = 0;
  int randomCue_ = -1;
  uint8_t from_ = 0, to_ = 0;
  uint32_t start_ = 0, duration_ = 1;
};

}  // namespace nctshow
