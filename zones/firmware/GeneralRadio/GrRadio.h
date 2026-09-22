#pragma once
// ESP-NOW for the general radio: channel 2, no encryption, broadcast peer pinned, unicast
// peers added around one send and removed again (the pairing station and the Mainshow
// controller do the same). Sends are synchronous and wait briefly for the MAC-layer result.
//
// The receive callback runs on the Wi-Fi task and only classifies and queues:
//   - zone-management frames (NctZoneProtocol::frameType) -> zoneQueue, with RSSI;
//   - the pool central's beacon and the preshow bridge's beacon/ack -> single-slot mailboxes
//     under a critical section (the newest supersedes; PreshowZone does exactly this);
//   - a neocube's SHOW_STATUS (NctShowProtocol.h, cube firmware v1.5.0+) -> showQueue, with RSSI;
//   - cube DISCOVER_REPLY / REGISTER_ACK (24-byte Packet) -> cubeQueue.
// Everything else on the air (other radios' pool states, plates' preshow events, other
// cube traffic) is dropped here. Decisions and Serial output happen in loop().
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <string.h>
#include <NctCubeProtocol.h>
#include <NctZoneProtocol.h>
#include <NctPoolProtocol.h>
#include <NctPreshowProtocol.h>
#include <NctShowProtocol.h>

namespace gr {

constexpr uint8_t CHANNEL = nctzone::ESPNOW_CHANNEL;
constexpr uint32_t SEND_WAIT_MS = 100;  // wait for the MAC-layer result of one send (Mainshow controller)
// Consecutive sends with no result at all: the radio driver has stopped calling back, the
// pairing station's "Radio completion timeout" condition. The host is told to reboot the board.
constexpr int NO_RESULT_LIMIT = 3;
constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

enum SendResult { SEND_REJECTED, SEND_DELIVERED, SEND_UNCONFIRMED, SEND_NO_RESULT, SEND_PEER_ERROR };
inline const char *const SEND_TEXT[] = {"rejected", "delivered", "unconfirmed", "no_result", "peer_error"};

struct CubeRx { Packet packet; uint8_t sender[6]; };
struct ZoneRx { uint8_t sender[6]; int8_t rssi; uint8_t length; uint8_t data[250]; };
struct ShowRx { uint8_t sender[6]; int8_t rssi; uint8_t data[sizeof(nctshow::ShowStatus)]; };

inline bool radioOk = false;
inline volatile int sendStatus = -1;  // -1 pending, else esp_now_send_status_t (set on the Wi-Fi task)
inline int noResults = 0;
inline uint32_t txSent = 0, txDelivered = 0, txUnconfirmed = 0, txNoResult = 0, txRejected = 0;
inline QueueHandle_t cubeQueue = nullptr, zoneQueue = nullptr, showQueue = nullptr;

inline portMUX_TYPE rxMux = portMUX_INITIALIZER_UNLOCKED;
inline bool poolBeaconPending = false, preshowBeaconPending = false, preshowAckPending = false;
inline uint8_t poolBeaconMac[6] = {}, preshowBeaconMac[6] = {};
inline nctzone::PoolBeacon poolBeaconFrame = {};
inline nctzone::PreshowBeacon preshowBeaconFrame = {};
inline nctzone::PreshowAck preshowAckFrame = {};

inline bool isBroadcast(const uint8_t *mac) { return memcmp(mac, BROADCAST_MAC, 6) == 0; }
inline bool isMulticast(const uint8_t *mac) { return (mac[0] & 1) != 0; }

// Runs on the Wi-Fi task: record the result, nothing else.
inline void onSent(const esp_now_send_info_t *, esp_now_send_status_t status) { sendStatus = int(status); }

inline void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  using namespace nctzone;
  if (frameType(data, len)) {
    if (!zoneQueue) return;
    ZoneRx z;
    memcpy(z.sender, info->src_addr, 6);
    z.length = uint8_t(len);
    memcpy(z.data, data, len);
    z.rssi = info->rx_ctrl ? int8_t(info->rx_ctrl->rssi) : 0;  // signal strength for the zone manager
    xQueueSend(zoneQueue, &z, 0);
    return;
  }
  if (poolFrameType(data, len) == POOL_BEACON) {
    portENTER_CRITICAL(&rxMux);
    memcpy(poolBeaconMac, info->src_addr, 6);
    memcpy(&poolBeaconFrame, data, sizeof(poolBeaconFrame));
    poolBeaconPending = true;
    portEXIT_CRITICAL(&rxMux);
    return;
  }
  uint8_t preshow = preshowFrameType(data, len);
  if (preshow == PRESHOW_BEACON) {
    portENTER_CRITICAL(&rxMux);
    memcpy(preshowBeaconMac, info->src_addr, 6);
    memcpy(&preshowBeaconFrame, data, sizeof(preshowBeaconFrame));
    preshowBeaconPending = true;
    portEXIT_CRITICAL(&rxMux);
    return;
  }
  if (preshow == PRESHOW_ACK) {
    portENTER_CRITICAL(&rxMux);
    memcpy(&preshowAckFrame, data, sizeof(preshowAckFrame));
    preshowAckPending = true;
    portEXIT_CRITICAL(&rxMux);
    return;
  }
  if (nctshow::frameType(data, len) == nctshow::SHOW_STATUS) {
    if (!showQueue) return;
    ShowRx s;
    memcpy(s.sender, info->src_addr, 6);
    memcpy(s.data, data, sizeof(s.data));
    s.rssi = info->rx_ctrl ? int8_t(info->rx_ctrl->rssi) : 0;
    xQueueSend(showQueue, &s, 0);
    return;
  }
  if (len != int(sizeof(Packet)) || (data[0] != MSG_DISCOVER_REPLY && data[0] != MSG_REGISTER_ACK) || !cubeQueue) return;
  CubeRx r;
  memcpy(&r.packet, data, sizeof(Packet));
  memcpy(r.sender, info->src_addr, 6);
  xQueueSend(cubeQueue, &r, 0);
}

// A pinned peer: stays in the table (broadcast, the latched pool central / preshow bridge).
inline bool addPeer(const uint8_t *mac) {
  if (esp_now_is_peer_exist(mac)) return true;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  return esp_now_add_peer(&peer) == ESP_OK;
}

// One frame to one address, waiting briefly for the MAC-layer result. A delivered unicast means
// the receiver's radio acknowledged the frame, not that it acted on it; a broadcast is never
// acknowledged at all. A unicast peer not already pinned is added for this send and removed.
inline SendResult sendFrame(const uint8_t *mac, const void *data, size_t length) {
  if (!radioOk) return SEND_REJECTED;
  bool temporary = !isMulticast(mac) && !esp_now_is_peer_exist(mac);
  if (!addPeer(mac)) { ++txRejected; return SEND_PEER_ERROR; }
  sendStatus = -1;
  SendResult result = SEND_REJECTED;
  if (esp_now_send(mac, (const uint8_t *)data, length) == ESP_OK) {
    uint32_t started = millis();
    while (sendStatus < 0 && uint32_t(millis() - started) < SEND_WAIT_MS) delay(1);
    int status = sendStatus;
    result = status < 0 ? SEND_NO_RESULT : status == ESP_NOW_SEND_SUCCESS ? SEND_DELIVERED : SEND_UNCONFIRMED;
  }
  if (temporary && esp_now_is_peer_exist(mac)) esp_now_del_peer(mac);
  ++txSent;
  if (result == SEND_DELIVERED) ++txDelivered;
  else if (result == SEND_UNCONFIRMED) ++txUnconfirmed;
  else if (result == SEND_REJECTED) ++txRejected;
  if (result == SEND_NO_RESULT) {
    ++txNoResult;
    if (++noResults >= NO_RESULT_LIMIT) radioOk = false;  // loop() reports `fatal` once
  } else noResults = 0;
  return result;
}

inline bool beginRadio() {
  cubeQueue = xQueueCreate(64, sizeof(CubeRx));
  zoneQueue = xQueueCreate(32, sizeof(ZoneRx));
  showQueue = xQueueCreate(64, sizeof(ShowRx));  // ~140 cubes answer a broadcast query within the jitter window
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  bool wifi = WiFi.mode(WIFI_STA) && WiFi.disconnect();
  delay(100);
  radioOk = wifi && cubeQueue && zoneQueue && showQueue && WiFi.setSleep(false) &&
            esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE) == ESP_OK && esp_now_init() == ESP_OK &&
            esp_now_register_recv_cb(onReceive) == ESP_OK && esp_now_register_send_cb(onSent) == ESP_OK;
  if (radioOk) radioOk = addPeer(BROADCAST_MAC);
  return radioOk;
}

}  // namespace gr
