#pragma once
// ESP-NOW management link for zone boards: receives database updates, answers registry
// queries, keeps tag statistics/log, and manages a small LRU of ESP-NOW peers.
// receive() may be called from the Wi-Fi task; everything else runs in loop() via poll().
#include <Arduino.h>
#include <esp_now.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "NctZoneDb.h"

namespace nctzone {

class ZoneLink {
 public:
  static constexpr uint32_t STAGING_TIMEOUT_MS = 60000;
  static constexpr uint32_t REPLY_JITTER_MS = 250;
  static constexpr int MAX_PEERS = 8;
  static constexpr int PENDING_REPLIES = 4;
  static constexpr int QUEUE_DEPTH = 32;

  bool begin(ZoneDb &db, const ZoneConfig &config, bool configValid, const char *firmware,
             int ledPin = -1, bool ledActiveLow = true);

  // Queue a received frame if it is a zone-management frame. Returns true if consumed.
  bool receive(const uint8_t *src, const uint8_t *dst, const uint8_t *data, int len);
  void poll();

  // Ensure an ESP-NOW peer exists; pinned peers are never evicted.
  bool ensurePeer(const uint8_t *mac, bool pinned = false);

  // Tag statistics and recent-event log. noteTag returns a handle for updateTag.
  uint32_t noteTag(const uint8_t *uid, uint8_t length, uint32_t cubeID, uint8_t result);
  void updateTag(uint32_t handle, uint8_t result);
  void noteSendFail() { sendFailCount_++; }
  void setError(uint8_t error) { lastError_ = error; }

  // Serial debug: "?" report, "db" records, "log" recent tags, "help". Returns true if handled.
  bool handleSerialCommand(const char *line);
  void printReport(bool ready = true);

  const ZoneConfig &config() const { return config_; }
  bool configValid() const { return configValid_; }
  bool stagingActive() const { return staging_.active; }
  uint16_t stagingReceived() const { return staging_.received; }
  uint32_t stagingVersion() const { return staging_.version; }
  uint8_t lastError() const { return lastError_; }

 private:
  struct Frame {
    uint8_t src[6];
    uint8_t broadcast;
    uint8_t length;
    uint8_t data[250];
  };
  struct Peer {
    uint8_t mac[6];
    uint32_t lastUsed;
    bool used, pinned;
  };
  struct Pending {
    bool active;
    uint8_t mac[6];
    uint8_t what;
    uint32_t nonce, dueAt;
  };
  struct Staging {
    bool active;
    uint32_t version, crc, lastActivity;
    uint16_t count, chunkCount, received;
    uint8_t perChunk;
    uint8_t *bitmap;
    Record *records;
    uint8_t announcer[6];
  };
  struct TagEvent {
    bool used;
    uint32_t handle, at, cubeID;
    uint8_t uidLength, uid[7], result;
  };

  void handle(const Frame &frame);
  void onAnnounce(const Frame &frame);
  void onChunk(const Frame &frame);
  void schedule(const uint8_t *mac, uint8_t what, uint32_t nonce);
  void sendStatus(const uint8_t *mac, uint32_t nonce);
  void sendLog(const uint8_t *mac, uint32_t nonce);
  bool send(const uint8_t *mac, const uint8_t *data, size_t length);
  void clearStaging();
  void finishStaging();

  ZoneDb *db_ = nullptr;
  ZoneConfig config_ = {};
  bool configValid_ = false;
  char firmware_[16] = {};
  int ledPin_ = -1;
  bool ledActiveLow_ = true;
  QueueHandle_t queue_ = nullptr;
  Peer peers_[MAX_PEERS] = {};
  Pending pending_[PENDING_REPLIES] = {};
  Staging staging_ = {};
  TagEvent log_[LOG_ENTRIES] = {};
  uint32_t nextHandle_ = 1;
  uint32_t tagCount_ = 0, unknownTagCount_ = 0, sendFailCount_ = 0;
  uint8_t lastError_ = ERR_NONE;
  uint32_t identifyUntil_ = 0, lastBlink_ = 0, rebootAt_ = 0;
  bool identifying_ = false, ledOn_ = false, rebootPending_ = false;
};

}  // namespace nctzone
