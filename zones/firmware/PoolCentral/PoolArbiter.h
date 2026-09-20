#pragma once
// Lease and arbitration logic for the pool central controller.
//
// Deliberately free of Arduino headers so the host tests exercise exactly the code that
// runs on the board. Everything here is a pure function of the slot state plus `now`;
// the sketch owns all I/O, and nothing in this file may log, block or touch hardware.
#include <stdint.h>
#include <string.h>
#include "NctPoolProtocol.h"
#include "PoolOutput.h"

namespace nctpool {

using nctzone::PoolState;
using nctzone::POOL_LEASE_DEFAULT_MS;
using nctzone::POOL_LEASE_MAX_MS;
using nctzone::POOL_MEMBER_COUNT;
using nctzone::POOL_RADIO_COUNT;
using nctzone::poolClampLease;
using nctzone::poolStateValid;

struct RadioSlot {
  bool valid;      // a frame from this radio has been accepted at least once
  bool active;
  bool legacy;     // last accepted frame used the pre-2026 15-byte packet
  uint8_t member;  // 0 when inactive
  uint16_t seq;
  uint16_t leaseMs;
  uint32_t bootId;
  uint32_t seen;   // arrival time of the last accepted frame
};

// Accept or reject a received state frame. `at` is when the frame arrived, not when it is
// being processed, so a frame that waited in the mailbox is still judged on its own age.
inline bool acceptState(RadioSlot &s, const PoolState &p, uint32_t at) {
  if (!poolStateValid(p)) return false;
  // Two escapes from the sequence filter are required, and both are load-bearing:
  //  - a rebooted radio restarts at seq 0, so without bootId the slot's high seq would
  //    reject that radio for good;
  //  - a radio that was out of range longer than any lease has a meaningless old seq.
  bool reset = !s.valid || p.bootId != s.bootId || uint32_t(at - s.seen) > POOL_LEASE_MAX_MS;
  // Signed wraparound comparison: rejects duplicates and frames overtaken by a newer one,
  // and stays correct across the 65535 rollover.
  if (!reset && int16_t(uint16_t(p.seq - s.seq)) <= 0) return false;
  s.valid = true;
  s.legacy = false;
  s.bootId = p.bootId;
  s.seq = p.seq;
  s.leaseMs = poolClampLease(p.leaseMs);
  s.active = p.active != 0;
  s.member = s.active ? p.member : 0;
  s.seen = at;
  return true;
}

// The pre-2026 packet carries no sequence or boot identity, so it can only be accepted on
// arrival order. Kept so that a slider missed during a rollout keeps working rather than
// going dark with no diagnosis; a radio already speaking the current protocol is never
// displaced by a legacy frame claiming the same id while its lease is still good.
inline bool acceptLegacy(RadioSlot &s, uint8_t radioId, bool active, uint8_t member, uint32_t at) {
  if (radioId < 1 || radioId > POOL_RADIO_COUNT) return false;
  if (active && (member < 1 || member > POOL_MEMBER_COUNT)) return false;
  if (s.valid && !s.legacy && uint32_t(at - s.seen) <= s.leaseMs) return false;
  s.valid = true;
  s.legacy = true;
  s.bootId = 0;
  s.seq = 0;
  s.leaseMs = POOL_LEASE_DEFAULT_MS;
  s.active = active;
  s.member = active ? member : 0;
  s.seen = at;
  return true;
}

// True when this radio no longer holds a member: never heard from, released, or its lease
// ran out. Expiry is derived on every read rather than swept by a timer, so there is no
// window in which a timeout sweep can stomp a freshly accepted frame.
inline bool expired(const RadioSlot &s, uint32_t now) {
  return !s.valid || !s.active || uint32_t(now - s.seen) > s.leaseMs;
}

// Pure OR, any-wins: a member frame is on when ANY radio currently holds it.
inline uint32_t arbitrate(const RadioSlot *slots, uint32_t now) {
  uint32_t desired = 0;
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i)
    if (!expired(slots[i], now)) desired |= memberBit(slots[i].member);
  return desired;
}

// Bit i set when radio i+1 is being heard from, whether or not it holds a member. Radios
// send idle heartbeats, so this distinguishes "slider idle" from "slider dead" and is
// echoed back in the beacon for each radio's own USB console.
inline uint8_t radioMask(const RadioSlot *slots, uint32_t now) {
  uint8_t mask = 0;
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i)
    if (slots[i].valid && uint32_t(now - slots[i].seen) <= slots[i].leaseMs) mask |= uint8_t(1 << i);
  return mask;
}

}  // namespace nctpool
