#pragma once
// Host stand-ins for the Arduino-ESP32 APIs used by NctZone and zone sketches.
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cstdarg>
#include <cmath>
#include <cassert>
#include <string>
#include <vector>
#include <deque>
#include <map>
using std::size_t;

// ---- time / GPIO / system ----
inline uint32_t fakeNow = 0;
inline uint32_t millis() { return fakeNow; }
inline void delay(unsigned ms) { fakeNow += ms; }
inline void delayMicroseconds(unsigned) {}
constexpr int HIGH = 1, LOW = 0, INPUT = 0, OUTPUT = 3, INPUT_PULLUP = 1, OUTPUT_OPEN_DRAIN = 2;
inline std::map<int, int> pinLevels;
inline std::vector<std::pair<int, int>> pinWrites;
inline void pinMode(int, int) {}
inline std::map<int, int> heldLow;  // pin -> remaining SCL pulses before an external device releases it (-1 = never)
inline int sclPulses = 0;
inline int stubSclPin = 3;  // zones use SDA 4 / SCL 3; the pool central uses SDA 8 / SCL 9
inline void digitalWrite(int pin, int level) { pinLevels[pin] = level; pinWrites.push_back({pin, level}); if (pin == stubSclPin && level == HIGH) { sclPulses++; for (auto &h : heldLow) if (h.second > 0) h.second--; } }
inline int digitalRead(int pin) { if (heldLow.count(pin) && heldLow[pin] != 0) return LOW; return pinLevels.count(pin) ? pinLevels[pin] : HIGH; }
// ---- critical sections ----
// Single-threaded on the host, but the depth counter lets tests assert the discipline
// that matters: no Serial and no I2C work may happen inside a critical section, and the
// ESP-NOW receive callback must do nothing but hand the frame over.
inline int i2cTransactions = 0;  // counted here so the Wi-Fi stub can record boot ordering
inline int criticalDepth = 0;
struct portMUX_TYPE { int unused = 0; };
#define portMUX_INITIALIZER_UNLOCKED {}
inline void portENTER_CRITICAL(portMUX_TYPE *) { ++criticalDepth; }
inline void portEXIT_CRITICAL(portMUX_TYPE *) { assert(criticalDepth > 0); --criticalDepth; }
inline void portENTER_CRITICAL_ISR(portMUX_TYPE *m) { portENTER_CRITICAL(m); }
inline void portEXIT_CRITICAL_ISR(portMUX_TYPE *m) { portEXIT_CRITICAL(m); }

inline uint32_t randomCounter = 0;
inline uint32_t esp_random() { return (randomCounter++ * 97u) + 13u; }
// Arduino random(lo, hi): [lo, hi). Deterministic; the neocube's show effects use it.
inline long random(long lo, long hi) { return hi > lo ? lo + long(esp_random() % uint32_t(hi - lo)) : lo; }
inline void randomSeed(uint32_t) {}
constexpr int D10 = 10;  // XIAO ESP32-C3 LED pin used by the neocube
struct EspClass { bool restarted = false; void restart() { restarted = true; } };
inline EspClass ESP;

using String = std::string;

// Space the host is willing to accept without blocking. Setting this to 0 models a USB
// CDC port nobody is draining, which is what stalled the Wi-Fi task in the live central.
inline int serialTxSpace = 4096;
inline bool serialConnected = true;
inline int serialWrites = 0;

struct SerialStub {
  std::string output, input;
  void begin(int) {}
  void setRxBufferSize(int) {}
  void setTxBufferSize(int) {}
  void setTxTimeoutMs(int) {}
  explicit operator bool() const { return serialConnected; }
  int availableForWrite() { return serialTxSpace; }
  int available() { return int(input.size()); }
  char read() { char c = input[0]; input.erase(0, 1); return c; }
  void flush() {}
  // Every path records a write and forbids output from inside a critical section.
  void note() { ++serialWrites; assert(criticalDepth == 0 && "Serial write inside a critical section"); }
  int printf(const char *fmt, ...) {
    char buffer[512];
    va_list args; va_start(args, fmt); int n = vsnprintf(buffer, sizeof(buffer), fmt, args); va_end(args);
    note(); output += buffer; return n;
  }
  void print(const char *s) { note(); output += s; }
  void println(const char *s) { note(); output += s; output += "\n"; }
  void println() { note(); output += "\n"; }
  // Arduino Print overloads for numbers and String (the neocube prints both).
  void print(const std::string &s) { print(s.c_str()); }
  void println(const std::string &s) { println(s.c_str()); }
  void print(char c) { note(); output.push_back(c); }
  void print(unsigned long long v) { print(std::to_string(v)); }
  void print(long long v) { print(std::to_string(v)); }
  void print(unsigned long v) { print(std::to_string(v)); }
  void print(long v) { print(std::to_string(v)); }
  void print(unsigned v) { print(std::to_string(v)); }
  void print(int v) { print(std::to_string(v)); }
  template <typename T> void println(T v) { print(v); println(); }
  size_t write(uint8_t c) { note(); output.push_back(char(c)); return 1; }
  size_t write(const uint8_t *data, size_t len) { note(); output.append((const char *)data, len); return len; }
};
inline SerialStub Serial;

// ---- Wi-Fi ----
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1, WIFI_STA = 1, WIFI_SECOND_CHAN_NONE = 0;
enum wifi_interface_t { WIFI_IF_STA = 0 };
inline int radioChannel = 1;
// Modem sleep duty-cycles the receiver and silently drops broadcasts; the live central
// never turned it off. Recorded so a test can assert setSleep(false) actually happened.
inline bool wifiSleep = true, wifiPersistent = true, wifiAutoReconnect = true;
inline int i2cAtWifiMode = -1;  // i2cTransactions when the radio was first brought up
struct WiFiStub {
  bool mode(int) { if (i2cAtWifiMode < 0) i2cAtWifiMode = i2cTransactions; return true; }
  bool disconnect() { return true; }
  bool setSleep(bool on) { wifiSleep = on; return true; }
  void persistent(bool on) { wifiPersistent = on; }
  void setAutoReconnect(bool on) { wifiAutoReconnect = on; }
  std::string macAddress() { return "02:AA:BB:CC:DD:EE"; }
  void macAddress(uint8_t *mac) { const uint8_t self[6] = {0x02, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE}; memcpy(mac, self, 6); }
  int channel() { return radioChannel; }
};
inline WiFiStub WiFi;
inline int esp_wifi_set_channel(int channel, int) { radioChannel = channel; return ESP_OK; }
using wifi_second_chan_t = int;
inline int esp_wifi_get_channel(uint8_t *primary, wifi_second_chan_t *second) {
  if (primary) *primary = uint8_t(radioChannel);
  if (second) *second = WIFI_SECOND_CHAN_NONE;
  return ESP_OK;
}

// ---- ESP-NOW ----
// rx_ctrl carries the signal strength on the real driver; the dongles report it to the zone
// manager. Left null by tests that do not care (aggregate-initialised from two members).
struct wifi_pkt_rx_ctrl_t { int rssi; };
struct esp_now_recv_info_t { uint8_t *src_addr; uint8_t *des_addr; wifi_pkt_rx_ctrl_t *rx_ctrl = nullptr; };
struct esp_now_send_info_t { uint8_t *des_addr; uint8_t *src_addr; };
enum esp_now_send_status_t { ESP_NOW_SEND_SUCCESS = 0, ESP_NOW_SEND_FAIL };
struct esp_now_peer_info_t { uint8_t peer_addr[6]; uint8_t lmk[16]; uint8_t channel; wifi_interface_t ifidx; bool encrypt; };
using esp_now_recv_cb_t = void (*)(const esp_now_recv_info_t *, const uint8_t *, int);
using esp_now_send_cb_t = void (*)(const esp_now_send_info_t *, esp_now_send_status_t);
struct SentFrame { std::vector<uint8_t> dest, data; };
inline std::vector<std::vector<uint8_t>> espPeers;
inline std::vector<SentFrame> sentFrames;
inline esp_now_recv_cb_t recvCallback = nullptr;
inline esp_now_send_cb_t sendCallback = nullptr;
inline bool autoSendCallback = true, sendDelivered = true, failSends = false;
inline int esp_now_init() { return ESP_OK; }
inline int esp_now_register_recv_cb(esp_now_recv_cb_t cb) { recvCallback = cb; return ESP_OK; }
inline int esp_now_register_send_cb(esp_now_send_cb_t cb) { sendCallback = cb; return ESP_OK; }
inline bool esp_now_is_peer_exist(const uint8_t *mac) {
  for (auto &p : espPeers) if (!memcmp(p.data(), mac, 6)) return true;
  return false;
}
inline int esp_now_add_peer(const esp_now_peer_info_t *peer) {
  // Channel 0 means "the current channel" (the neocube's peers), acceptable only once the radio is on 2.
  assert((peer->channel == 2 || (peer->channel == 0 && radioChannel == 2)) && !peer->encrypt);
  assert(!esp_now_is_peer_exist(peer->peer_addr));
  if (espPeers.size() >= 20) return ESP_FAIL;  // ESP-NOW unencrypted peer limit
  espPeers.emplace_back(peer->peer_addr, peer->peer_addr + 6);
  return ESP_OK;
}
inline int esp_now_del_peer(const uint8_t *mac) {
  for (auto i = espPeers.begin(); i != espPeers.end(); ++i)
    if (!memcmp(i->data(), mac, 6)) { espPeers.erase(i); return ESP_OK; }
  return ESP_FAIL;
}
inline int esp_now_send(const uint8_t *mac, const uint8_t *data, size_t len) {
  assert(len <= 250);
  if (failSends || !esp_now_is_peer_exist(mac)) return ESP_FAIL;
  sentFrames.push_back({std::vector<uint8_t>(mac, mac + 6), std::vector<uint8_t>(data, data + len)});
  if (autoSendCallback && sendCallback) {
    uint8_t dest[6]; memcpy(dest, mac, 6);
    esp_now_send_info_t info{dest, nullptr};
    sendCallback(&info, sendDelivered ? ESP_NOW_SEND_SUCCESS : ESP_NOW_SEND_FAIL);
  }
  return ESP_OK;
}

// ---- FreeRTOS queues ----
struct FakeQueue { size_t capacity, itemSize; std::deque<std::vector<uint8_t>> items; };
using QueueHandle_t = FakeQueue *;
constexpr int pdTRUE = 1, pdFALSE = 0;
#define pdMS_TO_TICKS(x) (x)
inline QueueHandle_t xQueueCreate(int n, size_t size) { return new FakeQueue{size_t(n), size, {}}; }
inline int xQueueSend(QueueHandle_t q, const void *item, int) {
  if (q->items.size() >= q->capacity) return pdFALSE;
  q->items.emplace_back((const uint8_t *)item, (const uint8_t *)item + q->itemSize);
  return pdTRUE;
}
// FreeRTOS allows overwrite only on a one-deep queue: the item replaces whatever is unread.
inline int xQueueOverwrite(QueueHandle_t q, const void *item) {
  assert(q->capacity == 1);
  q->items.clear();
  q->items.emplace_back((const uint8_t *)item, (const uint8_t *)item + q->itemSize);
  return pdTRUE;
}
inline int xQueueReceive(QueueHandle_t q, void *item, int) {
  if (q->items.empty()) return pdFALSE;
  memcpy(item, q->items.front().data(), q->itemSize);
  q->items.pop_front();
  return pdTRUE;
}

// ---- Flash partitions (NOR semantics: writes can only clear bits) ----
constexpr int ESP_PARTITION_TYPE_DATA = 1, ESP_PARTITION_SUBTYPE_ANY = 0xFF;
struct esp_partition_t { const char *label; uint32_t size; std::vector<uint8_t> *data; };
inline long partitionWriteBudget = -1;  // bytes allowed before writes fail (simulated power loss)
inline std::map<std::string, esp_partition_t *> &partitionTable() {
  static std::map<std::string, esp_partition_t *> table;
  return table;
}
inline bool partitionsInstalled = true;
inline esp_partition_t *fakePartition(const std::string &label) {
  auto &table = partitionTable();
  if (!table.count(label)) {
    uint32_t size = label == "zcfg" ? 0x1000 : 0x8000;
    auto *storage = new std::vector<uint8_t>(size, 0xFF);
    table[label] = new esp_partition_t{strdup(label.c_str()), size, storage};
  }
  return table[label];
}
inline const esp_partition_t *esp_partition_find_first(int, int, const char *label) {
  if (!partitionsInstalled) return nullptr;
  return fakePartition(label);
}
inline int esp_partition_read(const esp_partition_t *p, size_t offset, void *out, size_t len) {
  if (offset + len > p->size) return ESP_FAIL;
  memcpy(out, p->data->data() + offset, len);
  return ESP_OK;
}
inline int esp_partition_write(const esp_partition_t *p, size_t offset, const void *src, size_t len) {
  if (offset + len > p->size) return ESP_FAIL;
  const uint8_t *bytes = (const uint8_t *)src;
  for (size_t i = 0; i < len; i++) {
    if (partitionWriteBudget == 0) return ESP_FAIL;
    if (partitionWriteBudget > 0) partitionWriteBudget--;
    (*p->data)[offset + i] &= bytes[i];
  }
  return ESP_OK;
}
inline int esp_partition_erase_range(const esp_partition_t *p, size_t offset, size_t len) {
  if (offset + len > p->size) return ESP_FAIL;
  std::fill(p->data->begin() + offset, p->data->begin() + offset + len, 0xFF);
  return ESP_OK;
}

// ---- I2C / PN532 ----
inline int wireBegins = 0;
inline int wireSda = -1, wireScl = -1;  // pins of the last Wire.begin()
inline int pn532Sda = 4, pn532Scl = 3;  // pins the reader is wired to (zones: SDA 4 / SCL 3); -1 = it answers on any

// Two PCA9685 LED drivers, modelled well enough to test what the live central got wrong:
// unchecked writes, a shadow cache that never re-asserted, and ALL_LED never being cleared.
struct FakePca {
  uint8_t address = 0;
  bool present = true;
  uint8_t reg[256] = {};
  uint8_t nackWrites = 0;  // fail this many upcoming transactions, then recover
  int writes = 0, reads = 0;
  void powerOn() {
    memset(reg, 0, sizeof(reg));
    reg[0] = 0x11;  // MODE1: SLEEP set, auto-increment clear, as after a real reset
    reg[1] = 0x04;  // MODE2
    // Every LEDn powers up FULL_OFF (bit 4 of LEDn_OFF_H), which drives the channel LOW.
    // That is not a neutral state: with active-low relays a LOW channel energises the coil,
    // so at power-on the hardware is asking for every lamp to be ON until firmware says
    // otherwise. Modelled faithfully so a test can catch a boot that leaves it that way.
    for (uint8_t c = 0; c < 16; ++c) reg[9 + 4 * c] = 0x10;  // LEDn_OFF_H bit 4 = FULL_OFF
    reg[0xFA] = 0x00; reg[0xFB] = 0x00; reg[0xFC] = 0x00; reg[0xFD] = 0x10;
  }
  FakePca() { powerOn(); }
  bool autoIncrement() const { return reg[0] & 0x20; }
};
inline FakePca pcaBoards[2];
inline bool i2cBusStuck = false;

inline void resetPcaBoards() {
  pcaBoards[0] = FakePca(); pcaBoards[0].address = 0x40;
  pcaBoards[1] = FakePca(); pcaBoards[1].address = 0x41;
  i2cBusStuck = false;
}
inline FakePca *pcaAt(uint8_t address) {
  for (auto &b : pcaBoards) if (b.address == address && b.present) return &b;
  return nullptr;
}

// PN532 command channel for the RX gain: when pn532AcceptsCommands, sendCommandCheckAck() queues the
// reply the next Wire.requestFrom() at the PN532 address returns, and CIU_RFCfg is tracked in pn532RfCfg.
inline bool pn532AcceptsCommands = false;
inline std::deque<uint8_t> pn532Reply;
inline uint8_t pn532RfCfg = 0x59;
inline int pn532GainCommands = 0;
struct WireStub {
  uint8_t target = 0;
  std::vector<uint8_t> outgoing;
  std::deque<uint8_t> incoming;
  bool started = false;

  void note() { ++i2cTransactions; assert(criticalDepth == 0 && "I2C transaction inside a critical section"); }
  bool begin(int sda, int scl) { note(); wireBegins++; wireSda = sda; wireScl = scl; started = true; return true; }
  bool begin(int sda, int scl, uint32_t) { return begin(sda, scl); }
  void end() { started = false; }
  void setTimeOut(int) {}
  bool setClock(uint32_t) { return true; }
  void beginTransmission(uint8_t address) { note(); target = address; outgoing.clear(); }
  size_t write(uint8_t value) { outgoing.push_back(value); return 1; }
  size_t write(const uint8_t *data, size_t len) { outgoing.insert(outgoing.end(), data, data + len); return len; }

  // 0 success, 2 address NACK, 5 timeout -- the Arduino-ESP32 codes.
  uint8_t endTransmission(bool = true) {
    note();
    if (!started || i2cBusStuck) return 5;
    FakePca *board = pcaAt(target);
    if (!board) return 2;
    if (board->nackWrites) { --board->nackWrites; return 2; }
    if (outgoing.empty()) return 0;  // address probe
    uint8_t pointer = outgoing[0];
    board->writes++;
    for (size_t i = 1; i < outgoing.size(); ++i) {
      board->reg[pointer] = outgoing[i];
      if (board->autoIncrement()) pointer = uint8_t(pointer + 1);  // frozen without AI
    }
    return 0;
  }

  size_t requestFrom(uint8_t address, size_t count, bool = true) {
    note();
    incoming.clear();
    if (!started || i2cBusStuck) return 0;
    if (address == (0x48 >> 1)) {
      if (pn532Reply.empty()) return 0;
      incoming.assign(pn532Reply.begin(), pn532Reply.end());
      pn532Reply.clear();
      while (incoming.size() < count) incoming.push_back(0);
      return count;
    }
    FakePca *board = pcaAt(address);
    if (!board) return 0;
    board->reads++;
    uint8_t pointer = outgoing.empty() ? 0 : outgoing[0];
    for (size_t i = 0; i < count; ++i) {
      incoming.push_back(board->reg[pointer]);
      if (board->autoIncrement()) pointer = uint8_t(pointer + 1);
    }
    return count;
  }
  int available() { return int(incoming.size()); }
  int read() { if (incoming.empty()) return -1; int v = incoming.front(); incoming.pop_front(); return v; }
};
inline WireStub Wire;
constexpr int PN532_MIFARE_ISO14443A = 0;
constexpr uint8_t PN532_I2C_ADDRESS = 0x48 >> 1, PN532_PN532TOHOST = 0xD5, PN532_COMMAND_RFCONFIGURATION = 0x32,
                  PN532_COMMAND_READREGISTER = 0x06;
inline std::vector<uint8_t> presentedTag;
inline bool pn532Present = true;
inline bool pn532Reachable() {
  return pn532Present && (pn532Sda < 0 || (wireSda == pn532Sda && wireScl == pn532Scl));
}
struct Adafruit_PN532 {
  Adafruit_PN532(int, int) {}
  Adafruit_PN532(int, int, WireStub *) {}  // the Workstation's own Pn532Wire instance
  void begin() {}
  uint32_t getFirmwareVersion() { return pn532Reachable() ? 0x32010607 : 0; }
  bool SAMConfig() { return true; }
  // Without pn532AcceptsCommands the host has no reader command channel: the gain reports itself as not applied.
  bool sendCommandCheckAck(uint8_t *command, uint8_t length, uint16_t = 100) {
    if (!pn532Reachable() || !pn532AcceptsCommands || !length) return false;
    // Reply: ready byte, 00 00 FF LEN LCS D5 <cmd+1> [data] DCS 00
    pn532Reply = {0x01, 0x00, 0x00, 0xFF, 0x02, 0xFE, PN532_PN532TOHOST, uint8_t(command[0] + 1)};
    if (command[0] == PN532_COMMAND_RFCONFIGURATION && length >= 3 && command[1] == 0x0A) {
      pn532RfCfg = command[2];
      pn532GainCommands++;
    } else if (command[0] == PN532_COMMAND_READREGISTER) {
      pn532Reply.push_back(pn532RfCfg);
    }
    pn532Reply.push_back(0x00);
    pn532Reply.push_back(0x00);
    return true;
  }
  bool readPassiveTargetID(int, uint8_t *uid, uint8_t *length, int timeout) {
    if (!pn532Reachable()) return false;  // command not acknowledged: returns at once
    fakeNow += presentedTag.empty() ? timeout : 20;
    if (presentedTag.empty()) return false;
    *length = uint8_t(presentedTag.size());
    memcpy(uid, presentedTag.data(), presentedTag.size());
    return true;
  }
};

// ---- WS2812 strip (Adafruit_NeoPixel): the latest frame shown, as 0xRRGGBB per pixel ----
constexpr int NEO_GRB = 0x52, NEO_KHZ800 = 0x0000;
inline std::vector<uint32_t> neoShown;
inline int neoShows = 0;
struct Adafruit_NeoPixel {
  std::vector<uint32_t> buffer;
  Adafruit_NeoPixel(int count, int, int) : buffer(count, 0) {}
  void begin() {}
  void clear() { std::fill(buffer.begin(), buffer.end(), 0u); }
  void setPixelColor(int i, uint8_t r, uint8_t g, uint8_t b) {
    assert(i >= 0 && i < int(buffer.size()));
    buffer[i] = (uint32_t(r) << 16) | (uint32_t(g) << 8) | b;
  }
  void setPixelColor(int i, uint32_t c) { setPixelColor(i, uint8_t(c >> 16), uint8_t(c >> 8), uint8_t(c)); }
  static uint32_t Color(uint8_t r, uint8_t g, uint8_t b) { return (uint32_t(r) << 16) | (uint32_t(g) << 8) | b; }
  void show() { neoShown = buffer; ++neoShows; }
};

// ---- VL53L4CD time-of-flight sensor ----
inline bool laserPresent = true;
inline uint16_t laserDistance = 0;
inline uint8_t laserStatus = 0;            // VL53L4CD range_status; non-zero is an invalid reading
inline bool laserReady = true;             // dataReady()
inline uint8_t laserBudgetMs = 0;          // last accepted timing budget
inline uint32_t laserIntervalMs = 0;       // last accepted inter-measurement period
inline int laserContinuous = 0;            // startContinuous/stopContinuous balance
struct VL53L4CD {
  struct { uint8_t range_status = 0; } ranging_data;
  void setTimeout(uint16_t) {}
  bool init(bool = true, bool = false) { return laserPresent; }
  bool dataReady() { ranging_data.range_status = laserStatus; return laserReady; }
  // Mirrors the real library's limits: budget 10..200 ms, period 0 or above the budget.
  bool setRangeTiming(uint8_t budget, uint32_t interval) {
    if (budget < 10 || budget > 200) return false;
    if (interval != 0 && interval <= budget) return false;
    laserBudgetMs = budget; laserIntervalMs = interval; return true;
  }
  void startContinuous() { laserContinuous++; }
  void stopContinuous() { laserContinuous--; }
  uint16_t readRangeContinuousMillimeters(bool = true) { ranging_data.range_status = laserStatus; return laserDistance; }
  bool timeoutOccurred() { return false; }
};

// Preferences blob storage survives simulated sketch restarts. Keyed by
// namespace+key: PoolZone stores calibration and tuning as separate blobs.
struct Preferences {
  inline static std::map<std::string, std::vector<uint8_t>> blobs;
  std::string space;
  bool begin(const char *name, bool) { space = name ? name : ""; return true; }
  void end() { space.clear(); }
  std::string at(const char *key) const { return space + "/" + (key ? key : ""); }
  size_t getBytesLength(const char *key) {
    auto it = blobs.find(at(key));
    return it == blobs.end() ? 0 : it->second.size();
  }
  size_t putBytes(const char *key, const void *p, size_t n) {
    blobs[at(key)].assign((const uint8_t*)p, (const uint8_t*)p+n); return n;
  }
  size_t getBytes(const char *key, void *p, size_t n) {
    auto it = blobs.find(at(key));
    if (it == blobs.end() || it->second.size()!=n) return 0;
    memcpy(p, it->second.data(), n); return n;
  }
  // Scalars are stored as little-endian blobs of their own size (the neocube keeps its
  // registration and show version this way).
  template <typename T> T getScalar(const char *key, T fallback) {
    auto it = blobs.find(at(key));
    if (it == blobs.end() || it->second.size() != sizeof(T)) return fallback;
    T v; memcpy(&v, it->second.data(), sizeof v); return v;
  }
  uint32_t getUInt(const char *key, uint32_t fallback = 0) { return getScalar<uint32_t>(key, fallback); }
  uint8_t getUChar(const char *key, uint8_t fallback = 0) { return getScalar<uint8_t>(key, fallback); }
  size_t putUInt(const char *key, uint32_t v) { return putBytes(key, &v, sizeof v); }
  size_t putUChar(const char *key, uint8_t v) { return putBytes(key, &v, sizeof v); }
};
