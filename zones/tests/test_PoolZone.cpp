// Host test of the PoolZone sketch: slider -> member, central controller packets, heartbeat, cube zone.
#include "zone_stubs.h"
#include "../firmware/PoolZone/PoolZone.ino"
#include "sketch_test.h"

static RadioPacket lastCentral(size_t from = 0) {
  auto frames = framesTo(BROADCAST, from);
  assert(!frames.empty() && frames.back().data.size() == sizeof(RadioPacket));
  RadioPacket p;
  memcpy(&p, frames.back().data.data(), sizeof(p));
  return p;
}

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_POOL4);  // radio 4, member 1 at 383.0 mm, member 23 at 43.0 mm
  laserDistance = 383;
  setup();
  assert(plate.radioOk && laserOk && calibrationValid() && has(Serial.output, "POOL: radio=4 cal1=383.0 cal23=43.0 laser=ok"));
  assert(Serial.output.rfind("READY") > Serial.output.rfind("POOL:"));
  assert(queryStatus().lastError == nctzone::ERR_NONE);
  run(300);
  assert(confirmedPosition == 1);
  laserDistance = 43;
  run(300);
  assert(confirmedPosition == 23);
  laserDistance = 213;  // halfway
  run(300);
  assert(confirmedPosition == 12);
  laserDistance = 600;  // out of range keeps the last position
  run(300);
  assert(confirmedPosition == 12 && framesTo(BROADCAST).empty());

  // Registered cube: strip on, POOL zone to the cube, active packet with member + UID, heartbeat.
  laserDistance = 213;
  size_t mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(250);
  assert(pinLevels[STRIP_LED_PIN] == HIGH);
  auto cube = framesTo(FIRST_MAC.data(), mark);
  assert(cube.size() == 1 && cubePacket(cube[0]).type == MSG_SET_ZONE && cubePacket(cube[0]).success == nctzone::ZONE_POOL);
  RadioPacket central = lastCentral(mark);
  assert(central.magic == PACKET_MAGIC && central.radioId == 4 && central.active == 1 && central.member == 12 &&
         central.uidLength == 7 && !memcmp(central.uid, FIRST_UID.data(), 7));
  size_t beats = framesTo(BROADCAST, mark).size();
  run(1500);
  size_t later = framesTo(BROADCAST, mark).size();
  assert(later - beats >= 6 && later - beats <= 12);
  // Moving the slider while tagged updates the central frame.
  laserDistance = 383;
  run(400);
  assert(lastCentral(mark).member == 1);
  presentedTag.clear();
  run(1000);
  central = lastCentral(mark);
  assert(central.active == 0 && central.member == 0 && pinLevels[STRIP_LED_PIN] == LOW);
  size_t after = sentFrames.size();
  run(1000);
  assert(sentFrames.size() == after);  // no heartbeat without a tag

  // Unregistered tags still drive the pool interaction but no cube is addressed.
  mark = sentFrames.size();
  presentedTag = EXTRA_UID;
  run(250);
  assert(lastCentral(mark).active == 1 && pinLevels[STRIP_LED_PIN] == HIGH && framesTo(EXTRA_MAC.data(), mark).empty());
  presentedTag.clear();
  run(1000);

  // Calibration stream for setting up a radio.
  assert(has(serial("dist", 600), "DIST=383.0 MEMBER=1 TAG=OFF"));
  serial("dist");

  // Missing calibration or sensor is reported, never guessed.
  image("zcfg", CONFIG_POOL_NOCAL);
  setup();
  assert(!calibrationValid() && queryStatus().lastError == nctzone::ERR_PARAMS);
  image("zcfg", CONFIG_POOL4);
  laserPresent = false;
  setup();
  assert(queryStatus().lastError == nctzone::ERR_SENSOR);
  puts("PASS: PoolZone slider mapping, central packets + heartbeat, POOL zone to cubes, unregistered tags, calibration stream, missing params/sensor");
}
