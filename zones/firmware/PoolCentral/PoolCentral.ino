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

constexpr const char *FIRMWARE_VERSION = "poolcentral-3.0.0";
constexpr uint8_t SDA_PIN = 8, SCL_PIN = 9, CHANNEL = ESPNOW_CHANNEL;
constexpr uint32_t HEALTH_MS = 500, RECOVERY_MS = 1000, AUDIT_MS = 20, STATUS_MS = 1000;
constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Latest frame per radio, handed over by the Wi-Fi task. Only the newest matters: the
// slot is state, not a stream, and the sequence filter sorts out ordering.
struct Incoming {
  PoolState state;
  uint32_t at;
  bool legacy;
};
Incoming inbox[POOL_RADIO_COUNT] = {};
uint8_t pendingRadios = 0;
portMUX_TYPE radioMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t packets = 0, legacyPackets = 0, rejected = 0, lastPacket = 0;

RadioSlot radios[POOL_RADIO_COUNT] = {};
uint32_t epoch = 0;

struct BoardState {
  uint8_t address;
  bool online = false;
  uint8_t mode1 = 255, mode2 = 255;
  uint32_t lastOk = 0;
};
BoardState boards[2] = {{0x40}, {0x41}};
bool busStarted = false, radioReady = false, peerReady = false;
uint32_t i2cErrors = 0, mismatches = 0, recoveries = 0, logDrops = 0;
uint32_t desired = 0, verified = 0, known = 0;
uint32_t lastHealth = 0, lastAudit = 0, lastStatus = 0, lastRecovery = 0, lastBeacon = 0;
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
void onReceive(const esp_now_recv_info_t *, const uint8_t *data, int length) {
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
    if (parsed.radioId < 1 || parsed.radioId > POOL_RADIO_COUNT) return;
    legacy = true;
  } else {
    return;
  }
  uint8_t i = parsed.radioId - 1;
  uint32_t now = millis();
  portENTER_CRITICAL(&radioMux);
  inbox[i] = {parsed, now, legacy};
  pendingRadios |= uint8_t(1 << i);
  ++packets;
  if (legacy) ++legacyPackets;
  lastPacket = now;
  portEXIT_CRITICAL(&radioMux);
}

void takeRadios() {
  Incoming snapshot[POOL_RADIO_COUNT];
  uint8_t pending;
  portENTER_CRITICAL(&radioMux);
  memcpy(snapshot, inbox, sizeof(snapshot));
  pending = pendingRadios;
  pendingRadios = 0;
  portEXIT_CRITICAL(&radioMux);

  uint32_t now = millis();
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) {
    bool wasHolding = !expired(radios[i], now);
    uint8_t heldMember = radios[i].member;
    if (pending & (1 << i)) {
      const Incoming &in = snapshot[i];
      bool accepted = in.legacy
        ? acceptLegacy(radios[i], in.state.radioId, in.state.active != 0, in.state.member, in.at)
        : acceptState(radios[i], in.state, in.at);
      if (!accepted) ++rejected;
      else if (radios[i].active && (!wasHolding || heldMember != radios[i].member))
        logLine("RADIO %u -> MEMBER %u%s", i + 1, radios[i].member, radios[i].legacy ? " (LEGACY)" : "");
      else if (!radios[i].active && wasHolding) logLine("RADIO %u RELEASE", i + 1);
    }
    if (wasHolding && expired(radios[i], now) && radios[i].active) logLine("RADIO TIMEOUT: %u", i + 1);
  }
  desired = arbitrate(radios, now);
}

void failBoard(uint8_t b, const char *operation, int code) {
  ++i2cErrors;
  boards[b].online = false;
  known &= ~boardMask(b);
  verified &= ~boardMask(b);
  logLine("I2C ERROR addr=0x%02X op=%s code=%d SDA=%d SCL=%d", boards[b].address, operation, code,
          digitalRead(SDA_PIN), digitalRead(SCL_PIN));
}

bool writeBytes(uint8_t b, uint8_t reg, const uint8_t *data, size_t count) {
  if (!busStarted) return false;
  Wire.beginTransmission(boards[b].address);
  Wire.write(reg);
  Wire.write(data, count);
  uint8_t error = Wire.endTransmission(true);
  if (error) { failBoard(b, "write", error); return false; }
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
  if (!readMode(b)) return false;
  // Clear ALL_LED. If it survives a brownout with FULL_ON set, no per-channel write can
  // turn a light off - the defect the legacy controller's init left in place.
  const uint8_t off[4] = {0, 0, 0, 0x10};
  if (!writeBytes(b, 0xFA, off, 4)) return false;
  boards[b].online = true;
  logLine("I2C READY addr=0x%02X mode1=0x%02X mode2=0x%02X", boards[b].address, boards[b].mode1, boards[b].mode2);
  return true;
}

// Write (optionally) and always read back. A write is only cached as applied once the
// register reads back correct, so a NACK leaves the member pending and it is retried.
bool verifyMember(uint8_t member, bool on, bool write) {
  uint8_t b = member > 16, channel = uint8_t(member - (b ? 17 : 1));
  if (!boards[b].online) return false;
  uint8_t expected[4], actual[4];
  encodeOutput(on, expected);
  if (write && !writeBytes(b, uint8_t(6 + 4 * channel), expected, 4)) return false;
  if (!readBytes(b, uint8_t(6 + 4 * channel), actual, 4)) return false;
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

void status() {
  uint32_t count, legacyCount, bad, seen;
  portENTER_CRITICAL(&radioMux);
  count = packets; legacyCount = legacyPackets; bad = rejected; seen = lastPacket;
  portEXIT_CRITICAL(&radioMux);
  uint8_t actualChannel = 0;
  wifi_second_chan_t secondary;
  esp_wifi_get_channel(&actualChannel, &secondary);
  uint32_t now = millis();
  logLine("{\"device\":\"PoolCentral\",\"version\":3,\"firmware\":\"%s\",\"uptime_ms\":%lu,\"channel\":%u,"
          "\"radio_ready\":%s,\"epoch\":%lu,\"radio_mask\":%u,\"rx_packets\":%lu,\"rx_legacy\":%lu,"
          "\"rx_rejected\":%lu,\"last_rx_ms\":%lu,\"desired\":%lu,\"verified\":%lu,\"known\":%lu,"
          "\"i2c_errors\":%lu,\"mismatches\":%lu,\"recoveries\":%lu,\"log_drops\":%lu,\"sda\":%d,\"scl\":%d,"
          "\"boards\":[{\"addr\":64,\"online\":%s,\"mode1\":%u,\"mode2\":%u},{\"addr\":65,\"online\":%s,\"mode1\":%u,\"mode2\":%u}]}",
          FIRMWARE_VERSION, (unsigned long)now, actualChannel, radioReady ? "true" : "false",
          (unsigned long)epoch, radioMask(radios, now), (unsigned long)count, (unsigned long)legacyCount,
          (unsigned long)bad, (unsigned long)(now - seen), (unsigned long)desired, (unsigned long)verified,
          (unsigned long)known, (unsigned long)i2cErrors, (unsigned long)mismatches, (unsigned long)recoveries,
          (unsigned long)logDrops, digitalRead(SDA_PIN), digitalRead(SCL_PIN),
          boards[0].online ? "true" : "false", boards[0].mode1, boards[0].mode2,
          boards[1].online ? "true" : "false", boards[1].mode1, boards[1].mode2);
  for (uint8_t i = 0; i < POOL_RADIO_COUNT; ++i) {
    const RadioSlot &r = radios[i];
    logLine("{\"device\":\"PoolCentral\",\"type\":\"radio\",\"id\":%u,\"known\":%s,\"holding\":%s,"
            "\"member\":%u,\"seq\":%u,\"lease_ms\":%u,\"legacy\":%s,\"seen_ms\":%lu}",
            i + 1, r.valid ? "true" : "false", expired(r, now) ? "false" : "true", r.member, r.seq,
            r.leaseMs, r.legacy ? "true" : "false", (unsigned long)(r.valid ? now - r.seen : 0));
  }
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
      } else if (!overflow && (!strcmp(input, "TEST_SLEEP 64") || !strcmp(input, "TEST_SLEEP 65"))) {
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

void setup() {
  Serial.setTxBufferSize(4096); Serial.begin(115200); Serial.setTxTimeoutMs(0);
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
  for (auto &r : radios) r = RadioSlot{};
  desired = verified = known = 0;
  if (recoverBus()) for (uint8_t b = 0; b < 2; ++b) initializeBoard(b);
  logLine("POOL CENTRAL %s MAC=%s channel=%u epoch=%lu", FIRMWARE_VERSION, WiFi.macAddress().c_str(),
          CHANNEL, (unsigned long)epoch);
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
