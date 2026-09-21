// Preshow wire format: layout, framing and the sequence filter the bridge depends on.
// Deliberately includes nothing but the header: NctPreshowProtocol.h must stay free of
// Arduino dependencies so both sketches and the host tests share one definition.
#include "NctPreshowProtocol.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <vector>

using namespace nctzone;

static std::vector<uint8_t> bytesOf(const void *p, size_t n) {
  std::vector<uint8_t> out(n);
  memcpy(out.data(), p, n);
  return out;
}

static const uint8_t PLATE_A[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x0A};
static const uint8_t PLATE_B[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x0B};

static PreshowEvent makeEvent(uint8_t point, uint8_t state, uint16_t seq, uint32_t bootId) {
  PreshowEvent e = {};
  fillHeader(e.h, PRESHOW_EVENT);
  e.bootId = bootId;
  e.seq = seq;
  e.pointId = point;
  e.state = state;
  return e;
}

int main() {
  // ---- Field offsets are the wire contract; both ends memcpy whole structs. ----
  static_assert(sizeof(Header) == 4, "header");
  static_assert(offsetof(PreshowEvent, bootId) == 4, "bootId offset");
  static_assert(offsetof(PreshowEvent, seq) == 8, "seq offset");
  static_assert(offsetof(PreshowEvent, pointId) == 10, "pointId offset");
  static_assert(offsetof(PreshowEvent, state) == 11, "state offset");
  static_assert(offsetof(PreshowEvent, uid) == 13, "uid offset");
  static_assert(offsetof(PreshowAck, bootId) == 4, "ack bootId offset");
  static_assert(offsetof(PreshowAck, seq) == 8, "ack seq offset");
  static_assert(offsetof(PreshowBeacon, epoch) == 4, "epoch offset");
  static_assert(offsetof(PreshowBeacon, pointMask) == 12, "pointMask offset");

  // ---- Framing ----
  PreshowEvent e = makeEvent(2, 1, 7, 0xABCD1234);
  auto frame = bytesOf(&e, sizeof(e));
  assert(preshowFrameType(frame.data(), int(frame.size())) == PRESHOW_EVENT);
  // Never routed by the zone dispatcher, and never mistaken for a pool frame.
  assert(frameType(frame.data(), int(frame.size())) == 0);
  assert(poolFrameType(frame.data(), int(frame.size())) == 0);

  PreshowAck a = {};
  fillHeader(a.h, PRESHOW_ACK);
  a.bootId = e.bootId; a.seq = e.seq; a.pointId = e.pointId; a.flags = PRESHOW_ACK_APPLIED;
  auto ack = bytesOf(&a, sizeof(a));
  assert(preshowFrameType(ack.data(), int(ack.size())) == PRESHOW_ACK);
  assert(frameType(ack.data(), int(ack.size())) == 0 && poolFrameType(ack.data(), int(ack.size())) == 0);

  PreshowBeacon b = {};
  fillHeader(b.h, PRESHOW_BEACON);
  b.epoch = 0x12345678; b.pointMask = 0b0101; b.version = PRESHOW_PROTOCOL_VERSION;
  auto beacon = bytesOf(&b, sizeof(b));
  assert(preshowFrameType(beacon.data(), int(beacon.size())) == PRESHOW_BEACON);
  assert(frameType(beacon.data(), int(beacon.size())) == 0);
  assert(poolFrameType(beacon.data(), int(beacon.size())) == 0);

  // A pool frame is not a preshow frame either: both directions of the guard matter.
  PoolState pool = {};
  fillHeader(pool.h, POOL_STATE);
  auto poolFrame = bytesOf(&pool, sizeof(pool));
  assert(preshowFrameType(poolFrame.data(), int(poolFrame.size())) == 0);

  // Wrong length, wrong magic, wrong proto and truncation are all rejected.
  assert(preshowFrameType(frame.data(), int(frame.size()) - 1) == 0);
  assert(preshowFrameType(frame.data(), int(frame.size()) + 1) == 0);
  assert(preshowFrameType(ack.data(), int(frame.size())) == 0);
  assert(preshowFrameType(nullptr, int(frame.size())) == 0);
  assert(preshowFrameType(frame.data(), 3) == 0);
  for (size_t i = 0; i < 3; ++i) {
    auto bad = frame; bad[i] ^= 0xFF;
    assert(preshowFrameType(bad.data(), int(bad.size())) == 0);
  }
  auto unknownType = frame; unknownType[3] = 0x77;
  assert(preshowFrameType(unknownType.data(), int(unknownType.size())) == 0);

  // The legacy two-byte packet is not a preshow frame; the bridge matches it by length.
  std::vector<uint8_t> legacy{2, 1};
  assert(preshowFrameType(legacy.data(), int(legacy.size())) == 0);
  assert(frameType(legacy.data(), int(legacy.size())) == 0);
  assert(poolFrameType(legacy.data(), int(legacy.size())) == 0);

  // ---- Validation ----
  assert(preshowEventValid(e));
  PreshowEvent bad = e; bad.pointId = 0;                       assert(!preshowEventValid(bad));
  bad = e; bad.pointId = PRESHOW_POINT_COUNT + 1;              assert(!preshowEventValid(bad));
  bad = e; bad.state = 2;                                      assert(!preshowEventValid(bad));
  bad = e; bad.uidLength = 8;                                  assert(!preshowEventValid(bad));
  assert(!preshowPointValid(0) && preshowPointValid(1) && preshowPointValid(PRESHOW_POINT_COUNT));
  assert(!preshowPointValid(PRESHOW_POINT_COUNT + 1));
  assert(preshowPointBit(1) == 1 && preshowPointBit(4) == 8 && preshowPointBit(0) == 0);
  assert(preshowPointBit(PRESHOW_POINT_COUNT + 1) == 0);

  // ---- Sequence filter ----
  PreshowSender senders[PRESHOW_SENDER_COUNT] = {};
  uint32_t now = 1000;
  PreshowSender *sa = preshowSenderFor(senders, PLATE_A, now);
  assert(sa && preshowAccept(*sa, makeEvent(2, 1, 1, 0xA1), now) && sa->state == 1 && sa->pointId == 2);
  // A retransmission of the same edge is a duplicate: not applied, but it still proves the
  // plate is alive, so the freshness stamp moves.
  now += 120;
  assert(!preshowAccept(*sa, makeEvent(2, 1, 1, 0xA1), now) && sa->seen == now);
  // So does a frame overtaken by a newer one.
  assert(preshowAccept(*sa, makeEvent(2, 0, 2, 0xA1), now) && sa->state == 0);
  assert(!preshowAccept(*sa, makeEvent(2, 1, 1, 0xA1), now) && sa->state == 0);
  // A malformed frame is never accepted, whatever its sequence.
  assert(!preshowAccept(*sa, makeEvent(9, 1, 3, 0xA1), now) && sa->seq == 2);

  // Wraparound across 65535 while the plate keeps being heard from.
  sa->seq = 65534;
  assert(preshowAccept(*sa, makeEvent(2, 1, 65535, 0xA1), now));
  assert(preshowAccept(*sa, makeEvent(2, 0, 0, 0xA1), now) && sa->seq == 0);
  assert(preshowAccept(*sa, makeEvent(2, 1, 1, 0xA1), now) && sa->seq == 1);
  // A far-forward jump is indistinguishable from going backwards, and is rejected.
  assert(!preshowAccept(*sa, makeEvent(2, 0, 40001, 0xA1), now) && sa->seq == 1);

  // A rebooted plate restarts at a low sequence with a fresh bootId, and is taken at once:
  // without this escape its own past would lock it out for the rest of the show.
  assert(preshowAccept(*sa, makeEvent(2, 1, 1, 0xB2), now) && sa->bootId == 0xB2);
  // A plate silent longer than the stale window is let back in whatever it carries, because
  // its old sequence means nothing any more.
  sa->seq = 5000;
  assert(!preshowAccept(*sa, makeEvent(2, 0, 2, 0xB2), now));
  now += PRESHOW_SENDER_STALE_MS + 1;
  assert(preshowAccept(*sa, makeEvent(2, 0, 2, 0xB2), now) && sa->state == 0);

  // ---- Entries are keyed by address, never by the point a board claims ----
  PreshowSender *sb = preshowSenderFor(senders, PLATE_B, now);
  assert(sb && sb != sa);
  assert(preshowAccept(*sb, makeEvent(2, 1, 1, 0xC3), now) && sa->state == 0 && sb->state == 1);
  assert(preshowSenderFor(senders, PLATE_A, now) == sa && preshowSenderFor(senders, PLATE_B, now) == sb);
  // Both call themselves point 2, which is a misconfiguration worth reporting even though
  // the filter itself is unharmed.
  assert(preshowPointClashes(senders, now) == 2);

  // A full table refuses a newcomer rather than evicting a plate that is working ...
  uint8_t crowd[PRESHOW_SENDER_COUNT + 1][6];
  for (uint8_t i = 0; i < PRESHOW_SENDER_COUNT + 1; ++i) {
    memcpy(crowd[i], PLATE_A, 6);
    crowd[i][3] = uint8_t(0xC0 + i);
  }
  for (uint8_t i = 0; i < PRESHOW_SENDER_COUNT - 2; ++i) {
    PreshowSender *s = preshowSenderFor(senders, crowd[i], now);
    assert(s && preshowAccept(*s, makeEvent(1, 1, 1, 0x5000u + i), now));
  }
  assert(!preshowSenderFor(senders, crowd[PRESHOW_SENDER_COUNT], now));
  assert(preshowSenderFor(senders, PLATE_A, now) == sa && "a live plate keeps its entry");
  // ... and reclaims one once its owner has been silent past the stale window.
  now += PRESHOW_SENDER_STALE_MS + 1;
  assert(preshowSenderFor(senders, crowd[PRESHOW_SENDER_COUNT], now));

  // ---- Legacy shim ----
  PreshowSender old = {};
  memcpy(old.mac, PLATE_A, 6);
  assert(preshowAcceptLegacy(old, 3, 1, now) && old.legacy && old.pointId == 3 && old.state == 1);
  assert(preshowAcceptLegacy(old, 3, 0, now) && old.state == 0 && "legacy frames have no sequence");
  assert(!preshowAcceptLegacy(old, 0, 1, now) && !preshowAcceptLegacy(old, 1, 2, now));
  // A plate that has moved to the current protocol is not dragged back to legacy while it is
  // still being heard from, in case an old frame is still in flight behind it.
  assert(preshowAccept(old, makeEvent(3, 1, 1, 0xD4), now) && !old.legacy);
  assert(!preshowAcceptLegacy(old, 3, 0, now) && old.state == 1);
  now += PRESHOW_SENDER_STALE_MS + 1;
  assert(preshowAcceptLegacy(old, 3, 0, now) && old.legacy && "once it is gone, legacy speaks for it again");

  // ---- Timing budget ----
  // A burst must finish well inside the retry cadence, or the two would interleave.
  assert(PRESHOW_BURST_COUNT >= 2 && PRESHOW_BURST_GAP_MS * PRESHOW_BURST_COUNT < PRESHOW_RETRY_MS);
  // The window has to hold enough retries to survive a run of losses, and has to be shorter
  // than the state re-assert is long, or a failure would be reported after the self-heal.
  assert(PRESHOW_RETRY_WINDOW_MS / PRESHOW_RETRY_MS >= 10);
  assert(PRESHOW_STATE_REPEAT_MS > PRESHOW_RETRY_MS);
  assert(PRESHOW_BEACON_STALE_MS > PRESHOW_BEACON_MS * 3);
  // A plate must not be forgotten between its own re-asserts, or every heartbeat would look
  // like a fresh edge and TouchDesigner would be told about it.
  assert(PRESHOW_SENDER_STALE_MS > PRESHOW_STATE_REPEAT_MS * 3);
  assert(PRESHOW_SENDER_STALE_MS > PRESHOW_RETRY_WINDOW_MS);

  puts("PASS: preshow frame layout/offsets, framing vs zone+pool+legacy protocols, validation, "
       "per-address sequence filter (duplicates, wrap, reboot, staleness, capacity), point clashes, "
       "legacy shim, timing budget");
}
