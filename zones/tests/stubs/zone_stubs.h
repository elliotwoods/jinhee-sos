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
inline void digitalWrite(int pin, int level) { pinLevels[pin] = level; pinWrites.push_back({pin, level}); if (pin == 3 && level == HIGH) { sclPulses++; for (auto &h : heldLow) if (h.second > 0) h.second--; } }
inline int digitalRead(int pin) { if (heldLow.count(pin) && heldLow[pin] != 0) return LOW; return pinLevels.count(pin) ? pinLevels[pin] : HIGH; }
inline uint32_t randomCounter = 0;
inline uint32_t esp_random() { return (randomCounter++ * 97u) + 13u; }
struct EspClass { bool restarted = false; void restart() { restarted = true; } };
inline EspClass ESP;

using String = std::string;

struct SerialStub {
  std::string output, input;
  void begin(int) {}
  void setRxBufferSize(int) {}
  int available() { return int(input.size()); }
  char read() { char c = input[0]; input.erase(0, 1); return c; }
  void flush() {}
  int printf(const char *fmt, ...) {
    char buffer[512];
    va_list args; va_start(args, fmt); int n = vsnprintf(buffer, sizeof(buffer), fmt, args); va_end(args);
    output += buffer; return n;
  }
  void print(const char *s) { output += s; }
  void println(const char *s) { output += s; output += "\n"; }
  void println() { output += "\n"; }
  size_t write(uint8_t c) { output.push_back(char(c)); return 1; }
};
inline SerialStub Serial;

// ---- Wi-Fi ----
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1, WIFI_STA = 1, WIFI_SECOND_CHAN_NONE = 0;
enum wifi_interface_t { WIFI_IF_STA = 0 };
inline int radioChannel = 1;
struct WiFiStub {
  bool mode(int) { return true; }
  bool disconnect() { return true; }
  std::string macAddress() { return "02:AA:BB:CC:DD:EE"; }
  int channel() { return radioChannel; }
};
inline WiFiStub WiFi;
inline int esp_wifi_set_channel(int channel, int) { radioChannel = channel; return ESP_OK; }

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
struct WireStub { void begin(int, int) { wireBegins++; } void end() {} void setTimeOut(int) {} };
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
struct VL53L4CD {
  void setTimeout(uint16_t) {}
  bool init(bool = true, bool = false) { return laserPresent; }
  void startContinuous() {}
  uint16_t readRangeContinuousMillimeters(bool = true) { return laserDistance; }
  bool timeoutOccurred() { return false; }
};
