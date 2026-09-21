// NCT IMMERSIVE DEEP - PRESHOW MEDIA BRIDGE
//
// Receives PreshowEvent frames from the four PreshowZone tag plates and writes one line per
// cue to USB serial, where a TouchDesigner Serial DAT reads it:
//
//     PRESHOW,1,ON
//     PRESHOW,1,OFF
//
// That format is a contract with a TouchDesigner project that does not live in this repo.
// It must not change, and nothing else may be printed unless a human typed a command.
//
// Replaces live files/Preshow_MediaServer_SerialDAT, which was a pure listener: a hardcoded
// two-byte packet, no sequence, no acknowledgement, no retry. One lost frame meant the cue
// never fired, or the OFF never arrived and the point stayed lit, with nothing anywhere able
// to report it. This firmware adds the link the pool controller proved out and one thing more:
//   - it BROADCASTS a beacon, so plates latch its address and unicast back (MAC-layer
//     acknowledgement and hardware retries), and so swapping this board needs no plate reflash;
//   - it ACKNOWLEDGES every well-formed event by bootId+seq, including retries, so a plate
//     knows the serial line was really written rather than merely radiated;
//   - it de-duplicates on bootId+seq, so retries and the plates' periodic re-assert are
//     silent and only a genuine state change reaches TouchDesigner.
// Modem sleep is disabled and the receive callback does nothing but hand the frame over, both
// lessons from the legacy pool central (zones/firmware/PoolCentral).
//
// ESP-NOW channel 2. Not a zone board: no PN532, no zcfg/zdb partitions, not a zone-flasher
// target. The banner below is what zones/flasher/zone_detect.py identifies this board by.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <NctPreshowProtocol.h>

using namespace nctzone;

constexpr const char *FIRMWARE_VERSION = "preshowbridge-1.0.0";
constexpr uint8_t CHANNEL = ESPNOW_CHANNEL;
constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
constexpr uint32_t CDC_TX_TIMEOUT_MS = 8;  // see the note in setup()

// Latest frame per SENDER, handed over by the Wi-Fi task. Keyed by the ESP-NOW source
// address rather than the point id in the packet, so two plates configured alike cannot
// overwrite one another here. Only the newest frame per sender matters; the sequence filter
// sorts out ordering.
struct Incoming {
  bool used;
  uint8_t mac[6];
  PreshowEvent event;
  uint32_t at;
  bool legacy;
};
Incoming inbox[PRESHOW_SENDER_COUNT] = {};
bool inboxPending = false;
portMUX_TYPE radioMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t packets = 0, legacyPackets = 0, duplicates = 0, lastPacket = 0;
uint32_t noSlot = 0, inboxOverruns = 0;

PreshowSender senders[PRESHOW_SENDER_COUNT] = {};
uint32_t epoch = 0;
bool radioReady = false, peerReady = false;
uint32_t logDrops = 0, cueDrops = 0, acksSent = 0, ackErrors = 0, cues = 0;
uint32_t lastBeacon = 0, lastClashLog = 0;

// What the plates are asking for, and what TouchDesigner has actually been told. They are
// separate on purpose: a cue line that could not be written (port not open, buffer full) must
// not be recorded as delivered, or it would never be retried. Every loop pass tries again to
// close the gap, so a dropped line costs milliseconds rather than a whole show cue.
uint8_t desiredMask = 0, emittedMask = 0;
uint32_t pointCues[PRESHOW_POINT_COUNT] = {};
uint32_t pointChangedAt[PRESHOW_POINT_COUNT] = {};

// Peers needed to unicast acknowledgements back. Four plates plus headroom; a slot is reused
// oldest-first, which in practice never happens.
struct PeerSlot {
  bool used;
  uint8_t mac[6];
  uint32_t at;
};
PeerSlot peers[PRESHOW_SENDER_COUNT] = {};

// Single loop-task producer, for everything that is NOT a cue. Never wait for a monitor to
// consume output: losing a diagnostic line is counted, and must never delay a cue.
void logLine(const char *format, ...) {
  char line[600];
  va_list args;
  va_start(args, format);
  int count = vsnprintf(line, sizeof(line) - 2, format, args);
  va_end(args);
  if (count < 0) return;
  size_t length = size_t(count) < sizeof(line) - 2 ? size_t(count) : sizeof(line) - 2;
  line[length++] = '\n';
  // Backpressure is the only gate, deliberately. `if (Serial)` on a native USB-JTAG C3 is
  // HWCDC's own notion of "host attached", and if it were ever false while something really
  // was reading, cue lines would be dropped silently — the worst failure this firmware has.
  // availableForWrite() answers the question that actually matters: can this be written now.
  if (Serial.availableForWrite() >= int(length)) Serial.write((const uint8_t *)line, length);
  else ++logDrops;
}

// Runs on the Wi-Fi task. Parse and hand over, nothing else: no Serial, no peer changes, no
// esp_now_send. Everything that can block belongs in the loop.
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (!info || !info->src_addr) return;
  PreshowEvent parsed = {};
  bool legacy = false;
  if (preshowFrameType(data, length) == PRESHOW_EVENT) {
    memcpy(&parsed, data, sizeof(parsed));
    if (!preshowEventValid(parsed)) return;
  } else if (length == PRESHOW_LEGACY_SIZE) {
    // The pre-2026 packet: two bare bytes, {pointID, state}. No header to check, so validate
    // the only thing there is to validate.
    if (!preshowPointValid(data[0]) || data[1] > 1) return;
    parsed.pointId = data[0];
    parsed.state = data[1];
    legacy = true;
  } else {
    return;
  }
  uint32_t now = millis();
  portENTER_CRITICAL(&radioMux);
  // One mailbox entry per sender. Prefer this sender's own entry, then a free one, then the
  // stalest - so a burst from one plate can never displace another plate's latest state.
  Incoming *slot = nullptr, *spare = nullptr, *stalest = nullptr;
  for (Incoming &e : inbox) {
    if (e.used && preshowSameMac(e.mac, info->src_addr)) { slot = &e; break; }
    if (!e.used) { if (!spare) spare = &e; continue; }
    if (!stalest || uint32_t(now - e.at) > uint32_t(now - stalest->at)) stalest = &e;
  }
  if (!slot) slot = spare ? spare : stalest;
  if (slot == stalest && !spare) ++inboxOverruns;
  slot->used = true;
  memcpy(slot->mac, info->src_addr, 6);
  slot->event = parsed;
  slot->at = now;
  slot->legacy = legacy;
  inboxPending = true;
  ++packets;
  if (legacy) ++legacyPackets;
  lastPacket = now;
  portEXIT_CRITICAL(&radioMux);
}

bool ensureAckPeer(const uint8_t *mac) {
  if (!radioReady) return false;
  uint32_t now = millis();
  PeerSlot *spare = nullptr, *oldest = nullptr;
  for (PeerSlot &p : peers) {
    if (p.used && preshowSameMac(p.mac, mac)) {
      p.at = now;
      if (esp_now_is_peer_exist(mac)) return true;
      p.used = false;  // lost underneath us; fall through and add it again
      break;
    }
    if (!p.used) { if (!spare) spare = &p; continue; }
    if (!oldest || uint32_t(now - p.at) > uint32_t(now - oldest->at)) oldest = &p;
  }
  PeerSlot *claim = spare ? spare : oldest;
  if (!claim) return false;
  if (claim->used && esp_now_is_peer_exist(claim->mac)) esp_now_del_peer(claim->mac);
  claim->used = false;
  if (!esp_now_is_peer_exist(mac)) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, mac, 6);
    peer.channel = CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) return false;
  }
  claim->used = true;
  memcpy(claim->mac, mac, 6);
  claim->at = now;
  return true;
}

// Acknowledge EVERY well-formed event, including one we have already applied. If only new
// events were acknowledged, a single lost ack would leave the plate retrying for its whole
// window and then reporting a delivery failure that never happened.
void sendAck(const uint8_t *mac, const PreshowEvent &event, bool applied) {
  if (!radioReady || !ensureAckPeer(mac)) { ++ackErrors; return; }
  PreshowAck ack = {};
  fillHeader(ack.h, PRESHOW_ACK);
  ack.bootId = event.bootId;
  ack.seq = event.seq;
  ack.pointId = event.pointId;
  ack.flags = applied ? PRESHOW_ACK_APPLIED : 0;
  if (esp_now_send(mac, (const uint8_t *)&ack, sizeof(ack)) == ESP_OK) ++acksSent;
  else ++ackErrors;
}

void takeEvents() {
  Incoming snapshot[PRESHOW_SENDER_COUNT];
  bool pending;
  portENTER_CRITICAL(&radioMux);
  memcpy(snapshot, inbox, sizeof(snapshot));
  pending = inboxPending;
  inboxPending = false;
  for (Incoming &e : inbox) e.used = false;
  portEXIT_CRITICAL(&radioMux);
  if (!pending) return;

  for (const Incoming &in : snapshot) {
    if (!in.used) continue;
    uint32_t now = millis();
    PreshowSender *sender = preshowSenderFor(senders, in.mac, now);
    if (!sender) {
      // Every entry belongs to a plate still being heard from, so there is nothing safe to
      // reclaim. Dropping the newcomer is better than losing track of a plate that works.
      ++noSlot;
      continue;
    }
    bool accepted = in.legacy ? preshowAcceptLegacy(*sender, in.event.pointId, in.event.state, in.at)
                              : preshowAccept(*sender, in.event, in.at);
    if (accepted) {
      uint8_t bit = preshowPointBit(sender->pointId);
      if (sender->state) desiredMask |= bit; else desiredMask &= uint8_t(~bit);
    } else {
      ++duplicates;
    }
    // Legacy senders have no sequence to echo and no plate waiting for an answer.
    if (!in.legacy) sendAck(in.mac, in.event, accepted);
  }

  uint32_t now = millis();
  uint8_t clashing = preshowPointClashes(senders, now);
  if (clashing && now - lastClashLog >= 30000) {
    lastClashLog = now;
    logLine("NOTE %u live plates share a point id with another. Their cues are fighting over "
            "the same TouchDesigner channel; check the flashed point ids.", clashing);
  }
}

// The one place that writes to TouchDesigner. Emits only on a real change, retries a line
// that could not be written, and never prints anything else.
void emitCues() {
  for (uint8_t point = 1; point <= PRESHOW_POINT_COUNT; ++point) {
    uint8_t bit = preshowPointBit(point);
    bool want = (desiredMask & bit) != 0;
    if (want == ((emittedMask & bit) != 0)) continue;
    char line[24];
    int count = snprintf(line, sizeof(line), "PRESHOW,%u,%s\n", point, want ? "ON" : "OFF");
    if (count <= 0) continue;
    // Backpressure only — see the note in logLine() about why `if (Serial)` must not gate this.
    if (Serial.availableForWrite() < count) { ++cueDrops; continue; }
    Serial.write((const uint8_t *)line, size_t(count));
    if (want) emittedMask |= bit; else emittedMask &= uint8_t(~bit);
    ++cues;
    ++pointCues[point - 1];
    pointChangedAt[point - 1] = millis();
  }
}

// Broadcast, because the bridge does not learn a plate's MAC until it has heard from it.
// Plates latch the source address of this frame and unicast their events back.
void sendBeacon() {
  if (!radioReady || !peerReady) return;
  PreshowBeacon beacon = {};
  fillHeader(beacon.h, PRESHOW_BEACON);
  beacon.epoch = epoch;
  beacon.uptimeS = millis() / 1000;
  // What TouchDesigner has been told, not what was merely asked for: a plate reading
  // bridge_sees_me is asking whether its cue landed, and an undelivered line has not.
  beacon.pointMask = emittedMask;
  beacon.version = PRESHOW_PROTOCOL_VERSION;
  beacon.channel = CHANNEL;
  esp_now_send(BROADCAST_MAC, (const uint8_t *)&beacon, sizeof(beacon));
}

// Printed only in response to a typed command. TouchDesigner is reading this port, so
// unsolicited output would reach its Serial DAT alongside the cues.
void status() {
  uint32_t count, legacyCount, dupes, seen, dropped, overruns;
  portENTER_CRITICAL(&radioMux);
  count = packets; legacyCount = legacyPackets; dupes = duplicates; seen = lastPacket;
  dropped = noSlot; overruns = inboxOverruns;
  portEXIT_CRITICAL(&radioMux);
  uint8_t actualChannel = 0;
  wifi_second_chan_t secondary;
  esp_wifi_get_channel(&actualChannel, &secondary);
  uint32_t now = millis();
  logLine("{\"device\":\"PreshowBridge\",\"type\":\"status\",\"firmware\":\"%s\",\"mac\":\"%s\","
          "\"uptime_ms\":%lu,\"channel\":%u,\"radio_ready\":%s,\"epoch\":%lu,\"desired_mask\":%u,"
          "\"emitted_mask\":%u,\"rx_packets\":%lu,\"rx_legacy\":%lu,\"rx_duplicates\":%lu,"
          "\"rx_no_slot\":%lu,\"rx_overruns\":%lu,\"last_rx_ms\":%lu,\"acks\":%lu,\"ack_errors\":%lu,"
          "\"cues\":%lu,\"cue_drops\":%lu,\"log_drops\":%lu,\"point_clashes\":%u}",
          FIRMWARE_VERSION, WiFi.macAddress().c_str(), (unsigned long)now, actualChannel,
          radioReady ? "true" : "false", (unsigned long)epoch, desiredMask, emittedMask,
          (unsigned long)count, (unsigned long)legacyCount, (unsigned long)dupes,
          (unsigned long)dropped, (unsigned long)overruns, (unsigned long)(now - seen),
          (unsigned long)acksSent, (unsigned long)ackErrors, (unsigned long)cues,
          (unsigned long)cueDrops, (unsigned long)logDrops, preshowPointClashes(senders, now));
  for (uint8_t point = 1; point <= PRESHOW_POINT_COUNT; ++point)
    logLine("{\"device\":\"PreshowBridge\",\"type\":\"point\",\"point\":%u,\"state\":\"%s\","
            "\"cues\":%lu,\"changed_ms\":%lu}",
            point, (emittedMask & preshowPointBit(point)) ? "ON" : "OFF",
            (unsigned long)pointCues[point - 1],
            (unsigned long)(pointChangedAt[point - 1] ? now - pointChangedAt[point - 1] : 0));
  // One line per known plate, addressed by MAC. `point` is what that board calls itself.
  for (const PreshowSender &s : senders) {
    if (!s.valid) continue;
    logLine("{\"device\":\"PreshowBridge\",\"type\":\"plate\",\"mac\":\"%02X:%02X:%02X:%02X:%02X:%02X\","
            "\"point\":%u,\"state\":\"%s\",\"seq\":%u,\"boot_id\":%lu,\"legacy\":%s,\"seen_ms\":%lu}",
            s.mac[0], s.mac[1], s.mac[2], s.mac[3], s.mac[4], s.mac[5], s.pointId,
            s.state ? "ON" : "OFF", s.seq, (unsigned long)s.bootId, s.legacy ? "true" : "false",
            (unsigned long)(now - s.seen));
  }
}

void serialCommands() {
  static char input[32];
  static size_t used = 0;
  static bool overflow = false;
  for (int i = 0; i < 64 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      input[used] = 0;
      if (overflow || !used) { /* nothing typed, or a line too long to be a command */ }
      else if (!strcmp(input, "?") || !strcmp(input, "STATUS")) status();
      else if (!strcmp(input, "help")) {
        logLine("PRESHOW BRIDGE %s: ? or STATUS = report, TEST <1-%u> ON|OFF = drive a cue by hand.",
                FIRMWARE_VERSION, PRESHOW_POINT_COUNT);
      } else if (!strncmp(input, "TEST ", 5)) {
        // For checking the TouchDesigner end without a plate. It writes a real cue line, so
        // the next event from the owning plate puts the point back where it belongs.
        unsigned point = 0;
        char state[8] = {};
        if (sscanf(input + 5, "%u %7s", &point, state) != 2 || !preshowPointValid(uint8_t(point)) ||
            (strcmp(state, "ON") && strcmp(state, "OFF"))) {
          logLine("ERR TEST: expected TEST <1-%u> ON|OFF", PRESHOW_POINT_COUNT);
        } else {
          uint8_t bit = preshowPointBit(uint8_t(point));
          if (!strcmp(state, "ON")) desiredMask |= bit; else desiredMask &= uint8_t(~bit);
          logLine("TEST point %u %s", point, state);
        }
      } else logLine("ERR command; try help");
      used = 0;
      overflow = false;
    } else if (used < sizeof(input) - 1) input[used++] = c;
    else overflow = true;
  }
}

void setup() {
  Serial.setTxBufferSize(4096);
  Serial.begin(115200);
  // Small, not zero. Serial here is HWCDC over native USB; a few milliseconds lets a write
  // wait for the host's next poll instead of giving up the instant the ring is momentarily
  // full, which matters when the line being written is a show cue. It is also the entire
  // budget a write can ever consume, which nothing here can notice: the beacon is every
  // 500 ms and a cue line is fourteen bytes into a 4 KB buffer.
  Serial.setTxTimeoutMs(CDC_TX_TIMEOUT_MS);
  delay(500);

  for (auto &s : senders) s = PreshowSender{};
  for (auto &p : peers) p = PeerSlot{};
  portENTER_CRITICAL(&radioMux);
  for (Incoming &e : inbox) e.used = false;
  inboxPending = false;
  portEXIT_CRITICAL(&radioMux);
  desiredMask = emittedMask = 0;
  for (auto &c : pointCues) c = 0;
  for (auto &t : pointChangedAt) t = 0;
  packets = legacyPackets = duplicates = lastPacket = noSlot = inboxOverruns = 0;
  logDrops = cueDrops = acksSent = ackErrors = cues = 0;
  lastBeacon = lastClashLog = 0;

  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  // setSleep(false) matters: modem sleep duty-cycles the receiver and silently drops frames.
  // The legacy bridge never disabled it, which is one reason a cue could vanish.
  radioReady = WiFi.mode(WIFI_STA) && WiFi.setSleep(false) &&
               esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK &&
               esp_now_init() == ESP_OK && esp_now_register_recv_cb(onReceive) == ESP_OK;
  peerReady = false;
  if (radioReady && !esp_now_is_peer_exist(BROADCAST_MAC)) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    peerReady = esp_now_add_peer(&peer) == ESP_OK;
  } else if (radioReady) peerReady = true;
  epoch = esp_random();
  if (!epoch) epoch = 1;  // 0 is reserved so a plate can tell "no beacon seen yet"

  // The only unsolicited output, and only at boot. "NCT PRESHOW MEDIA BRIDGE" is the string
  // zones/flasher/zone_detect.py identifies this board by; do not change it.
  logLine("==============================");
  logLine("NCT PRESHOW MEDIA BRIDGE");
  logLine("%s  ESP-NOW CH%u -> SERIAL DAT", FIRMWARE_VERSION, CHANNEL);
  logLine("MAC=%s epoch=%lu radio=%s", WiFi.macAddress().c_str(), (unsigned long)epoch,
          radioReady && peerReady ? "ready" : "FAILED");
  logLine("==============================");
}

void loop() {
  takeEvents();
  emitCues();
  serialCommands();
  uint32_t now = millis();
  if (now - lastBeacon >= PRESHOW_BEACON_MS) {
    lastBeacon = now;
    sendBeacon();
  }
  delay(1);
}
