#pragma once
// Pool role: one emulated pool slider radio, so a host can light a pool lamp through the
// central controller without a PoolZone board. Same link as the real radios and the
// poolzone_test bridge (NctPoolProtocol.h): latch the central's beacon, unicast PoolState to
// it (broadcast until a beacon is heard), burst on every change, keep the heartbeat within the
// lease while a member is held, re-assert a release for a second, one broadcast copy every
// POOL_BROADCAST_COPY_MS.
//
// The central keys its slots by sender address (PoolArbiter.h), so one dongle owns one slot and
// therefore holds ONE member at a time, whatever radio id it reports. The radio id is cosmetic
// there; it is settable here only so a log on the central reads sensibly.
//
// Leased: the host must keep pinging (the same 1500 ms lease as PoolZone's HOST override) or
// the member is released, so an unplugged laptop cannot leave a lamp on for the rest of the show.
// Unlike the test bridge, nothing is transmitted while no member is held: an idle dongle that
// is only relaying zone frames does not spray pool traffic.
#include <string.h>
#include <stdio.h>
#include "WsRadio.h"
#include "WsJson.h"
#include "WsHex.h"

namespace ws {
namespace pool {

using namespace nctzone;

constexpr uint32_t HOST_TIMEOUT_MS = 1500;
constexpr uint32_t BEACON_REPORT_MS = 5000;  // unsolicited pool_beacon events at most this often (plus every change)

inline bool armed = false;
inline uint8_t member = 0, radioId = 1;
inline uint32_t bootId = 1;
inline uint16_t seq = 0;
inline uint32_t lastHost = 0, lastSend = 0, lastBroadcastCopy = 0, releaseUntil = 0, nextBurstAt = 0;
inline uint8_t burstRemaining = 0;
inline uint32_t sent = 0, errors = 0;

inline uint8_t centralMac[6] = {};
inline bool centralKnown = false, centralPeerPending = false;
inline uint32_t centralSeen = 0, centralEpoch = 0, lastBeaconReport = 0;
inline uint8_t centralMask = 0;

inline bool centralFresh(uint32_t now) { return centralKnown && uint32_t(now - centralSeen) < POOL_BEACON_STALE_MS; }
inline bool holding() { return member != 0; }
inline bool releasing(uint32_t now) { return !holding() && int32_t(releaseUntil - now) > 0; }

inline void transmit(uint32_t now, bool forceBroadcast) {
  if (!radioOk) return;
  PoolState packet = {};
  fillHeader(packet.h, POOL_STATE);
  packet.bootId = bootId;
  packet.seq = ++seq;
  packet.leaseMs = POOL_LEASE_DEFAULT_MS;
  packet.radioId = radioId;
  packet.member = member;
  packet.active = member != 0;
  const uint8_t *destination = (!forceBroadcast && centralFresh(now)) ? centralMac : BROADCAST_MAC;
  SendResult result = sendFrame(destination, &packet, sizeof(packet));
  if (result == SEND_DELIVERED || result == SEND_UNCONFIRMED || result == SEND_NO_RESULT) ++sent;
  else ++errors;
  if (!forceBroadcast) lastSend = now;
}

inline int stateFields(char *out, size_t capacity, uint32_t now) {
  char text[18] = "";
  if (centralKnown) formatMac(centralMac, text);
  return snprintf(out, capacity, "\"armed\":%s,\"member\":%u,\"radio_id\":%u,\"central_mac\":\"%s\",\"unicast\":%s,\"radio_mask\":%u,\"epoch\":%lu",
                  boolText(armed), member, radioId, text, boolText(centralFresh(now)), centralMask, (unsigned long)centralEpoch);
}

inline void replyState(const char *event, const char *id, uint32_t now) {
  char fields[200];
  stateFields(fields, sizeof(fields), now);
  reply(event, id, fields);
}

// Hold `newMember` (0 releases). A change bursts; the same member again just refreshes the lease.
inline void set(uint8_t newMember, uint8_t newRadioId, uint32_t now) {
  bool changed = newMember != member || newRadioId != radioId;
  member = newMember;
  radioId = newRadioId;
  armed = member != 0;
  lastHost = now;
  if (changed) {
    burstRemaining = POOL_BURST_COUNT;
    nextBurstAt = 0;
    if (!member) releaseUntil = now + POOL_RELEASE_REPEAT_MS;
  }
}

inline void command(const char *id, const char *line) {
  uint32_t value = 0, radio = radioId;
  if (!jsonUint(line, "member", value) || value > POOL_MEMBER_COUNT) { error(id, "pool needs member: 0 (off) or 1-23"); return; }
  if (jsonValue(line, "radio_id") && (!jsonUint(line, "radio_id", radio) || radio < 1 || radio > POOL_RADIO_COUNT)) {
    error(id, "radio_id must be 1-6"); return;
  }
  uint32_t now = millis();
  set(uint8_t(value), uint8_t(radio), now);
  replyState("pool_state", id, now);
}

inline void touch(uint32_t now) { if (armed) lastHost = now; }  // a late ping cannot re-arm an expired lease

inline void release(const char *why, uint32_t now) {
  if (!armed) return;
  set(0, radioId, now);
  char fields[240];
  int n = snprintf(fields, sizeof(fields), "\"detail\":\"%s\",", why);
  stateFields(fields + n, sizeof(fields) - n, now);
  reply("pool_watchdog", "", fields);
}

inline void pollBeacon(uint32_t now) {
  bool have;
  uint8_t mac[6];
  PoolBeacon beacon;
  portENTER_CRITICAL(&rxMux);
  have = poolBeaconPending;
  poolBeaconPending = false;
  if (have) { memcpy(mac, poolBeaconMac, 6); beacon = poolBeaconFrame; }
  portEXIT_CRITICAL(&rxMux);
  if (!have) return;
  bool moved = !centralKnown || memcmp(centralMac, mac, 6) != 0;
  bool restarted = centralKnown && beacon.epoch != centralEpoch;
  memcpy(centralMac, mac, 6);
  centralKnown = true;
  centralSeen = now;
  centralEpoch = beacon.epoch;
  centralMask = beacon.radioMask;
  if (moved) centralPeerPending = true;
  // A restarted central has forgotten this slot; a moved address was never the central: re-burst.
  if ((moved || restarted) && (holding() || releasing(now))) { burstRemaining = POOL_BURST_COUNT; nextBurstAt = 0; }
  if (moved || restarted || uint32_t(now - lastBeaconReport) >= BEACON_REPORT_MS) {
    lastBeaconReport = now;
    char text[18], fields[160];
    formatMac(mac, text);
    snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"epoch\":%lu,\"uptime_s\":%lu,\"radio_mask\":%u,\"version\":%u", text,
             (unsigned long)beacon.epoch, (unsigned long)beacon.uptimeS, beacon.radioMask, beacon.version);
    reply("pool_beacon", "", fields);
  }
}

inline void poll(uint32_t now) {
  pollBeacon(now);
  // Peers are added here, on the loop task, never from the receive callback. Pinned: the
  // central is unicast to every heartbeat.
  if (centralPeerPending && radioOk && addPeer(centralMac)) centralPeerPending = false;
  if (armed && uint32_t(now - lastHost) >= HOST_TIMEOUT_MS) release("host lease expired; member released", now);
  if (!holding() && !releasing(now)) return;
  if (burstRemaining && int32_t(now - nextBurstAt) >= 0) {
    --burstRemaining;
    nextBurstAt = now + POOL_BURST_GAP_MS;
    transmit(now, false);
  } else if (uint32_t(now - lastSend) >= POOL_HEARTBEAT_MS) {
    transmit(now, false);
  }
  if (centralFresh(now) && uint32_t(now - lastBroadcastCopy) >= POOL_BROADCAST_COPY_MS) {
    lastBroadcastCopy = now;
    transmit(now, true);
  }
}

inline void begin() {
  bootId = esp_random() | 1u;  // a fresh boot identity, so the central accepts the sequence restarting
  seq = 0;
}

}  // namespace pool
}  // namespace ws
