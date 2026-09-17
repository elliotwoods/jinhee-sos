#include <cassert>
#include <cstring>
#include "../firmware/PoolCentralTest/PoolOutput.h"
int main() {
  assert(memberBit(0)==0 && memberBit(24)==0);
  assert(memberBit(1)==1 && memberBit(16)==0x8000 && memberBit(17)==0x10000 && memberBit(23)==0x400000);
  assert((boardMask(0)|boardMask(1))==0x7fffff && !(boardMask(0)&boardMask(1)));
  assert(validMode(0x20,4) && validMode(0xa0,4));
  assert(!validMode(0x10,4) && !validMode(0x21,4) && !validMode(0x60,4) && !validMode(0x20,0x14));
  uint8_t b[4], on[]={0,0x10,0,0}, off[]={0,0,0,0x10};
  encodeOutput(true,b); assert(!memcmp(b,on,4));
  encodeOutput(false,b); assert(!memcmp(b,off,4));
}
