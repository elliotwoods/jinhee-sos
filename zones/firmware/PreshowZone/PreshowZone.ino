// =====================================================
// NCT IMMERSIVE DEEP — PRESHOW TAGGING PLATE (points 1-4)
//
// ESP32-C3 SuperMini + PN532 I2C (SDA GPIO4 / SCL GPIO3), ESP-NOW channel 2.
// Tag -> cube turns PRESHOW (red) and the media bridge gets POINT <n> ON; tag removed -> POINT <n> OFF.
// Cube table, point ID and name live in flash (zones/README.md); flash with zones/flasher.
// =====================================================

#include <Adafruit_PN532.h>
#include <NctTagPlate.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "preshow-2.2.0";

uint8_t MEDIA_BRIDGE_MAC[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};

struct PreshowMediaPacket {
  uint8_t pointID;
  uint8_t state;
};
static_assert(sizeof(PreshowMediaPacket) == 2, "Media bridge ABI changed");

TagPlate plate;
bool mediaEventActive = false;

bool mediaPointValid() {
  return plate.configOk && plate.config.zoneType == ZONE_PRESHOW && plate.config.pointId >= 1 && plate.config.pointId <= 4;
}

void sendMediaEvent(uint8_t state) {
  if (!mediaPointValid()) {
    Serial.println("MEDIA SKIPPED: zone point not configured");
    return;
  }
  PreshowMediaPacket packet = {plate.config.pointId, state};
  if (plate.sendFrame(MEDIA_BRIDGE_MAC, (const uint8_t *)&packet, sizeof(packet), true))
    Serial.printf("MEDIA -> POINT %u %s\n", plate.config.pointId, state ? "ON" : "OFF");
}

void tagEnter(const uint8_t *, uint8_t, const Record *cube) {
  mediaEventActive = false;
  if (!cube) return;  // only registered cubes trigger media
  sendMediaEvent(1);
  mediaEventActive = true;
}

void tagLeave(const uint8_t *, uint8_t, const Record *) {
  if (mediaEventActive) sendMediaEvent(0);
  mediaEventActive = false;
}

void setup() {
  TagPlateOptions options;
  options.firmware = FIRMWARE_VERSION;
  options.banner = "NCT PRESHOW TAG PLATE";
  options.zoneType = ZONE_PRESHOW;
  plate.onTagEnter = tagEnter;
  plate.onTagLeave = tagLeave;
  plate.begin(options);
  if (plate.radioOk) plate.link.ensurePeer(MEDIA_BRIDGE_MAC, true);
  plate.printReport();
}

void loop() {
  plate.loop();
  delay(1);
}
