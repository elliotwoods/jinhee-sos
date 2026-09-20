#pragma once
// Zone-management wire format. Shared by zone boards and the registry (pairing) station.
// Every frame starts with 'N','Z',PROTO,type. Neocubes drop frames whose length is not 24
// and the preshow media bridge drops frames whose length is not 2, so no frame here may
// be either length (enforced below and in minimumLength()).
#include <stdint.h>
#include <stddef.h>

namespace nctzone {

constexpr uint8_t MAGIC0 = 'N', MAGIC1 = 'Z', PROTO = 1;
constexpr uint8_t ESPNOW_CHANNEL = 2;

enum MessageType : uint8_t {
  DB_ANNOUNCE   = 0x10,
  DB_CHUNK      = 0x11,
  ZONE_QUERY    = 0x20,
  ZONE_STATUS   = 0x21,
  ZONE_LOG      = 0x22,
  ZONE_IDENTIFY = 0x23,
  ZONE_REBOOT   = 0x24,
  // 0x30 POOL_STATE and 0x31 POOL_BEACON are reserved by NctPoolProtocol.h and are
  // deliberately NOT handled by frameType() below: ZoneLink::receive() queues every
  // frame frameType() accepts and ZoneLink::handle() drops what it does not know, so
  // routing them here would swallow them before the pool sketch ever sees them. They
  // reach the sketch through TagPlate::onFrame instead. Do not reuse these values.
};

// Matches the neocube ZoneType enum (value sent in Packet.success of MSG_SET_ZONE).
enum ZoneType : uint8_t { ZONE_IDLE = 0, ZONE_PRESHOW = 1, ZONE_DESERT = 2, ZONE_POOL = 3, ZONE_MAINSHOW = 4 };

enum QueryWhat : uint8_t { QUERY_STATUS = 1, QUERY_LOG = 2 };

enum AnnounceFlags : uint8_t { ANNOUNCE_FORCE = 0x01 };  // honoured only when unicast

enum TagResult : uint8_t { TAG_UNKNOWN = 0, TAG_DELIVERED = 1, TAG_UNCONFIRMED = 2, TAG_PENDING = 3 };

enum ZoneError : uint8_t {
  ERR_NONE = 0, ERR_CONFIG = 1, ERR_DB_EMPTY = 2, ERR_NFC = 3, ERR_RADIO = 4,
  ERR_STAGING_ALLOC = 5, ERR_STAGING_CRC = 6, ERR_STAGING_INVALID = 7, ERR_COMMIT = 8, ERR_STAGING_TIMEOUT = 9,
  ERR_PARAMS = 10, ERR_SENSOR = 11,
};

constexpr uint8_t RECORD_SIZE = 18;
constexpr uint8_t MAX_RECORDS_PER_CHUNK = 12;
constexpr uint8_t LOG_ENTRIES = 8;
constexpr uint32_t REBOOT_CONFIRM = 0x544F4F42;  // "BOOT"

#pragma pack(push, 1)

struct Record {
  uint32_t cubeID;
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t mac[6];
};

struct Header {
  uint8_t magic0, magic1, proto, type;
};

struct DbAnnounce {
  Header h;
  uint32_t dbVersion;
  uint16_t count;
  uint16_t chunkCount;
  uint8_t recordsPerChunk;
  uint8_t flags;
  uint32_t crc32;  // zlib CRC-32 of the sorted record bytes
};

struct DbChunkHeader {
  Header h;
  uint32_t dbVersion;
  uint16_t index;
  uint8_t n;
};

struct DbChunk {
  DbChunkHeader c;
  Record records[MAX_RECORDS_PER_CHUNK];
};

struct ZoneQuery {
  Header h;
  uint32_t nonce;
  uint8_t what;
};

struct ZoneStatus {
  Header h;
  uint32_t nonce;
  uint8_t zoneType;
  uint8_t pointId;
  char name[16];
  char firmware[16];
  uint32_t dbVersion;
  uint16_t dbCount;
  uint32_t dbCrc;
  uint32_t stagingVersion;
  uint16_t stagingChunks;
  uint16_t stagingTotal;
  uint32_t uptimeS;
  uint32_t tagCount;
  uint32_t unknownTagCount;
  uint32_t sendFailCount;
  uint8_t lastError;
  uint8_t channel;
  uint8_t configValid;
  uint8_t activeSlot;  // 0 none, 1 A, 2 B
};

struct LogEntry {
  uint8_t uidLength;
  uint8_t uid[7];
  uint32_t cubeID;
  uint8_t result;
  uint32_t ageS;
};

struct ZoneLog {
  Header h;
  uint32_t nonce;
  uint8_t n;
  LogEntry entries[LOG_ENTRIES];
};

struct ZoneIdentify {
  Header h;
  uint8_t seconds;
};

struct ZoneReboot {
  Header h;
  uint32_t confirm;
};

#pragma pack(pop)

constexpr size_t CHUNK_HEADER_SIZE = sizeof(DbChunkHeader);

static_assert(sizeof(Record) == RECORD_SIZE, "record layout");
static_assert(sizeof(DbAnnounce) == 18, "announce layout");
static_assert(CHUNK_HEADER_SIZE == 11, "chunk header layout");
static_assert(CHUNK_HEADER_SIZE + RECORD_SIZE * MAX_RECORDS_PER_CHUNK <= 250, "chunk exceeds ESP-NOW payload");
static_assert(sizeof(ZoneQuery) == 9, "query layout");
static_assert(sizeof(ZoneStatus) == 80, "status layout");
static_assert(sizeof(LogEntry) == 17, "log entry layout");
static_assert(sizeof(ZoneLog) == 9 + 17 * LOG_ENTRIES, "log layout");
static_assert(sizeof(ZoneIdentify) == 5, "identify layout");
static_assert(sizeof(ZoneReboot) == 8, "reboot layout");
// Collision guard with neocube (24) and media bridge (2) frames.
static_assert(sizeof(DbAnnounce) != 24 && sizeof(ZoneQuery) != 24 && sizeof(ZoneStatus) != 24 &&
              sizeof(ZoneIdentify) != 24 && sizeof(ZoneReboot) != 24, "frame length collides with cube Packet");

inline constexpr size_t chunkLength(uint8_t n) { return CHUNK_HEADER_SIZE + size_t(RECORD_SIZE) * n; }
// n=0 is never sent; 11 + 18n is never 24 or 2 for n>=1.

inline void fillHeader(Header &h, uint8_t type) {
  h.magic0 = MAGIC0; h.magic1 = MAGIC1; h.proto = PROTO; h.type = type;
}

// Returns the message type, or 0 if data is not a well-formed zone frame of an acceptable length.
inline uint8_t frameType(const uint8_t *data, int len) {
  if (!data || len < int(sizeof(Header)) || len == 2 || len == 24) return 0;
  if (data[0] != MAGIC0 || data[1] != MAGIC1 || data[2] != PROTO) return 0;
  switch (data[3]) {
    case DB_ANNOUNCE:   return len == int(sizeof(DbAnnounce)) ? data[3] : 0;
    case DB_CHUNK: {
      if (len < int(chunkLength(1))) return 0;
      uint8_t n = data[offsetof(DbChunkHeader, n)];
      return (n >= 1 && n <= MAX_RECORDS_PER_CHUNK && len == int(chunkLength(n))) ? data[3] : 0;
    }
    case ZONE_QUERY:    return len == int(sizeof(ZoneQuery)) ? data[3] : 0;
    case ZONE_STATUS:   return len == int(sizeof(ZoneStatus)) ? data[3] : 0;
    case ZONE_LOG:      return len == int(sizeof(ZoneLog)) ? data[3] : 0;
    case ZONE_IDENTIFY: return len == int(sizeof(ZoneIdentify)) ? data[3] : 0;
    case ZONE_REBOOT:   return len == int(sizeof(ZoneReboot)) ? data[3] : 0;
    default:            return 0;
  }
}

}  // namespace nctzone
