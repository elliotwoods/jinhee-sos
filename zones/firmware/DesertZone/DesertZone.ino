// =====================================================
// NCT IMMERSIVE DEEP — DESERT TAGGING PLATE
//
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3) + 1CH MOSFET light panel on GPIO1.
// Registered cube on the plate: panel ON, cube -> DESERT, MSG_TAG_STATE 1 (pulse).
// Removed: panel OFF, MSG_TAG_STATE 0. ESP-NOW channel 2. No OTA: the cube table updates over ESP-NOW.
// =====================================================

#include <Adafruit_PN532.h>
#include <NctTagPlate.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "desert-2.2.0";

#define MOSFET_PIN 1

TagPlate plate;

void tagEnter(const uint8_t *, uint8_t, const Record *cube) {
  if (!cube) return;
  digitalWrite(MOSFET_PIN, HIGH);
  Serial.println("DESERT LIGHT ON");
  plate.sendToCube(*cube, MSG_TAG_STATE, 1);
}

void tagLeave(const uint8_t *, uint8_t, const Record *cube) {
  digitalWrite(MOSFET_PIN, LOW);
  Serial.println("DESERT LIGHT OFF");
  if (cube) plate.sendToCube(*cube, MSG_TAG_STATE, 0);
}

void setup() {
  pinMode(MOSFET_PIN, OUTPUT);
  digitalWrite(MOSFET_PIN, LOW);
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT DESERT TAG PLATE";
  options.zoneType = ZONE_DESERT;
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.begin(options);
  plate.printReport();
}

void loop() {
  plate.loop();
  delay(1);
}
