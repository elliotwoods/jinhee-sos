#pragma once
#include <Wire.h>
inline bool pn532TraceAll = false;  // nfc_poll trace:1 — every I2C transaction, not only failures
#ifdef ARDUINO_ARCH_ESP32
// Reference Arduino Wire transport with bounded transaction diagnostics.
// Reads are copied only after Wire reports success; failed reads return no data.
class Pn532Wire : public TwoWire {
  uint8_t tx[128]={}, rx[128]={};
  size_t txUsed=0, rxUsed=0, rxPosition=0;
  void trace(const char *direction, size_t requested, int status,
             const uint8_t *data, size_t count, uint32_t started) {
    // Every host discards status-0 lines, and the station's always-on trace was ~9 kB/s while
    // polling, which would starve the zone/show relays' availableForWrite checks.
    if(status==0 && !pn532TraceAll) return;
    if(Serial.availableForWrite()<200) return;
    Serial.printf("{\"event\":\"nfc_i2c\",\"direction\":\"%s\",\"requested\":%u,\"status\":%d,\"ms\":%lu,\"hex\":\"",
                  direction,unsigned(requested),status,(unsigned long)(millis()-started));
    for(size_t i=0;i<count;i++) Serial.printf("%02X",data[i]);
    Serial.println("\"}");
  }
public:
  Pn532Wire():TwoWire(0) {}
  bool end() override { rxUsed=rxPosition=txUsed=0; return TwoWire::end(); }
  void beginTransmission(uint8_t target) override { txUsed=0; TwoWire::beginTransmission(target); }
  size_t write(uint8_t value) override { return write(&value,1); }
  size_t write(const uint8_t *data,size_t length) override {
    size_t written=0;
    while(written<length && TwoWire::write(data[written])) written++;
    size_t copied=min(written,sizeof(tx)-txUsed);
    memcpy(tx+txUsed,data,copied);txUsed+=copied;return written;
  }
  uint8_t endTransmission() override { return endTransmission(true); }
  uint8_t endTransmission(bool stop) override {
    uint32_t started=millis(); uint8_t result=TwoWire::endTransmission(stop);
    trace("write",txUsed,result,tx,txUsed,started);txUsed=0;return result;
  }
  size_t requestFrom(uint8_t target,size_t length) override { return requestFrom(target,length,true); }
  size_t requestFrom(uint8_t target,size_t length,bool stop) override {
    rxPosition=rxUsed=0;
    if(length>sizeof(rx)) return 0;
    uint32_t started=millis();size_t received=TwoWire::requestFrom(target,length,stop);
    while(TwoWire::available() && rxUsed<sizeof(rx)) rx[rxUsed++]=TwoWire::read();
    trace("read",length,received==length ? 0 : -1,rx,rxUsed,started);
    return rxUsed;
  }
  int available() override { return int(rxUsed-rxPosition); }
  int read() override { return rxPosition<rxUsed ? rx[rxPosition++] : -1; }
  int peek() override { return rxPosition<rxUsed ? rx[rxPosition] : -1; }
  void flush() override { rxPosition=rxUsed; }
};
#else
using Pn532Wire = decltype(Wire);  // the host test harness's Wire stub
#endif
