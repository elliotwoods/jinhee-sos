#include "NctZoneDb.h"
#include <cstdlib>
#include <cstring>

namespace nctzone {

uint32_t crc32(const uint8_t *data, size_t len, uint32_t crc) {
  crc = ~crc;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}

int compareUid(const uint8_t *uidA, uint8_t lengthA, const uint8_t *uidB, uint8_t lengthB) {
  if (lengthA != lengthB) return lengthA < lengthB ? -1 : 1;
  return memcmp(uidA, uidB, lengthA);
}

bool validRecord(const Record &r) {
  if (r.cubeID == 0 || r.uidLength < 1 || r.uidLength > 7) return false;
  for (int i = r.uidLength; i < 7; i++)
    if (r.uid[i]) return false;
  if (r.mac[0] & 1) return false;  // multicast/broadcast is never a cube
  static const uint8_t zero[6] = {};
  return memcmp(r.mac, zero, 6) != 0;
}

bool validRecords(const Record *records, uint16_t count) {
  if (count && !records) return false;
  for (uint16_t i = 0; i < count; i++) {
    if (!validRecord(records[i])) return false;
    if (i && compareUid(records[i - 1].uid, records[i - 1].uidLength, records[i].uid, records[i].uidLength) >= 0)
      return false;
  }
  return true;
}

bool loadConfig(Storage &storage, ZoneConfig &config) {
  memset(&config, 0, sizeof(config));
  if (storage.size() < sizeof(config) || !storage.read(0, (uint8_t *)&config, sizeof(config))) return false;
  bool ok = !memcmp(config.magic, "NZCF", 4) && config.format == CONFIG_FORMAT &&
            config.crc == crc32((const uint8_t *)&config, offsetof(ZoneConfig, crc)) &&
            memchr(config.name, 0, sizeof(config.name)) != nullptr;
  if (!ok) memset(&config, 0, sizeof(config));
  return ok;
}

bool loadParams(Storage &storage, ZoneParams &params) {
  memset(&params, 0, sizeof(params));
  if (storage.size() < PARAMS_OFFSET + sizeof(params) || !storage.read(PARAMS_OFFSET, (uint8_t *)&params, sizeof(params)))
    return false;
  bool ok = !memcmp(params.magic, "NZPR", 4) && params.format == 1 && params.count <= 8 &&
            params.crc == crc32((const uint8_t *)&params, offsetof(ZoneParams, crc));
  if (!ok) memset(&params, 0, sizeof(params));
  return ok;
}

ZoneDb::~ZoneDb() { free(records_); }

uint16_t ZoneDb::capacityFor(size_t storageSize) {
  if (storageSize <= sizeof(SlotHeader)) return 0;
  size_t n = (storageSize - sizeof(SlotHeader)) / RECORD_SIZE;
  return n > 0xFFFF ? 0xFFFF : uint16_t(n);
}

uint16_t ZoneDb::capacity() const {
  uint16_t a = slots_[0] ? capacityFor(slots_[0]->size()) : 0;
  uint16_t b = slots_[1] ? capacityFor(slots_[1]->size()) : 0;
  return a < b ? a : b;
}

bool ZoneDb::readHeader(Storage *storage, SlotHeader &h) const {
  if (!storage || !storage->read(0, (uint8_t *)&h, sizeof(h))) return false;
  return !memcmp(h.magic, "NZDB", 4) && h.format == SLOT_FORMAT && h.recordSize == RECORD_SIZE &&
         h.headerCrc == crc32((const uint8_t *)&h, offsetof(SlotHeader, headerCrc)) &&
         h.count <= capacityFor(storage->size());
}

Record *ZoneDb::readRecords(Storage *storage, const SlotHeader &h) const {
  size_t bytes = size_t(h.count) * RECORD_SIZE;
  Record *records = (Record *)malloc(bytes ? bytes : 1);
  if (!records) return nullptr;
  if ((bytes && !storage->read(sizeof(SlotHeader), (uint8_t *)records, bytes)) ||
      crc32((const uint8_t *)records, bytes) != h.recordsCrc || !validRecords(records, h.count)) {
    free(records);
    return nullptr;
  }
  return records;
}

int ZoneDb::begin(Storage *slotA, Storage *slotB) {
  free(records_);
  records_ = nullptr;
  count_ = 0; version_ = generation_ = 0; crc_ = crc32(nullptr, 0); active_ = 0;
  slots_[0] = slotA; slots_[1] = slotB;
  SlotHeader headers[2];
  bool valid[2] = {readHeader(slotA, headers[0]), readHeader(slotB, headers[1])};
  int order[2] = {0, 1};
  if (valid[0] && valid[1]) {
    bool bNewer = headers[1].dbVersion > headers[0].dbVersion ||
                  (headers[1].dbVersion == headers[0].dbVersion && headers[1].generation > headers[0].generation);
    if (bNewer) { order[0] = 1; order[1] = 0; }
  } else if (valid[1]) {
    order[0] = 1; order[1] = 0;
  }
  for (int k = 0; k < 2; k++) {
    int i = order[k];
    if (!valid[i]) continue;
    Record *records = readRecords(slots_[i], headers[i]);
    if (!records) continue;
    records_ = records;
    count_ = headers[i].count;
    version_ = headers[i].dbVersion;
    generation_ = headers[i].generation;
    crc_ = headers[i].recordsCrc;
    active_ = i + 1;
    break;
  }
  return active_;
}

const Record *ZoneDb::find(const uint8_t *uid, uint8_t length) const {
  int lo = 0, hi = int(count_) - 1;
  while (lo <= hi) {
    int mid = (lo + hi) / 2;
    int c = compareUid(records_[mid].uid, records_[mid].uidLength, uid, length);
    if (c == 0) return &records_[mid];
    if (c < 0) lo = mid + 1; else hi = mid - 1;
  }
  return nullptr;
}

bool ZoneDb::commit(uint32_t dbVersion, Record *records, uint16_t count) {
  int target = active_ == 1 ? 1 : 0;
  Storage *storage = slots_[target];
  size_t bytes = size_t(count) * RECORD_SIZE;
  if (!storage || count > capacityFor(storage->size()) || !validRecords(records, count)) {
    free(records);
    return false;
  }
  SlotHeader h = {};
  memcpy(h.magic, "NZDB", 4);
  h.format = SLOT_FORMAT;
  h.recordSize = RECORD_SIZE;
  h.count = count;
  h.dbVersion = dbVersion;
  h.generation = generation_ + 1;
  h.recordsCrc = crc32((const uint8_t *)records, bytes);
  h.headerCrc = crc32((const uint8_t *)&h, offsetof(SlotHeader, headerCrc));
  // Header is written last: an interrupted write leaves this slot invalid and the other active.
  bool ok = storage->erase() &&
            (!bytes || storage->write(sizeof(SlotHeader), (const uint8_t *)records, bytes)) &&
            storage->write(0, (const uint8_t *)&h, sizeof(h));
  if (ok) {
    SlotHeader check;
    ok = readHeader(storage, check) && !memcmp(&check, &h, sizeof(h));
    uint32_t crc = 0;
    uint8_t buffer[256];
    for (size_t offset = 0; ok && offset < bytes; offset += sizeof(buffer)) {
      size_t n = bytes - offset < sizeof(buffer) ? bytes - offset : sizeof(buffer);
      ok = storage->read(sizeof(SlotHeader) + offset, buffer, n);
      crc = crc32(buffer, n, crc);
    }
    ok = ok && crc == h.recordsCrc;
  }
  if (!ok) {
    free(records);
    return false;
  }
  free(records_);
  records_ = records;
  count_ = count;
  version_ = dbVersion;
  generation_ = h.generation;
  crc_ = h.recordsCrc;
  active_ = target + 1;
  return true;
}

}  // namespace nctzone
