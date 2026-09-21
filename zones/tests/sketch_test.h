#pragma once
// Zone-board helpers: the generic ones plus those that need the cube Packet and the
// generated database fixtures. Include after the sketch.
#include "sketch_common.h"
#include "fixtures.h"

static void image(const char *label, const std::vector<uint8_t> &data) {
  auto *p = fakePartition(label);
  std::fill(p->data->begin(), p->data->end(), 0xFF);
  std::copy(data.begin(), data.end(), p->data->begin());
}

static nctzone::ZoneStatus queryStatus() {
  size_t before = sentFrames.size();
  radio(FRAME_QUERY_STATUS);
  run(400);
  nctzone::ZoneStatus s = {};
  bool ok = false;
  for (size_t i = before; i < sentFrames.size(); i++)
    if (!memcmp(sentFrames[i].dest.data(), REGISTRY, 6) &&
        nctzone::frameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) == nctzone::ZONE_STATUS) {
      memcpy(&s, sentFrames[i].data.data(), sizeof(s));
      ok = true;
    }
  assert(ok && "no status reply");
  return s;
}

// The ZONE_SETTINGS frame that follows each status reply (latest one sent since `from`).
static nctzone::ZoneSettings lastSettings(size_t from = 0) {
  nctzone::ZoneSettings m = {};
  bool ok = false;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (nctzone::frameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) == nctzone::ZONE_SETTINGS) {
      memcpy(&m, sentFrames[i].data.data(), sizeof(m));
      ok = true;
    }
  assert(ok && "no settings frame");
  return m;
}

static Packet cubePacket(const SentFrame &frame) {
  assert(frame.data.size() == sizeof(Packet));
  Packet p;
  memcpy(&p, frame.data.data(), sizeof(p));
  return p;
}
