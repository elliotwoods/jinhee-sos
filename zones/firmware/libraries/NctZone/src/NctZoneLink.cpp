#include "NctZoneLink.h"
#include <WiFi.h>
#include <esp_wifi.h>
#include <cstdlib>
#include <cstring>

namespace nctzone {

namespace {

void printHex(const uint8_t *data, int length) {
  for (int i = 0; i < length; i++) Serial.printf(i ? ":%02X" : "%02X", data[i]);
}

const char *resultName(uint8_t result) {
  switch (result) {
    case TAG_UNKNOWN: return "unknown";
    case TAG_DELIVERED: return "delivered";
    case TAG_UNCONFIRMED: return "unconfirmed";
    case TAG_PENDING: return "pending";
    default: return "?";
  }
}

bool isStagingError(uint8_t error) {
  return error == ERR_DB_EMPTY || error == ERR_STAGING_ALLOC || error == ERR_STAGING_CRC ||
         error == ERR_STAGING_INVALID || error == ERR_COMMIT || error == ERR_STAGING_TIMEOUT;
}

}  // namespace

bool ZoneLink::begin(ZoneDb &db, const ZoneConfig &config, bool configValid, const char *firmware, int ledPin,
                     bool ledActiveLow) {
  db_ = &db;
  config_ = config;
  configValid_ = configValid;
  strncpy(firmware_, firmware ? firmware : "", sizeof(firmware_) - 1);
  ledPin_ = ledPin;
  ledActiveLow_ = ledActiveLow;
  if (ledPin_ >= 0) {
    pinMode(ledPin_, OUTPUT);
    digitalWrite(ledPin_, ledActiveLow_ ? HIGH : LOW);
  }
  lastError_ = !configValid_ ? ERR_CONFIG : !db.count() ? ERR_DB_EMPTY : ERR_NONE;
  if (!queue_) queue_ = xQueueCreate(QUEUE_DEPTH, sizeof(Frame));
  return queue_ != nullptr;
}

bool ZoneLink::receive(const uint8_t *src, const uint8_t *dst, const uint8_t *data, int len) {
  if (!frameType(data, len)) return false;
  if (!queue_ || !src) return true;
  Frame frame;
  memcpy(frame.src, src, 6);
  frame.broadcast = dst ? (dst[0] & 1) : 1;  // unknown destination is treated as broadcast
  frame.length = uint8_t(len);
  memcpy(frame.data, data, len);
  xQueueSend(queue_, &frame, 0);
  return true;
}

void ZoneLink::poll() {
  uint32_t now = millis();
  Frame frame;
  for (int i = 0; i < QUEUE_DEPTH && queue_ && xQueueReceive(queue_, &frame, 0) == pdTRUE; i++) handle(frame);

  now = millis();
  if (staging_.active && uint32_t(now - staging_.lastActivity) > STAGING_TIMEOUT_MS) {
    clearStaging();
    lastError_ = ERR_STAGING_TIMEOUT;
  }

  for (Pending &p : pending_) {
    if (!p.active || uint32_t(now - p.dueAt) > 0x7FFFFFFFu) continue;  // dueAt still in the future
    p.active = false;
    if (p.what == QUERY_LOG) sendLog(p.mac, p.nonce);
    else sendStatus(p.mac, p.nonce);
  }

  if (identifying_) {
    bool expired = uint32_t(now - identifyUntil_) < 0x7FFFFFFFu;
    if (expired) {
      identifying_ = false;
      ledOn_ = false;
      if (ledPin_ >= 0) digitalWrite(ledPin_, ledActiveLow_ ? HIGH : LOW);
    } else if (ledPin_ >= 0 && uint32_t(now - lastBlink_) >= 150) {
      ledOn_ = !ledOn_;
      lastBlink_ = now;
      digitalWrite(ledPin_, (ledOn_ != ledActiveLow_) ? HIGH : LOW);
    }
  }

  if (rebootPending_ && uint32_t(now - rebootAt_) < 0x7FFFFFFFu) {
    Serial.println("REBOOT requested over ESP-NOW");
    Serial.flush();
    ESP.restart();
  }
}

void ZoneLink::handle(const Frame &frame) {
  switch (frameType(frame.data, frame.length)) {
    case DB_ANNOUNCE: onAnnounce(frame); break;
    case DB_CHUNK: onChunk(frame); break;
    case ZONE_QUERY: {
      ZoneQuery q;
      memcpy(&q, frame.data, sizeof(q));
      if (q.what == QUERY_STATUS || q.what == QUERY_LOG) schedule(frame.src, q.what, q.nonce);
      break;
    }
    case ZONE_IDENTIFY: {
      if (frame.broadcast) break;
      ZoneIdentify m;
      memcpy(&m, frame.data, sizeof(m));
      uint8_t seconds = m.seconds > 60 ? 60 : m.seconds;
      identifying_ = seconds > 0;
      identifyUntil_ = millis() + uint32_t(seconds) * 1000;
      lastBlink_ = 0;
      Serial.printf("IDENTIFY %u s requested by ", seconds);
      printHex(frame.src, 6);
      Serial.println();
      schedule(frame.src, QUERY_STATUS, 0);
      break;
    }
    case ZONE_REBOOT: {
      ZoneReboot m;
      memcpy(&m, frame.data, sizeof(m));
      if (frame.broadcast || m.confirm != REBOOT_CONFIRM) break;
      rebootPending_ = true;
      rebootAt_ = millis() + 300;
      break;
    }
    case ZONE_SET_CONFIG: {
      ZoneSetConfig m;
      memcpy(&m, frame.data, sizeof(m));
      if (frame.broadcast || m.confirm != SET_CONFIG_CONFIRM) break;
      Serial.printf("SET CONFIG rx_gain=%udB requested by ", m.rxGainDb);
      printHex(frame.src, 6);
      Serial.println();
      configRequested_ = true;
      requestedRxGain_ = m.rxGainDb;
      memcpy(requester_, frame.src, 6);
      break;
    }
    default: break;  // ZONE_STATUS / ZONE_LOG / ZONE_SETTINGS are for the registry
  }
}

bool ZoneLink::takeConfigRequest(uint8_t &rxGainDb) {
  if (!configRequested_) return false;
  configRequested_ = false;
  rxGainDb = requestedRxGain_;
  return true;
}

void ZoneLink::configApplied(const ZoneConfig &config, bool configValid, uint8_t result) {
  config_ = config;
  configValid_ = configValid;
  lastSetResult_ = result;
  static const uint8_t none[6] = {};
  if (memcmp(requester_, none, 6)) schedule(requester_, QUERY_STATUS, 0);
  memset(requester_, 0, 6);
}

void ZoneLink::onAnnounce(const Frame &frame) {
  DbAnnounce a;
  memcpy(&a, frame.data, sizeof(a));
  uint32_t now = millis();
  bool force = (a.flags & ANNOUNCE_FORCE) && !frame.broadcast;
  uint16_t expectedChunks = a.recordsPerChunk ? uint16_t((uint32_t(a.count) + a.recordsPerChunk - 1) / a.recordsPerChunk) : 0;
  bool valid = a.recordsPerChunk >= 1 && a.recordsPerChunk <= MAX_RECORDS_PER_CHUNK && a.count <= db_->capacity() &&
               a.chunkCount == expectedChunks;
  schedule(frame.src, QUERY_STATUS, 0);
  if (!valid) {
    lastError_ = ERR_STAGING_INVALID;
    return;
  }
  bool current = a.dbVersion == db_->version() && a.crc32 == db_->crc() && a.count == db_->count();
  if (current) return;
  if (!(a.dbVersion > db_->version() || force)) return;
  if (staging_.active) {
    bool same = staging_.version == a.dbVersion && staging_.crc == a.crc32 && staging_.count == a.count &&
                staging_.perChunk == a.recordsPerChunk;
    if (same) {
      staging_.lastActivity = now;
      memcpy(staging_.announcer, frame.src, 6);
      return;
    }
    if (!force && a.dbVersion < staging_.version) return;
  }
  clearStaging();
  size_t bytes = size_t(a.count) * RECORD_SIZE;
  staging_.records = (Record *)malloc(bytes ? bytes : 1);
  staging_.bitmap = (uint8_t *)calloc((a.chunkCount + 7) / 8 + 1, 1);
  if (!staging_.records || !staging_.bitmap) {
    clearStaging();
    lastError_ = ERR_STAGING_ALLOC;
    return;
  }
  staging_.active = true;
  staging_.version = a.dbVersion;
  staging_.crc = a.crc32;
  staging_.count = a.count;
  staging_.chunkCount = a.chunkCount;
  staging_.perChunk = a.recordsPerChunk;
  staging_.received = 0;
  staging_.lastActivity = now;
  memcpy(staging_.announcer, frame.src, 6);
  Serial.printf("DB UPDATE: staging version %lu (%u records, %u chunks)%s\n", (unsigned long)a.dbVersion,
                a.count, a.chunkCount, force ? " FORCED" : "");
  if (!a.count) finishStaging();
}

void ZoneLink::onChunk(const Frame &frame) {
  if (!staging_.active) return;
  DbChunkHeader c;
  memcpy(&c, frame.data, sizeof(c));
  if (c.dbVersion != staging_.version || c.index >= staging_.chunkCount) return;
  uint32_t offset = uint32_t(c.index) * staging_.perChunk;
  uint32_t remaining = staging_.count - offset;
  uint8_t expected = remaining < staging_.perChunk ? uint8_t(remaining) : staging_.perChunk;
  if (c.n != expected) return;
  staging_.lastActivity = millis();
  uint8_t mask = uint8_t(1u << (c.index % 8));
  if (staging_.bitmap[c.index / 8] & mask) return;
  memcpy((uint8_t *)staging_.records + offset * RECORD_SIZE, frame.data + CHUNK_HEADER_SIZE, size_t(c.n) * RECORD_SIZE);
  staging_.bitmap[c.index / 8] |= mask;
  staging_.received++;
  if (staging_.received == staging_.chunkCount) finishStaging();
}

void ZoneLink::finishStaging() {
  uint8_t announcer[6];
  memcpy(announcer, staging_.announcer, 6);
  uint32_t version = staging_.version;
  uint16_t count = staging_.count;
  size_t bytes = size_t(count) * RECORD_SIZE;
  if (crc32((const uint8_t *)staging_.records, bytes) != staging_.crc) {
    lastError_ = ERR_STAGING_CRC;
    Serial.println("DB UPDATE: CRC mismatch; discarded");
    clearStaging();
  } else if (!validRecords(staging_.records, count)) {
    lastError_ = ERR_STAGING_INVALID;
    Serial.println("DB UPDATE: invalid records; discarded");
    clearStaging();
  } else {
    Record *records = staging_.records;
    staging_.records = nullptr;
    clearStaging();
    if (db_->commit(version, records, count)) {
      if (isStagingError(lastError_)) lastError_ = ERR_NONE;
      if (!count) lastError_ = ERR_DB_EMPTY;
      Serial.printf("DB UPDATE: committed version %lu (%u records, slot %c)\n", (unsigned long)version, count,
                    db_->activeSlot() == 2 ? 'B' : 'A');
    } else {
      lastError_ = ERR_COMMIT;
      Serial.println("DB UPDATE: flash commit failed; previous database kept");
    }
  }
  schedule(announcer, QUERY_STATUS, 0);
}

void ZoneLink::clearStaging() {
  free(staging_.records);
  free(staging_.bitmap);
  memset(&staging_, 0, sizeof(staging_));
}

void ZoneLink::schedule(const uint8_t *mac, uint8_t what, uint32_t nonce) {
  Pending *slot = nullptr;
  for (Pending &p : pending_)
    if (p.active && p.what == what && !memcmp(p.mac, mac, 6)) {
      p.nonce = nonce ? nonce : p.nonce;
      return;
    }
  for (Pending &p : pending_)
    if (!p.active) { slot = &p; break; }
  if (!slot) return;
  slot->active = true;
  memcpy(slot->mac, mac, 6);
  slot->what = what;
  slot->nonce = nonce;
  slot->dueAt = millis() + (esp_random() % REPLY_JITTER_MS);
}

bool ZoneLink::ensurePeer(const uint8_t *mac, bool pinned) {
  uint32_t now = millis();
  Peer *slot = nullptr;
  for (Peer &p : peers_)
    if (p.used && !memcmp(p.mac, mac, 6)) { slot = &p; break; }
  if (!slot) {
    for (Peer &p : peers_)
      if (!p.used) { slot = &p; break; }
    if (!slot) {
      for (Peer &p : peers_)
        if (!p.pinned && (!slot || uint32_t(now - p.lastUsed) > uint32_t(now - slot->lastUsed))) slot = &p;
      if (!slot) return false;
      if (esp_now_is_peer_exist(slot->mac)) esp_now_del_peer(slot->mac);
      slot->used = false;
    }
    memcpy(slot->mac, mac, 6);
    slot->used = true;
    slot->pinned = pinned;
  }
  slot->pinned = slot->pinned || pinned;
  slot->lastUsed = now;
  if (esp_now_is_peer_exist(mac)) return true;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) == ESP_OK) return true;
  slot->used = false;
  return false;
}

bool ZoneLink::send(const uint8_t *mac, const uint8_t *data, size_t length) {
  return ensurePeer(mac) && esp_now_send(mac, data, length) == ESP_OK;
}

void ZoneLink::sendStatus(const uint8_t *mac, uint32_t nonce) {
  ZoneStatus s = {};
  fillHeader(s.h, ZONE_STATUS);
  s.nonce = nonce;
  s.zoneType = config_.zoneType;
  s.pointId = config_.pointId;
  strncpy(s.name, config_.name, sizeof(s.name) - 1);
  strncpy(s.firmware, firmware_, sizeof(s.firmware) - 1);
  s.dbVersion = db_->version();
  s.dbCount = db_->count();
  s.dbCrc = db_->crc();
  s.stagingVersion = staging_.active ? staging_.version : 0;
  s.stagingChunks = staging_.received;
  s.stagingTotal = staging_.chunkCount;
  s.uptimeS = millis() / 1000;
  s.tagCount = tagCount_;
  s.unknownTagCount = unknownTagCount_;
  s.sendFailCount = sendFailCount_;
  s.lastError = lastError_;
  s.channel = uint8_t(WiFi.channel());
  s.configValid = configValid_;
  s.activeSlot = uint8_t(db_->activeSlot());
  send(mac, (const uint8_t *)&s, sizeof(s));
  sendSettings(mac, nonce);
}

void ZoneLink::sendSettings(const uint8_t *mac, uint32_t nonce) {
  ZoneSettings m = {};
  fillHeader(m.h, ZONE_SETTINGS);
  m.nonce = nonce;
  m.rxGainStored = effectiveRxGain(config_.rxGainDb);
  m.rxGainApplied = rxGainApplied_;
  m.lastSetResult = lastSetResult_;
  send(mac, (const uint8_t *)&m, sizeof(m));
}

void ZoneLink::sendLog(const uint8_t *mac, uint32_t nonce) {
  ZoneLog m = {};
  fillHeader(m.h, ZONE_LOG);
  m.nonce = nonce;
  uint32_t now = millis();
  uint32_t below = 0xFFFFFFFFu;
  for (int k = 0; k < LOG_ENTRIES; k++) {
    const TagEvent *newest = nullptr;
    for (const TagEvent &e : log_)
      if (e.used && e.handle < below && (!newest || e.handle > newest->handle)) newest = &e;
    if (!newest) break;
    below = newest->handle;
    LogEntry &out = m.entries[m.n++];
    out.uidLength = newest->uidLength;
    memcpy(out.uid, newest->uid, 7);
    out.cubeID = newest->cubeID;
    out.result = newest->result;
    out.ageS = uint32_t(now - newest->at) / 1000;
  }
  send(mac, (const uint8_t *)&m, sizeof(m));
}

uint32_t ZoneLink::noteTag(const uint8_t *uid, uint8_t length, uint32_t cubeID, uint8_t result) {
  tagCount_++;
  if (result == TAG_UNKNOWN) unknownTagCount_++;
  TagEvent *slot = &log_[0];
  for (TagEvent &e : log_) {
    if (!e.used) { slot = &e; break; }
    if (e.handle < slot->handle) slot = &e;
  }
  memset(slot, 0, sizeof(*slot));
  slot->used = true;
  slot->handle = nextHandle_++;
  slot->at = millis();
  slot->cubeID = cubeID;
  slot->uidLength = length > 7 ? 7 : length;
  memcpy(slot->uid, uid, slot->uidLength);
  slot->result = result;
  return slot->handle;
}

void ZoneLink::updateTag(uint32_t handle, uint8_t result) {
  for (TagEvent &e : log_)
    if (e.used && e.handle == handle) e.result = result;
}

void ZoneLink::printReport(bool ready) {
  Serial.printf("FW: %s\n", firmware_);
  Serial.printf("MAC: %s\n", WiFi.macAddress().c_str());
  Serial.printf("CHANNEL: %u\n", unsigned(WiFi.channel()));
  if (configValid_) Serial.printf("ZONE: type=%u point=%u name=%s\n", config_.zoneType, config_.pointId, config_.name);
  else Serial.println("ZONE: unconfigured");
  const char *slot = db_->activeSlot() == 1 ? "A" : db_->activeSlot() == 2 ? "B" : "none";
  Serial.printf("DB: version=%lu count=%u crc=%08lX slot=%s capacity=%u\n", (unsigned long)db_->version(), db_->count(),
                (unsigned long)db_->crc(), slot, db_->capacity());
  if (staging_.active)
    Serial.printf("STAGING: version=%lu chunks=%u/%u\n", (unsigned long)staging_.version, staging_.received,
                  staging_.chunkCount);
  Serial.printf("STATS: tags=%lu unknown=%lu send_fail=%lu error=%u\n", (unsigned long)tagCount_,
                (unsigned long)unknownTagCount_, (unsigned long)sendFailCount_, lastError_);
  if (ready) Serial.println("READY");
}

bool ZoneLink::handleSerialCommand(const char *line) {
  while (*line == ' ') line++;
  size_t n = strlen(line);
  while (n && (line[n - 1] == ' ' || line[n - 1] == '\r')) n--;
  auto is = [&](const char *word) { return strlen(word) == n && !strncmp(line, word, n); };
  if (is("?")) {
    printReport();
  } else if (is("db")) {
    for (uint16_t i = 0; i < db_->count(); i++) {
      const Record &r = db_->records()[i];
      Serial.printf("CUBE %lu uid=", (unsigned long)r.cubeID);
      printHex(r.uid, r.uidLength);
      Serial.print(" mac=");
      printHex(r.mac, 6);
      Serial.println();
    }
    Serial.printf("DB END count=%u\n", db_->count());
  } else if (is("log")) {
    uint32_t now = millis(), below = 0xFFFFFFFFu;
    for (int k = 0; k < LOG_ENTRIES; k++) {
      const TagEvent *newest = nullptr;
      for (const TagEvent &e : log_)
        if (e.used && e.handle < below && (!newest || e.handle > newest->handle)) newest = &e;
      if (!newest) break;
      below = newest->handle;
      Serial.printf("TAG age=%lus cube=%lu result=%s uid=", (unsigned long)(uint32_t(now - newest->at) / 1000),
                    (unsigned long)newest->cubeID, resultName(newest->result));
      printHex(newest->uid, newest->uidLength);
      Serial.println();
    }
    Serial.println("LOG END");
  } else if (is("help")) {
    Serial.println("Commands: ? (report), db (records), log (recent tags), help");
  } else {
    return false;
  }
  return true;
}

}  // namespace nctzone
