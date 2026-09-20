// USB test bridge for the pool central controller. Emulates all six radios; no sensor
// required. Speaks the same NctPoolProtocol link as the real PoolZone radios: it listens
// for the central's beacon, unicasts its state, and keeps a periodic broadcast copy going.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdlib.h>
#include <string.h>
#include <NctPoolProtocol.h>

using namespace nctzone;

constexpr uint32_t USB_TIMEOUT_MS = 1500;
constexpr uint8_t BROADCAST_MAC[6] = {255,255,255,255,255,255};
uint8_t centralMac[6] = {255,255,255,255,255,255};
bool centralKnown = false;
uint32_t centralSeen = 0, centralEpoch = 0;
uint8_t centralMask = 0;
uint8_t members[POOL_RADIO_COUNT] = {};
uint32_t bootId[POOL_RADIO_COUNT] = {};
uint16_t sequence[POOL_RADIO_COUNT] = {};
uint8_t channel = ESPNOW_CHANNEL, nextRadio = 0;
bool ready = false, armed = false;
uint32_t lastHost = 0, lastSend = 0, lastStatus = 0, lastBroadcast = 0, queued = 0, errors = 0;
char input[96];
size_t used = 0;
bool overflow = false;

bool centralFresh() { return centralKnown && millis() - centralSeen < POOL_BEACON_STALE_MS; }

void status() {
  Serial.printf("{\"device\":\"PoolRadioTest\",\"version\":2,\"ready\":%s,\"channel\":%u,\"armed\":%s,\"mac\":\"%s\",\"queued\":%lu,\"errors\":%lu,\"members\":[%u,%u,%u,%u,%u,%u],\"unicast\":%s,\"beacon_ms\":%lu,\"radio_mask\":%u,\"central_mac\":\"%02X:%02X:%02X:%02X:%02X:%02X\"}\n",
    ready ? "true" : "false", channel, armed ? "true" : "false", WiFi.macAddress().c_str(),
    (unsigned long)queued, (unsigned long)errors, members[0],members[1],members[2],members[3],members[4],members[5],
    centralFresh() ? "true" : "false", (unsigned long)(centralKnown ? millis()-centralSeen : 0), centralMask,
    centralMac[0],centralMac[1],centralMac[2],centralMac[3],centralMac[4],centralMac[5]);
}

// Wi-Fi task: copy the beacon out and return.
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (poolFrameType(data, length) != POOL_BEACON) return;
  PoolBeacon beacon;
  memcpy(&beacon, data, sizeof(beacon));
  memcpy(centralMac, info->src_addr, 6);
  centralKnown = true;
  centralSeen = millis();
  centralEpoch = beacon.epoch;
  centralMask = beacon.radioMask;
}

void sendSlot(uint8_t index, bool forceBroadcast) {
  PoolState packet = {};
  fillHeader(packet.h, POOL_STATE);
  packet.bootId = bootId[index];
  packet.seq = ++sequence[index];
  packet.leaseMs = POOL_LEASE_DEFAULT_MS;
  packet.radioId = uint8_t(index + 1);
  packet.member = members[index];
  packet.active = packet.member != 0;
  const uint8_t *destination = (!forceBroadcast && centralFresh()) ? centralMac : BROADCAST_MAC;
  if (!forceBroadcast && centralFresh() && !esp_now_is_peer_exist(centralMac)) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, centralMac, 6);
    peer.channel = 0; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) destination = BROADCAST_MAC;
  }
  if (esp_now_send(destination, (uint8_t *)&packet, sizeof(packet)) == ESP_OK) ++queued;
  else ++errors;
}

bool setChannel(uint8_t value) {
  if (esp_wifi_set_channel(value, WIFI_SECOND_CHAN_NONE) != ESP_OK) return false;
  // A peer channel of zero follows the interface's channel.
  channel = value;
  return true;
}

void command(char *line) {
  if (!strcmp(line, "STATUS")) { status(); return; }
  if (!strcmp(line, "PING")) { lastHost = millis(); return; }
  if (!strcmp(line, "OFF")) {
    memset(members, 0, sizeof(members)); armed = false; status(); return;
  }
  const bool isSet = !strncmp(line, "SET ", 4);
  const bool isChannel = !strncmp(line, "CHANNEL ", 8);
  if (!isSet && !isChannel) { Serial.println("ERR unknown command"); return; }
  long values[6] = {};
  char *cursor = line + (isSet ? 4 : 8);
  const int count = isSet ? 6 : 1;
  for (int i=0; i<count; ++i) {
    while (*cursor == ' ') ++cursor;
    char *end;
    values[i] = strtol(cursor, &end, 10);
    if (end == cursor || values[i] < (isSet ? 0 : 1) || values[i] > (isSet ? POOL_MEMBER_COUNT : 13)) {
      Serial.println("ERR invalid range or argument count"); return;
    }
    cursor = end;
  }
  while (*cursor == ' ') ++cursor;
  if (*cursor) { Serial.println("ERR trailing arguments"); return; }
  if (isChannel) {
    for (uint8_t m : members) if (m) { Serial.println("ERR turn all lights off before channel change"); return; }
    if (!ready || !setChannel(values[0])) { Serial.println("ERR channel change failed"); return; }
  } else {
    if (!ready) { Serial.println("ERR radio unavailable"); return; }
    for (int i=0; i<POOL_RADIO_COUNT; ++i) members[i] = uint8_t(values[i]);
    lastHost = millis(); armed = true;
  }
  status();
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  ready = setChannel(ESPNOW_CHANNEL) && esp_now_init() == ESP_OK;
  if (ready) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = 0; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
    ready = esp_now_add_peer(&peer) == ESP_OK && esp_now_register_recv_cb(onReceive) == ESP_OK;
  }
  // Each emulated radio gets its own boot identity, as six separate boards would.
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) {
    bootId[i] = esp_random() | 1u;
    sequence[i] = 0;
  }
  status();
}

void loop() {
  // Bounded processing keeps heartbeat/watchdog running under serial input load.
  for (int n=0; n<128 && Serial.available(); ++n) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflow) Serial.println("ERR line too long");
      else { input[used] = 0; command(input); }
      used = 0; overflow = false;
    } else if (used < sizeof(input)-1) input[used++] = c;
    else overflow = true;
  }
  uint32_t now = millis();
  if (armed && now-lastHost > USB_TIMEOUT_MS) {
    memset(members, 0, sizeof(members)); armed = false;
    Serial.println("EVENT USB watchdog: all off"); status();
  }
  // One packet per 25ms: each radio slot keeps its 150ms heartbeat.
  if (ready && now-lastSend >= 25) {
    lastSend = now;
    sendSlot(nextRadio, false);
    nextRadio = (nextRadio+1)%POOL_RADIO_COUNT;
  }
  // A broadcast copy of one slot periodically, matching what the real radios do.
  if (ready && centralFresh() && now-lastBroadcast >= POOL_BROADCAST_COPY_MS/POOL_RADIO_COUNT) {
    lastBroadcast = now;
    sendSlot(nextRadio, true);
  }
  if (now-lastStatus >= 1000) { lastStatus = now; status(); }
  delay(1);
}
