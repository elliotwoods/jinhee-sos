// Host test of the actual PreshowZone sketch.
#include "zone_stubs.h"
#include "../firmware/PreshowZone/PreshowZone.ino"
#include "sketch_test.h"

// The bridge is never hardcoded any more: the plate learns this address from a beacon.
static const uint8_t BRIDGE[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};
static const uint8_t NEW_BRIDGE[6] = {0x02, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA};

static uint32_t bridgeEpochCounter = 0x9000;

// Beacon as the bridge broadcasts it, with `mask` reporting which points it holds ON.
static void beaconFrom(const uint8_t *mac, uint8_t mask, uint32_t epoch = 0) {
  PreshowBeacon b = {};
  fillHeader(b.h, PRESHOW_BEACON);
  b.epoch = epoch ? epoch : bridgeEpochCounter;
  b.uptimeS = millis() / 1000;
  b.pointMask = mask;
  b.version = PRESHOW_PROTOCOL_VERSION;
  b.channel = ESPNOW_CHANNEL;
  radioFrom(mac, (const uint8_t *)&b, sizeof(b), true);
}

// Acknowledge whatever the plate last transmitted, the way the bridge does.
static void ackFor(const uint8_t *mac, const PreshowEvent &e, bool applied = true) {
  PreshowAck a = {};
  fillHeader(a.h, PRESHOW_ACK);
  a.bootId = e.bootId;
  a.seq = e.seq;
  a.pointId = e.pointId;
  a.flags = applied ? PRESHOW_ACK_APPLIED : 0;
  radioFrom(mac, (const uint8_t *)&a, sizeof(a), false);
}

static std::vector<PreshowEvent> events(size_t from = 0) {
  std::vector<PreshowEvent> out;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (preshowFrameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) == PRESHOW_EVENT) {
      PreshowEvent e; memcpy(&e, sentFrames[i].data.data(), sizeof(e)); out.push_back(e);
    }
  return out;
}

static std::vector<PreshowEvent> eventsTo(const uint8_t *mac, size_t from = 0) {
  std::vector<PreshowEvent> out;
  for (auto &frame : framesTo(mac, from))
    if (preshowFrameType(frame.data.data(), int(frame.data.size())) == PRESHOW_EVENT) {
      PreshowEvent e; memcpy(&e, frame.data.data(), sizeof(e)); out.push_back(e);
    }
  return out;
}

// Keep a bridge alive for `ms`, beaconing as it really does, acknowledging every event.
static void liveBridge(const uint8_t *mac, uint32_t ms, uint8_t mask = 0) {
  uint32_t until = millis() + ms;
  while (millis() < until) {
    size_t mark = sentFrames.size();
    beaconFrom(mac, mask);
    run(PRESHOW_BEACON_MS);
    for (auto &e : events(mark)) ackFor(mac, e);
    run(10);
  }
}

int main() {
  image("zdb_a", SLOT_V1);
  image("zdb_b", {});
  image("zcfg", CONFIG_POINT2);
  setup();
  assert(plate.radioOk && plate.nfcOk && plate.configOk && radioChannel == 2);
  assert(has(Serial.output, "FW: preshow-3.0.0") && has(Serial.output, "DB: version=1 count=32"));
  assert(Serial.output.rfind("READY") > Serial.output.rfind("STATS:"));
  assert(!esp_now_is_peer_exist(BRIDGE) && "the bridge address is no longer compiled in");
  assert(esp_now_is_peer_exist(BROADCAST) && "but broadcast is, so events go out before any beacon");
  assert(mediaBootId != 0 && !bridgeKnown && !eventValid);

  // ---- Before any beacon: events still go out, by broadcast ----
  size_t mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  auto cube = framesTo(FIRST_MAC.data(), mark);
  assert(cube.size() == 1);
  Packet p = cubePacket(cube[0]);
  assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_PRESHOW && p.cubeID == FIRST_ID);
  auto media = eventsTo(BROADCAST, mark);
  assert(media.size() >= PRESHOW_BURST_COUNT && "an edge is burst, not sent once");
  assert(media[0].pointId == 2 && media[0].state == 1 && media[0].bootId == mediaBootId);
  assert(media[0].uidLength == FIRST_UID.size() && !memcmp(media[0].uid, FIRST_UID.data(), media[0].uidLength));
  // Every frame of the burst and every retry is the SAME edge: one sequence number per
  // change, so an acknowledgement is unambiguous.
  for (auto &e : media) assert(e.seq == media[0].seq && e.state == 1);
  assert(has(Serial.output, "MEDIA -> POINT 2 ON seq=1"));
  assert(has(Serial.output, "EVT TAG uid=04:60:35:4A:B6:21:91 cube=1 mac=AC:27:6E:80:37:BC zone=1"));

  // ---- Unacknowledged: retried for the whole window, then reported ----
  Serial.output.clear();
  mark = sentFrames.size();
  run(PRESHOW_RETRY_WINDOW_MS / 2);
  size_t retried = eventsTo(BROADCAST, mark).size();
  assert(retried >= 10 && "an unacknowledged edge is retried, not abandoned");
  assert(!has(Serial.output, "MEDIA FAIL") && "and not given up on early");
  run(PRESHOW_RETRY_WINDOW_MS);
  assert(has(Serial.output, "MEDIA FAIL: point 2 ON seq=1 unacknowledged after 3000ms"));
  assert(mediaFailures == 1 && queryStatus().sendFailCount >= 1);
  Serial.output.clear();
  run(PRESHOW_RETRY_WINDOW_MS);
  assert(!has(Serial.output, "MEDIA FAIL") && "reported once, not once per retry");

  // ---- But the state keeps being re-asserted, so the link self-heals ----
  mark = sentFrames.size();
  run(PRESHOW_STATE_REPEAT_MS * 4);
  auto repeats = eventsTo(BROADCAST, mark);
  assert(repeats.size() >= 3 && repeats.size() <= 8 && "re-assert continues after the give-up, at a low rate");
  for (auto &e : repeats) assert(e.state == 1 && e.seq == 1 && "the same edge, verbatim");

  // ---- A beacon: the plate latches the address and unicasts from then on ----
  mark = sentFrames.size();
  beaconFrom(BRIDGE, 0);
  run(50);
  assert(bridgeKnown && bridgeFresh() && !memcmp(bridgeMac, BRIDGE, 6));
  assert(esp_now_is_peer_exist(BRIDGE) && "added on the loop task, from the beacon");
  assert(!bridgeSeesMe && "the beacon said it holds nothing");
  auto unicast = eventsTo(BRIDGE, mark);
  assert(!unicast.empty() && "a fresh bridge means the retries go unicast at once");
  assert(unicast[0].seq == 1 && unicast[0].state == 1);

  // The acknowledgement is what stops the retries.
  Serial.output.clear();
  ackFor(BRIDGE, unicast.back());
  run(20);
  assert(eventAcked && mediaAcks == 1 && has(Serial.output, "MEDIA ACK point 2 ON seq=1"));
  mark = sentFrames.size();
  run(PRESHOW_RETRY_MS * 5);
  assert(eventsTo(BRIDGE, mark).empty() && "an acknowledged edge is not retried");

  // An acknowledgement for something else must not satisfy the current edge.
  PreshowEvent wrong = unicast.back();
  wrong.seq = 99;
  ackFor(BRIDGE, wrong);
  wrong = unicast.back();
  wrong.bootId ^= 0xFFFF;
  ackFor(BRIDGE, wrong);
  wrong = unicast.back();
  wrong.pointId = 3;
  ackFor(BRIDGE, wrong);
  run(20);
  assert(mediaAcks == 1 && "only an ack echoing this exact edge counts");

  // ---- Holding the tag: re-asserts, but no new edge ----
  mark = sentFrames.size();
  liveBridge(BRIDGE, 4000, preshowPointBit(2));
  auto held = events(mark);
  assert(!held.empty());
  for (auto &e : held) assert(e.seq == 1 && e.state == 1 && "holding a tag raises no new edge");
  assert(bridgeSeesMe && "the beacon's pointMask is the end-to-end confirmation");
  assert(framesTo(FIRST_MAC.data(), mark).empty() && "and the cube is not re-commanded");
  // A broadcast copy keeps going out regardless, to rescue a stale latched address.
  assert(!eventsTo(BROADCAST, mark).empty() && !eventsTo(BRIDGE, mark).empty());

  // ---- Leaving raises the OFF edge, with the next sequence number ----
  Serial.output.clear();
  presentedTag.clear();
  mark = sentFrames.size();
  run(900);  // the 700 ms leave timeout
  // The window also carries re-asserts of the previous state, so look at where it ended up.
  auto off = events(mark);
  assert(!off.empty() && off.back().state == 0 && off.back().seq == 2);
  assert(has(Serial.output, "MEDIA -> POINT 2 OFF seq=2"));
  assert(has(Serial.output, "EVT LEAVE uid=04:60:35:4A:B6:21:91 cube=1 held_ms="));
  liveBridge(BRIDGE, 1000);
  assert(eventAcked);

  // ---- Swapping the bridge board: the plate re-latches with no reflash ----
  mark = sentFrames.size();
  beaconFrom(NEW_BRIDGE, 0, ++bridgeEpochCounter);
  run(50);
  assert(!memcmp(bridgeMac, NEW_BRIDGE, 6) && esp_now_is_peer_exist(NEW_BRIDGE));
  assert(!eventsTo(NEW_BRIDGE, mark).empty() && "and re-delivers its current state to the new one");
  assert(!eventAcked && "a moved bridge knows nothing, so the edge is in flight again");
  liveBridge(NEW_BRIDGE, 1000);
  assert(eventAcked);

  // A bridge that reboots keeps its address but changes epoch, which also re-bursts.
  mark = sentFrames.size();
  beaconFrom(NEW_BRIDGE, 0, ++bridgeEpochCounter);
  run(50);
  assert(!eventAcked && !eventsTo(NEW_BRIDGE, mark).empty() && "a changed epoch re-delivers at once");
  liveBridge(NEW_BRIDGE, 1000);
  assert(eventAcked);

  // ---- A bridge that goes away: back to broadcast, and nothing is lost ----
  run(PRESHOW_BEACON_STALE_MS + 200);
  assert(!bridgeFresh() && bridgeKnown);
  mark = sentFrames.size();
  presentedTag = FIRST_UID;
  run(300);
  auto orphan = events(mark);
  assert(!orphan.empty() && orphan.back().state == 1 && orphan.back().seq == 3);
  assert(!eventsTo(BROADCAST, mark).empty() && "a stale beacon means broadcast again");
  Serial.output.clear();
  run(PRESHOW_RETRY_WINDOW_MS + 200);
  assert(has(Serial.output, "MEDIA FAIL: point 2 ON seq=3"));
  // The bridge comes back and the held state is delivered without anyone touching the plate.
  liveBridge(NEW_BRIDGE, 2000, preshowPointBit(2));
  assert(eventAcked && bridgeSeesMe && "the re-assert heals the cue that was lost");
  presentedTag.clear();
  run(900);
  liveBridge(NEW_BRIDGE, 1000);

  // ---- Unknown tag: no media at all, on enter or on leave ----
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = EXTRA_UID;
  run(300);
  uint16_t seqBefore = mediaSeq;
  presentedTag.clear();
  run(1000);
  assert(mediaSeq == seqBefore && "an unregistered cube raises no edge");
  assert(has(Serial.output, "EVT TAG uid=04:AA:BB:CC cube=0 mac=- zone=1"));
  nctzone::ZoneStatus s = queryStatus();
  assert(s.tagCount == 3 && s.unknownTagCount == 1 && s.dbVersion == 1 && s.pointId == 2);

  // ---- The report ----
  std::string report = serial("?");
  assert(has(report, "MEDIA: point=2") && has(report, "bridge_sees_me=") && has(report, "(unicast)"));
  assert(has(report, "bridge_mac=02:EE:DD:CC:BB:AA"));

  // ---- Database update over ESP-NOW; the new cube then works without reflashing ----
  radio(V2_ANNOUNCE);
  for (auto &chunk : V2_CHUNKS) radio(chunk);
  run(100);
  assert(plate.db.version() == 2 && plate.db.activeSlot() == 2);
  mark = sentFrames.size();
  seqBefore = mediaSeq;
  presentedTag = EXTRA_UID;
  run(200);
  assert(framesTo(EXTRA_MAC.data(), mark).size() == 1 && mediaSeq == seqBefore + 1);
  presentedTag.clear();
  run(1000);
  liveBridge(NEW_BRIDGE, 1000);

  // ---- Undelivered cube command is recorded (the cube link, not the media link) ----
  sendDelivered = false;
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  sendDelivered = true;
  assert(has(Serial.output, "EVT SENT cube=1 type=6 value=1 ok=0"));
  liveBridge(NEW_BRIDGE, 1000);
  std::string log = serial("log");
  assert(has(log, "result=unconfirmed") && has(log, "result=delivered") && has(log, "result=unknown"));

  // ---- Cube test commands from the flasher's monitor ----
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
  size_t quiet = framesTo(FIRST_MAC.data()).size();
  run(1500);
  assert(framesTo(FIRST_MAC.data()).size() == quiet && "a finished test flash stops commanding the cube");
  serial("flash 1 30");
  run(700);
  mark = sentFrames.size();
  assert(has(serial("stop"), "OK stop") && cubePacket(framesTo(FIRST_MAC.data(), mark).back()).success == nctzone::ZONE_IDLE);
  // A real tap during a test flash takes over: the cube ends in this zone's colour.
  serial("flash 1 30");
  presentedTag = FIRST_UID;
  run(1500);
  assert(cubePacket(framesTo(FIRST_MAC.data()).back()).success == nctzone::ZONE_PRESHOW);
  presentedTag.clear();
  run(1000);

  // ---- Reboot: database update persisted, and a fresh boot identity ----
  uint32_t previousBootId = mediaBootId;
  Serial.output.clear();
  setup();
  assert(plate.db.version() == 2 && has(Serial.output, "DB: version=2 count=33"));
  assert(mediaBootId != previousBootId && mediaSeq == 0 && !bridgeKnown && !eventValid);
  assert(!has(serial("?"), "bridge_mac=02:EE:DD:CC:BB:AA"));

  // ---- Unconfigured plate still updates cubes but never raises a media edge ----
  image("zcfg", {});
  setup();
  assert(!plate.configOk);
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  presentedTag.clear();
  run(1000);
  assert(framesTo(FIRST_MAC.data(), mark).size() == 1 && events(mark).empty());
  assert(has(Serial.output, "MEDIA SKIPPED: zone point not configured") && !eventValid);
  // And a beacon cannot make it start: there is no point id to cue.
  beaconFrom(BRIDGE, 0x0F, ++bridgeEpochCounter);
  run(100);
  assert(events(mark).empty() && !bridgeSeesMe);
  assert(!queryStatus().configValid);
  image("zcfg", CONFIG_POINT2);

  // ---- Missing PN532: radio still answers queries with ERR_NFC; the reader recovers ----
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

  puts("PASS: PreshowZone tag enter/leave, beacon-latched unicast with broadcast fallback, burst + "
       "retry-until-acknowledged + give-up report, state re-assert self-heal, bridge swap and reboot, "
       "live DB update, cube delivery failures, cube commands (zone/clear/flash/stop), degraded modes");
}
