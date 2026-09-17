// Host test of the generic TagPlateZone sketch: the zone sent to cubes comes from flash config.
#include "zone_stubs.h"
#include "../firmware/TagPlateZone/TagPlateZone.ino"
#include "sketch_test.h"

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_MAINSHOW);
  setup();
  assert(plate.radioOk && plate.configOk && has(Serial.output, "ZONE: type=4 point=0 name=Mainshow Entry"));
  size_t mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark + 1);
  Packet p = cubePacket(framesTo(FIRST_MAC.data(), mark)[0]);
  assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_MAINSHOW);

  image("zcfg", CONFIG_POINT2);  // same binary, preshow exit plate
  setup();
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark + 1 && cubePacket(sentFrames.back()).success == nctzone::ZONE_PRESHOW);

  // Without a valid config the plate must not guess a zone.
  image("zcfg", {});
  setup();
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark && has(Serial.output, "ZONE TYPE NOT CONFIGURED"));
  assert(queryStatus().lastError == nctzone::ERR_CONFIG);
  puts("PASS: TagPlateZone sends the configured zone (mainshow/preshow) and refuses to guess when unconfigured");
}
