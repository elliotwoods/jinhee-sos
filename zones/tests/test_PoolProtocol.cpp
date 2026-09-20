// Pool wire format: layout, framing and the rules the central depends on.
// Deliberately includes nothing but the header: NctPoolProtocol.h must stay free of
// Arduino dependencies so both the sketch and the host tests share one definition.
#include "NctPoolProtocol.h"
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

int main() {
  // ---- Field offsets are the wire contract; both ends memcpy whole structs. ----
  static_assert(sizeof(Header) == 4, "header");
  static_assert(offsetof(PoolState, bootId) == 4, "bootId offset");
  static_assert(offsetof(PoolState, seq) == 8, "seq offset");
  static_assert(offsetof(PoolState, leaseMs) == 10, "leaseMs offset");
  static_assert(offsetof(PoolState, radioId) == 12, "radioId offset");
  static_assert(offsetof(PoolState, uid) == 16, "uid offset");
  static_assert(offsetof(PoolBeacon, epoch) == 4, "epoch offset");
  static_assert(offsetof(PoolBeacon, radioMask) == 13, "radioMask offset");

  // ---- Framing ----
  PoolState s = {};
  fillHeader(s.h, POOL_STATE);
  s.radioId = 3; s.active = 1; s.member = 12; s.leaseMs = POOL_LEASE_DEFAULT_MS;
  auto frame = bytesOf(&s, sizeof(s));
  assert(poolFrameType(frame.data(), int(frame.size())) == POOL_STATE);
  assert(frameType(frame.data(), int(frame.size())) == 0);  // never routed by the zone dispatcher

  PoolBeacon b = {};
  fillHeader(b.h, POOL_BEACON);
  b.epoch = 0x12345678; b.radioMask = 0b000101; b.version = POOL_PROTOCOL_VERSION;
  auto beacon = bytesOf(&b, sizeof(b));
  assert(poolFrameType(beacon.data(), int(beacon.size())) == POOL_BEACON);
  assert(frameType(beacon.data(), int(beacon.size())) == 0);

  // Wrong length, wrong magic, wrong proto and truncation are all rejected.
  assert(poolFrameType(frame.data(), int(frame.size()) - 1) == 0);
  assert(poolFrameType(frame.data(), int(frame.size()) + 1) == 0);
  assert(poolFrameType(beacon.data(), int(frame.size())) == 0);
  assert(poolFrameType(nullptr, int(frame.size())) == 0);
  assert(poolFrameType(frame.data(), 3) == 0);
  for (size_t i = 0; i < 3; ++i) {
    auto bad = frame; bad[i] ^= 0xFF;
    assert(poolFrameType(bad.data(), int(bad.size())) == 0);
  }
  auto unknownType = frame; unknownType[3] = 0x77;
  assert(poolFrameType(unknownType.data(), int(unknownType.size())) == 0);

  // A legacy 15-byte packet is not a pool frame; the central matches it by magic instead.
  std::vector<uint8_t> legacy(POOL_LEGACY_SIZE, 0);
  memcpy(legacy.data(), &POOL_LEGACY_MAGIC, 4);
  assert(poolFrameType(legacy.data(), int(legacy.size())) == 0);
  assert(frameType(legacy.data(), int(legacy.size())) == 0);

  // ---- Validation ----
  assert(poolStateValid(s));
  PoolState bad = s; bad.radioId = 0;                 assert(!poolStateValid(bad));
  bad = s; bad.radioId = POOL_RADIO_COUNT + 1;        assert(!poolStateValid(bad));
  bad = s; bad.member = 0;                            assert(!poolStateValid(bad));
  bad = s; bad.member = POOL_MEMBER_COUNT + 1;        assert(!poolStateValid(bad));
  bad = s; bad.uidLength = 8;                         assert(!poolStateValid(bad));
  // A release carries no member, so member is not checked when inactive.
  bad = s; bad.active = 0; bad.member = 0;            assert(poolStateValid(bad));

  // ---- Lease clamping: a radio cannot latch a light on, or drop it instantly. ----
  assert(poolClampLease(0) == POOL_LEASE_MIN_MS);
  assert(poolClampLease(POOL_LEASE_MIN_MS - 1) == POOL_LEASE_MIN_MS);
  assert(poolClampLease(60000) == POOL_LEASE_MAX_MS);
  assert(poolClampLease(POOL_LEASE_DEFAULT_MS) == POOL_LEASE_DEFAULT_MS);
  assert(POOL_LEASE_MIN_MS <= POOL_LEASE_DEFAULT_MS && POOL_LEASE_DEFAULT_MS <= POOL_LEASE_MAX_MS);

  // The active heartbeat must fit several times into the shortest lease, or a single
  // lost frame would already be visible as a blink. Budget the real jittered interval
  // (the PN532 poll blocks the loop) against the lease a radio actually asks for.
  assert(POOL_HEARTBEAT_MS * 3 < POOL_LEASE_MIN_MS);
  assert(POOL_HEARTBEAT_WORST_MS * 3 <= POOL_LEASE_DEFAULT_MS);
  assert(POOL_BURST_COUNT >= 2 && POOL_BURST_GAP_MS * POOL_BURST_COUNT < POOL_HEARTBEAT_MS);
  assert(POOL_RELEASE_REPEAT_MS >= POOL_LEASE_DEFAULT_MS);
  assert(POOL_BEACON_STALE_MS > POOL_BEACON_MS * 3);

  puts("PASS: pool frame layout/offsets, framing vs zone+legacy protocols, validation, lease clamp, timing budget");
}
