// NCT IMMERSIVE DEEP - MAINSHOW CONTROLLER
//
// Starts the cubes' main-show timeline. Replaces live files/ShowStarter_M5Stack_Core2, which
// broadcast MSG_SHOW_START as 7: cube firmware v1.4.x moved it to 8 (7 is MSG_TAG_STATE), so
// cubes silently ignored the Core2.
//
// What a cube does (flashing_station/firmware/neocore_usb, frozen): a MSG_SET_ZONE with
// ZONE_MAINSHOW makes it "mainshow ready" (neon). A MSG_SHOW_START, carrying a showId in
// Packet.cubeID, starts its local ~5 minute timeline only if it is ready; a repeated showId
// is ignored. So every trigger here uses a fresh showId and sends it SHOW_REPEATS times,
// exactly like the Core2 did.
//
// Triggers:
//   - USB: JSON lines at 115200 (zones/mainshow/app.py), one object per line each way;
//   - the BOOT button (GPIO9) and the trigger input (XIAO D1 = GPIO3), both active low with a
//     pull-up. Physical triggers always broadcast, like the real show, and work with no
//     computer attached. An input must be released before it can trigger again; the trigger
//     input must have been open for TRIGGER_REARM_MS, so a dropout in a held signal is ignored.
// All triggers share one lockout so a bouncing contact or a double press cannot restart the
// show a moment after it began.
//
// ESP-NOW channel 2. Not a zone board: no PN532, no zcfg/zdb partitions, not a zone-flasher
// target. The banner below is what zones/flasher/zone_detect.py identifies this board by.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <Adafruit_NeoPixel.h>
#include <NctCubeProtocol.h>
#include <NctZoneProtocol.h>

constexpr const char *FIRMWARE_VERSION = "mainshow-1.2.0";
constexpr const char *BANNER = "NCT MAINSHOW CONTROLLER";
constexpr uint8_t CHANNEL = nctzone::ESPNOW_CHANNEL;
constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

constexpr int BUTTON_PIN = 9;   // XIAO ESP32-C3 BOOT button (a strapping pin: only matters at power-on)
constexpr int TRIGGER_PIN = 3;  // XIAO D1; pull to GND to trigger
constexpr uint32_t DEBOUNCE_MS = 50;
// The show wiring holds the trigger input low for the whole show. A dropout in that signal must not
// restart the show when it returns, so the input has to have been open this long before a closure
// counts as a new trigger. Shorter openings are reported as `ignored`.
constexpr uint32_t TRIGGER_REARM_MS = 1000;
constexpr uint32_t LOCKOUT_MS = 3000;     // the Core2's SHOW_LOCK_MS
constexpr int SHOW_REPEATS = 5;           // the Core2's burst: 5 sends, 30 ms apart
constexpr uint32_t SHOW_REPEAT_GAP_MS = 30;
constexpr uint32_t SEND_WAIT_MS = 100;    // wait for the MAC-layer result of one send

// Status on the ex-cube's eight WS2812s (XIAO D10 = GPIO10): a faint red light scrolls while waiting
// for a show start, a strong green one while the show runs. The controller hears nothing back from
// the cubes, so "running" means within SHOW_LENGTH_MS of the last trigger: the length of the cube's
// timeline (updateMainShowTimeline() in flashing_station/firmware/neocore_usb). `led_test` replaces
// the status with a colour cycle, a bench check that every pixel and channel is alive.
constexpr int LED_PIN = 10;
constexpr int LED_COUNT = 8;
constexpr uint32_t SHOW_LENGTH_MS = 298000;
constexpr uint8_t WAIT_LEVEL = 12, RUN_LEVEL = 100;  // the cube caps its LEDs at 100 of 255
constexpr uint32_t WAIT_PIXEL_MS = 180, RUN_PIXEL_MS = 60;  // scroll speed: time to move one pixel
constexpr uint32_t SCROLL_TAIL = 3;                        // pixels of fading tail behind the head
constexpr uint32_t LED_FRAME_MS = 20;
constexpr uint8_t LED_LEVEL = 60;          // led_test
constexpr uint32_t LED_COLOUR_MS = 1000, LED_CHASE_MS = 250;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
bool ledTest = false;
uint32_t ledStep = 0, ledStepAt = 0, ledFrameAt = 0;

bool radioReady = false;
volatile int sendStatus = -1;  // -1 pending, else esp_now_send_status_t (set on the Wi-Fi task)
uint32_t lastShowId = 0, lastTriggerAt = 0, shows = 0;
bool triggered = false;

struct Input {
  int pin;
  const char *name;
  uint32_t rearmMs;  // how long the input must have been open before a closure triggers
  int stable, raw;
  uint32_t changedAt, openedAt;
};
Input inputs[] = {{BUTTON_PIN, "button", 0, HIGH, HIGH, 0, 0}, {TRIGGER_PIN, "pin", TRIGGER_REARM_MS, HIGH, HIGH, 0, 0}};

enum SendResult { SEND_REJECTED, SEND_DELIVERED, SEND_UNCONFIRMED, SEND_NO_RESULT };
const char *const SEND_TEXT[] = {"rejected", "delivered", "unconfirmed", "no_result"};

// Runs on the Wi-Fi task: record the result, nothing else.
void onSent(const esp_now_send_info_t *, esp_now_send_status_t status) { sendStatus = int(status); }

void formatMac(const uint8_t *mac, char *out) {
  snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

bool parseMac(const char *text, uint8_t *mac) {
  if (strlen(text) != 17) return false;
  for (int i = 0; i < 6; i++) {
    char a = text[i * 3], b = text[i * 3 + 1];
    if (!isxdigit((unsigned char)a) || !isxdigit((unsigned char)b) || (i < 5 && text[i * 3 + 2] != ':')) return false;
    char pair[3] = {a, b, 0};
    mac[i] = uint8_t(strtoul(pair, nullptr, 16));
  }
  return true;
}

// ---- Minimal JSON for flat request objects: {"cmd":"...","id":"...","mac":"...","zone":4} ----
// Values are plain strings (no escapes) or unsigned integers; that is all the host sends.
const char *jsonValue(const char *line, const char *key) {
  char quoted[24];
  int n = snprintf(quoted, sizeof(quoted), "\"%s\"", key);
  if (n <= 0 || n >= int(sizeof(quoted))) return nullptr;
  for (const char *at = strstr(line, quoted); at; at = strstr(at + 1, quoted)) {
    const char *p = at + n;
    while (*p == ' ') p++;
    if (*p != ':') continue;  // the key text appeared as a value
    p++;
    while (*p == ' ') p++;
    return p;
  }
  return nullptr;
}

bool jsonString(const char *line, const char *key, char *out, size_t capacity) {
  const char *p = jsonValue(line, key);
  if (!p || *p != '"') return false;
  p++;
  size_t used = 0;
  while (*p && *p != '"') {
    if (*p == '\\' || *p < 0x20 || used + 1 >= capacity) return false;
    out[used++] = *p++;
  }
  if (*p != '"') return false;
  out[used] = 0;
  return true;
}

bool jsonUint(const char *line, const char *key, uint32_t &out) {
  const char *p = jsonValue(line, key);
  if (!p || !isdigit((unsigned char)*p)) return false;
  char *end = nullptr;
  unsigned long value = strtoul(p, &end, 10);
  if (end == p || value > 0xFFFFFFFFul) return false;
  out = uint32_t(value);
  return true;
}

// Replies go to the host as one JSON object per line. `id` is echoed ("" when unsolicited).
void reply(const char *event, const char *id, const char *fields = "") {
  Serial.printf("{\"event\":\"%s\",\"id\":\"%s\"%s%s}\n", event, id, *fields ? "," : "", fields);
}

void error(const char *id, const char *detail) {
  char fields[160];
  snprintf(fields, sizeof(fields), "\"detail\":\"%s\"", detail);
  reply("error", id, fields);
}

// One packet to one address, waiting briefly for the MAC-layer result. A delivered unicast
// means the cube's radio acknowledged the frame, not that the cube acted on it; a broadcast
// is never acknowledged at all.
SendResult sendPacket(const uint8_t *mac, const Packet &packet) {
  if (!radioReady) return SEND_REJECTED;
  bool broadcast = !memcmp(mac, BROADCAST_MAC, 6);
  bool temporary = !broadcast && !esp_now_is_peer_exist(mac);
  if (temporary) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, mac, 6);
    peer.channel = CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) return SEND_REJECTED;
  }
  sendStatus = -1;
  SendResult result = SEND_REJECTED;
  if (esp_now_send(mac, (const uint8_t *)&packet, sizeof(packet)) == ESP_OK) {
    uint32_t started = millis();
    while (sendStatus < 0 && uint32_t(millis() - started) < SEND_WAIT_MS) delay(1);
    int status = sendStatus;
    result = status < 0 ? SEND_NO_RESULT : status == ESP_NOW_SEND_SUCCESS ? SEND_DELIVERED : SEND_UNCONFIRMED;
  }
  if (temporary && esp_now_is_peer_exist(mac)) esp_now_del_peer(mac);
  return result;
}

void setZone(const char *id, const uint8_t *mac, uint8_t zone) {
  Packet packet = {};
  packet.type = MSG_SET_ZONE;
  packet.success = zone;
  SendResult result = sendPacket(mac, packet);
  char text[18], fields[120];
  formatMac(mac, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"zone\":%u,\"status\":\"%s\"", text, zone, SEND_TEXT[result]);
  reply("zone_sent", id, fields);
}

// One step of the test cycle: red, green, blue, white (whole strip, 1 s each), then each pixel
// alone in white (250 ms each), so a dead colour channel or a dead pixel is visible by eye.
void showLedStep(uint32_t step) {
  pixels.clear();
  const uint8_t L = LED_LEVEL;
  static const uint8_t COLOURS[4][3] = {{L, 0, 0}, {0, L, 0}, {0, 0, L}, {L, L, L}};
  if (step < 4) {
    for (int i = 0; i < LED_COUNT; i++) pixels.setPixelColor(i, COLOURS[step][0], COLOURS[step][1], COLOURS[step][2]);
  } else {
    pixels.setPixelColor(int(step - 4), L, L, L);
  }
  pixels.show();
}

bool showRunning(uint32_t now) { return triggered && uint32_t(now - lastTriggerAt) < SHOW_LENGTH_MS; }

// A head moving round the ring with a fading tail, positioned in 1/256 pixel steps so it glides.
void drawScroll(uint32_t now, uint8_t red, uint8_t green, uint32_t pixelMs) {
  const uint32_t ring = LED_COUNT * 256, tail = SCROLL_TAIL * 256;
  uint32_t head = uint32_t((uint64_t(now) * 256 / pixelMs) % ring);
  for (int i = 0; i < LED_COUNT; i++) {
    uint32_t behind = (head + ring - uint32_t(i) * 256) % ring;  // how far this pixel trails the head
    uint32_t scale = behind < tail ? tail - behind : 0;
    pixels.setPixelColor(i, uint8_t(red * scale / tail), uint8_t(green * scale / tail), 0);
  }
  pixels.show();
}

void pollLeds() {
  uint32_t now = millis();
  if (!ledTest) {
    if (uint32_t(now - ledFrameAt) < LED_FRAME_MS) return;
    ledFrameAt = now;
    if (showRunning(now)) drawScroll(now, 0, RUN_LEVEL, RUN_PIXEL_MS);
    else drawScroll(now, WAIT_LEVEL, 0, WAIT_PIXEL_MS);
    return;
  }
  uint32_t hold = ledStep < 4 ? LED_COLOUR_MS : LED_CHASE_MS;
  if (uint32_t(now - ledStepAt) < hold) return;
  ledStep = (ledStep + 1) % (4 + LED_COUNT);
  ledStepAt = now;
  showLedStep(ledStep);
}

void setLedTest(bool on) {
  ledTest = on;
  ledStep = 0;
  ledStepAt = millis();
  ledFrameAt = 0;
  if (on) showLedStep(0);  // off: the status scroll resumes on the next frame
}

uint32_t newShowId() {
  uint32_t id;
  do id = esp_random(); while (id == 0 || id == lastShowId);
  return id;
}

// Every trigger source ends up here. Returns false (and says so) inside the lockout.
bool startShow(const char *id, const char *source, const uint8_t *mac) {
  uint32_t now = millis();
  if (triggered && uint32_t(now - lastTriggerAt) < LOCKOUT_MS) {
    char fields[80];
    snprintf(fields, sizeof(fields), "\"source\":\"%s\",\"retry_ms\":%lu", source,
             (unsigned long)(LOCKOUT_MS - uint32_t(now - lastTriggerAt)));
    reply("locked", id, fields);
    return false;
  }
  triggered = true;
  lastTriggerAt = now;
  lastShowId = newShowId();
  shows++;
  Packet packet = {};
  packet.type = MSG_SHOW_START;
  packet.cubeID = lastShowId;  // the cube reads the showId from this field
  bool broadcast = !memcmp(mac, BROADCAST_MAC, 6);
  int sent = 0, delivered = 0;
  for (int i = 0; i < SHOW_REPEATS; i++) {
    if (i) delay(SHOW_REPEAT_GAP_MS);
    SendResult result = sendPacket(mac, packet);
    if (result != SEND_REJECTED) sent++;
    if (result == SEND_DELIVERED) delivered++;
  }
  char text[18], fields[200];
  if (broadcast) strcpy(text, "broadcast");
  else formatMac(mac, text);
  int n = snprintf(fields, sizeof(fields), "\"source\":\"%s\",\"show_id\":%lu,\"target\":\"%s\",\"sent\":%d,\"repeats\":%d",
                   source, (unsigned long)lastShowId, text, sent, SHOW_REPEATS);
  if (!broadcast && n > 0 && n < int(sizeof(fields))) snprintf(fields + n, sizeof(fields) - n, ",\"delivered\":%d", delivered);
  reply("show_start", id, fields);
  return true;
}

void hello(const char *id) {
  char fields[400];
  snprintf(fields, sizeof(fields),
           "\"firmware\":\"%s\",\"mac\":\"%s\",\"channel\":%d,\"radio_ok\":%s,\"button_pin\":%d,\"trigger_pin\":%d,"
           "\"lockout_ms\":%lu,\"rearm_ms\":%lu,\"last_show_id\":%lu,\"shows\":%lu,\"led_pin\":%d,\"led_test\":%s,\"show_running\":%s,\"show_length_ms\":%lu",
           FIRMWARE_VERSION, WiFi.macAddress().c_str(), int(WiFi.channel()), radioReady ? "true" : "false", BUTTON_PIN,
           TRIGGER_PIN, (unsigned long)LOCKOUT_MS, (unsigned long)TRIGGER_REARM_MS, (unsigned long)lastShowId, (unsigned long)shows, LED_PIN,
           ledTest ? "true" : "false", showRunning(millis()) ? "true" : "false", (unsigned long)SHOW_LENGTH_MS);
  reply("hello", id, fields);
}

// Plain-text "?" report, the convention every board here answers (zone_detect reads it).
void report() {
  Serial.printf("%s\nFW: %s\nMAC: %s\nCHANNEL: %d\nRADIO: %s\nREADY\n", BANNER, FIRMWARE_VERSION,
                WiFi.macAddress().c_str(), int(WiFi.channel()), radioReady ? "OK" : "FAILED");
}

void command(char *line) {
  if (!strcmp(line, "?")) { report(); return; }
  char id[41] = "", cmd[24] = "", target[24] = "";
  if (line[0] != '{') { error("", "Send one JSON object per line, or ? for the report"); return; }
  if (!jsonString(line, "id", id, sizeof(id)) || !id[0]) { error("", "Missing/invalid request id"); return; }
  if (!jsonString(line, "cmd", cmd, sizeof(cmd))) { error(id, "Missing cmd"); return; }
  if (!strcmp(cmd, "ping")) { reply("pong", id); return; }
  if (!strcmp(cmd, "hello")) { hello(id); return; }
  if (!strcmp(cmd, "led_test")) {
    uint32_t on;
    if (!jsonUint(line, "on", on) || on > 1) { error(id, "led_test needs on: 1 or 0"); return; }
    setLedTest(on);
    char fields[40];
    snprintf(fields, sizeof(fields), "\"on\":%s,\"pin\":%d", on ? "true" : "false", LED_PIN);
    reply("led_test", id, fields);
    return;
  }
  if (!radioReady) { error(id, "Radio unavailable; reset the controller"); return; }
  if (!strcmp(cmd, "set_zone")) {
    uint8_t mac[6];
    uint32_t zone;
    if (!jsonString(line, "mac", target, sizeof(target)) || !parseMac(target, mac) || (mac[0] & 1)) {
      error(id, "set_zone needs one cube's unicast MAC"); return;
    }
    if (!jsonUint(line, "zone", zone) || zone > nctzone::ZONE_MAINSHOW) { error(id, "Zone must be 0-4"); return; }
    setZone(id, mac, uint8_t(zone));
    return;
  }
  if (!strcmp(cmd, "show_start")) {
    uint8_t mac[6];
    if (!jsonString(line, "target", target, sizeof(target))) { error(id, "show_start needs a target"); return; }
    if (!strcmp(target, "broadcast")) memcpy(mac, BROADCAST_MAC, 6);
    else if (!parseMac(target, mac) || (mac[0] & 1)) { error(id, "Target must be \\\"broadcast\\\" or a unicast MAC"); return; }
    startShow(id, "usb", mac);
    return;
  }
  error(id, "Unknown command");
}

void pollInputs() {
  uint32_t now = millis();
  for (Input &in : inputs) {
    int level = digitalRead(in.pin);
    if (level != in.raw) { in.raw = level; in.changedAt = now; }
    if (in.raw != in.stable && uint32_t(now - in.changedAt) >= DEBOUNCE_MS) {
      in.stable = in.raw;
      if (in.stable == HIGH) { in.openedAt = in.changedAt; continue; }  // a release is never a trigger
      uint32_t open = uint32_t(in.changedAt - in.openedAt);  // from the release to this closure
      if (open >= in.rearmMs) {
        startShow("", in.name, BROADCAST_MAC);
      } else {
        char fields[80];
        snprintf(fields, sizeof(fields), "\"source\":\"%s\",\"open_ms\":%lu,\"rearm_ms\":%lu", in.name,
                 (unsigned long)open, (unsigned long)in.rearmMs);
        reply("ignored", "", fields);
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  pixels.begin();
  pixels.clear();
  pixels.show();  // WS2812s keep their last colour through a reflash: clear it before the status scroll
  for (Input &in : inputs) {
    pinMode(in.pin, INPUT_PULLUP);
    // Start from the current level, so an input already held low at boot does not fire.
    in.stable = in.raw = digitalRead(in.pin);
    in.changedAt = in.openedAt = millis();  // open at boot counts from now
  }
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  radioReady = WiFi.mode(WIFI_STA) && WiFi.disconnect() && WiFi.setSleep(false) &&
               esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK && esp_now_init() == ESP_OK &&
               esp_now_register_send_cb(onSent) == ESP_OK;
  if (radioReady) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    radioReady = esp_now_add_peer(&peer) == ESP_OK;
  }
  report();
  hello("");
}

void loop() {
  static char line[256];
  static size_t used = 0;
  static bool overflow = false;
  for (int count = 0; count < 512 && Serial.available(); count++) {
    char c = Serial.read();
    if (c == '\n') {
      if (overflow) error("", "Command too long");
      else if (used) { line[used] = 0; command(line); }
      used = 0;
      overflow = false;
    } else if (c != '\r' && !overflow) {
      if (used < sizeof(line) - 1) line[used++] = c;
      else overflow = true;
    }
  }
  pollInputs();
  pollLeds();
  delay(1);
}
