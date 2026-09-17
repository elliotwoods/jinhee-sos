// =====================================================
// NCT IMMERSIVE DEEP — POOL ZONE RADIO
//
// ESP32-C3 SuperMini + PN532 + VL53L4CD slider (I2C SDA GPIO4 / SCL GPIO3) + 12 V LED strip MOSFET on GPIO5.
// Any tag on the radio: strip ON, RadioPacket {active, member 1-23} broadcast to the pool central
// controller (heartbeat 150 ms); registered cubes are also set to POOL. ESP-NOW channel 2.
// Radio ID (1-6) = zone point; slider calibration (mm at member 1 and member 23) = zone params,
// both written by zones/flasher. Serial "dist" toggles a distance stream for calibration.
// =====================================================

#include <Adafruit_PN532.h>
#include <VL53L4CD.h>
#include <NctTagPlate.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "pool-2.2.0";

#define STRIP_LED_PIN 5
#define MEMBER_COUNT 23
#define FILTER_SIZE 2
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
uint16_t distanceBuffer[FILTER_SIZE] = {};
uint8_t bufferIndex = 0, bufferCount = 0;
float filteredDistance = 0;
int candidatePosition = -1, confirmedPosition = -1;
uint32_t candidateSince = 0, lastRangeRead = 0, lastHeartbeat = 0, lastStream = 0;

bool radioValid() { return plate.configOk && plate.config.pointId >= 1 && plate.config.pointId <= 6; }
bool calibrationValid() { return plate.paramsOk && plate.params.count >= 2 && calPos1 != calPos23 && calPos1 > 0 && calPos23 > 0; }

void sendCentralState(bool active) {
  if (!radioValid()) return;
  RadioPacket packet = {};
  packet.magic = PACKET_MAGIC;
  packet.radioId = plate.config.pointId;
  if (active && confirmedPosition >= 1 && confirmedPosition <= MEMBER_COUNT) {
    packet.active = 1;
    packet.member = confirmedPosition;
  }
  if (active) {
    packet.uidLength = plate.currentUidLength();
    memcpy(packet.uid, plate.currentUid(), packet.uidLength);
  }
  plate.sendFrame(BROADCAST_MAC, (const uint8_t *)&packet, sizeof(packet), true);
}

int distanceToMember(float distance) {
  float step = (calPos23 - calPos1) / (MEMBER_COUNT - 1);
  float margin = fabsf(step) * 0.7f;
  float low = (calPos1 < calPos23 ? calPos1 : calPos23) - margin;
  float high = (calPos1 > calPos23 ? calPos1 : calPos23) + margin;
  if (distance < low || distance > high) return -1;
  int member = int(lroundf((distance - calPos1) / step + 1.0f));
  return member < 1 ? 1 : member > MEMBER_COUNT ? MEMBER_COUNT : member;
}

void processSlider() {
  uint32_t now = millis();
  if (!laserOk || now - lastRangeRead < RANGE_INTERVAL_MS) return;
  lastRangeRead = now;
  uint16_t distance = laser.readRangeContinuousMillimeters();
  if (laser.timeoutOccurred() || distance < 10 || distance > 1000) return;
  distanceBuffer[bufferIndex] = distance;
  bufferIndex = (bufferIndex + 1) % FILTER_SIZE;
  if (bufferCount < FILTER_SIZE) bufferCount++;
  uint32_t total = 0;
  for (uint8_t i = 0; i < bufferCount; i++) total += distanceBuffer[i];
  filteredDistance = float(total) / bufferCount;
  if (streamDistance && now - lastStream >= 250) {
    lastStream = now;
    Serial.printf("DIST=%.1f MEMBER=%d TAG=%s\n", filteredDistance, confirmedPosition, plate.tagPresent() ? "ON" : "OFF");
  }
  if (!calibrationValid()) return;
  int member = distanceToMember(filteredDistance);
  if (member < 1) return;
  if (member != candidatePosition) {
    candidatePosition = member;
    candidateSince = now;
  } else if (member != confirmedPosition && now - candidateSince >= POSITION_STABLE_MS) {
    Serial.printf("[SLIDER] %d -> %d\n", confirmedPosition, member);
    confirmedPosition = member;
    if (plate.tagPresent()) {  // moving the slider updates the central frame immediately
      sendCentralState(true);
      lastHeartbeat = now;
    }
  }
}

void tagEnter(const uint8_t *, uint8_t, const Record *) {
  digitalWrite(STRIP_LED_PIN, HIGH);  // unregistered tags still drive the pool interaction
  Serial.printf("===== NEOCORE ON ===== MEMBER = %d\n", confirmedPosition);
  sendCentralState(true);
  lastHeartbeat = millis();
}

void tagLeave(const uint8_t *, uint8_t, const Record *) {
  digitalWrite(STRIP_LED_PIN, LOW);
  Serial.println("===== NEOCORE OFF =====");
  sendCentralState(false);
}

bool serialCommand(const char *line) {
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
  pinMode(STRIP_LED_PIN, OUTPUT);
  digitalWrite(STRIP_LED_PIN, LOW);
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT POOL RADIO";
  options.zoneType = ZONE_POOL;
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.onSerial = serialCommand;
  plate.onReport = report;
  plate.begin(options);  // starts I2C
  if (plate.paramsOk && plate.params.count >= 2) {
    calPos1 = plate.params.values[0] / 10.0f;
    calPos23 = plate.params.values[1] / 10.0f;
  }
  laser.setTimeout(250);
  laserOk = laser.init();
  if (laserOk) laser.startContinuous();
  Serial.println(laserOk ? "[OK] VL53L4CD" : "[ERROR] VL53L4CD");
  if (plate.link.lastError() == ERR_NONE) {
    if (!laserOk) plate.link.setError(ERR_SENSOR);
    else if (!calibrationValid() || !radioValid()) plate.link.setError(ERR_PARAMS);
  }
  if (plate.radioOk) plate.link.ensurePeer(BROADCAST_MAC, true);
  plate.printReport();
}

void loop() {
  processSlider();
  plate.loop();
  processSlider();
  if (plate.tagPresent() && millis() - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = millis();
    sendCentralState(true);
  }
}
