// Host tests for the NctZone library: storage format, A/B slots, ESP-NOW update rules, queries.
#include "zone_stubs.h"
#include "NctZone.h"
#include "fixtures.h"

using namespace nctzone;

static const uint8_t REGISTRY[6] = {0x3C, 0x0F, 0x02, 0xAD, 0x83, 0x24};
static const uint8_t SELF[6] = {0x02, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE};
static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static void load(const char *label, const std::vector<uint8_t> &image) {
  auto *p = fakePartition(label);
  std::fill(p->data->begin(), p->data->end(), 0xFF);
  std::copy(image.begin(), image.end(), p->data->begin());
}
static void wipe(const char *label) { auto *p = fakePartition(label); std::fill(p->data->begin(), p->data->end(), 0xFF); }

static void deliver(ZoneLink &link, const std::vector<uint8_t> &frame, bool broadcast = true) {
  uint8_t src[6], dst[6];
  memcpy(src, REGISTRY, 6);
  memcpy(dst, broadcast ? BROADCAST : SELF, 6);
  assert(link.receive(src, dst, frame.data(), int(frame.size())));
}

static std::vector<SentFrame> repliesAfter(ZoneLink &link, uint32_t ms = 300) {
  size_t before = sentFrames.size();
  link.poll();  // queue drained; replies scheduled with jitter
  fakeNow += ms;
  link.poll();
  return std::vector<SentFrame>(sentFrames.begin() + before, sentFrames.end());
}

static ZoneStatus lastStatus() {
  for (auto i = sentFrames.rbegin(); i != sentFrames.rend(); ++i)
    if (i->data.size() == sizeof(ZoneStatus) && i->data[3] == ZONE_STATUS) {
      ZoneStatus s;
      memcpy(&s, i->data.data(), sizeof(s));
      return s;
    }
  assert(!"no status frame sent");
  return {};
}

static void testProtocol() {
  assert(crc32((const uint8_t *)"123456789", 9) == 0xCBF43926u);
  // Chained CRC equals one-shot CRC.
  assert(crc32((const uint8_t *)"6789", 4, crc32((const uint8_t *)"12345", 5)) == 0xCBF43926u);
  assert(frameType(V2_ANNOUNCE.data(), int(V2_ANNOUNCE.size())) == DB_ANNOUNCE);
  assert(frameType(V2_CHUNKS[0].data(), int(V2_CHUNKS[0].size())) == DB_CHUNK);
  // Wrong length, wrong magic, cube-sized and media-sized frames are rejected.
  assert(!frameType(V2_ANNOUNCE.data(), int(V2_ANNOUNCE.size()) - 1));
  std::vector<uint8_t> bad = V2_ANNOUNCE;
  bad[1] = 'X';
  assert(!frameType(bad.data(), int(bad.size())));
  std::vector<uint8_t> cube(24, 0);
  cube[0] = 'N'; cube[1] = 'Z'; cube[2] = 1; cube[3] = DB_CHUNK;
  assert(!frameType(cube.data(), 24));
  uint8_t media[2] = {1, 1};
  assert(!frameType(media, 2));
  // Every chunk length avoids the cube/media lengths.
  for (int n = 1; n <= MAX_RECORDS_PER_CHUNK; n++) assert(chunkLength(n) != 24 && chunkLength(n) != 2);
}

static void testStorage() {
  PartitionStorage a("zdb_a"), b("zdb_b"), cfgStorage("zcfg");
  load("zdb_a", SLOT_V1);
  wipe("zdb_b");
  load("zcfg", CONFIG_POINT2);

  ZoneConfig cfg;
  assert(loadConfig(cfgStorage, cfg) && cfg.zoneType == ZONE_PRESHOW && cfg.pointId == 2 && !strcmp(cfg.name, "Preshow 2"));
  (*fakePartition("zcfg")->data)[10] ^= 1;
  assert(!loadConfig(cfgStorage, cfg) && cfg.zoneType == 0);
  load("zcfg", CONFIG_POINT2);

  ZoneDb db;
  assert(db.begin(&a, &b) == 1);
  assert(db.version() == 1 && db.count() == 32 && db.crc() == SLOT_V1_CRC && db.capacity() == 1819);
  const Record *r = db.find(FIRST_UID.data(), uint8_t(FIRST_UID.size()));
  assert(r && r->cubeID == FIRST_ID && !memcmp(r->mac, FIRST_MAC.data(), 6));
  assert(!db.find(EXTRA_UID.data(), 4));
  uint8_t shorter[4];
  memcpy(shorter, FIRST_UID.data(), 4);
  assert(!db.find(shorter, 4));  // prefix of a 7-byte UID is a different tag

  // Commit goes to the inactive slot; reboot selects the newer slot.
  Record *copy = (Record *)malloc(33 * RECORD_SIZE);
  memcpy(copy, db.records(), 32 * RECORD_SIZE);
  Record extra = {99, 4, {0x04, 0xAA, 0xBB, 0xCC}, {0x02, 0x11, 0x22, 0x33, 0x44, 0x55}};
  // Insert keeping order: 4-byte UIDs sort before 7-byte UIDs.
  memmove(copy + 1, copy, 32 * RECORD_SIZE);
  copy[0] = extra;
  assert(db.commit(2, copy, 33) && db.activeSlot() == 2 && db.version() == 2 && db.find(EXTRA_UID.data(), 4));
  ZoneDb rebooted;
  assert(rebooted.begin(&a, &b) == 2 && rebooted.version() == 2 && rebooted.generation() == 2 && rebooted.count() == 33);

  // A corrupted newest slot falls back to the older valid one.
  (*fakePartition("zdb_b")->data)[40] ^= 0xFF;
  ZoneDb fallback;
  assert(fallback.begin(&a, &b) == 1 && fallback.version() == 1);

  // Interrupted commit (power loss mid-write) keeps the active database, before and after reboot.
  ZoneDb live;
  assert(live.begin(&a, &b) == 1);
  Record *next = (Record *)malloc(32 * RECORD_SIZE);
  memcpy(next, live.records(), 32 * RECORD_SIZE);
  partitionWriteBudget = 100;
  assert(!live.commit(5, next, 32) && live.version() == 1 && live.activeSlot() == 1);
  partitionWriteBudget = -1;
  ZoneDb afterLoss;
  assert(afterLoss.begin(&a, &b) == 1 && afterLoss.version() == 1);

  // Unsorted, duplicate or invalid records are refused without touching flash.
  Record *unsorted = (Record *)malloc(2 * RECORD_SIZE);
  unsorted[0] = live.records()[1];
  unsorted[1] = live.records()[0];
  std::vector<uint8_t> before = *fakePartition("zdb_b")->data;
  assert(!live.commit(6, unsorted, 2) && *fakePartition("zdb_b")->data == before);
  Record *dup = (Record *)malloc(2 * RECORD_SIZE);
  dup[0] = live.records()[0];
  dup[1] = live.records()[0];
  assert(!live.commit(6, dup, 2));
  Record *broadcastMac = (Record *)malloc(RECORD_SIZE);
  broadcastMac[0] = extra;
  broadcastMac[0].mac[0] = 0xFF;
  assert(!live.commit(6, broadcastMac, 1));

  // Blank flash: empty database, not a crash.
  wipe("zdb_a");
  wipe("zdb_b");
  ZoneDb blank;
  assert(blank.begin(&a, &b) == 0 && blank.count() == 0 && blank.version() == 0 && !blank.find(FIRST_UID.data(), 7));
}

static void testUpdates() {
  load("zdb_a", SLOT_V1);
  wipe("zdb_b");
  load("zcfg", CONFIG_POINT2);
  PartitionStorage a("zdb_a"), b("zdb_b"), cfgStorage("zcfg");
  ZoneConfig cfg;
  bool cfgOk = loadConfig(cfgStorage, cfg);
  ZoneDb db;
  db.begin(&a, &b);
  ZoneLink link;
  radioChannel = 2;
  assert(link.begin(db, cfg, cfgOk, "test-fw", 8, true));

  // Status query (broadcast) is answered after jitter, unicast to the requester, with the nonce.
  sentFrames.clear();
  deliver(link, FRAME_QUERY_STATUS);
  link.poll();
  auto replies = repliesAfter(link);
  assert(replies.size() == 1 && !memcmp(replies[0].dest.data(), REGISTRY, 6));
  ZoneStatus s = lastStatus();
  assert(s.nonce == 0xABCDEF01u && s.dbVersion == 1 && s.dbCount == 32 && s.dbCrc == SLOT_V1_CRC && s.pointId == 2 &&
         s.zoneType == ZONE_PRESHOW && !strcmp(s.name, "Preshow 2") && !strcmp(s.firmware, "test-fw") &&
         s.channel == 2 && s.configValid && s.activeSlot == 1 && s.stagingVersion == 0);

  // Newer announce opens staging; out-of-order and duplicate chunks assemble; commit to slot B.
  deliver(link, V2_ANNOUNCE);
  link.poll();
  assert(link.stagingActive() && link.stagingVersion() == 2);
  size_t n = V2_CHUNKS.size();
  assert(n == 3);
  deliver(link, V2_CHUNKS[2]);
  deliver(link, V2_CHUNKS[0]);
  deliver(link, V2_CHUNKS[0]);
  link.poll();
  assert(link.stagingReceived() == 2 && db.version() == 1);
  repliesAfter(link);
  s = lastStatus();
  assert(s.stagingVersion == 2 && s.stagingChunks == 2 && s.stagingTotal == 3);
  // A repeated announce for the same version keeps progress.
  deliver(link, V2_ANNOUNCE);
  link.poll();
  assert(link.stagingReceived() == 2);
  deliver(link, V2_CHUNKS[1]);
  link.poll();
  assert(!link.stagingActive() && db.version() == 2 && db.count() == V2_COUNT && db.crc() == V2_CRC && db.activeSlot() == 2);
  assert(db.find(EXTRA_UID.data(), 4) && link.lastError() == ERR_NONE);
  repliesAfter(link);
  s = lastStatus();
  assert(s.dbVersion == 2 && s.activeSlot == 2);

  // Same or older version is ignored; broadcast FORCE is ignored.
  deliver(link, V2_ANNOUNCE);
  deliver(link, ROLLBACK_ANNOUNCE);
  deliver(link, ROLLBACK_ANNOUNCE_FORCE, true);
  link.poll();
  assert(!link.stagingActive());
  // Late chunks without staging do nothing.
  deliver(link, V2_CHUNKS[0]);
  link.poll();
  assert(db.version() == 2);

  // Unicast FORCE rolls back to an older version.
  deliver(link, ROLLBACK_ANNOUNCE_FORCE, false);
  link.poll();
  assert(link.stagingActive() && link.stagingVersion() == 1);
  for (auto &chunk : ROLLBACK_CHUNKS) deliver(link, chunk);
  link.poll();
  assert(db.version() == 1 && db.count() == ROLLBACK_COUNT && db.activeSlot() == 1);

  // A different chunking (5 per chunk) works; staging times out after 60 s of silence.
  deliver(link, V3SMALL_ANNOUNCE);
  deliver(link, V3SMALL_CHUNKS[0]);
  link.poll();
  assert(link.stagingActive() && link.stagingReceived() == 1);
  fakeNow += 61000;
  link.poll();
  assert(!link.stagingActive() && link.lastError() == ERR_STAGING_TIMEOUT && db.version() == 1);
  // A chunk from the wrong chunking layout (V2 12-per-chunk into V3 5-per-chunk staging) is rejected.
  deliver(link, V3SMALL_ANNOUNCE);
  link.poll();
  std::vector<uint8_t> wrongLayout = V2_CHUNKS[0];
  memcpy(wrongLayout.data() + 4, V3SMALL_ANNOUNCE.data() + 4, 4);  // version 3
  deliver(link, wrongLayout);
  link.poll();
  assert(link.stagingReceived() == 0);
  for (auto &chunk : V3SMALL_CHUNKS) deliver(link, chunk);
  link.poll();
  assert(db.version() == 3 && db.count() == V3SMALL_COUNT && link.lastError() == ERR_NONE);

  // Corrupted record data fails the CRC and leaves the database unchanged.
  std::vector<uint8_t> v4 = V2_ANNOUNCE;
  v4[4] = 4;
  deliver(link, v4);
  link.poll();
  for (size_t i = 0; i < V2_CHUNKS.size(); i++) {
    std::vector<uint8_t> chunk = V2_CHUNKS[i];
    chunk[4] = 4;
    if (i == 1) chunk[20] ^= 0x01;
    deliver(link, chunk);
  }
  link.poll();
  assert(db.version() == 3 && link.lastError() == ERR_STAGING_CRC && !link.stagingActive());

  // Announce claiming more records than fit is refused.
  std::vector<uint8_t> huge = V2_ANNOUNCE;
  huge[8] = 0xFF; huge[9] = 0xFF;
  deliver(link, huge);
  link.poll();
  assert(!link.stagingActive() && link.lastError() == ERR_STAGING_INVALID);

  // Log query returns newest-first tag events.
  link.noteTag(FIRST_UID.data(), 7, FIRST_ID, TAG_PENDING);
  uint32_t h = link.noteTag(EXTRA_UID.data(), 4, 99, TAG_PENDING);
  link.noteTag(FIRST_UID.data(), 4, 0, TAG_UNKNOWN);
  link.updateTag(h, TAG_DELIVERED);
  for (int i = 0; i < 10; i++) link.noteTag(FIRST_UID.data(), 7, FIRST_ID, TAG_DELIVERED);  // ring wraps
  sentFrames.clear();
  deliver(link, FRAME_QUERY_LOG, false);
  std::vector<SentFrame> logReplies;
  for (auto &frame : repliesAfter(link))
    if (frame.data[3] == ZONE_LOG) logReplies.push_back(frame);
  assert(logReplies.size() == 1 && logReplies[0].data.size() == sizeof(ZoneLog));
  ZoneLog log;
  memcpy(&log, logReplies[0].data.data(), sizeof(log));
  assert(log.nonce == 7 && log.n == LOG_ENTRIES && log.entries[0].result == TAG_DELIVERED);
  repliesAfter(link, 0);
  deliver(link, FRAME_QUERY_STATUS);
  repliesAfter(link);
  s = lastStatus();
  assert(s.tagCount == 13 && s.unknownTagCount == 1);

  // Identify blinks only when unicast; reboot requires unicast + confirm word.
  pinWrites.clear();
  deliver(link, IDENTIFY_5, true);
  link.poll();
  fakeNow += 1000;
  link.poll();
  assert(pinWrites.empty());
  deliver(link, IDENTIFY_5, false);
  for (int i = 0; i < 20; i++) { fakeNow += 160; link.poll(); }
  assert(pinWrites.size() >= 10);
  fakeNow += 5000;
  link.poll();
  assert(pinLevels[8] == HIGH);  // active-low LED ends off
  std::vector<uint8_t> badReboot = REBOOT;
  badReboot[4] ^= 1;
  deliver(link, REBOOT, true);
  deliver(link, badReboot, false);
  fakeNow += 1000;
  link.poll();
  assert(!ESP.restarted);
  deliver(link, REBOOT, false);
  link.poll();
  fakeNow += 400;
  link.poll();
  assert(ESP.restarted);
  ESP.restarted = false;

  // Serial report used by the flasher boot check.
  Serial.output.clear();
  assert(link.handleSerialCommand("?"));
  assert(Serial.output.find("FW: test-fw\n") != std::string::npos);
  assert(Serial.output.find("CHANNEL: 2\n") != std::string::npos);
  assert(Serial.output.find("ZONE: type=1 point=2 name=Preshow 2\n") != std::string::npos);
  assert(Serial.output.find("DB: version=3 count=33") != std::string::npos);
  assert(Serial.output.find("READY") != std::string::npos);
  Serial.output.clear();
  assert(link.handleSerialCommand("db") && Serial.output.find("CUBE 99 uid=04:AA:BB:CC mac=02:11:22:33:44:55") != std::string::npos);
  assert(!link.handleSerialCommand("nope"));
}

static void testPeers() {
  espPeers.clear();
  ZoneDb db;
  ZoneLink link;
  ZoneConfig cfg = {};
  link.begin(db, cfg, false, "peers", -1, true);
  uint8_t pinned[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};
  assert(link.ensurePeer(pinned, true));
  for (int i = 0; i < 30; i++) {
    uint8_t mac[6] = {0x02, 0, 0, 0, 0, uint8_t(i)};
    fakeNow += 10;
    assert(link.ensurePeer(mac));
    assert(espPeers.size() <= ZoneLink::MAX_PEERS);
  }
  assert(esp_now_is_peer_exist(pinned));
  uint8_t recent[6] = {0x02, 0, 0, 0, 0, 29};
  assert(esp_now_is_peer_exist(recent));
  uint8_t old[6] = {0x02, 0, 0, 0, 0, 0};
  assert(!esp_now_is_peer_exist(old));
  // Unconfigured zone reports its errors.
  assert(link.lastError() == ERR_CONFIG);
}

int main() {
  testProtocol();
  testStorage();
  testUpdates();
  testPeers();
  puts("PASS: NctZone protocol, A/B storage, power-loss safety, updates (order/dup/stale/force/timeout/CRC), log, identify, reboot, peers");
}
