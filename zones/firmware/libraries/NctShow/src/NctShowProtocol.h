#pragma once
// Main show wire format: wireless show-image updates for neocubes and the show timecode.
//
// Frames carry the 'N','Z',PROTO header and inherit the length rules in NctZoneProtocol.h (never
// 2 or 24 bytes: the media bridge and old cubes claim those lengths). Like pool and preshow frames
// they are DELIBERATELY absent from nctzone::frameType(): ZoneLink would queue and then drop them.
// Cubes decode them with nctshow::frameType(). Types 0x50..0x54 are reserved here; NctZoneProtocol.h
// must not reuse them. This library is separate and self-contained on purpose: the cube and the
// Mainshow controller include it without compiling NctZone, and zone manifests hash NctZone/src.
//
// Compatibility: cubes older than v1.5.0 drop every frame that is not 24 bytes, so they ignore all
// of these and keep playing their compiled-in show. MSG_SHOW_START (the 24-byte Packet) is
// unchanged; a controller that never sends SHOW_TIMECODE works exactly as before. Timecode is only
// a fallback for a ready cube that missed the start, plus drift correction.
//
// Update flow (host via a relay dongle): SHOW_ANNOUNCE, every SHOW_CHUNK (broadcast), SHOW_QUERY;
// repeat until each expected cube's SHOW_STATUS reports the announced version and CRC. A cube only
// accepts a version above its own unless the announce is unicast and FORCE. It never commits while
// a show is running; the new image then plays from the next start.
#include <stdint.h>
#include <stddef.h>
#include "NctShowEngine.h"

namespace nctshow {

constexpr uint8_t MAGIC0 = 'N', MAGIC1 = 'Z', PROTO = 1;  // identical to nctzone

#pragma pack(push, 1)
struct Header { uint8_t magic0, magic1, proto, type; };  // layout identical to nctzone::Header
#pragma pack(pop)
inline void fillHeader(Header &h, uint8_t type) { h.magic0 = MAGIC0; h.magic1 = MAGIC1; h.proto = PROTO; h.type = type; }

enum ShowMessageType : uint8_t {
  SHOW_ANNOUNCE = 0x50,  // host -> cubes, broadcast or unicast
  SHOW_CHUNK = 0x51,     // host -> cubes, broadcast
  SHOW_QUERY = 0x52,     // host -> cubes; each answers SHOW_STATUS unicast after a random delay
  SHOW_STATUS = 0x53,    // cube -> querier (also sent unsolicited after a commit)
  SHOW_TIMECODE = 0x54,  // show controller -> cubes, broadcast about once a second while a show runs
  SHOW_LIVE = 0x55,      // show editor -> cubes (v1.7.0+), broadcast ~20 Hz: authoring cubes mirror the editor
};

// SHOW_LIVE: the editor's live program for authoring cubes. Each entry names a registered cube number
// and the colour it shows now (levels 0..100). A cube that finds its number shows that colour for
// leaseMs, then returns to what it showed before; a cube playing a show ignores it.
constexpr uint8_t LIVE_MAX_ENTRIES = 48;
constexpr uint16_t LIVE_LEASE_MAX_MS = 2000;

constexpr uint8_t CHUNK_DATA = 200;         // every chunk carries this many bytes; the last is zero-padded
constexpr uint16_t MAX_CHUNKS = (MAX_IMAGE + CHUNK_DATA - 1) / CHUNK_DATA;
constexpr uint16_t MAX_REPLY_JITTER_MS = 5000;
constexpr uint32_t STAGING_TIMEOUT_MS = 60000;
constexpr uint32_t TIMECODE_INTERVAL_MS = 1000;
constexpr uint32_t DRIFT_LIMIT_MS = 100;     // a running cube snaps to timecode beyond this
constexpr uint32_t DEFAULT_LENGTH_MS = 298000;  // the compiled-in show, for controllers without a config

enum AnnounceFlags : uint8_t { ANNOUNCE_FORCE = 0x01 };  // honoured only when unicast
enum ShowSource : uint8_t { SOURCE_BUILTIN = 0, SOURCE_NVS = 1 };
enum ShowError : uint8_t {
  ERR_NONE = 0, ERR_ALLOC = 1, ERR_CRC = 2, ERR_INVALID = 3, ERR_COMMIT = 4, ERR_TIMEOUT = 5, ERR_ANNOUNCE = 6,
};

#pragma pack(push, 1)
struct ShowAnnounce {
  Header h;
  uint32_t version;
  uint32_t crc32;       // CRC-32 of the image bytes (length bytes, no padding)
  uint16_t length;      // image bytes
  uint16_t chunkCount;  // ceil(length / CHUNK_DATA)
  uint8_t chunkSize;    // CHUNK_DATA
  uint8_t flags;
};
struct ShowChunk {
  Header h;
  uint32_t version;
  uint16_t index;
  uint8_t n;  // meaningful bytes in data (1..CHUNK_DATA)
  uint8_t data[CHUNK_DATA];
};
struct ShowQuery {
  Header h;
  uint32_t nonce;
  uint16_t jitterMs;  // reply after a random delay in [0, jitterMs]
};
struct ShowStatus {
  Header h;
  uint32_t nonce;          // of the query answered; 0 when unsolicited
  uint32_t version;        // 0 = compiled-in show
  uint32_t crc;            // CRC-32 of the active image
  uint16_t length;         // active image bytes
  uint32_t stagingVersion; // 0 = not staging
  uint16_t stagingChunks;
  uint16_t stagingTotal;
  uint32_t cubeId;         // 0 = unregistered
  uint8_t source;          // ShowSource
  uint8_t lastError;       // ShowError
  uint8_t zone;
  uint8_t showRunning;
  uint8_t pendingCommit;   // a complete image waits for the show to end
  uint32_t uptimeS;
  char fw[16];             // NUL-padded firmware version
};
struct LiveEntry {
  uint16_t cube;  // registered cube number (1..65535)
  uint8_t r, g, b;
};
struct ShowLiveHeader {
  Header h;
  uint16_t leaseMs;  // 1..LIVE_LEASE_MAX_MS
  uint8_t n;         // 1..LIVE_MAX_ENTRIES entries follow
};
struct ShowTimecode {
  Header h;
  uint32_t showId;       // same id as the MSG_SHOW_START burst
  uint32_t tMs;          // show time when sent
  uint32_t showVersion;  // informational: the show the controller was configured for (0 unknown)
  uint32_t showCrc;
};
#pragma pack(pop)

static_assert(sizeof(ShowAnnounce) == 18, "announce layout");
static_assert(sizeof(ShowChunk) == 211, "chunk layout");
static_assert(sizeof(ShowQuery) == 10, "query layout");
static_assert(sizeof(ShowStatus) == 55, "status layout");
static_assert(sizeof(ShowTimecode) == 20, "timecode layout");
static_assert(sizeof(LiveEntry) == 5 && sizeof(ShowLiveHeader) == 7, "live layout");
inline constexpr size_t liveLength(uint8_t n) { return sizeof(ShowLiveHeader) + sizeof(LiveEntry) * size_t(n); }
static_assert(liveLength(LIVE_MAX_ENTRIES) <= 250, "live frame exceeds ESP-NOW payload");
// 7 + 5n is never 2 or 24.
static_assert(sizeof(ShowAnnounce) != 24 && sizeof(ShowChunk) != 24 && sizeof(ShowQuery) != 24 &&
              sizeof(ShowStatus) != 24 && sizeof(ShowTimecode) != 24, "frame length collides with cube Packet");

// Returns the message type, or 0 if data is not a well-formed show frame of the exact length.
inline uint8_t frameType(const uint8_t *data, int len) {
  if (!data || len < int(sizeof(Header)) || len == 2 || len == 24) return 0;
  if (data[0] != MAGIC0 || data[1] != MAGIC1 || data[2] != PROTO) return 0;
  switch (data[3]) {
    case SHOW_ANNOUNCE: return len == int(sizeof(ShowAnnounce)) ? data[3] : 0;
    case SHOW_CHUNK: {
      if (len != int(sizeof(ShowChunk))) return 0;
      uint8_t n = data[offsetof(ShowChunk, n)];
      return (n >= 1 && n <= CHUNK_DATA) ? data[3] : 0;
    }
    case SHOW_QUERY: return len == int(sizeof(ShowQuery)) ? data[3] : 0;
    case SHOW_STATUS: return len == int(sizeof(ShowStatus)) ? data[3] : 0;
    case SHOW_TIMECODE: return len == int(sizeof(ShowTimecode)) ? data[3] : 0;
    case SHOW_LIVE: {
      if (len < int(liveLength(1))) return 0;
      uint8_t n = data[offsetof(ShowLiveHeader, n)];
      return (n >= 1 && n <= LIVE_MAX_ENTRIES && len == int(liveLength(n))) ? data[3] : 0;
    }
    default: return 0;
  }
}

inline ShowTimecode makeTimecode(uint32_t showId, uint32_t tMs, uint32_t version, uint32_t crc) {
  ShowTimecode f{};
  fillHeader(f.h, SHOW_TIMECODE);
  f.showId = showId; f.tMs = tMs; f.showVersion = version; f.showCrc = crc;
  return f;
}

}  // namespace nctshow
