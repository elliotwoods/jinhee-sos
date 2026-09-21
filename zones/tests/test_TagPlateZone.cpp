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
  assert(has(serial("rxgain 38"), "RXGAIN SET 38dB: zone unconfigured"));

  // RX gain: the stored value is applied at boot, reported, and changed over the air without a reboot.
  pn532AcceptsCommands = true;
  image("zcfg", CONFIG_POINT2);  // written by the current flasher: 48 dB
  Serial.output.clear();
  setup();
  assert(has(Serial.output, "PN532 RX GAIN 48dB: set") && pn532RfCfg == 0x79);
  assert(has(serial("?"), "RXGAIN: stored=48dB applied=48dB"));
  mark = sentFrames.size();
  radio(SET_GAIN_38, true);  // broadcast: ignored
  run(400);
  assert(pn532RfCfg == 0x79 && framesTo(REGISTRY, mark).empty());
  radio(SET_GAIN_38, false);
  run(400);
  assert(pn532RfCfg == 0x59 && fakePartition("zcfg")->data->at(7) == 38);
  nctzone::ZoneSettings settings = lastSettings(mark);
  assert(settings.nonce == 0 && settings.rxGainStored == 38 && settings.rxGainApplied == 38 &&
         settings.lastSetResult == nctzone::SET_OK);
  assert(has(serial("?"), "RXGAIN: stored=38dB applied=38dB") && has(Serial.output, "ZONE: type=1 point=2 name=Preshow 2"));
  // Serial command: validated, then the same save path.
  assert(has(serial("rxgain 40"), "RXGAIN SET 40dB: invalid value") && pn532RfCfg == 0x59);
  assert(has(serial("rxgain 23"), "RXGAIN SET 23dB: ok") && pn532RfCfg == 0x19);
  assert(has(serial("rxgain"), "RXGAIN: stored=23dB applied=23dB"));
  // It persists: a reboot applies the stored gain, and the zone identity is unchanged.
  Serial.output.clear();
  setup();
  assert(plate.configOk && has(Serial.output, "PN532 RX GAIN 23dB: set") && pn532RfCfg == 0x19);
  assert(queryStatus().pointId == 2 && lastSettings().rxGainStored == 23);
  // A reader that refuses the command: the value is stored, reported as not applied.
  pn532AcceptsCommands = false;
  assert(has(serial("rxgain 43"), "RXGAIN SET 43dB: stored, reader did not accept it"));
  assert(has(serial("?"), "RXGAIN: stored=43dB applied=?") && fakePartition("zcfg")->data->at(7) == 43);
  // An older flasher's zcfg (byte 0) runs at the 48 dB default.
  pn532AcceptsCommands = true;
  image("zcfg", CONFIG_LEGACY_GAIN);
  Serial.output.clear();
  setup();
  assert(plate.configOk && has(Serial.output, "PN532 RX GAIN 48dB: set") && has(serial("?"), "RXGAIN: stored=48dB applied=48dB"));
  pn532AcceptsCommands = false;
  puts("PASS: TagPlateZone sends the configured zone (mainshow/preshow) and refuses to guess when unconfigured; RX gain stored/applied/changed over the air");
}
