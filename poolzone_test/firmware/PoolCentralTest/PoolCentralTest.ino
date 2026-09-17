// Poolzone central controller v2: verified I2C outputs and bounded recovery.
// Same RadioPacket, member mapping and 800ms radio lease as the legacy central.
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdarg.h>
#include "PoolOutput.h"

constexpr uint8_t SDA_PIN=8, SCL_PIN=9, CHANNEL=2;
constexpr uint32_t RADIO_TIMEOUT=800, HEALTH_MS=500, RECOVERY_MS=1000;
struct __attribute__((packed)) RadioPacket {
  uint32_t magic;
  uint8_t radioId, active, member, uidLength, uid[7];
};
static_assert(sizeof(RadioPacket)==15, "Wire format must match radios");
struct RadioState { bool active; uint8_t member; uint32_t seen; };
RadioState incoming[6]={}, radios[6]={};
portMUX_TYPE radioMux=portMUX_INITIALIZER_UNLOCKED;
uint32_t packets=0, lastPacket=0;
uint8_t changedRadios=0;
struct BoardState {
  uint8_t address;
  bool online=false;
  uint8_t mode1=255, mode2=255;
  uint32_t lastOk=0, lastAttempt=0;
};
BoardState boards[2]={{0x40},{0x41}};
bool busStarted=false, radioReady=false;
uint32_t i2cErrors=0, mismatches=0, recoveries=0, logDrops=0;
uint32_t desired=0, verified=0, known=0;
uint32_t lastHealth=0, lastAudit=0, lastStatus=0, lastRecovery=0;
uint8_t auditMember=1;

// Single loop-task producer. Never wait for a USB monitor to consume output.
void logLine(const char *format, ...) {
  char line[1000];
  va_list args; va_start(args,format);
  int count=vsnprintf(line,sizeof(line)-2,format,args); va_end(args);
  if(count<0) return;
  size_t length=min(size_t(count),sizeof(line)-2);
  line[length++]='\n';
  if(Serial && Serial.availableForWrite()>=int(length)) Serial.write((uint8_t*)line,length);
  else ++logDrops;
}

void onReceive(const esp_now_recv_info_t*, const uint8_t *data, int length) {
  if(length!=sizeof(RadioPacket)) return;
  RadioPacket p; memcpy(&p,data,sizeof(p));
  if(p.magic!=0x4E435450 || p.radioId<1 || p.radioId>6) return;
  uint8_t i=p.radioId-1;
  bool active=p.active && p.member>=1 && p.member<=23;
  uint32_t now=millis();
  portENTER_CRITICAL(&radioMux);
  incoming[i]={active,uint8_t(active?p.member:0),now};
  changedRadios|=1<<i;
  ++packets; lastPacket=now;
  portEXIT_CRITICAL(&radioMux);
}

void takeRadios() {
  RadioState snapshot[6]; uint8_t changes;
  portENTER_CRITICAL(&radioMux);
  memcpy(snapshot,incoming,sizeof(snapshot));
  changes=changedRadios; changedRadios=0;
  portEXIT_CRITICAL(&radioMux);
  uint32_t now=millis();
  for(uint8_t i=0;i<6;++i) {
    if(changes&(1<<i)) {
      RadioState next=snapshot[i];
      if(now-next.seen>RADIO_TIMEOUT) next.active=false;
      if(next.active && (!radios[i].active || radios[i].member!=next.member))
        logLine("RADIO %u -> MEMBER %u",i+1,next.member);
      else if(!next.active && radios[i].active) logLine("RADIO %u RELEASE",i+1);
      radios[i]=next;
    }
    if(radios[i].active && now-radios[i].seen>RADIO_TIMEOUT) {
      radios[i].active=false;
      logLine("RADIO TIMEOUT: %u",i+1);
    }
  }
  desired=0;
  for(const auto &r:radios) if(r.active) desired|=memberBit(r.member);
}

void failBoard(uint8_t b, const char *operation, int code) {
  ++i2cErrors; boards[b].online=false;
  known&=~boardMask(b); verified&=~boardMask(b);
  logLine("I2C ERROR addr=0x%02X op=%s code=%d SDA=%d SCL=%d",boards[b].address,operation,code,digitalRead(SDA_PIN),digitalRead(SCL_PIN));
}

bool writeBytes(uint8_t b,uint8_t reg,const uint8_t *data,size_t count) {
  if(!busStarted) return false;
  Wire.beginTransmission(boards[b].address);
  Wire.write(reg); Wire.write(data,count);
  uint8_t error=Wire.endTransmission(true);
  if(error) { failBoard(b,"write",error); return false; }
  return true;
}

bool readBytes(uint8_t b,uint8_t reg,uint8_t *data,size_t count) {
  if(!busStarted) return false;
  Wire.beginTransmission(boards[b].address); Wire.write(reg);
  uint8_t error=Wire.endTransmission(false);
  if(error) { failBoard(b,"read-address",error); return false; }
  size_t received=Wire.requestFrom(boards[b].address,count,true);
  if(received!=count) {
    while(Wire.available()) Wire.read();
    failBoard(b,"read-data",int(received)); return false;
  }
  for(size_t i=0;i<count;++i) data[i]=Wire.read();
  boards[b].lastOk=millis();
  return true;
}

// NXP bus-clear sequence: open-drain only; never drive high against a slave.
// Bounded clock-stretch wait. SCL stuck low requires peripheral/wiring repair.
bool recoverBus() {
  if(busStarted) Wire.end();
  busStarted=false;
  pinMode(SDA_PIN,INPUT_PULLUP); pinMode(SCL_PIN,INPUT_PULLUP);
  delayMicroseconds(50);
  int beforeSda=digitalRead(SDA_PIN), beforeScl=digitalRead(SCL_PIN), pulses=0;
  if(beforeScl && !beforeSda) {
    digitalWrite(SCL_PIN,HIGH); pinMode(SCL_PIN,OUTPUT_OPEN_DRAIN);
    for(int i=0;i<9 && !digitalRead(SDA_PIN);++i) {
      digitalWrite(SCL_PIN,LOW); delayMicroseconds(10);
      digitalWrite(SCL_PIN,HIGH);
      for(int wait=0;wait<100 && !digitalRead(SCL_PIN);++wait) delayMicroseconds(20);
      delayMicroseconds(10); ++pulses;
      if(!digitalRead(SCL_PIN)) break;
    }
    if(digitalRead(SCL_PIN)) {
      digitalWrite(SCL_PIN,LOW);
      digitalWrite(SDA_PIN,LOW); pinMode(SDA_PIN,OUTPUT_OPEN_DRAIN);
      delayMicroseconds(10); digitalWrite(SCL_PIN,HIGH); delayMicroseconds(10);
      digitalWrite(SDA_PIN,HIGH); delayMicroseconds(10);
    }
    pinMode(SDA_PIN,INPUT_PULLUP); pinMode(SCL_PIN,INPUT_PULLUP);
  }
  bool clear=digitalRead(SDA_PIN) && digitalRead(SCL_PIN);
  logLine("I2C BUS sda_before=%d scl_before=%d sda_after=%d scl_after=%d pulses=%d",beforeSda,beforeScl,digitalRead(SDA_PIN),digitalRead(SCL_PIN),pulses);
  if(clear) {
    busStarted=Wire.begin(SDA_PIN,SCL_PIN,100000);
    Wire.setTimeOut(25);
  }
  return busStarted;
}

bool readMode(uint8_t b) {
  // Read individually even if AI was cleared by a peripheral reset.
  if(!readBytes(b,0,&boards[b].mode1,1) || !readBytes(b,1,&boards[b].mode2,1)) return false;
  if(!validMode(boards[b].mode1,boards[b].mode2)) {
    ++mismatches; boards[b].online=false;
    known&=~boardMask(b); verified&=~boardMask(b);
    logLine("I2C MODE MISMATCH addr=0x%02X mode1=0x%02X mode2=0x%02X",boards[b].address,boards[b].mode1,boards[b].mode2);
    return false;
  }
  return true;
}

bool initializeBoard(uint8_t b) {
  boards[b].lastAttempt=millis(); boards[b].online=false;
  known&=~boardMask(b); verified&=~boardMask(b);
  // AI enabled; awake, internal oscillator. MODE2 matches legacy power-on default.
  uint8_t mode1=0x20, mode2=0x04;
  if(!writeBytes(b,0,&mode1,1) || !writeBytes(b,1,&mode2,1)) return false;
  delayMicroseconds(500); // oscillator settling per PCA9685 datasheet
  if(!readMode(b)) return false;
  // Clear ALL_LED overrides and establish a known off state across all 16 outputs.
  const uint8_t off[4]={0,0,0,0x10};
  if(!writeBytes(b,0xFA,off,4)) return false;
  boards[b].online=true;
  logLine("I2C READY addr=0x%02X mode1=0x%02X mode2=0x%02X",boards[b].address,boards[b].mode1,boards[b].mode2);
  return true;
}

bool verifyMember(uint8_t member, bool on, bool write) {
  uint8_t b=member>16, channel=member-(b?17:1);
  if(!boards[b].online) return false;
  uint8_t expected[4], actual[4]; encodeOutput(on,expected);
  if(write && !writeBytes(b,6+4*channel,expected,4)) return false;
  if(!readBytes(b,6+4*channel,actual,4)) return false;
  if(memcmp(expected,actual,4)) {
    ++mismatches;
    known&=~memberBit(member); verified&=~memberBit(member);
    logLine("I2C READBACK MISMATCH member=%u got=%02X%02X%02X%02X",member,actual[0],actual[1],actual[2],actual[3]);
    return false;
  }
  bool wasKnown=known&memberBit(member), wasOn=verified&memberBit(member);
  known|=memberBit(member);
  if(on) verified|=memberBit(member); else verified&=~memberBit(member);
  if(!wasKnown || wasOn!=on) logLine("FRAME %u %s",member,on?"ON":"OFF");
  return true;
}

void maintainOutputs() {
  uint32_t now=millis();
  if((!boards[0].online || !boards[1].online) && now-lastRecovery>=RECOVERY_MS) {
    lastRecovery=now; ++recoveries;
    // Do not disturb the healthy board for an address NACK. Clear the bus if a
    // line is held low or the peripheral driver is not running.
    bool clear=busStarted && digitalRead(SDA_PIN) && digitalRead(SCL_PIN);
    if(!clear) {
      for(auto &b:boards) b.online=false;
      known=verified=0; clear=recoverBus();
    }
    if(clear) for(uint8_t b=0;b<2;++b) if(!boards[b].online) initializeBoard(b);
    takeRadios(); // recovery cannot reapply a lease that expired while blocked
  }
  if(now-lastHealth>=HEALTH_MS) {
    lastHealth=now;
    for(uint8_t b=0;b<2;++b) if(boards[b].online) readMode(b);
    takeRadios();
  }
  for(uint8_t m=1;m<=23;++m) {
    uint32_t bit=memberBit(m);
    if(!(known&bit) || bool(desired&bit)!=bool(verified&bit)) verifyMember(m,desired&bit,true);
  }
  // Audit unchanged outputs too: detect silently reset/corrupted PCA registers.
  if(now-lastAudit>=20) {
    lastAudit=now;
    verifyMember(auditMember,desired&memberBit(auditMember),false);
    auditMember=auditMember%23+1;
  }
}

void status() {
  uint32_t count,seen;
  portENTER_CRITICAL(&radioMux); count=packets; seen=lastPacket; portEXIT_CRITICAL(&radioMux);
  uint8_t actualChannel=0; wifi_second_chan_t secondary;
  esp_wifi_get_channel(&actualChannel,&secondary);
  logLine("{\"device\":\"PoolCentralTest\",\"version\":2,\"uptime_ms\":%lu,\"channel\":%u,\"radio_ready\":%s,\"rx_packets\":%lu,\"last_rx_ms\":%lu,\"desired\":%lu,\"verified\":%lu,\"known\":%lu,\"i2c_errors\":%lu,\"mismatches\":%lu,\"recoveries\":%lu,\"log_drops\":%lu,\"sda\":%d,\"scl\":%d,\"boards\":[{\"addr\":64,\"online\":%s,\"mode1\":%u,\"mode2\":%u},{\"addr\":65,\"online\":%s,\"mode1\":%u,\"mode2\":%u}]}",
    (unsigned long)millis(),actualChannel,radioReady?"true":"false",(unsigned long)count,(unsigned long)(millis()-seen),
    (unsigned long)desired,(unsigned long)verified,(unsigned long)known,(unsigned long)i2cErrors,(unsigned long)mismatches,(unsigned long)recoveries,(unsigned long)logDrops,
    digitalRead(SDA_PIN),digitalRead(SCL_PIN),boards[0].online?"true":"false",boards[0].mode1,boards[0].mode2,boards[1].online?"true":"false",boards[1].mode1,boards[1].mode2);
}

void serialCommands() {
  static char input[48]; static size_t used=0; static bool overflow=false;
  for(int i=0;i<64 && Serial.available();++i) {
    char c=Serial.read(); if(c=='\r') continue;
    if(c=='\n') {
      input[used]=0;
      if(!overflow && !strcmp(input,"STATUS")) status();
      else if(!overflow && !strcmp(input,"RECOVER")) {
        ++recoveries; known=verified=0;
        for(auto &b:boards) b.online=false;
        if(recoverBus()) for(uint8_t b=0;b<2;++b) initializeBoard(b);
        takeRadios(); maintainOutputs(); status();
      } else if(!overflow && (!strcmp(input,"TEST_SLEEP 64") || !strcmp(input,"TEST_SLEEP 65"))) {
        // Maintenance fault injection, for exercising brownout/reset recovery.
        uint8_t b=input[12]=='4'?0:1, sleep=0x10;
        writeBytes(b,0,&sleep,1);
        logLine("TEST SLEEP addr=0x%02X",boards[b].address);
      } else logLine("ERR command");
      used=0; overflow=false;
    } else if(used<sizeof(input)-1) input[used++]=c; else overflow=true;
  }
}

void setup() {
  Serial.setTxBufferSize(4096); Serial.begin(115200); Serial.setTxTimeoutMs(0);
  WiFi.persistent(false); WiFi.setAutoReconnect(false);
  radioReady=WiFi.mode(WIFI_STA) && WiFi.setSleep(false) && esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE)==ESP_OK && esp_now_init()==ESP_OK && esp_now_register_recv_cb(onReceive)==ESP_OK;
  if(recoverBus()) for(uint8_t b=0;b<2;++b) initializeBoard(b);
  logLine("POOL CENTRAL v2 MAC=%s channel=%u",WiFi.macAddress().c_str(),CHANNEL);
}

void loop() {
  takeRadios();
  serialCommands();
  maintainOutputs();
  if(millis()-lastStatus>=1000) { lastStatus=millis(); status(); }
  delay(1);
}
