// =====================================================
// NCT IMMERSIVE DEEP — GENERIC TAGGING PLATE
//
// Replaces preshow_enter / Tag_Plate (PRESHOW) and mainshow_enter / Mainshow_Tagplate (MAINSHOW).
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3), ESP-NOW channel 2, no router needed.
// Tag -> the cube is set to the zone type stored in this plate's flash config (chosen in zones/flasher).
// =====================================================

#include <Adafruit_PN532.h>
#include <NctTagPlate.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "tagplate-2.3.0";

TagPlate plate;

void setup() {
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT TAG PLATE";
  options.zoneType = 0;  // from flash config
  plate.begin(options);
  plate.printReport();
}

void loop() {
  plate.loop();
  delay(1);
}
