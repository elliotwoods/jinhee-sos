// NCT IMMERSIVE DEEP - GENERAL RADIO
//
// One USB dongle for every ESP-NOW host function in the installation, driven by one JSON
// object per line at 115200 (zones/tools/general_radio.py). A strict superset of the
// pairing-station relay protocol (pairing_station/firmware/pairing_station), so the pairing
// app and the Zone Database Manager drive it unchanged, plus the Mainshow controller's verbs
// (zones/mainshow), an emulated pool slider radio (as poolzone_test's bridge) and an emulated
// preshow plate for the TouchDesigner media bridge:
//
//   cube     discover / identify / register (pairing station), set_zone to one cube or, spelled
//            out, to all cubes (MSG_SET_ZONE 0 idle, 1 preshow, 2 desert, 3 pool, 4 mainshow-
//            ready), show_start (MSG_SHOW_START, fresh showId x5). GrCube.h
//   zone     zone_send relay of zone-management frames built by the host, zone_frame for the
//            replies (status/log/settings), as the pairing station. Below.
//   pool     pool{member}: hold one pool lamp through the pool central. GrPool.h
//   preshow  preshow{point,state}: a TouchDesigner cue through the media bridge. GrPreshow.h
//   show     show_send relay of main-show frames built by the host (pairing_station/show_registry.py:
//            SHOW_ANNOUNCE/CHUNK/QUERY to cube firmware v1.5.0+), show_frame for the cubes'
//            SHOW_STATUS replies; show_config/show_stop and the show timecode. Below and GrCube.h.
//
// No NFC reader: hello reports nfc_ok:false and the nfc_* commands answer with an error, which
// is how the pairing app already treats a bare dongle. Not a zone board: no PN532, no
// zcfg/zdb partitions, not a zone-flasher target; the banner below is what
// zones/flasher/zone_detect.py refuses it by. The desert light panel is driven by the desert
// plate's own reader only; the cube-side half of a desert tap is set_zone 2.
//
// Every radio operation needs a hello or ping within HOST_GATE_MS, as the station requires.
// Pool and preshow outputs are leased on the same heartbeat: a host that stops talking has its
// lamp released and its cue turned OFF, so an unplugged laptop cannot leave the show changed.
// ESP-NOW channel 2, no encryption. The BOOT button does nothing.
#include <Arduino.h>
#include <string.h>
#include <stdio.h>
#include "GrHex.h"
#include "GrJson.h"
#include "GrRadio.h"
#include "GrCube.h"
#include "GrPool.h"
#include "GrPreshow.h"
#include "GrLeds.h"

using namespace gr;

constexpr const char *FIRMWARE_VERSION = "general-radio-1.1.0";  // 1.1: show relay + timecode
constexpr const char *BANNER = "NCT GENERAL RADIO";
constexpr uint32_t HOST_GATE_MS = 5000;  // the pairing station's HEARTBEAT_TIMEOUT
constexpr size_t LINE_CAPACITY = 1024;   // zone chunk lines are ~540 chars

uint32_t lastHost = 0;
bool hostEver = false;
uint32_t rxZone = 0, rxZoneDropped = 0, serialOverflows = 0, rxShow = 0, rxShowDropped = 0;

bool hostFresh(uint32_t now) { return hostEver && uint32_t(now - lastHost) <= HOST_GATE_MS; }

void touchHost(uint32_t now) {
  lastHost = now;
  hostEver = true;
  pool::touch(now);
  preshow::touch(now);
}

// Plain-text "?" report, the convention every board here answers (zone_detect reads it).
void report() {
  Serial.printf("%s\nFW: %s\nMAC: %s\nCHANNEL: %d\nRADIO: %s\nREADY\n", BANNER, FIRMWARE_VERSION,
                WiFi.macAddress().c_str(), int(WiFi.channel()), radioOk ? "OK" : "FAILED");
}

// hello (and status, the same body without side effects): the pairing station's fields first,
// so hosts that check protocol/zones/channel/radio_ok/nfc_ok see what they expect, then this
// board's roles. Written in pieces: the whole line is longer than one printf buffer.
void helloLine(const char *event, const char *id) {
  uint32_t now = millis();
  char fields[400];
  Serial.printf("{\"event\":\"%s\",\"id\":\"%s\",\"protocol\":1,\"firmware\":\"%s\",\"zones\":%u,\"show\":1,\"mac\":\"%s\",\"channel\":%d,"
                "\"radio_ok\":%s,\"nfc_ok\":false,\"nfc_polling\":false,\"tag_present\":false,"
                "\"roles\":[\"cube\",\"zone\",\"pool\",\"preshow\"],\"led_pin\":%d,\"led_test\":%s,\"host_fresh\":%s,",
                event, id, FIRMWARE_VERSION, unsigned(nctzone::PROTO), WiFi.macAddress().c_str(), int(WiFi.channel()),
                boolText(radioOk), leds::LED_PIN, boolText(leds::ledTest), boolText(hostFresh(now)));
  cube::helloFields(fields, sizeof(fields), now);
  Serial.printf("%s,\"tx\":{\"sent\":%lu,\"delivered\":%lu,\"unconfirmed\":%lu,\"no_result\":%lu,\"rejected\":%lu},"
                "\"rx\":{\"zone\":%lu,\"zone_dropped\":%lu,\"show\":%lu,\"show_dropped\":%lu,\"serial_overflows\":%lu},",
                fields, (unsigned long)txSent, (unsigned long)txDelivered, (unsigned long)txUnconfirmed, (unsigned long)txNoResult,
                (unsigned long)txRejected, (unsigned long)rxZone, (unsigned long)rxZoneDropped, (unsigned long)rxShow,
                (unsigned long)rxShowDropped, (unsigned long)serialOverflows);
  pool::stateFields(fields, sizeof(fields), now);
  Serial.printf("\"pool\":{%s},", fields);
  preshow::stateFields(fields, sizeof(fields), now);
  Serial.printf("\"preshow\":{%s}}\n", fields);
}

// Zone-management frames are built by the host (zones/tools/zonedb.py); this only validates and
// relays, with the pairing station's rules: the kinds a registry may send, and identify/reboot/
// set-config to one zone only.
void zoneSend(const char *id, const char *line) {
  static char hex[2 * 250 + 1];
  char macText[24];
  uint8_t mac[6], frame[250];
  if (!jsonString(line, "hex", hex, sizeof(hex))) { error(id, "Invalid zone frame"); return; }
  int length = parsePlainHex(hex, frame, sizeof(frame));
  uint8_t kind = length > 0 ? nctzone::frameType(frame, length) : 0;
  bool haveMac = jsonString(line, "mac", macText, sizeof(macText)) && parseMac(macText, mac);
  bool broadcast = haveMac && isBroadcast(mac);
  if (!haveMac || (isMulticast(mac) && !broadcast)) { error(id, "Invalid zone MAC"); return; }
  if (kind != nctzone::DB_ANNOUNCE && kind != nctzone::DB_CHUNK && kind != nctzone::ZONE_QUERY &&
      kind != nctzone::ZONE_IDENTIFY && kind != nctzone::ZONE_REBOOT && kind != nctzone::ZONE_SET_CONFIG) {
    error(id, "Invalid zone frame"); return;
  }
  if (broadcast && (kind == nctzone::ZONE_IDENTIFY || kind == nctzone::ZONE_REBOOT || kind == nctzone::ZONE_SET_CONFIG)) {
    error(id, "Identify/reboot/set-config must target one zone"); return;
  }
  SendResult result = sendFrame(mac, frame, size_t(length));
  char text[18], fields[80];
  formatMac(mac, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"kind\":%u,\"status\":\"%s\"", text, kind, SEND_TEXT[result]);
  reply("zone_sent", id, fields);
}

// Replies from zones (status, log, settings) go up as the station relays them; a registry's
// own announce/chunk/query traffic heard from another dongle is dropped.
void pollZoneQueue() {
  static char hex[2 * 250 + 1];
  ZoneRx z;
  for (int count = 0; count < 16 && zoneQueue && xQueueReceive(zoneQueue, &z, 0) == pdTRUE; count++) {
    uint8_t kind = nctzone::frameType(z.data, z.length);
    if (kind != nctzone::ZONE_STATUS && kind != nctzone::ZONE_LOG && kind != nctzone::ZONE_SETTINGS) continue;
    ++rxZone;
    if (Serial.availableForWrite() < int(2 * z.length + 80)) { ++rxZoneDropped; continue; }  // nobody is draining USB
    char text[18];
    formatMac(z.sender, text);
    plainHex(z.data, z.length, hex);
    Serial.printf("{\"event\":\"zone_frame\",\"id\":\"\",\"mac\":\"%s\",\"kind\":%u", text, kind);
    if (z.rssi) Serial.printf(",\"rssi\":%d", int(z.rssi));
    Serial.print(",\"hex\":\"");
    Serial.print(hex);
    Serial.print("\"}\n");
  }
}

// Main-show frames are built by the host (pairing_station/showfile.py); this only validates and
// relays what a show registry may send. Only a v1.5.0+ cube acts on them; older cubes drop them.
void showSend(const char *id, const char *line) {
  static char hex[2 * sizeof(nctshow::ShowChunk) + 1];
  char macText[24];
  uint8_t mac[6], frame[sizeof(nctshow::ShowChunk)];
  if (!jsonString(line, "hex", hex, sizeof(hex))) { error(id, "Invalid show frame"); return; }
  int length = parsePlainHex(hex, frame, sizeof(frame));
  uint8_t kind = length > 0 ? nctshow::frameType(frame, length) : 0;
  bool haveMac = jsonString(line, "mac", macText, sizeof(macText)) && parseMac(macText, mac);
  if (!haveMac || (isMulticast(mac) && !isBroadcast(mac))) { error(id, "Invalid show MAC"); return; }
  if (kind != nctshow::SHOW_ANNOUNCE && kind != nctshow::SHOW_CHUNK && kind != nctshow::SHOW_QUERY) {
    error(id, "Invalid show frame"); return;
  }
  SendResult result = sendFrame(mac, frame, size_t(length));
  char text[18], fields[80];
  formatMac(mac, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"kind\":%u,\"status\":\"%s\"", text, kind, SEND_TEXT[result]);
  reply("show_sent", id, fields);
}

// A cube's SHOW_STATUS goes up as show_frame (the zone_frame convention).
void pollShowQueue() {
  static char hex[2 * sizeof(nctshow::ShowStatus) + 1];
  ShowRx s;
  for (int count = 0; count < 16 && showQueue && xQueueReceive(showQueue, &s, 0) == pdTRUE; count++) {
    ++rxShow;
    if (Serial.availableForWrite() < int(2 * sizeof(s.data) + 80)) { ++rxShowDropped; continue; }
    char text[18];
    formatMac(s.sender, text);
    plainHex(s.data, sizeof(s.data), hex);
    Serial.printf("{\"event\":\"show_frame\",\"id\":\"\",\"mac\":\"%s\",\"kind\":%u", text, unsigned(nctshow::SHOW_STATUS));
    if (s.rssi) Serial.printf(",\"rssi\":%d", int(s.rssi));
    Serial.print(",\"hex\":\"");
    Serial.print(hex);
    Serial.print("\"}\n");
  }
}

void command(char *line) {
  if (!strcmp(line, "?")) { report(); return; }
  char id[41] = "", cmd[24] = "", macText[24] = "";
  if (line[0] != '{') { error("", "Send one JSON object per line, or ? for the report"); return; }
  if (!jsonString(line, "id", id, sizeof(id)) || !id[0]) { error("", "Missing/invalid request id"); return; }
  if (!jsonString(line, "cmd", cmd, sizeof(cmd))) { error(id, "Missing cmd"); return; }
  uint32_t now = millis();
  if (!strcmp(cmd, "ping")) { touchHost(now); reply("pong", id); return; }
  if (!strcmp(cmd, "hello")) { cube::stop(); touchHost(now); helloLine("hello", id); return; }
  if (!strcmp(cmd, "status")) { helloLine("status", id); return; }
  if (!strcmp(cmd, "stop")) { cube::stop(); reply("stopped", id); return; }
  if (!strncmp(cmd, "nfc_", 4)) { error(id, "No NFC reader on this radio"); return; }
  if (!strcmp(cmd, "led_test")) {
    bool on;
    if (!jsonBool(line, "on", on)) { error(id, "led_test needs on: 1 or 0"); return; }
    leds::setTest(on);
    char fields[40];
    snprintf(fields, sizeof(fields), "\"on\":%s,\"pin\":%d", boolText(on), leds::LED_PIN);
    reply("led_test", id, fields);
    return;
  }
  if (!radioOk) { error(id, "Radio unavailable; reboot the radio"); return; }
  if (!hostFresh(now)) { error(id, "Send hello/ping before operating"); return; }
  if (!strcmp(cmd, "discover")) { cube::discover(id); return; }
  if (!strcmp(cmd, "zone_send")) { zoneSend(id, line); return; }
  if (!strcmp(cmd, "show_send")) { showSend(id, line); return; }
  if (!strcmp(cmd, "show_config")) { cube::showConfig(id, line); return; }
  if (!strcmp(cmd, "show_stop")) { cube::showStop(id); return; }
  if (!strcmp(cmd, "pool")) { pool::command(id, line); return; }
  if (!strcmp(cmd, "preshow")) { preshow::command(id, line); return; }
  if (!strcmp(cmd, "show_start")) {
    uint8_t mac[6];
    if (!jsonString(line, "target", macText, sizeof(macText))) { error(id, "show_start needs a target"); return; }
    if (!strcmp(macText, "broadcast")) memcpy(mac, BROADCAST_MAC, 6);
    else if (!parseMac(macText, mac) || isMulticast(mac)) { error(id, "Target must be \\\"broadcast\\\" or a unicast MAC"); return; }
    cube::startShow(id, mac);
    return;
  }
  if (!strcmp(cmd, "set_zone")) {
    uint8_t mac[6];
    uint32_t zone;
    bool haveMac = jsonString(line, "mac", macText, sizeof(macText));
    if (haveMac && !strcmp(macText, "broadcast")) memcpy(mac, BROADCAST_MAC, 6);
    else if (!haveMac || !parseMac(macText, mac) || isMulticast(mac)) { error(id, "set_zone needs one cube's unicast MAC, or \\\"broadcast\\\" for every cube in range"); return; }
    if (!jsonUint(line, "zone", zone) || zone > nctzone::ZONE_MAINSHOW) { error(id, "Zone must be 0-4"); return; }
    cube::setZone(id, mac, uint8_t(zone));
    return;
  }
  // The pairing station's cube operations: one unicast MAC each.
  uint8_t mac[6];
  if (!jsonString(line, "mac", macText, sizeof(macText)) || !parseMac(macText, mac) || isMulticast(mac)) {
    error(id, !strcmp(cmd, "identify") || !strcmp(cmd, "register") ? "Invalid unicast MAC" : "Unknown command"); return;
  }
  if (!strcmp(cmd, "identify")) { cube::identify(id, mac, line); return; }
  if (!strcmp(cmd, "register")) { cube::registerCube(id, mac, line); return; }
  error(id, "Unknown command");
}

void setup() {
  // Zone chunk lines are ~540 chars; the host paces relays one line at a time. A short write
  // timeout, so a USB port nobody is draining cannot stall the radio work.
  Serial.setRxBufferSize(4096);
  Serial.setTxBufferSize(4096);
  Serial.setTxTimeoutMs(8);
  Serial.begin(115200);
  leds::begin();
  beginRadio();
  pool::begin();
  preshow::begin();
  report();
  helloLine("hello", "");
}

void loop() {
  static char line[LINE_CAPACITY];
  static size_t used = 0;
  static bool overflow = false;
  for (int count = 0; count < 4096 && Serial.available(); count++) {
    char c = Serial.read();
    if (c == '\n') {
      if (overflow) { ++serialOverflows; error("", "Serial command too long"); }
      else if (used) { line[used] = 0; command(line); }
      used = 0;
      overflow = false;
    } else if (c != '\r' && !overflow) {
      if (used < sizeof(line) - 1) line[used++] = c;
      else overflow = true;
    }
  }
  uint32_t now = millis();
  if (cube::active && !hostFresh(now)) cube::hostLost();
  // The driver stopped calling back (see GrRadio.h): every role's sends are refused from here
  // on, so say so once, the way the pairing station does. Only a reboot clears it.
  static bool fatalReported = false;
  if (!radioOk && !fatalReported) { fatalReported = true; reply("fatal", "", "\"detail\":\"Radio completion timeout; reboot the radio\""); }
  pollZoneQueue();
  pollShowQueue();
  cube::poll(now);
  pool::poll(now);
  preshow::poll(now);
  leds::poll(now, hostFresh(now), cube::showRunning(now));
  delay(1);
}
