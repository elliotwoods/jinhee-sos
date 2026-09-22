#!/usr/bin/env python3
"""Host simulation of the real sketch: no hardware, radio, or third-party packages."""
import pathlib, re, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'scripts'))
import host_cxx
source = (ROOT.parent / 'mainshow_enter/mainshow_enter.ino').read_text(encoding='utf-8')
table = (ROOT / 'CubeTable.h').read_text(encoding='utf-8')
rows = lambda s: re.findall(r'\{\d+,7,\{[^}]+\},\{[^}]+\}\}', s)
assert rows(source) == rows(table) and len(rows(table)) == 32
# Confirm the wire declaration remains identical to the receiver, ignoring whitespace.
packet = lambda s: re.sub(r'\s+', '', re.search(r'struct Packet\s*\{(.*?)\};', s, re.S)[1])
assert packet((ROOT / 'registration_console.ino').read_text(encoding='utf-8')) == packet((ROOT.parent / 'ForKimchi.ino').read_text(encoding='utf-8'))
stub = r'''
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
struct SerialT {
 void begin(int) {} int available() { return 0; } char read() { return 0; }
 template<class T> void print(T) {} template<class T> void println(T) {}
 void println() {} template<class... A> void printf(const char*, A...) {}
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
struct esp_now_recv_info_t { const uint8_t* src_addr; };
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
 assert(peers.size()==1); return 0;
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
'''
tests = r'''
void cmd(const char* s) { char b[64]; strcpy(b,s); command(b); }
void ack(int index, uint32_t id, uint8_t success=1, int length=24) {
 Packet p={}; p.type=MSG_REGISTER_ACK; p.cubeID=id; p.success=success;
 memcpy(p.mac,cubeTable[index].mac,6);
 esp_now_recv_info_t info{cubeTable[index].mac};
 onReceive(&info,(uint8_t*)&p,length);
}
int main() {
 setup(); assert(radioReady && mode==NONE && packets.empty() && validTable());
 cmd("register 0"); assert(mode==NONE);
 cmd("register 1 extra"); assert(mode==NONE);
 cmd("register 1"); tick(); assert(mode==REGISTER && attempts==1);
 Packet sent; memcpy(&sent,packets.back().data(),24);
 assert(sent.type==3 && sent.cubeID==1 && sent.uidLength==7);
 assert(!memcmp(sent.uid,cubeTable[0].uid,7));
 ack(1,1); ack(0,2); ack(0,1,0); ack(0,1,1,23); tick(); assert(phase==WAIT_ACK);
 ack(0,1); tick(); assert(phase==PAUSE && results[0]==1);
 ack(0,1); now+=999; tick(); assert(mode==REGISTER);
 now+=1; tick(); assert(mode==NONE && peers.empty());
 packets.clear(); delivery=ESP_NOW_SEND_FAIL;
 cmd("register 2"); tick();
 for(int i=0;i<3;i++) { now+=2000; tick(); }
 assert(mode==NONE && packets.size()==3 && results[1]==2 && peers.empty());
 delivery=ESP_NOW_SEND_SUCCESS;
 cmd("test 3"); tick(); assert(phase==LIGHT_ON && mode==TEST);
 cmd("register all"); assert(mode==TEST); // busy protection
 now+=2000; tick(); assert(mode==NONE && peers.empty());
 memcpy(&sent,packets.back().data(),24); assert(sent.type==6 && sent.success==0);
 cmd("test all"); tick(); cmd("stop"); assert(mode==NONE && peers.empty());
 memcpy(&sent,packets.back().data(),24); assert(sent.success==0);
 packets.clear(); cmd("register all");
 for(int i=0;i<CUBE_COUNT;i++) {
  tick(); assert(current==i);
  assert(!memcmp(destinations.back().data(),cubeTable[i].mac,6));
  if(i==4) { for(int j=0;j<3;j++){now+=2000;tick();} }
  else { ack(i,cubeTable[i].cubeID);tick(); now+=1000;tick(); }
 }
 assert(mode==NONE && peers.empty() && results[4]==2 && results[31]==1);
 cmd("test 1"); now=UINT32_MAX-1000; tick(); now+=2000; tick(); assert(mode==NONE);
 failSend=true; cmd("register 1"); tick();
 for(int i=0;i<3;i++){now+=2000;tick();}
 assert(mode==NONE && results[0]==2); failSend=false;
 callbacks=false; cmd("register 1"); tick(); tick();
 assert(!radioReady && mode==NONE); cmd("test all"); assert(mode==NONE);
 puts("PASS: mapping/ABI, ACK validation, retries, offline continuation, peer cleanup, test/stop, busy/invalid commands, timer rollover, radio faults");
}
'''
with tempfile.TemporaryDirectory(prefix='nct-tests-') as d:
    d=pathlib.Path(d)
    (d/'stub.h').write_text(stub,encoding='utf-8')
    for name in ['WiFi.h','esp_now.h','esp_wifi.h','freertos/FreeRTOS.h','freertos/queue.h']:
        p=d/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('#include "stub.h"\n',encoding='utf-8')
    (d/'test.cpp').write_text('#include "'+(ROOT/'registration_console.ino').as_posix()+'"\n'+tests,encoding='utf-8')
    binary=host_cxx.executable(d/'test')
    subprocess.run([host_cxx.compiler(),'-std=c++17','-I'+str(d),str(d/'test.cpp'),'-o',binary],check=True)
    subprocess.run([binary],check=True)
