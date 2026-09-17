// Host test of the actual PreshowZone sketch.
#include "zone_stubs.h"
#include "../firmware/PreshowZone/PreshowZone.ino"
#include "sketch_test.h"

static const uint8_t BRIDGE[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_POINT2);
  setup();
  assert(plate.radioOk && plate.nfcOk && plate.configOk && radioChannel == 2);
  assert(has(Serial.output, "FW: preshow-2.2.0") && has(Serial.output, "DB: version=1 count=32"));
  assert(Serial.output.rfind("READY") > Serial.output.rfind("STATS:"));
  assert(esp_now_is_peer_exist(BRIDGE));

  // Known cube: SET_ZONE(PRESHOW) unicast to its MAC, then media ON with the configured point.
  size_t mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  auto cube = framesTo(FIRST_MAC.data(), mark);
  auto media = framesTo(BRIDGE, mark);
  assert(cube.size() == 1);
  Packet p = cubePacket(cube[0]);
  assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_PRESHOW && p.cubeID == FIRST_ID);
  assert(media.size() == 1 && media[0].data == std::vector<uint8_t>({2, 1}));
  assert(has(Serial.output, "EVT TAG uid=04:60:35:4A:B6:21:91 cube=1 mac=AC:27:6E:80:37:BC zone=1"));
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=1 ok=1"));
  run(2000);  // holding the tag does not resend
  assert(framesTo(FIRST_MAC.data(), mark).size() == 1 && framesTo(BRIDGE, mark).size() == 1);
  presentedTag.clear();
  run(500);
  assert(framesTo(BRIDGE, mark).size() == 1);
  Serial.output.clear();
  run(600);  // media OFF once, after the 700 ms leave timeout
  media = framesTo(BRIDGE, mark);
  assert(media.size() == 2 && media[1].data == std::vector<uint8_t>({2, 0}));
  assert(has(Serial.output, "EVT LEAVE uid=04:60:35:4A:B6:21:91 cube=1 held_ms="));

  // Unknown tag: nothing sent, no media OFF on leave; counted as unknown.
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = EXTRA_UID;
  run(300);
  presentedTag.clear();
  run(1000);
  assert(sentFrames.size() == mark && has(Serial.output, "EVT TAG uid=04:AA:BB:CC cube=0 mac=- zone=1"));
  nctzone::ZoneStatus s = queryStatus();
  assert(s.tagCount == 2 && s.unknownTagCount == 1 && s.sendFailCount == 0 && s.dbVersion == 1 && s.pointId == 2);

  // Database update over ESP-NOW; the new cube then works without reflashing.
  radio(V2_ANNOUNCE);
  for (auto &chunk : V2_CHUNKS) radio(chunk);
  run(100);
  assert(plate.db.version() == 2 && plate.db.activeSlot() == 2);
  mark = sentFrames.size();
  presentedTag = EXTRA_UID;
  run(200);
  assert(framesTo(EXTRA_MAC.data(), mark).size() == 1 && framesTo(BRIDGE, mark).size() == 1);
  presentedTag.clear();
  run(1000);

  // Undelivered cube command is recorded.
  sendDelivered = false;
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  sendDelivered = true;
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=1 ok=0"));
  s = queryStatus();
  assert(s.sendFailCount >= 1);
  std::string log = serial("log");
  assert(has(log, "result=unconfirmed") && has(log, "result=delivered") && has(log, "result=unknown"));

  // Cube test commands from the flasher's monitor.
  mark = sentFrames.size();
  assert(has(serial("cube 1"), "CUBE 1 uid=04:60:35:4A:B6:21:91 mac=AC:27:6E:80:37:BC"));
  assert(has(serial("zone 1 4"), "OK zone 1 4"));
  assert(cubePacket(framesTo(FIRST_MAC.data(), mark).back()).success == nctzone::ZONE_MAINSHOW);
  assert(has(serial("clear 1"), "OK clear 1") && cubePacket(framesTo(FIRST_MAC.data(), mark).back()).success == nctzone::ZONE_IDLE);
  assert(has(serial("zone 1 9"), "ERR usage") && has(serial("clear 777"), "ERR cube 777") && has(serial("bogus"), "Unknown command"));
  mark = sentFrames.size();
  assert(has(serial("flash 1 2"), "OK flash 1 2s"));
  run(2600);
  auto flashes = framesTo(FIRST_MAC.data(), mark);
  assert(flashes.size() >= 5 && flashes.size() <= 7);
  assert(cubePacket(flashes[0]).success == nctzone::ZONE_PRESHOW && cubePacket(flashes[1]).success == nctzone::ZONE_POOL);
  assert(cubePacket(flashes.back()).success == nctzone::ZONE_IDLE && has(Serial.output, "EVT FLASH cube=1 done"));
  size_t quiet = sentFrames.size();
  run(1500);
  assert(sentFrames.size() == quiet);
  serial("flash 1 30");
  run(700);
  mark = sentFrames.size();
  assert(has(serial("stop"), "OK stop") && cubePacket(framesTo(FIRST_MAC.data(), mark).back()).success == nctzone::ZONE_IDLE);
  quiet = sentFrames.size();
  run(1500);
  assert(sentFrames.size() == quiet);
  // A real tap during a test flash takes over: the cube ends in this zone's colour.
  serial("flash 1 30");
  presentedTag = FIRST_UID;
  run(1500);
  assert(cubePacket(framesTo(FIRST_MAC.data()).back()).success == nctzone::ZONE_PRESHOW);
  presentedTag.clear();
  run(1000);

  // Reboot: database update persisted.
  Serial.output.clear();
  setup();
  assert(plate.db.version() == 2 && has(Serial.output, "DB: version=2 count=33"));

  // Unconfigured plate still updates cubes but never sends media events with a bogus point.
  image("zcfg", {});
  setup();
  assert(!plate.configOk);
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(framesTo(FIRST_MAC.data(), mark).size() == 1 && framesTo(BRIDGE, mark).empty());
  s = queryStatus();
  assert(!s.configValid);
  image("zcfg", CONFIG_POINT2);

  // Missing PN532: radio still answers queries with ERR_NFC; the reader recovers when connected.
  pn532Present = false;
  setup();
  assert(!plate.nfcOk && plate.radioOk);
  s = queryStatus();
  assert(s.lastError == nctzone::ERR_NFC);
  pn532Present = true;
  run(5200);
  assert(plate.nfcOk);
  s = queryStatus();
  assert(s.lastError == nctzone::ERR_NONE);

  // A reader that stops answering mid-show is noticed by the live health check and recovered without a reboot.
  std::string nfcLine = serial("nfc");
  assert(has(nfcLine, "NFC: ok=1 fw=32010607") && has(nfcLine, "sda=1 scl=1"));
  pn532Present = false;
  Serial.output.clear();
  run(3500);
  assert(!plate.nfcOk && has(Serial.output, "PN532 LOST"));
  assert(queryStatus().lastError == nctzone::ERR_NFC);
  pn532Present = true;
  run(5500);
  assert(plate.nfcOk && queryStatus().lastError == nctzone::ERR_NONE);
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(300);
  assert(framesTo(FIRST_MAC.data(), mark).size() == 1);
  presentedTag.clear();
  run(1000);
  assert(has(serial("nfc"), "recoveries=") && !has(serial("nfc"), "recoveries=0 "));
  // SDA held low by a reader that was interrupted mid-byte: nine clock pulses free it at start-up.
  heldLow[4] = 5;
  sclPulses = 0;
  setup();
  assert(plate.nfcOk && sclPulses >= 5 && heldLow[4] == 0);
  // A line that never releases is reported, and the radio keeps working.
  heldLow[4] = -1;
  Serial.output.clear();
  setup();
  assert(!plate.nfcOk && plate.radioOk && has(Serial.output, "I2C LINE HELD LOW") && queryStatus().lastError == nctzone::ERR_NFC);
  heldLow.clear();
  run(5200);
  assert(plate.nfcOk);
  // Manual recovery from the console.
  assert(has(serial("nfc recover", 200), "PN532 LOST: recovery requested") && plate.nfcOk);

  puts("PASS: PreshowZone tag enter/leave, events, media point, live DB update, delivery failures, cube commands (zone/clear/flash/stop), degraded modes");
}
