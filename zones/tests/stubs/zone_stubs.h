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
constexpr int HIGH = 1, LOW = 0, OUTPUT = 3, INPUT_PULLUP = 1, OUTPUT_OPEN_DRAIN = 2;
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
inline int criticalDepth = 0;
struct portMUX_TYPE { int unused = 0; };
#define portMUX_INITIALIZER_UNLOCKED {}
inline void portENTER_CRITICAL(portMUX_TYPE *) { ++criticalDepth; }
inline void portEXIT_CRITICAL(portMUX_TYPE *) { assert(criticalDepth > 0); --criticalDepth; }
inline void portENTER_CRITICAL_ISR(portMUX_TYPE *m) { portENTER_CRITICAL(m); }
inline void portEXIT_CRITICAL_ISR(portMUX_TYPE *m) { portEXIT_CRITICAL(m); }

inline uint32_t randomCounter = 0;
inline uint32_t esp_random() { return (randomCounter++ * 97u) + 13u; }
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
struct WiFiStub {
  bool mode(int) { return true; }
  bool disconnect() { return true; }
  bool setSleep(bool on) { wifiSleep = on; return true; }
  void persistent(bool on) { wifiPersistent = on; }
  void setAutoReconnect(bool on) { wifiAutoReconnect = on; }
  std::string macAddress() { return "02:AA:BB:CC:DD:EE"; }
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
struct esp_now_recv_info_t { uint8_t *src_addr; uint8_t *des_addr; };
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
  assert(peer->channel == 2 && !peer->encrypt);
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
    // ALL_LED_ON/OFF come up non-zero so firmware that never clears them is caught.
    reg[0xFA] = 0x00; reg[0xFB] = 0x10; reg[0xFC] = 0x00; reg[0xFD] = 0x00;
  }
  FakePca() { powerOn(); }
  bool autoIncrement() const { return reg[0] & 0x20; }
};
inline FakePca pcaBoards[2];
inline bool i2cBusStuck = false;
inline int i2cTransactions = 0;

inline void resetPcaBoards() {
  pcaBoards[0] = FakePca(); pcaBoards[0].address = 0x40;
  pcaBoards[1] = FakePca(); pcaBoards[1].address = 0x41;
  i2cBusStuck = false;
}
inline FakePca *pcaAt(uint8_t address) {
  for (auto &b : pcaBoards) if (b.address == address && b.present) return &b;
  return nullptr;
}

struct WireStub {
  uint8_t target = 0;
  std::vector<uint8_t> outgoing;
  std::deque<uint8_t> incoming;
  bool started = false;

  void note() { ++i2cTransactions; assert(criticalDepth == 0 && "I2C transaction inside a critical section"); }
  bool begin(int, int) { note(); wireBegins++; started = true; return true; }
  bool begin(int, int, uint32_t) { return begin(0, 0); }
  void end() { started = false; }
  void setTimeOut(int) {}
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
inline std::vector<uint8_t> presentedTag;
inline bool pn532Present = true;
struct Adafruit_PN532 {
  Adafruit_PN532(int, int) {}
  void begin() {}
  uint32_t getFirmwareVersion() { return pn532Present ? 0x32010607 : 0; }
  bool SAMConfig() { return true; }
  bool readPassiveTargetID(int, uint8_t *uid, uint8_t *length, int timeout) {
    if (!pn532Present) return false;  // command not acknowledged: returns at once
    fakeNow += presentedTag.empty() ? timeout : 20;
    if (presentedTag.empty()) return false;
    *length = uint8_t(presentedTag.size());
    memcpy(uid, presentedTag.data(), presentedTag.size());
    return true;
  }
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
};
