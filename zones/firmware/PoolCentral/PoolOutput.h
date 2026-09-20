#pragma once
#include <stdint.h>

inline uint32_t memberBit(uint8_t member) { return member>=1 && member<=23 ? uint32_t(1)<<(member-1) : 0; }

// Physical wiring map. The driver outputs are not wired to the frames in order, so member
// number and output index are different things and must not be conflated.
//
// Measured on the installation on 2026-09-21 by selecting each slider index in turn and
// recording which frame actually lit:
//
//   output index driven :  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
//   frame that lit      :  1 15 20 16  5  7 23 21 12 18  6 13  8 22  3 17 14 10  2 11 19  4  9
//
// This table is the inverse of that: POOL_OUTPUT_FOR_MEMBER[m-1] is the output to drive to
// light frame m. Re-measure and replace the row above (and regenerate this one) if the
// looms are ever re-terminated.
constexpr uint8_t POOL_OUTPUT_FOR_MEMBER[23] = {1, 19, 15, 22, 5, 11, 6, 13, 23, 18, 20, 9, 12, 17, 2, 4, 16, 10, 21, 3, 8, 14, 7};

// Guards against a mistyped table: every frame must be reachable by exactly one output.
constexpr bool poolMapIsPermutation() {
  bool seen[24] = {};
  for (uint8_t i = 0; i < 23; ++i) {
    uint8_t out = POOL_OUTPUT_FOR_MEMBER[i];
    if (out < 1 || out > 23 || seen[out]) return false;
    seen[out] = true;
  }
  return true;
}
static_assert(poolMapIsPermutation(), "POOL_OUTPUT_FOR_MEMBER must be a permutation of 1..23");

inline uint8_t outputForMember(uint8_t member) {
  return member >= 1 && member <= 23 ? POOL_OUTPUT_FOR_MEMBER[member - 1] : 0;
}
// Outputs 1-16 are board 0x40 channels 0-15; outputs 17-23 are board 0x41 channels 0-6.
inline uint8_t memberBoard(uint8_t member) { return outputForMember(member) > 16; }
inline uint8_t memberChannel(uint8_t member) {
  uint8_t out = outputForMember(member);
  return uint8_t(out - (out > 16 ? 17 : 1));
}

// Which MEMBERS live on a driver board. Not a contiguous range any more: the wiring map
// scatters them across both boards, so this must be derived rather than assumed.
inline uint32_t boardMask(uint8_t board) {
  uint32_t mask = 0;
  for (uint8_t m = 1; m <= 23; ++m) if (memberBoard(m) == board) mask |= memberBit(m);
  return mask;
}
inline bool validMode(uint8_t mode1,uint8_t mode2) { return (mode1&0x7F)==0x20 && mode2==0x04; }

// Output polarity, per OUTPUT index. A bit set here means that output is ACTIVE LOW: its
// relay coil is energised by a LOW output, so the lamp is lit by driving the channel low.
//
//     lamp ON  -> channel LOW   when active-low, HIGH when active-high
//     lamp OFF -> channel HIGH  when active-low, LOW  when active-high
//
// All 23 are active low: every relay behaves the same way round on the installation as
// wired. It is expressed per output rather than as one flag because the two driver boards
// were at one point observed to behave oppositely - sixteen frames on 0x40 inverted while
// the seven on 0x41 were correct - which a single flag cannot describe. That turned out to
// be a wiring difference and was corrected in the wiring, but the shape of the setting is
// kept so the same thing is a data change rather than a redesign.
//
// This is the only place polarity is expressed. Every write, readback comparison, audit and
// ALL_LED clear derives from encodeOutput(), and the logs and telemetry stay in terms of the
// lamp, never the relay.
constexpr uint32_t POOL_ACTIVE_LOW_OUTPUTS = 0x7FFFFFu;  // all 23 outputs

inline bool outputActiveLow(uint8_t out) {
  return out >= 1 && out <= 23 && ((POOL_ACTIVE_LOW_OUTPUTS >> (out - 1)) & 1u) != 0;
}

// bytes are LEDn_ON_L, LEDn_ON_H, LEDn_OFF_L, LEDn_OFF_H. Bit 4 of each _H byte is the
// PCA9685 FULL_ON / FULL_OFF flag; these outputs are switched, never dimmed.
inline void encodeOutputFor(uint8_t out, bool lamp, uint8_t *bytes) {
  const bool high = outputActiveLow(out) ? !lamp : lamp;
  bytes[0]=0; bytes[1]=high?0x10:0; bytes[2]=0; bytes[3]=high?0:0x10;
}

// Every output on a board shares a polarity in this installation (one relay module each),
// which is what lets ALL_LED express the dark state for a whole board in one write. Checked
// rather than assumed: a mixed board falls back to per-channel writes.
inline bool boardPolarityUniform(uint8_t board, bool *activeLow) {
  bool seen = false, first = false;
  for (uint8_t out = 1; out <= 23; ++out) {
    if ((out > 16) != (board != 0)) continue;
    bool low = outputActiveLow(out);
    if (!seen) { first = low; seen = true; }
    else if (low != first) return false;
  }
  if (activeLow) *activeLow = first;
  return seen;
}

// Encode for a FRAME, resolving the wiring map and that output's polarity.
inline void encodeOutput(uint8_t member, bool lamp, uint8_t *bytes) {
  encodeOutputFor(outputForMember(member), lamp, bytes);
}
