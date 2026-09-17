/*
=========================================================
 NCT IMMERSIVE DEEP
 NEocore Cube Firmware

 Version : v1.3.1
 Date    : 2026-09-15

 Hardware:
 - Seeed Studio XIAO ESP32-C3
 - WS2812 8 LED Ring
 - LED DATA = D10
 - 732530 500mAh LiPo

 v1.3.1 변경사항:
 - 최초/대기 색상 → 은은한 흰색 RGB(3,3,3)
 - 메인쇼존 네온색 → RGB(18,20,1)
 - 기존 ESP-NOW / 등록 / OTA / Zone 구조 변경 없음

 ★ 현장 기준 성공 구조 유지
=========================================================
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoOTA.h>


// =====================================================
// LED
// ★ 실제 제작 큐브 성공 핀
// =====================================================

#define LED_PIN D10
#define NUM_LEDS 8

Adafruit_NeoPixel pixels(
  NUM_LEDS,
  LED_PIN,
  NEO_GRB + NEO_KHZ800
);


// =====================================================
// NVS
// =====================================================

Preferences prefs;


// =====================================================
// OTA Wi-Fi
// =====================================================

const char* OTA_SSID = "CONFIGURE_LOCALLY";
const char* OTA_PASSWORD = "CONFIGURE_LOCALLY";


// =====================================================
// 메시지 종류
// ★ 기존 성공 구조 유지
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6
};


// =====================================================
// Zone
// =====================================================

enum ZoneType : uint8_t {

  ZONE_IDLE     = 0,
  ZONE_PRESHOW  = 1,
  ZONE_DESERT   = 2,
  ZONE_POOL     = 3,
  ZONE_MAINSHOW = 4
};


// =====================================================
// ESP-NOW Packet
// ★ Core2 / 태깅플레이트와 동일
// =====================================================

struct Packet {

  uint8_t type;

  uint32_t cubeID;

  uint8_t mac[6];

  uint8_t uidLength;

  uint8_t uid[7];

  uint8_t success;
};


Packet pendingPacket;

uint8_t senderMac[6];

volatile bool packetReady = false;


// =====================================================
// Cube 등록정보
// =====================================================

uint32_t myCubeID = 0;

uint8_t myUid[7];

uint8_t myUidLength = 0;

bool isRegistered = false;


// =====================================================
// 현재 Zone
// =====================================================

uint8_t currentZone = ZONE_IDLE;


// =====================================================
// OTA
// =====================================================

bool otaMode = false;


// =====================================================
// LED 색상
// =====================================================


// -----------------------------------------------------
// 최초 배부 / 대기
// 은은한 흰색
// -----------------------------------------------------

#define IDLE_R 3
#define IDLE_G 3
#define IDLE_B 3


// -----------------------------------------------------
// 프리쇼
// 빨강
// -----------------------------------------------------

#define PRESHOW_R 20
#define PRESHOW_G 0
#define PRESHOW_B 0


// -----------------------------------------------------
// 사막존
// 노랑
// -----------------------------------------------------

#define DESERT_R 20
#define DESERT_G 12
#define DESERT_B 0


// -----------------------------------------------------
// 풀존
// 파랑
// -----------------------------------------------------

#define POOL_R 0
#define POOL_G 2
#define POOL_B 20


// -----------------------------------------------------
// 메인쇼존
// ★ 실제 테스트한 네온색
// -----------------------------------------------------

#define MAINSHOW_R 18
#define MAINSHOW_G 20
#define MAINSHOW_B 1


// =====================================================
// LED 전체 색상
// =====================================================

void showColor(
  uint8_t r,
  uint8_t g,
  uint8_t b
) {

  for (int i = 0; i < NUM_LEDS; i++) {

    pixels.setPixelColor(
      i,
      pixels.Color(r, g, b)
    );
  }

  pixels.show();
}


// =====================================================
// LED OFF
// =====================================================

void ledOff() {

  pixels.clear();
  pixels.show();
}


// =====================================================
// 대기색
// =====================================================

void showIdleColor() {

  showColor(
    IDLE_R,
    IDLE_G,
    IDLE_B
  );
}


// =====================================================
// Zone → LED
// ★ 색상은 Cube 내부에서 관리
// =====================================================

void setZoneColor(uint8_t zone) {

  switch (zone) {

    case ZONE_IDLE:

      currentZone = zone;

      showColor(
        IDLE_R,
        IDLE_G,
        IDLE_B
      );

      break;


    case ZONE_PRESHOW:

      currentZone = zone;

      showColor(
        PRESHOW_R,
        PRESHOW_G,
        PRESHOW_B
      );

      break;


    case ZONE_DESERT:

      currentZone = zone;

      showColor(
        DESERT_R,
        DESERT_G,
        DESERT_B
      );

      break;


    case ZONE_POOL:

      currentZone = zone;

      showColor(
        POOL_R,
        POOL_G,
        POOL_B
      );

      break;


    case ZONE_MAINSHOW:

      currentZone = zone;

      showColor(
        MAINSHOW_R,
        MAINSHOW_G,
        MAINSHOW_B
      );

      break;


    default:

      Serial.print("UNKNOWN ZONE: ");
      Serial.println(zone);

      break;
  }
}


// =====================================================
// 등록 성공 표시
// =====================================================

void successBlink() {

  for (int i = 0; i < 2; i++) {

    showColor(0, 12, 0);

    delay(150);

    ledOff();

    delay(150);
  }

  showIdleColor();
}


// =====================================================
// 오류 표시
// =====================================================

void showError() {

  showColor(15, 0, 0);
}


// =====================================================
// OTA 표시
// =====================================================

void showOtaColor() {

  showColor(0, 0, 12);
}


// =====================================================
// 저장된 등록정보 읽기
// =====================================================

void loadRegistration() {

  prefs.begin(
    "cube",
    true
  );


  myCubeID =
    prefs.getUInt(
      "cubeID",
      0
    );


  myUidLength =
    prefs.getUChar(
      "uidLen",
      0
    );


  if (
    myUidLength > 0 &&
    myUidLength <= 7
  ) {

    prefs.getBytes(
      "uid",
      myUid,
      myUidLength
    );
  }


  prefs.end();


  isRegistered =
    (
      myCubeID > 0 &&
      myUidLength > 0
    );
}


// =====================================================
// Peer 추가
// =====================================================

void addPeer(
  const uint8_t *mac
) {

  if (
    esp_now_is_peer_exist(mac)
  ) {

    return;
  }


  esp_now_peer_info_t peer = {};


  memcpy(
    peer.peer_addr,
    mac,
    6
  );


  peer.channel = 0;

  peer.encrypt = false;


  esp_now_add_peer(
    &peer
  );
}


// =====================================================
// Discover Reply
// =====================================================

void sendDiscoverReply(
  const uint8_t *destination
) {

  addPeer(
    destination
  );


  Packet reply = {};


  reply.type =
    MSG_DISCOVER_REPLY;


  WiFi.macAddress(
    reply.mac
  );


  esp_now_send(
    destination,
    (uint8_t *)&reply,
    sizeof(reply)
  );
}


// =====================================================
// Register ACK
// =====================================================

void sendRegisterAck(
  const uint8_t *destination,
  uint32_t cubeID
) {

  addPeer(
    destination
  );


  Packet reply = {};


  reply.type =
    MSG_REGISTER_ACK;


  reply.cubeID =
    cubeID;


  reply.success = 1;


  WiFi.macAddress(
    reply.mac
  );


  esp_now_send(
    destination,
    (uint8_t *)&reply,
    sizeof(reply)
  );
}


// =====================================================
// 등록정보 저장
// =====================================================

void saveRegistration(
  const Packet &p
) {

  if (
    p.uidLength == 0 ||
    p.uidLength > 7
  ) {

    return;
  }


  prefs.begin(
    "cube",
    false
  );


  prefs.putUInt(
    "cubeID",
    p.cubeID
  );


  prefs.putUChar(
    "uidLen",
    p.uidLength
  );


  prefs.putBytes(
    "uid",
    p.uid,
    p.uidLength
  );


  prefs.end();


  myCubeID =
    p.cubeID;


  myUidLength =
    p.uidLength;


  memcpy(
    myUid,
    p.uid,
    myUidLength
  );


  isRegistered = true;


  Serial.print(
    "REGISTERED Cube #"
  );


  Serial.println(
    myCubeID
  );
}


// =====================================================
// OTA
// =====================================================

void enterOtaMode() {

  if (otaMode) {

    return;
  }


  otaMode = true;


  showOtaColor();


  esp_now_deinit();


  delay(100);


  WiFi.mode(
    WIFI_STA
  );


  WiFi.begin(
    OTA_SSID,
    OTA_PASSWORD
  );


  unsigned long start =
    millis();


  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - start < 15000
  ) {

    delay(300);
  }


  if (
    WiFi.status() != WL_CONNECTED
  ) {

    showError();

    delay(2000);

    ESP.restart();
  }


  char hostname[32];


  if (myCubeID > 0) {

    snprintf(
      hostname,
      sizeof(hostname),
      "NCT-CUBE-%03lu",
      (unsigned long)myCubeID
    );

  } else {

    snprintf(
      hostname,
      sizeof(hostname),
      "NCT-CUBE-UNREGISTERED"
    );
  }


  ArduinoOTA.setHostname(
    hostname
  );


  ArduinoOTA.onStart([]() {

    showColor(
      0,
      10,
      20
    );
  });


  ArduinoOTA.onEnd([]() {

    showColor(
      0,
      20,
      0
    );
  });


  ArduinoOTA.onError(
    [](ota_error_t error) {

      showError();
    }
  );


  ArduinoOTA.begin();


  Serial.print(
    "OTA READY: "
  );


  Serial.println(
    hostname
  );
}


// =====================================================
// ESP-NOW 수신
// =====================================================

void onDataRecv(
  const esp_now_recv_info_t *info,
  const uint8_t *data,
  int len
) {

  if (
    len != sizeof(Packet)
  ) {

    return;
  }


  memcpy(
    &pendingPacket,
    data,
    sizeof(Packet)
  );


  memcpy(
    senderMac,
    info->src_addr,
    6
  );


  packetReady = true;
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(300);


  // LED
  pixels.begin();

  ledOff();


  // Wi-Fi
  WiFi.mode(
    WIFI_STA
  );


  delay(100);


  Serial.print(
    "Cube MAC: "
  );


  Serial.println(
    WiFi.macAddress()
  );


  // 등록정보
  loadRegistration();


  if (isRegistered) {

    Serial.print(
      "Cube ID: "
    );

    Serial.println(
      myCubeID
    );

  } else {

    Serial.println(
      "UNREGISTERED"
    );
  }


  // ESP-NOW
  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT ERROR"
    );

    showError();

    return;
  }


  esp_now_register_recv_cb(
    onDataRecv
  );


  // 최초 배부 상태
  currentZone =
    ZONE_IDLE;


  showIdleColor();


  Serial.println(
    "Cube READY"
  );
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  // OTA
  if (otaMode) {

    ArduinoOTA.handle();

    delay(2);

    return;
  }


  // ESP-NOW 패킷 없음
  if (!packetReady) {

    delay(2);

    return;
  }


  packetReady = false;


  // DISCOVER
  if (
    pendingPacket.type ==
    MSG_DISCOVER
  ) {

    sendDiscoverReply(
      senderMac
    );

    return;
  }


  // REGISTER
  if (
    pendingPacket.type ==
    MSG_REGISTER
  ) {

    saveRegistration(
      pendingPacket
    );


    sendRegisterAck(
      senderMac,
      pendingPacket.cubeID
    );


    successBlink();

    return;
  }


  // OTA
  if (
    pendingPacket.type ==
    MSG_ENTER_OTA
  ) {

    enterOtaMode();

    return;
  }


  // ZONE
  if (
    pendingPacket.type ==
    MSG_SET_ZONE
  ) {

    uint8_t zone =
      pendingPacket.success;


    Serial.print(
      "ZONE = "
    );


    Serial.println(
      zone
    );


    setZoneColor(
      zone
    );

    return;
  }
}