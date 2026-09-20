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
  auto replies = framesTo(REGISTRY, before);
  assert(!replies.empty() && replies.back().data.size() == sizeof(nctzone::ZoneStatus));
  nctzone::ZoneStatus s;
  memcpy(&s, replies.back().data.data(), sizeof(s));
  return s;
}

static Packet cubePacket(const SentFrame &frame) {
  assert(frame.data.size() == sizeof(Packet));
  Packet p;
  memcpy(&p, frame.data.data(), sizeof(p));
  return p;
}
