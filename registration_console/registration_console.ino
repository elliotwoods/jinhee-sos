// Screenless replacement for the M5 registration console.
// Arduino-ESP32 3.3.11; no NFC/display libraries or router required.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <stddef.h>
#include "CubeTable.h"

constexpr uint8_t CHANNEL = 2;
constexpr uint8_t MSG_REGISTER = 3, MSG_REGISTER_ACK = 4, MSG_SET_ZONE = 6;
constexpr uint8_t ZONE_IDLE = 0, ZONE_MAINSHOW = 4;
// Do not pack: ForKimchi transmits this native layout, including padding.
struct Packet {
  uint8_t type;
  uint32_t cubeID;
  uint8_t mac[6];
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t success;
};
static_assert(sizeof(Packet) == 24 && offsetof(Packet, type) == 0 &&
              offsetof(Packet, cubeID) == 4 && offsetof(Packet, mac) == 8 &&
              offsetof(Packet, uidLength) == 14 && offsetof(Packet, uid) == 15 &&
              offsetof(Packet, success) == 22, "Cube packet ABI mismatch");
static_assert(CUBE_COUNT == 32, "Expected the original 32 mappings");
struct Received { Packet packet; uint8_t sender[6]; };
QueueHandle_t rxQueue, txQueue;
bool radioReady = false;
enum Mode { NONE, REGISTER, TEST };
enum Phase { BEGIN_CUBE, WAIT_ACK, PAUSE, LIGHT_ON };
Mode mode = NONE;
Phase phase = BEGIN_CUBE;
int current = 0, last = 0, attempts = 0;
uint32_t since = 0;
// 0 = not completed, 1 = acknowledged, 2 = unconfirmed, 3 = light test sent.
uint8_t results[CUBE_COUNT] = {};

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(Packet) || data[0] != MSG_REGISTER_ACK) return;
  Received r;
  memcpy(&r.packet, data, sizeof(Packet));
  memcpy(r.sender, info->src_addr, 6);
  xQueueSend(rxQueue, &r, 0);
}
void onSent(const esp_now_send_info_t *, esp_now_send_status_t status) {
  xQueueSend(txQueue, &status, 0);
}
void printBytes(const uint8_t *p, int length) {
  for (int i = 0; i < length; ++i) Serial.printf(i ? ":%02X" : "%02X", p[i]);
}
bool validTable() {
  for (int i = 0; i < CUBE_COUNT; ++i) {
    const auto &a = cubeTable[i];
    if (!a.cubeID || !a.uidLength || a.uidLength > 7 || (a.mac[0] & 1)) return false;
    for (int j = 0; j < i; ++j) {
      const auto &b = cubeTable[j];
      if (a.cubeID == b.cubeID || !memcmp(a.mac, b.mac, 6) ||
          (a.uidLength == b.uidLength && !memcmp(a.uid, b.uid, a.uidLength))) return false;
    }
  }
  return true;
}
void help() {
  Serial.println("\nlist | register all | register N | test all | test N | stop | help");
  Serial.println("N is cube ID 1..32. End commands with newline (115200 baud).");
  Serial.println("Registration rewrites cube ID/UID; green blink confirms processing.");
  Serial.println("Test: neon for 2 seconds, then dim idle. This interrupts a running show.");
}
void list() {
  Serial.println("CubeID,MAC,NFC");
  for (const auto &cube : cubeTable) {
    Serial.printf("%lu,", (unsigned long)cube.cubeID);
    printBytes(cube.mac, 6); Serial.print(',');
    printBytes(cube.uid, cube.uidLength); Serial.println();
  }
}
bool addPeer() {
  const auto &cube = cubeTable[current];
  if (esp_now_is_peer_exist(cube.mac)) return true;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, cube.mac, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_err_t err = esp_now_add_peer(&peer);
  if (err != ESP_OK) Serial.printf("Peer error: %s\n", esp_err_to_name(err));
  return err == ESP_OK;
}
void removePeer() {
  // A callback timeout disables radio use: keep the peer until reboot.
  if (radioReady && esp_now_is_peer_exist(cubeTable[current].mac)) {
    esp_now_del_peer(cubeTable[current].mac);
  }
}
bool sendPacket(const Packet &packet) {
  if (!radioReady || !addPeer()) return false;
  esp_err_t err = esp_now_send(cubeTable[current].mac,
                              reinterpret_cast<const uint8_t *>(&packet), sizeof(packet));
  if (err != ESP_OK) {
    Serial.printf("Send rejected: %s\n", esp_err_to_name(err));
    return false;
  }
  // Wait for radio completion before deleting a peer or sending another packet.
  // Callbacks only enqueue data; all logging and application work is here.
  esp_now_send_status_t status;
  if (xQueueReceive(txQueue, &status, pdMS_TO_TICKS(500)) != pdTRUE) {
    radioReady = false;
    Serial.println("RADIO CALLBACK TIMEOUT: reboot console before another operation.");
    return false;
  }
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Radio delivery OK" : "Radio delivery unconfirmed");
  return true; // Accepted for transmission, not an application acknowledgment.
}
void registerAttempt() {
  Packet p = {};
  p.type = MSG_REGISTER;
  p.cubeID = cubeTable[current].cubeID;
  p.uidLength = cubeTable[current].uidLength;
  memcpy(p.uid, cubeTable[current].uid, p.uidLength);
  // p.mac intentionally stays zero, as in the original M5 registration packet.
  ++attempts;
  Serial.printf("REGISTER Cube #%lu attempt %d/3\n", (unsigned long)p.cubeID, attempts);
  sendPacket(p);
  since = millis();
  phase = WAIT_ACK;
}
bool sendZone(uint8_t zone) {
  Packet p = {};
  p.type = MSG_SET_ZONE;
  p.cubeID = cubeTable[current].cubeID;
  p.success = zone;
  bool sent = sendPacket(p);
  Serial.printf("Cube #%lu zone %u: %s (no cube zone ACK)\n",
                (unsigned long)p.cubeID, zone, sent ? "sent" : "send failed");
  return sent;
}
void summary() {
  Serial.println("--- Sequence results ---");
  for (int i = 0; i < CUBE_COUNT; ++i) {
    if (!results[i]) continue;
    Serial.printf("Cube #%lu: %s\n", (unsigned long)cubeTable[i].cubeID,
                  results[i] == 1 ? "registration acknowledged" :
                  results[i] == 2 ? "unconfirmed" : "light commands sent; observe cube");
  }
  Serial.println("IDLE. Registration ACK does not verify flash persistence.");
}
void finishCube() {
  removePeer();
  if (current == last) { summary(); mode = NONE; }
  else { ++current; phase = BEGIN_CUBE; }
}
void stop() {
  if (mode == NONE) { Serial.println("Already idle."); return; }
  if (mode == TEST && phase == LIGHT_ON && !sendZone(ZONE_IDLE)) results[current] = 2;
  if (mode == REGISTER && phase == WAIT_ACK) results[current] = 2;
  removePeer();
  mode = NONE;
  Serial.println("Stopped. Already transmitted registrations cannot be undone.");
  summary();
}
void tick() {
  if (mode == NONE) return;
  if (!radioReady) {
    results[current] = 2;
    mode = NONE;
    Serial.println("Sequence aborted due to radio fault; active light may remain on.");
    summary();
    return;
  }
  if (phase == BEGIN_CUBE) {
    xQueueReset(rxQueue);
    attempts = 0;
    if (mode == REGISTER) registerAttempt();
    else {
      results[current] = sendZone(ZONE_MAINSHOW) ? 3 : 2;
      since = millis(); phase = LIGHT_ON;
    }
    return;
  }
  if (phase == WAIT_ACK) {
    Received r;
    while (xQueueReceive(rxQueue, &r, 0) == pdTRUE) {
      if (r.packet.type == MSG_REGISTER_ACK && r.packet.success == 1 &&
          r.packet.cubeID == cubeTable[current].cubeID &&
          !memcmp(r.sender, cubeTable[current].mac, 6) &&
          !memcmp(r.packet.mac, cubeTable[current].mac, 6)) {
        results[current] = 1;
        Serial.printf("ACK Cube #%lu; waiting for green blink\n", (unsigned long)r.packet.cubeID);
        since = millis(); phase = PAUSE;
        return;
      }
    }
    if (uint32_t(millis() - since) >= 2000) {
      if (attempts < 3) registerAttempt();
      else {
        results[current] = 2;
        Serial.printf("UNCONFIRMED Cube #%lu\n", (unsigned long)cubeTable[current].cubeID);
        finishCube();
      }
    }
  } else if (phase == PAUSE && uint32_t(millis() - since) >= 1000) {
    finishCube();
  } else if (phase == LIGHT_ON && uint32_t(millis() - since) >= 2000) {
    if (!sendZone(ZONE_IDLE)) results[current] = 2;
    finishCube();
  }
}
void command(char *line) {
  char *verb = strtok(line, " \t");
  if (!verb) return;
  char *arg = strtok(nullptr, " \t");
  char *extra = strtok(nullptr, " \t");
  if (!strcmp(verb, "help") && !arg) { help(); return; }
  if (!strcmp(verb, "list") && !arg) { list(); return; }
  if (!strcmp(verb, "stop") && !arg) { stop(); return; }
  if ((strcmp(verb, "register") && strcmp(verb, "test")) || !arg || extra) {
    Serial.println("Invalid command. Type help."); return;
  }
  if (mode != NONE) { Serial.println("Busy. Use stop before starting another sequence."); return; }
  if (!radioReady) { Serial.println("Radio/table unavailable. Reboot and check startup log."); return; }
  int first = 0, end = CUBE_COUNT - 1;
  if (strcmp(arg, "all")) {
    for (const char *p = arg; *p; ++p) {
      if (*p < '0' || *p > '9') { Serial.println("Invalid cube ID."); return; }
    }
    char *tail;
    unsigned long id = strtoul(arg, &tail, 10);
    first = -1;
    for (int i = 0; i < CUBE_COUNT; ++i) if (cubeTable[i].cubeID == id) first = i;
    if (first < 0) { Serial.println("Unknown cube ID; use list."); return; }
    end = first;
  }
  memset(results, 0, sizeof(results));
  current = first; last = end;
  mode = !strcmp(verb, "register") ? REGISTER : TEST;
  phase = BEGIN_CUBE;
}
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nNCT screenless registration console v1.0 / fixed channel 2");
  help();
  if (!validTable()) { Serial.println("INVALID MAPPING TABLE"); return; }
  rxQueue = xQueueCreate(8, sizeof(Received));
  txQueue = xQueueCreate(1, sizeof(esp_now_send_status_t));
  if (!rxQueue || !txQueue) { Serial.println("QUEUE ALLOCATION FAILED"); return; }
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  if (!WiFi.mode(WIFI_STA) || !WiFi.disconnect()) { Serial.println("WIFI INIT FAILED"); return; }
  delay(100);
  if (!WiFi.setSleep(false) ||
      esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) != ESP_OK ||
      esp_now_init() != ESP_OK ||
      esp_now_register_recv_cb(onReceive) != ESP_OK ||
      esp_now_register_send_cb(onSent) != ESP_OK) {
    Serial.println("RADIO INIT FAILED"); return;
  }
  radioReady = true;
  Serial.printf("Ready: %s / channel %u / %d mappings. Waiting for command.\n",
                WiFi.macAddress().c_str(), WiFi.channel(), CUBE_COUNT);
}
void loop() {
  static char line[64];
  static size_t used = 0;
  static bool overflow = false;
  // Bound work so continuous input cannot starve the sequence.
  for (int n = 0; n < 64 && Serial.available(); ++n) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (overflow) Serial.println("Command too long; discarded.");
      else { line[used] = 0; command(line); }
      used = 0; overflow = false;
    } else if (!overflow) {
      if (used < sizeof(line) - 1) line[used++] = c;
      else overflow = true;
    }
  }
  tick();
  delay(2);
}
