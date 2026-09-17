#include <initializer_list>
#include <assert.h>
#include <stdio.h>
#include "../firmware/PoolZone/OneEuroFilter.h"

int main() {
  for (uint32_t dt : {20u, 85u}) {
    OneEuroFilter f;
    f.update(200,0);
    double rawError=0, filteredError=0;
    for(uint32_t i=1;i<=300;++i) {
      float raw=200+((i%4<2) ? 4.f : -4.f);
      float value=f.update(raw,i*dt);
      if(i>30) { rawError+=(raw-200)*(raw-200); filteredError+=(value-200)*(value-200); }
    }
    assert(filteredError<rawError*.3); // meaningful stationary jitter reduction at both sampling rates
    uint32_t t=300*dt;
    float value=0;
    for(uint32_t i=1;i*dt<=300;++i) value=f.update(350,t+i*dt);
    assert(fabsf(value-350)<2); // large movement settles within 300ms, without overshoot
    assert(f.update(55,t+2000)==55); // long gap starts fresh
    f.reset(); assert(f.update(100,t+2001)==100);
    assert(isnan(f.update(NAN,t+2010)));
    assert(f.update(80,t+2020)==80);
    assert(f.update(90,t+2020)==80); // no divide-by-zero at duplicate timestamps
    printf("PASS One Euro dt=%ums, stationary RMS %.2f -> %.2f mm; movement and reset checks\n",dt,sqrt(rawError/270),sqrt(filteredError/270));
  }
  OneEuroFilter wrap;
  wrap.update(100,0xfffffff0u);
  float next=wrap.update(101,0x20u);
  assert(next>100 && next<101);
}
