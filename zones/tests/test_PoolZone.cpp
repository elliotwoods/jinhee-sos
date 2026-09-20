// Real sketch: local tracking, control-point calibration, flash and invalid readings.
#include "zone_stubs.h"
#include "../firmware/PoolZone/PoolZone.ino"
#include "sketch_test.h"

static const uint8_t CENTRAL[6] = {0x48, 0xF6, 0xEE, 0x15, 0x8E, 0xE0};

// Latest state frame, wherever it was addressed: unicast to the latched central or the
// periodic broadcast copy.
static PoolState central() {
  for (size_t i=sentFrames.size(); i-- > 0;) {
    const auto &f=sentFrames[i];
    if (poolFrameType(f.data.data(), int(f.data.size()))==POOL_STATE) {
      PoolState packet; memcpy(&packet, f.data.data(), sizeof(packet)); return packet;
    }
  }
  assert(false && "no pool state frame was sent"); return PoolState{};
}

static std::vector<SentFrame> stateFrames(size_t from=0, const uint8_t *dest=nullptr) {
  std::vector<SentFrame> out;
  for (size_t i=from; i<sentFrames.size(); ++i) {
    const auto &f=sentFrames[i];
    if (poolFrameType(f.data.data(), int(f.data.size()))!=POOL_STATE) continue;
    if (dest && memcmp(f.dest.data(), dest, 6)) continue;
    out.push_back(f);
  }
  return out;
}

static void beacon(uint32_t epoch, uint8_t mask, const uint8_t *from=CENTRAL) {
  PoolBeacon b={};
  fillHeader(b.h, POOL_BEACON);
  b.epoch=epoch; b.radioMask=mask; b.channel=ESPNOW_CHANNEL; b.version=POOL_PROTOCOL_VERSION;
  radioFrom(from, (const uint8_t *)&b, sizeof(b), true);
}

int main() {
  image("zdb_a", SLOT_V1); image("zdb_b", {}); image("zcfg", CONFIG_POOL4);
  laserDistance=383;
  setup(); run(300);
  assert(laserOk && calibrationValid() && confirmedPosition==1);
  assert(!plate.tagPresent() && plate.nfcOk);
  assert(!central().active && pinLevels[STRIP_LED_PIN]==LOW);
  float step=(383.f-43.f)/22;
  assert(distanceToMember(383+step*.33f)==1);
  assert(distanceToMember(383+step*.34f)==-1);
  assert(distanceToMember(383-step*.5f)==-1);
  // A full-scale jump settles, then releases member 1 and confirms 12 in one pass.
  laserDistance=213; run(500); assert(confirmedPosition==12);
  // Hysteresis: a held member keeps a wider window (exitFrac) than it needed to enter
  // (enterFrac). 4 mm off a ~15.5 mm pitch used to release; now it holds.
  laserDistance=217; run(400); assert(confirmedPosition==12);
  laserDistance=222; run(400); assert(confirmedPosition==-1);
  laserDistance=213; run(400); assert(confirmedPosition==12);
  // A bad reading marks the sample invalid at once, but the member is held for
  // dropoutMs so one glitch cannot drop the relay. This is the flicker fix.
  laserStatus=4; run(100); assert(!sampleValid && confirmedPosition==12 && outputMember()==0);
  laserStatus=0; run(200); assert(sampleValid && confirmedPosition==12);
  laserStatus=4; run(700); assert(confirmedPosition==-1 && !sampleValid);
  laserStatus=0; run(400); assert(confirmedPosition==12);
  laserDistance=0; run(700); assert(confirmedPosition==-1 && !sampleValid);
  assert(has(serial("CAL GET"), "PoolZoneCalibration"));
  serial("CAL SET 1 nan"); assert(calibration.mm[0]==383);
  serial("CAL SET 24 50"); assert(calibration.mm[0]==383);
  serial("CAL SET 1 380"); assert(calibration.mm[0]==380 && !calibrationSaved);
  serial("CAL ANCHORS 4196353"); assert(calibration.anchors==4196353);
  assert(has(serial("CAL SAVE"),"OK CAL SAVE") && calibrationSaved);
  serial("CAL SET 1 379");
  assert(has(serial("CAL LOAD"),"OK CAL LOAD") && calibration.mm[0]==380);
  setup(); assert(calibrationSaved && calibration.mm[0]==380 && calibration.anchors==4196353);
  serial("CAL SET 2 380");
  assert(has(serial("CAL SAVE"),"ERR CAL SAVE"));
  serial("CAL LOAD"); assert(calibration.mm[1]!=380);
  // Registered NeoCube activates strip, central and the compatible POOL cube command.
  size_t mark=sentFrames.size();
  presentedTag=FIRST_UID; laserDistance=213; run(250);
  assert(confirmedPosition==12 && plate.tagPresent() && pinLevels[STRIP_LED_PIN]==HIGH);
  assert(central().active && central().member==12 && central().uidLength==FIRST_UID.size());
  auto cube=framesTo(FIRST_MAC.data(),mark); assert(cube.size()==1);
  assert(cubePacket(cube[0]).type==MSG_SET_ZONE && cubePacket(cube[0]).success==ZONE_POOL);
  assert(plate.currentCube().cubeID==FIRST_ID && plate.currentDelivery()==1);
  size_t beats=stateFrames().size(); run(1500);
  size_t sent=stateFrames().size()-beats;
  // Roughly one heartbeat per HEARTBEAT_MS plus the periodic broadcast copy, and never a
  // flood: the central must not be asked to absorb more than it needs.
  assert(sent>=8 && sent<=1500/POOL_BROADCAST_COPY_MS+1500/HEARTBEAT_MS+4);
  // Sequence numbers are strictly increasing, and the boot identity is stable.
  uint16_t previous=0; uint32_t bootId=0;
  for (const auto &f : stateFrames(beats)) {
    PoolState p; memcpy(&p, f.data.data(), sizeof(p));
    assert(p.radioId==4 && p.leaseMs==POOL_LEASE_DEFAULT_MS);
    if (previous) assert(int16_t(p.seq-previous)>0);
    if (bootId) assert(p.bootId==bootId);
    previous=p.seq; bootId=p.bootId;
  }
  assert(bootId!=0);
  // A brief sensor glitch must not interrupt a live central broadcast.
  laserStatus=4; run(150); assert(central().active && central().member==12);
  laserStatus=0; run(150); assert(central().active && central().member==12);
  laserDistance=222; run(400); assert(!central().active && central().member==0);
  laserDistance=383; run(600); assert(central().member==1);
  presentedTag.clear(); run(450); assert(plate.tagPresent());
  run(500); assert(!plate.tagPresent() && !central().active && pinLevels[STRIP_LED_PIN]==LOW);
  // Original unknown-tag behavior remains active without addressing an unregistered cube.
  mark=sentFrames.size(); presentedTag=EXTRA_UID; run(250);
  assert(central().active && plate.currentCube().cubeID==0 && framesTo(EXTRA_MAC.data(),mark).empty());
  presentedTag.clear(); run(1000);
  // Explicit host arm, leased keepalives, no-tag UID, disarm and watchdog expiry.
  serial("HOST PING"); assert(!overrideActive());
  serial("HOST ARM"); assert(overrideActive() && central().active && central().uidLength==0);
  for(int i=0;i<8;++i) { run(300); serial("HOST PING"); }
  assert(overrideActive());
  serial("HOST DISARM"); assert(!central().active && !interactionActive());
  serial("HOST ARM"); run(1600); assert(!overrideActive() && !central().active);
  serial("HOST PING"); assert(!overrideActive());
  // Disarming an override never removes a real tag's activation.
  presentedTag=FIRST_UID; run(250); serial("HOST ARM"); serial("HOST DISARM");
  assert(central().active && interactionActive());
  laserDistance=0; run(700); assert(!central().active);
  laserDistance=383; run(500); assert(central().active);
  serial("CAL SET 1 380"); assert(!central().active && calibrationEditing);
  serial("CAL LOAD"); run(250); assert(central().active && !calibrationEditing);
  presentedTag.clear(); run(1000);
  sendDelivered=false; presentedTag=FIRST_UID; run(250); assert(plate.currentDelivery()==-1);
  sendDelivered=true; presentedTag.clear(); run(1000);
  SliderCalibration uneven;
  for (int i=0; i<23; ++i) uneven.mm[i]=20+10*i;
  uneven.mm[1]=40; uneven.mm[2]=60;
  // Use an independently valid irregular ascending calibration.
  for (int i=2; i<23; ++i) uneven.mm[i]=40+30*(i-1);
  assert(uneven.valid());
  assert(uneven.select(33.4f)==2 && uneven.select(33.3f)==-1);
  assert(uneven.select(49.9f)==2 && uneven.select(50.0f)==-1);
  assert(uneven.select(NAN)==-1);
  // ---- Pool link: beacon, latching, unicast, bursts and idle heartbeats ----
  presentedTag.clear(); laserDistance=383; run(1000);
  // With no beacon heard, everything goes out as broadcast.
  size_t mark2=sentFrames.size(); run(600);
  assert(!stateFrames(mark2, BROADCAST).empty());
  assert(stateFrames(mark2, CENTRAL).empty() && !centralFresh());

  // A beacon latches the central as a pinned peer, and state is unicast to it from then on.
  beacon(0xABCD, 0); run(200);
  assert(centralFresh() && esp_now_is_peer_exist(CENTRAL));
  assert(!centralSeesMe && has(serial("HOST STATUS"), "\"central_sees_me\":false"));
  mark2=sentFrames.size(); run(600);
  assert(!stateFrames(mark2, CENTRAL).empty() && "state is unicast once the central is known");
  // A broadcast copy still goes out, so a stale latched address cannot strand the radio.
  assert(!stateFrames(mark2, BROADCAST).empty() && "a periodic broadcast copy is always sent");

  // radioMask tells this radio the central is hearing it; radio id 4 is bit 3.
  beacon(0xABCD, 1<<3); run(200);
  assert(centralSeesMe && has(serial("HOST STATUS"), "\"central_sees_me\":true"));
  assert(has(serial("HOST STATUS"), "\"unicast\":true"));

  // The peer is pinned, so filling the LRU with cube peers cannot evict it.
  for (int i=0;i<8;++i) { uint8_t mac[6]={0x02,0,0,0,0,uint8_t(0x40+i)}; plate.link.ensurePeer(mac); }
  assert(esp_now_is_peer_exist(CENTRAL) && "the central peer is pinned");

  // A changed epoch means the central restarted and lost every lease: re-assert at once
  // rather than waiting for the next slider movement.
  presentedTag=FIRST_UID; laserDistance=213; run(600);
  assert(central().active && central().member==12);
  mark2=sentFrames.size();
  beacon(0x1234, 1<<3);
  run(POOL_BURST_GAP_MS*POOL_BURST_COUNT+30);
  assert(stateFrames(mark2).size()>=POOL_BURST_COUNT && "a restarted central triggers an immediate re-burst");

  // A change bursts, so one lost frame is not a lease-long wrong light. The slider has to
  // settle first, so the window is measured from the transition itself.
  laserDistance=383;
  for (int guard=0; guard<200 && central().member!=1; ++guard) { mark2=sentFrames.size(); run(5); }
  assert(central().member==1);
  run(POOL_BURST_GAP_MS*POOL_BURST_COUNT+20);
  assert(stateFrames(mark2).size()>=POOL_BURST_COUNT && "a member change is burst, not sent once");

  // A release keeps being re-asserted: a lost release leaves a light stuck on.
  presentedTag.clear(); run(1000);
  assert(!central().active);
  mark2=sentFrames.size(); run(POOL_RELEASE_REPEAT_MS);
  size_t releases=0;
  for (const auto &f : stateFrames(mark2)) { PoolState p; memcpy(&p,f.data.data(),sizeof(p)); if(!p.active) ++releases; }
  assert(releases>=4 && "the release is repeated, not sent once");

  // Idle heartbeats never stop, so the central can tell an idle slider from a dead one.
  run(2000);
  mark2=sentFrames.size(); run(POOL_IDLE_HEARTBEAT_MS*4);
  assert(stateFrames(mark2).size()>=3 && "an idle radio keeps reporting");
  for (const auto &f : stateFrames(mark2)) { PoolState p; memcpy(&p,f.data.data(),sizeof(p)); assert(!p.active); }

  // When the beacon stops, the radio falls back to broadcast rather than shouting at a
  // central that may no longer be there.
  run(POOL_BEACON_STALE_MS+200);
  assert(!centralFresh());
  mark2=sentFrames.size(); run(POOL_IDLE_HEARTBEAT_MS*3);
  assert(stateFrames(mark2, CENTRAL).empty() && !stateFrames(mark2, BROADCAST).empty());

  // A failing unicast is counted and still leaves the broadcast copy going out.
  beacon(0x1234, 1<<3); run(200);
  assert(centralFresh());
  uint32_t errorsBefore=centralErrors;
  failSends=true; run(POOL_IDLE_HEARTBEAT_MS*2); failSends=false;
  assert(centralErrors>errorsBefore);
  mark2=sentFrames.size(); run(POOL_BROADCAST_COPY_MS*2);
  assert(!stateFrames(mark2, BROADCAST).empty());

  // A reboot takes a new boot identity and restarts the sequence, which the central
  // accepts precisely because bootId changed.
  uint32_t previousBoot=poolBootId;
  setup(); run(300);
  assert(poolBootId!=previousBoot && poolSeq<=POOL_BURST_COUNT+2 && !centralKnown);

  puts("PASS: PoolZone ±33% mapping, flash, tagged POOL delivery/ACK, cube command, pool link beacon/latch/"
       "unicast+broadcast copy, bursts, repeated release, idle heartbeats, stale fallback, seq/bootId, "
       "unknown tags, leased host override and editing interlock");
}
