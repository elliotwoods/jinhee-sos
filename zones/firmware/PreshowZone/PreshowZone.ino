// =====================================================
// NCT IMMERSIVE DEEP — PRESHOW TAGGING PLATE (points 1-4)
//
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3), ESP-NOW channel 2.
// Replacement plates are ex-cube XIAO ESP32-C3 boards with the reader on the labelled SDA/SCL pads
// (D4/D5 = GPIO6/GPIO7); the plate finds the reader on either pair.
// Tag -> cube turns PRESHOW (red) and TouchDesigner gets POINT <n> ON; tag removed -> OFF.
//
// The media bridge broadcasts a beacon; this plate latches its address and unicasts events
// back, so the radio gets MAC-layer acknowledgement and hardware retries. On top of that the
// bridge acknowledges each event by sequence, and the plate retries until that acknowledgement
// arrives or PRESHOW_RETRY_WINDOW_MS elapses — so a cue is delivered when the serial line has
// actually been written, not merely when the radio claimed delivery. The current state is then
// re-asserted at a low rate forever, which heals an edge lost while the bridge was away.
// The bridge address is never hardcoded: swapping the bridge board needs no reflash here.
// See NctPreshowProtocol.h.
//
// Cube table, point ID and name live in flash (zones/README.md); flash with zones/flasher.
// =====================================================

#include <Adafruit_PN532.h>
#include <NctTagPlate.h>
#include <NctPreshowProtocol.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "preshow-3.4.0";

uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t LEGACY_BRIDGE_MAC[6] = {PRESHOW_LEGACY_BRIDGE_MAC[0], PRESHOW_LEGACY_BRIDGE_MAC[1],
                                PRESHOW_LEGACY_BRIDGE_MAC[2], PRESHOW_LEGACY_BRIDGE_MAC[3],
                                PRESHOW_LEGACY_BRIDGE_MAC[4], PRESHOW_LEGACY_BRIDGE_MAC[5]};

// Host-driven cue control, for a plate with no reader attached — bench bring-up, and checking
// the TouchDesigner end without a cube. Same shape as PoolZone's override: explicitly armed,
// and leased, so an unplugged laptop cannot leave a cue latched ON for the rest of the show.
constexpr uint32_t HOST_TIMEOUT_MS = 1500;

TagPlate plate;
bool mediaEventActive = false;  // an ON was delivered to the bridge, so we owe it an OFF

// ---- Media link ----
uint32_t mediaBootId = 0;
uint16_t mediaSeq = 0;
// The event currently being delivered. Retransmissions are byte-identical: the sequence
// number identifies the edge, not the frame, which is what makes an acknowledgement
// unambiguous and lets the bridge recognise a retry as the duplicate it is.
PreshowEvent currentEvent = {};
bool eventValid = false, eventAcked = false, failLogged = false;
uint32_t eventSince = 0, lastSend = 0, nextBurstAt = 0, lastBroadcastCopy = 0;
uint8_t burstRemaining = 0;
uint32_t mediaSent = 0, mediaErrors = 0, mediaRetries = 0, mediaFailures = 0, mediaAcks = 0;

uint8_t bridgeMac[6] = {};
bool bridgeKnown = false, bridgeSeesMe = false, bridgePeerPending = false;
uint32_t bridgeSeen = 0, bridgeEpoch = 0, ackLatencyMs = 0;

// Legacy fallback. `bridgeEverSeen` deliberately never goes back to false: once a real bridge
// has introduced itself the plate stays on the current protocol, so a bridge reboot does not
// make it start spraying 2-byte frames again.
bool bridgeEverSeen = false, legacyLogged = false;
uint32_t legacySent = 0;

// Host override.
bool hostArmed = false, hostState = false;
uint8_t hostPoint = 0;  // 0 = use the flashed point
uint32_t lastHost = 0;

// Mailboxes. mediaFrame() runs on the Wi-Fi task and may only hand the frame over.
// One slot each is enough: consecutive beacons supersede one another, and a burst of
// acknowledgements is always a burst for the same event, so keeping the newest is exact.
portMUX_TYPE mediaMux = portMUX_INITIALIZER_UNLOCKED;
bool beaconPending = false, ackPending = false;
uint8_t beaconMac[6] = {};
PreshowBeacon beaconFrame = {};
PreshowAck ackFrame = {};

bool overrideActive() { return hostArmed && millis() - lastHost < HOST_TIMEOUT_MS; }

// The point this plate is currently speaking for. The host may impersonate another one, so a
// single bench board can exercise all four TouchDesigner channels.
uint8_t activePoint() {
  if (overrideActive() && hostPoint) return hostPoint;
  return plate.configOk ? plate.config.pointId : 0;
}

bool mediaPointValid() {
  return plate.configOk && plate.config.zoneType == ZONE_PRESHOW && preshowPointValid(activePoint());
}

bool bridgeFresh() { return bridgeKnown && millis() - bridgeSeen < PRESHOW_BEACON_STALE_MS; }

// True until a real bridge has introduced itself. While it holds, the plate also emits the
// pre-2026 2-byte packet, so it works with the original listener-only bridge that is still on
// the TouchDesigner computer. See the note in NctPreshowProtocol.h.
bool legacyFallback() { return !bridgeEverSeen; }

// Untracked on purpose: retries at this cadence would churn the tag plate's four delivery
// slots and misattribute a cube's acknowledgement. The PreshowAck is the real confirmation.
void transmitEvent(bool forceBroadcast = false) {
  if (!eventValid || !plate.radioOk) return;
  const uint8_t *destination = (!forceBroadcast && bridgeFresh()) ? bridgeMac : BROADCAST_MAC;
  if (plate.sendUntracked(destination, (const uint8_t *)&currentEvent, sizeof(currentEvent), true)) ++mediaSent;
  else ++mediaErrors;
  if (legacyFallback()) {
    // Unicast to the known original bridge for the MAC-layer acknowledgement and retries the
    // old link never had, and a broadcast copy when this pass is the broadcast one, which
    // covers that board having been swapped for another legacy one.
    PreshowLegacy legacy = {currentEvent.pointId, currentEvent.state};
    const uint8_t *legacyTo = forceBroadcast ? BROADCAST_MAC : LEGACY_BRIDGE_MAC;
    if (plate.sendUntracked(legacyTo, (const uint8_t *)&legacy, sizeof(legacy), true)) ++legacySent;
    else ++mediaErrors;
  }
  lastSend = millis();
}

// Begin delivering a new edge: burst it now, then retry until acknowledged or timed out.
// `point` forces the point rather than taking the active one, which matters when the host
// override expires: the OFF has to go to the point the ON went to, not to the flashed one.
bool startEvent(uint8_t state, uint8_t point = 0) {
  uint8_t target = point ? point : activePoint();
  if (!plate.configOk || plate.config.zoneType != ZONE_PRESHOW || !preshowPointValid(target)) {
    Serial.println("MEDIA SKIPPED: zone point not configured");
    return false;
  }
  currentEvent = PreshowEvent{};
  fillHeader(currentEvent.h, PRESHOW_EVENT);
  currentEvent.bootId = mediaBootId;
  currentEvent.seq = ++mediaSeq;
  currentEvent.pointId = target;
  currentEvent.state = state;
  if (state && plate.tagPresent()) {
    currentEvent.uidLength = plate.currentUidLength();
    memcpy(currentEvent.uid, plate.currentUid(), currentEvent.uidLength);
  }
  eventValid = true;
  eventAcked = failLogged = legacyLogged = false;
  eventSince = millis();
  ackLatencyMs = 0;
  burstRemaining = PRESHOW_BURST_COUNT;
  nextBurstAt = 0;
  Serial.printf("MEDIA -> POINT %u %s seq=%u\n", currentEvent.pointId, state ? "ON" : "OFF", currentEvent.seq);
  return true;
}

// Runs on the Wi-Fi task: copy the frame out and return. No Serial, no I2C, no peers.
void mediaFrame(const uint8_t *src, const uint8_t *data, int len) {
  uint8_t type = preshowFrameType(data, len);
  if (type == PRESHOW_BEACON) {
    portENTER_CRITICAL(&mediaMux);
    memcpy(beaconMac, src, 6);
    memcpy(&beaconFrame, data, sizeof(beaconFrame));
    beaconPending = true;
    portEXIT_CRITICAL(&mediaMux);
  } else if (type == PRESHOW_ACK) {
    portENTER_CRITICAL(&mediaMux);
    memcpy(&ackFrame, data, sizeof(ackFrame));
    ackPending = true;
    portEXIT_CRITICAL(&mediaMux);
  }
}

void pollMedia() {
  PreshowBeacon beacon;
  PreshowAck ack;
  uint8_t mac[6];
  bool haveBeacon, haveAck;
  portENTER_CRITICAL(&mediaMux);
  haveBeacon = beaconPending;
  beaconPending = false;
  if (haveBeacon) { memcpy(mac, beaconMac, 6); beacon = beaconFrame; }
  haveAck = ackPending;
  ackPending = false;
  if (haveAck) ack = ackFrame;
  portEXIT_CRITICAL(&mediaMux);

  uint32_t now = millis();
  if (haveBeacon) {
    bool moved = !bridgeKnown || memcmp(bridgeMac, mac, 6) != 0;
    uint32_t previousEpoch = bridgeEpoch;
    if (!bridgeEverSeen) {
      bridgeEverSeen = true;
      Serial.println("MEDIA: bridge found; 2-byte legacy fallback off");
    }
    memcpy(bridgeMac, mac, 6);
    bridgeKnown = true;
    bridgeSeen = now;
    bridgeEpoch = beacon.epoch;
    bridgeSeesMe = mediaPointValid() && (beacon.pointMask & preshowPointBit(activePoint()));
    if (moved) bridgePeerPending = true;
    // A changed epoch means the bridge restarted and has forgotten every point, and a moved
    // address means we were talking to something that is no longer the bridge. Either way the
    // current state has to be delivered again, with a fresh window in which to prove it.
    if (eventValid && (moved || beacon.epoch != previousEpoch)) {
      eventAcked = failLogged = false;
      eventSince = now;
      burstRemaining = PRESHOW_BURST_COUNT;
      nextBurstAt = 0;
    }
  }
  // Peers are added here, on the loop task, never from the receive callback.
  if (bridgePeerPending && plate.radioOk && plate.link.ensurePeer(bridgeMac, true)) bridgePeerPending = false;

  if (haveAck && eventValid && !eventAcked && ack.bootId == currentEvent.bootId &&
      ack.seq == currentEvent.seq && ack.pointId == currentEvent.pointId) {
    eventAcked = true;
    ++mediaAcks;
    ackLatencyMs = now - eventSince;
    Serial.printf("MEDIA ACK point %u %s seq=%u after %lums\n", currentEvent.pointId,
                  currentEvent.state ? "ON" : "OFF", currentEvent.seq, (unsigned long)ackLatencyMs);
  }

  if (!eventValid) return;
  if (burstRemaining && int32_t(now - nextBurstAt) >= 0) {
    --burstRemaining;
    nextBurstAt = now + PRESHOW_BURST_GAP_MS;
    transmitEvent();
  } else if (!eventAcked && int32_t(now - (eventSince + PRESHOW_RETRY_WINDOW_MS)) < 0) {
    if (now - lastSend >= PRESHOW_RETRY_MS) { ++mediaRetries; transmitEvent(); }
  } else if (!eventAcked && legacyFallback() && !legacyLogged) {
    // Not a failure: there is no modern bridge out there to acknowledge anything, and the
    // 2-byte frames this plate is also sending are unacknowledgeable by design. Saying
    // MEDIA FAIL here would report the old bridge as broken every single time a cue fired.
    legacyLogged = true;
    Serial.printf("MEDIA LEGACY: point %u %s seq=%u (2-byte fallback, unacknowledged)\n",
                  currentEvent.pointId, currentEvent.state ? "ON" : "OFF", currentEvent.seq);
  } else if (!eventAcked && !failLogged && !legacyFallback()) {
    // Reported once, and counted where the pairing station's "Query zones" table shows it.
    // The re-assert below keeps running, so this is a diagnosis, not a surrender.
    failLogged = true;
    ++mediaFailures;
    plate.link.noteSendFail();
    Serial.printf("MEDIA FAIL: point %u %s seq=%u unacknowledged after %lums\n", currentEvent.pointId,
                  currentEvent.state ? "ON" : "OFF", currentEvent.seq, (unsigned long)PRESHOW_RETRY_WINDOW_MS);
  }
  // Re-assert forever, acknowledged or not. The bridge writes a serial line only when a
  // point's state actually changes, so this costs TouchDesigner nothing and is what makes a
  // bridge reboot or a spell out of range self-healing.
  if (now - lastSend >= PRESHOW_STATE_REPEAT_MS) transmitEvent();
  // One broadcast copy periodically: rescues a plate that latched an address which has since
  // stopped being the bridge, or whose legacy bridge board has been swapped for another.
  if ((bridgeFresh() || legacyFallback()) && now - lastBroadcastCopy >= PRESHOW_BROADCAST_COPY_MS) {
    lastBroadcastCopy = now;
    transmitEvent(true);
  }
}

// ---- Host override ----
// Raising a cue by hand, for a plate with no reader attached. A real tag always wins: the day
// the PN532 goes on this board, nothing has to be undone.

void hostStatus() {
  Serial.printf("{\"device\":\"PreshowZone\",\"type\":\"host\",\"armed\":%s,\"state\":\"%s\","
                "\"point\":%u,\"configured_point\":%u,\"mode\":\"%s\",\"firmware\":\"%s\","
                "\"seq\":%u,\"acked\":%s,\"ack_ms\":%lu,\"bridge_sees_me\":%s,\"bridge_seen_ms\":%lu,"
                "\"sent\":%lu,\"legacy_sent\":%lu,\"retries\":%lu,\"acks\":%lu,\"failed\":%lu,"
                "\"errors\":%lu,\"nfc\":%s,\"radio\":%s,\"bridge_mac\":\"",
                overrideActive() ? "true" : "false", hostState ? "ON" : "OFF", activePoint(),
                plate.configOk ? plate.config.pointId : 0, legacyFallback() ? "legacy" : "modern",
                FIRMWARE_VERSION, mediaSeq, !eventValid ? "false" : eventAcked ? "true" : "false",
                (unsigned long)ackLatencyMs, bridgeSeesMe ? "true" : "false",
                (unsigned long)(bridgeKnown ? millis() - bridgeSeen : 0), (unsigned long)mediaSent,
                (unsigned long)legacySent, (unsigned long)mediaRetries, (unsigned long)mediaAcks,
                (unsigned long)mediaFailures, (unsigned long)mediaErrors,
                plate.nfcOk ? "true" : "false", plate.radioOk ? "true" : "false");
  if (bridgeKnown) for (uint8_t i = 0; i < 6; ++i) Serial.printf(i ? ":%02X" : "%02X", bridgeMac[i]);
  Serial.println("\"}");
}

// Drop the cue the host was holding, so an unplugged laptop or a closed window cannot leave
// TouchDesigner latched ON for the rest of the show.
void releaseHost(const char *why) {
  uint8_t held = hostPoint;
  bool wasOn = hostState;
  hostArmed = hostState = false;
  hostPoint = 0;
  Serial.printf("EVENT override %s\n", why);
  if (!wasOn) return;
  startEvent(0, held);
  // Put one frame on the air straight away. The normal burst follows from pollMedia, but a
  // real tag arriving in this same pass would replace the edge before any of it went out —
  // and on an impersonated point nothing else would ever turn that cue off.
  transmitEvent();
}

void pollHost() {
  if (hostArmed && millis() - lastHost >= HOST_TIMEOUT_MS) releaseHost("expired");
}

bool hostCue(uint8_t state, uint8_t point) {
  if (!overrideActive()) {
    Serial.println("ERR HOST: send HOST ARM first");
    return true;
  }
  if (state) {
    if (point && !preshowPointValid(point)) {
      Serial.printf("ERR HOST: point must be 1-%u\n", PRESHOW_POINT_COUNT);
      return true;
    }
    uint8_t target = point ? point : (plate.configOk ? plate.config.pointId : 0);
    // Every edge gets its own burst and retry window, so switching points is two commands.
    // Doing it implicitly here would replace the OFF before a single frame of it went out.
    if (hostState && hostPoint && hostPoint != target) {
      Serial.printf("ERR HOST: point %u is still ON; turn it off first\n", hostPoint);
      return true;
    }
    hostPoint = target;
    hostState = startEvent(1, target);
    if (!hostState) hostPoint = 0;
  } else {
    if (hostState) startEvent(0, hostPoint);
    hostState = false;
  }
  hostStatus();
  return true;
}

bool serialCommand(const char *line) {
  if (strncmp(line, "HOST ", 5)) return false;
  const char *rest = line + 5;
  if (!strcmp(rest, "ARM")) {
    hostArmed = true;
    lastHost = millis();
    Serial.println("EVENT override armed");
    hostStatus();
    return true;
  }
  if (!strcmp(rest, "PING")) {
    // A late keepalive cannot re-arm an expired lease — the same rule PoolZone uses. By the
    // time one arrives pollHost() has already released it, so this simply does nothing.
    if (overrideActive()) lastHost = millis();
    return true;
  }
  if (!strcmp(rest, "DISARM")) {
    if (hostArmed) releaseHost("disarmed");
    else Serial.println("EVENT override disarmed");
    hostStatus();
    return true;
  }
  if (!strcmp(rest, "STATUS")) { hostStatus(); return true; }
  if (!strcmp(rest, "OFF")) return hostCue(0, 0);
  if (!strncmp(rest, "ON", 2) && (!rest[2] || rest[2] == ' ')) {
    unsigned point = 0;
    char extra;
    if (rest[2] && sscanf(rest + 3, "%u %c", &point, &extra) != 1) {
      Serial.printf("ERR HOST: expected HOST ON [1-%u]\n", PRESHOW_POINT_COUNT);
      return true;
    }
    return hostCue(1, uint8_t(point));
  }
  Serial.printf("ERR HOST: ARM | PING | DISARM | STATUS | ON [1-%u] | OFF\n", PRESHOW_POINT_COUNT);
  return true;
}

void tagEnter(const uint8_t *, uint8_t, const Record *cube) {
  // A real tag always wins over the bench override, including its impersonated point.
  if (hostArmed) releaseHost("released to a real tag");
  mediaEventActive = false;
  if (!cube) return;  // only registered cubes trigger media
  mediaEventActive = startEvent(1);
}

void tagLeave(const uint8_t *, uint8_t, const Record *) {
  if (mediaEventActive) startEvent(0);
  mediaEventActive = false;
}

void report() {
  Serial.printf("MEDIA: mode=%s point=%u state=%s seq=%u acked=%s ack_ms=%lu bridge_sees_me=%s bridge_seen_ms=%lu "
                "epoch=%lu sent=%lu legacy=%lu retries=%lu acks=%lu failed=%lu errors=%lu bridge_mac=",
                legacyFallback() ? "legacy" : "modern", mediaPointValid() ? activePoint() : 0,
                !eventValid ? "none" : currentEvent.state ? "ON" : "OFF", mediaSeq,
                !eventValid ? "-" : eventAcked ? "yes" : "no", (unsigned long)ackLatencyMs,
                bridgeSeesMe ? "yes" : "no", (unsigned long)(bridgeKnown ? millis() - bridgeSeen : 0),
                (unsigned long)bridgeEpoch, (unsigned long)mediaSent, (unsigned long)legacySent,
                (unsigned long)mediaRetries, (unsigned long)mediaAcks, (unsigned long)mediaFailures,
                (unsigned long)mediaErrors);
  if (bridgeKnown) for (uint8_t i = 0; i < 6; ++i) Serial.printf(i ? ":%02X" : "%02X", bridgeMac[i]);
  else Serial.print("unknown");
  Serial.println(bridgeFresh() ? " (unicast)" : " (broadcast)");
}

void setup() {
  mediaEventActive = eventValid = eventAcked = failLogged = legacyLogged = false;
  bridgeKnown = bridgeSeesMe = bridgePeerPending = bridgeEverSeen = false;
  bridgeSeen = bridgeEpoch = eventSince = lastSend = nextBurstAt = lastBroadcastCopy = ackLatencyMs = 0;
  mediaSent = mediaErrors = mediaRetries = mediaFailures = mediaAcks = legacySent = 0;
  hostArmed = hostState = false;
  hostPoint = 0;
  lastHost = 0;
  burstRemaining = 0;
  beaconPending = ackPending = false;
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT PRESHOW TAG PLATE";
  options.zoneType = ZONE_PRESHOW;
  options.altSdaPin = 6;  // XIAO ESP32-C3 D4
  options.altSclPin = 7;  // XIAO ESP32-C3 D5
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.onFrame = mediaFrame;
  plate.onReport = report;
  plate.onSerial = serialCommand;
  // A fresh boot identity, so the bridge accepts this plate's sequence starting again from
  // zero instead of rejecting it as stale for the rest of the show.
  mediaBootId = esp_random();
  if (!mediaBootId) mediaBootId = 1;
  mediaSeq = 0;
  plate.begin(options);
  // Pinned, because the plate broadcasts until it has heard a beacon and periodically after.
  if (plate.radioOk) {
    plate.link.ensurePeer(BROADCAST_MAC, true);
    // Pinned too: until a beacon arrives this is where the 2-byte fallback goes, and a
    // unicast is what buys the MAC-layer acknowledgement and retries.
    plate.link.ensurePeer(LEGACY_BRIDGE_MAC, true);
  }
  plate.printReport();
}

void loop() {
  plate.loop();
  pollHost();
  pollMedia();
  delay(1);
}
