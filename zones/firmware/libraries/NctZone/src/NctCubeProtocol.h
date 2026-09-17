#pragma once
// Neocube wire format. Must stay byte-identical to the cube firmware (ForKimchi.ino): cubes drop any
// ESP-NOW frame whose length is not sizeof(Packet). tests/run_firmware_tests.py checks this struct.
#include <stdint.h>
#include <stddef.h>

enum CubeMessageType : uint8_t {
  MSG_DISCOVER = 1,
  MSG_DISCOVER_REPLY = 2,
  MSG_REGISTER = 3,
  MSG_REGISTER_ACK = 4,
  // 5 is reserved (was MSG_ENTER_OTA)
  MSG_SET_ZONE = 6,   // zone in Packet.success
  MSG_TAG_STATE = 7,  // 1 = tag on plate, 0 = removed, in Packet.success
  MSG_SHOW_START = 8
};

struct Packet {
  uint8_t type;
  uint32_t cubeID;
  uint8_t mac[6];
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t success;
};

static_assert(sizeof(Packet) == 24 && offsetof(Packet, type) == 0 && offsetof(Packet, cubeID) == 4 &&
              offsetof(Packet, mac) == 8 && offsetof(Packet, uidLength) == 14 && offsetof(Packet, uid) == 15 &&
              offsetof(Packet, success) == 22, "Cube ABI changed");
