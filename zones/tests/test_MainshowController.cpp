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

// Cube Packets (24 bytes) sent since `from`; SHOW_TIMECODE frames (20 bytes) are counted apart.
static size_t packetsSince(size_t from) {
  size_t n = 0;
  for (size_t i = from; i < sentFrames.size(); i++) n += sentFrames[i].data.size() == sizeof(Packet);
  return n;
}

static std::vector<nctshow::ShowTimecode> timecodesSince(size_t from) {
  std::vector<nctshow::ShowTimecode> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    const auto &f = sentFrames[i];
    if (nctshow::frameType(f.data.data(), int(f.data.size())) != nctshow::SHOW_TIMECODE) continue;
    nctshow::ShowTimecode tc;
    memcpy(&tc, f.data.data(), sizeof tc);
    out.push_back(tc);
  }
  return out;
}

static std::vector<Packet> showStarts(size_t from) {
  std::vector<Packet> out;
  for (size_t i = from; i < sentFrames.size(); i++) {
    if (sentFrames[i].data.size() != sizeof(Packet)) continue;
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
  assert(has(Serial.output, "NCT MAINSHOW CONTROLLER") && has(Serial.output, "FW: mainshow-1.3.0"));
  assert(!has(Serial.output, "MAINSHOW ENTRANCE") && !has(Serial.output, "Cube READY"));
  assert(has(Serial.output, "{\"event\":\"hello\",\"id\":\"\",\"firmware\":\"mainshow-1.3.0\""));
  assert(sentFrames.empty() && "nothing is sent until asked");

  // ---- Host protocol ----
  std::string out = serial("{\"cmd\":\"hello\",\"id\":\"h1\"}");
  assert(has(out, "\"event\":\"hello\",\"id\":\"h1\"") && has(out, "\"channel\":2") && has(out, "\"radio_ok\":true"));
  assert(has(out, "\"button_pin\":9") && has(out, "\"trigger_pin\":3") && has(out, "\"lockout_ms\":3000") && has(out, "\"rearm_ms\":1000"));
  assert(has(serial("{\"cmd\": \"ping\", \"id\": \"p1\"}"), "{\"event\":\"pong\",\"id\":\"p1\"}"));  // spaced JSON too
  assert(has(serial("{\"cmd\":\"ping\"}"), "Missing/invalid request id"));
  assert(has(serial("{\"cmd\":\"dance\",\"id\":\"x\"}"), "Unknown command"));
  assert(has(serial("hello"), "one JSON object per line"));
  assert(has(serial("?"), "NCT MAINSHOW CONTROLLER\nFW: mainshow-1.3.0\nMAC: 02:AA:BB:CC:DD:EE\nCHANNEL: 2"));

  // ---- Mainshow ready: one unicast SET_ZONE 4 ----
  size_t before = sentFrames.size();
  out = serial("{\"cmd\":\"set_zone\",\"id\":\"z1\",\"mac\":\"AC:27:6E:80:00:D0\",\"zone\":4}");
  assert(packetsSince(before) == 1);
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
  assert(packetsSince(before) == 0 && "rejected commands send nothing");

  // ---- Trigger for one cube: 5 unicast SHOW_START (type 8), one showId ----
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"s1\",\"target\":\"AC:27:6E:80:00:D0\"}", 400);
  auto first = showStarts(before);
  assert(first.size() == 5 && packetsSince(before) == 5);
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
  assert(packetsSince(before) == 0);
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
  assert(packetsSince(before) == 0);
  out = hold(TRIGGER_PIN, LOW, 400);
  auto pinShow = showStarts(before);
  assert(pinShow.size() == 5 && !memcmp(sentFrames.back().dest.data(), BROADCAST, 6));
  assert(has(out, "{\"event\":\"show_start\",\"id\":\"\",\"source\":\"pin\""));
  // The show wiring holds the input low for the whole show (~10 min): still only the one trigger,
  // nothing sent and nothing printed while it is held.
  before = sentFrames.size();
  out = hold(TRIGGER_PIN, LOW, 10 * 60 * 1000);
  assert(packetsSince(before) == 0 && out.empty());
  // Dropouts in the held signal, well past the lockout: a sub-debounce blip is invisible, and a
  // longer one (up to the 1 s re-arm) is reported as ignored instead of restarting the show.
  out = hold(TRIGGER_PIN, HIGH, 30);
  out += hold(TRIGGER_PIN, LOW, 500);
  assert(packetsSince(before) == 0 && out.empty());
  for (uint32_t gap : {60u, 400u, 940u}) {
    hold(TRIGGER_PIN, HIGH, gap);
    out = hold(TRIGGER_PIN, LOW, 4000);
    assert(packetsSince(before) == 0 && "a dropout shorter than the re-arm time must not restart the show");
    char expect[80];
    snprintf(expect, sizeof(expect), "{\"event\":\"ignored\",\"id\":\"\",\"source\":\"pin\",\"open_ms\":%u,", gap);
    assert(has(out, expect) && has(out, "\"rearm_ms\":1000}"));
  }
  // The contact bounces as it opens: neither the release nor the bounce is a trigger.
  for (int i = 0; i < 5; i++) { hold(TRIGGER_PIN, HIGH, 3); hold(TRIGGER_PIN, LOW, 4); }
  out = hold(TRIGGER_PIN, HIGH, 1000);  // open for the full re-arm time
  assert(packetsSince(before) == 0 && out.empty());
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
  assert(has(out, "{\"event\":\"locked\",\"id\":\"\",\"source\":\"button\"") && packetsSince(before) == 0);
  hold(BUTTON_PIN, HIGH, 100);

  // ---- An input held low at power-on does not fire ----
  pinLevels[TRIGGER_PIN] = LOW;
  run(4000);
  inputs[1].stable = inputs[1].raw = HIGH;  // forget the state, as a fresh boot would
  esp_now_del_peer(BROADCAST);
  setup();
  before = sentFrames.size();
  run(500);
  assert(packetsSince(before) == 0);
  pinLevels[TRIGGER_PIN] = HIGH;

  // ---- Status LEDs on the ex-cube strip (D10) ----
  auto channel = [](uint32_t c, int shift) { return (c >> shift) & 0xFF; };
  // Waiting: a faint red head scrolls round the ring; no green or blue.
  auto frameCheck = [&](uint32_t maxRed, uint32_t maxGreen) {
    uint32_t brightest = 0;
    for (uint32_t c : neoShown) {
      assert(channel(c, 16) <= maxRed && channel(c, 8) <= maxGreen && channel(c, 0) == 0);
      brightest = std::max(brightest, std::max(channel(c, 16), channel(c, 8)));
    }
    return brightest;
  };
  auto brightestPixel = [&]() {
    int best = 0;
    for (int i = 1; i < 8; i++)
      if ((neoShown[i] & 0xFFFF00) > (neoShown[best] & 0xFFFF00)) best = i;
    return best;
  };
  // Long after the last trigger in the tests above: waiting.
  run(300000);
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h2\"}"), "\"led_pin\":10,\"led_test\":false,\"show_running\":false,\"show_length_ms\":298000,\"timecode\":true"));
  assert(frameCheck(12, 0) >= 8 && "waiting: dim red, clearly visible");
  int at = brightestPixel();
  run(180);
  assert(brightestPixel() == (at + 1) % 8 && "waiting: the red head moves one pixel per 180 ms");
  int lit = 0;
  for (uint32_t c : neoShown) lit += c != 0;
  assert(lit >= 2 && lit <= 4 && "a head with a fading tail, not the whole ring");

  // Running: a trigger turns it strong green and fast, for the length of the cube's show.
  hold(BUTTON_PIN, LOW, 400);
  hold(BUTTON_PIN, HIGH, 100);
  assert(frameCheck(0, 100) >= 66 && "running: strong green, capped at the cube's 100");
  at = brightestPixel();
  run(60);
  assert(brightestPixel() == (at + 1) % 8 && "running: one pixel per 60 ms");
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h3\"}"), "\"show_running\":true"));
  run(298000 - 700);
  assert(frameCheck(0, 100) >= 66 && "still running just before the show ends");
  run(600);
  assert(frameCheck(12, 0) >= 8 && "back to waiting red when the cube's timeline has ended");

  // The bench colour cycle overrides the status, then hands it back.
  assert(has(serial("{\"cmd\":\"led_test\",\"id\":\"l0\"}"), "led_test needs on"));
  out = serial("{\"cmd\":\"led_test\",\"id\":\"l1\",\"on\":1}", 1);
  assert(has(out, "{\"event\":\"led_test\",\"id\":\"l1\",\"on\":true,\"pin\":10}"));
  const uint32_t R = 60u << 16, G = 60u << 8, B = 60u, W = R | G | B;
  for (uint32_t colour : {R, G, B, W}) {
    assert(neoShown == std::vector<uint32_t>(8, colour));
    run(1000);
  }
  for (int pixel = 0; pixel < 8; pixel++) {
    std::vector<uint32_t> one(8, 0u);
    one[pixel] = W;
    assert(neoShown == one);
    run(250);
  }
  assert(neoShown == std::vector<uint32_t>(8, R) && "the cycle repeats");
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h4\"}"), "\"led_test\":true"));
  size_t sentBefore = sentFrames.size();
  run(20000);
  assert(sentFrames.size() == sentBefore && "the LED test sends nothing over the radio");
  serial("{\"cmd\":\"led_test\",\"id\":\"l2\",\"on\":0}", 40);
  assert(frameCheck(12, 0) >= 8 && "led_test off: the waiting scroll resumes");

  // ---- Timecode: the fallback for a ready cube that missed SHOW_START ----
  run(3000);
  before = sentFrames.size();
  out = serial("{\"cmd\":\"show_start\",\"id\":\"t1\",\"target\":\"broadcast\"}", 400);
  auto tcs = timecodesSince(before);
  assert(tcs.size() == 1 && tcs[0].showId == lastShowId && tcs[0].tMs < 400 && "one timecode straight after the burst");
  assert(!memcmp(sentFrames.back().dest.data(), BROADCAST, 6) && sentFrames.back().data.size() == 20);
  run(5000);
  tcs = timecodesSince(before);
  assert(tcs.size() == 6 && "then one a second");
  for (size_t i = 1; i < tcs.size(); i++) {
    assert(tcs[i].showId == tcs[0].showId && tcs[i].tMs - tcs[i - 1].tMs >= 1000 && tcs[i].tMs - tcs[i - 1].tMs < 1010);
  }
  assert(packetsSince(before) == 5 && "timecode never repeats SHOW_START");
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h5\"}"), "\"show_running\":true"));
  // show_stop ends the timecode (and allows an immediate restart).
  assert(has(serial("{\"cmd\":\"show_stop\",\"id\":\"x1\"}"), "{\"event\":\"show_stop\",\"id\":\"x1\",\"was_running\":true"));
  size_t stopped = sentFrames.size();
  run(5000);
  assert(sentFrames.size() == stopped && "no timecode after show_stop");
  // A start for one cube sends that cube its timecode, not everyone.
  before = sentFrames.size();
  serial("{\"cmd\":\"show_start\",\"id\":\"t2\",\"target\":\"AC:27:6E:80:00:D0\"}", 1500);
  tcs = timecodesSince(before);
  assert(tcs.size() == 2);
  for (size_t i = before; i < sentFrames.size(); i++) assert(!memcmp(sentFrames[i].dest.data(), CUBE44, 6));
  serial("{\"cmd\":\"show_stop\",\"id\":\"x2\"}");

  // show_config: the length bounds the timecode, survives a reboot, and is carried in hello.
  assert(has(serial("{\"cmd\":\"show_config\",\"id\":\"c0\"}"), "show_config needs length_ms"));
  assert(has(serial("{\"cmd\":\"show_config\",\"id\":\"c1\",\"length_ms\":0}"), "show_config needs length_ms"));
  out = serial("{\"cmd\":\"show_config\",\"id\":\"c2\",\"length_ms\":4500,\"version\":7,\"crc\":3735928559}");
  assert(has(out, "{\"event\":\"show_config\",\"id\":\"c2\",\"length_ms\":4500,\"version\":7,\"crc\":3735928559}"));
  showLengthMs = 1; showVersion = 0;
  esp_now_del_peer(BROADCAST);
  setup();
  assert(showLengthMs == 4500 && showVersion == 7 && showCrc == 3735928559u && "the config is kept in NVS");
  run(3000);
  before = sentFrames.size();
  serial("{\"cmd\":\"show_start\",\"id\":\"t3\",\"target\":\"broadcast\"}", 8000);
  tcs = timecodesSince(before);
  assert(tcs.size() == 5 && tcs.back().tMs < 4500 && "no timecode at or after the configured length");
  assert(tcs[0].showVersion == 7 && tcs[0].showCrc == 3735928559u);
  assert(has(serial("{\"cmd\":\"hello\",\"id\":\"h6\"}"), "\"show_running\":false,\"show_length_ms\":4500"));

  puts("PASS: MainshowController sends SET_ZONE/SHOW_START (type 8, fresh showId x5), locks out, debounces and re-arms its inputs, scrolls red/green status LEDs, cycles the LED test, and broadcasts timecode while a show runs");
  return 0;
}
