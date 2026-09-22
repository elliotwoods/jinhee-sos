// =====================================================
// NCT IMMERSIVE DEEP — RESET TAGGING PLATE
//
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3), ESP-NOW channel 2, no local hardware.
// Used at the end of the show: a registered cube on the plate is returned to idle.
//
// The cube firmware is frozen, so this plate can only use a message the cube already handles.
// MSG_SET_ZONE with zone 0 (ZONE_IDLE) is the one clearing command it has: it stops a running
// main show, drops the cube's mainshow eligibility (a later SHOW_START is ignored) and shows the
// idle colour, dim white 3,3,3. No message turns the LEDs fully off; only the cube's own show
// timeline end does that. The shared plate core sends the colour and repeats it (NctTagPlate.h,
// ZONE_REPEAT_MS), so this sketch sends nothing of its own: a second frame straight behind the
// colour could replace it in the cube's single packet slot.
// =====================================================

#include <Adafruit_PN532.h>
#include <NctTagPlate.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "reset-1.0.0";

TagPlate plate;

void tagEnter(const uint8_t *, uint8_t, const Record *cube) {
  if (!cube) return;
  Serial.printf("RESET -> idle: Cube #%lu\n", (unsigned long)cube->cubeID);
}

void setup() {
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT RESET TAG PLATE";
  options.zoneType = ZONE_RESET;  // the core sends ZONE_IDLE to the cube (cubeZoneFor)
  plate.onTagEnter = tagEnter;
  plate.begin(options);
  plate.printReport();
}

void loop() {
  plate.loop();
  delay(1);
}
