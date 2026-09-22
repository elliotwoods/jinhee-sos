#pragma once
// Shared tag-plate application for zone boards: PN532 polling, cube lookup in the flash database,
// MSG_SET_ZONE delivery with acknowledgment tracking, zone-management link, serial console and
// machine-readable "EVT ..." lines for the zone flasher's cube monitor.
// Header-only so that firmware which only relays zone frames (the pairing station) does not need the
// PN532 library. Include from a zone sketch after <Adafruit_PN532.h>.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>
#include <Adafruit_PN532.h>
#include "NctZone.h"
#include "NctCubeProtocol.h"

namespace nctzone {

struct TagPlateOptions {
  const char *firmware = "";   // <=15 chars, reported to the flasher and registry
  const char *banner = "NCT TAG PLATE";
  uint8_t zoneType = 0;        // zone sent to cubes; 0 = use the zone type stored in zcfg
  int sdaPin = 4, sclPin = 3;  // field-proven PN532 wiring
  // Optional second PN532 wiring, tried when the reader does not answer on sdaPin/sclPin, e.g. 6/7 for a reader on
  // the XIAO ESP32-C3's labelled SDA/SCL pads (D4/D5). The pair the reader answers on is kept. -1 = none: leave it
  // off where anything else shares or sits on those pins (the pool slider shares the reader's bus).
  int altSdaPin = -1, altSclPin = -1;
  bool nfcEnabled = true;     // local sensor calibration can bypass reader initialization/polling
  int ledPin = 8;              // SuperMini onboard LED (active low)
  bool repeatZone = true;      // re-send the tapped cube's colour (see ZONE_REPEAT_MS)
};

class TagPlate {
 public:
  static constexpr uint32_t NFC_CHECK_INTERVAL = 30, NFC_READ_TIMEOUT = 80, TAG_LEAVE_TIMEOUT = 700;
  static constexpr uint32_t NFC_RETRY_INTERVAL = 5000, FLASH_INTERVAL = 500;
  // Reader supervision (lessons from pairing_station/I2C_DEBUG.md): a healthy no-tag poll lasts ~NFC_READ_TIMEOUT;
  // one that returns at once means the I2C command failed. The firmware query is a live check, not a cached flag.
  static constexpr uint32_t NFC_HEALTH_INTERVAL = 3000, NFC_FAST_FAIL_MS = 20, NFC_FAST_FAIL_LIMIT = 10;

  // Colour repeats, because one MSG_SET_ZONE is not enough to be sure a cube changed colour.
  // Two different ways it gets lost, and they need different answers:
  //   - The unicast fails on the radio. ESP-NOW says so in the send callback, so that case can be
  //     retried until it is acknowledged.
  //   - The cube drops it after the radio accepted it. ForKimchi.ino keeps exactly ONE received
  //     packet (pendingPacket/packetReady) and consumes it in loop(), whose idle pass is delay(2),
  //     so two frames arriving inside one pass leave only the second. A plate that sends anything
  //     straight behind the colour - the desert plate's MSG_TAG_STATE, which the cube does not even
  //     handle - can have its colour command silently replaced by a no-op. The wire reports success,
  //     so nothing here can detect it; the only answer is to send the colour again unprompted.
  // Hence two unconditional repeats first, then retries only while the radio is failing. The cube
  // never acknowledges MSG_SET_ZONE itself and is not to be changed, so an application-level
  // acknowledgement is not available. Every repeat is byte-identical and setZoneColor() only writes
  // the LEDs, so a duplicate costs one 24-byte frame and nothing else.
  // Healthy radio: three frames per tap. Radio down: seven, spread over the window, then a report.
  static constexpr uint8_t ZONE_REPEAT_COUNT = 2;  // unconditional, offsets from the first send
  static constexpr uint32_t ZONE_REPEAT_MS[ZONE_REPEAT_COUNT] = {120, 400};
  static constexpr uint32_t ZONE_RETRY_MS = 600;           // cadence afterwards, while unacknowledged
  static constexpr uint32_t ZONE_REPEAT_WINDOW_MS = 3000;  // nothing is re-sent after this

  // Hooks (all optional). `cube` is null for tags that are not in the database.
  void (*onTagEnter)(const uint8_t *uid, uint8_t length, const Record *cube) = nullptr;
  void (*onTagLeave)(const uint8_t *uid, uint8_t length, const Record *cube) = nullptr;
  bool (*onSerial)(const char *line) = nullptr;
  void (*onReport)() = nullptr;  // extra lines for the "?" report, printed before READY
  // Frames the zone-management protocol does not claim, for sketches that speak a second
  // protocol on the same radio (the pool link). RUNS ON THE WI-FI TASK: hand the frame
  // over and return. No Serial, no I2C, no peer changes, nothing that can block.
  void (*onFrame)(const uint8_t *src, const uint8_t *data, int len) = nullptr;

  ZoneDb db;
  ZoneLink link;
  ZoneConfig config = {};
  ZoneParams params = {};
  bool configOk = false, paramsOk = false, nfcOk = false, radioOk = false;

  void begin(const TagPlateOptions &options) {
    options_ = options;
    instance() = this;
    Serial.begin(115200);
    delay(500);
    Serial.printf("\n==========================\n%s\n==========================\n", options_.banner);
    if (!configStorage_.found() || !slotA_.found() || !slotB_.found())
      Serial.println("PARTITIONS MISSING: flash with the zone flasher (custom partitions.csv)");
    configOk = loadConfig(configStorage_, config);
    paramsOk = loadParams(configStorage_, params);
    int slot = db.begin(&slotA_, &slotB_);
    Serial.printf("CONFIG: %s\n", configOk ? "valid" : "INVALID");
    Serial.printf("DB: slot=%d version=%lu count=%u\n", slot, (unsigned long)db.version(), db.count());

    // The PN532 stays powered across ESP32 resets; a reset mid-transaction can leave it holding the bus.
    altPins_ = false;
    bool busClear = recoverBus();
    delay(300);
    nfcOk = false;
    for (int attempt = 0; options_.nfcEnabled && attempt < 3 && !nfcOk; attempt++) {
      if (attempt) busClear = recoverBus();
      nfcOk = findNfc(busClear);
      if (!nfcOk) delay(400);
    }
    Serial.println(!options_.nfcEnabled ? "PN532 disabled" : nfcOk ? "PN532 FOUND" : busClear ? "PN532 NOT FOUND (radio continues; retrying)"
                                                    : "PN532 I2C LINE HELD LOW (check wiring / power-cycle the reader; retrying)");
    lastNfcRetry_ = lastHealth_ = millis();

    sendResults_ = xQueueCreate(8, sizeof(SendResult));
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(100);
    radioOk = sendResults_ && esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK &&
              esp_now_init() == ESP_OK && esp_now_register_recv_cb(receiveCallback) == ESP_OK &&
              esp_now_register_send_cb(sentCallback) == ESP_OK;
    link.begin(db, config, configOk, options_.firmware, options_.ledPin, true);
    if (!radioOk) {
      Serial.println("ESP-NOW INIT ERROR");
      link.setError(ERR_RADIO);
    } else if (options_.nfcEnabled && !nfcOk) {
      link.setError(ERR_NFC);
    }
  }

  void printNfc() {
    Serial.printf("NFC: ok=%u fw=%08lX polls=%lu found=%lu last_ms=%lu max_ms=%lu fast_fail=%lu recoveries=%lu sda=%d scl=%d pins=%d/%d\n",
                  nfcOk, (unsigned long)nfcVersion_, (unsigned long)nfcPolls_, (unsigned long)nfcFound_,
                  (unsigned long)nfcLastMs_, (unsigned long)nfcMaxMs_, (unsigned long)nfcFastFails_,
                  (unsigned long)nfcRecoveries_, digitalRead(sdaPin()), digitalRead(sclPin()), sdaPin(), sclPin());
  }

  uint8_t rxGainStored() const { return effectiveRxGain(configOk ? config.rxGainDb : 0); }

  void printRxGainSetting() {
    uint8_t applied = link.rxGainApplied();
    if (applied) Serial.printf("RXGAIN: stored=%udB applied=%udB\n", rxGainStored(), applied);
    else Serial.printf("RXGAIN: stored=%udB applied=?\n", rxGainStored());
  }

  // Store a new PN532 RX gain in zcfg and apply it to the reader without a reboot. Used by the serial
  // "rxgain" command and ZONE_SET_CONFIG. Runs on loop(): flash erase and I2C are not for the Wi-Fi task.
  uint8_t changeRxGain(uint8_t db) {
    uint8_t result;
    if (!validRxGain(db)) {
      result = SET_INVALID;
    } else if (!configOk) {
      result = SET_UNCONFIGURED;
    } else {
      ZoneConfig updated = config;
      updated.rxGainDb = db;
      if (!saveConfig(configStorage_, updated, params, paramsOk)) {
        // The erase may have run: reload whatever is there so the report matches the flash.
        configOk = loadConfig(configStorage_, config);
        paramsOk = loadParams(configStorage_, params);
        result = SET_FLASH_FAILED;
      } else {
        config = updated;
        result = options_.nfcEnabled && nfcOk && setRxGain(db) ? SET_OK : SET_NOT_APPLIED;
        if (result == SET_NOT_APPLIED) link.setRxGainApplied(0);
      }
    }
    static const char *const NAMES[] = {"none", "ok", "invalid value", "zone unconfigured", "flash write failed",
                                        "stored, reader did not accept it"};
    Serial.printf("RXGAIN SET %udB: %s\n", db, NAMES[result]);
    link.configApplied(config, configOk, result);
    return result;
  }

  void printReport() {
    link.printReport(false);
    printNfc();
    printRxGainSetting();
    if (onReport) onReport();
    Serial.println("READY");
  }

  void loop() {
    pollSerial();
    link.poll();
    uint8_t requestedGain;
    if (link.takeConfigRequest(requestedGain)) changeRxGain(requestedGain);
    processSendResults();
    pollFlash();
    pollZoneRepeat();
    if (options_.nfcEnabled) pollNfc();
  }

  uint8_t zoneType() const { return options_.zoneType ? options_.zoneType : (configOk ? config.zoneType : 0); }
  bool tagPresent() const { return tagPresent_; }
  const uint8_t *currentUid() const { return currentUid_; }
  uint8_t currentUidLength() const { return currentUidLength_; }
  const Record &currentCube() const { return currentCube_; }
  int currentDelivery() const { return currentDelivery_; }  // 0 pending/unknown, 1 ACK, -1 failed

  // Unicast a 24-byte cube Packet. `handle` (from link.noteTag) receives the delivery result.
  bool sendToCube(const Record &cube, uint8_t type, uint8_t value, uint32_t handle = 0) {
    Packet packet = {};
    packet.type = type;
    packet.cubeID = cube.cubeID;
    packet.success = value;
    bool ok = sendFrame(cube.mac, (const uint8_t *)&packet, sizeof(packet), false, handle, cube.cubeID, type, value);
    if (!ok && handle) link.updateTag(handle, TAG_UNCONFIRMED);
    return ok;
  }

  // Send a frame without per-frame delivery tracking. For a high-rate link such as the
  // pool state stream, which would otherwise churn the four `pending_` slots and
  // misattribute a cube's acknowledgement, and would print a line for every lost frame.
  // The ESP-NOW MAC-layer acknowledgement and retries still apply to a unicast.
  bool sendUntracked(const uint8_t *mac, const uint8_t *data, size_t length, bool pinned) {
    if (!radioOk || !link.ensurePeer(mac, pinned)) return false;
    return esp_now_send(mac, data, length) == ESP_OK;
  }

  // Send any frame (media bridge, pool central controller). Pinned peers are never evicted.
  bool sendFrame(const uint8_t *mac, const uint8_t *data, size_t length, bool pinned, uint32_t handle = 0,
                 uint32_t cubeID = 0, uint8_t type = 0, uint8_t value = 0) {
    if (!radioOk || !link.ensurePeer(mac, pinned)) {
      Serial.println("PEER ADD FAILED");
      link.noteSendFail();
      return false;
    }
    bool track = !(mac[0] & 1);  // broadcasts are never acknowledged
    Pending *slot = nullptr;
    if (track) {
      for (Pending &p : pending_)
        if (!p.active) { slot = &p; break; }
      if (!slot) slot = &pending_[0];
      slot->active = true;
      memcpy(slot->mac, mac, 6);
      slot->handle = handle;
      slot->cubeID = cubeID;
      slot->type = type;
      slot->value = value;
      slot->order = ++order_;
    }
    esp_err_t result = esp_now_send(mac, data, length);
    if (result == ESP_OK) return true;
    if (slot) slot->active = false;
    Serial.printf("ESP-NOW SEND FAILED: %d\n", result);
    link.noteSendFail();
    return false;
  }

 private:
  struct SendResult { uint8_t mac[6]; uint8_t ok; };
  struct Pending { bool active; uint8_t mac[6]; uint32_t handle, cubeID, order; uint8_t type, value; };

  static TagPlate *&instance() { static TagPlate *plate = nullptr; return plate; }

  static void receiveCallback(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
    TagPlate *self = instance();
    if (!self) return;
    if (self->link.receive(info->src_addr, info->des_addr, data, len)) return;
    if (self->onFrame) self->onFrame(info->src_addr, data, len);
  }
  static void sentCallback(const esp_now_send_info_t *info, esp_now_send_status_t status) {
    TagPlate *self = instance();
    if (!self || !self->sendResults_ || !info || !info->des_addr) return;
    SendResult r;
    memcpy(r.mac, info->des_addr, 6);
    r.ok = status == ESP_NOW_SEND_SUCCESS;
    xQueueSend(self->sendResults_, &r, 0);
  }

  static void printHex(const uint8_t *data, int length) {
    for (int i = 0; i < length; i++) Serial.printf(i ? ":%02X" : "%02X", data[i]);
  }

  // NXP UM10204 bus clear: release SDA, clock SCL up to nine times, then STOP. Open-drain only, so a line is
  // never driven high against the reader. Returns true when both lines are high afterwards.
  bool recoverBus() {
    const int sda = sdaPin(), scl = sclPin();
    Wire.end();
    pinMode(sda, INPUT_PULLUP);
    pinMode(scl, INPUT_PULLUP);
    delay(10);
    if (digitalRead(scl) == HIGH && digitalRead(sda) == LOW) {
      digitalWrite(scl, HIGH);
      pinMode(scl, OUTPUT_OPEN_DRAIN);
      for (int i = 0; i < 9 && digitalRead(sda) == LOW; i++) {
        digitalWrite(scl, LOW);
        delayMicroseconds(10);
        digitalWrite(scl, HIGH);
        delayMicroseconds(10);
      }
      digitalWrite(scl, LOW);
      digitalWrite(sda, LOW);
      pinMode(sda, OUTPUT_OPEN_DRAIN);
      delayMicroseconds(10);
      digitalWrite(scl, HIGH);
      delayMicroseconds(10);
      digitalWrite(sda, HIGH);
      delayMicroseconds(10);
      pinMode(scl, INPUT_PULLUP);
      pinMode(sda, INPUT_PULLUP);
      delay(10);
    }
    bool clear = digitalRead(scl) == HIGH && digitalRead(sda) == HIGH;
    Wire.begin(sda, scl);
    Wire.setTimeOut(250);
    return clear;
  }

  int sdaPin() const { return altPins_ ? options_.altSdaPin : options_.sdaPin; }
  int sclPin() const { return altPins_ ? options_.altSclPin : options_.sclPin; }
  bool hasAltPins() const { return options_.altSdaPin >= 0 && options_.altSclPin >= 0; }

  // Start the reader on the current pin pair (whose bus recoverBus() just cleared, or not), then on the alternate
  // pair if one is configured. The pair that answered stays selected; if neither does, the current one is kept, so
  // the report describes the wiring that last worked and the held-low diagnosis stays about that bus.
  bool findNfc(bool busClear) {
    if (busClear && beginNfc()) return true;
    if (!hasAltPins()) return false;
    Wire.end();
    pinMode(sdaPin(), INPUT);
    pinMode(sclPin(), INPUT);
    altPins_ = !altPins_;
    if (recoverBus() && beginNfc()) {
      Serial.printf("PN532 FOUND on SDA=%d SCL=%d\n", sdaPin(), sclPin());
      return true;
    }
    Wire.end();
    pinMode(sdaPin(), INPUT);
    pinMode(sclPin(), INPUT);
    altPins_ = !altPins_;
    recoverBus();
    return false;
  }

  // Only library calls that read their reply back are used: a PN532 RFConfiguration command whose reply is left
  // unread made the chip hold SCL low until power-cycled (seen on this hardware; see pairing_station/I2C_DEBUG.md).
  bool beginNfc() {
    nfc_.begin();
    nfcVersion_ = nfc_.getFirmwareVersion();
    if (((nfcVersion_ >> 24) & 0xFF) != 0x32) return false;  // a floating bus can return garbage; PN532 IC is 0x32
    if (!nfc_.SAMConfig()) return false;
    setRxGain(rxGainStored());
    return true;
  }

  // Set the receiver gain stored in zcfg (default 48 dB, the maximum, so a weakly coupled cube is still read).
  // RFConfiguration CfgItem 0x0A takes all eleven analog registers for 106 kbps type A (UM0701-02 table 19);
  // only CIU_RFCfg moves from its 0x59 default, whose RxGain (bits 6..4) 101 = 38 dB is replaced by the chosen
  // step (PN512 data sheet table 92; 0x79 = 48 dB). The other ten keep their documented defaults. Higher gain
  // also raises the noise the demodulator sees, so measure rather than assume a marginal tag improves.
  // The reply (D5 33, UM0701-02 p106) is read here because the library acknowledges the command and waits for
  // its reply but never consumes it, and that unread reply is what held SCL low (pairing_station/I2C_DEBUG.md).
  bool setRxGain(uint8_t db) {
    db = effectiveRxGain(db);
    uint8_t rfcfg = uint8_t((0x59 & 0x8F) | (rxGainField(db) << 4));
    uint8_t command[] = {PN532_COMMAND_RFCONFIGURATION, 0x0A, rfcfg, 0xF4, 0x3F, 0x11, 0x4D,
                         0x85, 0x61, 0x6F, 0x26, 0x62, 0x87};
    uint8_t reply[10] = {};  // ready byte, then 00 00 FF LEN LCS D5 33 DCS 00
    bool ok = nfc_.sendCommandCheckAck(command, sizeof(command)) &&
              Wire.requestFrom(uint8_t(PN532_I2C_ADDRESS), uint8_t(sizeof(reply))) == sizeof(reply);
    if (ok) {
      for (uint8_t &byte : reply) byte = Wire.read();
      ok = reply[6] == PN532_PN532TOHOST && reply[7] == PN532_COMMAND_RFCONFIGURATION + 1;
    }
    Serial.printf("PN532 RX GAIN %udB: %s\n", db, ok ? "set" : "NOT SET (reader keeps its previous gain)");
    // The command replaces the whole register, so a NOT SET after a reset leaves the chip's 38 dB default,
    // but a failure on a live reader may leave the earlier gain: report it as unknown either way.
    link.setRxGainApplied(ok ? db : 0);
    return ok;
  }

  // Diagnostic: print the gain the chip is actually running, instead of trusting that the command above stuck.
  // ReadRegister (UM0701-02 p76) fetches CIU_RFCfg, which lives at XRAM 0x6316; that address comes from libnfc's
  // register table, whose CIU_Status1 0x6337 matches the manual's own worked example. RxGain is bits 6..4
  // (PN512 data sheet table 92). Reply: ready byte, then 00 00 FF LEN LCS D5 07 <value> DCS 00.
  void printRxGain() {
    static const uint8_t DB[8] = {18, 23, 18, 23, 33, 38, 43, 48};
    uint8_t command[] = {PN532_COMMAND_READREGISTER, 0x63, 0x16};
    uint8_t reply[11] = {};
    bool ok = nfc_.sendCommandCheckAck(command, sizeof(command)) &&
              Wire.requestFrom(uint8_t(PN532_I2C_ADDRESS), uint8_t(sizeof(reply))) == sizeof(reply);
    if (ok) {
      for (uint8_t &byte : reply) byte = Wire.read();
      ok = reply[6] == PN532_PN532TOHOST && reply[7] == PN532_COMMAND_READREGISTER + 1;
    }
    if (!ok) { Serial.println("RFCFG: read failed"); return; }
    uint8_t value = reply[8];
    Serial.printf("RFCFG: CIU_RFCfg=0x%02X rx_gain=%udB level_amp=%u rf_level=%u\n",
                  value, DB[(value >> 4) & 0x07], (value >> 7) & 1, value & 0x0F);
  }

  void nfcLost(const char *why) {
    nfcOk = false;
    link.setRxGainApplied(0);  // re-applied by beginNfc() on recovery
    fastFailRun_ = 0;
    lastNfcRetry_ = millis() - NFC_RETRY_INTERVAL;  // recover on the next pass
    link.setError(ERR_NFC);
    Serial.printf("PN532 LOST: %s\n", why);
  }

  void processSendResults() {
    SendResult r;
    while (sendResults_ && xQueueReceive(sendResults_, &r, 0) == pdTRUE) {
      Pending *oldest = nullptr;
      for (Pending &p : pending_)
        if (p.active && !memcmp(p.mac, r.mac, 6) && (!oldest || p.order < oldest->order)) oldest = &p;
      if (!oldest) continue;
      oldest->active = false;
      if (!r.ok) link.noteSendFail();
      if (repeating_ && oldest->type == MSG_SET_ZONE && oldest->cubeID == repeatCube_.cubeID) repeatAcked_ = r.ok;
      if (oldest->handle && oldest->handle == currentTagHandle_)
        currentDelivery_ = r.ok ? 1 : -1;
      if (oldest->handle) link.updateTag(oldest->handle, r.ok ? TAG_DELIVERED : TAG_UNCONFIRMED);
      if (oldest->cubeID) {
        Serial.printf("Cube #%lu %s\n", (unsigned long)oldest->cubeID, r.ok ? "DELIVERED" : "NOT ACKNOWLEDGED");
        Serial.printf("EVT SENT cube=%lu type=%u value=%u ok=%u\n", (unsigned long)oldest->cubeID, oldest->type,
                      oldest->value, r.ok);
      } else if (!r.ok) {
        Serial.print("NOT ACKNOWLEDGED: ");
        printHex(r.mac, 6);
        Serial.println();
      }
    }
  }

  void tagEnter(const uint8_t *uid, uint8_t length) {
    Serial.print("\nTAG ENTER: ");
    printHex(uid, length);
    Serial.println();
    const Record *cube = db.find(uid, length);
    currentCube_ = cube ? *cube : Record{};
    currentDelivery_ = 0;
    currentTagHandle_ = 0;
    // The value that goes to the cube: the plate kind for 1..4, ZONE_IDLE for a reset plate. The EVT
    // line reports it (not the kind) so the flasher monitor matches it against the SENT value.
    const uint8_t cubeZone = cubeZoneFor(zoneType());
    Serial.print("EVT TAG uid=");
    printHex(uid, length);
    if (cube) {
      Serial.printf(" cube=%lu mac=", (unsigned long)cube->cubeID);
      printHex(cube->mac, 6);
    } else {
      Serial.print(" cube=0 mac=-");
    }
    Serial.printf(" zone=%u\n", cubeZone);
    if (!cube) {
      link.noteTag(uid, length, 0, TAG_UNKNOWN);
      Serial.println("UNKNOWN CUBE");
    } else {
      Serial.printf("FOUND Cube #%lu\n", (unsigned long)cube->cubeID);
      uint32_t handle = link.noteTag(uid, length, cube->cubeID, TAG_PENDING);
      currentTagHandle_ = handle;
      if (flashing_ && flashCube_.cubeID == cube->cubeID) flashing_ = false;  // a real tap wins over a test flash
      if (zoneSendsColour(zoneType())) {
        if (!sendToCube(*cube, MSG_SET_ZONE, cubeZone, handle)) currentDelivery_ = -1;
        startZoneRepeat(*cube, cubeZone, handle);
      } else {
        Serial.println("ZONE TYPE NOT CONFIGURED: cube not updated");
        link.updateTag(handle, TAG_UNCONFIRMED);
      }
    }
    if (onTagEnter) onTagEnter(uid, length, cube);
  }

  void pollNfc() {
    uint32_t now = millis();
    if (!nfcOk) {
      if (now - lastNfcRetry_ >= NFC_RETRY_INTERVAL) {
        nfcRecoveries_++;
        bool busClear = recoverBus();
        nfcOk = findNfc(busClear);
        lastNfcRetry_ = lastHealth_ = millis();
        Serial.println(nfcOk ? "PN532 FOUND" : busClear ? "PN532 NOT FOUND (retrying)" : "PN532 I2C LINE HELD LOW (retrying)");
        if (nfcOk && link.lastError() == ERR_NFC) link.setError(ERR_NONE);
      }
      return;
    }
    if (!tagPresent_ && now - lastHealth_ >= NFC_HEALTH_INTERVAL) {
      lastHealth_ = now;
      uint32_t version = nfc_.getFirmwareVersion();
      if (((version >> 24) & 0xFF) != 0x32) return nfcLost("no reply to the firmware query");
      now = millis();
    }
    if (now - lastNfcCheck_ < NFC_CHECK_INTERVAL) return;
    lastNfcCheck_ = now;
    uint8_t uid[10];  // PN532 may report up to 10-byte UIDs
    uint8_t length = 0;
    bool found = nfc_.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &length, NFC_READ_TIMEOUT);
    nfcLastMs_ = millis() - now;
    if (nfcLastMs_ > nfcMaxMs_) nfcMaxMs_ = nfcLastMs_;
    nfcPolls_++;
    if (found) {
      nfcFound_++;
      fastFailRun_ = 0;
    } else if (nfcLastMs_ < NFC_FAST_FAIL_MS) {
      nfcFastFails_++;
      if (++fastFailRun_ >= NFC_FAST_FAIL_LIMIT && !tagPresent_) return nfcLost("scan commands are failing on the I2C bus");
    } else {
      fastFailRun_ = 0;
    }
    now = millis();
    if (found && length >= 1 && length <= 7) {
      lastSeen_ = now;
      if (!tagPresent_) {
        tagPresent_ = true;
        enteredAt_ = now;
        currentUidLength_ = length;
        memcpy(currentUid_, uid, length);
        tagEnter(uid, length);
      }
      return;
    }
    if (tagPresent_ && now - lastSeen_ > TAG_LEAVE_TIMEOUT) {
      tagPresent_ = false;
      cancelZoneRepeat();
      Serial.print("TAG LEAVE: ");
      printHex(currentUid_, currentUidLength_);
      Serial.println();
      Serial.print("EVT LEAVE uid=");
      printHex(currentUid_, currentUidLength_);
      Serial.printf(" cube=%lu held_ms=%lu\n", (unsigned long)currentCube_.cubeID, (unsigned long)(lastSeen_ - enteredAt_));
      if (onTagLeave) onTagLeave(currentUid_, currentUidLength_, currentCube_.cubeID ? &currentCube_ : nullptr);
      currentCube_ = Record{};
    }
  }

  // ---- serial console: zone report + cube test commands ----
  const Record *cubeById(uint32_t id) const {
    for (uint16_t i = 0; i < db.count(); i++)
      if (db.records()[i].cubeID == id) return &db.records()[i];
    return nullptr;
  }

  // ---- colour repeats (see ZONE_REPEAT_MS) ----
  // Every repeat carries the tap's handle, so the zone log and currentDelivery() report how the
  // whole three-second effort ended rather than how the first frame alone went.
  void startZoneRepeat(const Record &cube, uint8_t zone, uint32_t handle) {
    if (!options_.repeatZone) return;
    repeatCube_ = cube;
    repeatValue_ = zone;
    repeatHandle_ = handle;
    repeatSent_ = 0;
    repeatAcked_ = false;
    repeatStartedAt_ = millis();
    repeatDueAt_ = repeatStartedAt_ + ZONE_REPEAT_MS[0];
    repeating_ = true;
  }

  // Any colour command issued after this one supersedes it, and a tag that has left may already be
  // on the next plate: a repeat must never repaint a cube somebody else has since claimed.
  void cancelZoneRepeat() { repeating_ = false; }

  void pollZoneRepeat() {
    if (!repeating_) return;
    uint32_t now = millis();
    if (int32_t(now - repeatDueAt_) < 0) return;
    uint32_t elapsed = now - repeatStartedAt_;
    if (repeatSent_ >= ZONE_REPEAT_COUNT) {  // past the unconditional pair: only a failing radio is retried
      if (repeatAcked_) return cancelZoneRepeat();
      if (elapsed > ZONE_REPEAT_WINDOW_MS) {
        repeating_ = false;
        Serial.printf("Cube #%lu colour NOT ACKNOWLEDGED after %u tries\n", (unsigned long)repeatCube_.cubeID,
                      repeatSent_ + 1);
        Serial.printf("EVT ZONE_GAVE_UP cube=%lu value=%u tries=%u ms=%lu\n", (unsigned long)repeatCube_.cubeID,
                      repeatValue_, repeatSent_ + 1, (unsigned long)elapsed);
        return;
      }
    }
    repeatSent_++;
    repeatAcked_ = false;
    Serial.printf("EVT ZONE_REPEAT cube=%lu value=%u n=%u ms=%lu\n", (unsigned long)repeatCube_.cubeID,
                  repeatValue_, repeatSent_, (unsigned long)elapsed);
    sendToCube(repeatCube_, MSG_SET_ZONE, repeatValue_, repeatHandle_);
    repeatDueAt_ = repeatSent_ < ZONE_REPEAT_COUNT ? repeatStartedAt_ + ZONE_REPEAT_MS[repeatSent_] : now + ZONE_RETRY_MS;
  }

  void pollFlash() {
    if (!flashing_) return;
    uint32_t now = millis();
    if (now - flashStarted_ >= flashDuration_) {
      flashing_ = false;
      sendToCube(flashCube_, MSG_SET_ZONE, ZONE_IDLE);
      Serial.printf("EVT FLASH cube=%lu done\n", (unsigned long)flashCube_.cubeID);
    } else if (now - lastFlash_ >= FLASH_INTERVAL) {
      lastFlash_ = now;
      flashBlue_ = !flashBlue_;
      sendToCube(flashCube_, MSG_SET_ZONE, flashBlue_ ? ZONE_POOL : ZONE_PRESHOW);
    }
  }

  bool cubeCommand(const char *line) {
    char word[8] = {};
    unsigned long id = 0, value = 0;
    int n = sscanf(line, "%7s %lu %lu", word, &id, &value);
    bool isZone = !strcmp(word, "zone"), isClear = !strcmp(word, "clear"), isFlash = !strcmp(word, "flash"),
         isCube = !strcmp(word, "cube");
    if (!strcmp(word, "stop") && n == 1) {
      cancelZoneRepeat();
      if (flashing_) {
        flashing_ = false;
        sendToCube(flashCube_, MSG_SET_ZONE, ZONE_IDLE);
      }
      Serial.println("OK stop");
      return true;
    }
    if (!(isZone || isClear || isFlash || isCube)) return false;
    const Record *cube = n >= 2 ? cubeById(id) : nullptr;
    if (!cube) {
      Serial.printf("ERR cube %lu is not in this zone's database\n", id);
      return true;
    }
    if (!isCube) cancelZoneRepeat();  // a hand-set colour supersedes the repeats of the last tap
    if (isCube) {
      Serial.printf("CUBE %lu uid=", (unsigned long)cube->cubeID);
      printHex(cube->uid, cube->uidLength);
      Serial.print(" mac=");
      printHex(cube->mac, 6);
      Serial.println();
    } else if (isZone) {
      if (n < 3 || value > ZONE_MAINSHOW) {
        Serial.println("ERR usage: zone <cubeID> <0-4>");
        return true;
      }
      if (flashing_ && flashCube_.cubeID == cube->cubeID) flashing_ = false;
      sendToCube(*cube, MSG_SET_ZONE, uint8_t(value));
      Serial.printf("OK zone %lu %lu\n", id, value);
    } else if (isClear) {
      if (flashing_ && flashCube_.cubeID == cube->cubeID) flashing_ = false;
      sendToCube(*cube, MSG_SET_ZONE, ZONE_IDLE);
      Serial.printf("OK clear %lu\n", id);
    } else {
      if (flashing_ && flashCube_.cubeID != cube->cubeID) sendToCube(flashCube_, MSG_SET_ZONE, ZONE_IDLE);
      flashCube_ = *cube;
      flashing_ = true;
      flashDuration_ = (n >= 3 ? (value > 60 ? 60 : (value ? value : 1)) : 5) * 1000;
      flashStarted_ = millis();
      lastFlash_ = flashStarted_ - FLASH_INTERVAL;
      flashBlue_ = true;
      Serial.printf("OK flash %lu %lus\n", id, (unsigned long)(flashDuration_ / 1000));
    }
    return true;
  }

  void pollSerial() {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        serialLine_[serialUsed_] = 0;
        if (serialUsed_) handleLine(serialLine_);
        serialUsed_ = 0;
      } else if (serialUsed_ < sizeof(serialLine_) - 1) {
        serialLine_[serialUsed_++] = c;
      }
    }
  }

  void handleLine(const char *line) {
    while (*line == ' ') line++;
    if (!strcmp(line, "?")) {
      printReport();
    } else if (!strcmp(line, "nfc")) {
      printNfc();
    } else if (!strcmp(line, "rfcfg")) {
      printRxGain();
    } else if (!strncmp(line, "rxgain", 6) && (line[6] == 0 || line[6] == ' ')) {
      unsigned long db = 0;
      if (sscanf(line + 6, "%lu", &db) != 1) printRxGainSetting();
      else changeRxGain(db > 255 ? 0 : uint8_t(db));
    } else if (!strcmp(line, "nfc recover")) {
      nfcLost("recovery requested");
      if (tagPresent_) {
        tagPresent_ = false;
        if (onTagLeave) onTagLeave(currentUid_, currentUidLength_, currentCube_.cubeID ? &currentCube_ : nullptr);
      }
    } else if (!strcmp(line, "help")) {
      Serial.println("Commands: ? | nfc | nfc recover | rfcfg | rxgain [18|23|33|38|43|48] | db | log | cube <id> | zone <id> <0-4> | clear <id> | flash <id> [s] | stop | help");
    } else if (!(onSerial && onSerial(line)) && !cubeCommand(line) && !link.handleSerialCommand(line)) {
      Serial.println("Unknown command; try help");
    }
  }

  TagPlateOptions options_;
  PartitionStorage configStorage_{"zcfg"}, slotA_{"zdb_a"}, slotB_{"zdb_b"};
  Adafruit_PN532 nfc_{uint8_t(-1), uint8_t(-1)};  // I2C, no IRQ/reset pins (same as the field-proven sketches)
  QueueHandle_t sendResults_ = nullptr;
  Pending pending_[4] = {};
  uint32_t order_ = 0;
  bool tagPresent_ = false;
  uint8_t currentUid_[7] = {}, currentUidLength_ = 0;
  Record currentCube_ = {};
  uint32_t currentTagHandle_ = 0;
  int currentDelivery_ = 0;
  uint32_t lastSeen_ = 0, lastNfcCheck_ = 0, lastNfcRetry_ = 0, enteredAt_ = 0, lastHealth_ = 0;
  uint32_t nfcVersion_ = 0, nfcPolls_ = 0, nfcFound_ = 0, nfcLastMs_ = 0, nfcMaxMs_ = 0, nfcFastFails_ = 0, nfcRecoveries_ = 0;
  uint8_t fastFailRun_ = 0;
  bool altPins_ = false;  // the reader answered on altSdaPin/altSclPin
  bool flashing_ = false, flashBlue_ = false;
  Record flashCube_ = {};
  uint32_t flashStarted_ = 0, flashDuration_ = 0, lastFlash_ = 0;
  bool repeating_ = false, repeatAcked_ = false;
  Record repeatCube_ = {};
  uint8_t repeatValue_ = 0, repeatSent_ = 0;
  uint32_t repeatHandle_ = 0, repeatStartedAt_ = 0, repeatDueAt_ = 0;
  char serialLine_[64] = {};
  size_t serialUsed_ = 0;
};

}  // namespace nctzone
