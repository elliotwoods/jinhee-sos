// =====================================================
// NCT IMMERSIVE DEEP — PRESHOW TAGGING PLATE (points 1-4)
//
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3), ESP-NOW channel 2.
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

constexpr const char *FIRMWARE_VERSION = "preshow-3.1.0";

uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

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

// Mailboxes. mediaFrame() runs on the Wi-Fi task and may only hand the frame over.
// One slot each is enough: consecutive beacons supersede one another, and a burst of
// acknowledgements is always a burst for the same event, so keeping the newest is exact.
portMUX_TYPE mediaMux = portMUX_INITIALIZER_UNLOCKED;
bool beaconPending = false, ackPending = false;
uint8_t beaconMac[6] = {};
PreshowBeacon beaconFrame = {};
PreshowAck ackFrame = {};

bool mediaPointValid() {
  return plate.configOk && plate.config.zoneType == ZONE_PRESHOW && preshowPointValid(plate.config.pointId);
}

bool bridgeFresh() { return bridgeKnown && millis() - bridgeSeen < PRESHOW_BEACON_STALE_MS; }

// Untracked on purpose: retries at this cadence would churn the tag plate's four delivery
// slots and misattribute a cube's acknowledgement. The PreshowAck is the real confirmation.
void transmitEvent(bool forceBroadcast = false) {
  if (!eventValid || !plate.radioOk) return;
  const uint8_t *destination = (!forceBroadcast && bridgeFresh()) ? bridgeMac : BROADCAST_MAC;
  if (plate.sendUntracked(destination, (const uint8_t *)&currentEvent, sizeof(currentEvent), true)) ++mediaSent;
  else ++mediaErrors;
  lastSend = millis();
}

// Begin delivering a new edge: burst it now, then retry until acknowledged or timed out.
bool startEvent(uint8_t state) {
  if (!mediaPointValid()) {
    Serial.println("MEDIA SKIPPED: zone point not configured");
    return false;
  }
  currentEvent = PreshowEvent{};
  fillHeader(currentEvent.h, PRESHOW_EVENT);
  currentEvent.bootId = mediaBootId;
  currentEvent.seq = ++mediaSeq;
  currentEvent.pointId = plate.config.pointId;
  currentEvent.state = state;
  if (state && plate.tagPresent()) {
    currentEvent.uidLength = plate.currentUidLength();
    memcpy(currentEvent.uid, plate.currentUid(), currentEvent.uidLength);
  }
  eventValid = true;
  eventAcked = failLogged = false;
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
    memcpy(bridgeMac, mac, 6);
    bridgeKnown = true;
    bridgeSeen = now;
    bridgeEpoch = beacon.epoch;
    bridgeSeesMe = mediaPointValid() && (beacon.pointMask & preshowPointBit(plate.config.pointId));
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
  } else if (!eventAcked && !failLogged) {
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
  // stopped being the bridge.
  if (bridgeFresh() && now - lastBroadcastCopy >= PRESHOW_BROADCAST_COPY_MS) {
    lastBroadcastCopy = now;
    transmitEvent(true);
  }
}

void tagEnter(const uint8_t *, uint8_t, const Record *cube) {
  mediaEventActive = false;
  if (!cube) return;  // only registered cubes trigger media
  mediaEventActive = startEvent(1);
}

void tagLeave(const uint8_t *, uint8_t, const Record *) {
  if (mediaEventActive) startEvent(0);
  mediaEventActive = false;
}

void report() {
  Serial.printf("MEDIA: point=%u state=%s seq=%u acked=%s ack_ms=%lu bridge_sees_me=%s bridge_seen_ms=%lu "
                "epoch=%lu sent=%lu retries=%lu acks=%lu failed=%lu errors=%lu bridge_mac=",
                mediaPointValid() ? plate.config.pointId : 0,
                !eventValid ? "none" : currentEvent.state ? "ON" : "OFF", mediaSeq,
                !eventValid ? "-" : eventAcked ? "yes" : "no", (unsigned long)ackLatencyMs,
                bridgeSeesMe ? "yes" : "no", (unsigned long)(bridgeKnown ? millis() - bridgeSeen : 0),
                (unsigned long)bridgeEpoch, (unsigned long)mediaSent, (unsigned long)mediaRetries,
                (unsigned long)mediaAcks, (unsigned long)mediaFailures, (unsigned long)mediaErrors);
  if (bridgeKnown) for (uint8_t i = 0; i < 6; ++i) Serial.printf(i ? ":%02X" : "%02X", bridgeMac[i]);
  else Serial.print("unknown");
  Serial.println(bridgeFresh() ? " (unicast)" : " (broadcast)");
}

void setup() {
  mediaEventActive = eventValid = eventAcked = failLogged = false;
  bridgeKnown = bridgeSeesMe = bridgePeerPending = false;
  bridgeSeen = bridgeEpoch = eventSince = lastSend = nextBurstAt = lastBroadcastCopy = ackLatencyMs = 0;
  mediaSent = mediaErrors = mediaRetries = mediaFailures = mediaAcks = 0;
  burstRemaining = 0;
  beaconPending = ackPending = false;
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT PRESHOW TAG PLATE";
  options.zoneType = ZONE_PRESHOW;
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.onFrame = mediaFrame;
  plate.onReport = report;
  // A fresh boot identity, so the bridge accepts this plate's sequence starting again from
  // zero instead of rejecting it as stale for the rest of the show.
  mediaBootId = esp_random();
  if (!mediaBootId) mediaBootId = 1;
  mediaSeq = 0;
  plate.begin(options);
  // Pinned, because the plate broadcasts until it has heard a beacon and periodically after.
  if (plate.radioOk) plate.link.ensurePeer(BROADCAST_MAC, true);
  plate.printReport();
}

void loop() {
  plate.loop();
  pollMedia();
  delay(1);
}
