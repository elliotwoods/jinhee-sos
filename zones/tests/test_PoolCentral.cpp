// Real sketch: lease arbitration, sequence filtering, verified PCA9685 output and the
// concurrency discipline the legacy central got wrong. Frames are built straight from
// NctPoolProtocol.h, which is itself the cross-check that the header is single-sourced.
#include "zone_stubs.h"
#include "../firmware/PoolCentral/PoolCentral.ino"
#include "sketch_common.h"

using namespace nctzone;

static uint8_t RADIO_MAC[POOL_RADIO_COUNT][6] = {
  {0x02, 0x00, 0x00, 0x00, 0x00, 0x01}, {0x02, 0x00, 0x00, 0x00, 0x00, 0x02},
  {0x02, 0x00, 0x00, 0x00, 0x00, 0x03}, {0x02, 0x00, 0x00, 0x00, 0x00, 0x04},
  {0x02, 0x00, 0x00, 0x00, 0x00, 0x05}, {0x02, 0x00, 0x00, 0x00, 0x00, 0x06},
};
static uint32_t BOOT_ID[POOL_RADIO_COUNT] = {0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1006};
static uint16_t SEQ[POOL_RADIO_COUNT] = {};

static PoolState makeState(uint8_t radioId, bool active, uint8_t member, uint16_t seq,
                           uint16_t lease = POOL_LEASE_DEFAULT_MS, uint32_t bootId = 0) {
  PoolState p = {};
  fillHeader(p.h, POOL_STATE);
  p.bootId = bootId ? bootId : BOOT_ID[radioId - 1];
  p.seq = seq;
  p.leaseMs = lease;
  p.radioId = radioId;
  p.active = active;
  p.member = active ? member : 0;
  return p;
}

// Deliver as if from the board that normally carries this radio id.
static void deliver(const PoolState &p) {
  radioFrom(RADIO_MAC[p.radioId - 1], (const uint8_t *)&p, sizeof(p), false);
}

// Deliver the same frame from a DIFFERENT board - the duplicate-id case.
static void deliverFrom(const uint8_t *mac, const PoolState &p) {
  radioFrom(mac, (const uint8_t *)&p, sizeof(p), false);
}

// The slot the central has assigned to a given sender, or nullptr if it has none.
static RadioSlot *slotOf(const uint8_t *mac) {
  for (RadioSlot &s : radios) if (s.valid && sameMac(s.mac, mac)) return &s;
  return nullptr;
}

// Normal traffic: a radio sends with a strictly increasing sequence.
static void send(uint8_t radioId, bool active, uint8_t member, uint16_t lease = POOL_LEASE_DEFAULT_MS) {
  deliver(makeState(radioId, active, member, ++SEQ[radioId - 1], lease));
}

// Hold a member the way a real radio does: keep heartbeating for the whole interval.
static void hold(uint8_t radioId, uint8_t member, uint32_t ms) {
  uint32_t until = millis() + ms;
  while (millis() < until) { send(radioId, true, member); run(POOL_HEARTBEAT_MS); }
}

static void sendLegacy(uint8_t radioId, bool active, uint8_t member) {
  uint8_t frame[POOL_LEGACY_SIZE] = {};
  memcpy(frame, &POOL_LEGACY_MAGIC, 4);
  frame[4] = radioId; frame[5] = active; frame[6] = active ? member : 0;
  radioFrom(RADIO_MAC[radioId - 1], frame, sizeof(frame), true);
}

// Read the driver register a member maps to, straight out of the fake PCA9685.
// Read a physical driver output, in output-index space (1-23), knowing nothing about the
// wiring map - so a mistake in the map cannot hide itself here.
static bool litOutput(uint8_t out) {
  uint8_t b = out > 16, channel = uint8_t(out - (b ? 17 : 1));
  uint8_t expected[4];
  encodeOutputFor(out, true, expected);
  return !memcmp(pcaBoards[b].reg + 6 + 4 * channel, expected, 4);
}

// Frame `member` is lit when the output the map sends it to is lit.
static bool lit(uint8_t member) { return litOutput(outputForMember(member)); }

static bool onlyLit(std::vector<uint8_t> members) {
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    bool want = false;
    for (uint8_t w : members) if (w == m) want = true;
    if (lit(m) != want) return false;
  }
  return true;
}

static std::vector<PoolBeacon> beacons(size_t from = 0) {
  std::vector<PoolBeacon> out;
  for (size_t i = from; i < sentFrames.size(); i++)
    if (sentFrames[i].data.size() == sizeof(PoolBeacon) &&
        poolFrameType(sentFrames[i].data.data(), int(sentFrames[i].data.size())) == POOL_BEACON) {
      PoolBeacon b; memcpy(&b, sentFrames[i].data.data(), sizeof(b)); out.push_back(b);
    }
  return out;
}


// ---- Six-radio load simulation ----
// Models what the sliders actually do, including the RF loss that the installation
// suffers when several are worked at once, and measures how long the lights disagree
// with the sliders. Deterministic, so a regression is reproducible.
static uint32_t rngState = 0;
static uint32_t rnd() { rngState = rngState * 1664525u + 1013904223u; return rngState >> 8; }
static bool dropped(int percent) { return int(rnd() % 100) < percent; }

struct SimRadio {
  bool active;
  uint8_t member;
  uint32_t nextChange, nextBeat, releaseUntil;
  uint8_t expectMember;   // what a perfectly-delivered link would be showing, including
  uint32_t expectUntil;   // the deliberate POOL_RELEASE_HOLD_MS damping
};

static void simSend(uint8_t radioId, bool active, uint8_t member, bool modern, int loss) {
  bool drop = dropped(loss);
  if (modern) {
    // A dropped frame still consumed a sequence number, exactly as on the air.
    PoolState p = makeState(radioId, active, member, ++SEQ[radioId - 1]);
    if (!drop) deliver(p);
  } else if (!drop) {
    sendLegacy(radioId, active, member);
  }
}

// `modern` selects the new sender (burst on change, heartbeat, repeated release) or the
// current one (single frame on change, heartbeat, a single release frame, no sequence).
// Returns the longest run of milliseconds during which the verified lights disagreed
// with what the sliders were doing.
static uint32_t simulate(bool modern, uint32_t durationMs, int loss) {
  rngState = 20260921u;
  resetPcaBoards();
  for (auto &b : BOOT_ID) b += 0x100;
  for (auto &q : SEQ) q = 0;
  setup();
  run(50);

  SimRadio sim[POOL_RADIO_COUNT] = {};
  uint32_t start = millis(), lastAgree = start, worst = 0;
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) sim[i].nextChange = start + 50 + rnd() % 200;

  while (millis() - start < durationMs) {
    uint32_t now = millis();
    for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) {
      SimRadio &r = sim[i];
      uint8_t id = uint8_t(i + 1);
      if (now >= r.nextChange) {
        r.nextChange = now + 200 + rnd() % 200;
        bool wasActive = r.active;
        r.active = (rnd() % 10) < 7;  // mostly holding a member, sometimes letting go
        r.member = uint8_t(1 + rnd() % POOL_MEMBER_COUNT);
        r.nextBeat = now + POOL_HEARTBEAT_MS;
        if (modern) {
          for (uint8_t b = 0; b < POOL_BURST_COUNT; ++b) simSend(id, r.active, r.member, true, loss);
          if (!r.active) r.releaseUntil = now + POOL_RELEASE_REPEAT_MS;
        } else {
          // The current sender emits one frame on a change, and one release frame only.
          if (r.active || wasActive) simSend(id, r.active, r.member, false, loss);
        }
      }
      if (now >= r.nextBeat) {
        r.nextBeat = now + POOL_HEARTBEAT_MS;
        if (r.active) simSend(id, true, r.member, modern, loss);
        else if (modern && now < r.releaseUntil) simSend(id, false, 0, true, loss);
      }
    }
    run(10);

    // Expected output is the specification, not the raw intent: a release is damped by
    // POOL_RELEASE_HOLD_MS on purpose, so counting that as disagreement would measure the
    // feature rather than the link.
    uint32_t truth = 0, tick = millis();
    for (auto &r : sim) {
      if (r.active) { r.expectMember = r.member; r.expectUntil = tick + POOL_RELEASE_HOLD_MS; }
      if (r.active) truth |= memberBit(r.member);
      else if (r.expectMember && int32_t(r.expectUntil - tick) > 0) truth |= memberBit(r.expectMember);
    }
    if (verified == truth) lastAgree = millis();
    else if (millis() - lastAgree > worst) worst = millis() - lastAgree;
  }
  return worst;
}

int main() {
  // ---- Output mapping (previously poolzone_test/tests/output_test.cpp, never run) ----
  assert(memberBit(0) == 0 && memberBit(POOL_MEMBER_COUNT + 1) == 0);
  assert(memberBit(1) == 1 && memberBit(16) == 0x8000 && memberBit(17) == 0x10000 && memberBit(23) == 0x400000);
  assert((boardMask(0) | boardMask(1)) == 0x7fffff && !(boardMask(0) & boardMask(1)));
  assert(validMode(0x20, 4) && validMode(0xa0, 4));           // RESTART bit is not a fault
  assert(!validMode(0x10, 4) && !validMode(0x21, 4) && !validMode(0x60, 4) && !validMode(0x20, 0x14));
  // Relay polarity is expressed per OUTPUT, though every relay is currently wired the same
  // way round: lamp ON drives the channel low.
  uint8_t encoded[4], fullOn[] = {0, 0x10, 0, 0}, fullOff[] = {0, 0, 0, 0x10};
  for (uint8_t out = 1; out <= POOL_MEMBER_COUNT; ++out) assert(outputActiveLow(out) && "all relays are active-low");
  encodeOutputFor(17, true, encoded); assert(!memcmp(encoded, fullOff, 4) && "active-low: lit drives low");
  encodeOutputFor(17, false, encoded); assert(!memcmp(encoded, fullOn, 4) && "active-low: dark drives high");
  encodeOutputFor(1, true, encoded); assert(!memcmp(encoded, fullOff, 4) && "and the same on the other board");
  // Whatever the polarity, the two states must differ and be full-on/full-off only, and a
  // frame must encode for the output the wiring map sends it to.
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    uint8_t a[4], b[4], viaOutput[4];
    encodeOutput(m, true, a); encodeOutput(m, false, b);
    assert(memcmp(a, b, 4) && a[0] == 0 && a[2] == 0 && b[0] == 0 && b[2] == 0);
    assert((a[1] | a[3]) == 0x10 && (b[1] | b[3]) == 0x10);
    encodeOutputFor(outputForMember(m), true, viaOutput);
    assert(!memcmp(a, viaOutput, 4) && "a frame encodes for its mapped output");
  }
  // Each board is uniform, which is what makes the ALL_LED shortcut legitimate.
  bool low40 = false, low41 = false;
  assert(boardPolarityUniform(0, &low40) && low40);
  assert(boardPolarityUniform(1, &low41) && low41);

  // ---- Wiring map, checked against the raw measurements rather than the derived table ----
  // Exactly as recorded on the installation: driving output index i lit frame OBSERVED[i-1].
  static const uint8_t OBSERVED[23] = {1, 15, 20, 16, 5, 7, 23, 21, 12, 18, 6, 13, 8,
                                       22, 3, 17, 14, 10, 2, 11, 19, 4, 9};
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    uint8_t out = outputForMember(m);
    assert(out >= 1 && out <= POOL_MEMBER_COUNT);
    assert(OBSERVED[out - 1] == m && "frame m must be driven by the output observed to light it");
  }
  // Nothing outside 1..23 resolves to an output, and the boards partition the frames.
  assert(outputForMember(0) == 0 && outputForMember(POOL_MEMBER_COUNT + 1) == 0);
  assert((boardMask(0) | boardMask(1)) == 0x7FFFFFu && !(boardMask(0) & boardMask(1)));
  uint32_t onBoard0 = 0;
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) if (outputForMember(m) <= 16) onBoard0 |= memberBit(m);
  assert(boardMask(0) == onBoard0 && "boardMask must follow the wiring, not a contiguous range");

  stubSclPin = SCL_PIN;  // the pool central is on SDA 8 / SCL 9, not the zone pins
  resetPcaBoards();
  i2cAtWifiMode = -1;
  // A real power cycle leaves both drivers asleep, ALL_LED set, and every channel FULL_OFF
  // - which drives it LOW and, with active-low relays, asks for every lamp to be ON.
  assert(pcaBoards[0].reg[0] == 0x11 && pcaBoards[0].reg[0xFD] == 0x10);
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m)
    assert(lit(m) && "the hardware really does power up asking for every lamp");

  setup();

  // ---- Boot must leave every lamp off, before anything slow runs ----
  // Checked immediately after setup(), with no loop() passes: a boot that relies on the
  // main loop to tidy up has already had the relays energised for hundreds of milliseconds.
  assert(onlyLit({}) && "every lamp must be out by the end of setup()");
  assert(known == 0x7FFFFFu && verified == 0 && "and proved by readback, not assumed");
  assert(i2cAtWifiMode > 0 && "outputs must be darkened BEFORE the radio is brought up");
  run(50);

  // ---- Init ----
  assert(radioReady && peerReady && radioChannel == ESPNOW_CHANNEL);
  assert(!wifiSleep && "modem sleep must be disabled or broadcasts are silently dropped");
  assert(!wifiPersistent && !wifiAutoReconnect);
  assert(boards[0].online && boards[1].online);
  assert(boards[0].mode1 == 0x20 && boards[0].mode2 == 0x04);
  // ALL_LED cleared despite powering up non-zero; the legacy init never did this. It must
  // be cleared to the DARK encoding, not a hardcoded FULL_OFF: under active-low relays that
  // would light all 23 frames on every board initialisation and recovery.
  // ALL_LED must be cleared to each board's OWN dark state: the boards have opposite
  // polarity, so one value for both would light every frame on one of them.
  for (uint8_t bi = 0; bi < 2; ++bi) {
    uint8_t boardDark[4];
    encodeOutputFor(bi ? 17 : 1, false, boardDark);
    assert(!memcmp(pcaBoards[bi].reg + 0xFA, boardDark, 4) && "ALL_LED cleared to that board's dark state");
  }
  // Every physical output is dark, checked without reference to the wiring map.
  for (uint8_t out = 1; out <= POOL_MEMBER_COUNT; ++out) assert(!litOutput(out));
  // A board that only answers on the second attempt must still boot dark.
  resetPcaBoards(); i2cAtWifiMode = -1;
  pcaBoards[1].nackWrites = 3;  // a few glitched transactions during boot
  setup();
  assert(onlyLit({}) && known == 0x7FFFFFu && "a flaky board must not boot with lamps lit");
  // And one that never answers must not stall the boot or leave the healthy board lit.
  resetPcaBoards(); i2cAtWifiMode = -1;
  pcaBoards[1].present = false;
  setup();
  assert(!boards[1].online && "the missing board is reported, not waited on");
  // In output space: 0x40 carries outputs 1-16, whichever frames those happen to be.
  for (uint8_t out = 1; out <= 16; ++out) assert(!litOutput(out) && "the healthy board still boots dark");
  resetPcaBoards(); i2cAtWifiMode = -1;
  setup();
  run(50);
  assert(onlyLit({}) && boards[0].online && boards[1].online);
  // Nothing is lit until a radio asks for it, and every member register really holds the
  // dark encoding rather than merely "not the lit one".
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    uint8_t memberDark[4];
    encodeOutput(m, false, memberDark);   // that frame's mapped output, with its polarity
    assert(!memcmp(pcaBoards[memberBoard(m)].reg + 6 + 4 * memberChannel(m), memberDark, 4));
  }
  assert(onlyLit({}) && desired == 0);
  assert(epoch != 0);
  run(POOL_BEACON_MS + 100);
  auto first = beacons();
  assert(!first.empty() && first.back().epoch == epoch && first.back().version == POOL_PROTOCOL_VERSION);
  assert(first.back().channel == ESPNOW_CHANNEL && first.back().radioMask == 0);

  // ---- Pure OR arbitration: any radio holding a member lights it ----
  send(1, true, 7); send(4, true, 7); run(60);
  assert(lit(7) && onlyLit({7}));
  send(1, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(lit(7) && "a member stays lit while another radio still holds it");
  send(4, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // Six radios, six members, spanning the 0x40/0x41 board boundary.
  uint8_t spread[POOL_RADIO_COUNT] = {1, 5, 16, 17, 22, 23};
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) send(uint8_t(i + 1), true, spread[i]);
  run(60);
  assert(onlyLit({1, 5, 16, 17, 22, 23}));
  assert(radioMask(radios, millis()) == 0x3F);
  auto withRadios = beacons(sentFrames.size() - 1);
  run(POOL_BEACON_MS + 60);
  assert(beacons().back().radioMask == 0x3F && "the beacon tells each radio the central sees it");
  // The 0x40/0x41 boundary sits between output 16 and output 17, which the wiring map sends
  // to frames 17 and 14 respectively - not to frames 16 and 17.
  assert(outputForMember(17) == 16 && memberBoard(17) == 0 && memberChannel(17) == 15);
  assert(outputForMember(14) == 17 && memberBoard(14) == 1 && memberChannel(14) == 0);
  uint8_t on40[4], on41[4];
  encodeOutputFor(16, true, on40);
  encodeOutputFor(17, true, on41);
  assert(!memcmp(pcaBoards[0].reg + 6 + 4 * 15, on40, 4) && "frame 17 is the last channel of 0x40");
  send(1, true, 14); run(60);
  assert(!memcmp(pcaBoards[1].reg + 6, on41, 4) && "frame 14 is the first channel of 0x41");
  send(1, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) send(uint8_t(i + 1), false, 0);
  run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // Every member reachable.
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    send(2, true, m); run(40);
    assert(onlyLit({m}));
  }
  send(2, false, 0); run(POOL_RELEASE_HOLD_MS + 100);

  // ---- Sequence filtering ----
  // A frame overtaken by a newer one must not re-assert the member it carried.
  send(2, true, 5); run(40);
  assert(onlyLit({5}));
  deliver(makeState(2, true, 11, uint16_t(SEQ[1] - 1)));  // delayed, lower sequence
  run(60);
  assert(onlyLit({5}) && "a stale frame must never re-assert an old member");
  // A duplicate is ignored, but must still not cause the lease to lapse.
  uint32_t before = rejected;
  deliver(makeState(2, true, 5, SEQ[1]));
  run(40);
  assert(rejected == before + 1 && onlyLit({5}));
  send(2, false, 0); run(POOL_RELEASE_HOLD_MS + 100);

  // Wraparound across 65535. The sequence cannot simply be teleported forward: a jump of
  // 65505 is indistinguishable from going backwards by 31, and is correctly rejected.
  // The radio must be currently live, or the staleness escape would let anything in.
  send(4, true, 20); run(40);
  assert(onlyLit({20}));
  deliver(makeState(4, true, 21, uint16_t(SEQ[3] + 40000)));
  run(40);
  assert(!lit(21) && onlyLit({20}) && "a far-forward sequence jump reads as stale, not as progress");
  // Arrive on a fresh boot near the rollover, then walk across it. The slot is only handed
  // to a different bootId once the previous board's lease has lapsed, so let it.
  BOOT_ID[3] = 0x3004; SEQ[3] = 65533;
  run(POOL_LEASE_DEFAULT_MS + POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));
  send(4, true, 9); run(40); assert(onlyLit({9}));     // seq 65534, accepted after the lapse
  send(4, true, 10); run(40); assert(onlyLit({10}));   // seq 65535
  send(4, true, 11); run(40); assert(onlyLit({11}));   // seq 0 - the rollover
  send(4, true, 12); run(40); assert(onlyLit({12}));   // seq 1
  send(4, false, 0); run(POOL_RELEASE_HOLD_MS + 100);

  // A rebooted radio restarts at seq 0 with a new bootId. Without a bootId escape the
  // slot's high sequence would reject the radio forever; the slot is handed over once the
  // previous board's lease has lapsed, which a real reboot takes far longer than.
  send(5, true, 3); run(40); assert(onlyLit({3}));
  BOOT_ID[4] = 0x2005; SEQ[4] = 0;
  run(POOL_LEASE_DEFAULT_MS + 50);            // the old board is gone and its lease lapses
  send(5, true, 8); run(40);
  assert(onlyLit({8}) && "a rebooted radio takes the slot back once the old lease lapsed");
  send(5, false, 0); run(POOL_RELEASE_HOLD_MS + 100);

  // ---- Two boards configured with the SAME radio id ----
  // Slots are keyed by the sender's address, so a shared id is no longer a conflict: both
  // boards get their own slot and both work. Previously they landed in one slot and flipped
  // it between them at their combined heartbeat rate, which reached the lamps as flicker
  // with no other symptom.
  static const uint8_t TWIN[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x99};
  const uint32_t TWIN_BOOT = 0xDEADBEEF;
  uint16_t twinSeq = 0;
  send(6, true, 4); run(60);
  assert(onlyLit({4}));
  for (int beat = 0; beat < 6; ++beat) {
    // The twin claims radio id 6 as well, and is idle - exactly a second slider sitting
    // untouched. Its "nothing selected" must not speak for the board that is holding 4.
    deliverFrom(TWIN, makeState(6, false, 0, ++twinSeq, POOL_LEASE_DEFAULT_MS, TWIN_BOOT));
    run(POOL_IDLE_HEARTBEAT_MS / 2);
    send(6, true, 4);                          // the real holder keeps heartbeating
    run(POOL_IDLE_HEARTBEAT_MS / 2);
    assert(onlyLit({4}) && "a board sharing an id must not speak for another");
  }
  // Two separate slots, one per address, each with its own boot identity and sequence.
  assert(slotOf(RADIO_MAC[5]) && slotOf(TWIN) && slotOf(RADIO_MAC[5]) != slotOf(TWIN));
  assert(slotOf(RADIO_MAC[5])->bootId == BOOT_ID[5] && slotOf(TWIN)->bootId == TWIN_BOOT);
  assert(slotOf(RADIO_MAC[5])->radioId == 6 && slotOf(TWIN)->radioId == 6);
  // Reported, because the labels now lie even though nothing misbehaves.
  assert(claimedIdClashes(radios, millis()) == 2);
  // And the twin lights its own member at the same time, independently.
  deliverFrom(TWIN, makeState(6, true, 19, ++twinSeq, POOL_LEASE_DEFAULT_MS, TWIN_BOOT));
  run(60);
  assert(onlyLit({4, 19}) && "both boards drive their own member");
  deliverFrom(TWIN, makeState(6, false, 0, ++twinSeq, POOL_LEASE_DEFAULT_MS, TWIN_BOOT));
  send(6, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Slot capacity ----
  // More senders than slots: live boards are never evicted, and the newcomer is counted.
  // Let every slot from the earlier tests fall out of its lease first, so the table really
  // is reclaimable and this measures capacity rather than leftovers.
  run(POOL_LEASE_DEFAULT_MS + POOL_RELEASE_HOLD_MS + 200);
  uint32_t droppedBefore = noSlot;
  uint8_t crowd[POOL_SLOT_COUNT + 2][6];
  for (uint8_t i = 0; i < POOL_SLOT_COUNT + 2; ++i) {
    memcpy(crowd[i], TWIN, 6);
    crowd[i][3] = uint8_t(0xC0 + i);
    deliverFrom(crowd[i], makeState(1, true, uint8_t(1 + i), 1, POOL_LEASE_DEFAULT_MS, 0x7000u + i));
    run(30);
  }
  assert(noSlot > droppedBefore && "a full slot table refuses newcomers rather than evicting");
  for (uint8_t i = 0; i < POOL_SLOT_COUNT; ++i)
    assert(slotOf(crowd[i]) && lit(uint8_t(1 + i)) && "boards that got a slot keep it while live");
  // Once they fall quiet the slots are reclaimed and a new board is admitted.
  run(POOL_LEASE_MAX_MS + POOL_RELEASE_HOLD_MS + 200);
  assert(onlyLit({}));
  deliverFrom(crowd[POOL_SLOT_COUNT + 1], makeState(1, true, 12, 2, POOL_LEASE_DEFAULT_MS, 0x7100u));
  run(60);
  assert(onlyLit({12}) && slotOf(crowd[POOL_SLOT_COUNT + 1]) && "a stale slot is reclaimed");
  deliverFrom(crowd[POOL_SLOT_COUNT + 1], makeState(1, false, 0, 3, POOL_LEASE_DEFAULT_MS, 0x7100u));
  run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // A radio silent for longer than any lease returns with a low sequence and same bootId.
  send(6, true, 2); run(40); assert(onlyLit({2}));
  run(POOL_LEASE_MAX_MS + 200);
  assert(onlyLit({}));
  SEQ[5] = 1;
  send(6, true, 4); run(40);
  assert(onlyLit({4}) && "a long-silent radio must not be locked out by its old sequence");
  send(6, false, 0); run(POOL_RELEASE_HOLD_MS + 100);

  // ---- Lease ----
  send(1, true, 6, 0); run(40);
  assert(slotOf(RADIO_MAC[0])->leaseMs == POOL_LEASE_MIN_MS && "a zero lease is clamped up");
  send(1, true, 6, 60000); run(40);
  assert(slotOf(RADIO_MAC[0])->leaseMs == POOL_LEASE_MAX_MS && "an absurd lease is clamped down");
  send(1, true, 6); run(40);
  assert(slotOf(RADIO_MAC[0])->leaseMs == POOL_LEASE_DEFAULT_MS);
  // One radio going silent releases only its own member.
  send(3, true, 14); run(40);
  assert(onlyLit({6, 14}));
  // Radio 3 goes quiet. Its member survives its lease and then the release hold before
  // going dark, and radio 1's member is untouched throughout.
  hold(1, 6, POOL_LEASE_DEFAULT_MS - 100);
  assert(onlyLit({6, 14}) && "still inside radio 3's lease");
  hold(1, 6, POOL_RELEASE_HOLD_MS + 200);
  assert(onlyLit({6}) && "radio 3 expired on its own; radio 1 kept heartbeating");
  send(1, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Flicker: a momentary gap in a radio's reporting must not reach the lamps ----
  // Reproduces the reported symptom: the slider says "nothing selected" for a frame or two,
  // roughly twice a second, while the lamp is meant to be steadily on.
  send(2, true, 9); run(60);
  assert(onlyLit({9}));
  for (int blip = 0; blip < 6; ++blip) {
    send(2, false, 0);            // a dropped sample / settling filter
    run(80);
    assert(onlyLit({9}) && "a brief gap must not switch the lamp off");
    send(2, true, 9);
    run(420);
    assert(onlyLit({9}));
  }
  // A sustained release still turns the lamp off, just POOL_RELEASE_HOLD_MS later.
  send(2, false, 0); run(POOL_RELEASE_HOLD_MS / 2);
  assert(onlyLit({9}) && "still held inside the release window");
  run(POOL_RELEASE_HOLD_MS);
  assert(onlyLit({}) && "a real release still reaches the lamp");
  // Losing several frames outright is covered too: the lease plus the hold ride it out.
  send(3, true, 15); run(60);
  assert(onlyLit({15}));
  run(POOL_LEASE_DEFAULT_MS - 100);          // silence, just inside the lease
  assert(onlyLit({15}));
  run(200);                                   // lease has now lapsed, hold carries it
  assert(onlyLit({15}) && "the hold covers a lapsed lease");
  send(3, true, 15); run(60);
  assert(onlyLit({15}) && "and the radio coming back is seamless");
  send(3, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));
  // Moving directly between members is NOT damped - no ghost lamp trailing the slider.
  send(4, true, 6); run(60); assert(onlyLit({6}));
  send(4, true, 7); run(60);
  assert(onlyLit({7}) && "a deliberate move drops the old member at once");

  // Two radios on one member: one letting go leaves the other holding, with no blink.
  send(5, true, 7); run(60);
  assert(onlyLit({7}));
  send(4, false, 0); run(60);
  assert(onlyLit({7}));
  send(5, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- I2C faults ----
  // A NACKed write must not be cached as applied. The legacy controller discarded the
  // return code and updated its shadow cache anyway, so one glitch stuck a light forever.
  // Which driver a frame lives on is the wiring map's business, so derive it rather than
  // assuming frame 10 is on 0x40 - it is not.
  const uint8_t faultBoard = memberBoard(10);
  uint8_t neighbour = 0;
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m)
    if (m != 10 && memberBoard(m) == faultBoard) { neighbour = m; break; }
  assert(neighbour && "the fault board must carry more than one frame");
  uint32_t errorsBefore = i2cErrors, recoveriesBefore = recoveries;
  pcaBoards[faultBoard].nackWrites = 1;
  send(1, true, 10);
  loop();  // a single pass, so the failure is observed before any retry can mask it
  assert(i2cErrors > errorsBefore);
  assert(!(known & memberBit(10)) && "a refused write must never be cached as applied");
  // One glitched transaction must NOT take the board down. Recovery bit-bangs the bus and
  // rewrites ALL_LED, darkening every lamp on the board for long enough for a relay to
  // drop out - which is precisely the flicker this must not cause.
  assert(boards[faultBoard].online && "a single NACK must not take the board offline");
  assert(recoveries == recoveriesBefore && "and must not trigger a bus recovery");
  assert((known & memberBit(neighbour)) && "other frames on that board keep their verified state");
  pcaBoards[faultBoard].nackWrites = 0;
  hold(1, 10, RECOVERY_MS + 500);
  assert(lit(10) && (verified & memberBit(10)) && "a refused write must be retried, not forgotten");

  // A driver that silently resets (brownout, glitch) loses MODE1 auto-increment and its
  // outputs. The audit must notice with no bus fault at all, and restore only live leases.
  // Frame 10 is held throughout and lives on `faultBoard`; pick an expiring frame on the
  // same board so the reset really does wipe both.
  uint8_t expiring = 0;
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m)
    if (m != 10 && m != neighbour && memberBoard(m) == faultBoard) { expiring = m; break; }
  assert(expiring);
  send(3, true, expiring); run(60);
  assert(lit(expiring));
  send(3, false, 0); run(POOL_RELEASE_HOLD_MS + 100);   // radio 3 lets go of it ...
  pcaBoards[faultBoard].powerOn();                      // ... and only then does the driver reset
  hold(1, 10, HEALTH_MS + RECOVERY_MS + 400);
  assert(boards[faultBoard].online && boards[faultBoard].mode1 == 0x20 && "the reset driver is reinitialised");
  assert(!lit(expiring) && "an expired selection must not be restored by recovery");
  assert(lit(10) && "a still-held selection is restored after the reset");

  // A held-low SDA is cleared with the NXP nine-clock sequence, open-drain only.
  int pulsesBefore = sclPulses;
  size_t writesBefore = pinWrites.size();
  boards[0].online = boards[1].online = false;
  heldLow[SDA_PIN] = 4;              // released after four SCL pulses
  hold(1, 10, RECOVERY_MS + 400);
  assert(sclPulses > pulsesBefore && sclPulses - pulsesBefore <= 9);
  for (size_t i = writesBefore; i < pinWrites.size(); ++i)
    if (pinWrites[i].first == SDA_PIN) assert(pinWrites[i].second == LOW || pinLevels.count(SDA_PIN));
  heldLow.clear();
  hold(1, 10, RECOVERY_MS + 400);
  assert(boards[0].online && boards[1].online);
  send(1, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Concurrency discipline ----
  // The receive callback runs on the Wi-Fi task. It must hand the frame over and nothing
  // else: the legacy central printed to USB there and stalled the radio.
  int serialBefore = serialWrites, i2cBefore = i2cTransactions;
  deliver(makeState(2, true, 13, ++SEQ[1]));
  assert(serialWrites == serialBefore && "no USB writes inside the ESP-NOW callback");
  assert(i2cTransactions == i2cBefore && "no I2C inside the ESP-NOW callback");
  run(60);
  assert(onlyLit({13}));

  // A USB port nobody is draining must cost log lines, never light control.
  serialTxSpace = 0;
  uint32_t dropsBefore = logDrops;
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) { send(2, true, m); run(40); assert(onlyLit({m})); }
  assert(logDrops > dropsBefore && "log lines are dropped rather than blocking");
  serialTxSpace = 4096;
  send(2, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Legacy receive shim ----
  // A slider missed during a rollout keeps working instead of going dark.
  run(POOL_LEASE_MAX_MS + 100);
  sendLegacy(5, true, 18); run(60);
  assert(onlyLit({18}) && slotOf(RADIO_MAC[4])->legacy);
  sendLegacy(5, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));
  // But a legacy frame must never displace a radio already on the current protocol.
  send(5, true, 21); run(40);
  assert(onlyLit({21}) && !slotOf(RADIO_MAC[4])->legacy);
  sendLegacy(5, true, 2); run(40);
  assert(onlyLit({21}) && !slotOf(RADIO_MAC[4])->legacy && "a stray legacy frame cannot pre-empt a live lease");
  send(5, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Armed output test ----
  // Needed to answer a wiring question without a slider, so it must drive the lamps
  // exactly and then give them back on its own.
  send(1, true, 6); run(60);
  assert(onlyLit({6}));
  assert(has(serial("OUT 6 OFF"), "OUT ARM") && "a test command without arming is refused");
  assert(onlyLit({6}) && "and changes nothing");
  serial("OUT ARM");
  run(40);
  assert(onlyLit({}) && "arming takes the lamps off the radios and puts them out");
  serial("OUT 9 ON"); run(40);
  assert(onlyLit({9}));
  serial("OUT ALL ON"); run(60);
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) assert(lit(m));
  serial("OUT ALL OFF"); run(60);
  assert(onlyLit({}));
  // Bad input is refused without disturbing what is already on.
  serial("OUT 9 ON"); run(40);
  assert(has(serial("OUT 99 ON"), "ERR OUT") && has(serial("OUT 9 SIDEWAYS"), "ERR OUT"));
  run(40);
  assert(onlyLit({9}) && "a rejected command leaves the test state alone");
  // A radio holding a member is ignored while the test is armed ...
  hold(1, 6, POOL_HEARTBEAT_MS * 3);
  assert(onlyLit({9}) && "an armed test is not overridden by the radios");
  // ... and released explicitly.
  serial("OUT DISARM"); run(60);
  assert(onlyLit({6}) && "disarming hands the lamps straight back to the radios");
  // The lease expires on its own, so a forgotten arm cannot hold the show.
  serial("OUT ARM"); serial("OUT 15 ON"); run(60);
  assert(onlyLit({15}));
  hold(1, 6, OUTPUT_TEST_MS + 200);
  assert(onlyLit({6}) && "the armed test times out and the radios resume");
  assert(!testArmed() && testUntil == 0);
  send(1, false, 0); run(POOL_RELEASE_HOLD_MS + 100);
  assert(onlyLit({}));

  // ---- Six radios at once, with RF loss: the reported failure ----
  // Same scenario, same seed, same 20% loss; only the sender differs.
  uint32_t current = simulate(false, 15000, 20);
  uint32_t improved = simulate(true, 15000, 20);
  printf("six-radio load, 20%% loss: worst disagreement %u ms now, %u ms with bursts+repeated release\n",
         current, improved);
  // The single-shot sender still loses a release or a change outright, and the member is
  // then wrong for far longer than the deliberate release damping can account for - i.e.
  // genuine divergence, not the hold. (The central-side hold does absorb part of it, which
  // is why this is well under a full lease now.)
  assert(current > POOL_RELEASE_HOLD_MS && "the single-shot sender still diverges beyond the hold");
  // The new sender bursts changes and repeats releases, so a single loss is invisible.
  assert(improved < POOL_HEARTBEAT_MS * 2 && "bursts and repeated releases must absorb a lost frame");
  assert(improved * 3 < current);
  // Under no loss at all both converge, so the difference above is loss, not overhead.
  assert(simulate(false, 4000, 0) < POOL_HEARTBEAT_MS * 2);
  assert(simulate(true, 4000, 0) < POOL_HEARTBEAT_MS * 2);

  puts("PASS: PoolCentral init/ALL_LED/modem-sleep, beacon, OR arbitration, seq+bootId filtering, lease "
       "clamp/expiry, release-hold de-glitch, transient-I2C tolerance, verified I2C retry, "
       "driver-reset and bus recovery, callback discipline, legacy shim, per-MAC slots (shared "
       "ids independent, capacity and reclaim), frame->output wiring map, "
       "leased output test, boot-dark before radio "
       "bring-up (flaky and missing boards), six-radio lossy load");
}
