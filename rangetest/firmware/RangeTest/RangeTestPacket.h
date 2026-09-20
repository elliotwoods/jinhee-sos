// ESP-NOW range test wire format. One sketch builds both roles, so there is a
// single definition of this struct and the two ends cannot drift apart.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace rangetest {

// 'R','T','L','1' little-endian. Deliberately NOT 0x3154524E ('N','R','T','1'):
// that first byte equals the zone protocol's MAGIC0 ('N') and would survive only
// on the second byte, which is no margin at all against a protocol we must not
// disturb, and is confusing in a sniffer dump.
constexpr uint32_t MAGIC = 0x314C5452;
constexpr uint8_t VERSION = 1;
constexpr uint8_t CHANNEL = 2;

constexpr uint8_t TYPE_PING = 1;   // TX -> RX
constexpr uint8_t TYPE_ACK = 2;    // RX -> TX

constexpr uint8_t ROLE_TX = 1;
constexpr uint8_t ROLE_RX = 2;

// 127 means "not measured": real RSSI/noise floor are negative dBm, so 127 can
// never be confused with a reading.
constexpr int8_t RSSI_UNKNOWN = 127;

#pragma pack(push, 1)
struct RangeTestPacket {
  uint32_t magic;
  uint8_t version;
  uint8_t type;
  uint8_t role;           // sender's role, for banner/log cross-checking
  uint8_t reserved;
  uint32_t bootId;        // random per boot; identifies a TX restart
  uint32_t seq;           // TX ping counter, echoed in the ACK
  uint32_t originTxMicros;// TX departure micros(), echoed in the ACK
  uint32_t turnaroundUs;  // ACK only: RX micros() spent between receive and reply
  int8_t rssi;            // ACK only: uplink RSSI the RX measured for the ping
  int8_t noiseFloor;      // ACK only: uplink noise floor the RX measured
  uint8_t channel;        // ACK only: channel the RX received the ping on
  uint8_t reserved2;
  uint8_t originMac[6];   // the TX that sent the ping; lets TX filter its own ACKs
  uint8_t pad[2];
};
#pragma pack(pop)

static_assert(sizeof(RangeTestPacket) == 36, "Wire format must stay 36 bytes");
static_assert(offsetof(RangeTestPacket, magic) == 0, "magic must lead the frame");
static_assert(offsetof(RangeTestPacket, bootId) == 8, "field offsets are the wire format");
static_assert(offsetof(RangeTestPacket, seq) == 12, "field offsets are the wire format");
static_assert(offsetof(RangeTestPacket, originMac) == 28, "field offsets are the wire format");

// Non-interference is an invariant of this installation, so make it a compile
// error rather than something a future reader has to remember. Every live
// receiver on channel 2 gates on frame length before doing anything else:
// cube = 24, pool radio = 15, preshow media bridge = 2. Zone frames additionally
// reject lengths 2 and 24 and then require a 'N','Z' magic.
static_assert(sizeof(RangeTestPacket) != 24 && sizeof(RangeTestPacket) != 15 &&
                sizeof(RangeTestPacket) != 2,
              "length collides with cube / pool radio / media bridge frames");

}  // namespace rangetest
