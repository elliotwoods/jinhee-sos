#pragma once
// Flash-backed cube database with two redundant slots and a zone identity record.
// Hardware-independent: storage is supplied through the Storage interface.
#include "NctZoneProtocol.h"

namespace nctzone {

uint32_t crc32(const uint8_t *data, size_t len, uint32_t crc = 0);  // zlib-compatible, chainable

class Storage {
 public:
  virtual ~Storage() {}
  virtual size_t size() const = 0;
  virtual bool read(size_t offset, uint8_t *out, size_t len) = 0;
  virtual bool write(size_t offset, const uint8_t *data, size_t len) = 0;
  virtual bool erase() = 0;
};

#pragma pack(push, 1)
struct SlotHeader {
  char magic[4];  // "NZDB"
  uint8_t format;
  uint8_t recordSize;
  uint16_t count;
  uint32_t dbVersion;
  uint32_t generation;
  uint32_t recordsCrc;
  uint32_t headerCrc;  // CRC-32 of the preceding 20 bytes
};

struct ZoneConfig {
  char magic[4];  // "NZCF"
  uint8_t format;
  uint8_t zoneType;
  uint8_t pointId;
  uint8_t rxGainDb;  // PN532 RX gain in dB; 0 (older flashers) = RX_GAIN_DEFAULT_DB
  char name[16];  // NUL-terminated
  uint32_t crc;   // CRC-32 of the preceding 24 bytes
};
// Optional per-zone integer parameters (e.g. pool slider calibration), stored after ZoneConfig in zcfg.
struct ZoneParams {
  char magic[4];  // "NZPR"
  uint8_t format;
  uint8_t count;
  uint16_t reserved;
  int32_t values[8];
  uint32_t crc;  // CRC-32 of the preceding 40 bytes
};
#pragma pack(pop)

constexpr size_t PARAMS_OFFSET = 0x40;
static_assert(sizeof(ZoneParams) == 44, "zone params layout");
static_assert(sizeof(SlotHeader) == 24, "slot header layout");
static_assert(sizeof(ZoneConfig) == 28, "zone config layout");

constexpr uint8_t SLOT_FORMAT = 1;
constexpr uint8_t CONFIG_FORMAT = 1;

// Records are ordered by UID length, then UID bytes. Duplicates are invalid.
int compareUid(const uint8_t *uidA, uint8_t lengthA, const uint8_t *uidB, uint8_t lengthB);
bool validRecord(const Record &record);
bool validRecords(const Record *records, uint16_t count);
bool loadConfig(Storage &storage, ZoneConfig &config);
bool loadParams(Storage &storage, ZoneParams &params);
// Rewrites zcfg with `config` (CRC recomputed) and `params` (kept only when paramsValid), then verifies
// by reading both back. The partition is erased first, so a failure can leave zcfg invalid.
bool saveConfig(Storage &storage, ZoneConfig &config, const ZoneParams &params, bool paramsValid);

class ZoneDb {
 public:
  ~ZoneDb();
  // Loads the newest valid slot. Returns the active slot: 0 none, 1 A, 2 B.
  int begin(Storage *slotA, Storage *slotB);
  const Record *find(const uint8_t *uid, uint8_t length) const;
  // Takes ownership of a malloc'd record buffer (freed on failure too). Writes the inactive slot,
  // verifies it by read-back, then activates it. The previously active slot is left intact.
  bool commit(uint32_t dbVersion, Record *records, uint16_t count);

  uint32_t version() const { return version_; }
  uint32_t generation() const { return generation_; }
  uint32_t crc() const { return crc_; }
  uint16_t count() const { return count_; }
  int activeSlot() const { return active_; }
  const Record *records() const { return records_; }
  uint16_t capacity() const;
  static uint16_t capacityFor(size_t storageSize);

 private:
  bool readHeader(Storage *storage, SlotHeader &header) const;
  Record *readRecords(Storage *storage, const SlotHeader &header) const;
  Storage *slots_[2] = {nullptr, nullptr};
  Record *records_ = nullptr;
  uint16_t count_ = 0;
  uint32_t version_ = 0, generation_ = 0, crc_ = 0;
  int active_ = 0;
};

}  // namespace nctzone
