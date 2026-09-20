// Real sketch: local tracking, control-point calibration, flash and invalid readings.
#include "zone_stubs.h"
#include "../firmware/PoolZone/PoolZone.ino"
#include "sketch_test.h"

static RadioPacket central() {
  auto frames=framesTo(BROADCAST); assert(!frames.empty());
  RadioPacket packet; memcpy(&packet, frames.back().data.data(), sizeof(packet)); return packet;
}

int main() {
  image("zdb_a", SLOT_V1); image("zdb_b", {}); image("zcfg", CONFIG_POOL4);
  laserDistance=383;
  setup(); run(300);
  assert(laserOk && calibrationValid() && confirmedPosition==1);
  assert(!plate.tagPresent() && plate.nfcOk);
  assert(!central().active && pinLevels[STRIP_LED_PIN]==LOW);
  float step=(383.f-43.f)/22;
  assert(distanceToMember(383+step*.33f)==1);
  assert(distanceToMember(383+step*.34f)==-1);
  assert(distanceToMember(383-step*.5f)==-1);
  // A full-scale jump settles, then releases member 1 and confirms 12 in one pass.
  laserDistance=213; run(500); assert(confirmedPosition==12);
  // Hysteresis: a held member keeps a wider window (exitFrac) than it needed to enter
  // (enterFrac). 4 mm off a ~15.5 mm pitch used to release; now it holds.
  laserDistance=217; run(400); assert(confirmedPosition==12);
  laserDistance=222; run(400); assert(confirmedPosition==-1);
  laserDistance=213; run(400); assert(confirmedPosition==12);
  // A bad reading marks the sample invalid at once, but the member is held for
  // dropoutMs so one glitch cannot drop the relay. This is the flicker fix.
  laserStatus=4; run(100); assert(!sampleValid && confirmedPosition==12 && outputMember()==0);
  laserStatus=0; run(200); assert(sampleValid && confirmedPosition==12);
  laserStatus=4; run(700); assert(confirmedPosition==-1 && !sampleValid);
  laserStatus=0; run(400); assert(confirmedPosition==12);
  laserDistance=0; run(700); assert(confirmedPosition==-1 && !sampleValid);
  assert(has(serial("CAL GET"), "PoolZoneCalibration"));
  serial("CAL SET 1 nan"); assert(calibration.mm[0]==383);
  serial("CAL SET 24 50"); assert(calibration.mm[0]==383);
  serial("CAL SET 1 380"); assert(calibration.mm[0]==380 && !calibrationSaved);
  serial("CAL ANCHORS 4196353"); assert(calibration.anchors==4196353);
  assert(has(serial("CAL SAVE"),"OK CAL SAVE") && calibrationSaved);
  serial("CAL SET 1 379");
  assert(has(serial("CAL LOAD"),"OK CAL LOAD") && calibration.mm[0]==380);
  setup(); assert(calibrationSaved && calibration.mm[0]==380 && calibration.anchors==4196353);
  serial("CAL SET 2 380");
  assert(has(serial("CAL SAVE"),"ERR CAL SAVE"));
  serial("CAL LOAD"); assert(calibration.mm[1]!=380);
  // Registered NeoCube activates strip, central and the compatible POOL cube command.
  size_t mark=sentFrames.size();
  presentedTag=FIRST_UID; laserDistance=213; run(250);
  assert(confirmedPosition==12 && plate.tagPresent() && pinLevels[STRIP_LED_PIN]==HIGH);
  assert(central().active && central().member==12 && central().uidLength==FIRST_UID.size());
  auto cube=framesTo(FIRST_MAC.data(),mark); assert(cube.size()==1);
  assert(cubePacket(cube[0]).type==MSG_SET_ZONE && cubePacket(cube[0]).success==ZONE_POOL);
  assert(plate.currentCube().cubeID==FIRST_ID && plate.currentDelivery()==1);
  size_t beats=framesTo(BROADCAST).size(); run(1500);
  assert(framesTo(BROADCAST).size()-beats>=8 && framesTo(BROADCAST).size()-beats<=11);
  // A brief sensor glitch must not interrupt a live central broadcast.
  laserStatus=4; run(150); assert(central().active && central().member==12);
  laserStatus=0; run(150); assert(central().active && central().member==12);
  laserDistance=222; run(400); assert(!central().active && central().member==0);
  laserDistance=383; run(600); assert(central().member==1);
  presentedTag.clear(); run(450); assert(plate.tagPresent());
  run(500); assert(!plate.tagPresent() && !central().active && pinLevels[STRIP_LED_PIN]==LOW);
  // Original unknown-tag behavior remains active without addressing an unregistered cube.
  mark=sentFrames.size(); presentedTag=EXTRA_UID; run(250);
  assert(central().active && plate.currentCube().cubeID==0 && framesTo(EXTRA_MAC.data(),mark).empty());
  presentedTag.clear(); run(1000);
  // Explicit host arm, leased keepalives, no-tag UID, disarm and watchdog expiry.
  serial("HOST PING"); assert(!overrideActive());
  serial("HOST ARM"); assert(overrideActive() && central().active && central().uidLength==0);
  for(int i=0;i<8;++i) { run(300); serial("HOST PING"); }
  assert(overrideActive());
  serial("HOST DISARM"); assert(!central().active && !interactionActive());
  serial("HOST ARM"); run(1600); assert(!overrideActive() && !central().active);
  serial("HOST PING"); assert(!overrideActive());
  // Disarming an override never removes a real tag's activation.
  presentedTag=FIRST_UID; run(250); serial("HOST ARM"); serial("HOST DISARM");
  assert(central().active && interactionActive());
  laserDistance=0; run(700); assert(!central().active);
  laserDistance=383; run(500); assert(central().active);
  serial("CAL SET 1 380"); assert(!central().active && calibrationEditing);
  serial("CAL LOAD"); run(250); assert(central().active && !calibrationEditing);
  presentedTag.clear(); run(1000);
  sendDelivered=false; presentedTag=FIRST_UID; run(250); assert(plate.currentDelivery()==-1);
  sendDelivered=true; presentedTag.clear(); run(1000);
  SliderCalibration uneven;
  for (int i=0; i<23; ++i) uneven.mm[i]=20+10*i;
  uneven.mm[1]=40; uneven.mm[2]=60;
  // Use an independently valid irregular ascending calibration.
  for (int i=2; i<23; ++i) uneven.mm[i]=40+30*(i-1);
  assert(uneven.valid());
  assert(uneven.select(33.4f)==2 && uneven.select(33.3f)==-1);
  assert(uneven.select(49.9f)==2 && uneven.select(50.0f)==-1);
  assert(uneven.select(NAN)==-1);
  puts("PASS: PoolZone ±33% mapping, flash, tagged POOL delivery/ACK, central packets/heartbeat/release, unknown tags, leased host override and editing interlock");
}
