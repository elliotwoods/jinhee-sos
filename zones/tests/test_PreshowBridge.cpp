// Real sketch: the TouchDesigner serial contract, de-duplication, acknowledgement of every
// well-formed event, the beacon, and the concurrency discipline. Frames are built straight
// from NctPreshowProtocol.h, which is itself the cross-check that the header is single-sourced.
#include "zone_stubs.h"
#include "../firmware/PreshowBridge/PreshowBridge.ino"
#include "sketch_common.h"

using namespace nctzone;

static uint8_t PLATE_MAC[PRESHOW_POINT_COUNT][6] = {
  {0x02, 0x00, 0x00, 0x00, 0x00, 0x11}, {0x02, 0x00, 0x00, 0x00, 0x00, 0x12},
  {0x02, 0x00, 0x00, 0x00, 0x00, 0x13}, {0x02, 0x00, 0x00, 0x00, 0x00, 0x14},
};
static uint32_t BOOT_ID[PRESHOW_POINT_COUNT] = {0x1001, 0x1002, 0x1003, 0x1004};
static uint16_t SEQ[PRESHOW_POINT_COUNT] = {};

static PreshowEvent makeEvent(uint8_t point, uint8_t state, uint16_t seq, uint32_t bootId = 0) {
  PreshowEvent e = {};
  fillHeader(e.h, PRESHOW_EVENT);
  e.bootId = bootId ? bootId : BOOT_ID[point - 1];
  e.seq = seq;
  e.pointId = point;
  e.state = state;
  return e;
}

static void deliver(const PreshowEvent &e, bool broadcast = false) {
  radioFrom(PLATE_MAC[e.pointId - 1], (const uint8_t *)&e, sizeof(e), broadcast);
}

// A new edge, the way a plate raises one: a fresh sequence number.
static PreshowEvent edge(uint8_t point, uint8_t state) {
  return makeEvent(point, state, ++SEQ[point - 1]);
}

// What a plate actually does with an edge: burst it, spaced as the plate spaces it.
static void sendEdge(uint8_t point, uint8_t state) {
  PreshowEvent e = edge(point, state);
  for (uint8_t i = 0; i < PRESHOW_BURST_COUNT; ++i) {
    deliver(e);
    run(PRESHOW_BURST_GAP_MS);
  }
  run(30);
}

static void sendLegacy(uint8_t point, uint8_t state) {
  uint8_t frame[PRESHOW_LEGACY_SIZE] = {point, state};
  radioFrom(PLATE_MAC[point - 1], frame, sizeof(frame), true);
  run(30);
}

// Everything the bridge has written to TouchDesigner, cue lines only.
static std::vector<std::string> cueLines(const std::string &text) {
  std::vector<std::string> out;
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) end = text.size();
    std::string line = text.substr(start, end - start);
    if (line.rfind("PRESHOW,", 0) == 0) out.push_back(line);
    start = end + 1;
  }
  return out;
}

// Every line the bridge wrote that is NOT a cue. TouchDesigner's Serial DAT sees these too,
// so outside the boot banner there must be none unless a human typed something.
static std::vector<std::string> otherLines(const std::string &text) {
  std::vector<std::string> out;
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) end = text.size();
    std::string line = text.substr(start, end - start);
    if (!line.empty() && line.rfind("PRESHOW,", 0) != 0) out.push_back(line);
    start = end + 1;
  }
  return out;
}

static std::vector<PreshowAck> acksTo(const uint8_t *mac, size_t from = 0) {
  std::vector<PreshowAck> out;
  for (auto &frame : framesTo(mac, from))
    if (preshowFrameType(frame.data.data(), int(frame.data.size())) == PRESHOW_ACK) {
      PreshowAck a; memcpy(&a, frame.data.data(), sizeof(a)); out.push_back(a);
    }
  return out;
}

static std::vector<PreshowBeacon> beacons(size_t from = 0) {
  std::vector<PreshowBeacon> out;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (preshowFrameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) == PRESHOW_BEACON) {
      PreshowBeacon b; memcpy(&b, sentFrames[i].data.data(), sizeof(b)); out.push_back(b);
    }
  return out;
}

int main() {
  setup();

  // ---- Init ----
  assert(radioReady && peerReady && radioChannel == ESPNOW_CHANNEL);
  assert(!wifiSleep && "modem sleep must be disabled or frames are silently dropped");
  assert(!wifiPersistent && !wifiAutoReconnect);
  assert(epoch != 0 && "0 is reserved so a plate can tell 'no beacon seen yet'");
  assert(desiredMask == 0 && emittedMask == 0);
  // The banner is what zone_detect.py identifies this board by.
  assert(has(Serial.output, "NCT PRESHOW MEDIA BRIDGE"));
  assert(has(Serial.output, "ESP-NOW CH2 -> SERIAL DAT") && !has(Serial.output, "CH1"));
  assert(cueLines(Serial.output).empty() && "nothing is cued before a plate says so");

  run(PRESHOW_BEACON_MS + 50);
  auto first = beacons();
  assert(!first.empty() && first.back().epoch == epoch && first.back().version == PRESHOW_PROTOCOL_VERSION);
  assert(first.back().channel == ESPNOW_CHANNEL && first.back().pointMask == 0);
  assert(!memcmp(sentFrames.back().dest.data(), BROADCAST, 6) && "the beacon is broadcast");

  // ---- The TouchDesigner contract ----
  Serial.output.clear();
  size_t mark = sentFrames.size();
  sendEdge(1, 1);
  auto lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,1,ON");
  assert(otherLines(Serial.output).empty() && "no unsolicited output alongside a cue");
  // Every frame of the burst is acknowledged, echoing exactly what the plate is waiting for.
  auto acks = acksTo(PLATE_MAC[0], mark);
  assert(acks.size() == PRESHOW_BURST_COUNT);
  assert(acks[0].bootId == BOOT_ID[0] && acks[0].seq == SEQ[0] && acks[0].pointId == 1);
  assert(acks[0].flags == PRESHOW_ACK_APPLIED && "the first one applied the change");
  assert(acks[1].flags == 0 && acks[2].flags == 0 && "the retries did not, and say so");
  assert(acks.back().seq == SEQ[0] && "a duplicate is still acknowledged, or the plate would "
                                      "retry its whole window and report a phantom failure");

  // A held tag re-asserts the same edge forever. The bridge must stay silent.
  Serial.output.clear();
  PreshowEvent held = makeEvent(1, 1, SEQ[0]);
  for (int beat = 0; beat < 30; ++beat) { deliver(held); run(PRESHOW_STATE_REPEAT_MS); }
  assert(cueLines(Serial.output).empty() && "re-asserting a state TouchDesigner already knows is silent");
  assert(emittedMask == preshowPointBit(1) && "and the point is still held");
  assert(beacons(mark).back().pointMask == preshowPointBit(1) && "the plate is told the cue landed");

  // OFF is a change, so exactly one line.
  Serial.output.clear();
  sendEdge(1, 0);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,1,OFF" && emittedMask == 0);

  // ---- Four points, independent ----
  Serial.output.clear();
  for (uint8_t point = 1; point <= PRESHOW_POINT_COUNT; ++point) sendEdge(point, 1);
  lines = cueLines(Serial.output);
  assert(lines.size() == PRESHOW_POINT_COUNT);
  for (uint8_t point = 1; point <= PRESHOW_POINT_COUNT; ++point) {
    char expected[24];
    snprintf(expected, sizeof(expected), "PRESHOW,%u,ON", point);
    assert(lines[point - 1] == expected);
  }
  assert(emittedMask == 0x0F);
  run(PRESHOW_BEACON_MS + 50);
  assert(beacons().back().pointMask == 0x0F);
  Serial.output.clear();
  for (uint8_t point = 1; point <= PRESHOW_POINT_COUNT; ++point) sendEdge(point, 0);
  assert(cueLines(Serial.output).size() == PRESHOW_POINT_COUNT && emittedMask == 0);

  // ---- Sequence filtering ----
  // A frame overtaken by a newer one must never re-assert the state it carried.
  sendEdge(2, 1);
  Serial.output.clear();
  deliver(makeEvent(2, 0, uint16_t(SEQ[1] - 1)));   // delayed, lower sequence
  run(40);
  assert(cueLines(Serial.output).empty() && emittedMask == preshowPointBit(2));
  // A far-forward jump reads as going backwards, and is rejected the same way.
  uint32_t dupesBefore = duplicates;
  deliver(makeEvent(2, 0, uint16_t(SEQ[1] + 40000)));
  run(40);
  assert(duplicates > dupesBefore && emittedMask == preshowPointBit(2));
  sendEdge(2, 0);
  assert(emittedMask == 0);

  // A rebooted plate restarts at a low sequence with a fresh bootId and is taken at once.
  sendEdge(3, 1);
  assert(emittedMask == preshowPointBit(3));
  BOOT_ID[2] = 0x2003;
  SEQ[2] = 0;
  Serial.output.clear();
  sendEdge(3, 0);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,3,OFF" && "a reboot must not lock a plate out");

  // ---- A bridge reboot is healed by the plates' re-assert ----
  // The plate does not know we restarted; it just keeps sending the same frame it always was.
  sendEdge(4, 1);
  assert(emittedMask == preshowPointBit(4));
  PreshowEvent stillHeld = makeEvent(4, 1, SEQ[3]);
  uint32_t previousEpoch = epoch;
  setup();
  run(20);
  assert(epoch != previousEpoch && emittedMask == 0 && "a fresh bridge knows nothing");
  Serial.output.clear();
  deliver(stillHeld);
  run(40);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,4,ON" && "the re-assert restores the true state");
  sendEdge(4, 0);
  assert(emittedMask == 0);

  // ---- A cue line that could not be written is retried, never lost ----
  serialTxSpace = 0;                       // nothing is draining the port
  uint32_t dropsBefore = cueDrops;
  sendEdge(1, 1);
  run(50);
  assert(cueDrops > dropsBefore && desiredMask == preshowPointBit(1) && emittedMask == 0);
  serialTxSpace = 4096;                    // the port comes back
  Serial.output.clear();
  run(50);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,1,ON" && emittedMask == preshowPointBit(1));
  sendEdge(1, 0);
  assert(emittedMask == 0);

  // The beacon reports what TouchDesigner was told, not merely what was asked for: a plate
  // reading it is asking whether its cue landed.
  serialTxSpace = 0;
  sendEdge(2, 1);
  run(PRESHOW_BEACON_MS + 50);
  assert(desiredMask == preshowPointBit(2) && beacons().back().pointMask == 0);
  serialTxSpace = 4096;
  run(PRESHOW_BEACON_MS + 50);
  assert(beacons().back().pointMask == preshowPointBit(2));
  sendEdge(2, 0);

  // ---- Malformed and foreign frames ----
  uint32_t packetsBefore = packets;
  // Sent explicitly rather than through deliver(), which addresses a plate by its point id.
  PreshowEvent malformed = edge(1, 1);
  malformed.pointId = 9;
  radioFrom(PLATE_MAC[0], (const uint8_t *)&malformed, sizeof(malformed), false);
  malformed = edge(1, 1);
  malformed.state = 7;
  radioFrom(PLATE_MAC[0], (const uint8_t *)&malformed, sizeof(malformed), false);
  PoolState pool = {};                      // the other protocol on this channel
  fillHeader(pool.h, POOL_STATE);
  pool.radioId = 1; pool.leaseMs = POOL_LEASE_DEFAULT_MS;
  radioFrom(PLATE_MAC[0], (const uint8_t *)&pool, sizeof(pool), true);
  uint8_t cubeSized[24] = {};               // a neocube packet, which must be ignored
  radioFrom(PLATE_MAC[0], cubeSized, sizeof(cubeSized), false);
  run(40);
  assert(packets == packetsBefore && "nothing malformed or foreign reaches the mailbox");
  assert(emittedMask == 0);

  // ---- Legacy shim ----
  // A plate missed during the rollout keeps working instead of going silent.
  Serial.output.clear();
  mark = sentFrames.size();
  sendLegacy(3, 1);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,3,ON" && legacyPackets > 0);
  assert(acksTo(PLATE_MAC[2], mark).empty() && "a legacy plate has no sequence to acknowledge");
  Serial.output.clear();
  sendLegacy(3, 1);
  assert(cueLines(Serial.output).empty() && "a repeated legacy frame is still not a change");
  sendLegacy(3, 0);
  assert(emittedMask == 0);
  // But a stray legacy frame must not speak for a plate already on the current protocol.
  sendEdge(3, 1);
  assert(emittedMask == preshowPointBit(3));
  Serial.output.clear();
  sendLegacy(3, 0);
  assert(cueLines(Serial.output).empty() && emittedMask == preshowPointBit(3));
  sendEdge(3, 0);

  // ---- Two plates flashed with the same point ----
  static const uint8_t TWIN[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x99};
  PreshowEvent twin = makeEvent(1, 1, 1, 0xDEADBEEF);
  radioFrom(TWIN, (const uint8_t *)&twin, sizeof(twin), false);
  run(40);
  sendEdge(1, 1);
  assert(preshowPointClashes(senders, millis()) == 2 && "the clash is reported ...");
  assert(emittedMask == preshowPointBit(1) && "... and neither plate corrupts the other's sequence");
  twin = makeEvent(1, 0, 2, 0xDEADBEEF);
  radioFrom(TWIN, (const uint8_t *)&twin, sizeof(twin), false);
  run(40);
  sendEdge(1, 0);
  assert(emittedMask == 0);

  // ---- Concurrency discipline ----
  // The receive callback runs on the Wi-Fi task. It must hand the frame over and nothing
  // else: no USB writes, no peer changes, no sending. (SerialStub::note() also asserts that
  // no write happens inside a critical section.)
  int serialBefore = serialWrites;
  size_t peersBefore = espPeers.size(), framesBefore = sentFrames.size();
  deliver(edge(2, 1));
  assert(serialWrites == serialBefore && "no USB writes inside the ESP-NOW callback");
  assert(espPeers.size() == peersBefore && "no peer added inside the ESP-NOW callback");
  assert(sentFrames.size() == framesBefore && "nothing transmitted inside the ESP-NOW callback");
  run(40);
  assert(emittedMask == preshowPointBit(2));
  sendEdge(2, 0);

  // A port nobody is draining costs diagnostic lines, never the radio link.
  serialTxSpace = 0;
  uint32_t logDropsBefore = logDrops;
  serial("?");
  assert(logDrops > logDropsBefore && "diagnostics are dropped rather than blocking");
  serialTxSpace = 4096;

  // ---- Console ----
  // Nothing is printed unless a human typed something, because TouchDesigner is reading here.
  Serial.output.clear();
  run(5000);
  assert(Serial.output.empty() && "the bridge is silent when nothing is happening");
  std::string report = serial("?");
  assert(has(report, "\"device\":\"PreshowBridge\",\"type\":\"status\"") && has(report, FIRMWARE_VERSION));
  assert(has(report, "\"type\":\"point\"") && has(report, "\"type\":\"plate\""));
  assert(cueLines(report).empty() && "a report must never look like a cue");
  assert(has(serial("STATUS"), "\"type\":\"status\""));
  assert(has(serial("help"), "PRESHOW BRIDGE") && has(serial("nonsense"), "ERR command"));
  // The hand-driven test cue, for checking the TouchDesigner end without a plate.
  Serial.output.clear();
  serial("TEST 2 ON");
  run(20);
  lines = cueLines(Serial.output);
  assert(lines.size() == 1 && lines[0] == "PRESHOW,2,ON");
  serial("TEST 2 OFF");
  run(20);
  assert(emittedMask == 0);
  assert(has(serial("TEST 9 ON"), "ERR TEST") && has(serial("TEST 2 SIDEWAYS"), "ERR TEST"));

  puts("PASS: PreshowBridge init/modem-sleep/beacon, exact TouchDesigner serial contract, "
       "change-only cues, acknowledgement of duplicates, seq+bootId filtering, bridge-reboot "
       "self-heal, undrained-port cue retry, legacy shim, shared point ids, callback discipline, "
       "silent-unless-asked console");
}
