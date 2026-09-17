#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_arduino_version.h>

// =====================================================
// NCT IMMERSIVE DEEP
// PRESHOW MEDIA BRIDGE
//
// Tag Plate
//    ↓ ESP-NOW Channel 2 (shared with neocubes, zones and the registry station)
// Bridge ESP32
//    ↓ USB Serial 115200
// TouchDesigner Serial DAT
// =====================================================

#define ESPNOW_CHANNEL 2


// =====================================================
// 태그플레이트와 반드시 동일
// =====================================================

struct PreshowMediaPacket {

  uint8_t pointID;   // 1 ~ 4
  uint8_t state;     // 1 = ON / 0 = OFF

};


// =====================================================
// 패킷 처리
// =====================================================

void handleMediaPacket(
  const uint8_t *data,
  int len
) {

  if (
    len != sizeof(PreshowMediaPacket)
  ) {
    return;
  }


  PreshowMediaPacket packet;


  memcpy(
    &packet,
    data,
    sizeof(packet)
  );


  if (
    packet.pointID < 1 ||
    packet.pointID > 4
  ) {
    return;
  }


  if (
    packet.state > 1
  ) {
    return;
  }


  // ===================================================
  // TouchDesigner Serial DAT용 출력
  //
  // PRESHOW,1,ON
  // PRESHOW,1,OFF
  // ===================================================

  Serial.print("PRESHOW,");
  Serial.print(packet.pointID);
  Serial.print(",");


  if (
    packet.state == 1
  ) {

    Serial.println("ON");

  } else {

    Serial.println("OFF");
  }
}


// =====================================================
// ESP32 Arduino Core 3.x
// =====================================================

#if ESP_ARDUINO_VERSION_MAJOR >= 3

void onDataRecv(
  const esp_now_recv_info_t *info,
  const uint8_t *data,
  int len
) {

  handleMediaPacket(
    data,
    len
  );
}

#else

// =====================================================
// ESP32 Arduino Core 2.x
// =====================================================

void onDataRecv(
  const uint8_t *mac,
  const uint8_t *data,
  int len
) {

  handleMediaPacket(
    data,
    len
  );
}

#endif


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(500);


  Serial.println();
  Serial.println("==============================");
  Serial.println("NCT PRESHOW MEDIA BRIDGE");
  Serial.println("ESP-NOW CH1 -> SERIAL DAT");
  Serial.println("==============================");


  // ===================================================
  // Wi-Fi Radio
  // ===================================================

  WiFi.mode(WIFI_STA);

  delay(100);


  // ===================================================
  // ESP-NOW Channel 2 강제
  // ===================================================

  esp_err_t channelResult =
    esp_wifi_set_channel(
      ESPNOW_CHANNEL,
      WIFI_SECOND_CHAN_NONE
    );


  if (
    channelResult == ESP_OK
  ) {

    Serial.println("CHANNEL SET -> 1");

  } else {

    Serial.print("CHANNEL SET ERROR: ");
    Serial.println(channelResult);
  }


  // ===================================================
  // MAC 출력
  // ===================================================

  Serial.print("BRIDGE MAC: ");
  Serial.println(WiFi.macAddress());


  // ===================================================
  // ESP-NOW
  // ===================================================

  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println("ESP-NOW INIT ERROR");

    while (true) {
      delay(100);
    }
  }


  esp_now_register_recv_cb(
    onDataRecv
  );


  Serial.println("BRIDGE READY");
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  delay(10);
}