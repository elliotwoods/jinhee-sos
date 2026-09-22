#pragma once
// Preshow role: a fifth "plate" for the TouchDesigner media bridge, so a host can raise a cue
// without a PreshowZone board. The bridge (zones/firmware/PreshowBridge) accepts a PreshowEvent
// from any address, keeps one point/state per sender and acknowledges every well-formed event,
// so this is the PreshowZone media link ported as is (NctPreshowProtocol.h): latch the bridge's
// beacon and unicast to it, burst three frames on every edge, retry every 120 ms until the ack
// matching bootId+seq+point arrives (report once after 3 s, keep going), re-assert the current
// state every second forever, one broadcast copy a second; and, until a beacon has ever been
// heard, also the pre-2026 2-byte packet to the original bridge board.
//
// One cue per sender at the bridge, so switching points is two commands (OFF, then ON), as
// PreshowZone's HOST override insists. Leased like that override: the host keeps pinging or the
// held cue is turned OFF, so an unplugged laptop cannot leave TouchDesigner latched ON.
#include <string.h>
#include <stdio.h>
#include "WsRadio.h"
#include "WsJson.h"
#include "WsHex.h"

namespace ws {
namespace preshow {

using namespace nctzone;

constexpr uint32_t HOST_TIMEOUT_MS = 1500;
constexpr uint32_t BEACON_REPORT_MS = 5000;

inline uint32_t bootId = 1;
inline uint16_t seq = 0;
inline PreshowEvent currentEvent = {};
inline bool eventValid = false, eventAcked = false, failReported = false;
inline uint32_t eventSince = 0, lastSend = 0, nextBurstAt = 0, lastBroadcastCopy = 0, ackLatencyMs = 0;
inline uint8_t burstRemaining = 0;
inline uint32_t sent = 0, legacySent = 0, retries = 0, acks = 0, failures = 0, errors = 0;

inline uint8_t bridgeMac[6] = {};
inline bool bridgeKnown = false, bridgeEverSeen = false, bridgePeerPending = false, bridgeSeesMe = false;
inline uint32_t bridgeSeen = 0, bridgeEpoch = 0, lastBeaconReport = 0;

// The host's cue: armed while the host holds the lease, `point`/`state` what it asked for.
inline bool armed = false, state = false;
inline uint8_t point = 0;
inline uint32_t lastHost = 0;

inline bool bridgeFresh(uint32_t now) { return bridgeKnown && uint32_t(now - bridgeSeen) < PRESHOW_BEACON_STALE_MS; }
inline bool legacyFallback() { return !bridgeEverSeen; }  // never goes back to true (PreshowZone)

inline void transmit(uint32_t now, bool forceBroadcast) {
  if (!eventValid || !radioOk) return;
  const uint8_t *destination = (!forceBroadcast && bridgeFresh(now)) ? bridgeMac : BROADCAST_MAC;
  SendResult result = sendFrame(destination, &currentEvent, sizeof(currentEvent));
  if (result == SEND_DELIVERED || result == SEND_UNCONFIRMED || result == SEND_NO_RESULT) ++sent;
  else ++errors;
  if (legacyFallback()) {
    PreshowLegacy legacy = {currentEvent.pointId, currentEvent.state};
    const uint8_t *legacyTo = forceBroadcast ? BROADCAST_MAC : PRESHOW_LEGACY_BRIDGE_MAC;
    result = sendFrame(legacyTo, &legacy, sizeof(legacy));
    if (result == SEND_DELIVERED || result == SEND_UNCONFIRMED || result == SEND_NO_RESULT) ++legacySent;
    else ++errors;
  }
  if (!forceBroadcast) lastSend = now;
}

// Begin delivering a new edge: burst it now, then retry until acknowledged or timed out.
inline void startEvent(uint8_t newState, uint8_t target, uint32_t now) {
  currentEvent = PreshowEvent{};
  fillHeader(currentEvent.h, PRESHOW_EVENT);
  currentEvent.bootId = bootId;
  currentEvent.seq = ++seq;
  currentEvent.pointId = target;
  currentEvent.state = newState;
  eventValid = true;
  eventAcked = failReported = false;
  eventSince = now;
  ackLatencyMs = 0;
  burstRemaining = PRESHOW_BURST_COUNT;
  nextBurstAt = 0;
}

inline int stateFields(char *out, size_t capacity, uint32_t now) {
  char text[18] = "";
  if (bridgeKnown) formatMac(bridgeMac, text);
  return snprintf(out, capacity,
                  "\"armed\":%s,\"point\":%u,\"state\":%u,\"seq\":%u,\"acked\":%s,\"ack_ms\":%lu,\"bridge_mac\":\"%s\",\"unicast\":%s,"
                  "\"mode\":\"%s\",\"bridge_sees_me\":%s",
                  boolText(armed), point, state ? 1 : 0, seq, boolText(eventValid && eventAcked), (unsigned long)ackLatencyMs,
                  text, boolText(bridgeFresh(now)), legacyFallback() ? "legacy" : "modern", boolText(bridgeSeesMe));
}

inline void replyState(const char *event, const char *id, uint32_t now) {
  char fields[260];
  stateFields(fields, sizeof(fields), now);
  reply(event, id, fields);
}

inline void command(const char *id, const char *line) {
  uint32_t newPoint = 0, newState = 0;
  if (!jsonUint(line, "point", newPoint) || !preshowPointValid(uint8_t(newPoint))) { error(id, "preshow needs point: 1-4"); return; }
  if (!jsonUint(line, "state", newState) || newState > 1) { error(id, "preshow needs state: 1 (ON) or 0 (OFF)"); return; }
  uint32_t now = millis();
  if (newState) {
    // Every edge gets its own burst and retry window, so switching points is two commands.
    // Doing it implicitly here would replace the OFF before a single frame of it went out.
    if (state && point != newPoint) {
      char detail[80];
      snprintf(detail, sizeof(detail), "Point %u is still ON; turn it off first", point);
      error(id, detail);
      return;
    }
    armed = true;
    lastHost = now;
    if (!state || point != newPoint) startEvent(1, uint8_t(newPoint), now);  // the same ON again just refreshes the lease
    point = uint8_t(newPoint);
    state = true;
  } else {
    if (state && point == newPoint) startEvent(0, point, now);
    else if (state) { error(id, "That point is not the one held ON"); return; }
    state = false;
    if (armed) lastHost = now;
  }
  replyState("preshow_state", id, now);
}

inline void touch(uint32_t now) { if (armed) lastHost = now; }

// Drop the cue the host was holding: OFF for the point the ON went to.
inline void release(const char *why, uint32_t now) {
  if (!armed) return;
  bool wasOn = state;
  uint8_t held = point;
  armed = state = false;
  if (wasOn) {
    startEvent(0, held, now);
    transmit(now, false);  // one frame on the air straight away
  }
  char fields[300];
  int n = snprintf(fields, sizeof(fields), "\"detail\":\"%s\",", why);
  stateFields(fields + n, sizeof(fields) - n, now);
  reply("preshow_watchdog", "", fields);
}

inline void pollMailboxes(uint32_t now) {
  bool haveBeacon, haveAck;
  uint8_t mac[6];
  PreshowBeacon beacon;
  PreshowAck ack;
  portENTER_CRITICAL(&rxMux);
  haveBeacon = preshowBeaconPending;
  preshowBeaconPending = false;
  if (haveBeacon) { memcpy(mac, preshowBeaconMac, 6); beacon = preshowBeaconFrame; }
  haveAck = preshowAckPending;
  preshowAckPending = false;
  if (haveAck) ack = preshowAckFrame;
  portEXIT_CRITICAL(&rxMux);

  if (haveBeacon) {
    bool moved = !bridgeKnown || memcmp(bridgeMac, mac, 6) != 0;
    bool restarted = bridgeKnown && beacon.epoch != bridgeEpoch;
    bool first = !bridgeEverSeen;
    bridgeEverSeen = true;
    memcpy(bridgeMac, mac, 6);
    bridgeKnown = true;
    bridgeSeen = now;
    bridgeEpoch = beacon.epoch;
    bridgeSeesMe = eventValid && currentEvent.state && (beacon.pointMask & preshowPointBit(currentEvent.pointId));
    if (moved) bridgePeerPending = true;
    // A changed epoch means the bridge restarted and has forgotten every point, and a moved
    // address means we were talking to something that is no longer the bridge: deliver again.
    if (eventValid && (moved || restarted)) {
      eventAcked = failReported = false;
      eventSince = now;
      burstRemaining = PRESHOW_BURST_COUNT;
      nextBurstAt = 0;
    }
    if (first || moved || restarted || uint32_t(now - lastBeaconReport) >= BEACON_REPORT_MS) {
      lastBeaconReport = now;
      char text[18], fields[160];
      formatMac(mac, text);
      snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"epoch\":%lu,\"uptime_s\":%lu,\"point_mask\":%u,\"version\":%u", text,
               (unsigned long)beacon.epoch, (unsigned long)beacon.uptimeS, beacon.pointMask, beacon.version);
      reply("preshow_beacon", "", fields);
    }
  }
  if (bridgePeerPending && radioOk && addPeer(bridgeMac)) bridgePeerPending = false;

  if (haveAck && eventValid && !eventAcked && ack.bootId == currentEvent.bootId && ack.seq == currentEvent.seq &&
      ack.pointId == currentEvent.pointId) {
    eventAcked = true;
    ++acks;
    ackLatencyMs = now - eventSince;
    char fields[120];
    snprintf(fields, sizeof(fields), "\"point\":%u,\"state\":%u,\"seq\":%u,\"ms\":%lu,\"applied\":%s", currentEvent.pointId,
             currentEvent.state, currentEvent.seq, (unsigned long)ackLatencyMs, boolText(ack.flags & PRESHOW_ACK_APPLIED));
    reply("preshow_ack", "", fields);
  }
}

inline void poll(uint32_t now) {
  pollMailboxes(now);
  if (armed && uint32_t(now - lastHost) >= HOST_TIMEOUT_MS) release("host lease expired; cue turned off", now);
  if (!eventValid) return;
  if (burstRemaining && int32_t(now - nextBurstAt) >= 0) {
    --burstRemaining;
    nextBurstAt = now + PRESHOW_BURST_GAP_MS;
    transmit(now, false);
  } else if (!eventAcked && int32_t(now - (eventSince + PRESHOW_RETRY_WINDOW_MS)) < 0) {
    if (uint32_t(now - lastSend) >= PRESHOW_RETRY_MS) { ++retries; transmit(now, false); }
  } else if (!eventAcked && !failReported && !legacyFallback()) {
    // Reported once; the re-assert below keeps running, so this is a diagnosis, not a surrender.
    // With no modern bridge out there (legacy mode) nothing can acknowledge, so nothing is reported.
    failReported = true;
    ++failures;
    char fields[80];
    snprintf(fields, sizeof(fields), "\"point\":%u,\"state\":%u,\"seq\":%u", currentEvent.pointId, currentEvent.state, currentEvent.seq);
    reply("preshow_fail", "", fields);
  }
  if (uint32_t(now - lastSend) >= PRESHOW_STATE_REPEAT_MS) transmit(now, false);
  if ((bridgeFresh(now) || legacyFallback()) && uint32_t(now - lastBroadcastCopy) >= PRESHOW_BROADCAST_COPY_MS) {
    lastBroadcastCopy = now;
    transmit(now, true);
  }
}

inline void begin() {
  bootId = esp_random();
  if (!bootId) bootId = 1;
  seq = 0;
  // Pinned: until a beacon arrives the 2-byte fallback is unicast here for the MAC-layer
  // acknowledgement and retries the old link never had.
  if (radioOk) addPeer(PRESHOW_LEGACY_BRIDGE_MAC);
}

}  // namespace preshow
}  // namespace ws
