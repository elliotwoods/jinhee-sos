// NCT ESP-NOW range test. XIAO ESP32-C3 / D10 / eight WS2812 LEDs.
// One sketch, two roles: TX is carried around the exhibition, RX sits in the
// back room and answers every ping with an ACK carrying the RSSI it measured.
// Channel 2, matching the cubes, zones, pairing station and pool central.
//
// Radio configuration is deliberately identical to flashing_station/firmware/
// neocore_usb: same init order, same default Wi-Fi power save, same default TX
// power. The point of this firmware is to predict cube behaviour, so it must not
// give itself advantages the cubes do not have.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <esp_random.h>
#include <Adafruit_NeoPixel.h>
#include <stdarg.h>
#include "RangeTestPacket.h"
#include "RangeTestTypes.h"

using namespace rangetest;

#define FIRMWARE_VERSION "v1.0.0"

// ===================================================
// Hardware (identical to the cube)
// ===================================================
#define LED_PIN D10
#define NUM_LEDS 8
#define LED_MAX_LEVEL 100  // cube convention; 255 is the WS2812 maximum

Adafruit_NeoPixel pixels(NUM_LEDS, LED_PIN, NEO_GRB + NEO_KHZ800);

// Both roles run the same display: a comet of dots around all eight pixels, one
// step per packet. Only the hue differs - blue on the TX, red on the RX - which
// is enough to tell the boards apart without spending a pixel on a role marker.
constexpr uint8_t COMET_PIXELS = NUM_LEDS;

// ===================================================
// Role
// ===================================================
// Known bench boards. An unknown board still runs, as TX, with a warning.
const RoleDefault ROLE_TABLE[] = {
  {{0x1C, 0xDB, 0xD4, 0xF0, 0xC3, 0xE0}, ROLE_TX},
  {{0x1C, 0xDB, 0xD4, 0xF0, 0xD2, 0x20}, ROLE_RX},
};

uint8_t role = ROLE_TX;
const char *roleSource = "default";
bool roleKnown = false;
uint8_t myMac[6] = {0};
uint32_t bootId = 0;
bool radioReady = false;

const char *roleName(uint8_t value) {
  return value == ROLE_RX ? "RX" : "TX";
}

// ===================================================
// Configuration
// ===================================================
uint8_t broadcastMac[6] = {255, 255, 255, 255, 255, 255};
uint16_t pingIntervalMs = 200;  // 5 Hz

// How long a ping may wait for its ACK before being counted lost. Kept below the
// ping interval so a late ACK is never credited to the following ping.
uint16_t ackWindowMs() {
  return pingIntervalMs > 60 ? 150 : uint16_t(pingIntervalMs - 10);
}

// ===================================================
// Non-blocking logging
// ===================================================
// Single loop-task producer. Never wait for a USB monitor to consume output:
// losing a log line is acceptable, delaying the radio is not.
uint32_t logDrops = 0;

// Per-packet lines are what the GUI logs, but they overrun the USB buffer when
// nothing is reading. VERBOSE OFF leaves only the 1 Hz STAT line, for a board
// left plugged in unattended.
bool verbose = true;

// MUTE ON makes the RX keep receiving and counting but stop answering. It is the
// automated negative control: the TX must then report 100% loss while the RX
// still logs every ping, which proves the TX "delivered" indication is a real
// application ACK and not a constant.
bool muted = false;

void logLine(const char *format, ...) {
  char line[400];
  va_list args;
  va_start(args, format);
  int count = vsnprintf(line, sizeof(line) - 2, format, args);
  va_end(args);
  if (count < 0) return;
  size_t length = min(size_t(count), sizeof(line) - 2);
  line[length++] = '\n';
  // The `if (Serial)` guard is load-bearing, not defensive noise: writing to the
  // USB CDC before a host has opened the port wedges the peripheral, and the
  // board then stays silent for good while the radio carries on happily. Dropping
  // this check was tried and reproducibly killed serial output on both boards.
  if (Serial && Serial.availableForWrite() >= int(length)) {
    Serial.write((uint8_t *)line, length);
  } else {
    ++logDrops;
  }
}

void macToText(const uint8_t *mac, char *out) {
  snprintf(out, 13, "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

// ===================================================
// Receive mailbox
// ===================================================
// The ESP-NOW receive callback runs in the high-priority Wi-Fi task. It copies
// and returns: no esp_now_send, no Serial, no LED work. This is the pattern
// poolzone_test/firmware/PoolCentralTest was rewritten to use after an unsafe
// callback caused a reproducible control failure.
constexpr uint8_t MAILBOX_SLOTS = 16;
RxEvent mailbox[MAILBOX_SLOTS];
uint8_t mailboxHead = 0, mailboxTail = 0;
uint32_t mailboxDrops = 0;
portMUX_TYPE mailMux = portMUX_INITIALIZER_UNLOCKED;

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (length != int(sizeof(RangeTestPacket))) return;
  RangeTestPacket packet;
  memcpy(&packet, data, sizeof(packet));
  if (packet.magic != MAGIC) return;

  RxEvent event;
  event.packet = packet;
  // esp_now_info is a local variable in the driver and is valid only inside this
  // callback, so copy the bytes out. Storing info or info->src_addr would be a
  // use-after-free.
  if (info && info->src_addr) memcpy(event.src, info->src_addr, 6);
  else memset(event.src, 0, 6);
  if (info && info->rx_ctrl) {
    event.rssi = int8_t(info->rx_ctrl->rssi);
    event.noiseFloor = int8_t(info->rx_ctrl->noise_floor);
    event.channel = uint8_t(info->rx_ctrl->channel);
  } else {
    event.rssi = RSSI_UNKNOWN;
    event.noiseFloor = RSSI_UNKNOWN;
    event.channel = 0;
  }
  event.rxMicros = micros();
  event.rxMillis = millis();

  portENTER_CRITICAL(&mailMux);
  uint8_t next = uint8_t((mailboxHead + 1) % MAILBOX_SLOTS);
  if (next == mailboxTail) {
    ++mailboxDrops;
  } else {
    mailbox[mailboxHead] = event;
    mailboxHead = next;
  }
  portEXIT_CRITICAL(&mailMux);
}

bool takeRxEvent(RxEvent &out) {
  bool got = false;
  portENTER_CRITICAL(&mailMux);
  if (mailboxTail != mailboxHead) {
    out = mailbox[mailboxTail];
    mailboxTail = uint8_t((mailboxTail + 1) % MAILBOX_SLOTS);
    got = true;
  }
  portEXIT_CRITICAL(&mailMux);
  return got;
}

// ===================================================
// Send callback
// ===================================================
// A broadcast 802.11 frame is never acknowledged by the MAC and is never
// retried, so this status is always success and says nothing about delivery.
// It is still worth having: it paces the ping loop, it gives the real departure
// timestamp, and it separates a local PHY failure from radio loss.
volatile bool sendPending = false;
volatile bool sendFailedFlag = false;
volatile uint32_t departMicros = 0;
bool pingInFlight = false;
uint32_t departedCount = 0, sendFailedCount = 0;

void onSent(const esp_now_send_info_t *, esp_now_send_status_t status) {
  departMicros = micros();
  sendFailedFlag = (status != ESP_NOW_SEND_SUCCESS);
  sendPending = false;
}

// ===================================================
// LED state
// ===================================================
// One decaying brightness per pixel. The cursor advances one step per packet,
// so the comet's speed is the packet rate and its brightness is the signal.
constexpr uint8_t COMET_DECAY = 6;      // per 20ms frame: a tail of roughly 0.3s
constexpr uint8_t COMET_FLOOR = LED_MAX_LEVEL / 10;
uint8_t cometLevel[COMET_PIXELS] = {0};
uint32_t cometSeq[COMET_PIXELS] = {0};
uint8_t cometCursor = 0;

uint32_t lastLedFrame = 0;

// LEDS ON mirrors the physical ring over USB so the console can show exactly
// what the board shows, rather than reimplementing the animation and drifting.
// Off by default: it is another 10 lines per second on the wire.
bool ledReport = false;
uint32_t lastLedReport = 0;
uint32_t lastLedSent[NUM_LEDS] = {0};

uint8_t limitLed(uint16_t value) {
  return value > LED_MAX_LEVEL ? uint8_t(LED_MAX_LEVEL) : uint8_t(value);
}

void setPixel(uint8_t index, uint16_t r, uint16_t g, uint16_t b) {
  pixels.setPixelColor(index, pixels.Color(limitLed(r), limitLed(g), limitLed(b)));
}

// Brightness from signal strength: full above -65 dBm, down to a quarter at
// -85 dBm and below.
uint8_t cometBrightness(int8_t rssi) {
  if (rssi == RSSI_UNKNOWN) return LED_MAX_LEVEL;
  if (rssi >= -65) return LED_MAX_LEVEL;
  if (rssi <= -85) return LED_MAX_LEVEL / 4;
  return uint8_t(LED_MAX_LEVEL / 4 + (int16_t(rssi + 85) * (LED_MAX_LEVEL * 3 / 4)) / 20);
}

// Move the comet on by `steps` and light the new head. Skipped packets advance
// the cursor without lighting anything, so a loss reads as a stutter in the flow.
void advanceComet(uint8_t steps, uint32_t seq, uint8_t level) {
  cometCursor = uint8_t((cometCursor + steps) % COMET_PIXELS);
  cometLevel[cometCursor] = level;
  cometSeq[cometCursor] = seq;
}

void litComet(uint32_t seq, uint8_t level) {
  for (uint8_t i = 0; i < COMET_PIXELS; ++i) {
    if (cometSeq[i] == seq) {
      cometLevel[i] = level;
      return;
    }
  }
}

void clearComet() {
  memset(cometLevel, 0, sizeof(cometLevel));
  memset(cometSeq, 0, sizeof(cometSeq));
  cometCursor = 0;
}

// ===================================================
// Statistics
// ===================================================
// TX
uint32_t txSeq = 0;
uint32_t txAttempted = 0, txAcked = 0, txLost = 0;
uint32_t winAttempted = 0, winDeparted = 0, winAcked = 0, winLost = 0, winSendFailed = 0;
RssiStats winUplink, winDownlink;
uint32_t winRttSum = 0, winRttMin = 0, winRttMax = 0, winRttCount = 0;

bool ackPending = false;
uint32_t ackSeq = 0, ackDeadline = 0, ackDepartMicros = 0;
uint32_t nextPingAt = 0;

// RX
uint8_t originMac[6] = {0};
bool originKnown = false;
uint32_t originBootId = 0;
uint32_t lastOriginSeq = 0;
uint32_t rxReceived = 0, rxGapLost = 0, rxRestarts = 0, rxAckSent = 0, rxAckFailed = 0;
uint32_t winRxReceived = 0, winRxGapLost = 0;
RssiStats winRxRssi, winRxNoise;
uint32_t lastPingMillis = 0;
bool everHeard = false;

uint32_t lastStat = 0;

void resetStats() {
  txSeq = 0;
  txAttempted = txAcked = txLost = 0;
  departedCount = sendFailedCount = 0;
  winAttempted = winDeparted = winAcked = winLost = winSendFailed = 0;
  winUplink.reset();
  winDownlink.reset();
  winRttSum = winRttMin = winRttMax = winRttCount = 0;
  ackPending = false;
  originKnown = false;
  lastOriginSeq = 0;
  originBootId = 0;
  rxReceived = rxGapLost = rxRestarts = rxAckSent = rxAckFailed = 0;
  winRxReceived = winRxGapLost = 0;
  winRxRssi.reset();
  winRxNoise.reset();
  everHeard = false;
  lastPingMillis = 0;
  logDrops = 0;
  mailboxDrops = 0;
  clearComet();
}

// ===================================================
// Provenance
// ===================================================
// Printed by name, not number: BROWNOUT is the one that matters when the TX is
// being carried around a building on a battery, and it must not be something a
// reader has to look up in an enum.
const char *resetName() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_EXT: return "EXT";
    case ESP_RST_SW: return "SW";
    case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT: return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_SDIO: return "SDIO";
    case ESP_RST_USB: return "USB";
    case ESP_RST_JTAG: return "JTAG";
    default: return "UNKNOWN";
  }
}

const char *sleepName() {
  switch (WiFi.getSleep()) {
    case WIFI_PS_NONE: return "NONE";
    case WIFI_PS_MIN_MODEM: return "MIN_MODEM";
    case WIFI_PS_MAX_MODEM: return "MAX_MODEM";
    default: return "UNKNOWN";
  }
}

void printTxPower() {
  // esp_wifi_get_max_tx_power returns esp_err_t and writes the power through an
  // out parameter, in units of 0.25 dBm. Printing its return value would show a
  // plausible-looking 0.
  int8_t quarters = 0;
  esp_err_t err = esp_wifi_get_max_tx_power(&quarters);
  logLine("TX power: %s %d (%.2f dBm)", esp_err_to_name(err), quarters, quarters / 4.0f);
}

void printStatus() {
  char mac[13];
  macToText(myMac, mac);
  uint32_t version = 0;
  esp_now_get_version(&version);
  logLine("================================");
  logLine("NCT RANGE TEST");
  logLine("FW: " FIRMWARE_VERSION);
  logLine("Role: %s (%s)", roleName(role), roleSource);
  logLine("MAC: %s", WiFi.macAddress().c_str());
  logLine("Boot ID: %08lx  reset: %s", (unsigned long)bootId, resetName());
  logLine("ESP-NOW CHANNEL: %d", int(WiFi.channel()));
  logLine("ESP-NOW version: %lu  radio_ok=%u", (unsigned long)version, radioReady);
  logLine("Wi-Fi sleep: %s (cube default; deliberately not disabled)", sleepName());
  printTxPower();
  logLine("Packet: %u bytes magic 0x%08lx  rate: %u Hz",
          unsigned(sizeof(RangeTestPacket)), (unsigned long)MAGIC, unsigned(1000 / pingIntervalMs));
  logLine("Counters: tx_attempted=%lu tx_acked=%lu tx_lost=%lu rx_received=%lu rx_gap_lost=%lu "
          "rx_restarts=%lu log_drops=%lu mailbox_drops=%lu",
          (unsigned long)txAttempted, (unsigned long)txAcked, (unsigned long)txLost,
          (unsigned long)rxReceived, (unsigned long)rxGapLost, (unsigned long)rxRestarts,
          (unsigned long)logDrops, (unsigned long)mailboxDrops);
  logLine("mac=%s", mac);
  logLine("RANGE TEST READY");
  logLine("================================");
}

// ===================================================
// Sending
// ===================================================
bool sendPacket(RangeTestPacket &packet) {
  packet.magic = MAGIC;
  packet.version = VERSION;
  packet.role = role;
  packet.bootId = bootId;
  sendPending = true;
  esp_err_t err = esp_now_send(broadcastMac, (uint8_t *)&packet, sizeof(packet));
  if (err != ESP_OK) {
    sendPending = false;
    return false;
  }
  return true;
}

void sendPing() {
  RangeTestPacket packet = {};
  packet.type = TYPE_PING;
  packet.seq = ++txSeq;
  packet.originTxMicros = micros();
  packet.turnaroundUs = 0;
  packet.rssi = RSSI_UNKNOWN;
  packet.noiseFloor = RSSI_UNKNOWN;
  packet.channel = uint8_t(WiFi.channel());
  memcpy(packet.originMac, myMac, 6);

  ++txAttempted;
  ++winAttempted;
  uint32_t queuedMicros = micros();
  if (!sendPacket(packet)) {
    ++sendFailedCount;
    ++winSendFailed;
    advanceComet(1, packet.seq, COMET_FLOOR);
    logLine("PKT role=TX t=%lu seq=%lu ack=0 err=queue", (unsigned long)millis(), (unsigned long)packet.seq);
    return;
  }
  // The send callback refines this with the real departure time.
  departMicros = queuedMicros;
  pingInFlight = true;
  ackPending = true;
  ackSeq = packet.seq;
  ackDeadline = millis() + ackWindowMs();
  // Advance on every ping SENT, not only on the ones acknowledged. A moving but
  // barely-lit comet says "board alive, link dead"; a frozen one says the board
  // has crashed or browned out. Collapsing those two would hide the worse fault.
  advanceComet(1, packet.seq, COMET_FLOOR);
}

void sendAck(const RxEvent &event) {
  RangeTestPacket packet = {};
  packet.type = TYPE_ACK;
  packet.seq = event.packet.seq;
  packet.originTxMicros = event.packet.originTxMicros;
  packet.turnaroundUs = micros() - event.rxMicros;
  packet.rssi = event.rssi;
  packet.noiseFloor = event.noiseFloor;
  packet.channel = event.channel;
  memcpy(packet.originMac, event.packet.originMac, 6);
  if (sendPacket(packet)) ++rxAckSent;
  else ++rxAckFailed;
}

// ===================================================
// TX handling
// ===================================================
void handleAck(const RxEvent &event) {
  if (memcmp(event.packet.originMac, myMac, 6) != 0) return;  // an ACK for another TX
  if (!ackPending || event.packet.seq != ackSeq) return;      // stale or duplicate

  uint32_t rtt = micros() - departMicros;
  uint32_t turnaround = event.packet.turnaroundUs;
  uint32_t air = rtt > turnaround ? rtt - turnaround : 0;

  ackPending = false;
  ++txAcked;
  ++winAcked;
  winUplink.add(event.packet.rssi);
  winDownlink.add(event.rssi);
  if (winRttCount == 0 || rtt < winRttMin) winRttMin = rtt;
  if (winRttCount == 0 || rtt > winRttMax) winRttMax = rtt;
  winRttSum += rtt;
  ++winRttCount;

  // The ACK is the whole point of the TX display: the pixel only brightens once
  // the receiver has answered, at the strength the receiver measured.
  litComet(event.packet.seq, cometBrightness(event.packet.rssi));

  if (!verbose) return;
  char src[13];
  macToText(event.src, src);
  logLine("PKT role=TX t=%lu seq=%lu ack=1 rtt_us=%lu air_us=%lu turn_us=%lu "
          "up_rssi=%d up_nf=%d dn_rssi=%d dn_nf=%d up_ch=%u rx=%s",
          (unsigned long)event.rxMillis, (unsigned long)event.packet.seq,
          (unsigned long)rtt, (unsigned long)air, (unsigned long)turnaround,
          event.packet.rssi, event.packet.noiseFloor, event.rssi, event.noiseFloor,
          unsigned(event.packet.channel), src);
}

void expireAck() {
  if (!ackPending || int32_t(millis() - ackDeadline) < 0) return;
  ackPending = false;
  ++txLost;
  ++winLost;
  if (verbose) logLine("PKT role=TX t=%lu seq=%lu ack=0", (unsigned long)millis(), (unsigned long)ackSeq);
}

// ===================================================
// RX handling
// ===================================================
void handlePing(const RxEvent &event) {
  if (!muted) sendAck(event);  // reply first; everything below is bookkeeping

  char src[13];
  macToText(event.packet.originMac, src);
  uint32_t gap = 0;

  if (!originKnown || memcmp(originMac, event.packet.originMac, 6) != 0) {
    if (originKnown) logLine("EVENT origin_change t=%lu src=%s", (unsigned long)event.rxMillis, src);
    memcpy(originMac, event.packet.originMac, 6);
    originKnown = true;
    originBootId = event.packet.bootId;
    lastOriginSeq = event.packet.seq;
  } else if (event.packet.bootId != originBootId) {
    // Without bootId a TX brownout would register as a billion-packet gap and
    // quietly corrupt the loss statistic for the rest of the survey.
    ++rxRestarts;
    logLine("EVENT tx_restart t=%lu src=%s boot=%08lx prev_boot=%08lx",
            (unsigned long)event.rxMillis, src, (unsigned long)event.packet.bootId,
            (unsigned long)originBootId);
    originBootId = event.packet.bootId;
    lastOriginSeq = event.packet.seq;
  } else if (event.packet.seq > lastOriginSeq + 1) {
    gap = event.packet.seq - lastOriginSeq - 1;
    rxGapLost += gap;
    winRxGapLost += gap;
    lastOriginSeq = event.packet.seq;
  } else if (event.packet.seq > lastOriginSeq) {
    lastOriginSeq = event.packet.seq;
  }

  ++rxReceived;
  ++winRxReceived;
  winRxRssi.add(event.rssi);
  winRxNoise.add(event.noiseFloor);
  everHeard = true;
  lastPingMillis = event.rxMillis;

  advanceComet(uint8_t(1 + min(gap, uint32_t(COMET_PIXELS - 1))), event.packet.seq,
               cometBrightness(event.rssi));

  if (!verbose) return;
  logLine("PKT role=RX t=%lu seq=%lu src=%s boot=%08lx gap=%lu rssi=%d nf=%d ch=%u turn_us=%lu",
          (unsigned long)event.rxMillis, (unsigned long)event.packet.seq, src,
          (unsigned long)event.packet.bootId, (unsigned long)gap,
          event.rssi, event.noiseFloor, unsigned(event.channel),
          (unsigned long)(micros() - event.rxMicros));
}

// ===================================================
// Periodic statistics
// ===================================================
void printStat() {
  uint32_t now = millis();
  if (role == ROLE_TX) {
    uint32_t resolved = winAcked + winLost;
    float loss = resolved ? (100.0f * float(winLost) / float(resolved)) : 0.0f;
    logLine("STAT role=TX t=%lu rate_hz=%u attempted=%lu departed=%lu sendfail=%lu acked=%lu "
            "lost=%lu loss_pct=%.1f rtt_us_avg=%lu rtt_us_min=%lu rtt_us_max=%lu "
            "up_rssi_avg=%.1f up_rssi_min=%d up_rssi_max=%d dn_rssi_avg=%.1f dn_rssi_min=%d "
            "dn_rssi_max=%d sleep=%s ch=%d verbose=%u total_attempted=%lu total_acked=%lu total_lost=%lu "
            "log_drops=%lu mailbox_drops=%lu",
            (unsigned long)now, unsigned(1000 / pingIntervalMs),
            (unsigned long)winAttempted, (unsigned long)winDeparted, (unsigned long)winSendFailed,
            (unsigned long)winAcked, (unsigned long)winLost, loss,
            (unsigned long)(winRttCount ? winRttSum / winRttCount : 0),
            (unsigned long)(winRttCount ? winRttMin : 0), (unsigned long)(winRttCount ? winRttMax : 0),
            winUplink.average(), winUplink.count ? winUplink.min : 0, winUplink.count ? winUplink.max : 0,
            winDownlink.average(), winDownlink.count ? winDownlink.min : 0,
            winDownlink.count ? winDownlink.max : 0,
            sleepName(), int(WiFi.channel()), verbose,
            (unsigned long)txAttempted, (unsigned long)txAcked, (unsigned long)txLost,
            (unsigned long)logDrops, (unsigned long)mailboxDrops);
  } else {
    uint32_t expected = winRxReceived + winRxGapLost;
    float loss = expected ? (100.0f * float(winRxGapLost) / float(expected)) : 0.0f;
    char src[13];
    macToText(originMac, src);
    logLine("STAT role=RX t=%lu received=%lu gap_lost=%lu loss_pct=%.1f rssi_avg=%.1f rssi_min=%d "
            "rssi_max=%d nf_avg=%.1f src=%s boot=%08lx last_seq=%lu ack_sent=%lu ack_failed=%lu "
            "restarts=%lu quiet_ms=%lu sleep=%s ch=%d verbose=%u mute=%u total_received=%lu total_gap_lost=%lu "
            "log_drops=%lu mailbox_drops=%lu",
            (unsigned long)now, (unsigned long)winRxReceived, (unsigned long)winRxGapLost, loss,
            winRxRssi.average(), winRxRssi.count ? winRxRssi.min : 0,
            winRxRssi.count ? winRxRssi.max : 0, winRxNoise.average(),
            originKnown ? src : "none", (unsigned long)originBootId, (unsigned long)lastOriginSeq,
            (unsigned long)rxAckSent, (unsigned long)rxAckFailed, (unsigned long)rxRestarts,
            (unsigned long)(everHeard ? now - lastPingMillis : 0),
            sleepName(), int(WiFi.channel()), verbose, muted,
            (unsigned long)rxReceived, (unsigned long)rxGapLost,
            (unsigned long)logDrops, (unsigned long)mailboxDrops);
  }

  winAttempted = winDeparted = winAcked = winLost = winSendFailed = 0;
  winUplink.reset();
  winDownlink.reset();
  winRttSum = winRttMin = winRttMax = winRttCount = 0;
  winRxReceived = winRxGapLost = 0;
  winRxRssi.reset();
  winRxNoise.reset();
}

// ===================================================
// LED rendering
// ===================================================
// Both roles show the same thing, in their own hue: the TX lights a pixel when
// the receiver's ACK comes back, the RX lights one when a ping arrives. Colour
// alone separates the boards, so every pixel carries packet information and
// none is spent on a role marker.
void roleColor(uint8_t level, uint16_t &r, uint16_t &g, uint16_t &b) {
  r = role == ROLE_RX ? level : 0;
  g = 0;
  b = role == ROLE_TX ? level : 0;
}

void renderBreathing() {
  // Nothing arriving. Amber means "nothing heard since boot", the role colour
  // means "was hearing and lost it".
  float phase = (millis() % 3000) / 3000.0f;
  float wave = phase < 0.5f ? phase * 2.0f : (1.0f - phase) * 2.0f;
  uint8_t level = uint8_t(wave * LED_MAX_LEVEL * 0.6f);
  uint16_t r, g, b;
  roleColor(level, r, g, b);
  for (uint8_t i = 0; i < COMET_PIXELS; ++i) {
    if (everHeard) setPixel(i, r, g, b);
    else setPixel(i, level, level * 2 / 3, 0);
  }
}

void renderComet() {
  uint16_t r, g, b;
  for (uint8_t i = 0; i < COMET_PIXELS; ++i) {
    roleColor(cometLevel[i], r, g, b);
    setPixel(i, r, g, b);
    cometLevel[i] = cometLevel[i] > COMET_DECAY ? uint8_t(cometLevel[i] - COMET_DECAY) : 0;
  }
}

void renderLeds() {
  uint32_t now = millis();
  if (now - lastLedFrame < 20) return;  // ~50 fps, matching the cube
  lastLedFrame = now;

  // Only the RX can fall silent: the TX advances its comet on every ping it
  // sends, whether or not anything answers.
  if (role == ROLE_RX && (!everHeard || now - lastPingMillis > 2000)) renderBreathing();
  else renderComet();
  pixels.show();
  reportLeds(now);
}

void reportLeds(uint32_t now) {
  if (!ledReport || now - lastLedReport < 100) return;
  uint32_t current[NUM_LEDS];
  bool changed = false;
  for (uint8_t i = 0; i < NUM_LEDS; ++i) {
    current[i] = pixels.getPixelColor(i);
    if (current[i] != lastLedSent[i]) changed = true;
  }
  if (!changed) return;
  lastLedReport = now;
  memcpy(lastLedSent, current, sizeof(current));
  char line[80];
  int used = 0;
  for (uint8_t i = 0; i < NUM_LEDS; ++i) {
    used += snprintf(line + used, sizeof(line) - used, "%s%06lx",
                     i ? "," : "", (unsigned long)(current[i] & 0xFFFFFF));
  }
  logLine("LEDS role=%s px=%s", roleName(role), line);
}

void bootWipe() {
  for (uint8_t i = 0; i < NUM_LEDS; ++i) {
    for (uint8_t j = 0; j < NUM_LEDS; ++j) {
      if (j > i) { setPixel(j, 0, 0, 0); continue; }
      uint16_t r, g, b;
      roleColor(LED_MAX_LEVEL, r, g, b);
      setPixel(j, r, g, b);
    }
    pixels.show();
    delay(60);
  }
  delay(200);
  pixels.clear();
  pixels.show();
}

// ===================================================
// Serial commands
// ===================================================
void handleCommand(char *input) {
  if (!strcasecmp(input, "STATUS")) {
    printStatus();
  } else if (!strcasecmp(input, "RESET")) {
    resetStats();
    logLine("OK reset");
  } else if (!strncasecmp(input, "ROLE ", 5)) {
    const char *value = input + 5;
    if (!strcasecmp(value, "TX") || !strcasecmp(value, "RX")) {
      role = strcasecmp(value, "RX") == 0 ? ROLE_RX : ROLE_TX;
      roleSource = "serial";
      resetStats();
      logLine("OK role=%s (not persisted; reboot returns to the MAC default)", roleName(role));
    } else {
      logLine("ERR role");
    }
  } else if (!strncasecmp(input, "RATE ", 5)) {
    int hz = atoi(input + 5);
    if (hz >= 1 && hz <= 20) {
      pingIntervalMs = uint16_t(1000 / hz);
      logLine("OK rate_hz=%d interval_ms=%u ack_window_ms=%u", hz, pingIntervalMs, ackWindowMs());
    } else {
      logLine("ERR rate (1-20)");
    }
  } else if (!strncasecmp(input, "SLEEP ", 6)) {
    const char *value = input + 6;
    if (!strcasecmp(value, "ON")) {
      WiFi.setSleep(WIFI_PS_MIN_MODEM);
      logLine("OK sleep=%s", sleepName());
    } else if (!strcasecmp(value, "OFF")) {
      WiFi.setSleep(WIFI_PS_NONE);
      logLine("OK sleep=%s", sleepName());
    } else {
      logLine("ERR sleep");
    }
  } else if (!strncasecmp(input, "LEDS ", 5)) {
    const char *value = input + 5;
    if (!strcasecmp(value, "ON") || !strcasecmp(value, "OFF")) {
      ledReport = strcasecmp(value, "ON") == 0;
      memset(lastLedSent, 0xFF, sizeof(lastLedSent));  // force the next frame out
      logLine("OK leds=%u", ledReport);
    } else {
      logLine("ERR leds");
    }
  } else if (!strncasecmp(input, "MUTE ", 5)) {
    const char *value = input + 5;
    if (!strcasecmp(value, "ON") || !strcasecmp(value, "OFF")) {
      muted = strcasecmp(value, "ON") == 0;
      logLine("OK mute=%u", muted);
    } else {
      logLine("ERR mute");
    }
  } else if (!strcasecmp(input, "REBOOT")) {
    logLine("OK reboot");
    Serial.flush();
    delay(50);
    esp_restart();
  } else if (!strncasecmp(input, "VERBOSE ", 8)) {
    const char *value = input + 8;
    if (!strcasecmp(value, "ON") || !strcasecmp(value, "OFF")) {
      verbose = strcasecmp(value, "ON") == 0;
      logLine("OK verbose=%u", verbose);
    } else {
      logLine("ERR verbose");
    }
  } else if (!strncasecmp(input, "MARK ", 5)) {
    logLine("MARK t=%lu label=%s", (unsigned long)millis(), input + 5);
  } else if (!strcasecmp(input, "?")) {
    printStatus();
  } else {
    logLine("ERR command");
  }
}

void serialCommands() {
  static char input[128];
  static size_t used = 0;
  static bool overflow = false;
  while (Serial.available()) {
    char c = char(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      input[used] = 0;
      if (overflow) logLine("ERR overflow");
      else if (used) handleCommand(input);
      used = 0;
      overflow = false;
    } else if (used < sizeof(input) - 1) {
      input[used++] = c;
    } else {
      overflow = true;
    }
  }
}

// ===================================================
// Setup / loop
// ===================================================
void resolveRole() {
  for (const RoleDefault &entry : ROLE_TABLE) {
    if (memcmp(entry.mac, myMac, 6) == 0) {
      role = entry.role;
      roleSource = "mac table";
      roleKnown = true;
      return;
    }
  }
  role = ROLE_TX;
  roleSource = "UNKNOWN BOARD - defaulted";
  roleKnown = false;
}

void setup() {
  Serial.setTxBufferSize(4096);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);

  pixels.begin();
  pixels.clear();
  pixels.show();

  bootId = esp_random();

  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  WiFi.mode(WIFI_STA);
  delay(100);
  WiFi.macAddress(myMac);
  resolveRole();

  // No WiFi.setSleep() call: the cube does not make one either, so the default
  // WIFI_PS_MIN_MODEM applies to both. Use the SLEEP command to A/B it.
  radioReady = esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK &&
               esp_now_init() == ESP_OK &&
               esp_now_register_recv_cb(onReceive) == ESP_OK &&
               esp_now_register_send_cb(onSent) == ESP_OK;

  if (radioReady) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, broadcastMac, 6);
    peer.channel = 0;  // follow the interface channel, as the cube does
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    radioReady = esp_now_add_peer(&peer) == ESP_OK;
  }

  clearComet();
  bootWipe();
  printStatus();
  if (!radioReady) logLine("ESP-NOW INIT ERROR");
  if (!roleKnown) logLine("WARNING unknown board; add its MAC to ROLE_TABLE");

  uint32_t now = millis();
  nextPingAt = now;
  lastStat = now;
  lastPingMillis = now;
}

void loop() {
  serialCommands();

  RxEvent event;
  while (takeRxEvent(event)) {
    if (event.packet.type == TYPE_PING && role == ROLE_RX) handlePing(event);
    else if (event.packet.type == TYPE_ACK && role == ROLE_TX) handleAck(event);
  }

  // The ping left the PHY. A frame that never departed is a local failure, not
  // radio loss, and must be counted separately or a firmware bug reads as bad RF.
  if (pingInFlight && !sendPending) {
    pingInFlight = false;
    ++departedCount;
    ++winDeparted;
    if (sendFailedFlag) {
      sendFailedFlag = false;
      ++sendFailedCount;
      ++winSendFailed;
    }
  }

  if (role == ROLE_TX) {
    expireAck();
    // Pace on the send callback: a frame still queued is not a lost frame, and
    // queueing another would only produce ESP_ERR_ESPNOW_NO_MEM bursts.
    if (!sendPending && int32_t(millis() - nextPingAt) >= 0) {
      nextPingAt = millis() + pingIntervalMs;
      sendPing();
    }
  }

  if (millis() - lastStat >= 1000) {
    lastStat = millis();
    printStat();
  }

  renderLeds();
  delay(1);
}
