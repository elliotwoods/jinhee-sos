// NCT NFC pairing bridge. Arduino-ESP32 3.3.11, ArduinoJson 7, Adafruit PN532.
// Only this station is reflashed. The cube wire ABI stays identical to ForKimchi.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>
#include "Pn532Wire.h"
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <stddef.h>
#include <NctZoneProtocol.h>  // zones/firmware/libraries/NctZone

struct Packet {
  uint8_t type;
  uint32_t cubeID;
  uint8_t mac[6];
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t success;
};
static_assert(sizeof(Packet)==24 && offsetof(Packet,type)==0 && offsetof(Packet,cubeID)==4 &&
              offsetof(Packet,mac)==8 && offsetof(Packet,uidLength)==14 &&
              offsetof(Packet,uid)==15 && offsetof(Packet,success)==22, "Cube ABI changed");
struct Received { Packet packet; uint8_t sender[6]; };
struct ZoneReceived { uint8_t sender[6]; uint8_t length; uint8_t data[250]; };
enum Mode { IDLE, IDENTIFY, REGISTERING, ACK_PAUSE };
constexpr uint8_t CHANNEL=2, DISCOVER=1, DISCOVER_REPLY=2, REGISTER=3, REGISTER_ACK=4, SET_ZONE=6;
constexpr uint32_t HEARTBEAT_TIMEOUT=5000;
uint8_t broadcastMac[6]={255,255,255,255,255,255};
QueueHandle_t rxQueue=nullptr, txQueue=nullptr, zoneQueue=nullptr;
Pn532Wire nfcWire;
Adafruit_PN532 nfc(-1,-1,&nfcWire);
bool radioOK=false, nfcOK=false, active=false;
uint32_t nfcFirmware=0;
uint8_t nfcI2cStatus=255;
bool nfcPolling=false; // Diagnostic startup: enable explicitly after a successful single read.
bool recoverNfcBus();
void pollNfc();
uint32_t nfcPolls=0, nfcFound=0, nfcLastDuration=0, nfcMaxDuration=0;
Mode mode=IDLE;
uint8_t target[6]={};
Packet registration={};
String operationID;
uint32_t lastHost=0, started=0, lastBlink=0, lastAttempt=0, ackTime=0, durationMs=0;
int attempts=0;
bool blue=false, tagPresent=false, scanArmed=false;
uint32_t lastSeen=0, lastNfc=0;
uint8_t lastUid[10]={}, lastUidLength=0;

String hexString(const uint8_t *data, int length) {
  String out;
  for(int i=0;i<length;i++) { char b[4]; snprintf(b,sizeof(b), i ? ":%02X" : "%02X",data[i]); out+=b; }
  return out;
}
void output(JsonDocument &doc) { serializeJson(doc,Serial); Serial.println(); }
void event(const char *name, const String &id="", const char *detail="") {
  JsonDocument d; d["event"]=name; d["id"]=id; if(*detail) d["detail"]=detail; output(d);
}
void error(const String &id, const char *detail) { event("error",id,detail); }
void receiveCallback(const esp_now_recv_info_t *info,const uint8_t *data,int len) {
  if(nctzone::frameType(data,len)) {
    if(!zoneQueue) return;
    ZoneReceived z; memcpy(z.sender,info->src_addr,6); z.length=len; memcpy(z.data,data,len);
    xQueueSend(zoneQueue,&z,0); return;
  }
  if(len!=sizeof(Packet) || (data[0]!=DISCOVER_REPLY && data[0]!=REGISTER_ACK)) return;
  Received r; memcpy(&r.packet,data,sizeof(Packet)); memcpy(r.sender,info->src_addr,6);
  xQueueSend(rxQueue,&r,0);
}
void sendCallback(const esp_now_send_info_t *,esp_now_send_status_t status) { xQueueSend(txQueue,&status,0); }
bool addPeer(const uint8_t *mac) {
  if(esp_now_is_peer_exist(mac)) return true;
  esp_now_peer_info_t p={}; memcpy(p.peer_addr,mac,6); p.channel=CHANNEL; p.ifidx=WIFI_IF_STA;
  return esp_now_add_peer(&p)==ESP_OK;
}
bool sendPacket(const uint8_t *mac,const Packet &p) {
  if(!radioOK) return false;
  JsonDocument d; d["event"]="radio"; d["id"]=operationID; d["mac"]=hexString(mac,6); d["type"]=p.type;
  if(!addPeer(mac)) { d["status"]="peer_error"; output(d); return false; }
  esp_err_t err=esp_now_send(mac,reinterpret_cast<const uint8_t*>(&p),sizeof(p));
  if(err!=ESP_OK) { d["status"]="rejected"; d["detail"]=esp_err_to_name(err); output(d); return false; }
  esp_now_send_status_t status;
  if(xQueueReceive(txQueue,&status,pdMS_TO_TICKS(500))!=pdTRUE) {
    radioOK=false; event("fatal",operationID,"Radio completion timeout; reboot station"); return false;
  }
  d["status"]=status==ESP_NOW_SEND_SUCCESS ? "delivered" : "unconfirmed";
  output(d);
  return true; // Queue acceptance/radio result is distinct from a cube application ACK.
}
// Zone-management frames are built by the host (zones/tools/zonedb.py); the station only validates and relays.
bool sendZoneFrame(const String &id,const uint8_t *mac,const uint8_t *data,size_t length) {
  JsonDocument d; d["event"]="zone_sent"; d["id"]=id; d["mac"]=hexString(mac,6); d["kind"]=data[3];
  bool temporary=!(mac[0]&1) && !esp_now_is_peer_exist(mac);
  if(!addPeer(mac)) { d["status"]="peer_error"; output(d); return false; }
  esp_err_t err=esp_now_send(mac,data,length);
  bool ok=err==ESP_OK;
  if(!ok) { d["status"]="rejected"; d["detail"]=esp_err_to_name(err); }
  else {
    esp_now_send_status_t status;
    if(xQueueReceive(txQueue,&status,pdMS_TO_TICKS(500))!=pdTRUE) {
      radioOK=false; event("fatal",id,"Radio completion timeout; reboot station"); ok=false;
    } else d["status"]=status==ESP_NOW_SEND_SUCCESS ? "delivered" : "unconfirmed";
  }
  if(temporary && esp_now_is_peer_exist(mac)) esp_now_del_peer(mac);
  if(radioOK) output(d);
  return ok;
}
String plainHex(const uint8_t *data,int length) {
  String out;
  for(int i=0;i<length;i++) { char b[3]; snprintf(b,sizeof(b),"%02X",data[i]); out+=b; }
  return out;
}
int parsePlainHex(const char *s,uint8_t *out,int capacity) {
  int length=s ? strlen(s) : 0;
  if(!length || length%2 || length/2>capacity) return -1;
  for(int i=0;i<length/2;i++) {
    if(!isxdigit(s[2*i]) || !isxdigit(s[2*i+1])) return -1;
    char b[]={s[2*i],s[2*i+1],0}; out[i]=strtoul(b,nullptr,16);
  }
  return length/2;
}
void zone(uint8_t value) { Packet p={}; p.type=SET_ZONE; p.success=value; sendPacket(target,p); }
void releaseTarget() {
  if(active) {
    zone(0);
    if(radioOK && esp_now_is_peer_exist(target)) esp_now_del_peer(target);
  }
  active=false; mode=IDLE; scanArmed=false;
}
void hello(const String &id) {
  JsonDocument d; d["event"]="hello"; d["id"]=id; d["protocol"]=1;
  d["firmware"]="nct-pairing-1.6-zones"; d["zones"]=nctzone::PROTO; d["mac"]=WiFi.macAddress(); d["channel"]=WiFi.channel();
  d["radio_ok"]=radioOK; d["nfc_ok"]=nfcOK;
  d["nfc_polling"]=nfcPolling; d["nfc_firmware"]=nfcFirmware; d["nfc_i2c_status"]=nfcI2cStatus; d["tag_present"]=tagPresent; output(d);
}
int parseHex(const char *s,uint8_t *out,int capacity) {
  if(!s) return -1;
  int length=strlen(s);
  if(!length || (length+1)%3 || (length+1)/3>capacity) return -1;
  int n=(length+1)/3;
  for(int i=0;i<n;i++) {
    if(!isxdigit(s[i*3]) || !isxdigit(s[i*3+1]) || (i<n-1 && s[i*3+2]!=':')) return -1;
    char b[]={s[i*3],s[i*3+1],0}; out[i]=strtoul(b,nullptr,16);
  }
  return n;
}
void attemptRegistration() {
  attempts++;
  JsonDocument d; d["event"]="attempt"; d["id"]=operationID; d["attempt"]=attempts;
  d["mac"]=hexString(target,6); output(d);
  sendPacket(target,registration); lastAttempt=millis();
}
void registrationResult(bool acknowledged) {
  JsonDocument d; d["event"]="registered"; d["id"]=operationID;
  d["mac"]=hexString(target,6); d["cube_id"]=registration.cubeID; d["acknowledged"]=acknowledged;
  d["detail"]=acknowledged ? "Cube acknowledged; flash persistence not verified" : "No matching acknowledgment after three attempts";
  releaseTarget(); // Restore static before the host can start the next operation.
  output(d);
}
void command(char *line) {
  JsonDocument d;
  if(deserializeJson(d,line)) { error("","Invalid JSON"); return; }
  String id=d["id"] | "";
  const char *cmd=d["cmd"] | "";
  if(id.length()>40 || id.length()==0) { error("","Missing/invalid request id"); return; }
  if(!strcmp(cmd,"ping")) { lastHost=millis(); event("pong",id); return; }
  if(!strcmp(cmd,"hello")) { releaseTarget(); operationID=""; lastHost=millis(); hello(id); return; }
  if(!strcmp(cmd,"nfc_recover")) {
    if(mode!=IDLE) { error(id,"Stop before reader recovery"); return; }
    nfcPolling=false; nfcOK=false;
    bool clear=recoverNfcBus(); nfcWire.begin(4,3); nfcWire.setClock(100000); nfcWire.setTimeOut(250);
    if(clear) {
      nfc.begin(); nfcFirmware=nfc.getFirmwareVersion();
      nfcOK=nfcFirmware && nfc.SAMConfig();
    }
    nfcI2cStatus=nfcOK ? 0 : 5;
    JsonDocument result; result["event"]="nfc_recovered"; result["id"]=id;
    result["bus_clear"]=clear; result["ready"]=nfcOK; result["firmware"]=nfcFirmware;
    result["i2c_status"]=nfcI2cStatus; output(result); return;
  }
  if(!strcmp(cmd,"nfc_poll")) {
    if(mode!=IDLE) { error(id,"Stop before reader diagnostics"); return; }
    nfcPolling=d["enabled"] | false;
    if(d["once"] | false) { nfcPolling=true; lastNfc=millis()-100; pollNfc(); nfcPolling=false; }
    JsonDocument result; result["event"]="nfc_poll_result"; result["id"]=id;
    result["ready"]=nfcOK; result["enabled"]=nfcPolling; result["polls"]=nfcPolls; result["found"]=nfcFound;
    result["duration_ms"]=nfcLastDuration; result["tag_present"]=tagPresent;
    if(lastUidLength) result["uid"]=hexString(lastUid,lastUidLength);
    output(result); return;
  }
  if(!strcmp(cmd,"nfc_status")) {
    if(mode!=IDLE) { error(id,"Stop the current operation before reader diagnostics"); return; }
    JsonDocument status; status["event"]="nfc_status"; status["id"]=id;
    status["sda"]=digitalRead(4); status["scl"]=digitalRead(3);
    uint32_t currentFirmware=nfc.getFirmwareVersion();
    status["i2c_status"]=currentFirmware ? 0 : 5;
    status["status_source"]="firmware_response";
    status["firmware_now"]=currentFirmware;
    status["nfc_polling"]=nfcPolling; status["polls"]=nfcPolls; status["found"]=nfcFound;
    status["last_poll_ms"]=nfcLastDuration; status["max_poll_ms"]=nfcMaxDuration;
    output(status); return;
  }
  if(!strcmp(cmd,"stop")) { releaseTarget(); operationID=""; event("stopped",id); return; }
  if(!radioOK) { error(id,"Radio unavailable; reboot station"); return; }
  if(uint32_t(millis()-lastHost)>HEARTBEAT_TIMEOUT) { error(id,"Send hello/ping before operating"); return; }
  if(!strcmp(cmd,"discover")) {
    if(mode==REGISTERING || mode==ACK_PAUSE) { error(id,"Registration is active"); return; }
    Packet p={}; p.type=DISCOVER; sendPacket(broadcastMac,p); event("discover_sent",id); return;
  }
  if(!strcmp(cmd,"zone_send")) {
    uint8_t zoneMac[6], frame[250];
    int length=parsePlainHex(d["hex"] | "",frame,sizeof(frame));
    uint8_t kind=length>0 ? nctzone::frameType(frame,length) : 0;
    bool broadcast=parseHex(d["mac"] | "",zoneMac,6)==6 && !memcmp(zoneMac,broadcastMac,6);
    if(parseHex(d["mac"] | "",zoneMac,6)!=6 || ((zoneMac[0]&1) && !broadcast)) { error(id,"Invalid zone MAC"); return; }
    if(kind!=nctzone::DB_ANNOUNCE && kind!=nctzone::DB_CHUNK && kind!=nctzone::ZONE_QUERY &&
       kind!=nctzone::ZONE_IDENTIFY && kind!=nctzone::ZONE_REBOOT) { error(id,"Invalid zone frame"); return; }
    if(broadcast && (kind==nctzone::ZONE_IDENTIFY || kind==nctzone::ZONE_REBOOT)) {
      error(id,"Identify/reboot must target one zone"); return;
    }
    sendZoneFrame(id,zoneMac,frame,length); return;
  }
  uint8_t mac[6];
  if(parseHex(d["mac"] | "",mac,6)!=6 || (mac[0]&1)) { error(id,"Invalid unicast MAC"); return; }
  if(!strcmp(cmd,"identify")) {
    if(mode!=IDLE) { error(id,"Station busy; stop first"); return; }
    if(!d["duration_ms"].is<uint32_t>()) { error(id,"Invalid duration"); return; }
    durationMs=d["duration_ms"].as<uint32_t>();
    if(durationMs>60000) { error(id,"Duration exceeds 60 seconds"); return; }
    memcpy(target,mac,6); active=true; operationID=id; mode=IDENTIFY;
    started=lastBlink=lastSeen=millis(); blue=false;
    // Force a clear-reader interval AFTER selecting this target. Old tags cannot carry over.
    scanArmed=false; tagPresent=true; lastUidLength=0;
    JsonDocument state; state["event"]="tag_state"; state["present"]=true; output(state);
    zone(1); event("identifying",id); return;
  }
  if(!strcmp(cmd,"register")) {
    if(mode==REGISTERING || mode==ACK_PAUSE || (active && memcmp(target,mac,6))) {
      error(id,"Station busy with another operation"); return;
    }
    Packet p={};
    int len=parseHex(d["uid"] | "",p.uid,7);
    if((len!=4 && len!=7) || !d["cube_id"].is<uint32_t>() || d["cube_id"].as<uint32_t>()==0) {
      error(id,"Invalid cube ID or UID (only 4/7-byte tags supported)"); return;
    }
    p.type=REGISTER; p.cubeID=d["cube_id"].as<uint32_t>(); p.uidLength=len;
    memcpy(target,mac,6); active=true; operationID=id; registration=p; mode=REGISTERING;
    scanArmed=false; attempts=0; xQueueReset(rxQueue); attemptRegistration(); return;
  }
  error(id,"Unknown command");
}
void pollRadio() {
  ZoneReceived z;
  for(int count=0;count<16 && zoneQueue && xQueueReceive(zoneQueue,&z,0)==pdTRUE;count++) {
    uint8_t kind=nctzone::frameType(z.data,z.length);
    if(kind!=nctzone::ZONE_STATUS && kind!=nctzone::ZONE_LOG) continue;  // other registries' traffic
    JsonDocument d; d["event"]="zone_frame"; d["mac"]=hexString(z.sender,6); d["kind"]=kind;
    d["hex"]=plainHex(z.data,z.length); output(d);
  }
  Received r;
  for(int count=0;count<64 && xQueueReceive(rxQueue,&r,0)==pdTRUE;count++) {
    if(memcmp(r.sender,r.packet.mac,6)) continue;
    if(r.packet.type==DISCOVER_REPLY) {
      JsonDocument d; d["event"]="device"; d["mac"]=hexString(r.sender,6); output(d);
    } else if(mode==REGISTERING && r.packet.type==REGISTER_ACK && r.packet.success==1 &&
              r.packet.cubeID==registration.cubeID && !memcmp(r.sender,target,6)) {
      mode=ACK_PAUSE; ackTime=millis();
      event("ack_received",operationID,"Allowing cube confirmation blink to finish");
    }
  }
}
void pollNfc() {
  if(!nfcPolling || !nfcOK || uint32_t(millis()-lastNfc)<50) return;
  lastNfc=millis();
  uint8_t uid[10]={}, length=0;
  uint32_t readStarted=millis(); nfcPolls++;
  bool found=nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A,uid,&length,80);
  uint32_t now=millis();
  nfcLastDuration=now-readStarted; if(nfcLastDuration>nfcMaxDuration) nfcMaxDuration=nfcLastDuration;
  if(found) {
    nfcFound++;
    lastSeen=now;
    bool changed=!tagPresent || length!=lastUidLength || (length<=10 && memcmp(uid,lastUid,length));
    tagPresent=true;
    JsonDocument d;
    if(changed) {
      d["event"]="tag_state"; d["present"]=true; output(d);
      if((length==4 || length==7) && mode==IDENTIFY && scanArmed) {
        d.clear(); d["event"]="tag"; d["id"]=operationID; d["uid"]=hexString(uid,length); output(d);
      } else if(length!=4 && length!=7) event("nfc_error","","Unsupported UID length; remove this tag");
    }
    scanArmed=false;
    lastUidLength=length;
    if(length<=10) memcpy(lastUid,uid,length);
  } else if(uint32_t(now-lastSeen)>700 && (tagPresent || (mode==IDENTIFY && !scanArmed))) {
    tagPresent=false; scanArmed=(mode==IDENTIFY);
    JsonDocument d; d["event"]="tag_state"; d["present"]=false; output(d);
  }
}
// NXP UM10204 bus clear: release SDA, pulse SCL up to nine times, then STOP.
// Open-drain outputs never drive either line high against a peripheral.
bool recoverNfcBus() {
  nfcWire.end();
  pinMode(4,INPUT_PULLUP); pinMode(3,INPUT_PULLUP); delay(10);
  JsonDocument d; d["event"]="nfc_bus";
  d["sda_before"]=digitalRead(4); d["scl_before"]=digitalRead(3);
  int pulses=0;
  if(digitalRead(3)==HIGH && digitalRead(4)==LOW) {
    digitalWrite(3,HIGH); pinMode(3,OUTPUT_OPEN_DRAIN);
    for(int i=0;i<9;i++) {
      digitalWrite(3,LOW); delayMicroseconds(10);
      digitalWrite(3,HIGH); delayMicroseconds(10);
      for(int wait=0;wait<100 && digitalRead(3)==LOW;wait++) delayMicroseconds(20);
      pulses++;
      if(digitalRead(3)==LOW) break;
    }
    if(digitalRead(3)==HIGH) {
      digitalWrite(3,LOW);
      digitalWrite(4,LOW); pinMode(4,OUTPUT_OPEN_DRAIN); delayMicroseconds(10);
      digitalWrite(3,HIGH); delayMicroseconds(10);
      digitalWrite(4,HIGH); delayMicroseconds(10);
    }
    pinMode(3,INPUT_PULLUP); pinMode(4,INPUT_PULLUP); delay(10);
  }
  bool clear=digitalRead(3)==HIGH && digitalRead(4)==HIGH;
  d["sda_after"]=digitalRead(4); d["scl_after"]=digitalRead(3); d["pulses"]=pulses; output(d);
  return clear;
}
void setup() {
  // Zone chunk lines are ~520 chars; the host also paces relays one line at a time.
  Serial.setRxBufferSize(4096); Serial.begin(115200); delay(800);
  rxQueue=xQueueCreate(64,sizeof(Received)); txQueue=xQueueCreate(1,sizeof(esp_now_send_status_t));
  zoneQueue=xQueueCreate(32,sizeof(ZoneReceived));
  WiFi.persistent(false); WiFi.setAutoReconnect(false);
  bool wifi=WiFi.mode(WIFI_STA) && WiFi.disconnect(); delay(100);
  radioOK=wifi && rxQueue && txQueue && zoneQueue && WiFi.setSleep(false) &&
      esp_wifi_set_channel(CHANNEL,WIFI_SECOND_CHAN_NONE)==ESP_OK && esp_now_init()==ESP_OK &&
      esp_now_register_recv_cb(receiveCallback)==ESP_OK && esp_now_register_send_cb(sendCallback)==ESP_OK;
  if(radioOK) radioOK=addPeer(broadcastMac);
  bool busClear=recoverNfcBus();
  nfcWire.begin(4,3); nfcWire.setClock(100000); nfcWire.setTimeOut(250); delay(1200);
  if(!busClear) { nfcI2cStatus=5; event("nfc_error","","I2C line held low after recovery; check reader power/mode and power-cycle it"); }
  for(int i=0;i<3 && !nfcOK && busClear;i++) {
    nfc.begin(); delay(200);
    nfcFirmware=nfc.getFirmwareVersion();
    nfcI2cStatus=nfcFirmware ? 0 : 5;
    if(nfcFirmware) { nfcOK=nfc.SAMConfig(); }
    JsonDocument d; d["event"]="nfc_init"; d["attempt"]=i+1; d["i2c_status"]=nfcI2cStatus;
    d["firmware"]=nfcFirmware; d["ready"]=nfcOK; output(d);
    if(!nfcOK) delay(400);
  }
  hello("");
}
void loop() {
  static char line[1024]; static size_t used=0; static bool overflow=false;  // zone chunks are ~540 chars
  for(int count=0;count<4096 && Serial.available();count++) {
    char c=Serial.read();
    if(c=='\n') {
      if(overflow) error("","Serial command too long");
      else { line[used]=0; if(used) command(line); }
      used=0; overflow=false;
    } else if(c!='\r' && !overflow) {
      if(used<sizeof(line)-1) line[used++]=c; else overflow=true;
    }
  }
  if(active && uint32_t(millis()-lastHost)>HEARTBEAT_TIMEOUT) {
    releaseTarget(); event("watchdog",operationID,"Application heartbeat lost; attempted idle"); operationID="";
  }
  if(rxQueue) pollRadio();
  if(radioOK && mode==REGISTERING && uint32_t(millis()-lastAttempt)>=2000) {
    if(attempts<3) attemptRegistration(); else registrationResult(false);
  } else if(radioOK && mode==ACK_PAUSE && uint32_t(millis()-ackTime)>=1000) {
    registrationResult(true);
  } else if(radioOK && mode==IDENTIFY) {
    if(durationMs && uint32_t(millis()-started)>=durationMs) {
      String id=operationID; releaseTarget(); event("flash_done",id);
    } else if(uint32_t(millis()-lastBlink)>=500) {
      blue=!blue; zone(blue ? 3 : 1); lastBlink=millis();
    }
  }
  pollNfc();
  delay(2);
}
