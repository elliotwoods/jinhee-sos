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

// The pre-2026 2-byte packets, which the plate also emits until it has heard a beacon.
static std::vector<std::vector<uint8_t>> legacyTo(const uint8_t *mac, size_t from = 0) {
  std::vector<std::vector<uint8_t>> out;
  for (auto &frame : framesTo(mac, from))
    if (frame.data.size() == PRESHOW_LEGACY_SIZE) out.push_back(frame.data);
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

// Keep a bridge alive AND the host lease alive, the way the test app does: ping well inside
// HOST_TIMEOUT_MS rather than letting the lease lapse mid-test.
static void hostBridge(const uint8_t *mac, uint32_t ms) {
  uint32_t until = millis() + ms;
  while (millis() < until) {
    size_t mark = sentFrames.size();
    Serial.input = "HOST PING\n";
    beaconFrom(mac, 0);
    run(200);
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
  assert(has(Serial.output, "FW: preshow-3.2.0") && has(Serial.output, "DB: version=1 count=32"));
  assert(Serial.output.rfind("READY") > Serial.output.rfind("STATS:"));
  assert(esp_now_is_peer_exist(BROADCAST) && "broadcast, so events go out before any beacon");
  // The legacy bridge is pinned only as the fallback destination; the plate still has to
  // LEARN the real bridge's address from a beacon.
  assert(esp_now_is_peer_exist(BRIDGE) && legacyFallback() && !bridgeKnown);
  assert(mediaBootId != 0 && !bridgeKnown && !eventValid);

  // ---- Before any beacon: events still go out, by broadcast ----
  size_t mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(200);
  auto cube = framesTo(FIRST_MAC.data(), mark);
  assert(cube.size() == 2 && "the colour, and the first of its two repeats (NctTagPlate.h ZONE_REPEAT_MS)");
  for (auto &frame : cube) {
    Packet p = cubePacket(frame);
    assert(p.type == MSG_SET_ZONE && p.success == nctzone::ZONE_PRESHOW && p.cubeID == FIRST_ID);
  }
  auto media = eventsTo(BROADCAST, mark);
  assert(media.size() >= PRESHOW_BURST_COUNT && "an edge is burst, not sent once");
  assert(media[0].pointId == 2 && media[0].state == 1 && media[0].bootId == mediaBootId);
  assert(media[0].uidLength == FIRST_UID.size() && !memcmp(media[0].uid, FIRST_UID.data(), media[0].uidLength));
  // Every frame of the burst and every retry is the SAME edge: one sequence number per
  // change, so an acknowledgement is unambiguous.
  for (auto &e : media) assert(e.seq == media[0].seq && e.state == 1);
  assert(has(Serial.output, "MEDIA -> POINT 2 ON seq=1"));
  assert(has(Serial.output, "EVT TAG uid=04:60:35:4A:B6:21:91 cube=1 mac=AC:27:6E:80:37:BC zone=1"));

  // ---- And the 2-byte fallback goes out alongside, for the bridge that is really there ----
  // The TouchDesigner bridge is still the original listener-only board. Without this the cue
  // would simply not arrive, for a reason that has nothing to do with the radio.
  auto legacyFrames = legacyTo(BRIDGE, mark);
  assert(legacyFrames.size() >= PRESHOW_BURST_COUNT && legacySent > 0);
  for (auto &f : legacyFrames) assert(f == std::vector<uint8_t>({2, 1}) && "exactly the pre-2026 packet");
  // The burst and the retries go unicast, for the MAC-layer acknowledgement and retries the
  // old link never had; only the periodic rescue copy is broadcast.
  assert(legacyFrames.size() > legacyTo(BROADCAST, mark).size());

  // ---- Unacknowledged: retried for the whole window, then reported ----
  Serial.output.clear();
  mark = sentFrames.size();
  run(PRESHOW_RETRY_WINDOW_MS / 2);
  size_t retried = eventsTo(BROADCAST, mark).size();
  assert(retried >= 10 && "an unacknowledged edge is retried, not abandoned");
  assert(!has(Serial.output, "MEDIA FAIL") && "and not given up on early");
  run(PRESHOW_RETRY_WINDOW_MS);
  // No bridge has ever announced itself, so there is nothing that could acknowledge this.
  // Calling that a delivery failure would report the old bridge as broken on every cue.
  assert(has(Serial.output, "MEDIA LEGACY: point 2 ON seq=1 (2-byte fallback, unacknowledged)"));
  assert(!has(Serial.output, "MEDIA FAIL") && mediaFailures == 0 && queryStatus().sendFailCount == 0);
  Serial.output.clear();
  run(PRESHOW_RETRY_WINDOW_MS);
  assert(!has(Serial.output, "MEDIA LEGACY") && "reported once, not once per retry");

  // ---- But the state keeps being re-asserted, so the link self-heals ----
  mark = sentFrames.size();
  run(PRESHOW_STATE_REPEAT_MS * 4);
  auto repeats = eventsTo(BROADCAST, mark);
  assert(repeats.size() >= 3 && repeats.size() <= 8 && "re-assert continues after the give-up, at a low rate");
  for (auto &e : repeats) assert(e.state == 1 && e.seq == 1 && "the same edge, verbatim");

  // One broadcast copy of the legacy packet goes out periodically too, which covers the
  // legacy bridge board having been swapped for another one.
  assert(!legacyTo(BROADCAST, mark).empty());

  // ---- A beacon: the plate latches the address and unicasts from then on ----
  Serial.output.clear();
  mark = sentFrames.size();
  beaconFrom(BRIDGE, 0);
  run(50);
  assert(bridgeKnown && bridgeFresh() && !memcmp(bridgeMac, BRIDGE, 6));
  // A real bridge exists now, so the fallback switches itself off — for good.
  assert(!legacyFallback() && has(Serial.output, "MEDIA: bridge found; 2-byte legacy fallback off"));
  uint32_t legacyAtHandover = legacySent;
  run(PRESHOW_STATE_REPEAT_MS * 3);
  assert(legacySent == legacyAtHandover && "no more 2-byte frames, ever");
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
  assert(has(report, "MEDIA: mode=modern point=2") && has(report, "bridge_sees_me=") && has(report, "(unicast)"));
  assert(has(report, "bridge_mac=02:EE:DD:CC:BB:AA"));

  // ---- Host override: raising a cue by hand, for a plate with no reader attached ----
  // Nothing happens until it is armed.
  mark = sentFrames.size();
  assert(has(serial("HOST ON"), "ERR HOST: send HOST ARM first") && events(mark).empty());
  assert(has(serial("HOST ARM"), "\"armed\":true") && has(serial("HOST STATUS"), "\"mode\":\"modern\""));
  seqBefore = mediaSeq;
  mark = sentFrames.size();
  serial("HOST ON");
  run(60);
  auto manual = events(mark);
  assert(!manual.empty() && manual[0].state == 1 && manual[0].pointId == 2 && mediaSeq == seqBefore + 1);
  assert(hostState && has(serial("HOST STATUS"), "\"state\":\"ON\""));
  hostBridge(NEW_BRIDGE, 1000);
  assert(eventAcked && "a hand-raised cue is delivered exactly like a tagged one");
  mark = sentFrames.size();
  serial("HOST OFF");
  run(60);
  manual = events(mark);
  assert(!manual.empty() && manual.back().state == 0 && !hostState);

  // Impersonating another point, so one bench board can exercise all four TD channels.
  serial("HOST ON 4");
  run(60);
  assert(hostPoint == 4 && activePoint() == 4 && currentEvent.pointId == 4 && currentEvent.state == 1);
  // Switching points while one is still ON is refused: each edge must get its own burst and
  // retry window, and doing it implicitly would discard the OFF before a frame of it went out.
  assert(has(serial("HOST ON 2"), "ERR HOST: point 4 is still ON"));
  assert(has(serial("HOST ON 9"), "ERR HOST: point must be 1-4") && currentEvent.pointId == 4);
  serial("HOST OFF");
  run(60);
  assert(currentEvent.state == 0 && currentEvent.pointId == 4 && "the OFF goes to the point that was ON");
  serial("HOST ON 2");
  run(60);
  assert(currentEvent.pointId == 2 && currentEvent.state == 1);

  // A forgotten arm must not leave TouchDesigner latched ON. Stop pinging and the lease
  // expires, and the plate raises the OFF itself.
  Serial.output.clear();
  mark = sentFrames.size();
  run(HOST_TIMEOUT_MS + 100);
  assert(!hostArmed && !hostState && has(Serial.output, "EVENT override expired"));
  manual = events(mark);
  assert(!manual.empty() && manual.back().state == 0 && manual.back().pointId == 2);
  assert(activePoint() == 2 && "and the plate goes back to its flashed point");
  liveBridge(NEW_BRIDGE, 1000);

  // A ping that arrives after the lease has gone cannot resurrect it.
  serial("HOST ARM");
  assert(hostArmed);
  run(HOST_TIMEOUT_MS + 100);
  assert(!hostArmed && "the lease lapses on its own, without the host having to say anything");
  serial("HOST PING");
  run(20);
  assert(!hostArmed && "and a late keepalive cannot bring it back");
  assert(has(serial("HOST ON"), "ERR HOST: send HOST ARM first"));
  assert(has(serial("HOST NONSENSE"), "ERR HOST: ARM | PING | DISARM"));

  // A real tag wins over the override, including its impersonated point: the cue the host was
  // holding is released rather than left latched on a point nothing will ever turn off.
  serial("HOST ARM");
  serial("HOST ON 3");
  run(60);
  assert(hostState && currentEvent.pointId == 3 && currentEvent.state == 1);
  mark = sentFrames.size();
  Serial.output.clear();
  presentedTag = FIRST_UID;
  run(300);
  assert(!hostArmed && !hostState && has(Serial.output, "EVENT override released to a real tag"));
  auto afterTag = events(mark);
  bool releasedPoint3 = false;
  for (auto &e : afterTag) if (e.pointId == 3 && e.state == 0) releasedPoint3 = true;
  assert(releasedPoint3 && "point 3 was turned off before the tag took over");
  assert(currentEvent.pointId == 2 && currentEvent.state == 1 && "and the tag's cue is on the flashed point");
  presentedTag.clear();
  run(1000);
  liveBridge(NEW_BRIDGE, 1000);

  // ---- Database update over ESP-NOW; the new cube then works without reflashing ----
  radio(V2_ANNOUNCE);
  for (auto &chunk : V2_CHUNKS) radio(chunk);
  run(100);
  assert(plate.db.version() == 2 && plate.db.activeSlot() == 2);
  mark = sentFrames.size();
  seqBefore = mediaSeq;
  presentedTag = EXTRA_UID;
  run(200);
  assert(framesTo(EXTRA_MAC.data(), mark).size() == 2 && mediaSeq == seqBefore + 1);  // colour + first repeat
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
  assert(framesTo(FIRST_MAC.data(), mark).size() == 3 && events(mark).empty());  // colour + its two repeats
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
  assert(framesTo(FIRST_MAC.data(), mark).size() == 2 && "the recovered reader commands the cube again");
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
