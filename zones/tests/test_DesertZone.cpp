// Host test of the DesertZone sketch: light panel MOSFET, MSG_TAG_STATE, and the colour repeats
// the shared plate sends after a tap (NctTagPlate.h, ZONE_REPEAT_MS).
#include "zone_stubs.h"
#include "../firmware/DesertZone/DesertZone.ino"
#include "sketch_test.h"

using nctzone::TagPlate;

static int colourFrames(size_t from) {
  int n = 0;
  for (auto &frame : framesTo(FIRST_MAC.data(), from))
    if (cubePacket(frame).type == MSG_SET_ZONE && cubePacket(frame).success == nctzone::ZONE_DESERT) n++;
  return n;
}

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_DESERT);
  setup();
  assert(plate.radioOk && pinLevels[MOSFET_PIN] == LOW && has(Serial.output, "FW: desert-2.4.0"));

  // ---- A tap: colour, tag state, then the two unconditional repeats ----
  // The repeats exist because the cube keeps one received packet and consumes it in loop(): the
  // MSG_TAG_STATE sent right behind the colour can overwrite it, and the radio reports success.
  size_t mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  auto frames = framesTo(FIRST_MAC.data(), mark);
  assert(frames.size() == 3 && pinLevels[MOSFET_PIN] == HIGH);
  assert(cubePacket(frames[0]).type == MSG_SET_ZONE && cubePacket(frames[0]).success == nctzone::ZONE_DESERT);
  assert(cubePacket(frames[1]).type == MSG_TAG_STATE && cubePacket(frames[1]).success == 1);
  assert(cubePacket(frames[2]).type == MSG_SET_ZONE && cubePacket(frames[2]).success == nctzone::ZONE_DESERT);
  assert(has(Serial.output, "EVT ZONE_REPEAT cube=1 value=2 n=1"));
  run(300);
  assert(colourFrames(mark) == 3 && "the second unconditional repeat, at 400 ms");
  // Acknowledged, so nothing more goes out for the rest of the window or while the tag is held.
  run(3000);
  assert(colourFrames(mark) == 3 && framesTo(FIRST_MAC.data(), mark).size() == 4);

  presentedTag.clear();
  run(1000);
  frames = framesTo(FIRST_MAC.data(), mark);
  assert(frames.size() == 5 && pinLevels[MOSFET_PIN] == LOW);
  assert(cubePacket(frames[4]).type == MSG_TAG_STATE && cubePacket(frames[4]).success == 0);
  std::string log = serial("log");
  assert(has(log, "result=delivered"));

  // ---- Unknown tags never switch the panel on ----
  mark = sentFrames.size();
  presentedTag = EXTRA_UID;
  run(300);
  assert(pinLevels[MOSFET_PIN] == LOW && sentFrames.size() == mark);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark);

  // ---- A radio that never acknowledges: retried for the whole window, then reported ----
  sendDelivered = false;
  Serial.output.clear();
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(TagPlate::ZONE_REPEAT_WINDOW_MS - 300);
  assert(colourFrames(mark) == 6 && "0, 120, 400 ms then every 600 ms while unacknowledged");
  assert(!has(Serial.output, "ZONE_GAVE_UP") && "still inside the three-second window");
  run(1000);
  assert(colourFrames(mark) == 7);
  assert(has(Serial.output, "EVT ZONE_GAVE_UP cube=1 value=2 tries=7"));
  assert(has(Serial.output, "Cube #1 colour NOT ACKNOWLEDGED after 7 tries"));
  run(2000);
  assert(colourFrames(mark) == 7 && "giving up is final; the held tag is not re-commanded");
  assert(plate.currentDelivery() == -1 && has(serial("log"), "result=unconfirmed"));
  presentedTag.clear();
  run(1000);

  // ---- The tag leaving cancels what is left: the cube may already be on another plate ----
  Serial.output.clear();
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(50);
  presentedTag.clear();
  run(2000);  // leave is detected 700 ms after the tag goes, by which time both repeats have gone out
  assert(colourFrames(mark) == 3 && has(Serial.output, "TAG LEAVE"));
  assert(!has(Serial.output, "ZONE_GAVE_UP") && "cancelled, not given up on");
  sendDelivered = true;

  // ---- A hand-set colour supersedes the repeats of the last tap ----
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(50);
  assert(has(serial("zone 1 0"), "OK zone 1 0"));
  run(2000);
  assert(colourFrames(mark) == 1 && "only the tap's first colour; the repeats were cancelled");
  presentedTag.clear();
  run(1000);

  // ---- Both results of a double send are attributed in order: zone delivered, tag state not ----
  autoSendCallback = false;
  presentedTag = FIRST_UID;
  run(50);  // before the first repeat, so only the two frames of the tap are in flight
  uint8_t dest[6];
  memcpy(dest, FIRST_MAC.data(), 6);
  esp_now_send_info_t info{dest, nullptr};
  Serial.output.clear();
  sendCallback(&info, ESP_NOW_SEND_SUCCESS);
  sendCallback(&info, ESP_NOW_SEND_FAIL);
  run(20);
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=2 ok=1") && has(Serial.output, "EVT SENT cube=1 type=7 value=1 ok=0"));
  autoSendCallback = true;
  presentedTag.clear();
  run(1000);
  puts("PASS: DesertZone light panel, DESERT zone + TAG_STATE on/off, colour repeats (acknowledged, "
       "retried to the give-up report, cancelled on leave and by a hand-set colour), unknown tags ignored, "
       "send results attributed in order");
}
