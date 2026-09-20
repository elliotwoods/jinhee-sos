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

static void deliver(const PoolState &p) {
  radioFrom(RADIO_MAC[p.radioId - 1], (const uint8_t *)&p, sizeof(p), false);
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
static bool lit(uint8_t member) {
  uint8_t b = member > 16, channel = uint8_t(member - (b ? 17 : 1));
  uint8_t expected[4];
  encodeOutput(true, expected);
  return !memcmp(pcaBoards[b].reg + 6 + 4 * channel, expected, 4);
}

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

    uint32_t truth = 0;
    for (auto &r : sim) if (r.active) truth |= memberBit(r.member);
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
  uint8_t encoded[4], fullOn[] = {0, 0x10, 0, 0}, fullOff[] = {0, 0, 0, 0x10};
  encodeOutput(true, encoded); assert(!memcmp(encoded, fullOn, 4));
  encodeOutput(false, encoded); assert(!memcmp(encoded, fullOff, 4));

  stubSclPin = SCL_PIN;  // the pool central is on SDA 8 / SCL 9, not the zone pins
  resetPcaBoards();
  // Both drivers come up asleep with ALL_LED set, as after a real power cycle.
  assert(pcaBoards[0].reg[0xFB] == 0x10);

  setup();
  run(50);

  // ---- Init ----
  assert(radioReady && peerReady && radioChannel == ESPNOW_CHANNEL);
  assert(!wifiSleep && "modem sleep must be disabled or broadcasts are silently dropped");
  assert(!wifiPersistent && !wifiAutoReconnect);
  assert(boards[0].online && boards[1].online);
  assert(boards[0].mode1 == 0x20 && boards[0].mode2 == 0x04);
  // ALL_LED cleared despite powering up non-zero; the legacy init never did this.
  for (auto &b : pcaBoards) assert(b.reg[0xFA] == 0 && b.reg[0xFB] == 0 && b.reg[0xFC] == 0 && b.reg[0xFD] == 0x10);
  assert(epoch != 0);
  run(POOL_BEACON_MS + 100);
  auto first = beacons();
  assert(!first.empty() && first.back().epoch == epoch && first.back().version == POOL_PROTOCOL_VERSION);
  assert(first.back().channel == ESPNOW_CHANNEL && first.back().radioMask == 0);

  // ---- Pure OR arbitration: any radio holding a member lights it ----
  send(1, true, 7); send(4, true, 7); run(60);
  assert(lit(7) && onlyLit({7}));
  send(1, false, 0); run(60);
  assert(lit(7) && "a member stays lit while another radio still holds it");
  send(4, false, 0); run(60);
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
  // Member 16 is board 0x40 channel 15; member 17 is board 0x41 channel 0.
  assert(pcaBoards[0].reg[6 + 4 * 15] == 0 && pcaBoards[0].reg[7 + 4 * 15] == 0x10);
  assert(pcaBoards[1].reg[6] == 0 && pcaBoards[1].reg[7] == 0x10);
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) send(uint8_t(i + 1), false, 0);
  run(60);
  assert(onlyLit({}));

  // Every member reachable.
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    send(2, true, m); run(40);
    assert(onlyLit({m}));
  }
  send(2, false, 0); run(60);

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
  send(2, false, 0); run(60);

  // Wraparound across 65535. The sequence cannot simply be teleported forward: a jump of
  // 65505 is indistinguishable from going backwards by 31, and is correctly rejected.
  deliver(makeState(4, true, 21, uint16_t(SEQ[3] + 40000)));
  run(40);
  assert(!lit(21) && "a far-forward sequence jump reads as stale, not as progress");
  // Arrive on a fresh boot near the rollover, then walk across it.
  BOOT_ID[3] = 0x3004; SEQ[3] = 65533;
  send(4, true, 9); run(40); assert(onlyLit({9}));     // seq 65534, accepted via bootId reset
  send(4, true, 10); run(40); assert(onlyLit({10}));   // seq 65535
  send(4, true, 11); run(40); assert(onlyLit({11}));   // seq 0 - the rollover
  send(4, true, 12); run(40); assert(onlyLit({12}));   // seq 1
  send(4, false, 0); run(60);

  // A rebooted radio restarts at seq 0 with a new bootId. Without that escape the slot's
  // high sequence would reject the radio forever.
  send(5, true, 3); run(40); assert(onlyLit({3}));
  BOOT_ID[4] = 0x2005; SEQ[4] = 0;
  send(5, true, 8); run(40);
  assert(onlyLit({8}) && "a rebooted radio must be accepted immediately");
  send(5, false, 0); run(60);

  // A radio silent for longer than any lease returns with a low sequence and same bootId.
  send(6, true, 2); run(40); assert(onlyLit({2}));
  run(POOL_LEASE_MAX_MS + 200);
  assert(onlyLit({}));
  SEQ[5] = 1;
  send(6, true, 4); run(40);
  assert(onlyLit({4}) && "a long-silent radio must not be locked out by its old sequence");
  send(6, false, 0); run(60);

  // ---- Lease ----
  send(1, true, 6, 0); run(40);
  assert(radios[0].leaseMs == POOL_LEASE_MIN_MS && "a zero lease is clamped up");
  send(1, true, 6, 60000); run(40);
  assert(radios[0].leaseMs == POOL_LEASE_MAX_MS && "an absurd lease is clamped down");
  send(1, true, 6); run(40);
  assert(radios[0].leaseMs == POOL_LEASE_DEFAULT_MS);
  // One radio going silent releases only its own member.
  send(3, true, 14); run(40);
  assert(onlyLit({6, 14}));
  hold(1, 6, POOL_LEASE_DEFAULT_MS + 100);
  assert(onlyLit({6}) && "radio 3 expired on its own; radio 1 kept heartbeating");
  send(1, false, 0); run(60);
  assert(onlyLit({}));

  // ---- I2C faults ----
  // A NACKed write must not be cached as applied. The legacy controller discarded the
  // return code and updated its shadow cache anyway, so one glitch stuck a light forever.
  uint32_t errorsBefore = i2cErrors;
  pcaBoards[0].nackWrites = 3;
  send(1, true, 10);
  loop();  // a single pass, so the failure is observed before any retry can mask it
  assert(i2cErrors > errorsBefore);
  assert(!lit(10) && "the write was refused, so the register really is unset");
  assert(!(known & memberBit(10)) && "a refused write must never be cached as applied");
  pcaBoards[0].nackWrites = 0;
  hold(1, 10, RECOVERY_MS + 500);
  assert(lit(10) && (verified & memberBit(10)) && "a refused write must be retried, not forgotten");

  // A driver that silently resets (brownout, glitch) loses MODE1 auto-increment and its
  // outputs. The audit must notice with no bus fault at all, and restore only live leases.
  send(3, true, 20); run(60);
  assert(lit(20));
  send(3, false, 0); run(60);        // radio 3 releases member 20 ...
  pcaBoards[1].powerOn();            // ... and only then does 0x41 reset
  hold(1, 10, HEALTH_MS + RECOVERY_MS + 400);
  assert(boards[1].online && boards[1].mode1 == 0x20 && "the reset driver is reinitialised");
  assert(!lit(20) && "an expired selection must not be restored by recovery");
  assert(lit(10) && "a live selection survives the other board's recovery");

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
  send(1, false, 0); run(60);
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
  send(2, false, 0); run(60);
  assert(onlyLit({}));

  // ---- Legacy receive shim ----
  // A slider missed during a rollout keeps working instead of going dark.
  run(POOL_LEASE_MAX_MS + 100);
  sendLegacy(5, true, 18); run(60);
  assert(onlyLit({18}) && radios[4].legacy);
  sendLegacy(5, false, 0); run(60);
  assert(onlyLit({}));
  // But a legacy frame must never displace a radio already on the current protocol.
  send(5, true, 21); run(40);
  assert(onlyLit({21}) && !radios[4].legacy);
  sendLegacy(5, true, 2); run(40);
  assert(onlyLit({21}) && !radios[4].legacy && "a stray legacy frame cannot pre-empt a live lease");
  send(5, false, 0); run(60);
  assert(onlyLit({}));

  // ---- Six radios at once, with RF loss: the reported failure ----
  // Same scenario, same seed, same 20% loss; only the sender differs.
  uint32_t current = simulate(false, 15000, 20);
  uint32_t improved = simulate(true, 15000, 20);
  printf("six-radio load, 20%% loss: worst disagreement %u ms now, %u ms with bursts+repeated release\n",
         current, improved);
  // The current sender loses a release outright and the member stays lit for a whole
  // lease; that is the stuck/blinking light the installation shows.
  assert(current >= POOL_LEASE_DEFAULT_MS && "the current sender should show a lease-long stuck light");
  // The new sender bursts changes and repeats releases, so a single loss is invisible.
  assert(improved < POOL_HEARTBEAT_MS * 2 && "bursts and repeated releases must absorb a lost frame");
  assert(improved * 3 < current);
  // Under no loss at all both converge, so the difference above is loss, not overhead.
  assert(simulate(false, 4000, 0) < POOL_HEARTBEAT_MS * 2);
  assert(simulate(true, 4000, 0) < POOL_HEARTBEAT_MS * 2);

  puts("PASS: PoolCentral init/ALL_LED/modem-sleep, beacon, OR arbitration, seq+bootId filtering, lease "
       "clamp/expiry, verified I2C retry, driver-reset and bus recovery, callback discipline, legacy shim, "
       "six-radio lossy load");
}
