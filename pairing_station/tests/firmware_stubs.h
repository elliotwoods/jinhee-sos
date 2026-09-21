
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <string>
#include <vector>
#include <deque>
#include <cassert>
using std::size_t;
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(unsigned n) { now += n; }
using String = std::string;
std::string serialOutput;
struct SerialT {
 void setRxBufferSize(int) {} void begin(int) {} int available() { return 0; } char read() { return 0; }
 size_t write(uint8_t c) { serialOutput.push_back(c); return 1; }
 size_t write(const uint8_t* b, size_t n) { serialOutput.append((const char*)b,n); return n; }
 void println() { serialOutput += "\n"; }
} Serial;
struct WifiT {
 void persistent(bool) {} void setAutoReconnect(bool) {}
 bool mode(int) { return true; } bool disconnect() { return true; }
 bool setSleep(bool) { return true; } std::string macAddress() { return "test"; }
 unsigned channel() { return 2; }
} WiFi;
using esp_err_t = int;
constexpr int ESP_OK=0, WIFI_STA=1, WIFI_IF_STA=0, WIFI_SECOND_CHAN_NONE=0;
const char* esp_err_to_name(int) { return "mock error"; }
struct wifi_pkt_rx_ctrl_t { signed rssi:8; };
struct esp_now_recv_info_t { const uint8_t* src_addr; const uint8_t* des_addr=nullptr; wifi_pkt_rx_ctrl_t* rx_ctrl=nullptr; };
struct esp_now_send_info_t {};
enum esp_now_send_status_t { ESP_NOW_SEND_SUCCESS, ESP_NOW_SEND_FAIL };
struct esp_now_peer_info_t { uint8_t peer_addr[6]; int channel, ifidx; bool encrypt; };
struct Q { size_t cap, size; std::deque<std::vector<uint8_t>> values; };
using QueueHandle_t=Q*;
#define pdTRUE 1
#define pdMS_TO_TICKS(x) (x)
QueueHandle_t xQueueCreate(int n, size_t s) { return new Q{size_t(n),s,{}}; }
int xQueueSend(Q* q, const void* p, int) {
 if(q->values.size() == q->cap) return 0;
 q->values.emplace_back((const uint8_t*)p,(const uint8_t*)p+q->size); return 1;
}
int xQueueReceive(Q* q, void* p, int) {
 if(q->values.empty()) return 0;
 memcpy(p,q->values.front().data(),q->size); q->values.pop_front(); return 1;
}
void xQueueReset(Q* q) { q->values.clear(); }
int esp_wifi_set_channel(int,int) { return 0; }
int esp_now_init() { return 0; }
int esp_now_register_recv_cb(void(*)(const esp_now_recv_info_t*,const uint8_t*,int)) { return 0; }
void(*sendCB)(const esp_now_send_info_t*,esp_now_send_status_t);
int esp_now_register_send_cb(decltype(sendCB) f) { sendCB=f; return 0; }
std::vector<std::vector<uint8_t>> peers, packets, destinations;
bool callbacks=true, failSend=false;
esp_now_send_status_t delivery=ESP_NOW_SEND_SUCCESS;
bool esp_now_is_peer_exist(const uint8_t* m) {
 for(auto& p:peers) if(!memcmp(p.data(),m,6)) return true; return false;
}
int esp_now_add_peer(const esp_now_peer_info_t* p) {
 assert(p->channel==2 && !p->encrypt); peers.emplace_back(p->peer_addr,p->peer_addr+6);
 assert(peers.size()<=2); return 0;
}
int esp_now_del_peer(const uint8_t* m) {
 for(auto i=peers.begin();i!=peers.end();++i) if(!memcmp(i->data(),m,6)){peers.erase(i);break;}
 return 0;
}
int esp_now_send(const uint8_t* m,const uint8_t* p,size_t n) {
 if(failSend) return -1;
 packets.emplace_back(p,p+n); destinations.emplace_back(m,m+6);
 if(callbacks) sendCB(nullptr,delivery); return 0;
}

struct WireT { void begin(int,int) {} void setClock(int) {} void setTimeOut(int) {} void end() {}
 void beginTransmission(int) {} uint8_t endTransmission(){return 0;}
 uint8_t requestFrom(uint8_t,uint8_t){return 0;} int read(){return 0;} } Wire;
std::vector<uint8_t> presentedTag;
constexpr int PN532_MIFARE_ISO14443A=0, PN532_COMMAND_GETGENERALSTATUS=4;
struct Adafruit_PN532 {
 Adafruit_PN532(int,int,WireT*) {}
 void begin() {} uint32_t getFirmwareVersion(){return 1;}
 bool SAMConfig(){return true;}
 bool sendCommandCheckAck(uint8_t*,uint8_t,uint16_t){return true;}
 bool setPassiveActivationRetries(uint8_t){return true;}
 bool readPassiveTargetID(int,uint8_t* uid,uint8_t* length,int) {
  *length=presentedTag.size();
  if(!*length) return false;
  memcpy(uid,presentedTag.data(),presentedTag.size());return true;
 }
};

constexpr int HIGH=1, LOW=0, INPUT_PULLUP=1, OUTPUT_OPEN_DRAIN=2;
int levels[5]={1,1,1,1,1};
void pinMode(int,int) {}
int digitalRead(int pin) {return levels[pin];}
void digitalWrite(int pin,int level) {levels[pin]=level;}
void delayMicroseconds(int) {}
