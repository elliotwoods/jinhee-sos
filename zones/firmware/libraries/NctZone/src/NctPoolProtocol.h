#pragma once
// Pool light wire format. Shared by the six PoolZone slider radios, the pool central
// controller (zones/firmware/PoolCentral) and the USB bench bridge (poolzone_test).
//
// This is the ONE definition. The legacy 15-byte RadioPacket was copied into five
// sketches with nothing cross-checking them; run_firmware_tests.py now refuses a
// sketch that declares its own copy, the same guard the neocube Packet already had.
//
// Pool frames carry the 'N','Z',PROTO header so they inherit the length-collision
// guarantees documented in NctZoneProtocol.h, but they are DELIBERATELY absent from
// frameType(): ZoneLink::receive() queues every frame frameType() accepts and
// ZoneLink::handle() silently drops what it does not recognise, so a beacon routed
// through there would occupy a queue slot and never reach the sketch. Pool frames are
// decoded by poolFrameType() from TagPlate::onFrame instead.
#include <stdint.h>
#include <stddef.h>
#include "NctZoneProtocol.h"

namespace nctzone {

constexpr uint8_t POOL_STATE = 0x30;   // radio -> central
constexpr uint8_t POOL_BEACON = 0x31;  // central -> radios (broadcast)

constexpr uint8_t POOL_PROTOCOL_VERSION = 1;
constexpr uint8_t POOL_RADIO_COUNT = 6;
constexpr uint8_t POOL_MEMBER_COUNT = 23;

// Lease held by the central for each radio. A radio may shorten its own lease; the
// central clamps whatever arrives, so a bad or hostile value cannot latch a light on.
// The floor is not arbitrary: it must fit several heartbeats, or even the shortest
// lease a radio may request would blink on a single lost frame.
constexpr uint16_t POOL_LEASE_DEFAULT_MS = 800;  // preserves the legacy RADIO_TIMEOUT_MS
constexpr uint16_t POOL_LEASE_MIN_MS = 600;
constexpr uint16_t POOL_LEASE_MAX_MS = 2000;

// Radio transmit schedule. A lost heartbeat costs at most one lease of blink; a lost
// release costs a lease of a *stuck-on* light, which is the more visible artefact, so
// changes burst and releases repeat.
constexpr uint32_t POOL_HEARTBEAT_MS = 150;        // while an interaction is active
// What the heartbeat actually costs in the worst case: TagPlate::NFC_READ_TIMEOUT is
// 80 ms and a no-tag PN532 poll blocks for it, so the interval really lands at
// 150-250 ms. Lease budgeting must use this figure, not the nominal one.
constexpr uint32_t POOL_HEARTBEAT_WORST_MS = 250;
constexpr uint32_t POOL_IDLE_HEARTBEAT_MS = 500;   // while idle, forever
constexpr uint8_t POOL_BURST_COUNT = 3;            // frames sent on any state change
constexpr uint32_t POOL_BURST_GAP_MS = 20;
constexpr uint32_t POOL_RELEASE_REPEAT_MS = 1000;  // keep re-asserting active=0 this long
constexpr uint32_t POOL_BROADCAST_COPY_MS = 450;   // one broadcast copy this often, always

// Central beacon schedule.
constexpr uint32_t POOL_BEACON_MS = 500;
constexpr uint32_t POOL_BEACON_STALE_MS = 3000;  // no beacon for this long -> broadcast only

// The original pre-2026 pool packet, still accepted by the central so that a slider
// missed during a rollout keeps working instead of going dark with no diagnosis.
constexpr uint32_t POOL_LEGACY_MAGIC = 0x4E435450;
constexpr int POOL_LEGACY_SIZE = 15;

#pragma pack(push, 1)

struct PoolState {
  Header h;
  uint32_t bootId;    // random per radio boot; a change resets the central's seq filter
  uint16_t seq;       // per radio, wraps; the central rejects stale and duplicate frames
  uint16_t leaseMs;   // requested lease, clamped on receipt
  uint8_t radioId;    // 1..POOL_RADIO_COUNT (the zone's configured pointId)
  uint8_t active;
  uint8_t member;     // 1..POOL_MEMBER_COUNT when active
  uint8_t uidLength;  // NFC UID of the cube on the plate; informational
  uint8_t uid[7];
};

struct PoolBeacon {
  Header h;
  uint32_t epoch;     // changes on central boot; a radio re-bursts its state when it moves
  uint32_t uptimeS;
  uint8_t channel;    // telemetry only. A radio on another channel never hears this frame,
                      // so nothing may branch on it.
  uint8_t radioMask;  // bit i set => radio i+1 is currently within its lease at the central
  uint8_t version;
  uint8_t flags;
  uint8_t reserved;
};

#pragma pack(pop)

static_assert(sizeof(PoolState) == 23, "pool state layout");
static_assert(sizeof(PoolBeacon) == 17, "pool beacon layout");
// 2 = preshow media bridge, 15 = legacy pool RadioPacket, 24 = neocube Packet.
static_assert(sizeof(PoolState) != 2 && sizeof(PoolState) != POOL_LEGACY_SIZE && sizeof(PoolState) != 24,
              "pool state length collides with another protocol");
static_assert(sizeof(PoolBeacon) != 2 && sizeof(PoolBeacon) != POOL_LEGACY_SIZE && sizeof(PoolBeacon) != 24,
              "pool beacon length collides with another protocol");
// Nothing here may be routed by the zone-management dispatcher; see the note above.
static_assert(POOL_STATE != DB_ANNOUNCE && POOL_STATE != DB_CHUNK && POOL_STATE != ZONE_QUERY &&
              POOL_STATE != ZONE_STATUS && POOL_STATE != ZONE_LOG && POOL_STATE != ZONE_IDENTIFY &&
              POOL_STATE != ZONE_REBOOT && POOL_BEACON != DB_ANNOUNCE && POOL_BEACON != DB_CHUNK &&
              POOL_BEACON != ZONE_QUERY && POOL_BEACON != ZONE_STATUS && POOL_BEACON != ZONE_LOG &&
              POOL_BEACON != ZONE_IDENTIFY && POOL_BEACON != ZONE_REBOOT,
              "pool type byte collides with a zone-management type");

// Returns POOL_STATE / POOL_BEACON, or 0 if this is not a well-formed pool frame.
inline uint8_t poolFrameType(const uint8_t *data, int len) {
  if (!data || len < int(sizeof(Header))) return 0;
  if (data[0] != MAGIC0 || data[1] != MAGIC1 || data[2] != PROTO) return 0;
  switch (data[3]) {
    case POOL_STATE:  return len == int(sizeof(PoolState)) ? POOL_STATE : 0;
    case POOL_BEACON: return len == int(sizeof(PoolBeacon)) ? POOL_BEACON : 0;
    default:          return 0;
  }
}

inline bool poolStateValid(const PoolState &p) {
  return p.radioId >= 1 && p.radioId <= POOL_RADIO_COUNT && p.uidLength <= 7 &&
         (!p.active || (p.member >= 1 && p.member <= POOL_MEMBER_COUNT));
}

inline uint16_t poolClampLease(uint16_t ms) {
  return ms < POOL_LEASE_MIN_MS ? POOL_LEASE_MIN_MS : ms > POOL_LEASE_MAX_MS ? POOL_LEASE_MAX_MS : ms;
}

}  // namespace nctzone
