// Real neocube sketch (flashing_station/firmware/neocore_usb): legacy SET_ZONE / SHOW_START
// behaviour is unchanged, timecode joins and resyncs a ready cube, and wireless show updates
// stage, validate, defer while a show runs, commit to NVS and survive a reboot.
#include "zone_stubs.h"
#include "../../flashing_station/firmware/neocore_usb/neocore_usb.ino"
#include "sketch_common.h"
#include "fixtures.h"

static const uint8_t HOST[6] = {0x02, 0x11, 0x22, 0x33, 0x44, 0x55};
static const uint8_t MAIN[6] = {0x02, 0x66, 0x77, 0x88, 0x99, 0xAA};

static uint32_t rgb(uint8_t r, uint8_t g, uint8_t b) { return (uint32_t(r) << 16) | (uint32_t(g) << 8) | b; }
// Show clock, allowing for the few milliseconds run() advances after a frame is handled.
static bool clockNear(uint32_t t) { uint32_t c = millis() - showStartMillis; return c >= t && c < t + 6; }
static uint32_t shown() { return neoShown.empty() ? 0xFFFFFFFF : neoShown[0]; }

static void packet(uint8_t type, uint32_t cubeID = 0, uint8_t success = 0) {
  Packet p = {};
  p.type = type;
  p.cubeID = cubeID;
  p.success = success;
  radioFrom(MAIN, (const uint8_t *)&p, sizeof p);
  run(5);
}

static void frame(const std::vector<uint8_t> &f, bool broadcast = true, const uint8_t *from = HOST) {
  radioFrom(from, f.data(), f.size(), broadcast);
  run(3);
}

static void timecodeAt(uint32_t showId, uint32_t t) {
  auto f = nctshow::makeTimecode(showId, t, 0, 0);
  radioFrom(MAIN, (const uint8_t *)&f, sizeof f);
  run(1);
}

static std::vector<nctshow::ShowStatus> statusesTo(const uint8_t *mac, size_t from) {
  std::vector<nctshow::ShowStatus> out;
  for (const auto &f : framesTo(mac, from)) {
    if (nctshow::frameType(f.data.data(), int(f.data.size())) != nctshow::SHOW_STATUS) continue;
    nctshow::ShowStatus s;
    memcpy(&s, f.data.data(), sizeof s);
    out.push_back(s);
  }
  return out;
}

static nctshow::ShowStatus query(uint32_t nonce) {
  size_t before = sentFrames.size();
  std::vector<uint8_t> q(sizeof(nctshow::ShowQuery));
  nctshow::ShowQuery sq = {};
  nctshow::fillHeader(sq.h, nctshow::SHOW_QUERY);
  sq.nonce = nonce;
  sq.jitterMs = 300;
  memcpy(q.data(), &sq, sizeof sq);
  frame(q);
  run(310);
  auto replies = statusesTo(HOST, before);
  assert(replies.size() == 1 && replies[0].nonce == nonce);
  return replies[0];
}

static void sendUpdate(const std::vector<uint8_t> &announce, const std::vector<std::vector<uint8_t>> &chunks,
                       bool broadcast = true) {
  frame(announce, broadcast);
  // Out of order, with a duplicate.
  for (size_t i = chunks.size(); i-- > 0;) frame(chunks[i]);
  frame(chunks[0]);
}

static void reboot() {
  showQueue = nullptr;
  showRunning = false;
  lastShowId = 0;
  stopStaging();
  showUpdateError = nctshow::ERR_NONE;
  haveAnnouncer = false;
  memset(pendingReplies, 0, sizeof pendingReplies);
  Serial.output.clear();
  setup();
}

int main() {
  setup();
  assert(has(Serial.output, "FW: v1.6.0-USB.1") && has(Serial.output, "Cube READY"));
  assert(has(Serial.output, "SHOW: v=0 crc=dd7f47d4 src=builtin"));
  assert(has(serial("?"), "FW: v1.6.0-USB.1\nCube MAC: 02:AA:BB:CC:DD:EE\nESP-NOW CHANNEL: 2\nSHOW: v=0"));
  assert(radioChannel == 2 && showSource == nctshow::SOURCE_BUILTIN && showVersion == 0);

  // ---- Legacy behaviour: an old Mainshow controller never sends timecode ----
  packet(MSG_DISCOVER);
  assert(framesTo(MAIN).size() == 1 && framesTo(MAIN)[0].data.size() == 24 && framesTo(MAIN)[0].data[0] == MSG_DISCOVER_REPLY);
  packet(MSG_SHOW_START, 7);
  assert(!showRunning && "SHOW_START is ignored unless the cube is mainshow-ready");
  packet(MSG_SET_ZONE, 0, ZONE_MAINSHOW);
  assert(currentZone == ZONE_MAINSHOW && shown() == rgb(18, 20, 1));
  packet(MSG_SHOW_START, 7);
  assert(showRunning && lastShowId == 7 && shown() == rgb(18, 20, 1));
  uint32_t started = showStartMillis;
  run(10);
  packet(MSG_SHOW_START, 7);  // repeated burst
  assert(showStartMillis == started && "a repeated showId never restarts the show");
  run(32000);   // 00:32: off
  assert(shown() == 0);
  run(4200);    // 00:36.2: white blink (on)
  assert(shown() == rgb(20, 20, 20));
  run(262000);  // past 04:58
  assert(!showRunning && currentZone == ZONE_IDLE && shown() == 0);
  packet(MSG_SHOW_START, 8);
  assert(!showRunning && "the show end drops mainshow eligibility");

  // ---- Timecode: join, duplicate start, drift, new show, idle ----
  timecodeAt(9, 40000);
  assert(!showRunning && "an idle cube ignores timecode");
  packet(MSG_SET_ZONE, 0, ZONE_MAINSHOW);
  timecodeAt(9, nctshow::DEFAULT_LENGTH_MS);
  assert(!showRunning && "timecode at or beyond the show length is ignored");
  timecodeAt(9, 40000);
  assert(showRunning && lastShowId == 9 && clockNear(40000));
  run(25);
  assert(shown() == rgb(20, 20, 20) && "joined mid blink: 00:40.02 is in the on phase");
  started = showStartMillis;
  packet(MSG_SHOW_START, 9);
  assert(showStartMillis == started && "the SHOW_START it missed arriving late is a duplicate");
  timecodeAt(9, millis() - showStartMillis + 90);
  assert(showStartMillis == started && "drift within 100 ms is left alone");
  uint32_t expected = millis() - showStartMillis + 400;
  timecodeAt(9, expected);
  assert(clockNear(expected) && "drift above 100 ms snaps to the timecode");
  timecodeAt(10, 1000);
  assert(lastShowId == 10 && clockNear(1000) && "a different running show is replaced");
  packet(MSG_SET_ZONE, 0, ZONE_IDLE);
  assert(!showRunning);
  timecodeAt(10, 2000);
  assert(!showRunning);

  // ---- Status of the compiled-in show ----
  nctshow::ShowStatus st = query(0x1234);
  assert(st.version == 0 && st.crc == DEFAULT_SHOW_CRC && st.length == DEFAULT_SHOW_SIZE && st.source == nctshow::SOURCE_BUILTIN);
  assert(!strcmp(st.fw, "v1.6.0-USB.1") && st.zone == ZONE_IDLE && !st.showRunning && !st.stagingVersion);

  // ---- Wireless update: v5, out of order, duplicate chunk; commit and unsolicited status ----
  size_t before = sentFrames.size();
  sendUpdate(SHOW_ANNOUNCE_V5, SHOW_CHUNKS_V5);
  assert(showVersion == 5 && showCrc == VECTOR_CRC && showSource == nctshow::SOURCE_NVS);
  assert(showImageSize == VECTOR_IMAGE.size() && !memcmp(showImage, VECTOR_IMAGE.data(), showImageSize));
  auto unsolicited = statusesTo(HOST, before);
  assert(unsolicited.size() == 1 && unsolicited[0].nonce == 0 && unsolicited[0].version == 5);
  st = query(0x5555);
  assert(st.version == 5 && st.crc == VECTOR_CRC && st.source == nctshow::SOURCE_NVS && !st.lastError);

  // The update survives a reboot.
  reboot();
  assert(has(Serial.output, "SHOW: v=5 crc=") && has(Serial.output, "src=nvs") && showVersion == 5);

  // Older version: ignored when broadcast, accepted when forced by unicast.
  sendUpdate(SHOW_ANNOUNCE_V4, SHOW_CHUNKS_V4);
  assert(showVersion == 5);
  sendUpdate(SHOW_ANNOUNCE_V5_FORCE, SHOW_CHUNKS_V5, true);
  assert(showVersion == 5 && !stagingVersion && "the same version and CRC is already current");

  std::vector<uint8_t> force4 = SHOW_ANNOUNCE_V4;
  force4[offsetof(nctshow::ShowAnnounce, flags)] = nctshow::ANNOUNCE_FORCE;
  sendUpdate(force4, SHOW_CHUNKS_V4, true);
  assert(showVersion == 5 && !stagingVersion && "FORCE is honoured only when unicast");

  // ---- Never commit during a show ----
  packet(MSG_SET_ZONE, 0, ZONE_MAINSHOW);
  packet(MSG_SHOW_START, 11);
  assert(showRunning);
  frame(force4, false);
  for (const auto &c : SHOW_CHUNKS_V4) frame(c);
  assert(pendingCommit && showVersion == 5 && showRunning && "complete but waiting for the show to end");
  st = query(0x6666);
  assert(st.pendingCommit && st.showRunning && st.version == 5 && st.stagingVersion == 4);
  packet(MSG_SET_ZONE, 0, ZONE_IDLE);
  run(5);
  assert(!pendingCommit && showVersion == 4 && "committed once the show stopped");

  // ---- Corrupt data never commits ----
  std::vector<uint8_t> force6 = SHOW_ANNOUNCE_V5;
  force6[offsetof(nctshow::ShowAnnounce, version)] = 6;
  frame(force6);
  auto bad = SHOW_CHUNKS_V5;
  for (auto &c : bad) c[offsetof(nctshow::ShowChunk, version)] = 6;
  bad[1][offsetof(nctshow::ShowChunk, data) + 3] ^= 0xFF;
  for (const auto &c : bad) frame(c);
  assert(showVersion == 4 && showUpdateError == nctshow::ERR_CRC && !stagingVersion);

  // A partial update times out.
  frame(force6);
  frame(SHOW_CHUNKS_V5[0]);  // wrong version: ignored
  assert(stagingVersion == 6 && stagingReceived == 0);
  run(nctshow::STAGING_TIMEOUT_MS + 50);
  assert(!stagingVersion && showUpdateError == nctshow::ERR_TIMEOUT && showVersion == 4);

  // A torn NVS write (image changed, CRC not) falls back to the compiled-in show at boot.
  Preferences::blobs["show/img"][20] ^= 0x01;
  reboot();
  assert(showVersion == 0 && showSource == nctshow::SOURCE_BUILTIN && has(Serial.output, "src=builtin"));

  // The registration NVS was never touched by any of this.
  assert(!Preferences::blobs.count("cube/cubeID"));

  // ---- Fanning (v1.6.0): the player follows this cube's registered number ----
  assert(showPlayer.cube() == 0 && "unregistered: no offsets");
  {
    Packet reg = {};
    reg.type = MSG_REGISTER; reg.cubeID = 23; reg.uidLength = 4;
    reg.uid[0] = 0x04; reg.uid[1] = 0xAA; reg.uid[2] = 0xBB; reg.uid[3] = 0xCC;
    radioFrom(MAIN, (const uint8_t *)&reg, sizeof reg);
    run(800);
  }
  assert(myCubeID == 23 && showPlayer.cube() == 23);
  reboot();
  assert(showPlayer.cube() == 23 && "a reboot keeps the number for the offsets");
  // A fanned image renders this cube's offset: the vector show (VECTOR_SETS, cube 23 included) as v7.
  {
    std::vector<uint8_t> announce = SHOW_ANNOUNCE_V5;
    announce[offsetof(nctshow::ShowAnnounce, version)] = 7;
    auto chunks = SHOW_CHUNKS_V5;
    for (auto &c : chunks) c[offsetof(nctshow::ShowChunk, version)] = 7;
    sendUpdate(announce, chunks);
    assert(showVersion == 7);
    const auto *rows = &VECTOR_SETS[0].second;
    for (const auto &set : VECTOR_SETS) if (set.first == 23) rows = &set.second;
    nctshow::Player reference;
    reference.begin(showImage, 23);
    uint32_t seq = 0;
    auto rng = [](uint32_t lo, uint32_t hi, void *ctx) -> uint32_t { uint32_t &n = *(uint32_t *)ctx; n++; return lo + (n * 7919u) % (hi - lo); };
    for (const auto &v : *rows) {
      nctshow::Rgb got;
      reference.render(v[0], rng, &seq, got);
      assert(got.r == v[2] && got.g == v[3] && got.b == v[4]);
    }
  }
  std::printf("NeocoreShow OK\n");
}
