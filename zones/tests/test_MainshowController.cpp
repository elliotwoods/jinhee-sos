// Real sketch: the SET_ZONE and SHOW_START packets a cube must see (built from the shared
// NctCubeProtocol.h), the showId rules the cube relies on, the lockout, and the physical inputs.
#include "zone_stubs.h"
#include "../firmware/MainshowController/MainshowController.ino"
#include "sketch_common.h"

static const uint8_t CUBE44[6] = {0xAC, 0x27, 0x6E, 0x80, 0x00, 0xD0};

static Packet packetOf(const SentFrame &frame) {
  assert(frame.data.size() == sizeof(Packet) && sizeof(Packet) == 24);
  Packet p;
  memcpy(&p, frame.data.data(), sizeof(p));
  return p;
}

static std::vector<Packet> showStarts(size_t from) {
  std::vector<Packet> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    Packet p = packetOf(sentFrames[i]);
    if (p.type == MSG_SHOW_START) out.push_back(p);
  }
  return out;
}

// Hold an input at a level for `ms`, running the sketch meanwhile.
static std::string hold(int pin, int level, uint32_t ms) {
  Serial.output.clear();
  pinLevels[pin] = level;
  run(ms);
  return Serial.output;
}

int main() {
  setup();

  // ---- Init ----
  assert(radioReady && radioChannel == 2);
  assert(!wifiSleep && !wifiPersistent && !wifiAutoReconnect);
  assert(esp_now_is_peer_exist(BROADCAST) && espPeers.size() == 1);
  // The banner is what zone_detect.py identifies this board by, and the image must not
  // contain a legacy entrance-plate signature that would be matched first.
  assert(has(Serial.output, "NCT MAINSHOW CONTROLLER") && has(Serial.output, "FW: mainshow-1.1.0"));
  assert(!has(Serial.output, "MAINSHOW ENTRANCE") && !has(Serial.output, "Cube READY"));
  assert(has(Serial.output, "{\"event\":\"hello\",\"id\":\"\",\"firmware\":\"mainshow-1.1.0\""));
  assert(sentFrames.empty() && "nothing is sent until asked");

  // ---- Host protocol ----
  std::string out = serial("{\"cmd\":\"hello\",\"id\":\"h1\"}");
  assert(has(out, "\"event\":\"hello\",\"id\":\"h1\"") && has(out, "\"channel\":2") && has(out, "\"radio_ok\":true"));
  assert(has(out, "\"button_pin\":9") && has(out, "\"trigger_pin\":3") && has(out, "\"lockout_ms\":3000") && has(out, "\"rearm_ms\":1000"));
  assert(has(serial("{\"cmd\": \"ping\", \"id\": \"p1\"}"), "{\"event\":\"pong\",\"id\":\"p1\"}"));  // spaced JSON too
  assert(has(serial("{\"cmd\":\"ping\"}"), "Missing/invalid request id"));
  assert(has(serial("{\"cmd\":\"dance\",\"id\":\"x\"}"), "Unknown command"));
  assert(has(serial("hello"), "one JSON object per line"));
  assert(has(serial("?"), "NCT MAINSHOW CONTROLLER\nFW: mainshow-1.1.0\nMAC: 02:AA:BB:CC:DD:EE\nCHANNEL: 2"));

  // ---- Mainshow ready: one unicast SET_ZONE 4 ----
  size_t before = sentFrames.size();
  out = serial("{\"cmd\":\"set_zone\",\"id\":\"z1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4}");
  assert(sentFrames.size() == before + 1);
  assert(!memcmp(sentFrames.back().dest.data(), CUBE44, 6));
  Packet zone = packetOf(sentFrames.back());
  assert(zone.type == MSG_SET_ZONE && zone.type == 6 && zone.success == nctzone::ZONE_MAINSHOW && zone.success == 4);
  assert(has(out, "{\"event\":\"zone_sent\",\"id\":\"z1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4,\"status\":\"delivered\"}"));
  assert(espPeers.size() == 1 && "the cube's temporary peer is removed again");
  sendDelivered = false;
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"z2\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":0}"), "\"status\":\"unconfirmed\""));
  sendDelivered = true;
  before = sentFrames.size();
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"z3\",\"mac\":\"FF:FF:FF:FF:FF:FF\",\"zone\":4}"), "unicast MAC"));
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"z4\",\"mac\":\"AC:27:6E:80:00\",\"zone\":4}"), "unicast MAC"));
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"z5\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":5}"), "Zone must be 0-4"));
  assert(has(serial("{\"cmd\":\"set_zone\",\"id\":\"z6\",\"mac\":\"AC:27:6E:80:00:D0\"}"), "Zone must be 0-4"));
  assert(sentFrames.size() == before && "rejected commands send nothing");

  // ---- Trigger for one cube: 5 unicast SHOW_START (type 8), one showId ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"s1\",\"target\":\"AC:27:6E:80:00:D0\"}", 400);
  auto first = showStarts(before);
  assert(first.size() == 5 && sentFrames.size() == before + 5);
  for (size_t i = before; i < sentFrames.size(); i++) assert(!memcmp(sentFrames[i].dest.data(), CUBE44, 6));
  for (auto &p : first) assert(p.type == 8 && p.cubeID == first[0].cubeID && p.success == 0);
  assert(first[0].cubeID != 0 && first[0].cubeID == lastShowId);
  char expect[160];
  snprintf(expect, sizeof(expect), "\"source\":\"usb\",\"show_id\":%lu,\"target\":\"AC:27:6E:80:00:D0\",\"sent\":5,\"repeats\":5,\"delivered\":5",
           (unsigned long)lastShowId);
  assert(has(out, expect));
  assert(espPeers.size() == 1);

  // ---- Lockout: a second trigger inside 3 s is refused and sends nothing ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"s2\",\"target\":\"broadcast\"}");
  assert(has(out, "{\"event\":\"locked\",\"id\":\"s2\",\"source\":\"usb\",\"retry_ms\":"));
  assert(sentFrames.size() == before);
  run(3000);

  // ---- Broadcast: a fresh showId, no delivered count (broadcasts are never acknowledged) ----
  uint32_t previous = lastShowId;
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"s3\",\"target\":\"broadcast\"}", 400);
  auto second = showStarts(before);
  assert(second.size() == 5 && second[0].cubeID != previous && second[0].cubeID != 0);
  for (size_t i = before; i < sentFrames.size(); i++) assert(!memcmp(sentFrames[i].dest.data(), BROADCAST, 6));
  assert(has(out, "\"target\":\"broadcast\",\"sent\":5,\"repeats\":5}") && !has(out, "delivered"));
  assert(has(serial("{\"cmd\":\"show_start\",\"id\":\"s4\"}"), "needs a target"));
  assert(has(serial("{\"cmd\":\"show_start\",\"id\":\"s5\",\"target\":\"everyone\"}"), "unicast MAC"));
  run(3000);

  // ---- Physical inputs: debounce, press not release, broadcast, held low fires once ----
  before = sentFrames.size();
  hold(TRIGGER_PIN, LOW, 20);  // a 20 ms glitch is not a press
  hold(TRIGGER_PIN, HIGH, 100);
  assert(sentFrames.size() == before);
  out = hold(TRIGGER_PIN, LOW, 400);
  auto pinShow = showStarts(before);
  assert(pinShow.size() == 5 && !memcmp(sentFrames.back().dest.data(), BROADCAST, 6));
  assert(has(out, "{\"event\":\"show_start\",\"id\":\"\",\"source\":\"pin\""));
  // The show wiring holds the input low for the whole show (~10 min): still only the one trigger,
  // nothing sent and nothing printed while it is held.
  before = sentFrames.size();
  out = hold(TRIGGER_PIN, LOW, 10 * 60 * 1000);
  assert(sentFrames.size() == before && out.empty());
  // Dropouts in the held signal, well past the lockout: a sub-debounce blip is invisible, and a
  // longer one (up to the 1 s re-arm) is reported as ignored instead of restarting the show.
  out = hold(TRIGGER_PIN, HIGH, 30);
  out += hold(TRIGGER_PIN, LOW, 500);
  assert(sentFrames.size() == before && out.empty());
  for (uint32_t gap : {60u, 400u, 940u}) {
    hold(TRIGGER_PIN, HIGH, gap);
    out = hold(TRIGGER_PIN, LOW, 4000);
    assert(sentFrames.size() == before && "a dropout shorter than the re-arm time must not restart the show");
    char expect[80];
    snprintf(expect, sizeof(expect), "{\"event\":\"ignored\",\"id\":\"\",\"source\":\"pin\",\"open_ms\":%u,", gap);
    assert(has(out, expect) && has(out, "\"rearm_ms\":1000}"));
  }
  // The contact bounces as it opens: neither the release nor the bounce is a trigger.
  for (int i = 0; i < 5; i++) { hold(TRIGGER_PIN, HIGH, 3); hold(TRIGGER_PIN, LOW, 4); }
  out = hold(TRIGGER_PIN, HIGH, 1000);  // open for the full re-arm time
  assert(sentFrames.size() == before && out.empty());
  // The next show's closure starts the next show, with a new showId.
  uint32_t held = lastShowId;
  out = hold(TRIGGER_PIN, LOW, 400);
  assert(showStarts(before).size() == 5 && lastShowId != held && has(out, "\"source\":\"pin\""));
  hold(TRIGGER_PIN, HIGH, 3100);  // released, and past the lockout for the button tests below
  before = sentFrames.size();

  out = hold(BUTTON_PIN, LOW, 400);
  assert(has(out, "\"source\":\"button\"") && showStarts(before).size() == 5);
  hold(BUTTON_PIN, HIGH, 100);
  before = sentFrames.size();
  out = hold(BUTTON_PIN, LOW, 200);  // a second press inside the lockout
  assert(has(out, "{\"event\":\"locked\",\"id\":\"\",\"source\":\"button\"") && sentFrames.size() == before);
  hold(BUTTON_PIN, HIGH, 100);

  // ---- An input held low at power-on does not fire ----
  pinLevels[TRIGGER_PIN] = LOW;
  run(4000);
  inputs[1].stable = inputs[1].raw = HIGH;  // forget the state, as a fresh boot would
  esp_now_del_peer(BROADCAST);
  setup();
  before = sentFrames.size();
  run(500);
  assert(sentFrames.size() == before);
  pinLevels[TRIGGER_PIN] = HIGH;

  puts("PASS: MainshowController sends SET_ZONE/SHOW_START (type 8, fresh showId x5), locks out, and debounces its inputs");
  return 0;
}
