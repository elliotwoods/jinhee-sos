#pragma once
// Reader role: the pairing station's PN532 (pairing_station.ino, frozen), ported to the snprintf/
// reply() style of the other Ws headers, plus the tag plates' reader supervision (NctTagPlate.h:
// the IC-byte check on the firmware query, a live health query while no tag is on the reader,
// fast-fail counting, automatic recovery). Same wiring as the station: I2C SDA GPIO4 / SCL GPIO3.
// NctTagPlate.h itself is not included: it drags in the zone database and partitions.
//
//   - Commands, field names and error texts are the station's (nfc_recover / nfc_poll / nfc_status,
//     hello's nfc_ok/nfc_polling/nfc_firmware/nfc_i2c_status/tag_present), so the pairing app
//     and the console drive this reader unchanged.
//   - The reader polls only while a host has asked for it: the station boots with nfcPolling
//     false and the pairing app switches it on with `nfc_poll enabled:true`. A bare dongle
//     relaying zone or show frames therefore never spends the 80 ms read inside its loop, and
//     never toggles GPIO3/4 after boot (automatic recovery runs only while polling is wanted).
//   - Identify gating is the station's: an old tag cannot carry over into a pairing scan. The
//     reader must see the target's interval clear (tag_state present:false) before a `tag` is
//     reported with the operation id, and only once per placement.
//   - Without a reader wired the board still boots and every command answers (ready:false,
//     i2c_status:5), which is how the pairing app already treats a bare dongle.
#include <Wire.h>
#include "Pn532Wire.h"
#include <Adafruit_PN532.h>
#include <string.h>
#include <stdio.h>
#include "WsJson.h"
#include "WsHex.h"

namespace ws {
namespace nfc {

constexpr int SDA_PIN = 4, SCL_PIN = 3;
constexpr uint32_t POLL_INTERVAL_MS = 50, READ_TIMEOUT_MS = 80, LEAVE_TIMEOUT_MS = 700;
// Supervision (pairing_station/I2C_DEBUG.md): a healthy no-tag poll lasts ~READ_TIMEOUT_MS; one that
// returns at once means the I2C command failed. The firmware query is a live check, not a cached flag.
constexpr uint32_t HEALTH_INTERVAL_MS = 3000, FAST_FAIL_MS = 20, RETRY_INTERVAL_MS = 5000;
constexpr int FAST_FAIL_LIMIT = 10;
constexpr uint8_t PN532_IC = 0x32;  // a floating bus can answer the firmware query with garbage

inline Pn532Wire wire;
inline Adafruit_PN532 reader(-1, -1, &wire);
inline bool ok = false, polling = false, tagPresent = false, scanArmed = false, identifying = false;
inline uint32_t firmware = 0, polls = 0, found = 0, lastMs = 0, maxMs = 0;
inline uint32_t lastPoll = 0, lastSeen = 0, lastHealth = 0, lastRetry = 0;
inline uint32_t fastFails = 0, fastFailRun = 0, recoveries = 0;
inline uint8_t i2cStatus = 255, lastUid[10] = {}, lastUidLength = 0;
inline char operationId[41] = "";

// NXP UM10204 bus clear, as the station does it: release both lines and, only if SCL is free while
// SDA is held, clock SCL nine times and STOP. Open-drain outputs never drive a line high against the
// reader. The bus is then restarted at the station's speed and timeout. Returns true when both
// lines are high afterwards.
inline bool recoverBus() {
  wire.end();
  pinMode(SDA_PIN, INPUT_PULLUP);
  pinMode(SCL_PIN, INPUT_PULLUP);
  delay(10);
  int sdaBefore = digitalRead(SDA_PIN), sclBefore = digitalRead(SCL_PIN);
  int pulses = 0;
  if (sclBefore == HIGH && sdaBefore == LOW) {
    digitalWrite(SCL_PIN, HIGH);
    pinMode(SCL_PIN, OUTPUT_OPEN_DRAIN);
    for (int i = 0; i < 9; i++) {
      digitalWrite(SCL_PIN, LOW);
      delayMicroseconds(10);
      digitalWrite(SCL_PIN, HIGH);
      delayMicroseconds(10);
      for (int wait = 0; wait < 100 && digitalRead(SCL_PIN) == LOW; wait++) delayMicroseconds(20);
      pulses++;
      if (digitalRead(SCL_PIN) == LOW) break;
    }
    if (digitalRead(SCL_PIN) == HIGH) {
      digitalWrite(SCL_PIN, LOW);
      digitalWrite(SDA_PIN, LOW);
      pinMode(SDA_PIN, OUTPUT_OPEN_DRAIN);
      delayMicroseconds(10);
      digitalWrite(SCL_PIN, HIGH);
      delayMicroseconds(10);
      digitalWrite(SDA_PIN, HIGH);
      delayMicroseconds(10);
    }
    pinMode(SCL_PIN, INPUT_PULLUP);
    pinMode(SDA_PIN, INPUT_PULLUP);
    delay(10);
  }
  bool clear = digitalRead(SCL_PIN) == HIGH && digitalRead(SDA_PIN) == HIGH;
  char fields[120];
  snprintf(fields, sizeof(fields), "\"sda_before\":%d,\"scl_before\":%d,\"sda_after\":%d,\"scl_after\":%d,\"pulses\":%d",
           sdaBefore, sclBefore, digitalRead(SDA_PIN), digitalRead(SCL_PIN), pulses);
  reply("nfc_bus", "", fields);
  wire.begin(SDA_PIN, SCL_PIN);
  wire.setClock(100000);
  wire.setTimeOut(250);
  return clear;
}

// Only library calls that read their reply back are used: a PN532 command whose reply is left unread
// made the chip hold SCL low until power-cycled (pairing_station/I2C_DEBUG.md).
inline bool beginReader() {
  reader.begin();
  firmware = reader.getFirmwareVersion();
  if (((firmware >> 24) & 0xFF) != PN532_IC) firmware = 0;
  ok = firmware && reader.SAMConfig();
  i2cStatus = ok ? 0 : 5;
  return ok;
}

// Boot, after the radio and before the boot report/hello, so they carry the real nfc_ok. Three
// attempts as the station makes; about 1.8 s at worst without a reader wired.
inline void begin() {
  bool clear = recoverBus();
  delay(300);
  if (!clear) {
    i2cStatus = 5;
    reply("nfc_error", "", "\"detail\":\"I2C line held low after recovery; check reader power/mode and power-cycle it\"");
  }
  for (int attempt = 0; attempt < 3 && clear && !ok; attempt++) {
    beginReader();
    char fields[100];
    snprintf(fields, sizeof(fields), "\"attempt\":%d,\"i2c_status\":%u,\"firmware\":%lu,\"ready\":%s", attempt + 1, i2cStatus,
             (unsigned long)firmware, boolText(ok));
    reply("nfc_init", "", fields);
    if (!ok) delay(400);
  }
  lastHealth = lastRetry = millis();
}

// Force a clear-reader interval AFTER selecting this target: old tags cannot carry over (the
// station's identify, whose synthetic tag_state precedes its radio and identifying events).
inline void beginIdentify(const char *id) {
  scanArmed = false;
  tagPresent = true;
  lastUidLength = 0;
  lastSeen = millis();
  identifying = true;
  snprintf(operationId, sizeof(operationId), "%s", id);
  reply("tag_state", "", "\"present\":true");
}

// The target is released (stop, hello, flash_done, watchdog) or handed to register: no tag may
// be reported against the old operation.
inline void endIdentify() {
  identifying = false;
  scanArmed = false;
}

inline void lost(const char *why) {
  ok = false;
  i2cStatus = 5;
  fastFailRun = 0;
  lastRetry = millis();
  char fields[120];
  snprintf(fields, sizeof(fields), "\"detail\":\"PN532 lost: %s\"", why);
  reply("nfc_error", "", fields);
}

inline void poll(uint32_t now) {
  if (!polling) return;
  if (!ok) {
    // Automatic only while a host asked for polling, so a bare dongle never toggles GPIO3/4 after boot.
    if (uint32_t(now - lastRetry) < RETRY_INTERVAL_MS) return;
    recoveries++;
    if (recoverBus()) beginReader();
    i2cStatus = ok ? 0 : 5;
    lastRetry = lastHealth = millis();
    return;
  }
  if (!tagPresent && uint32_t(now - lastHealth) >= HEALTH_INTERVAL_MS) {
    lastHealth = now;
    if (((reader.getFirmwareVersion() >> 24) & 0xFF) != PN532_IC) { lost("no reply to the firmware query"); return; }
    now = millis();
  }
  if (uint32_t(now - lastPoll) < POLL_INTERVAL_MS) return;
  lastPoll = now;
  uint8_t uid[10] = {}, length = 0;
  polls++;
  bool hit = reader.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &length, READ_TIMEOUT_MS);
  now = millis();
  lastMs = uint32_t(now - lastPoll);
  if (lastMs > maxMs) maxMs = lastMs;
  if (hit) {
    fastFailRun = 0;
  } else if (lastMs < FAST_FAIL_MS) {
    fastFails++;
    if (++fastFailRun >= FAST_FAIL_LIMIT && !tagPresent) { lost("scan commands are failing on the I2C bus"); return; }
  } else {
    fastFailRun = 0;
  }
  // From here the station's tag logic, verbatim.
  if (hit) {
    found++;
    lastSeen = now;
    bool changed = !tagPresent || length != lastUidLength || (length <= 10 && memcmp(uid, lastUid, length));
    tagPresent = true;
    if (changed) {
      reply("tag_state", "", "\"present\":true");
      if ((length == 4 || length == 7) && identifying && scanArmed) {
        char text[32], fields[48];
        colonHex(uid, length, text, sizeof(text));
        snprintf(fields, sizeof(fields), "\"uid\":\"%s\"", text);
        reply("tag", operationId, fields);
      } else if (length != 4 && length != 7) {
        reply("nfc_error", "", "\"detail\":\"Unsupported UID length; remove this tag\"");
      }
    }
    scanArmed = false;
    lastUidLength = length;
    if (length <= 10) memcpy(lastUid, uid, length);
  } else if (uint32_t(now - lastSeen) > LEAVE_TIMEOUT_MS && (tagPresent || (identifying && !scanArmed))) {
    tagPresent = false;
    scanArmed = identifying;
    reply("tag_state", "", "\"present\":false");
  }
}

// The station's `once`: one read now, polling left off afterwards.
inline void pollOnce() {
  polling = true;
  lastPoll = millis() - 100;
  poll(millis());
  polling = false;
}

// ---- host commands (the mode gates are the caller's) ----

inline void recover(const char *id) {
  polling = false;
  ok = false;
  bool clear = recoverBus();
  if (clear) beginReader();
  i2cStatus = ok ? 0 : 5;
  char fields[100];
  snprintf(fields, sizeof(fields), "\"bus_clear\":%s,\"ready\":%s,\"firmware\":%lu,\"i2c_status\":%u", boolText(clear), boolText(ok),
           (unsigned long)firmware, i2cStatus);
  reply("nfc_recovered", id, fields);
}

inline void pollCommand(const char *id, const char *line) {
  bool enabled = false, once = false, trace;
  jsonBool(line, "enabled", enabled);
  polling = enabled;
  if (jsonBool(line, "trace", trace)) pn532TraceAll = trace;
  if (jsonBool(line, "once", once) && once) pollOnce();
  char text[32] = "", fields[160];
  int n = snprintf(fields, sizeof(fields), "\"ready\":%s,\"enabled\":%s,\"polls\":%lu,\"found\":%lu,\"duration_ms\":%lu,\"tag_present\":%s",
                   boolText(ok), boolText(polling), (unsigned long)polls, (unsigned long)found, (unsigned long)lastMs, boolText(tagPresent));
  if (lastUidLength && n > 0 && n < int(sizeof(fields))) {
    colonHex(lastUid, lastUidLength, text, sizeof(text));
    snprintf(fields + n, sizeof(fields) - n, ",\"uid\":\"%s\"", text);
  }
  reply("nfc_poll_result", id, fields);
}

inline void status(const char *id) {
  uint32_t now = reader.getFirmwareVersion();  // a live query, not the cached flag
  char fields[240];
  snprintf(fields, sizeof(fields),
           "\"sda\":%d,\"scl\":%d,\"i2c_status\":%d,\"status_source\":\"firmware_response\",\"firmware_now\":%lu,\"nfc_polling\":%s,"
           "\"polls\":%lu,\"found\":%lu,\"last_poll_ms\":%lu,\"max_poll_ms\":%lu,\"trace\":%s",
           digitalRead(SDA_PIN), digitalRead(SCL_PIN), now ? 0 : 5, (unsigned long)now, boolText(polling), (unsigned long)polls,
           (unsigned long)found, (unsigned long)lastMs, (unsigned long)maxMs, boolText(pn532TraceAll));
  reply("nfc_status", id, fields);
}

// The station's hello fields, in its order.
inline int helloFields(char *out, size_t capacity) {
  return snprintf(out, capacity, "\"nfc_ok\":%s,\"nfc_polling\":%s,\"nfc_firmware\":%lu,\"nfc_i2c_status\":%u,\"tag_present\":%s",
                  boolText(ok), boolText(polling), (unsigned long)firmware, i2cStatus, boolText(tagPresent));
}

// The "?" report line, in the tag plates' printNfc format.
inline int reportLine(char *out, size_t capacity) {
  return snprintf(out, capacity,
                  "NFC: ok=%u fw=%08lX polling=%u polls=%lu found=%lu last_ms=%lu max_ms=%lu fast_fail=%lu recoveries=%lu sda=%d scl=%d",
                  unsigned(ok), (unsigned long)firmware, unsigned(polling), (unsigned long)polls, (unsigned long)found,
                  (unsigned long)lastMs, (unsigned long)maxMs, (unsigned long)fastFails, (unsigned long)recoveries,
                  digitalRead(SDA_PIN), digitalRead(SCL_PIN));
}

}  // namespace nfc
}  // namespace ws
