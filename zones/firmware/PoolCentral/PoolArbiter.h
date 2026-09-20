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

// A momentary gap in a radio's reporting must not reach the lamps. A slider that blips to
// "nothing selected" for a frame or two - a dropped range sample, a filter settling, a lost
// packet - would otherwise switch a relay off and straight back on, which reads as flicker.
// After a radio stops holding a member the lamp is kept lit for this long; if the radio
// comes back to the same member inside the window the lamp never moves at all.
//
// Deliberately asymmetric: lighting a lamp stays instant, only letting go is damped. Set to
// 0 to restore strict instantaneous OR. The cost is that a genuine release is this much
// later, so keep it well under the time a visitor takes to move away.
constexpr uint32_t POOL_RELEASE_HOLD_MS = 400;

// Slots are keyed by the sender's ESP-NOW address, not by the radio id it reports. A MAC is
// unique by construction, so two boards can no longer contend for one slot however they are
// configured, which makes the configured id cosmetic. Six sliders plus headroom, so a
// replacement board brought up alongside the one it replaces still gets a slot of its own.
constexpr uint8_t POOL_SLOT_COUNT = 8;

struct RadioSlot {
  bool valid;      // a frame from this sender has been accepted at least once
  bool active;
  bool legacy;     // last accepted frame used the pre-2026 15-byte packet
  uint8_t mac[6];  // the identity. Everything else about a slot may change; this may not.
  uint8_t radioId; // what the board calls itself: reported and logged, never routed on
  uint8_t member;  // 0 when inactive
  uint16_t seq;
  uint16_t leaseMs;
  uint32_t bootId;
  uint32_t seen;   // arrival time of the last accepted frame
  uint8_t holdMember;   // last member actually held, kept briefly after release
  uint32_t holdUntil;   // and until when
};

inline bool sameMac(const uint8_t *a, const uint8_t *b) { return memcmp(a, b, 6) == 0; }

// Accept or reject a received state frame. `at` is when the frame arrived, not when it is
// being processed, so a frame that waited in the mailbox is still judged on its own age.
// The slot has already been matched to the sender's MAC, so this only has to decide whether
// the frame is newer than what the slot holds.
inline bool acceptState(RadioSlot &s, const PoolState &p, uint32_t at) {
  if (!poolStateValid(p)) return false;
  // A slot belongs to exactly one board, so a changed bootId can only mean that board
  // rebooted and restarted its sequence - take it at once. Two boards can no longer end up
  // in one slot, whatever radio ids they happen to be configured with.
  bool reset = !s.valid || s.legacy || p.bootId != s.bootId || uint32_t(at - s.seen) > POOL_LEASE_MAX_MS;
  // Signed wraparound comparison: rejects duplicates and frames overtaken by a newer one,
  // and stays correct across the 65535 rollover. Skipped once a board has been silent
  // longer than any lease, when its old sequence is meaningless - otherwise it could never
  // be heard from again.
  if (!reset && int16_t(uint16_t(p.seq - s.seq)) <= 0) return false;
  s.valid = true;
  s.legacy = false;
  s.radioId = p.radioId;
  s.bootId = p.bootId;
  s.seq = p.seq;
  s.leaseMs = poolClampLease(p.leaseMs);
  s.active = p.active != 0;
  s.member = s.active ? p.member : 0;
  s.seen = at;
  return true;
}


inline bool acceptLegacy(RadioSlot &s, uint8_t radioId, bool active, uint8_t member, uint32_t at) {
  if (active && (member < 1 || member > POOL_MEMBER_COUNT)) return false;
  // The slot is the sender's own, so a legacy frame can only ever speak for its own board.
  // A board that has moved to the current protocol is not dragged back to legacy while its
  // lease is good, in case an old frame is still in flight behind it.
  if (s.valid && !s.legacy && uint32_t(at - s.seen) <= s.leaseMs) return false;
  s.valid = true;
  s.legacy = true;
  s.radioId = radioId;
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

// Push the release hold forward for as long as a radio is really holding a member. Called
// once per pass before arbitrating, so `holdUntil` ends up POOL_RELEASE_HOLD_MS after the
// last instant the radio was holding, whether it let go deliberately or simply went quiet.
inline void refreshHold(RadioSlot &s, uint32_t now) {
  if (!expired(s, now)) {
    s.holdMember = s.member;
    s.holdUntil = now + POOL_RELEASE_HOLD_MS;
  }
}

// What a radio contributes: the member it holds, or - briefly after it lets go - the last
// member it held. Moving straight from one member to another is not damped, because
// refreshHold has already replaced holdMember by the time this is read.
inline uint32_t contribution(const RadioSlot &s, uint32_t now) {
  if (!expired(s, now)) return memberBit(s.member);
  if (s.holdMember && int32_t(s.holdUntil - now) > 0) return memberBit(s.holdMember);
  return 0;
}

// The slot this sender owns, claiming a free one if it is new. Returns nullptr only when
// every slot is held by a board that is still live, in which case the frame is dropped and
// counted rather than evicting a slider that is currently lighting something.
inline RadioSlot *slotFor(RadioSlot *slots, const uint8_t *mac, uint32_t now) {
  RadioSlot *spare = nullptr, *stalest = nullptr;
  for (uint8_t i = 0; i < POOL_SLOT_COUNT; ++i) {
    RadioSlot &s = slots[i];
    if (s.valid && sameMac(s.mac, mac)) return &s;
    if (!s.valid) { if (!spare) spare = &s; continue; }
    // Reclaimable once the board is neither lighting anything nor inside its lease.
    if (contribution(s, now) || uint32_t(now - s.seen) <= s.leaseMs) continue;
    if (!stalest || uint32_t(now - s.seen) > uint32_t(now - stalest->seen)) stalest = &s;
  }
  RadioSlot *claim = spare ? spare : stalest;
  if (!claim) return nullptr;
  *claim = RadioSlot{};
  memcpy(claim->mac, mac, 6);
  return claim;
}

// How many live boards report the same radio id as another. Harmless now that the slots are
// separate, but still worth surfacing: it means the labels are wrong.
inline uint8_t claimedIdClashes(const RadioSlot *slots, uint32_t now) {
  uint8_t clashing = 0;
  for (uint8_t i = 0; i < POOL_SLOT_COUNT; ++i) {
    const RadioSlot &a = slots[i];
    if (!a.valid || uint32_t(now - a.seen) > a.leaseMs) continue;
    for (uint8_t j = 0; j < POOL_SLOT_COUNT; ++j) {
      const RadioSlot &b = slots[j];
      if (i == j || !b.valid || uint32_t(now - b.seen) > b.leaseMs) continue;
      if (a.radioId == b.radioId) { ++clashing; break; }
    }
  }
  return clashing;
}

// Pure OR, any-wins: a member frame is on when ANY radio currently holds it (or is inside
// its release hold).
inline uint32_t arbitrate(const RadioSlot *slots, uint32_t now) {
  uint32_t desired = 0;
  for (uint8_t i = 0; i < POOL_SLOT_COUNT; ++i) desired |= contribution(slots[i], now);
  return desired;
}

// Bit i set when some live board reports itself as radio i+1, whether or not it is holding
// a member. Radios echo this back as `central_sees_me`, so it stays in claimed-id space
// even though routing no longer is; two boards claiming one id both set the bit, which is
// simply true of both. Idle boards keep heartbeating, so this still tells "slider idle"
// apart from "slider dead".
inline uint8_t radioMask(const RadioSlot *slots, uint32_t now) {
  uint8_t mask = 0;
  for (uint8_t i = 0; i < POOL_SLOT_COUNT; ++i) {
    const RadioSlot &s = slots[i];
    if (!s.valid || uint32_t(now - s.seen) > s.leaseMs) continue;
    if (s.radioId >= 1 && s.radioId <= POOL_RADIO_COUNT) mask |= uint8_t(1 << (s.radioId - 1));
  }
  return mask;
}

}  // namespace nctpool
