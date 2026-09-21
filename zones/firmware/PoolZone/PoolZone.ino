// =====================================================
// NCT IMMERSIVE DEEP — POOL ZONE RADIO
//
// ESP32-C3 SuperMini + PN532 + VL53L4CD slider (I2C SDA GPIO4 / SCL GPIO3) + 12 V LED strip MOSFET on GPIO5.
// NeoCube tag (700 ms removal timeout) or explicitly armed USB override activates output.
// PoolState to the pool central: unicast to the beacon-latched address for ESP-NOW
// acknowledgement and retries, a burst on every change, a repeated release, a periodic
// broadcast copy, and idle heartbeats so silence means a fault. See NctPoolProtocol.h.
// Registered NeoCubes receive POOL via the shared tag core.
// CAL commands edit 23 ticks; outputs pause during unsaved calibration uploads.
// CAL SAVE persists to NVS. Legacy endpoints seed an unsaved initial calibration.
// TUNE commands edit filter/decision parameters live; TUNE SAVE persists them.
// RAW ON streams every sensor sample for host-side filter tuning.
// =====================================================

#include <Adafruit_PN532.h>
#include <VL53L4CD.h>
#include <NctTagPlate.h>
#include <NctPoolProtocol.h>
#include <Preferences.h>
#include "SliderCalibration.h"
#include "SliderTuning.h"
#include "OneEuroFilter.h"

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "pool-3.2.0";
// Embedded by the zone builder for exact-source update detection.
#ifndef POOL_BUILD_ID
#define POOL_BUILD_ID unknown
#endif
#define POOL_STRINGIFY_INNER(x) #x
#define POOL_STRINGIFY(x) POOL_STRINGIFY_INNER(x)
constexpr const char *FIRMWARE_BUILD_ID = POOL_STRINGIFY(POOL_BUILD_ID);

#define STRIP_LED_PIN 5
#define MEMBER_COUNT POOL_MEMBER_COUNT
#define HEARTBEAT_MS POOL_HEARTBEAT_MS

uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

TagPlate plate;
VL53L4CD laser;
bool laserOk = false, streamDistance = false;
float calPos1 = 0, calPos23 = 0;
SliderCalibration calibration;
SliderTuning tuning;
bool calibrationSaved = false, tuningSaved = false, sampleValid = false;
bool rawStream = false;
uint32_t rawDropped = 0;
uint8_t rangeStatus = 0;
uint16_t sampleIntervalMs = 10;
constexpr uint32_t OVERRIDE_TIMEOUT_MS = 1500;
bool hostArmed = false, calibrationEditing = false;
uint32_t lastHost = 0, centralQueued = 0, centralErrors = 0, lastDebug = 0;
int lastOutput = -1;
uint32_t lastSample = 0, lastTelemetry = 0;

void calibrationReport() {
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"calibration\",\"saved\":%s,\"valid\":%s,\"ticks\":[", calibrationSaved ? "true" : "false", calibration.valid() ? "true" : "false");
  for (int i = 0; i < 23; ++i) Serial.printf(i ? ",%.2f" : "%.2f", calibration.mm[i]);
  Serial.printf("],\"anchors\":%lu,\"firmware\":\"%s\",\"build_id\":\"%s\"}\n", (unsigned long)calibration.anchors, FIRMWARE_VERSION, FIRMWARE_BUILD_ID);
}

bool loadCalibration() {
  Preferences prefs;
  if (!prefs.begin("pool-slider", true)) return false;
  SliderCalibration loaded;
  bool ok = prefs.getBytesLength("ticks-v1") == sizeof(loaded) && prefs.getBytes("ticks-v1", &loaded, sizeof(loaded)) == sizeof(loaded) && loaded.valid();
  prefs.end();
  if (ok) calibration = loaded;
  return ok;
}

bool saveCalibration() {
  if (!calibration.valid()) return false;
  Preferences prefs;
  if (!prefs.begin("pool-slider", false)) return false;
  SliderCalibration check;
  bool ok = prefs.putBytes("ticks-v1", &calibration, sizeof(calibration)) == sizeof(calibration) &&
            prefs.getBytes("ticks-v1", &check, sizeof(check)) == sizeof(check) && !memcmp(&check, &calibration, sizeof(check));
  prefs.end();
  return ok;
}

void tuningReport() {
  SliderTuning d;
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"tuning\",\"saved\":%s,\"valid\":%s,"
                "\"min_cutoff_hz\":%.4f,\"beta\":%.5f,\"derivative_cutoff_hz\":%.4f,"
                "\"enter_frac\":%.4f,\"exit_frac\":%.4f,\"confirm_ms\":%u,\"release_ms\":%u,"
                "\"dropout_ms\":%u,\"timing_budget_ms\":%u,\"interval_ms\":%u,\"median_window\":%u,",
                tuningSaved ? "true" : "false", tuning.valid() ? "true" : "false",
                tuning.minCutoffHz, tuning.beta, tuning.derivativeCutoffHz, tuning.enterFrac, tuning.exitFrac,
                tuning.confirmMs, tuning.releaseMs, tuning.dropoutMs, tuning.timingBudgetMs, tuning.intervalMs,
                tuning.medianWindow);
  Serial.printf("\"defaults\":{\"min_cutoff_hz\":%.4f,\"beta\":%.5f,\"derivative_cutoff_hz\":%.4f,"
                "\"enter_frac\":%.4f,\"exit_frac\":%.4f,\"confirm_ms\":%u,\"release_ms\":%u,"
                "\"dropout_ms\":%u,\"timing_budget_ms\":%u,\"interval_ms\":%u,\"median_window\":%u}}\n",
                d.minCutoffHz, d.beta, d.derivativeCutoffHz, d.enterFrac, d.exitFrac, d.confirmMs,
                d.releaseMs, d.dropoutMs, d.timingBudgetMs, d.intervalMs, d.medianWindow);
}

bool loadTuning() {
  Preferences prefs;
  if (!prefs.begin("pool-slider", true)) return false;
  SliderTuning loaded;
  bool ok = prefs.getBytesLength("tune-v1") == sizeof(loaded) && prefs.getBytes("tune-v1", &loaded, sizeof(loaded)) == sizeof(loaded) && loaded.valid();
  prefs.end();
  if (ok) tuning = loaded;
  return ok;
}

bool saveTuning() {
  if (!tuning.valid()) return false;
  Preferences prefs;
  if (!prefs.begin("pool-slider", false)) return false;
  SliderTuning check;
  bool ok = prefs.putBytes("tune-v1", &tuning, sizeof(tuning)) == sizeof(tuning) &&
            prefs.getBytes("tune-v1", &check, sizeof(check)) == sizeof(check) && !memcmp(&check, &tuning, sizeof(check));
  prefs.end();
  return ok;
}
OneEuroFilter distanceFilter;
MedianFilter medianFilter;
float rawDistance = 0, filteredDistance = 0;
int candidatePosition = -1, confirmedPosition = -1;
uint32_t candidateSince = 0, lastRangeRead = 0, lastHeartbeat = 0, lastStream = 0;

// ---- Pool link ----
// The central broadcasts a beacon; we latch its address and unicast our state back, so
// the radio gets MAC-layer acknowledgement and hardware retries instead of shouting into
// a shared channel. One broadcast copy still goes out periodically, which costs nothing
// (the central de-duplicates on sequence) and covers a stale or wrong latched address.
uint32_t poolBootId = 0;
uint16_t poolSeq = 0;
uint8_t centralMac[6] = {};
bool centralKnown = false, centralSeesMe = false;
uint32_t centralSeen = 0, centralEpoch = 0;
uint32_t lastBroadcastCopy = 0, releaseUntil = 0, nextBurstAt = 0;
uint8_t burstRemaining = 0;
bool centralPeerPending = false;

// Beacon mailbox. poolFrame() runs on the Wi-Fi task and may only hand the frame over.
portMUX_TYPE poolMux = portMUX_INITIALIZER_UNLOCKED;
bool beaconPending = false;
uint8_t beaconMac[6] = {};
PoolBeacon beaconFrame = {};

bool centralFresh() { return centralKnown && millis() - centralSeen < POOL_BEACON_STALE_MS; }
// 0 means "not currently in a run"; millis() 0 is stored as 1 so the sentinel holds.
uint32_t releaseSince = 0;

// sampleValid means "the last read was good" and drives the telemetry the calibration
// GUI captures control points from, so it must go false the moment a read fails.
// sliderLive() means "a good read is recent enough to keep driving the output", which
// is what tolerates a short dropout without releasing the member.
bool sliderLive(uint32_t now) { return lastSample && now - lastSample <= tuning.dropoutMs; }

// Applied live so an operator sees the effect of a parameter before committing it.
// Filter history is deliberately preserved: re-seeding would itself look like a glitch.
void applyTuning(const SliderTuning &previous, bool retime) {
  distanceFilter.configure(tuning.minCutoffHz, tuning.beta, tuning.derivativeCutoffHz, tuning.dropoutMs);
  medianFilter.configure(tuning.medianWindow);
  sampleIntervalMs = tuning.pollIntervalMs();
  if (!retime || !laserOk) return;
  laser.stopContinuous();
  if (!laser.setRangeTiming(uint8_t(tuning.timingBudgetMs), tuning.intervalMs)) {
    // Never leave the sensor unconfigured: put back the timing that was working.
    tuning.timingBudgetMs = previous.timingBudgetMs;
    tuning.intervalMs = previous.intervalMs;
    laser.setRangeTiming(uint8_t(tuning.timingBudgetMs), tuning.intervalMs);
    sampleIntervalMs = tuning.pollIntervalMs();
    Serial.println("ERR TUNE: sensor rejected timing; previous timing kept");
  }
  laser.startContinuous();
  lastRangeRead = millis();
}

bool radioValid() { return plate.configOk && plate.config.pointId >= 1 && plate.config.pointId <= 6; }
bool calibrationValid() { return calibration.valid(); }

void sendCentralState(bool active, bool forceBroadcast = false) {
  if (!radioValid() || !plate.radioOk) return;
  PoolState packet = {};
  fillHeader(packet.h, POOL_STATE);
  packet.bootId = poolBootId;
  packet.seq = ++poolSeq;
  packet.leaseMs = POOL_LEASE_DEFAULT_MS;
  packet.radioId = plate.config.pointId;
  if (active && confirmedPosition >= 1 && confirmedPosition <= MEMBER_COUNT) {
    packet.active = 1;
    packet.member = confirmedPosition;
  }
  if (active && plate.tagPresent()) {
    packet.uidLength = plate.currentUidLength();
    memcpy(packet.uid, plate.currentUid(), packet.uidLength);
  }
  bool unicast = !forceBroadcast && centralFresh();
  const uint8_t *destination = unicast ? centralMac : BROADCAST_MAC;
  // Untracked on purpose: at this rate the tag plate's four delivery slots would churn
  // and misattribute a cube's acknowledgement. The beacon's radioMask is the real
  // application-level confirmation that the central is hearing this radio.
  if (plate.sendUntracked(destination, (const uint8_t *)&packet, sizeof(packet), true)) ++centralQueued;
  else ++centralErrors;
}

// Re-assert the current state immediately and a couple more times in quick succession.
// A lost heartbeat costs at most one lease of blink; a lost change or release is visible
// for a whole lease, so changes are the ones worth repeating.
void startBurst() { burstRemaining = POOL_BURST_COUNT; nextBurstAt = 0; }

// Runs on the Wi-Fi task: copy the frame out and return. No Serial, no I2C, no peers.
void poolFrame(const uint8_t *src, const uint8_t *data, int len) {
  if (poolFrameType(data, len) != POOL_BEACON) return;
  portENTER_CRITICAL(&poolMux);
  memcpy(beaconMac, src, 6);
  memcpy(&beaconFrame, data, sizeof(beaconFrame));
  beaconPending = true;
  portEXIT_CRITICAL(&poolMux);
}

void pollBeacon() {
  PoolBeacon beacon;
  uint8_t mac[6];
  bool pending;
  portENTER_CRITICAL(&poolMux);
  pending = beaconPending;
  beaconPending = false;
  if (pending) { memcpy(mac, beaconMac, 6); beacon = beaconFrame; }
  portEXIT_CRITICAL(&poolMux);
  if (pending) {
    bool moved = !centralKnown || memcmp(centralMac, mac, 6) != 0;
    uint32_t previousEpoch = centralEpoch;
    memcpy(centralMac, mac, 6);
    centralKnown = true;
    centralSeen = millis();
    centralEpoch = beacon.epoch;
    centralSeesMe = radioValid() && (beacon.radioMask & (1 << (plate.config.pointId - 1)));
    if (moved) centralPeerPending = true;
    // A changed epoch means the central restarted and has forgotten every lease, so
    // re-assert at once rather than waiting for the next slider movement.
    if (moved || beacon.epoch != previousEpoch) startBurst();
  }
  // Peers are added here, on the loop task, never from the receive callback.
  if (centralPeerPending && plate.radioOk && plate.link.ensurePeer(centralMac, true)) centralPeerPending = false;
}

bool overrideActive() { return hostArmed && millis() - lastHost < OVERRIDE_TIMEOUT_MS; }
bool interactionActive() { return plate.tagPresent() || overrideActive(); }
int outputMember() {
  return interactionActive() && !calibrationEditing && sliderLive(millis()) && calibrationValid() && confirmedPosition > 0 ? confirmedPosition : 0;
}

void updateInteraction() {
  uint32_t now = millis();
  if (hostArmed && now-lastHost >= OVERRIDE_TIMEOUT_MS) {
    hostArmed = false;
    Serial.println("EVENT override expired");
  }
  digitalWrite(STRIP_LED_PIN, interactionActive() ? HIGH : LOW);
  pollBeacon();
  int output = outputMember();
  if (output != lastOutput) {
    // Keep re-asserting a release for a while: a lost release leaves a light stuck on for
    // a whole lease, which is far more visible than a lost heartbeat.
    if (output == 0) releaseUntil = now + POOL_RELEASE_REPEAT_MS;
    lastOutput = output;
    startBurst();
  }
  bool releasing = output == 0 && int32_t(releaseUntil - now) > 0;
  uint32_t interval = (interactionActive() || releasing) ? HEARTBEAT_MS : POOL_IDLE_HEARTBEAT_MS;
  if (burstRemaining && int32_t(now - nextBurstAt) >= 0) {
    --burstRemaining;
    nextBurstAt = now + POOL_BURST_GAP_MS;
    sendCentralState(output > 0);
    lastHeartbeat = millis();
  } else if (now - lastHeartbeat >= interval) {
    // Idle heartbeats never stop. They cost almost nothing and turn a silent radio into a
    // reportable fault instead of something indistinguishable from an idle slider.
    sendCentralState(output > 0);
    lastHeartbeat = millis();
  }
  // One broadcast copy periodically, whatever the unicast link is doing. This is what
  // rescues a radio that latched a stale central address.
  if (centralFresh() && now - lastBroadcastCopy >= POOL_BROADCAST_COPY_MS) {
    lastBroadcastCopy = now;
    sendCentralState(output > 0, true);
  }
}

void interactionReport() {
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"interaction\",\"override\":%s,\"active\":%s,\"output\":%d,\"tag\":%s,\"nfc\":%s,\"radio\":%s,\"radio_id\":%u,\"queued\":%lu,\"send_errors\":%lu,\"cube\":%lu,\"delivery\":%d,\"seq\":%u,\"unicast\":%s,\"central_sees_me\":%s,\"central_seen_ms\":%lu,\"central_mac\":\"",
    overrideActive() ? "true" : "false", interactionActive() ? "true" : "false", outputMember(), plate.tagPresent() ? "true" : "false", plate.nfcOk ? "true" : "false", plate.radioOk && radioValid() ? "true" : "false", plate.config.pointId,
    (unsigned long)centralQueued, (unsigned long)centralErrors, (unsigned long)(plate.tagPresent() ? plate.currentCube().cubeID : 0), plate.currentDelivery(),
    poolSeq, centralFresh() ? "true" : "false", centralSeesMe ? "true" : "false",
    (unsigned long)(centralKnown ? millis() - centralSeen : 0));
  if (centralKnown) for (uint8_t i=0; i<6; ++i) Serial.printf(i ? ":%02X" : "%02X", centralMac[i]);
  Serial.print("\",\"uid\":\"");
  if (plate.tagPresent()) for (uint8_t i=0; i<plate.currentUidLength(); ++i) Serial.printf(i ? ":%02X" : "%02X", plate.currentUid()[i]);
  Serial.print("\",\"mac\":\"");
  if (plate.tagPresent() && plate.currentCube().cubeID) for (uint8_t i=0; i<6; ++i) Serial.printf(i ? ":%02X" : "%02X", plate.currentCube().mac[i]);
  Serial.println("\"}");
}

int distanceToMember(float distance) {
  return calibration.select(distance);
}

void rawReport(uint32_t now) {
  if (!rawStream) return;
  // USB CDC write() blocks when the host stops draining the port, which would stall the
  // sample cadence and the central heartbeat. Drop this line rather than block, and stop
  // streaming entirely if the port goes away.
  if (!Serial) { rawStream = false; return; }
  if (Serial.availableForWrite() < 160) { ++rawDropped; return; }
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"raw\",\"t\":%lu,\"mm\":", (unsigned long)now);
  if (sampleValid) Serial.printf("%.0f", rawDistance); else Serial.print("null");
  // A tolerated dropout does not advance the filter, so there is no fresh filtered
  // value to report; null rather than repeating a stale one.
  Serial.print(",\"f\":");
  if (sampleValid) Serial.printf("%.2f", filteredDistance); else Serial.print("null");
  Serial.printf(",\"st\":%u,\"idx\":%d}\n", rangeStatus, confirmedPosition);
}

// The single release path, shared by the per-sample dropout and the staleness watchdog
// so the two can never disagree about what "released" means.
void releaseSlider(uint32_t now) {
  distanceFilter.reset();
  medianFilter.reset();
  candidatePosition = confirmedPosition = -1;
  candidateSince = now;
  releaseSince = 0;
}

void processSlider() {
  uint32_t now = millis();
  if (!laserOk || now - lastRangeRead < sampleIntervalMs) return;
  lastRangeRead = now;
  if (!laser.dataReady()) return;
  uint16_t distance = laser.readRangeContinuousMillimeters(false);
  rangeStatus = laser.ranging_data.range_status;
  sampleValid = !laser.timeoutOccurred() && rangeStatus == 0 && distance >= 10 && distance <= 1000;
  if (!sampleValid) {
    // A single bad reading used to reset the filter and drop the output outright,
    // which showed up as a flickering relay. Hold the member for dropoutMs instead.
    if (!sliderLive(now)) releaseSlider(now);
    rawReport(now);
    return;
  }
  lastSample = now;
  rawDistance = distance;
  filteredDistance = distanceFilter.update(medianFilter.update(rawDistance), now);
  int member = calibration.select(filteredDistance, confirmedPosition, tuning.enterFrac, tuning.exitFrac);
  if (member != candidatePosition) { candidatePosition = member; candidateSince = now; }
  uint32_t held = now - candidateSince;
  // Entering a member needs confirmMs of agreement; leaving the confirmed member needs
  // releaseMs of sustained disagreement. Both directions are debounced, where 2.7.0
  // debounced only entry. When releaseMs >= confirmMs the two branches collapse into
  // one pass, so a normal tick-to-tick slide never emits an intermediate member 0.
  if (confirmedPosition >= 1 && candidatePosition != confirmedPosition && held >= tuning.releaseMs)
    confirmedPosition = -1;
  if (confirmedPosition < 1 && candidatePosition >= 1 && held >= tuning.confirmMs)
    confirmedPosition = candidatePosition;
  rawReport(now);
  if (streamDistance && now - lastStream >= 250) {
    lastStream = now;
    Serial.printf("DIST=%.1f MEMBER=%d TAG=%s\n", filteredDistance, confirmedPosition, plate.tagPresent() ? "ON" : "OFF");
  }
}

void telemetry() {
  uint32_t now = millis();
  // Backstop for a sensor that stops delivering readings at all, where the per-sample
  // dropout path never runs. staleMs() is always above dropoutMs so this cannot fire
  // first and make dropout tolerance inert.
  if (now - lastSample > tuning.staleMs() && (sampleValid || confirmedPosition > 0)) {
    sampleValid = false;
    releaseSlider(now);
  }
  if (now - lastTelemetry < 100) return;
  lastTelemetry = now;
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"sample\",\"sensor\":%s,\"distance\":", sampleValid ? "true" : "false");
  if (sampleValid) Serial.printf("%.2f", filteredDistance); else Serial.print("null");
  Serial.print(",\"raw_distance\":");
  if (sampleValid) Serial.printf("%.2f", rawDistance); else Serial.print("null");
  Serial.printf(",\"index\":%d,\"valid\":%s,\"saved\":%s}\n", confirmedPosition, calibrationValid() ? "true" : "false", calibrationSaved ? "true" : "false");
  interactionReport();
  if (now-lastDebug >= 1000) { lastDebug = now; plate.printNfc(); }
}

void tagEnter(const uint8_t *, uint8_t, const Record *) {
  Serial.printf("===== NEOCORE ON ===== MEMBER = %d\n", confirmedPosition);
  lastOutput = -1;  // refresh the UID even if an override already selected this member
  updateInteraction();
}

void tagLeave(const uint8_t *, uint8_t, const Record *) {
  Serial.println("===== NEOCORE OFF =====");
  lastOutput = -1;
  updateInteraction();
}

// Applies one named field to a copy, so an out-of-range value is rejected whole.
bool tuningAssign(SliderTuning &t, const char *key, float value) {
  if (!isfinite(value)) return false;
  // Guard the magnitude before any integer conversion: lround/uint16_t casts of a
  // negative or huge float are undefined behaviour, which the test harness's UBSan
  // build treats as a failure.
  if (value < -1.0f || value > 65535.0f) return false;
  auto whole = [&](long lo, long hi, uint16_t &field) {
    long v = lround(value);
    if (v < lo || v > hi) return false;
    field = uint16_t(v); return true;
  };
  if (!strcmp(key, "mincutoff")) { t.minCutoffHz = value; return true; }
  if (!strcmp(key, "beta")) { t.beta = value; return true; }
  if (!strcmp(key, "dcutoff")) { t.derivativeCutoffHz = value; return true; }
  if (!strcmp(key, "enter")) { t.enterFrac = value; return true; }
  if (!strcmp(key, "exit")) { t.exitFrac = value; return true; }
  if (!strcmp(key, "confirm")) return whole(0, 2000, t.confirmMs);
  if (!strcmp(key, "release")) return whole(0, 2000, t.releaseMs);
  if (!strcmp(key, "dropout")) return whole(0, 2000, t.dropoutMs);
  if (!strcmp(key, "budget")) return whole(10, 200, t.timingBudgetMs);
  if (!strcmp(key, "interval")) return whole(0, 1000, t.intervalMs);
  if (!strcmp(key, "median")) {
    long v = lround(value);
    if (v < 1 || v > 9 || !(v & 1)) return false;
    t.medianWindow = uint8_t(v); return true;
  }
  return false;
}

bool tuneCommand(const char *line) {
  if (!strcmp(line, "TUNE GET")) { tuningReport(); return true; }
  if (!strcmp(line, "TUNE SAVE")) {
    tuningSaved = saveTuning();
    Serial.println(tuningSaved ? "OK TUNE SAVE" : "ERR TUNE SAVE: invalid parameters or flash failure");
    tuningReport(); return true;
  }
  if (!strcmp(line, "TUNE LOAD")) {
    SliderTuning previous = tuning;
    tuningSaved = loadTuning();
    if (!tuningSaved) tuning = SliderTuning();
    applyTuning(previous, true);
    Serial.println(tuningSaved ? "OK TUNE LOAD" : "ERR no saved tuning; firmware defaults applied");
    tuningReport(); return true;
  }
  if (!strcmp(line, "TUNE DEFAULTS")) {
    SliderTuning previous = tuning;
    tuning = SliderTuning();
    tuningSaved = false;
    applyTuning(previous, true);
    Serial.println("OK TUNE DEFAULTS");
    tuningReport(); return true;
  }
  if (strncmp(line, "TUNE SET ", 9)) return false;
  char key[16]; float value; char extra;
  if (sscanf(line + 9, "%15s %f %c", key, &value, &extra) != 2) {
    Serial.println("ERR TUNE SET: expected <key> <value>"); return true;
  }
  SliderTuning candidate = tuning;
  if (!tuningAssign(candidate, key, value) || !candidate.valid()) {
    Serial.println("ERR TUNE SET: unknown key or value out of range"); return true;
  }
  SliderTuning previous = tuning;
  bool retime = candidate.timingBudgetMs != previous.timingBudgetMs || candidate.intervalMs != previous.intervalMs;
  tuning = candidate;
  tuningSaved = false;
  // Applied live and without pausing output: watching the change take effect is the point.
  applyTuning(previous, retime);
  tuningReport(); return true;
}

bool serialCommand(const char *line) {
  if (!strncmp(line, "TUNE ", 5)) return tuneCommand(line);
  if (!strncmp(line, "RAW ", 4)) {
    // Never persisted and off at boot: USB CDC writes block when the host stops
  // reading, which would wreck the sample cadence and the 150 ms heartbeat.
  if (!strcmp(line + 4, "ON")) { rawStream = true; rawDropped = 0; }
    else if (!strcmp(line + 4, "OFF")) rawStream = false;
    else { Serial.println("ERR RAW: expected ON or OFF"); return true; }
    Serial.printf("OK RAW %s dropped=%lu\n", rawStream ? "ON" : "OFF", (unsigned long)rawDropped);
    return true;
  }
  if (!strcmp(line, "HOST ARM")) {
    hostArmed = true; lastHost = millis(); updateInteraction(); interactionReport(); return true;
  }
  if (!strcmp(line, "HOST PING")) {
    // A late keepalive cannot re-arm an expired lease.
    if (overrideActive()) lastHost = millis(); else hostArmed = false;
    return true;
  }
  if (!strcmp(line, "HOST DISARM")) {
    hostArmed = false; updateInteraction(); interactionReport(); return true;
  }
  if (!strcmp(line, "HOST STATUS")) { interactionReport(); return true; }
  if (!strcmp(line, "CAL GET")) { calibrationReport(); return true; }
  if (!strcmp(line, "CAL SAVE")) {
    calibrationSaved = saveCalibration();
    if (calibrationSaved) calibrationEditing = false;
    Serial.println(calibrationSaved ? "OK CAL SAVE" : "ERR CAL SAVE: incomplete, non-monotonic or flash failure");
    calibrationReport(); return true;
  }
  if (!strcmp(line, "CAL LOAD")) {
    calibrationSaved = loadCalibration();
    if (calibrationSaved) calibrationEditing = false;
    confirmedPosition = candidatePosition = -1;
    Serial.println(calibrationSaved ? "OK CAL LOAD" : "ERR no saved calibration");
    calibrationReport(); return true;
  }
  if (!strncmp(line, "CAL ANCHORS ", 12)) {
    unsigned long mask; char extra;
    if (sscanf(line+12, "%lu %c", &mask, &extra) != 1 || mask > 0x7fffff || !(mask & 1) || !(mask & (1u<<22))) {
      Serial.println("ERR CAL ANCHORS: endpoint control points required"); return true;
    }
    calibrationEditing = true;
    calibration.anchors = mask;
    calibrationSaved = false;
    calibrationReport(); return true;
  }
  if (!strncmp(line, "CAL SET ", 8)) {
    int index; float value; char extra;
    if (sscanf(line + 8, "%d %f %c", &index, &value, &extra) != 2 || index < 1 || index > 23 || !isfinite(value) || value < 10 || value > 1000) {
      Serial.println("ERR CAL SET: index 1-23, distance 10-1000 mm"); return true;
    }
    calibrationEditing = true;
    calibration.mm[index-1] = value;
    calibrationSaved = false;
    candidatePosition = confirmedPosition = -1;
    calibrationReport(); return true;
  }
  if (strcmp(line, "dist")) return false;
  streamDistance = !streamDistance;
  Serial.printf("OK dist stream %s\n", streamDistance ? "on" : "off");
  return true;
}

void report() {
  Serial.printf("POOL: radio=%u cal1=%.1f cal23=%.1f laser=%s member=%d tune=%s\n", plate.configOk ? plate.config.pointId : 0, calPos1,
                calPos23, laserOk ? "ok" : "MISSING", confirmedPosition, tuningSaved ? "saved" : "defaults");
}

void setup() {
  hostArmed = calibrationEditing = rawStream = false;
  rawDropped = 0;
  lastOutput = -1;
  calPos1 = calPos23 = 0;
  calibration = SliderCalibration();
  tuning = SliderTuning();
  distanceFilter.reset();
  medianFilter.reset();
  sampleValid = false;
  confirmedPosition = candidatePosition = -1;
  candidateSince = releaseSince = 0;
  lastSample = 0;
  pinMode(STRIP_LED_PIN, OUTPUT);
  digitalWrite(STRIP_LED_PIN, LOW);
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT POOL RADIO";
  options.zoneType = ZONE_POOL;
  options.nfcEnabled = true;
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.onSerial = serialCommand;
  plate.onReport = report;
  plate.onFrame = poolFrame;
  // A fresh boot identity, so the central accepts this radio's sequence starting again
  // from zero instead of rejecting it as stale for the rest of the show.
  poolBootId = esp_random();
  if (!poolBootId) poolBootId = 1;
  poolSeq = 0;
  centralKnown = centralSeesMe = centralPeerPending = false;
  centralSeen = centralEpoch = releaseUntil = nextBurstAt = lastBroadcastCopy = 0;
  burstRemaining = 0;
  plate.begin(options);  // starts I2C
  if (plate.paramsOk && plate.params.count >= 2) {
    calPos1 = plate.params.values[0] / 10.0f;
    calPos23 = plate.params.values[1] / 10.0f;
  }
  calibrationSaved = loadCalibration();
  if (!calibrationSaved && calPos1 >= 10 && calPos23 >= 10 && calPos1 != calPos23) {
    for (int i=0; i<23; ++i) calibration.mm[i] = calPos1 + (calPos23-calPos1)*i/22.0f;
  }
  // Absent or unreadable tuning leaves the firmware defaults in place. Nothing is
  // written here: the updater verifies the nvs partition is unchanged by an update.
  tuningSaved = loadTuning();
  laser.setTimeout(100);
  laserOk = laser.init();
  // A saved timing the sensor rejects must not leave the slider dead at every boot.
  if (laserOk && !laser.setRangeTiming(uint8_t(tuning.timingBudgetMs), tuning.intervalMs)) {
    Serial.println("ERR TUNE: sensor rejected saved timing; using defaults");
    SliderTuning defaults;
    tuning.timingBudgetMs = defaults.timingBudgetMs;
    tuning.intervalMs = defaults.intervalMs;
    laserOk = laser.setRangeTiming(uint8_t(tuning.timingBudgetMs), tuning.intervalMs);
  }
  if (laserOk) laser.startContinuous();
  applyTuning(tuning, false);
  Serial.println(laserOk ? "[OK] VL53L4CD" : "[ERROR] VL53L4CD");
  if (plate.link.lastError() == ERR_NONE) {
    if (!laserOk) plate.link.setError(ERR_SENSOR);
    else if (!calibrationValid() || !radioValid()) plate.link.setError(ERR_PARAMS);
  }
  if (plate.radioOk) plate.link.ensurePeer(BROADCAST_MAC, true);
  plate.printReport();
  calibrationReport();
  tuningReport();
}

void loop() {
  processSlider();
  updateInteraction();
  plate.loop();
  processSlider();
  updateInteraction();
  telemetry();
}
