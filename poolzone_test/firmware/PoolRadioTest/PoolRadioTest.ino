// USB test bridge for the legacy Poolzone central controller. No sensor required.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdlib.h>
#include <string.h>

struct __attribute__((packed)) RadioPacket {
  uint32_t magic;
  uint8_t radioId, active, member, uidLength, uid[7];
};
static_assert(sizeof(RadioPacket) == 15, "Central controller wire format changed");
constexpr uint32_t MAGIC = 0x4E435450;
constexpr uint32_t USB_TIMEOUT_MS = 1500;
uint8_t destination[6] = {255,255,255,255,255,255};
uint8_t members[6] = {};
uint8_t channel = 2, nextRadio = 0;
bool ready = false, armed = false;
uint32_t lastHost = 0, lastSend = 0, lastStatus = 0, queued = 0, errors = 0;
char input[96];
size_t used = 0;
bool overflow = false;

void status() {
  Serial.printf("{\"device\":\"PoolRadioTest\",\"version\":1,\"ready\":%s,\"channel\":%u,\"armed\":%s,\"mac\":\"%s\",\"queued\":%lu,\"errors\":%lu,\"members\":[%u,%u,%u,%u,%u,%u]}\n",
    ready ? "true" : "false", channel, armed ? "true" : "false", WiFi.macAddress().c_str(),
    (unsigned long)queued, (unsigned long)errors, members[0],members[1],members[2],members[3],members[4],members[5]);
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
    if (end == cursor || values[i] < (isSet ? 0 : 1) || values[i] > (isSet ? 23 : 13)) {
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
    for (int i=0; i<6; ++i) members[i] = values[i];
    lastHost = millis(); armed = true;
  }
  status();
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  ready = setChannel(2) && esp_now_init() == ESP_OK;
  if (ready) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, destination, 6);
    peer.channel = 0; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
    ready = esp_now_add_peer(&peer) == ESP_OK;
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
  // One packet per 25ms: each radio slot receives its original 150ms heartbeat.
  if (ready && now-lastSend >= 25) {
    lastSend = now;
    RadioPacket packet = {};
    packet.magic = MAGIC; packet.radioId = nextRadio+1;
    packet.member = members[nextRadio]; packet.active = packet.member != 0;
    if (esp_now_send(destination, (uint8_t*)&packet, sizeof(packet)) == ESP_OK) ++queued;
    else ++errors;
    nextRadio = (nextRadio+1)%6;
  }
  if (now-lastStatus >= 1000) { lastStatus = now; status(); }
  delay(1);
}
