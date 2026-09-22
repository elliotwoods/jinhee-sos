// Real sketch: the pairing-station protocol it must keep (gate, discover, register, identify,
// zone relay, and the PN532 reader with its fresh-tag gating, ported from
// pairing_station/tests/firmware_test.cpp), the Mainshow verbs (set_zone with the plate's repeats,
// show_start with the showId rules and lockout), the emulated pool radio and preshow plate (bursts,
// heartbeats, beacon latching, acknowledgements, host leases), all against the shared protocol headers.
#include "zone_stubs.h"
#include "../firmware/Workstation/Workstation.ino"
#include "sketch_common.h"
#include "fixtures.h"

static const uint8_t CUBE44[6] = {0xAC, 0x27, 0x6E, 0x80, 0x00, 0xD0};
static const uint8_t ZONE1[6] = {0x14, 0x63, 0x93, 0xC0, 0xEC, 0x14};
static const uint8_t CENTRAL[6] = {0x02, 0x50, 0x4F, 0x4F, 0x4C, 0x01};
static const uint8_t BRIDGE[6] = {0x02, 0x50, 0x52, 0x45, 0x53, 0x01};
static const uint8_t LEGACY[6] = {0xE8, 0x3D, 0xC1, 0x94, 0x6C, 0x9C};

static Packet packetOf(const SentFrame &frame) {
  assert(frame.data.size() == sizeof(Packet) && sizeof(Packet) == 24);
  Packet p;
  memcpy(&p, frame.data.data(), sizeof(p));
  return p;
}

// Cube packets of one type sent since `from`, optionally only to `to`.
static std::vector<Packet> packets(size_t from, uint8_t type, const uint8_t *to = nullptr) {
  std::vector<Packet> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    if (sentFrames[i].data.size() != sizeof(Packet)) continue;
    if (to && memcmp(sentFrames[i].dest.data(), to, 6)) continue;
    Packet p = packetOf(sentFrames[i]);
    if (p.type == type) out.push_back(p);
  }
  return out;
}

static std::vector<nctzone::PoolState> poolStates(size_t from, const uint8_t *to = nullptr) {
  std::vector<nctzone::PoolState> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    if (nctzone::poolFrameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) != nctzone::POOL_STATE) continue;
    if (to && memcmp(sentFrames[i].dest.data(), to, 6)) continue;
    nctzone::PoolState s;
    memcpy(&s, sentFrames[i].data.data(), sizeof(s));
    out.push_back(s);
  }
  return out;
}

static std::vector<nctzone::PreshowEvent> preshowEvents(size_t from, const uint8_t *to = nullptr) {
  std::vector<nctzone::PreshowEvent> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    if (nctzone::preshowFrameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) != nctzone::PRESHOW_EVENT) continue;
    if (to && memcmp(sentFrames[i].dest.data(), to, 6)) continue;
    nctzone::PreshowEvent e;
    memcpy(&e, sentFrames[i].data.data(), sizeof(e));
    out.push_back(e);
  }
  return out;
}

static size_t legacyFrames(size_t from, const uint8_t *to) {
  size_t n = 0;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (sentFrames[i].data.size() == 2 && !memcmp(sentFrames[i].dest.data(), to, 6)) n++;
  return n;
}

static void cubeReply(const uint8_t *mac, uint8_t type, uint32_t cubeId = 0, uint8_t success = 0) {
  Packet p = {};
  p.type = type;
  p.cubeID = cubeId;
  memcpy(p.mac, mac, 6);
  p.success = success;
  radioFrom(mac, (const uint8_t *)&p, sizeof(p), false);
}

static void poolBeacon(uint32_t epoch, uint8_t mask) {
  nctzone::PoolBeacon b = {};
  nctzone::fillHeader(b.h, nctzone::POOL_BEACON);
  b.epoch = epoch;
  b.radioMask = mask;
  b.version = nctzone::POOL_PROTOCOL_VERSION;
  radioFrom(CENTRAL, (const uint8_t *)&b, sizeof(b), true);
}

static void preshowBeacon(uint32_t epoch, uint8_t mask) {
  nctzone::PreshowBeacon b = {};
  nctzone::fillHeader(b.h, nctzone::PRESHOW_BEACON);
  b.epoch = epoch;
  b.pointMask = mask;
  b.version = nctzone::PRESHOW_PROTOCOL_VERSION;
  radioFrom(BRIDGE, (const uint8_t *)&b, sizeof(b), true);
}

static void preshowAck(const nctzone::PreshowEvent &e, bool applied) {
  nctzone::PreshowAck a = {};
  nctzone::fillHeader(a.h, nctzone::PRESHOW_ACK);
  a.bootId = e.bootId;
  a.seq = e.seq;
  a.pointId = e.pointId;
  a.flags = applied ? nctzone::PRESHOW_ACK_APPLIED : 0;
  radioFrom(BRIDGE, (const uint8_t *)&a, sizeof(a), false);
}

static std::string ping() { return serial("{\"cmd\":\"ping\",\"id\":\"p\"}"); }

// Keep the host lease alive for `ms`, pinging every second. Every line the board said is in the
// result exactly once, so a test can count events.
static std::string hold(uint32_t ms) {
  std::string out;
  for (uint32_t t = 0; t < ms; t += 1000) {
    out += ping();
    Serial.output.clear();
    run(ms - t < 1000 ? ms - t : 980);
    out += Serial.output;
  }
  return out;
}

static size_t count(const std::string &text, const char *needle) {
  size_t n = 0;
  for (size_t at = text.find(needle); at != std::string::npos; at = text.find(needle, at + 1)) n++;
  return n;
}

static std::string hex(const uint8_t *data, size_t n) {
  std::string out;
  char b[3];
  for (size_t i = 0; i < n; i++) { snprintf(b, sizeof(b), "%02X", data[i]); out += b; }
  return out;
}

int main() {
  setup();

  // ---- Init ----
  assert(radioOk && radioChannel == 2);
  assert(!wifiSleep && !wifiPersistent && !wifiAutoReconnect);
  assert(esp_now_is_peer_exist(BROADCAST) && esp_now_is_peer_exist(LEGACY) && espPeers.size() == 2);
  // boot_reader_ready: the station's bus clear and init events, then the report and hello with the
  // reader's real state. The NFC report line sits between RADIO and READY (probe.py / zone_detect
  // parse the others unchanged).
  assert(has(Serial.output, "{\"event\":\"nfc_bus\",\"id\":\"\",\"sda_before\":1,\"scl_before\":1,\"sda_after\":1,\"scl_after\":1,\"pulses\":0}"));
  assert(has(Serial.output, "{\"event\":\"nfc_init\",\"id\":\"\",\"attempt\":1,\"i2c_status\":0,\"firmware\":838927879,\"ready\":true}"));
  assert(count(Serial.output, "nfc_init") == 1 && !has(Serial.output, "nfc_error"));
  assert(has(Serial.output, "NCT WORKSTATION\nFW: workstation-1.0.0\nMAC: 02:AA:BB:CC:DD:EE\nCHANNEL: 2\nRADIO: OK\n"
                            "NFC: ok=1 fw=32010607 polling=0 polls=0 found=0 last_ms=0 max_ms=0 fast_fail=0 recoveries=0 sda=1 scl=1\nREADY"));
  // Signatures zone_detect.py would match first, and what the cube identifier looks for.
  for (const char *needle : {"nct-pairing", "NCT GENERAL RADIO", "Cube READY", "Cube MAC:", "MAINSHOW ENTRANCE", "POOL RADIO",
                             "DESERT TAG PLATE", "MEDIA BRIDGE PEER", "PRESHOW EXIT TAG", "NCT PRESHOW TAG PLATE",
                             "NCT MAINSHOW CONTROLLER", "NCT PRESHOW MEDIA BRIDGE", "POOL CENTRAL", "NCT RANGE TEST"})
    assert(!has(Serial.output, needle));
  assert(has(Serial.output, "{\"event\":\"hello\",\"id\":\"\",\"protocol\":1,\"firmware\":\"workstation-1.0.0\",\"zones\":1,\"show\":1"));
  assert(has(Serial.output, "\"radio_ok\":true,\"nfc_ok\":true,\"nfc_polling\":false,\"nfc_firmware\":838927879,\"nfc_i2c_status\":0,\"tag_present\":false,"));
  assert(criticalDepth == 0 && wireBegins == 1 && wireSda == 4 && wireScl == 3);
  assert(sentFrames.empty() && "nothing is sent until asked");

  // ---- Host protocol ----
  std::string out = serial("{\"cmd\":\"hello\",\"id\":\"h1\"}");
  assert(has(out, "\"event\":\"hello\",\"id\":\"h1\"") && has(out, "\"channel\":2") && has(out, "\"radio_ok\":true"));
  assert(has(out, "\"nfc_ok\":true") && has(out, "\"roles\":[\"cube\",\"zone\",\"pool\",\"preshow\",\"nfc\"]"));
  assert(has(out, "\"pool\":{\"armed\":false,\"member\":0") && has(out, "\"preshow\":{\"armed\":false,\"point\":0"));
  assert(has(out, "\"lockout_ms\":3000") && has(out, "\"show_running\":false") && has(out, "\"busy\":\"idle\""));
  assert(has(serial("{\"cmd\": \"ping\", \"id\": \"p1\"}"), "{\"event\":\"pong\",\"id\":\"p1\"}"));
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s1\"}"), "{\"event\":\"status\",\"id\":\"s1\",\"protocol\":1"));
  assert(has(serial("{\"cmd\":\"ping\"}"), "Missing/invalid request id"));
  assert(has(serial("{\"cmd\":\"dance\",\"id\":\"x\"}"), "Unknown command"));
  // nfc_status_live: the station's fields, the firmware queried now rather than a cached flag.
  out = serial("{\"cmd\":\"nfc_status\",\"id\":\"n\"}");
  assert(has(out, "{\"event\":\"nfc_status\",\"id\":\"n\",\"sda\":1,\"scl\":1,\"i2c_status\":0,\"status_source\":\"firmware_response\","
                  "\"firmware_now\":838927879,\"nfc_polling\":false,\"polls\":0,\"found\":0,\"last_poll_ms\":0,\"max_poll_ms\":0,\"trace\":false}"));
  assert(has(serial("hello"), "one JSON object per line"));
  assert(has(serial("?"), "NCT WORKSTATION\nFW: workstation-1.0.0\nMAC: 02:AA:BB:CC:DD:EE\nCHANNEL: 2\nRADIO: OK\nNFC: ok=1 fw=32010607"));
  assert(has(serial("{\"cmd\":\"led_test\",\"id\":\"l\",\"on\":1}"), "\"event\":\"led_test\",\"id\":\"l\",\"on\":true,\"pin\":10"));
  assert(neoShown.size() == 8 && neoShown[0] == 0x3C0000u);  // red, whole strip
  assert(has(serial("{\"cmd\":\"led_test\",\"id\":\"l\",\"on\":0}"), "\"on\":false"));
  std::string longLine(1100, 'x');
  assert(has(serial(longLine.c_str()), "Serial command too long"));
  assert(sentFrames.empty());

  // ---- Gate: hello/ping within 5 s ----
  run(5100);
  assert(has(serial("{\"cmd\":\"discover\",\"id\":\"d0\"}"), "Send hello/ping before operating"));
  assert(sentFrames.empty());
  ping();

  // ---- Discover ----
  out = serial("{\"cmd\":\"discover\",\"id\":\"d1\"}");
  assert(has(out, "{\"event\":\"radio\",\"id\":\"\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"type\":1,\"status\":\"delivered\"}"));
  assert(has(out, "{\"event\":\"discover_sent\",\"id\":\"d1\"}"));
  assert(packets(0, MSG_DISCOVER, BROADCAST).size() == 1);
  Serial.output.clear();
  cubeReply(CUBE44, MSG_DISCOVER_REPLY);
  uint8_t other[6] = {0x02, 1, 2, 3, 4, 5};
  Packet forged = {};
  forged.type = MSG_DISCOVER_REPLY;
  memcpy(forged.mac, CUBE44, 6);
  radioFrom(other, (const uint8_t *)&forged, sizeof(forged), false);  // sender != reported MAC
  run(5);
  assert(has(Serial.output, "{\"event\":\"device\",\"id\":\"\",\"mac\":\"AC:27:6E:80:00:D0\"}"));
  assert(Serial.output.find("device") == Serial.output.rfind("device"));

  // ---- Zone relay: the station's rules ----
  nctzone::ZoneQuery query = {};
  nctzone::fillHeader(query.h, nctzone::ZONE_QUERY);
  query.nonce = 7;
  query.what = nctzone::QUERY_STATUS;
  std::string queryHex = hex((const uint8_t *)&query, sizeof(query));
  size_t before = sentFrames.size();
  out = serial(("{\"cmd\":\"zone_send\",\"id\":\"z1\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" + queryHex + "\"}").c_str());
  assert(has(out, "{\"event\":\"zone_sent\",\"id\":\"z1\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"kind\":32,\"status\":\"delivered\"}"));
  assert(sentFrames.size() == before + 1 && sentFrames.back().data.size() == sizeof(query));
  assert(espPeers.size() == 2 && "no peer left behind");
  out = serial(("{\"cmd\":\"zone_send\",\"id\":\"z2\",\"mac\":\"14:63:93:C0:EC:14\",\"hex\":\"" + queryHex + "\"}").c_str());
  assert(has(out, "\"mac\":\"14:63:93:C0:EC:14\",\"kind\":32,\"status\":\"delivered\"") && espPeers.size() == 2);
  nctzone::ZoneIdentify identify = {};
  nctzone::fillHeader(identify.h, nctzone::ZONE_IDENTIFY);
  identify.seconds = 5;
  std::string identifyHex = hex((const uint8_t *)&identify, sizeof(identify));
  assert(has(serial(("{\"cmd\":\"zone_send\",\"id\":\"z3\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" + identifyHex + "\"}").c_str()),
             "must target one zone"));
  assert(has(serial(("{\"cmd\":\"zone_send\",\"id\":\"z4\",\"mac\":\"01:00:5E:00:00:01\",\"hex\":\"" + queryHex + "\"}").c_str()),
             "Invalid zone MAC"));
  nctzone::ZoneStatus status = {};
  nctzone::fillHeader(status.h, nctzone::ZONE_STATUS);
  status.zoneType = 1;
  status.pointId = 2;
  std::string statusHex = hex((const uint8_t *)&status, sizeof(status));
  assert(has(serial(("{\"cmd\":\"zone_send\",\"id\":\"z5\",\"mac\":\"14:63:93:C0:EC:14\",\"hex\":\"" + statusHex + "\"}").c_str()),
             "Invalid zone frame"));
  // A zone's status reply comes up as zone_frame with its signal strength; another registry's
  // announce does not.
  Serial.output.clear();
  {
    uint8_t src[6], dst[6];
    memcpy(src, ZONE1, 6);
    memcpy(dst, SELF, 6);
    wifi_pkt_rx_ctrl_t ctrl{-61};
    esp_now_recv_info_t info{src, dst, &ctrl};
    recvCallback(&info, (const uint8_t *)&status, int(sizeof(status)));
  }
  nctzone::DbAnnounce announce = {};
  nctzone::fillHeader(announce.h, nctzone::DB_ANNOUNCE);
  radioFrom(REGISTRY, (const uint8_t *)&announce, sizeof(announce), true);
  run(5);
  assert(has(Serial.output, ("{\"event\":\"zone_frame\",\"id\":\"\",\"mac\":\"14:63:93:C0:EC:14\",\"kind\":33,\"rssi\":-61,\"hex\":\"" + statusHex + "\"}").c_str()));
  assert(!has(Serial.output, "\"kind\":16"));

  // ---- set_zone: one cube, three frames at 0/120/400 ms ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"set_zone\",\"id\":\"s1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4}");
  assert(has(out, "{\"event\":\"zone_sent\",\"id\":\"s1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4,\"status\":\"delivered\",\"repeats\":3}"));
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 1 && packets(before, MSG_SET_ZONE, CUBE44)[0].success == 4);
  run(90);  // t = 110: the second frame is not due yet
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 1);
  run(20);
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 2);
  assert(has(Serial.output, "{\"event\":\"zone_repeat\",\"id\":\"\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4,\"n\":2,\"status\":\"delivered\"}"));
  run(300);
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 3);
  run(1000);
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 3 && "no more than the plate's three");
  assert(espPeers.size() == 2);
  // A new colour for the same cube supersedes its pending repeats.
  before = sentFrames.size();
  serial("{\"cmd\":\"set_zone\",\"id\":\"s2\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":2}");
  serial("{\"cmd\":\"set_zone\",\"id\":\"s3\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":0}");
  run(500);
  {
    auto sent = packets(before, MSG_SET_ZONE, CUBE44);
    assert(sent.size() == 4 && sent[0].success == 2 && sent[1].success == 0 && sent[2].success == 0 && sent[3].success == 0);
  }
  // Every cube in range, only when spelled out.
  before = sentFrames.size();
  out = serial("{\"cmd\":\"set_zone\",\"id\":\"s4\",\"mac\":\"broadcast\",\"zone\":0}");
  assert(has(out, "\"mac\":\"broadcast\",\"zone\":0,\"status\":\"delivered\",\"repeats\":3"));
  run(500);
  assert(packets(before, MSG_SET_ZONE, BROADCAST).size() == 3);
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"s5\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"zone\":0}"), "unicast MAC"));
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"s6\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":5}"), "Zone must be 0-4"));

  // ---- show_start: fresh showId x5, lockout ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"t1\",\"target\":\"AC:27:6E:80:00:D0\"}");
  {
    auto starts = packets(before, MSG_SHOW_START, CUBE44);
    assert(starts.size() == 5 && starts[0].cubeID != 0);
    for (auto &p : starts) assert(p.cubeID == starts[0].cubeID);
    assert(has(out, ("\"event\":\"show_start\",\"id\":\"t1\",\"source\":\"usb\",\"show_id\":" + std::to_string(starts[0].cubeID)).c_str()));
    assert(has(out, "\"target\":\"AC:27:6E:80:00:D0\",\"sent\":5,\"repeats\":5,\"delivered\":5"));
    uint32_t first = starts[0].cubeID;
    out = serial("{\"cmd\":\"show_start\",\"id\":\"t2\",\"target\":\"broadcast\"}");
    assert(has(out, "\"event\":\"locked\",\"id\":\"t2\",\"source\":\"usb\",\"retry_ms\":"));
    assert(packets(before, MSG_SHOW_START).size() == 5);
    hold(3100);
    before = sentFrames.size();
    out = serial("{\"cmd\":\"show_start\",\"id\":\"t3\",\"target\":\"broadcast\"}");
    auto again = packets(before, MSG_SHOW_START, BROADCAST);
    assert(again.size() == 5 && again[0].cubeID != first);
    assert(has(out, "\"target\":\"broadcast\",\"sent\":5,\"repeats\":5}") && !has(out, "delivered"));
    assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"show_running\":true"));
  }
  assert(has(serial("{\"cmd\":\"show_start\",\"id\":\"t4\",\"target\":\"01:00:5E:00:00:01\"}"), "unicast MAC"));

  // ---- Register: attempts, matching ack, pause, release ----
  ping();
  before = sentFrames.size();
  out = serial("{\"cmd\":\"register\",\"id\":\"r1\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":44,\"uid\":\"04:A1:B2:C3\"}");
  assert(has(out, "{\"event\":\"attempt\",\"id\":\"r1\",\"attempt\":1,\"mac\":\"AC:27:6E:80:00:D0\"}"));
  assert(has(out, "{\"event\":\"radio\",\"id\":\"r1\",\"mac\":\"AC:27:6E:80:00:D0\",\"type\":3,\"status\":\"delivered\"}"));
  {
    auto reg = packets(before, MSG_REGISTER, CUBE44);
    assert(reg.size() == 1 && reg[0].cubeID == 44 && reg[0].uidLength == 4 && reg[0].uid[0] == 0x04 && reg[0].uid[3] == 0xC3);
  }
  assert(has(serial("{\"cmd\":\"discover\",\"id\":\"d2\"}"), "Registration is active"));
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"busy\":\"registering\""));
  hold(2100);
  assert(packets(before, MSG_REGISTER, CUBE44).size() == 2);
  Serial.output.clear();
  cubeReply(CUBE44, MSG_REGISTER_ACK, 45, 1);  // wrong cube id: ignored
  run(5);
  assert(!has(Serial.output, "ack_received"));
  cubeReply(CUBE44, MSG_REGISTER_ACK, 44, 1);
  run(5);
  assert(has(Serial.output, "{\"event\":\"ack_received\",\"id\":\"r1\",\"detail\":\"Allowing cube confirmation blink to finish\"}"));
  assert(!has(Serial.output, "registered"));
  size_t beforeRelease = sentFrames.size();
  out = hold(1100);
  assert(has(out, "\"event\":\"registered\",\"id\":\"r1\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":44,\"acknowledged\":true"));
  assert(packets(beforeRelease, MSG_SET_ZONE, CUBE44).size() == 1 && packets(beforeRelease, MSG_SET_ZONE, CUBE44)[0].success == 0);
  assert(packets(before, MSG_REGISTER, CUBE44).size() == 2 && "no third attempt after the ack");
  // Unacknowledged: three attempts, then failure.
  before = sentFrames.size();
  serial("{\"cmd\":\"register\",\"id\":\"r2\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":44,\"uid\":\"04:A1:B2:C3:D4:E5:F6\"}");
  out = hold(6100);
  assert(packets(before, MSG_REGISTER, CUBE44).size() == 3);
  assert(has(out, "\"acknowledged\":false,\"detail\":\"No matching acknowledgment after three attempts\""));
  assert(has(serial("{\"cmd\":\"register\",\"id\":\"r3\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":0,\"uid\":\"04:A1:B2:C3\"}"), "Invalid cube ID"));
  assert(has(serial("{\"cmd\":\"register\",\"id\":\"r4\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":4,\"uid\":\"04:A1\"}"), "Invalid cube ID"));

  // ---- Identify: blink, done, and the heartbeat watchdog ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"identify\",\"id\":\"i1\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":1200}");
  assert(has(out, "{\"event\":\"identifying\",\"id\":\"i1\"}"));
  assert(packets(before, MSG_SET_ZONE, CUBE44).size() == 1 && packets(before, MSG_SET_ZONE, CUBE44)[0].success == 1);
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"s7\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":2}"), "held by identify"));
  assert(has(serial("{\"cmd\":\"identify\",\"id\":\"i2\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":10}"), "stop first"));
  // nfc_commands_refused_while_busy: the station's three wordings.
  assert(has(serial("{\"cmd\":\"nfc_recover\",\"id\":\"nb1\"}"), "{\"event\":\"error\",\"id\":\"nb1\",\"detail\":\"Stop before reader recovery\"}"));
  assert(has(serial("{\"cmd\":\"nfc_poll\",\"id\":\"nb2\",\"enabled\":1}"), "{\"event\":\"error\",\"id\":\"nb2\",\"detail\":\"Stop before reader diagnostics\"}"));
  assert(has(serial("{\"cmd\":\"nfc_status\",\"id\":\"nb3\"}"), "{\"event\":\"error\",\"id\":\"nb3\",\"detail\":\"Stop the current operation before reader diagnostics\"}"));
  assert(!nfc::polling && "refused: not switched on");
  out = hold(1300);
  {
    auto blink = packets(before, MSG_SET_ZONE, CUBE44);
    assert(blink.size() == 4 && blink[1].success == 3 && blink[2].success == 1 && blink[3].success == 0);
    assert(has(out, "{\"event\":\"flash_done\",\"id\":\"i1\"}"));
  }
  assert(has(serial("{\"cmd\":\"identify\",\"id\":\"i3\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":70000}"), "60 seconds"));
  before = sentFrames.size();
  serial("{\"cmd\":\"identify\",\"id\":\"i4\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":0}");
  run(5100);  // no ping
  assert(has(Serial.output, "{\"event\":\"watchdog\",\"id\":\"i4\",\"detail\":\"Application heartbeat lost; attempted idle\"}"));
  assert(packets(before, MSG_SET_ZONE, CUBE44).back().success == 0);
  assert(has(serial("{\"cmd\":\"stop\",\"id\":\"x\"}"), "{\"event\":\"stopped\",\"id\":\"x\"}"));
  ping();
  before = sentFrames.size();
  serial("{\"cmd\":\"identify\",\"id\":\"i5\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":0}");
  out = serial("{\"cmd\":\"stop\",\"id\":\"x2\"}");
  assert(has(out, "stopped") && packets(before, MSG_SET_ZONE, CUBE44).back().success == 0);

  // ---- Pool: one emulated radio ----
  ping();
  assert(poolStates(0).empty() && "silent until a member is held");
  before = sentFrames.size();
  out = serial("{\"cmd\":\"pool\",\"id\":\"q1\",\"member\":5}", 50);
  assert(has(out, "\"event\":\"pool_state\",\"id\":\"q1\",\"armed\":true,\"member\":5,\"radio_id\":1,\"central_mac\":\"\",\"unicast\":false"));
  {
    auto burst = poolStates(before, BROADCAST);  // no beacon yet: broadcast
    assert(burst.size() == 3 && burst[0].member == 5 && burst[0].active == 1 && burst[0].radioId == 1);
    assert(burst[0].bootId != 0 && burst[1].seq == burst[0].seq + 1 && burst[2].seq == burst[0].seq + 2);
    assert(burst[0].leaseMs == nctzone::POOL_LEASE_DEFAULT_MS && nctzone::poolStateValid(burst[0]));
  }
  before = sentFrames.size();
  run(600);
  assert(poolStates(before).size() == 4 && "heartbeat every 150 ms");
  Serial.output.clear();
  poolBeacon(1000, 0);
  before = sentFrames.size();
  run(50);
  assert(has(Serial.output, "{\"event\":\"pool_beacon\",\"id\":\"\",\"mac\":\"02:50:4F:4F:4C:01\",\"epoch\":1000,\"uptime_s\":0,\"radio_mask\":0,\"version\":1}"));
  assert(esp_now_is_peer_exist(CENTRAL) && espPeers.size() == 3);
  {
    auto burst = poolStates(before, CENTRAL);  // the central moved from unknown: re-burst, unicast now
    assert(burst.size() == 3 && burst[0].member == 5);
  }
  before = sentFrames.size();
  out = hold(1000);
  assert(poolStates(before, CENTRAL).size() >= 6 && poolStates(before, BROADCAST).size() == 2 && "unicast heartbeat plus broadcast copies");
  assert(!has(out, "pool_beacon") && "a beacon every 500 ms is not reported every time");
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"central_mac\":\"02:50:4F:4F:4C:01\",\"unicast\":true"));
  // Release: active=0 re-asserted for a second, then silence.
  before = sentFrames.size();
  out = serial("{\"cmd\":\"pool\",\"id\":\"q2\",\"member\":0}", 50);
  assert(has(out, "\"armed\":false,\"member\":0"));
  hold(1500);
  {
    auto release = poolStates(before);
    assert(release.size() >= 8 && release.size() <= 12);
    for (auto &s : release) assert(s.active == 0 && s.member == 0);
  }
  before = sentFrames.size();
  hold(1000);
  assert(poolStates(before).empty() && "nothing on the air once released");
  // Lease: no ping for 1.5 s releases the member.
  serial("{\"cmd\":\"pool\",\"id\":\"q3\",\"member\":7,\"radio_id\":3}", 50);
  before = sentFrames.size();
  Serial.output.clear();
  run(1600);
  assert(has(Serial.output, "{\"event\":\"pool_watchdog\",\"id\":\"\",\"detail\":\"host lease expired; member released\",\"armed\":false,\"member\":0,\"radio_id\":3"));
  assert(poolStates(before).back().active == 0 && poolStates(before).front().member == 7);
  assert(has(serial("{\"cmd\":\"pool\",\"id\":\"q4\",\"member\":24}"), "member: 0 (off) or 1-23"));
  assert(has(serial("{\"cmd\":\"pool\",\"id\":\"q5\",\"member\":1,\"radio_id\":7}"), "radio_id must be 1-6"));
  hold(1200);  // let the release window pass

  // ---- Preshow: a fifth plate ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"preshow\",\"id\":\"w1\",\"point\":2,\"state\":1}", 50);
  assert(has(out, "\"event\":\"preshow_state\",\"id\":\"w1\",\"armed\":true,\"point\":2,\"state\":1,\"seq\":1,\"acked\":false"));
  assert(has(out, "\"bridge_mac\":\"\",\"unicast\":false,\"mode\":\"legacy\""));
  {
    // No bridge known: the burst of three is broadcast, plus the periodic broadcast copy that is
    // due at once, plus the 2-byte packet to the old bridge board.
    auto burst = preshowEvents(before, BROADCAST);
    assert(burst.size() == 4 && burst[0].pointId == 2 && burst[0].state == 1 && burst[0].seq == 1 && burst[0].uidLength == 0);
    assert(burst[1].seq == 1 && "retransmissions are byte-identical");
    assert(nctzone::preshowEventValid(burst[0]) && legacyFrames(before, LEGACY) == 3);
  }
  before = sentFrames.size();
  run(250);
  assert(preshowEvents(before).size() == 2 && "retry every 120 ms while unacknowledged");
  Serial.output.clear();
  preshowBeacon(500, 0);
  before = sentFrames.size();
  run(50);
  assert(has(Serial.output, "{\"event\":\"preshow_beacon\",\"id\":\"\",\"mac\":\"02:50:52:45:53:01\",\"epoch\":500,\"uptime_s\":0,\"point_mask\":0,\"version\":1}"));
  assert(esp_now_is_peer_exist(BRIDGE) && espPeers.size() == 4);
  {
    auto burst = preshowEvents(before, BRIDGE);
    assert(burst.size() == 3 && legacyFrames(before, LEGACY) == 0 && "legacy fallback off for good");
    Serial.output.clear();
    preshowAck(burst[0], true);
    run(5);
    assert(has(Serial.output, "{\"event\":\"preshow_ack\",\"id\":\"\",\"point\":2,\"state\":1,\"seq\":1,\"ms\":"));
    assert(has(Serial.output, "\"applied\":true}"));
  }
  before = sentFrames.size();
  out = hold(2100);
  assert(preshowEvents(before, BRIDGE).size() == 2 && preshowEvents(before, BROADCAST).size() == 2 && "re-asserted once a second, one broadcast copy a second");
  assert(!has(out, "preshow_fail"));
  assert(has(serial("{\"cmd\":\"preshow\",\"id\":\"w2\",\"point\":3,\"state\":1}"), "Point 2 is still ON; turn it off first"));
  assert(has(serial("{\"cmd\":\"preshow\",\"id\":\"w3\",\"point\":3,\"state\":0}"), "not the one held ON"));
  preshowBeacon(500, 0);  // the real bridge beacons every 500 ms; without one for 3 s the link goes broadcast-only
  before = sentFrames.size();
  out = serial("{\"cmd\":\"preshow\",\"id\":\"w4\",\"point\":2,\"state\":0}", 50);
  assert(has(out, "\"armed\":true,\"point\":2,\"state\":0,\"seq\":2,\"acked\":false"));
  {
    auto off = preshowEvents(before, BRIDGE);
    assert(off.size() == 3 && off[0].state == 0 && off[0].pointId == 2 && off[0].seq == 2);
  }
  // Unacknowledged with a bridge present: reported once after the 3 s window, still re-asserted.
  before = sentFrames.size();
  out = hold(1500);
  preshowBeacon(500, 0);
  out += hold(1800);
  assert(has(out, "{\"event\":\"preshow_fail\",\"id\":\"\",\"point\":2,\"state\":0,\"seq\":2}"));
  assert(out.find("preshow_fail") == out.rfind("preshow_fail"));
  assert(preshowEvents(before, BRIDGE).size() >= 20 && "retried every 120 ms for the window, then re-asserted");
  // A restarted bridge gets the state delivered again.
  before = sentFrames.size();
  preshowBeacon(501, 0);
  run(60);
  assert(preshowEvents(before, BRIDGE).size() == 3);
  // The lease: an ON that stops being pinged is turned off.
  serial("{\"cmd\":\"preshow\",\"id\":\"w5\",\"point\":1,\"state\":1}", 50);
  before = sentFrames.size();
  Serial.output.clear();
  run(1600);
  assert(has(Serial.output, "{\"event\":\"preshow_watchdog\",\"id\":\"\",\"detail\":\"host lease expired; cue turned off\",\"armed\":false,\"point\":1,\"state\":0,\"seq\":4"));
  {
    auto frames = preshowEvents(before, BRIDGE);
    assert(frames.front().state == 1 && frames.front().pointId == 1 && frames.back().state == 0 && frames.back().pointId == 1);
  }
  assert(has(serial("{\"cmd\":\"preshow\",\"id\":\"w6\",\"point\":5,\"state\":1}"), "point: 1-4"));
  assert(has(serial("{\"cmd\":\"preshow\",\"id\":\"w7\",\"point\":1,\"state\":2}"), "state: 1 (ON) or 0 (OFF)"));

  // ---- Show relay (general-radio-1.1.0; SHOW_LIVE 1.2.0): the host's show frames out, SHOW_STATUS back ----
  run(3100);
  ping();
  before = sentFrames.size();
  out = serial(("{\"cmd\":\"show_send\",\"id\":\"s1\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" +
                hex(SHOW_ANNOUNCE_V5.data(), SHOW_ANNOUNCE_V5.size()) + "\"}").c_str());
  assert(has(out, "{\"event\":\"show_sent\",\"id\":\"s1\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"kind\":80,\"status\":\"delivered\"}"));
  assert(sentFrames.size() == before + 1 && sentFrames.back().data == SHOW_ANNOUNCE_V5 &&
         !memcmp(sentFrames.back().dest.data(), BROADCAST, 6));
  for (const auto &chunk : SHOW_CHUNKS_V5) {
    out = serial(("{\"cmd\":\"show_send\",\"id\":\"s2\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" +
                  hex(chunk.data(), chunk.size()) + "\"}").c_str());
    assert(has(out, "\"kind\":81") && sentFrames.back().data == chunk);
  }
  out = serial(("{\"cmd\":\"show_send\",\"id\":\"s3\",\"mac\":\"AC:27:6E:80:00:D0\",\"hex\":\"" +
                hex(SHOW_QUERY_FRAME.data(), SHOW_QUERY_FRAME.size()) + "\"}").c_str());
  assert(has(out, "\"kind\":82") && !memcmp(sentFrames.back().dest.data(), CUBE44, 6));
  // Only what a show registry may send: never timecode (that is the show controller's), a status, a
  // zone frame or a multicast group.
  before = sentFrames.size();
  for (const auto &frame : {SHOW_TIMECODE_FRAME, FRAME_QUERY_STATUS}) {
    assert(has(serial(("{\"cmd\":\"show_send\",\"id\":\"s4\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" +
                       hex(frame.data(), frame.size()) + "\"}").c_str()), "Invalid show frame"));
  }
  assert(has(serial(("{\"cmd\":\"show_send\",\"id\":\"s5\",\"mac\":\"01:00:5E:00:00:01\",\"hex\":\"" +
                     hex(SHOW_QUERY_FRAME.data(), SHOW_QUERY_FRAME.size()) + "\"}").c_str()), "Invalid show MAC"));
  assert(sentFrames.size() == before);
  // SHOW_LIVE (general-radio-1.2.0): the show editor's live frame, broadcast only; the largest
  // (48 entries, 247 bytes) is bigger than a chunk and still fits.
  for (const auto &frame : {LIVE_23, LIVE_FULL}) {
    out = serial(("{\"cmd\":\"show_send\",\"id\":\"s6\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" +
                  hex(frame.data(), frame.size()) + "\"}").c_str());
    assert(has(out, "{\"event\":\"show_sent\",\"id\":\"s6\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"kind\":85,\"status\":\"delivered\"}"));
    assert(sentFrames.back().data == frame && !memcmp(sentFrames.back().dest.data(), BROADCAST, 6));
  }
  before = sentFrames.size();
  assert(has(serial(("{\"cmd\":\"show_send\",\"id\":\"s7\",\"mac\":\"AC:27:6E:80:00:D0\",\"hex\":\"" +
                     hex(LIVE_23.data(), LIVE_23.size()) + "\"}").c_str()), "SHOW_LIVE is broadcast only"));
  {
    std::vector<uint8_t> torn(LIVE_FULL.begin(), LIVE_FULL.end() - 1);  // n says 48, one byte short
    assert(has(serial(("{\"cmd\":\"show_send\",\"id\":\"s8\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"hex\":\"" +
                       hex(torn.data(), torn.size()) + "\"}").c_str()), "Invalid show frame"));
  }
  assert(sentFrames.size() == before);
  // A cube's SHOW_STATUS goes up as show_frame; another host's announce heard on the air does not.
  {
    nctshow::ShowStatus st = {};
    nctshow::fillHeader(st.h, nctshow::SHOW_STATUS);
    st.version = 5; st.cubeId = 44;
    Serial.output.clear();
    radioFrom(CUBE44, (const uint8_t *)&st, sizeof st);
    radioFrom(ZONE1, SHOW_ANNOUNCE_V5.data(), SHOW_ANNOUNCE_V5.size());
    run(20);
    assert(has(Serial.output, ("{\"event\":\"show_frame\",\"id\":\"\",\"mac\":\"AC:27:6E:80:00:D0\",\"kind\":83,\"hex\":\"" +
                               hex((const uint8_t *)&st, sizeof st) + "\"}").c_str()));
    assert(Serial.output.find("show_frame") == Serial.output.rfind("show_frame"));
  }

  // ---- Show timecode: as the Mainshow controller, bounded by show_config ----
  out = serial("{\"cmd\":\"show_config\",\"id\":\"c1\",\"length_ms\":4500,\"version\":5,\"crc\":77}");
  assert(has(out, "{\"event\":\"show_config\",\"id\":\"c1\",\"length_ms\":4500,\"version\":5,\"crc\":77}"));
  assert(has(serial("{\"cmd\":\"show_config\",\"id\":\"c2\",\"length_ms\":0}"), "show_config needs length_ms"));
  before = sentFrames.size();
  serial("{\"cmd\":\"show_start\",\"id\":\"t9\",\"target\":\"broadcast\"}", 400);
  out = hold(6000);
  {
    std::vector<nctshow::ShowTimecode> tcs;
    for (size_t i = before; i < sentFrames.size(); i++) {
      const auto &f = sentFrames[i];
      if (nctshow::frameType(f.data.data(), int(f.data.size())) != nctshow::SHOW_TIMECODE) continue;
      nctshow::ShowTimecode tc;
      memcpy(&tc, f.data.data(), sizeof tc);
      assert(!memcmp(f.dest.data(), BROADCAST, 6));
      tcs.push_back(tc);
    }
    assert(tcs.size() == 5 && tcs[0].tMs < 400 && tcs.back().tMs < 4500 && "one after the burst, then 1 Hz, until the length");
    assert(tcs[0].showId == cube::lastShowId && tcs[0].showVersion == 5 && tcs[0].showCrc == 77);
  }
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"h9\"}"), "\"show_running\":false,\"show_length_ms\":4500,\"timecode\":true"));
  run(3100);
  ping();
  serial("{\"cmd\":\"show_start\",\"id\":\"t10\",\"target\":\"broadcast\"}", 400);
  assert(has(serial("{\"cmd\":\"show_stop\",\"id\":\"x1\"}"), "{\"event\":\"show_stop\",\"id\":\"x1\",\"was_running\":true"));
  before = sentFrames.size();
  hold(3000);
  for (size_t i = before; i < sentFrames.size(); i++)
    assert(nctshow::frameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) != nctshow::SHOW_TIMECODE);

  // ---- Reader (workstation-1.0.0): the station's PN532, polled only while a host asks ----
  ping();
  // nfc_not_polled_until_asked: a tag on an idle reader is never read, so a bare relay is never
  // slowed by the 80 ms read.
  presentedTag = {4, 1, 2, 3};
  out = hold(2000);
  assert(!has(out, "tag_state") && nfc::polls == 0);  // (tagPresent is still the identify's synthetic true: only polling clears it)
  // nfc_poll_enable_and_once: `once` reads now and leaves polling off (the station's semantics);
  // `enabled` switches it on and off.
  out = serial("{\"cmd\":\"nfc_poll\",\"id\":\"n1\",\"once\":1}");
  assert(out.find("{\"event\":\"tag_state\",\"id\":\"\",\"present\":true}") < out.find("nfc_poll_result"));
  assert(has(out, "{\"event\":\"nfc_poll_result\",\"id\":\"n1\",\"ready\":true,\"enabled\":false,\"polls\":1,\"found\":1,\"duration_ms\":20,"
                  "\"tag_present\":true,\"uid\":\"04:01:02:03\"}"));
  assert(!has(out, "\"event\":\"tag\"") && "not identifying: no pairing scan");
  out = hold(1000);
  assert(!has(out, "tag_state") && nfc::polls == 1 && "once leaves polling off");
  out = serial("{\"cmd\":\"nfc_poll\",\"id\":\"n2\",\"enabled\":true}");
  assert(has(out, "{\"event\":\"nfc_poll_result\",\"id\":\"n2\",\"ready\":true,\"enabled\":true,\"polls\":1,"));
  hold(1000);
  assert(nfc::polls >= 15 && nfc::found >= 15 && "every 50 ms");
  presentedTag.clear();
  out = hold(1000);
  assert(has(out, "{\"event\":\"tag_state\",\"id\":\"\",\"present\":false}") && count(out, "tag_state") == 1);
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"nfc_ok\":true,\"nfc_polling\":true,\"nfc_firmware\":838927879,\"nfc_i2c_status\":0,\"tag_present\":false,"));
  out = serial("{\"cmd\":\"nfc_status\",\"id\":\"n3\"}");
  assert(has(out, "\"firmware_now\":838927879,\"nfc_polling\":true,") && has(out, "\"last_poll_ms\":80,\"max_poll_ms\":80,\"trace\":false}"));
  assert(has(serial("{\"cmd\":\"nfc_poll\",\"id\":\"n4\",\"enabled\":false}"), "\"ready\":true,\"enabled\":false,"));
  {
    uint32_t polls = nfc::polls;
    hold(1000);
    assert(nfc::polls == polls && "off again");
  }
  assert(has(serial("?"), "NFC: ok=1 fw=32010607 polling=0 polls="));

  // identify_fresh_tag_gating: the station's rule that a tag already on the reader is not a pairing
  // scan. The synthetic tag_state precedes the radio and identifying events; the reader must see the
  // interval clear, then exactly one `tag` per placement.
  serial("{\"cmd\":\"nfc_poll\",\"id\":\"n5\",\"enabled\":true}");
  before = sentFrames.size();
  out = serial("{\"cmd\":\"identify\",\"id\":\"i6\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":0}");
  assert(out.find("{\"event\":\"tag_state\",\"id\":\"\",\"present\":true}") < out.find("{\"event\":\"radio\",\"id\":\"i6\""));
  assert(out.find("{\"event\":\"radio\",\"id\":\"i6\"") < out.find("{\"event\":\"identifying\",\"id\":\"i6\"}"));
  presentedTag = {4, 1, 2, 3};
  out = hold(100);
  assert(!has(out, "\"event\":\"tag\"") && "a tag already on the reader cannot carry over");
  presentedTag.clear();
  out = hold(800);
  assert(has(out, "{\"event\":\"tag_state\",\"id\":\"\",\"present\":false}"));
  presentedTag = {4, 1, 2, 3};
  out = hold(100);
  assert(has(out, "{\"event\":\"tag\",\"id\":\"i6\",\"uid\":\"04:01:02:03\"}") && count(out, "\"event\":\"tag\"") == 1);
  out = hold(100);
  assert(!has(out, "\"event\":\"tag\"") && "still there: no second scan");
  {
    auto blink = packets(before, MSG_SET_ZONE, CUBE44);
    assert(blink.size() >= 3 && blink[0].success == 1 && blink[1].success == 3 && blink[2].success == 1 && "blinking throughout");
  }
  // identify_blink_timing_with_polling: the 500 ms alternation and flash_done hold with the 80 ms
  // no-tag read inside the loop, allowing one poll period of slack.
  serial("{\"cmd\":\"stop\",\"id\":\"x3\"}");
  presentedTag.clear();
  hold(800);
  before = sentFrames.size();
  serial("{\"cmd\":\"identify\",\"id\":\"i7\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":1200}");
  out = hold(1400);
  {
    auto blink = packets(before, MSG_SET_ZONE, CUBE44);
    assert(blink.size() == 4 && blink[0].success == 1 && blink[1].success == 3 && blink[2].success == 1 && blink[3].success == 0);
    assert(has(out, "{\"event\":\"flash_done\",\"id\":\"i7\"}"));
  }
  // register_disarms: after the scan, register (the station clears scanArmed there), stop and hello
  // all end the scan; a tag placed afterwards is state only.
  serial("{\"cmd\":\"identify\",\"id\":\"i8\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":0}");
  hold(800);
  presentedTag = {4, 1, 2, 3};
  out = hold(100);
  assert(has(out, "{\"event\":\"tag\",\"id\":\"i8\",\"uid\":\"04:01:02:03\"}"));
  out = serial("{\"cmd\":\"register\",\"id\":\"r5\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":44,\"uid\":\"04:01:02:03\"}");
  assert(has(out, "{\"event\":\"attempt\",\"id\":\"r5\",\"attempt\":1,"));
  presentedTag.clear();
  out = hold(800);
  presentedTag = {4, 1, 2, 3};
  out += hold(100);
  assert(has(out, "\"present\":false") && has(out, "\"present\":true") && !has(out, "\"event\":\"tag\""));
  cubeReply(CUBE44, MSG_REGISTER_ACK, 44, 1);
  out = hold(1300);
  assert(has(out, "\"event\":\"registered\",\"id\":\"r5\",\"mac\":\"AC:27:6E:80:00:D0\",\"cube_id\":44,\"acknowledged\":true"));
  for (const char *release : {"{\"cmd\":\"stop\",\"id\":\"x4\"}", "{\"cmd\":\"hello\",\"id\":\"h2\"}"}) {
    ping();
    serial("{\"cmd\":\"identify\",\"id\":\"i9\",\"mac\":\"AC:27:6E:80:00:D0\",\"duration_ms\":0}");
    presentedTag.clear();
    hold(800);  // the interval clears: a scan is armed
    assert(nfc::scanArmed);
    serial(release);
    assert(!nfc::scanArmed && !nfc::identifying);
    presentedTag = {4, 1, 2, 3};
    out = hold(100);
    assert(has(out, "{\"event\":\"tag_state\",\"id\":\"\",\"present\":true}") && !has(out, "\"event\":\"tag\""));
  }
  // uid_rejection: a 10-byte UID is reported and refused, as the station does.
  presentedTag = {4, 1, 2, 3, 4, 5, 6, 7, 8, 9};
  out = hold(100);
  assert(has(out, "{\"event\":\"nfc_error\",\"id\":\"\",\"detail\":\"Unsupported UID length; remove this tag\"}"));
  presentedTag.clear();
  hold(800);
  assert(!nfc::tagPresent);
  // bus_recovery_held_low: the station's nine-clock bus clear. The station clocks all nine whenever
  // SCL is free and SDA is held (it stops early only for a stuck SCL), then STOPs.
  {
    int begins = wireBegins;
    heldLow[4] = 3;  // released after three clocks
    out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b1\"}");
    assert(has(out, "{\"event\":\"nfc_bus\",\"id\":\"\",\"sda_before\":0,\"scl_before\":1,\"sda_after\":1,\"scl_after\":1,\"pulses\":9}"));
    assert(has(out, "{\"event\":\"nfc_recovered\",\"id\":\"b1\",\"bus_clear\":true,\"ready\":true,\"firmware\":838927879,\"i2c_status\":0}"));
    assert(wireBegins == begins + 1 && !nfc::polling && "recovery restarts the bus and stops polling");
    heldLow[4] = -1;  // never released
    out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b2\"}");
    assert(has(out, "\"sda_before\":0,\"scl_before\":1,\"sda_after\":0,\"scl_after\":1,\"pulses\":9}"));
    assert(has(out, "\"event\":\"nfc_recovered\",\"id\":\"b2\",\"bus_clear\":false,\"ready\":false,") && has(out, "\"i2c_status\":5}"));
    assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h3\"}"), "\"nfc_ok\":false,\"nfc_polling\":false,\"nfc_firmware\":838927879,\"nfc_i2c_status\":5,"));
    heldLow.clear();
    heldLow[3] = -1;  // SCL held: nothing to clock
    out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b3\"}");
    assert(has(out, "\"sda_before\":1,\"scl_before\":0,\"sda_after\":1,\"scl_after\":0,\"pulses\":0}"));
    assert(has(out, "\"bus_clear\":false,\"ready\":false,"));
    heldLow.clear();
    out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b4\"}");
    assert(has(out, "\"pulses\":0}") && has(out, "\"bus_clear\":true,\"ready\":true,\"firmware\":838927879,\"i2c_status\":0}"));
  }
  // bare_dongle_degrades: no reader wired, every command still answers and the radio still works.
  pn532Present = false;
  out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b5\"}");
  assert(has(out, "{\"event\":\"nfc_recovered\",\"id\":\"b5\",\"bus_clear\":true,\"ready\":false,\"firmware\":0,\"i2c_status\":5}"));
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h4\"}"), "\"nfc_ok\":false,\"nfc_polling\":false,\"nfc_firmware\":0,\"nfc_i2c_status\":5,\"tag_present\":false,"));
  out = serial("{\"cmd\":\"nfc_poll\",\"id\":\"n6\",\"enabled\":1}");
  assert(has(out, "{\"event\":\"nfc_poll_result\",\"id\":\"n6\",\"ready\":false,\"enabled\":true,"));
  out = serial("{\"cmd\":\"nfc_status\",\"id\":\"n7\"}");
  assert(has(out, "\"i2c_status\":5,\"status_source\":\"firmware_response\",\"firmware_now\":0,\"nfc_polling\":true,"));
  assert(has(serial("{\"cmd\":\"discover\",\"id\":\"d3\"}"), "{\"event\":\"discover_sent\",\"id\":\"d3\"}"));
  assert(!has(serial("{\"cmd\":\"nfc_status\",\"id\":\"n8\"}"), "No NFC reader"));
  pn532Present = true;
  out = serial("{\"cmd\":\"nfc_recover\",\"id\":\"b6\"}");
  assert(has(out, "\"bus_clear\":true,\"ready\":true,\"firmware\":838927879,\"i2c_status\":0}"));
  // reader_lost_supervision: a reader that stops answering is reported once and dropped; because a
  // host asked for polling it is brought back automatically (the plates' 5 s retry).
  serial("{\"cmd\":\"nfc_poll\",\"id\":\"n9\",\"enabled\":true}");
  pn532Present = false;
  out = hold(1500);
  assert(has(out, "{\"event\":\"nfc_error\",\"id\":\"\",\"detail\":\"PN532 lost: ") && count(out, "nfc_error") == 1 && !nfc::ok);
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"nfc_ok\":false,\"nfc_polling\":true,"));
  pn532Present = true;
  {
    uint32_t recoveries = nfc::recoveries;
    out = hold(5100);
    assert(nfc::ok && nfc::recoveries == recoveries + 1 && has(out, "\"event\":\"nfc_bus\"") && !has(out, "nfc_error"));
  }
  assert(has(serial("{\"cmd\":\"status\",\"id\":\"s\"}"), "\"nfc_ok\":true,\"nfc_polling\":true,\"nfc_firmware\":838927879,\"nfc_i2c_status\":0,"));
  // trace_gating: `trace` switches the I2C transaction trace on. The trace body lives in the ESP32
  // Pn532Wire (status-0 lines and a starved USB port are skipped there), which the host cannot run.
  serial("{\"cmd\":\"nfc_poll\",\"id\":\"n10\",\"enabled\":true,\"trace\":1}");
  assert(pn532TraceAll && has(serial("{\"cmd\":\"nfc_status\",\"id\":\"n11\"}"), "\"trace\":true}"));
  serial("{\"cmd\":\"nfc_poll\",\"id\":\"n12\",\"enabled\":true,\"trace\":0}");
  assert(!pn532TraceAll && has(serial("{\"cmd\":\"nfc_status\",\"id\":\"n13\"}"), "\"trace\":false}"));
  // serial_backpressure: a port nobody drains still drops zone replies (counted) while the reader
  // polls with a tag on it; nothing blocks.
  presentedTag = {4, 1, 2, 3};
  hold(100);
  serialTxSpace = 100;
  {
    uint32_t dropped = rxZoneDropped;
    radioFrom(ZONE1, (const uint8_t *)&status, sizeof(status), false);
    hold(100);
    assert(rxZoneDropped == dropped + 1 && nfc::tagPresent);
  }
  serialTxSpace = 4096;
  presentedTag.clear();
  serial("{\"cmd\":\"nfc_poll\",\"id\":\"n14\",\"enabled\":false}");
  hold(800);

  // ---- Radio failure is reported, not hidden ----
  ping();
  autoSendCallback = false;
  out = serial("{\"cmd\":\"set_zone\",\"id\":\"f1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":0}", 700);
  assert(has(out, "\"status\":\"no_result\""));
  assert(has(out, "\"event\":\"fatal\"") && !radioOk);
  assert(has(serial("{\"cmd\":\"discover\",\"id\":\"f2\"}"), "Radio unavailable"));
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"f3\"}"), "\"radio_ok\":false"));

  puts("Workstation OK");
  return 0;
}
