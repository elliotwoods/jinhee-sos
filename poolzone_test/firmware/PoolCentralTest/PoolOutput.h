#pragma once
#include <stdint.h>
inline uint32_t memberBit(uint8_t member) { return member>=1 && member<=23 ? uint32_t(1)<<(member-1) : 0; }
inline uint32_t boardMask(uint8_t board) { return board ? 0x7F0000UL : 0xFFFFUL; }
inline bool validMode(uint8_t mode1,uint8_t mode2) { return (mode1&0x7F)==0x20 && mode2==0x04; }
inline void encodeOutput(bool on,uint8_t *bytes) {
  bytes[0]=0; bytes[1]=on?0x10:0; bytes[2]=0; bytes[3]=on?0:0x10;
}
