// =====================================================
// NCT IMMERSIVE DEEP — POOL ZONE RADIO
//
// ESP32-C3 SuperMini + PN532 + VL53L4CD slider (I2C SDA GPIO4 / SCL GPIO3) + 12 V LED strip MOSFET on GPIO5.
// NeoCube tag (700 ms removal timeout) or explicitly armed USB override activates output.
// RadioPacket heartbeat 150 ms; registered NeoCubes receive POOL via the shared tag core.
// CAL commands edit 23 ticks; outputs pause during unsaved calibration uploads.
// CAL SAVE persists to NVS. Legacy endpoints seed an unsaved initial calibration.
// =====================================================

#include <Adafruit_PN532.h>
#include <VL53L4CD.h>
#include <NctTagPlate.h>
#include <Preferences.h>
#include "SliderCalibration.h"
#include "OneEuroFilter.h"

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "pool-2.7.0";
// Embedded by the zone builder for exact-source update detection.
#ifndef POOL_BUILD_ID
#define POOL_BUILD_ID unknown
#endif
#define POOL_STRINGIFY_INNER(x) #x
#define POOL_STRINGIFY(x) POOL_STRINGIFY_INNER(x)
constexpr const char *FIRMWARE_BUILD_ID = POOL_STRINGIFY(POOL_BUILD_ID);

#define STRIP_LED_PIN 5
#define MEMBER_COUNT 23
#define RANGE_INTERVAL_MS 20
#define POSITION_STABLE_MS 50
#define HEARTBEAT_MS 150
#define PACKET_MAGIC 0x4E435450

uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Must match the pool central controller.
struct __attribute__((packed)) RadioPacket {
  uint32_t magic;
  uint8_t radioId;
  uint8_t active;
  uint8_t member;
  uint8_t uidLength;
  uint8_t uid[7];
};
static_assert(sizeof(RadioPacket) == 15, "Pool central ABI changed");

TagPlate plate;
VL53L4CD laser;
bool laserOk = false, streamDistance = false;
float calPos1 = 0, calPos23 = 0;
SliderCalibration calibration;
bool calibrationSaved = false, sampleValid = false;
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
OneEuroFilter distanceFilter;
float rawDistance = 0, filteredDistance = 0;
int candidatePosition = -1, confirmedPosition = -1;
uint32_t candidateSince = 0, lastRangeRead = 0, lastHeartbeat = 0, lastStream = 0;

bool radioValid() { return plate.configOk && plate.config.pointId >= 1 && plate.config.pointId <= 6; }
bool calibrationValid() { return calibration.valid(); }

void sendCentralState(bool active) {
  if (!radioValid() || !plate.radioOk) return;
  RadioPacket packet = {};
  packet.magic = PACKET_MAGIC;
  packet.radioId = plate.config.pointId;
  if (active && confirmedPosition >= 1 && confirmedPosition <= MEMBER_COUNT) {
    packet.active = 1;
    packet.member = confirmedPosition;
  }
  if (active && plate.tagPresent()) {
    packet.uidLength = plate.currentUidLength();
    memcpy(packet.uid, plate.currentUid(), packet.uidLength);
  }
  if (plate.sendFrame(BROADCAST_MAC, (const uint8_t *)&packet, sizeof(packet), true)) ++centralQueued;
  else ++centralErrors;
}

bool overrideActive() { return hostArmed && millis() - lastHost < OVERRIDE_TIMEOUT_MS; }
bool interactionActive() { return plate.tagPresent() || overrideActive(); }
int outputMember() {
  return interactionActive() && !calibrationEditing && sampleValid && millis()-lastSample <= 400 && calibrationValid() && confirmedPosition > 0 ? confirmedPosition : 0;
}

void updateInteraction() {
  uint32_t now = millis();
  if (hostArmed && now-lastHost >= OVERRIDE_TIMEOUT_MS) {
    hostArmed = false;
    Serial.println("EVENT override expired");
  }
  digitalWrite(STRIP_LED_PIN, interactionActive() ? HIGH : LOW);
  int output = outputMember();
  if (output != lastOutput || (interactionActive() && now-lastHeartbeat >= HEARTBEAT_MS)) {
    sendCentralState(output > 0);
    lastOutput = output;
    lastHeartbeat = millis();
  }
}

void interactionReport() {
  Serial.printf("{\"device\":\"PoolZoneCalibration\",\"type\":\"interaction\",\"override\":%s,\"active\":%s,\"output\":%d,\"tag\":%s,\"nfc\":%s,\"radio\":%s,\"radio_id\":%u,\"queued\":%lu,\"send_errors\":%lu,\"cube\":%lu,\"delivery\":%d,\"uid\":\"",
    overrideActive() ? "true" : "false", interactionActive() ? "true" : "false", outputMember(), plate.tagPresent() ? "true" : "false", plate.nfcOk ? "true" : "false", plate.radioOk && radioValid() ? "true" : "false", plate.config.pointId,
    (unsigned long)centralQueued, (unsigned long)centralErrors, (unsigned long)(plate.tagPresent() ? plate.currentCube().cubeID : 0), plate.currentDelivery());
  if (plate.tagPresent()) for (uint8_t i=0; i<plate.currentUidLength(); ++i) Serial.printf(i ? ":%02X" : "%02X", plate.currentUid()[i]);
  Serial.print("\",\"mac\":\"");
  if (plate.tagPresent() && plate.currentCube().cubeID) for (uint8_t i=0; i<6; ++i) Serial.printf(i ? ":%02X" : "%02X", plate.currentCube().mac[i]);
  Serial.println("\"}");
}

int distanceToMember(float distance) {
  return calibration.select(distance);
}

void processSlider() {
  uint32_t now = millis();
  if (!laserOk || now - lastRangeRead < RANGE_INTERVAL_MS) return;
  lastRangeRead = now;
  if (!laser.dataReady()) return;
  uint16_t distance = laser.readRangeContinuousMillimeters(false);
  sampleValid = !laser.timeoutOccurred() && laser.ranging_data.range_status == 0 && distance >= 10 && distance <= 1000;
  if (!sampleValid) {
    distanceFilter.reset();
    candidatePosition = confirmedPosition = -1;
    return;
  }
  lastSample = millis();
  rawDistance = distance;
  filteredDistance = distanceFilter.update(rawDistance, lastSample);
  int member = distanceToMember(filteredDistance);
  // Leaving any acceptance window clears immediately; entering requires stability.
  if (member != confirmedPosition) confirmedPosition = -1;
  if (member != candidatePosition) {
    candidatePosition = member;
    candidateSince = now;
  } else if (member >= 1 && now - candidateSince >= POSITION_STABLE_MS) {
    confirmedPosition = member;
  }
  if (streamDistance && now - lastStream >= 250) {
    lastStream = now;
    Serial.printf("DIST=%.1f MEMBER=%d TAG=%s\n", filteredDistance, confirmedPosition, plate.tagPresent() ? "ON" : "OFF");
  }
}

void telemetry() {
  uint32_t now = millis();
  if (now - lastSample > 400) { sampleValid = false; confirmedPosition = candidatePosition = -1; distanceFilter.reset(); }
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

bool serialCommand(const char *line) {
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
  Serial.printf("POOL: radio=%u cal1=%.1f cal23=%.1f laser=%s member=%d\n", plate.configOk ? plate.config.pointId : 0, calPos1,
                calPos23, laserOk ? "ok" : "MISSING", confirmedPosition);
}

void setup() {
  hostArmed = calibrationEditing = false;
  lastOutput = -1;
  calPos1 = calPos23 = 0;
  calibration = SliderCalibration();
  distanceFilter.reset();
  sampleValid = false;
  confirmedPosition = candidatePosition = -1;
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
  plate.begin(options);  // starts I2C
  if (plate.paramsOk && plate.params.count >= 2) {
    calPos1 = plate.params.values[0] / 10.0f;
    calPos23 = plate.params.values[1] / 10.0f;
  }
  calibrationSaved = loadCalibration();
  if (!calibrationSaved && calPos1 >= 10 && calPos23 >= 10 && calPos1 != calPos23) {
    for (int i=0; i<23; ++i) calibration.mm[i] = calPos1 + (calPos23-calPos1)*i/22.0f;
  }
  laser.setTimeout(100);
  laserOk = laser.init();
  if (laserOk) laserOk = laser.setRangeTiming(20, 0);
  if (laserOk) laser.startContinuous();
  Serial.println(laserOk ? "[OK] VL53L4CD" : "[ERROR] VL53L4CD");
  if (plate.link.lastError() == ERR_NONE) {
    if (!laserOk) plate.link.setError(ERR_SENSOR);
    else if (!calibrationValid() || !radioValid()) plate.link.setError(ERR_PARAMS);
  }
  if (plate.radioOk) plate.link.ensurePeer(BROADCAST_MAC, true);
  plate.printReport();
  calibrationReport();
}

void loop() {
  processSlider();
  updateInteraction();
  plate.loop();
  processSlider();
  updateInteraction();
  telemetry();
}
