#include "../firmware/pairing_station/pairing_station.ino"
void cmd(const char* text) { char b[1024]; strcpy(b,text); command(b); }
void advance(uint32_t ms) { now+=ms; loop(); }
void ack(uint32_t id, const uint8_t *mac, uint8_t success=1, int length=24) {
 Packet p={}; p.type=REGISTER_ACK;p.cubeID=id;p.success=success;memcpy(p.mac,mac,6);
 esp_now_recv_info_t info{mac};receiveCallback(&info,(uint8_t*)&p,length);
}
int main() {
 setup();nfcPolling=true;assert(radioOK && nfcOK && mode==IDLE && packets.empty());
 cmd("{\"cmd\":\"hello\",\"id\":\"hello\"}");
 cmd("{\"cmd\":\"discover\",\"id\":\"d\"}");
 assert(packets.back()[0]==DISCOVER && destinations.back()[0]==255);
 cmd("{\"cmd\":\"identify\",\"id\":\"a\",\"mac\":\"02:00:00:00:00:01\",\"duration_ms\":0}");
 assert(mode==IDENTIFY && !scanArmed);
 // A tag already on the reader must not become a pairing scan.
 presentedTag={4,1,2,3};serialOutput.clear();advance(100);
 assert(serialOutput.find("\"event\":\"tag\"")==std::string::npos);
 presentedTag.clear();advance(701);assert(scanArmed);
 presentedTag={4,1,2,3};serialOutput.clear();advance(100);
 assert(serialOutput.find("\"event\":\"tag\"")!=std::string::npos);
 assert(serialOutput.find("\"id\":\"a\"")!=std::string::npos);
 serialOutput.clear();advance(100);
 assert(serialOutput.find("\"event\":\"tag\"")==std::string::npos);
 cmd("{\"cmd\":\"register\",\"id\":\"r\",\"mac\":\"02:00:00:00:00:01\",\"cube_id\":33,\"uid\":\"04:01:02:03\"}");
 assert(mode==REGISTERING && attempts==1);
 uint8_t other[6]={2,0,0,0,0,2};
 ack(33,other);ack(34,target);ack(33,target,0);ack(33,target,1,23);pollRadio();
 assert(mode==REGISTERING);
 ack(33,target);pollRadio();assert(mode==ACK_PAUSE);
 advance(1000);assert(mode==IDLE && peers.size()==1); // only broadcast remains
 assert(serialOutput.find("\"acknowledged\":true")!=std::string::npos);
 // Offline registration retries are bounded; host keeps heartbeat alive.
 cmd("{\"cmd\":\"register\",\"id\":\"offline\",\"mac\":\"02:00:00:00:00:02\",\"cube_id\":34,\"uid\":\"04:02:03:04\"}");
 for(int i=0;i<3;i++) {cmd("{\"cmd\":\"ping\",\"id\":\"p\"}");advance(2000);}
 assert(mode==IDLE && attempts==3 && peers.size()==1);
 assert(serialOutput.find("\"acknowledged\":false")!=std::string::npos);
 cmd("{\"cmd\":\"identify\",\"id\":\"flash\",\"mac\":\"02:00:00:00:00:01\",\"duration_ms\":2000}");
 advance(500);Packet packet;memcpy(&packet,packets.back().data(),24);assert(packet.success==3);
 advance(1500);assert(mode==IDLE);memcpy(&packet,packets.back().data(),24);assert(packet.success==0);
 cmd("{\"cmd\":\"ping\",\"id\":\"p\"}");
 cmd("{\"cmd\":\"identify\",\"id\":\"watch\",\"mac\":\"02:00:00:00:00:01\",\"duration_ms\":0}");
 advance(5001);assert(mode==IDLE && peers.size()==1);
 assert(serialOutput.find("\"event\":\"watchdog\"")!=std::string::npos);
 cmd("{\"cmd\":\"hello\",\"id\":\"h\"}");
 cmd("{\"cmd\":\"identify\",\"id\":\"restart\",\"mac\":\"02:00:00:00:00:01\",\"duration_ms\":0}");
 cmd("{\"cmd\":\"hello\",\"id\":\"h\"}");assert(mode==IDLE);
 // Reject invalid registration instead of silently truncating the tag.
 cmd("{\"cmd\":\"register\",\"id\":\"bad\",\"mac\":\"02:00:00:00:00:01\",\"cube_id\":33,\"uid\":\"04:01:02\"}");assert(mode==IDLE);
 // Invalid inputs must never emit radio packets or activate a target.
 size_t sentBefore=packets.size();
 cmd("{\"cmd\":\"identify\",\"id\":\"badmac\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"duration_ms\":0}");
 cmd("{\"cmd\":\"identify\",\"id\":\"long\",\"mac\":\"02:00:00:00:00:01\",\"duration_ms\":60001}");
 cmd("{\"cmd\":\"register\",\"id\":\"zero\",\"mac\":\"02:00:00:00:00:01\",\"cube_id\":0,\"uid\":\"04:01:02:03\"}");
 assert(mode==IDLE && packets.size()==sentBefore);
 // Spoofed discovery payload MAC must not be surfaced to the host.
 Packet spoof={};spoof.type=DISCOVER_REPLY;memcpy(spoof.mac,other,6);
 esp_now_recv_info_t info{target};serialOutput.clear();
 receiveCallback(&info,(uint8_t*)&spoof,sizeof(spoof));pollRadio();
 assert(serialOutput.find("\"event\":\"device\"")==std::string::npos);
 // A late registration ACK after stopping cannot resume registration.
 cmd("{\"cmd\":\"register\",\"id\":\"late\",\"mac\":\"02:00:00:00:00:01\",\"cube_id\":33,\"uid\":\"04:01:02:03\"}");
 cmd("{\"cmd\":\"stop\",\"id\":\"stoplate\"}");
 serialOutput.clear();ack(33,target);pollRadio();
 assert(mode==IDLE && serialOutput.find("\"event\":\"registered\"")==std::string::npos);
 levels[4]=LOW;assert(recoverNfcBus());
 levels[3]=LOW;assert(!recoverNfcBus());

 // Zone registry relay: only valid zone frames are sent; identify/reboot never broadcast.
 cmd("{\"cmd\":\"hello\",\"id\":\"zh\"}");
 size_t zoneBefore=packets.size();serialOutput.clear();
 cmd("{\"cmd\":\"zone_send\",\"id\":\"q\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"4E5A01200700000001\"}");
 assert(packets.size()==zoneBefore+1 && packets.back().size()==9 && destinations.back()[0]==255);
 assert(serialOutput.find("\"event\":\"zone_sent\"")!=std::string::npos && serialOutput.find("\"status\":\"delivered\"")!=std::string::npos);
 cmd("{\"cmd\":\"zone_send\",\"id\":\"ident\",\"mac\":\"02:00:00:00:00:09\",\"hex\":\"4E5A01230A\"}");
 assert(packets.size()==zoneBefore+2 && packets.back().size()==5 && destinations.back()[5]==9 && peers.size()==1);
 serialOutput.clear();
 cmd("{\"cmd\":\"zone_send\",\"id\":\"b1\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"4E5A01230A\"}");
 cmd("{\"cmd\":\"zone_send\",\"id\":\"b2\",\"mac\":\"02:00:00:00:00:09\",\"hex\":\"00060000000000000000000000000000000000000000000000\"}");
 cmd("{\"cmd\":\"zone_send\",\"id\":\"b3\",\"mac\":\"02:00:00:00:00:09\",\"hex\":\"4E5A0120070000000\"}");
 cmd("{\"cmd\":\"zone_send\",\"id\":\"b4\",\"mac\":\"03:00:00:00:00:09\",\"hex\":\"4E5A01200700000001\"}");
 assert(packets.size()==zoneBefore+2);
 assert(serialOutput.find("Identify/reboot/set-config must target one zone")!=std::string::npos);
 assert(serialOutput.find("Invalid zone frame")!=std::string::npos && serialOutput.find("Invalid zone MAC")!=std::string::npos);
 // Set config (RX gain, 1.8): unicast only.
 serialOutput.clear();
 cmd("{\"cmd\":\"zone_send\",\"id\":\"sc\",\"mac\":\"02:00:00:00:00:09\",\"hex\":\"4E5A01255343464726\"}");
 assert(packets.size()==zoneBefore+3 && packets.back().size()==9 && destinations.back()[5]==9);
 cmd("{\"cmd\":\"zone_send\",\"id\":\"scb\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"4E5A01255343464726\"}");
 assert(packets.size()==zoneBefore+3 && serialOutput.find("must target one zone")!=std::string::npos);
 // Received zone status frames are relayed as hex; cube-sized frames never enter the zone path.
 { uint8_t status[80]={'N','Z',1,0x21}; uint8_t zmac[6]={2,0,0,0,0,9}; esp_now_recv_info_t zi{zmac};
   serialOutput.clear(); receiveCallback(&zi,status,sizeof(status)); pollRadio();
   assert(serialOutput.find("\"event\":\"zone_frame\"")!=std::string::npos && serialOutput.find("4E5A0121")!=std::string::npos);
   assert(serialOutput.find("\"rssi\"")==std::string::npos);  // no rx_ctrl: no signal reported
   wifi_pkt_rx_ctrl_t rx{}; rx.rssi=-71; esp_now_recv_info_t zr{zmac,nullptr,&rx};
   serialOutput.clear(); receiveCallback(&zr,status,sizeof(status)); pollRadio();
   assert(serialOutput.find("\"rssi\":-71")!=std::string::npos);  // signal strength for the zone manager
   uint8_t settings[11]={'N','Z',1,0x26}; serialOutput.clear(); receiveCallback(&zi,settings,sizeof(settings)); pollRadio();
   assert(serialOutput.find("\"event\":\"zone_frame\"")!=std::string::npos && serialOutput.find("4E5A0126")!=std::string::npos);
   uint8_t query[9]={'N','Z',1,0x20}; serialOutput.clear(); receiveCallback(&zi,query,sizeof(query)); pollRadio();
   assert(serialOutput.find("zone_frame")==std::string::npos); }
 puts("PASS: zone relay validation,  actual firmware fresh-tag gating, ACK filters, retries, flash timing, heartbeat, reconnect cleanup, UID rejection, peer cleanup");
}
