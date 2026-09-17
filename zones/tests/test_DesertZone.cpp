// Host test of the DesertZone sketch: light panel MOSFET and MSG_TAG_STATE.
#include "zone_stubs.h"
#include "../firmware/DesertZone/DesertZone.ino"
#include "sketch_test.h"

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_DESERT);
  setup();
  assert(plate.radioOk && pinLevels[MOSFET_PIN] == LOW && has(Serial.output, "FW: desert-2.2.0"));
  size_t mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  auto frames = framesTo(FIRST_MAC.data(), mark);
  assert(frames.size() == 2 && pinLevels[MOSFET_PIN] == HIGH);
  assert(cubePacket(frames[0]).type == MSG_SET_ZONE && cubePacket(frames[0]).success == nctzone::ZONE_DESERT);
  assert(cubePacket(frames[1]).type == MSG_TAG_STATE && cubePacket(frames[1]).success == 1);
  run(2000);
  assert(framesTo(FIRST_MAC.data(), mark).size() == 2);
  presentedTag.clear();
  run(1000);
  frames = framesTo(FIRST_MAC.data(), mark);
  assert(frames.size() == 3 && pinLevels[MOSFET_PIN] == LOW);
  assert(cubePacket(frames[2]).type == MSG_TAG_STATE && cubePacket(frames[2]).success == 0);
  std::string log = serial("log");
  assert(has(log, "result=delivered"));

  // Unknown tags never switch the panel on.
  mark = sentFrames.size();
  presentedTag = EXTRA_UID;
  run(300);
  assert(pinLevels[MOSFET_PIN] == LOW && sentFrames.size() == mark);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark);

  // Both results of a double send are attributed in order: zone delivered, tag state not.
  autoSendCallback = false;
  presentedTag = FIRST_UID;
  run(200);
  uint8_t dest[6];
  memcpy(dest, FIRST_MAC.data(), 6);
  esp_now_send_info_t info{dest, nullptr};
  Serial.output.clear();
  sendCallback(&info, ESP_NOW_SEND_SUCCESS);
  sendCallback(&info, ESP_NOW_SEND_FAIL);
  run(50);
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=2 ok=1") && has(Serial.output, "EVT SENT cube=1 type=7 value=1 ok=0"));
  autoSendCallback = true;
  presentedTag.clear();
  run(1000);
  puts("PASS: DesertZone light panel, DESERT zone + TAG_STATE on/off, unknown tags ignored, send results attributed in order");
}
