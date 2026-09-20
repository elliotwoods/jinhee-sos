// NCT IMMERSIVE DEEP - POOL CENTRAL CONTROLLER
//
// Receives PoolState frames from the six PoolZone slider radios and drives 23 member
// frame lights through two PCA9685 boards. Arbitration is pure OR: a frame is lit while
// ANY radio holds that member.
//
// Replaces live files/PoolZone_Central_Controiler, which had three defects that made the
// installation unstable when several sliders were used at once:
//   - radios[] was shared between the ESP-NOW callback and loop() with no critical
//     section, and the callback blocked on Serial.print inside the Wi-Fi task;
//   - Wire.endTransmission()'s return code was discarded while the shadow cache was
//     updated anyway, so a single NACK desynchronised a light until reboot;
//   - modem sleep was left on and ALL_LED was never cleared at init.
// Those fixes were verified on hardware as PoolCentralTest v2 (poolzone_test/E2E_RESULTS.md).
// This firmware keeps them and adds the sequenced, acknowledged link the radios now use.
//
// ESP32-C3, I2C SDA 8 / SCL 9, PCA9685 at 0x40 (members 1-16) and 0x41 (members 17-23).
// Senders are tracked one slot per MAC address, not per configured radio id: see
// POOL_SLOT_COUNT in PoolArbiter.h. The id a board reports is a label only.
// The channels drive relays, not lamps, and the two boards' relays are wired opposite ways
// round: see POOL_ACTIVE_LOW_OUTPUTS in PoolOutput.h. The
// outputs are not wired to the frames in order: see POOL_OUTPUT_FOR_MEMBER. Logs, telemetry
// and the radio protocol are always in FRAME numbers, never relay state or output index.
// ESP-NOW channel 2. Not a zone board: no zcfg/zdb partitions, not a zone-flasher target.
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdarg.h>
#include <NctPoolProtocol.h>
#include "PoolOutput.h"
#include "PoolArbiter.h"

using namespace nctzone;
using namespace nctpool;

constexpr const char *FIRMWARE_VERSION = "poolcentral-4.2.0";
constexpr uint8_t SDA_PIN = 8, SCL_PIN = 9, CHANNEL = ESPNOW_CHANNEL;
constexpr uint32_t HEALTH_MS = 500, RECOVERY_MS = 1000, AUDIT_MS = 20, STATUS_MS = 1000;
constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Latest frame per SENDER, handed over by the Wi-Fi task. Keyed by the ESP-NOW source
// address rather than the radio id in the packet, so two boards configured alike cannot
// overwrite one another here either. Only the newest frame matters: a slot is state, not a
// stream, and the sequence filter sorts out ordering.
struct Incoming {
  bool used;
  uint8_t mac[6];
  PoolState state;
  uint32_t at;
  bool legacy;
};
Incoming inbox[POOL_SLOT_COUNT] = {};
bool inboxPending = false;
portMUX_TYPE radioMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t packets = 0, legacyPackets = 0, rejected = 0, lastPacket = 0;
uint32_t noSlot = 0, inboxOverruns = 0, lastClashLog = 0;

RadioSlot radios[POOL_SLOT_COUNT] = {};
uint32_t epoch = 0;

// A relay coil switching injects exactly the kind of supply dip and EMI that corrupts an
// I2C transaction, and since the rewire it is the LIT state that energises a coil. One
// glitched transaction must not tear the board down: recovery bit-bangs the bus and
// rewrites ALL_LED, which darkens every lamp on that board for tens of milliseconds -
// easily long enough for a relay to drop out and pick up again.
constexpr uint8_t I2C_FAILURES_BEFORE_OFFLINE = 3;

struct BoardState {
  uint8_t address;
  bool online = false;
  uint8_t mode1 = 255, mode2 = 255;
  uint32_t lastOk = 0;
  uint8_t failures = 0;  // consecutive; any success clears it
};
BoardState boards[2] = {{0x40}, {0x41}};
bool busStarted = false, radioReady = false, peerReady = false;
uint32_t i2cErrors = 0, mismatches = 0, recoveries = 0, logDrops = 0;
uint32_t desired = 0, verified = 0, known = 0;
uint32_t lastHealth = 0, lastAudit = 0, lastStatus = 0, lastRecovery = 0, lastBeacon = 0;

// Explicitly armed output test, for checking the relay wiring without a slider. Leases
// itself so a forgotten arm cannot hold the show: it releases back to the radios after
// OUTPUT_TEST_MS and says so.
constexpr uint32_t ALL_MEMBERS = 0x7FFFFFu;  // every frame, as a member bitmask
constexpr uint32_t OUTPUT_TEST_MS = 120000;
uint32_t testUntil = 0, testDesired = 0;
bool testArmed() { return testUntil && int32_t(testUntil - millis()) > 0; }
uint8_t auditMember = 1;

// Single loop-task producer. Never wait for a USB monitor to consume output: losing a log
// line is counted, and must never delay light control.
void logLine(const char *format, ...) {
  char line[1000];
  va_list args; va_start(args, format);
  int count = vsnprintf(line, sizeof(line) - 2, format, args); va_end(args);
  if (count < 0) return;
  size_t length = size_t(count) < sizeof(line) - 2 ? size_t(count) : sizeof(line) - 2;
  line[length++] = '\n';
  if (Serial && Serial.availableForWrite() >= int(length)) Serial.write((uint8_t *)line, length);
  else ++logDrops;
}

// Runs on the Wi-Fi task. Parse and hand over, nothing else: no Serial, no I2C, no
// arbitration. Everything that can block belongs in the loop.
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (!info || !info->src_addr) return;
  PoolState parsed = {};
  bool legacy = false;
  if (poolFrameType(data, length) == POOL_STATE) {
    memcpy(&parsed, data, sizeof(parsed));
    if (!poolStateValid(parsed)) return;
  } else if (length == POOL_LEGACY_SIZE) {
    uint32_t magic;
    memcpy(&magic, data, sizeof(magic));
    if (magic != POOL_LEGACY_MAGIC) return;
    parsed.radioId = data[4];
    parsed.active = data[5];
    parsed.member = data[6];
    legacy = true;
  } else {
    return;
  }
  uint32_t now = millis();
  portENTER_CRITICAL(&radioMux);
  // One mailbox entry per sender. Prefer this sender's own entry, then a free one, then
  // the stalest - so a burst from one board can never displace another board's latest
  // state, which is the whole point of keying on the address.
  Incoming *slot = nullptr, *spare = nullptr, *stalest = nullptr;
  for (Incoming &e : inbox) {
    if (e.used && sameMac(e.mac, info->src_addr)) { slot = &e; break; }
    if (!e.used) { if (!spare) spare = &e; continue; }
    if (!stalest || uint32_t(now - e.at) > uint32_t(now - stalest->at)) stalest = &e;
  }
  if (!slot) slot = spare ? spare : stalest;
  if (slot == stalest && !spare) ++inboxOverruns;
  slot->used = true;
  memcpy(slot->mac, info->src_addr, 6);
  slot->state = parsed;
  slot->at = now;
  slot->legacy = legacy;
  inboxPending = true;
  ++packets;
  if (legacy) ++legacyPackets;
  lastPacket = now;
  portEXIT_CRITICAL(&radioMux);
}

// Short label for logs: the claimed radio id plus the last two bytes of the address, so
// two boards calling themselves the same thing are still tellable apart at a glance.
void slotName(const RadioSlot &s, char *out, size_t size) {
  snprintf(out, size, "%u@%02X%02X", s.radioId, s.mac[4], s.mac[5]);
}

void takeRadios() {
  Incoming snapshot[POOL_SLOT_COUNT];
  bool pending;
  portENTER_CRITICAL(&radioMux);
  memcpy(snapshot, inbox, sizeof(snapshot));
  pending = inboxPending;
  inboxPending = false;
  for (Incoming &e : inbox) e.used = false;
  portEXIT_CRITICAL(&radioMux);

  uint32_t now = millis();
  if (pending) {
    for (const Incoming &in : snapshot) {
      if (!in.used) continue;
      RadioSlot *slot = slotFor(radios, in.mac, now);
      if (!slot) {
        // Every slot belongs to a board that is still live, so there is nothing safe to
        // reclaim. Dropping the newcomer is better than unlighting a working slider.
        ++noSlot;
        continue;
      }
      bool wasHolding = !expired(*slot, now);
      uint8_t heldMember = slot->member;
      bool accepted = in.legacy
        ? acceptLegacy(*slot, in.state.radioId, in.state.active != 0, in.state.member, in.at)
        : acceptState(*slot, in.state, in.at);
      char label[16];
      slotName(*slot, label, sizeof(label));
      if (!accepted) ++rejected;
      else if (slot->active && (!wasHolding || heldMember != slot->member))
        logLine("RADIO %s -> MEMBER %u%s", label, slot->member, slot->legacy ? " (LEGACY)" : "");
      else if (!slot->active && wasHolding) logLine("RADIO %s RELEASE", label);
    }
  }
  for (RadioSlot &slot : radios) {
    if (!slot.valid) continue;
    if (slot.active && uint32_t(now - slot.seen) > slot.leaseMs) {
      char label[16];
      slotName(slot, label, sizeof(label));
      logLine("RADIO TIMEOUT: %s", label);
      slot.active = false;   // logged once; the lease has lapsed either way
    }
    refreshHold(slot, now);
  }
  // An armed test speaks for the outputs instead of the radios, so what is on the lamps is
  // exactly what was asked for and nothing else.
  if (testArmed()) desired = testDesired;
  else {
    if (testUntil) { testUntil = 0; logLine("OUTPUT TEST expired; radios back in control"); }
    desired = arbitrate(radios, now);
  }

  // Not a fault any more - the boards have separate slots - but it means the labels lie.
  uint8_t clashing = claimedIdClashes(radios, now);
  if (clashing && now - lastClashLog >= 30000) {
    lastClashLog = now;
    logLine("NOTE %u live boards share a radio id with another. Slots are keyed by address so "
            "this is harmless, but the ids no longer identify anything.", clashing);
  }
}

void failBoard(uint8_t b, const char *operation, int code) {
  ++i2cErrors;
  bool giveUp = ++boards[b].failures >= I2C_FAILURES_BEFORE_OFFLINE;
  if (giveUp) {
    boards[b].online = false;
    known &= ~boardMask(b);
    verified &= ~boardMask(b);
  }
  logLine("I2C ERROR addr=0x%02X op=%s code=%d fails=%u%s SDA=%d SCL=%d", boards[b].address, operation, code,
          boards[b].failures, giveUp ? " OFFLINE" : " retrying", digitalRead(SDA_PIN), digitalRead(SCL_PIN));
}

bool writeBytes(uint8_t b, uint8_t reg, const uint8_t *data, size_t count) {
  if (!busStarted) return false;
  Wire.beginTransmission(boards[b].address);
  Wire.write(reg);
  Wire.write(data, count);
  uint8_t error = Wire.endTransmission(true);
  if (error) { failBoard(b, "write", error); return false; }
  boards[b].failures = 0;
  return true;
}

bool readBytes(uint8_t b, uint8_t reg, uint8_t *data, size_t count) {
  if (!busStarted) return false;
  Wire.beginTransmission(boards[b].address);
  Wire.write(reg);
  uint8_t error = Wire.endTransmission(false);
  if (error) { failBoard(b, "read-address", error); return false; }
  size_t received = Wire.requestFrom(boards[b].address, count, true);
  if (received != count) {
    while (Wire.available()) Wire.read();
    failBoard(b, "read-data", int(received));
    return false;
  }
  for (size_t i = 0; i < count; ++i) data[i] = uint8_t(Wire.read());
  boards[b].lastOk = millis();
  boards[b].failures = 0;
  return true;
}

// NXP bus-clear sequence: open-drain only; never drive a line high against a slave.
// Bounded clock-stretch wait. SCL stuck low needs peripheral or wiring repair.
bool recoverBus() {
  if (busStarted) Wire.end();
  busStarted = false;
  pinMode(SDA_PIN, INPUT_PULLUP); pinMode(SCL_PIN, INPUT_PULLUP);
  delayMicroseconds(50);
  int beforeSda = digitalRead(SDA_PIN), beforeScl = digitalRead(SCL_PIN), pulses = 0;
  if (beforeScl && !beforeSda) {
    digitalWrite(SCL_PIN, HIGH); pinMode(SCL_PIN, OUTPUT_OPEN_DRAIN);
    for (int i = 0; i < 9 && !digitalRead(SDA_PIN); ++i) {
      digitalWrite(SCL_PIN, LOW); delayMicroseconds(10);
      digitalWrite(SCL_PIN, HIGH);
      for (int wait = 0; wait < 100 && !digitalRead(SCL_PIN); ++wait) delayMicroseconds(20);
      delayMicroseconds(10); ++pulses;
      if (!digitalRead(SCL_PIN)) break;
    }
    if (digitalRead(SCL_PIN)) {
      digitalWrite(SCL_PIN, LOW);
      digitalWrite(SDA_PIN, LOW); pinMode(SDA_PIN, OUTPUT_OPEN_DRAIN);
      delayMicroseconds(10); digitalWrite(SCL_PIN, HIGH); delayMicroseconds(10);
      digitalWrite(SDA_PIN, HIGH); delayMicroseconds(10);
    }
    pinMode(SDA_PIN, INPUT_PULLUP); pinMode(SCL_PIN, INPUT_PULLUP);
  }
  bool clear = digitalRead(SDA_PIN) && digitalRead(SCL_PIN);
  logLine("I2C BUS sda_before=%d scl_before=%d sda_after=%d scl_after=%d pulses=%d", beforeSda, beforeScl,
          digitalRead(SDA_PIN), digitalRead(SCL_PIN), pulses);
  if (clear) {
    busStarted = Wire.begin(SDA_PIN, SCL_PIN, 100000);
    Wire.setTimeOut(25);
  }
  return busStarted;
}

bool readMode(uint8_t b) {
  // Read individually: a peripheral reset may have cleared auto-increment.
  if (!readBytes(b, 0, &boards[b].mode1, 1) || !readBytes(b, 1, &boards[b].mode2, 1)) return false;
  if (!validMode(boards[b].mode1, boards[b].mode2)) {
    ++mismatches;
    boards[b].online = false;
    known &= ~boardMask(b);
    verified &= ~boardMask(b);
    logLine("I2C MODE MISMATCH addr=0x%02X mode1=0x%02X mode2=0x%02X", boards[b].address, boards[b].mode1, boards[b].mode2);
    return false;
  }
  return true;
}

bool initializeBoard(uint8_t b) {
  boards[b].online = false;
  known &= ~boardMask(b);
  verified &= ~boardMask(b);
  // AI enabled, awake, internal oscillator. MODE2 matches the legacy power-on default.
  uint8_t mode1 = 0x20, mode2 = 0x04;
  if (!writeBytes(b, 0, &mode1, 1) || !writeBytes(b, 1, &mode2, 1)) return false;
  delayMicroseconds(500);  // oscillator settling, per the PCA9685 datasheet
  // Clear ALL_LED to the DARK state, derived from encodeOutput so it follows the relay
  // polarity: with active-low relays a hardcoded FULL_OFF here would light every frame.
  // Done before the MODE readback so a board spends as little time as possible in the
  // power-on state. If a stale ALL_LED override survives a brownout, no per-channel write
  // can move a lamp - the defect the legacy controller's init left in place.
  // ALL_LED can only say one thing for all sixteen channels, so it is only usable when this
  // board's outputs share a polarity. They do here (one relay module per board), but a mixed
  // board would be silently half-lit by it, so check rather than assume: darkenOutputs()
  // writes every channel explicitly straight afterwards either way.
  bool activeLow = false;
  if (boardPolarityUniform(b, &activeLow)) {
    uint8_t dark[4];
    encodeOutputFor(activeLow ? 17 : 1, false, dark);  // any output with this board's polarity
    if (!writeBytes(b, 0xFA, dark, 4)) return false;
  }
  if (!readMode(b)) return false;
  boards[b].online = true;
  boards[b].failures = 0;
  logLine("I2C READY addr=0x%02X mode1=0x%02X mode2=0x%02X", boards[b].address, boards[b].mode1, boards[b].mode2);
  return true;
}

// Write (optionally) and always read back. A write is only cached as applied once the
// register reads back correct, so a NACK leaves the member pending and it is retried.
bool verifyMember(uint8_t member, bool on, bool write) {
  uint8_t b = memberBoard(member), channel = memberChannel(member);  // wiring map, not identity
  if (!boards[b].online) return false;
  uint8_t expected[4], actual[4];
  encodeOutput(member, on, expected);
  if ((write && !writeBytes(b, uint8_t(6 + 4 * channel), expected, 4)) ||
      !readBytes(b, uint8_t(6 + 4 * channel), actual, 4)) {
    known &= ~memberBit(member);  // never cache a write that was not acknowledged
    verified &= ~memberBit(member);
    return false;
  }
  if (memcmp(expected, actual, 4)) {
    ++mismatches;
    known &= ~memberBit(member);
    verified &= ~memberBit(member);
    logLine("I2C READBACK MISMATCH member=%u got=%02X%02X%02X%02X", member, actual[0], actual[1], actual[2], actual[3]);
    return false;
  }
  bool wasKnown = known & memberBit(member), wasOn = verified & memberBit(member);
  known |= memberBit(member);
  if (on) verified |= memberBit(member); else verified &= ~memberBit(member);
  if (!wasKnown || wasOn != on) logLine("FRAME %u %s", member, on ? "ON" : "OFF");
  return true;
}

void maintainOutputs() {
  uint32_t now = millis();
  if ((!boards[0].online || !boards[1].online) && now - lastRecovery >= RECOVERY_MS) {
    lastRecovery = now;
    ++recoveries;
    // Do not disturb a healthy board over an address NACK. Clear the bus only when a line
    // is held low or the peripheral driver is not running.
    bool clear = busStarted && digitalRead(SDA_PIN) && digitalRead(SCL_PIN);
    if (!clear) {
      for (auto &b : boards) b.online = false;
      known = verified = 0;
      clear = recoverBus();
    }
    if (clear) for (uint8_t b = 0; b < 2; ++b) if (!boards[b].online) initializeBoard(b);
    takeRadios();  // recovery must not reapply a lease that expired while it was blocked
  }
  if (now - lastHealth >= HEALTH_MS) {
    lastHealth = now;
    for (uint8_t b = 0; b < 2; ++b) if (boards[b].online) readMode(b);
    takeRadios();
  }
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    uint32_t bit = memberBit(m);
    if (!(known & bit) || bool(desired & bit) != bool(verified & bit)) verifyMember(m, desired & bit, true);
  }
  // Audit unchanged outputs too, so a silently reset or corrupted PCA register is caught
  // even while nothing is changing.
  if (now - lastAudit >= AUDIT_MS) {
    lastAudit = now;
    verifyMember(auditMember, desired & memberBit(auditMember), false);
    auditMember = uint8_t(auditMember % POOL_MEMBER_COUNT + 1);
  }
}

// Broadcast, because the central does not learn a radio's MAC until it has heard from it.
// Radios latch the source address of this frame and unicast their state back.
void sendBeacon() {
  if (!radioReady || !peerReady) return;
  PoolBeacon beacon = {};
  fillHeader(beacon.h, POOL_BEACON);
  beacon.epoch = epoch;
  beacon.uptimeS = millis() / 1000;
  beacon.channel = CHANNEL;
  beacon.radioMask = radioMask(radios, millis());
  beacon.version = POOL_PROTOCOL_VERSION;
  esp_now_send(BROADCAST_MAC, (const uint8_t *)&beacon, sizeof(beacon));
}

uint8_t slotsUsed() {
  uint8_t used = 0;
  for (const RadioSlot &r : radios) if (r.valid) ++used;
  return used;
}

void status() {
  uint32_t count, legacyCount, bad, seen;
  portENTER_CRITICAL(&radioMux);
  count = packets; legacyCount = legacyPackets; bad = rejected; seen = lastPacket;
  portEXIT_CRITICAL(&radioMux);
  uint32_t dropped, overruns;
  portENTER_CRITICAL(&radioMux);
  dropped = noSlot; overruns = inboxOverruns;
  portEXIT_CRITICAL(&radioMux);
  uint8_t actualChannel = 0;
  wifi_second_chan_t secondary;
  esp_wifi_get_channel(&actualChannel, &secondary);
  uint32_t now = millis();
  // The per-radio lines below carry the same device name, so the summary is typed and
  // consumers must select on it rather than taking the last matching line.
  logLine("{\"device\":\"PoolCentral\",\"type\":\"status\",\"version\":3,\"firmware\":\"%s\",\"uptime_ms\":%lu,\"channel\":%u,"
          "\"radio_ready\":%s,\"epoch\":%lu,\"radio_mask\":%u,\"rx_packets\":%lu,\"rx_legacy\":%lu,"
          "\"rx_rejected\":%lu,\"rx_no_slot\":%lu,\"rx_overruns\":%lu,\"id_clashes\":%u,\"slots_used\":%u,\"last_rx_ms\":%lu,\"desired\":%lu,\"verified\":%lu,\"known\":%lu,"
          "\"i2c_errors\":%lu,\"mismatches\":%lu,\"recoveries\":%lu,\"log_drops\":%lu,\"sda\":%d,\"scl\":%d,"
          "\"boards\":[{\"addr\":64,\"online\":%s,\"mode1\":%u,\"mode2\":%u},{\"addr\":65,\"online\":%s,\"mode1\":%u,\"mode2\":%u}]}",
          FIRMWARE_VERSION, (unsigned long)now, actualChannel, radioReady ? "true" : "false",
          (unsigned long)epoch, radioMask(radios, now), (unsigned long)count, (unsigned long)legacyCount,
          (unsigned long)bad, (unsigned long)dropped, (unsigned long)overruns, claimedIdClashes(radios, now),
          slotsUsed(), (unsigned long)(now - seen), (unsigned long)desired, (unsigned long)verified,
          (unsigned long)known, (unsigned long)i2cErrors, (unsigned long)mismatches, (unsigned long)recoveries,
          (unsigned long)logDrops, digitalRead(SDA_PIN), digitalRead(SCL_PIN),
          boards[0].online ? "true" : "false", boards[0].mode1, boards[0].mode2,
          boards[1].online ? "true" : "false", boards[1].mode1, boards[1].mode2);
  // One line per KNOWN SENDER, addressed by MAC. `id` is only what that board calls
  // itself; nothing here is routed on it.
  for (const RadioSlot &r : radios) {
    if (!r.valid) continue;
    logLine("{\"device\":\"PoolCentral\",\"type\":\"radio\",\"mac\":\"%02X:%02X:%02X:%02X:%02X:%02X\","
            "\"id\":%u,\"holding\":%s,\"member\":%u,\"seq\":%u,\"lease_ms\":%u,\"legacy\":%s,\"seen_ms\":%lu}",
            r.mac[0], r.mac[1], r.mac[2], r.mac[3], r.mac[4], r.mac[5],
            r.radioId, expired(r, now) ? "false" : "true", r.member, r.seq,
            r.leaseMs, r.legacy ? "true" : "false", (unsigned long)(now - r.seen));
  }
}

// Read every member's registers back and say, in plain terms, what the driver is being
// told to do. The one place that reports the electrical level as well as the lamp state,
// so a wiring question can be answered without a meter.
void outputDump() {
  logLine("OUTPUT polarity by output: active-low mask=0x%06lX (0x40 outputs 1-16, 0x41 outputs 17-23)",
          (unsigned long)POOL_ACTIVE_LOW_OUTPUTS);
  for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m) {
    uint8_t b = memberBoard(m), channel = memberChannel(m), actual[4];
    if (!boards[b].online || !readBytes(b, uint8_t(6 + 4 * channel), actual, 4)) {
      logLine("OUT frame=%2u output=%2u addr=0x%02X ch=%2u UNREADABLE", m, outputForMember(m), boards[b].address, channel);
      continue;
    }
    uint8_t out = outputForMember(m);
    bool high = (actual[1] & 0x10) != 0;   // FULL_ON bit set => channel driven high
    bool lamp = outputActiveLow(out) ? !high : high;
    logLine("OUT frame=%2u output=%2u addr=0x%02X ch=%2u %s regs=%02X%02X%02X%02X level=%s lamp=%s%s",
            m, out, boards[b].address, channel, outputActiveLow(out) ? "act-low " : "act-high",
            actual[0], actual[1], actual[2], actual[3],
            high ? "HIGH" : "LOW ", lamp ? "ON " : "OFF",
            (desired & memberBit(m)) == (lamp ? memberBit(m) : 0u) ? "" : "  <-- DISAGREES WITH REQUEST");
  }
}

void outputCommand(const char *rest) {
  if (!strcmp(rest, "DISARM")) {
    testUntil = 0; testDesired = 0;
    logLine("OUTPUT TEST disarmed; radios back in control");
    return;
  }
  if (!strcmp(rest, "ARM")) {
    testUntil = millis() + OUTPUT_TEST_MS;
    testDesired = 0;
    logLine("OUTPUT TEST armed for %lus; all frames off. OUT <1-%u|ALL> ON|OFF, OUT DISARM to release.",
            (unsigned long)(OUTPUT_TEST_MS / 1000), POOL_MEMBER_COUNT);
    return;
  }
  if (!testArmed()) { logLine("ERR OUT: send OUT ARM first"); return; }
  char target[8] = {};
  char state[8] = {};
  if (sscanf(rest, "%7s %7s", target, state) != 2) { logLine("ERR OUT: expected OUT <1-%u|ALL> ON|OFF", POOL_MEMBER_COUNT); return; }
  bool on = !strcmp(state, "ON");
  if (!on && strcmp(state, "OFF")) { logLine("ERR OUT: expected ON or OFF"); return; }
  testUntil = millis() + OUTPUT_TEST_MS;  // any command renews the lease
  if (!strcmp(target, "ALL")) {
    testDesired = on ? ALL_MEMBERS : 0;
    logLine("OUTPUT TEST all frames %s", on ? "ON" : "OFF");
    return;
  }
  int member = atoi(target);
  if (member < 1 || member > POOL_MEMBER_COUNT) { logLine("ERR OUT: frame must be 1-%u", POOL_MEMBER_COUNT); return; }
  if (on) testDesired |= memberBit(uint8_t(member)); else testDesired &= ~memberBit(uint8_t(member));
  logLine("OUTPUT TEST frame %d %s (output %u on 0x%02X ch %u)", member, on ? "ON" : "OFF",
          outputForMember(uint8_t(member)), boards[memberBoard(uint8_t(member))].address,
          memberChannel(uint8_t(member)));
}

void serialCommands() {
  static char input[48];
  static size_t used = 0;
  static bool overflow = false;
  for (int i = 0; i < 64 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      input[used] = 0;
      if (!overflow && !strcmp(input, "STATUS")) status();
      else if (!overflow && !strcmp(input, "RECOVER")) {
        ++recoveries;
        known = verified = 0;
        for (auto &b : boards) b.online = false;
        if (recoverBus()) for (uint8_t b = 0; b < 2; ++b) initializeBoard(b);
        takeRadios(); maintainOutputs(); status();
      } else if (!overflow && !strcmp(input, "OUT DUMP")) outputDump();
      else if (!overflow && !strncmp(input, "OUT ", 4)) outputCommand(input + 4);
      else if (!overflow && (!strcmp(input, "TEST_SLEEP 64") || !strcmp(input, "TEST_SLEEP 65"))) {
        // Maintenance fault injection for exercising brownout/reset recovery. This briefly
        // disturbs live lights; it is not part of normal operation.
        uint8_t b = input[12] == '4' ? 0 : 1, sleep = 0x10;
        writeBytes(b, 0, &sleep, 1);
        logLine("TEST SLEEP addr=0x%02X", boards[b].address);
      } else logLine("ERR command");
      used = 0; overflow = false;
    } else if (used < sizeof(input) - 1) input[used++] = c;
    else overflow = true;
  }
}

// Put every lamp out and prove it, before anything slower runs.
//
// A PCA9685 powers up with every channel FULL_OFF, which drives it LOW - and a LOW channel
// energises a relay coil, so from the moment the boards have power the hardware is asking
// for all 23 lamps to be on. Nothing makes that safe until this runs. Twenty-three coils
// pulling in at once also sags the supply, so which of them actually latch varies from boot
// to boot. Retry is bounded, so a missing board delays the boot by milliseconds rather than
// stalling it; the ordinary recovery path picks it up from there.
bool darkenOutputs() {
  for (int attempt = 0; attempt < 5; ++attempt) {
    if (!busStarted) recoverBus();
    for (uint8_t b = 0; b < 2; ++b) if (!boards[b].online) initializeBoard(b);
    // ALL_LED darkens all sixteen channels of a board in one write, but only a per-channel
    // readback proves it, and only `known` records that proof. Retry just what is still
    // unproven, so a glitched transaction costs a few milliseconds rather than a re-sweep.
    for (uint8_t m = 1; m <= POOL_MEMBER_COUNT; ++m)
      if (!(known & memberBit(m)) || (verified & memberBit(m))) verifyMember(m, false, true);
    if (known == ALL_MEMBERS && verified == 0) return true;
  }
  return false;
}

void setup() {
  Serial.setTxBufferSize(4096); Serial.begin(115200); Serial.setTxTimeoutMs(0);

  // Outputs first. Bringing up Wi-Fi and ESP-NOW takes hundreds of milliseconds on this
  // chip, and every one of them would be spent with the relays energised.
  for (auto &r : radios) r = RadioSlot{};
  desired = verified = known = 0;
  // Assume nothing about the drivers or the bus: a reset of this chip does not reset them,
  // and after a watchdog or a reflash they may still be holding lamps on.
  busStarted = false;
  for (uint8_t b = 0; b < 2; ++b) {
    boards[b].online = false;
    boards[b].failures = 0;
    boards[b].mode1 = boards[b].mode2 = 255;
  }
  bool dark = darkenOutputs();

  WiFi.persistent(false); WiFi.setAutoReconnect(false);
  // setSleep(false) matters: modem sleep duty-cycles the receiver and silently drops
  // frames, which the legacy controller never disabled.
  radioReady = WiFi.mode(WIFI_STA) && WiFi.setSleep(false) &&
               esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK &&
               esp_now_init() == ESP_OK && esp_now_register_recv_cb(onReceive) == ESP_OK;
  if (radioReady && !esp_now_is_peer_exist(BROADCAST_MAC)) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    peerReady = esp_now_add_peer(&peer) == ESP_OK;
  } else if (radioReady) peerReady = true;
  epoch = esp_random();
  if (!epoch) epoch = 1;  // 0 is reserved so a radio can tell "no beacon seen yet"
  logLine("POOL CENTRAL %s MAC=%s channel=%u epoch=%lu outputs=%s", FIRMWARE_VERSION,
          WiFi.macAddress().c_str(), CHANNEL, (unsigned long)epoch, dark ? "dark" : "UNVERIFIED");
}

void loop() {
  takeRadios();
  serialCommands();
  maintainOutputs();
  uint32_t now = millis();
  if (now - lastBeacon >= POOL_BEACON_MS) { lastBeacon = now; sendBeacon(); }
  if (now - lastStatus >= STATUS_MS) { lastStatus = now; status(); }
  delay(1);
}
