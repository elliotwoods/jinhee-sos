#pragma once
// Preshow media wire format. Shared by the four PreshowZone tag plates and the TouchDesigner
// bridge (zones/firmware/PreshowBridge).
//
// This is the ONE definition. What it replaces was a two-byte struct copied into both
// sketches by hand, with a hardcoded destination MAC and no sequence, acknowledgement or
// retry of any kind: a single lost frame meant TouchDesigner never fired the cue, or never
// received the OFF and left the point lit, and nothing anywhere could tell you it happened.
//
// The shape is taken from NctPoolProtocol.h, which is hardware-proven: the receiver
// broadcasts a beacon, each sender latches its source address and unicasts back, so the
// radio gets MAC-layer acknowledgement and hardware retries instead of shouting into a
// shared channel. Two things are added on top, because a show cue is a one-shot edge rather
// than a stream that re-states itself sixty times a second:
//
//   - the bridge unicasts a PreshowAck echoing bootId+seq, so the plate retries until the
//     serial line has actually been written, not merely until the radio claimed delivery;
//   - the plate keeps re-asserting its current state at a low rate, so an edge lost while
//     the bridge was away heals itself as soon as it returns.
//
// Preshow frames carry the 'N','Z',PROTO header so they inherit the length-collision
// guarantees documented in NctZoneProtocol.h, but they are DELIBERATELY absent from
// frameType(), for exactly the reason set out at the top of NctPoolProtocol.h: they are
// decoded by preshowFrameType() from TagPlate::onFrame instead.
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "NctZoneProtocol.h"
// Included for the type-byte collision guard below rather than for any pool behaviour: the
// two links share this header, this channel and this building, so the check has to be
// against the real constants, not a copy of them.
#include "NctPoolProtocol.h"

namespace nctzone {

constexpr uint8_t PRESHOW_EVENT = 0x40;   // plate -> bridge
constexpr uint8_t PRESHOW_ACK = 0x41;     // bridge -> plate (unicast)
constexpr uint8_t PRESHOW_BEACON = 0x42;  // bridge -> radios (broadcast)

constexpr uint8_t PRESHOW_PROTOCOL_VERSION = 1;
constexpr uint8_t PRESHOW_POINT_COUNT = 4;

// Plate transmit schedule.
//
// A sequence number identifies an EVENT, not a frame: every retransmission of the same
// ON/OFF is byte-identical. That is what makes an acknowledgement unambiguous (the plate
// waits for an ack carrying exactly the seq it is trying to deliver) and what lets the
// bridge treat a retry as the duplicate it is. The pool link increments per frame because
// there a dropped frame is simply superseded; here each edge has to arrive.
constexpr uint8_t PRESHOW_BURST_COUNT = 3;        // frames sent immediately on any change
constexpr uint32_t PRESHOW_BURST_GAP_MS = 20;
constexpr uint32_t PRESHOW_RETRY_MS = 120;        // retry cadence while unacknowledged
// How long an unacknowledged edge is retried before the plate reports it. Chosen with the
// tag-leave timeout in mind: TagPlate::TAG_LEAVE_TIMEOUT is 700 ms, so three seconds covers
// a visitor arriving and leaving again without the two edges' retry windows overlapping.
constexpr uint32_t PRESHOW_RETRY_WINDOW_MS = 3000;
// Re-assert the current state forever, acknowledged or not. This is the self-healing path:
// the bridge only writes a serial line when a point's state actually CHANGES, so these cost
// TouchDesigner nothing, and a bridge that reboots or comes back into range picks up the
// true state within one interval instead of staying wrong until the next visitor.
constexpr uint32_t PRESHOW_STATE_REPEAT_MS = 1000;
// One broadcast copy this often, whatever the unicast link is doing: rescues a plate that
// latched an address which has since stopped being the bridge.
constexpr uint32_t PRESHOW_BROADCAST_COPY_MS = 1000;

// Bridge beacon schedule.
constexpr uint32_t PRESHOW_BEACON_MS = 500;
constexpr uint32_t PRESHOW_BEACON_STALE_MS = 3000;  // no beacon for this long -> broadcast only

// A sender silent for longer than this has a sequence number that means nothing any more,
// so it is let back in whatever it carries. Must be comfortably longer than the retry window
// plus the repeat interval, or an ordinary quiet plate would keep resetting its own filter.
constexpr uint32_t PRESHOW_SENDER_STALE_MS = 10000;

// The pre-2026 packet: two bare bytes, {pointID, state}, no header and no magic. Length 2 is
// claimed by this protocol alone - see the collision guards in NctZoneProtocol.h and
// NctPoolProtocol.h.
//
// Both ends keep speaking it, in opposite directions, so the rollout can go either way round:
//   - the bridge ACCEPTS it, so a plate missed during a rollout keeps working;
//   - a plate SENDS it as well, until it has heard a beacon, so a plate can be replaced while
//     the bridge is still the original listener-only board. That is not hypothetical: the
//     TouchDesigner bridge is exactly that board today.
// A plate stops sending it the moment a real PreshowBeacon arrives, and never resumes.
constexpr int PRESHOW_LEGACY_SIZE = 2;

// The original media bridge, as hardcoded in PreshowZone before this protocol existed. Used
// only as the fallback destination while no beacon has ever been heard: unicast buys
// MAC-layer acknowledgement and hardware retries, which the old link never had. A broadcast
// copy goes out too, which covers this board having been swapped for another legacy one.
constexpr uint8_t PRESHOW_LEGACY_BRIDGE_MAC[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};

#pragma pack(push, 1)

struct PreshowEvent {
  Header h;
  uint32_t bootId;    // random per plate boot; a change resets the bridge's seq filter
  uint16_t seq;       // per plate, wraps; incremented once per state CHANGE, not per frame
  uint8_t pointId;    // 1..PRESHOW_POINT_COUNT (the zone's configured pointId)
  uint8_t state;      // 1 = ON, 0 = OFF
  uint8_t uidLength;  // NFC UID of the cube that caused it; informational
  uint8_t uid[7];
};

struct PreshowAck {
  Header h;
  uint32_t bootId;  // echoed from the event, so a plate cannot be fooled by its own past
  uint16_t seq;     // echoed from the event
  uint8_t pointId;  // echoed from the event
  uint8_t flags;    // PRESHOW_ACK_APPLIED when this event changed the point's state
};

struct PreshowBeacon {
  Header h;
  uint32_t epoch;     // changes on bridge boot; a plate re-bursts its state when it moves
  uint32_t uptimeS;
  uint8_t pointMask;  // bit i set => the bridge currently holds point i+1 ON
  uint8_t version;
  uint8_t channel;    // telemetry only. A plate on another channel never hears this frame,
                      // so nothing may branch on it.
  uint8_t flags;
};

// The pre-2026 packet, defined here so neither end can grow its own copy again - which is
// exactly what it did before, once in the plate and once in the bridge.
struct PreshowLegacy {
  uint8_t pointId;
  uint8_t state;
};

#pragma pack(pop)

enum PreshowAckFlags : uint8_t { PRESHOW_ACK_APPLIED = 0x01 };

static_assert(sizeof(PreshowLegacy) == PRESHOW_LEGACY_SIZE, "legacy media packet ABI changed");

static_assert(sizeof(PreshowEvent) == 20, "preshow event layout");
static_assert(sizeof(PreshowAck) == 12, "preshow ack layout");
static_assert(sizeof(PreshowBeacon) == 16, "preshow beacon layout");
// 2 = legacy preshow media packet, 15 = legacy pool RadioPacket, 24 = neocube Packet.
static_assert(sizeof(PreshowEvent) != PRESHOW_LEGACY_SIZE && sizeof(PreshowEvent) != 15 && sizeof(PreshowEvent) != 24,
              "preshow event length collides with another protocol");
static_assert(sizeof(PreshowAck) != PRESHOW_LEGACY_SIZE && sizeof(PreshowAck) != 15 && sizeof(PreshowAck) != 24,
              "preshow ack length collides with another protocol");
static_assert(sizeof(PreshowBeacon) != PRESHOW_LEGACY_SIZE && sizeof(PreshowBeacon) != 15 && sizeof(PreshowBeacon) != 24,
              "preshow beacon length collides with another protocol");
// Nothing here may be routed by the zone-management dispatcher; see the note above. Nor may
// it collide with the pool link, which shares the same header and the same radio channel.
static_assert(PRESHOW_EVENT != DB_ANNOUNCE && PRESHOW_EVENT != DB_CHUNK && PRESHOW_EVENT != ZONE_QUERY &&
              PRESHOW_EVENT != ZONE_STATUS && PRESHOW_EVENT != ZONE_LOG && PRESHOW_EVENT != ZONE_IDENTIFY &&
              PRESHOW_EVENT != ZONE_REBOOT && PRESHOW_ACK != DB_ANNOUNCE && PRESHOW_ACK != DB_CHUNK &&
              PRESHOW_ACK != ZONE_QUERY && PRESHOW_ACK != ZONE_STATUS && PRESHOW_ACK != ZONE_LOG &&
              PRESHOW_ACK != ZONE_IDENTIFY && PRESHOW_ACK != ZONE_REBOOT && PRESHOW_BEACON != DB_ANNOUNCE &&
              PRESHOW_BEACON != DB_CHUNK && PRESHOW_BEACON != ZONE_QUERY && PRESHOW_BEACON != ZONE_STATUS &&
              PRESHOW_BEACON != ZONE_LOG && PRESHOW_BEACON != ZONE_IDENTIFY && PRESHOW_BEACON != ZONE_REBOOT,
              "preshow type byte collides with a zone-management type");
static_assert(PRESHOW_EVENT != POOL_STATE && PRESHOW_EVENT != POOL_BEACON && PRESHOW_ACK != POOL_STATE &&
              PRESHOW_ACK != POOL_BEACON && PRESHOW_BEACON != POOL_STATE && PRESHOW_BEACON != POOL_BEACON,
              "preshow type byte collides with the pool link");

// Returns PRESHOW_EVENT / PRESHOW_ACK / PRESHOW_BEACON, or 0 if this is not a well-formed
// preshow frame.
inline uint8_t preshowFrameType(const uint8_t *data, int len) {
  if (!data || len < int(sizeof(Header))) return 0;
  if (data[0] != MAGIC0 || data[1] != MAGIC1 || data[2] != PROTO) return 0;
  switch (data[3]) {
    case PRESHOW_EVENT:  return len == int(sizeof(PreshowEvent)) ? PRESHOW_EVENT : 0;
    case PRESHOW_ACK:    return len == int(sizeof(PreshowAck)) ? PRESHOW_ACK : 0;
    case PRESHOW_BEACON: return len == int(sizeof(PreshowBeacon)) ? PRESHOW_BEACON : 0;
    default:             return 0;
  }
}

inline bool preshowPointValid(uint8_t pointId) {
  return pointId >= 1 && pointId <= PRESHOW_POINT_COUNT;
}

inline bool preshowEventValid(const PreshowEvent &e) {
  return preshowPointValid(e.pointId) && e.state <= 1 && e.uidLength <= 7;
}

inline uint8_t preshowPointBit(uint8_t pointId) {
  return preshowPointValid(pointId) ? uint8_t(1 << (pointId - 1)) : uint8_t(0);
}

// ---- Bridge-side sequence filter ----
// One entry per SENDER address, not per point: a MAC is unique by construction, so two
// plates configured with the same point id cannot corrupt one another's sequence state.
// The point id a plate reports is what the cue is addressed to, and is reported when two
// boards claim the same one, but it is never what a filter entry is keyed on.
constexpr uint8_t PRESHOW_SENDER_COUNT = 8;  // four plates plus headroom for a replacement

struct PreshowSender {
  bool valid;
  bool legacy;     // last accepted frame used the pre-2026 two-byte packet
  uint8_t mac[6];  // the identity; everything else about an entry may change, this may not
  uint8_t pointId;
  uint8_t state;
  uint16_t seq;
  uint32_t bootId;
  uint32_t seen;   // arrival time of the last accepted frame
};

inline bool preshowSameMac(const uint8_t *a, const uint8_t *b) { return memcmp(a, b, 6) == 0; }

// The entry this sender owns, claiming a free or long-stale one if it is new. Returns
// nullptr only when every entry belongs to a sender still heard from recently, in which case
// the frame is dropped and counted rather than evicting a plate that is working.
inline PreshowSender *preshowSenderFor(PreshowSender *senders, const uint8_t *mac, uint32_t now) {
  PreshowSender *spare = nullptr, *stalest = nullptr;
  for (uint8_t i = 0; i < PRESHOW_SENDER_COUNT; ++i) {
    PreshowSender &s = senders[i];
    if (s.valid && preshowSameMac(s.mac, mac)) return &s;
    if (!s.valid) { if (!spare) spare = &s; continue; }
    if (uint32_t(now - s.seen) <= PRESHOW_SENDER_STALE_MS) continue;
    if (!stalest || uint32_t(now - s.seen) > uint32_t(now - stalest->seen)) stalest = &s;
  }
  PreshowSender *claim = spare ? spare : stalest;
  if (!claim) return nullptr;
  *claim = PreshowSender{};
  memcpy(claim->mac, mac, 6);
  return claim;
}

// Decide whether this event carries something the bridge has not already applied. `at` is
// when the frame arrived, not when it is processed, so a frame that waited in the mailbox is
// still judged on its own age.
//
// A false return means "already seen" - a retry or a heartbeat. The caller must still
// acknowledge it: if only new events were acknowledged, one lost ack would leave the plate
// retrying for its whole window and then reporting a failure that never happened.
inline bool preshowAccept(PreshowSender &s, const PreshowEvent &e, uint32_t at) {
  if (!preshowEventValid(e)) return false;
  // An entry belongs to exactly one board, so a changed bootId can only mean that board
  // rebooted and restarted its sequence - take it at once.
  bool reset = !s.valid || s.legacy || e.bootId != s.bootId || uint32_t(at - s.seen) > PRESHOW_SENDER_STALE_MS;
  // Signed wraparound comparison: rejects duplicates and frames overtaken by a newer one,
  // and stays correct across the 65535 rollover. Skipped after a long silence, when the old
  // sequence is meaningless - otherwise a plate could never be heard from again.
  if (!reset && int16_t(uint16_t(e.seq - s.seq)) <= 0) {
    s.seen = at;  // a duplicate still proves the plate is alive
    return false;
  }
  s.valid = true;
  s.legacy = false;
  s.pointId = e.pointId;
  s.state = e.state;
  s.seq = e.seq;
  s.bootId = e.bootId;
  s.seen = at;
  return true;
}

// The legacy two-byte packet has no sequence at all, so every one of them is "new". A board
// that has moved to the current protocol is not dragged back to legacy while it is still
// being heard from, in case an old frame is still in flight behind it.
inline bool preshowAcceptLegacy(PreshowSender &s, uint8_t pointId, uint8_t state, uint32_t at) {
  if (!preshowPointValid(pointId) || state > 1) return false;
  if (s.valid && !s.legacy && uint32_t(at - s.seen) <= PRESHOW_SENDER_STALE_MS) return false;
  s.valid = true;
  s.legacy = true;
  s.pointId = pointId;
  s.state = state;
  s.seq = 0;
  s.bootId = 0;
  s.seen = at;
  return true;
}

// How many senders heard from recently report the same point id as another. Harmless to the
// filter, which is keyed by address, but it means two plates are fighting over one cue.
inline uint8_t preshowPointClashes(const PreshowSender *senders, uint32_t now) {
  uint8_t clashing = 0;
  for (uint8_t i = 0; i < PRESHOW_SENDER_COUNT; ++i) {
    const PreshowSender &a = senders[i];
    if (!a.valid || uint32_t(now - a.seen) > PRESHOW_SENDER_STALE_MS) continue;
    for (uint8_t j = 0; j < PRESHOW_SENDER_COUNT; ++j) {
      const PreshowSender &b = senders[j];
      if (i == j || !b.valid || uint32_t(now - b.seen) > PRESHOW_SENDER_STALE_MS) continue;
      if (a.pointId == b.pointId) { ++clashing; break; }
    }
  }
  return clashing;
}

}  // namespace nctzone
