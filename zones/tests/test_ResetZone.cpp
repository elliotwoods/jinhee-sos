// Host test of the ResetZone sketch: a plate of kind ZONE_RESET (5) sends the frozen cube the
// only clearing command it has, MSG_SET_ZONE with ZONE_IDLE (0), with the shared repeats.
#include "zone_stubs.h"
#include "../firmware/ResetZone/ResetZone.ino"
#include "sketch_test.h"

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_RESET);
  setup();
  assert(plate.radioOk && plate.configOk && has(Serial.output, "FW: reset-1.0.0"));
  assert(has(Serial.output, "NCT RESET TAG PLATE") && has(Serial.output, "ZONE: type=5 point=1 name=Reset 1"));
  assert(plate.zoneType() == nctzone::ZONE_RESET && queryStatus().zoneType == nctzone::ZONE_RESET);

  // ---- A registered cube: idle sent once, then the two unconditional repeats; nothing else ----
  size_t mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  assert(has(Serial.output, "RESET -> idle: Cube #1"));
  presentedTag.clear();
  run(1000);
  auto cube = framesTo(FIRST_MAC.data(), mark);
  assert(cube.size() == 3 && sentFrames.size() == mark + 3 && "colour, two repeats, and the hook sends nothing");
  for (auto &frame : cube) {
    Packet p = cubePacket(frame);
    assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_IDLE && p.cubeID == FIRST_ID && "5 never reaches a cube");
  }
  // The EVT lines report the value sent to the cube (0), not the plate kind, so the flasher
  // monitor matches the tap against its SENT result.
  assert(has(Serial.output, "EVT TAG uid=") && has(Serial.output, " cube=1 mac=") && has(Serial.output, " zone=0\n"));
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=0 ok=1"));
  assert(has(Serial.output, "EVT ZONE_REPEAT cube=1 value=0 n=2"));
  assert(plate.currentDelivery() == 1 && has(serial("log"), "result=delivered"));

  // ---- Unknown tags are logged and never commanded ----
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = EXTRA_UID;
  run(300);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark && has(Serial.output, "UNKNOWN CUBE") && !has(Serial.output, "RESET -> idle"));

  // ---- Operator commands keep their cube-side bound: 0-4 accepted, the plate kind 5 is not ----
  mark = sentFrames.size();
  assert(has(serial("zone 1 4"), "OK zone 1 4") && cubePacket(sentFrames.back()).success == nctzone::ZONE_MAINSHOW);
  assert(has(serial("zone 1 5"), "ERR usage: zone <cubeID> <0-4>") && sentFrames.size() == mark + 1);
  assert(has(serial("clear 1"), "OK clear 1") && cubePacket(sentFrames.back()).success == nctzone::ZONE_IDLE);

  // ---- Without a valid config the plate does not guess ----
  image("zcfg", {});
  setup();
  // The sketch pins the kind at compile time, so even an unconfigured plate resets a cube.
  // That is the same as DesertZone: the kind is what the hardware is, the config is its identity.
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(framesTo(FIRST_MAC.data(), mark).size() == 3 && cubePacket(sentFrames.back()).success == nctzone::ZONE_IDLE);
  assert(queryStatus().lastError == nctzone::ERR_CONFIG);
  puts("PASS: ResetZone sends ZONE_IDLE (0) to a tapped cube with the shared repeats, reports kind 5 and cube value 0, "
       "ignores unknown tags, keeps the 0-4 operator bound");
}
