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
  // The colour is sent once and then repeated twice (NctTagPlate.h, ZONE_REPEAT_MS): one frame is
  // not enough to be sure the cube changed colour, and the cube acknowledges nothing itself.
  auto cube = framesTo(FIRST_MAC.data(), mark);
  assert(cube.size() == 3 && sentFrames.size() == mark + 3);
  for (auto &frame : cube) {
    Packet p = cubePacket(frame);
    assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_MAINSHOW && "every repeat is identical");
  }

  image("zcfg", CONFIG_POINT2);  // same binary, preshow exit plate
  setup();
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark + 3 && cubePacket(sentFrames.back()).success == nctzone::ZONE_PRESHOW);

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
