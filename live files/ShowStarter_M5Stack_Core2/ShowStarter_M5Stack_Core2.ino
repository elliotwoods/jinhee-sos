/*
  ============================================================
  NCT IMMERSIVE DEEP
  M5Stack Core2 MAIN SHOW CONTROLLER

  Version : v1.0.2-RANDOM-SHOWID
  Date    : 2026-09-17

  변경점
  - 매 LIGHTING SHOW 실행마다 랜덤 32bit showId 생성
  - 같은 showId를 5회 / 30ms 간격 Broadcast
  - Core2 재부팅 후에도 이전 showId와 충돌 가능성 극소화
  - TP-Link_E9E4 접속 -> 현재 ESP-NOW 채널 자동 일치
  - 현재 채널 / MAC / showId Serial 출력
  - 1초 HOLD 후 SHOW START
  - 큐브의 Zone을 강제로 바꾸지 않음

  Cube Firmware 대상:
  - v1.4.0-MAINSHOW-TEST
  - MSG_SHOW_START = 7
  - Packet.cubeID = showId
  ============================================================
*/

#include <M5Unified.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_system.h>


// ============================================================
// DEVICE
// ============================================================

#define DEVICE_NAME "NCT MAIN SHOW CONTROLLER"
#define FW_VERSION  "v1.0.2-RANDOM-SHOWID"


// ============================================================
// WIFI
// ============================================================

const char* WIFI_SSID =
  "CONFIGURE_LOCALLY";

const char* WIFI_PASSWORD =
  "CONFIGURE_LOCALLY";


// ============================================================
// MESSAGE TYPE
// Cube v1.4.0과 동일
// ============================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6,

  MSG_SHOW_START     = 7
};


// ============================================================
// PACKET
// Cube v1.4.0과 동일
// ============================================================

struct Packet {

  uint8_t type;

  uint32_t cubeID;

  uint8_t mac[6];

  uint8_t uidLength;

  uint8_t uid[7];

  uint8_t success;
};


// ============================================================
// BROADCAST
// ============================================================

uint8_t broadcastMac[6] = {

  0xFF, 0xFF, 0xFF,
  0xFF, 0xFF, 0xFF

};


// ============================================================
// TOUCH
// ============================================================

bool holding = false;

unsigned long holdStartMillis = 0;

const unsigned long HOLD_TIME_MS =
  1000;


// ============================================================
// SHOW
// ============================================================

uint32_t currentShowId = 0;

unsigned long lastShowTrigger = 0;

const unsigned long SHOW_LOCK_MS =
  3000;


// ============================================================
// UI
// ============================================================

void drawReadyScreen() {

  M5.Display.fillScreen(
    TFT_BLACK
  );


  M5.Display.setTextDatum(
    top_center
  );


  M5.Display.setTextColor(
    TFT_WHITE
  );


  M5.Display.setTextSize(
    2
  );


  M5.Display.drawString(
    "NCT MAIN SHOW",
    M5.Display.width() / 2,
    15
  );


  M5.Display.setTextSize(
    1
  );


  M5.Display.drawString(
    FW_VERSION,
    M5.Display.width() / 2,
    48
  );


  M5.Display.drawString(
    "WiFi / ESP-NOW CH : " +
    String(WiFi.channel()),
    M5.Display.width() / 2,
    70
  );


  // ----------------------------------------------------------
  // BUTTON
  // ----------------------------------------------------------

  M5.Display.drawRoundRect(
    20,
    95,
    M5.Display.width() - 40,
    100,
    12,
    TFT_WHITE
  );


  M5.Display.setTextSize(
    2
  );


  M5.Display.drawString(
    "LIGHTING SHOW",
    M5.Display.width() / 2,
    120
  );


  M5.Display.setTextSize(
    1
  );


  M5.Display.drawString(
    "HOLD 1 SECOND",
    M5.Display.width() / 2,
    160
  );


  M5.Display.drawString(
    "READY",
    M5.Display.width() / 2,
    215
  );
}


// ============================================================
// HOLD DISPLAY
// ============================================================

void drawHoldProgress(
  unsigned long elapsed
) {

  int percent =
    constrain(
      (elapsed * 100)
      / HOLD_TIME_MS,
      0,
      100
    );


  M5.Display.fillRect(
    40,
    205,
    M5.Display.width() - 80,
    25,
    TFT_BLACK
  );


  M5.Display.setTextDatum(
    top_center
  );


  M5.Display.setTextColor(
    TFT_YELLOW
  );


  M5.Display.drawString(
    "HOLD " +
    String(percent) +
    "%",
    M5.Display.width() / 2,
    210
  );
}


// ============================================================
// SHOW DISPLAY
// ============================================================

void drawShowStartScreen() {

  M5.Display.fillScreen(
    TFT_BLACK
  );


  M5.Display.setTextDatum(
    middle_center
  );


  M5.Display.setTextColor(
    TFT_YELLOW
  );


  M5.Display.setTextSize(
    2
  );


  M5.Display.drawString(
    "SHOW START",
    M5.Display.width() / 2,
    90
  );


  M5.Display.setTextColor(
    TFT_WHITE
  );


  M5.Display.setTextSize(
    1
  );


  M5.Display.drawString(
    "SHOW ID",
    M5.Display.width() / 2,
    130
  );


  M5.Display.drawString(
    String(currentShowId),
    M5.Display.width() / 2,
    150
  );


  M5.Display.drawString(
    "CH " +
    String(WiFi.channel()),
    M5.Display.width() / 2,
    180
  );
}


// ============================================================
// WIFI CONNECT
// ============================================================

void connectWiFi() {

  WiFi.mode(
    WIFI_STA
  );


  WiFi.setSleep(
    false
  );


  Serial.println();

  Serial.print(
    "WiFi connecting"
  );


  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );


  unsigned long start =
    millis();


  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - start < 15000
  ) {

    Serial.print(".");

    delay(
      250
    );
  }


  Serial.println();


  if (
    WiFi.status() != WL_CONNECTED
  ) {

    Serial.println(
      "WIFI FAILED"
    );


    M5.Display.fillScreen(
      TFT_RED
    );


    M5.Display.setTextColor(
      TFT_WHITE
    );


    M5.Display.setTextDatum(
      middle_center
    );


    M5.Display.drawString(
      "WIFI FAILED",
      M5.Display.width() / 2,
      M5.Display.height() / 2
    );


    while (true) {

      delay(
        100
      );
    }
  }


  Serial.println(
    "WiFi connected"
  );


  Serial.print(
    "CHANNEL: "
  );

  Serial.println(
    WiFi.channel()
  );


  Serial.print(
    "Core2 MAC: "
  );

  Serial.println(
    WiFi.macAddress()
  );
}


// ============================================================
// ADD BROADCAST PEER
// ============================================================

bool addBroadcastPeer() {

  if (
    esp_now_is_peer_exist(
      broadcastMac
    )
  ) {

    return true;
  }


  esp_now_peer_info_t peer = {};


  memcpy(
    peer.peer_addr,
    broadcastMac,
    6
  );


  // 공유기 채널과 동일
  peer.channel =
    WiFi.channel();


  peer.encrypt =
    false;


  esp_err_t result =
    esp_now_add_peer(
      &peer
    );


  if (
    result != ESP_OK
  ) {

    Serial.print(
      "BROADCAST PEER ERROR: "
    );

    Serial.println(
      result
    );

    return false;
  }


  return true;
}


// ============================================================
// RANDOM SHOW ID
// ============================================================

uint32_t makeNewShowId() {

  uint32_t id =
    esp_random();


  // 0은 사용하지 않음
  if (
    id == 0
  ) {

    id =
      1;
  }


  // 혹시 바로 직전과 같으면 다시 생성
  while (
    id == currentShowId
  ) {

    id =
      esp_random();


    if (
      id == 0
    ) {

      id =
        1;
    }
  }


  return id;
}


// ============================================================
// SEND SHOW START
// ============================================================

void sendShowStart() {

  currentShowId =
    makeNewShowId();


  Packet packet = {};


  packet.type =
    MSG_SHOW_START;


  // Cube v1.4.0 구조
  // cubeID 필드가 showId
  packet.cubeID =
    currentShowId;


  Serial.println();
  Serial.println(
    "================================"
  );

  Serial.println(
    "SHOW START"
  );


  Serial.print(
    "SHOW ID: "
  );

  Serial.println(
    currentShowId
  );


  Serial.print(
    "CHANNEL: "
  );

  Serial.println(
    WiFi.channel()
  );


  Serial.println(
    "================================"
  );


  // ----------------------------------------------------------
  // 동일 SHOW ID 5회 반복
  // 첫 패킷 = 시작
  // 나머지는 Cube가 중복 무시
  // ----------------------------------------------------------

  for (
    int i = 0;
    i < 5;
    i++
  ) {

    esp_err_t result =
      esp_now_send(
        broadcastMac,
        (uint8_t*)&packet,
        sizeof(packet)
      );


    Serial.print(
      "SHOW_START "
    );


    Serial.print(
      i + 1
    );


    Serial.print(
      "/5 : "
    );


    if (
      result == ESP_OK
    ) {

      Serial.println(
        "QUEUED"
      );

    } else {

      Serial.print(
        "ERROR "
      );

      Serial.println(
        result
      );
    }


    delay(
      30
    );
  }
}


// ============================================================
// START SHOW
// ============================================================

void startLightingShow() {

  unsigned long now =
    millis();


  if (
    lastShowTrigger != 0 &&
    now - lastShowTrigger <
      SHOW_LOCK_MS
  ) {

    Serial.println(
      "SHOW BUTTON LOCKED"
    );

    return;
  }


  lastShowTrigger =
    now;


  sendShowStart();


  drawShowStartScreen();


  delay(
    1200
  );


  drawReadyScreen();
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  auto cfg =
    M5.config();


  M5.begin(
    cfg
  );


  Serial.begin(
    115200
  );


  delay(
    500
  );


  M5.Display.setRotation(
    1
  );


  M5.Display.fillScreen(
    TFT_BLACK
  );


  Serial.println();
  Serial.println(
    "================================"
  );

  Serial.println(
    DEVICE_NAME
  );

  Serial.println(
    FW_VERSION
  );

  Serial.println(
    "================================"
  );


  M5.Display.setTextDatum(
    top_left
  );


  M5.Display.setTextColor(
    TFT_WHITE
  );


  M5.Display.drawString(
    DEVICE_NAME,
    10,
    20
  );


  M5.Display.drawString(
    FW_VERSION,
    10,
    50
  );


  M5.Display.drawString(
    "WiFi connecting...",
    10,
    100
  );


  // ==========================================================
  // WIFI
  // ==========================================================

  connectWiFi();


  // ==========================================================
  // ESP-NOW
  // ==========================================================

  if (
    esp_now_init()
      != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT FAILED"
    );


    while (
      true
    ) {

      delay(
        100
      );
    }
  }


  if (
    !addBroadcastPeer()
  ) {

    Serial.println(
      "BROADCAST PEER FAILED"
    );


    while (
      true
    ) {

      delay(
        100
      );
    }
  }


  Serial.println(
    "ESP-NOW READY"
  );


  Serial.print(
    "ESP-NOW CHANNEL: "
  );

  Serial.println(
    WiFi.channel()
  );


  Serial.println(
    "READY"
  );


  drawReadyScreen();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  M5.update();


  auto touch =
    M5.Touch.getDetail();


  bool insideButton =

    touch.x >= 20 &&

    touch.x <=
      M5.Display.width() - 20 &&

    touch.y >= 95 &&

    touch.y <= 195;


  // ==========================================================
  // HOLD
  // ==========================================================

  if (
    touch.isPressed() &&
    insideButton
  ) {

    if (
      !holding
    ) {

      holding =
        true;


      holdStartMillis =
        millis();


      Serial.println(
        "BUTTON HOLD START"
      );
    }


    unsigned long elapsed =
      millis() -
      holdStartMillis;


    drawHoldProgress(
      elapsed
    );


    if (
      elapsed >=
      HOLD_TIME_MS
    ) {

      holding =
        false;


      startLightingShow();


      // 손가락을 떼기 전까지
      // 다시 시작하지 않음

      while (
        M5.Touch.getCount() > 0
      ) {

        M5.update();

        delay(
          20
        );
      }
    }

  } else {

    if (
      holding
    ) {

      holding =
        false;


      Serial.println(
        "BUTTON HOLD CANCEL"
      );


      drawReadyScreen();
    }
  }


  delay(
    10
  );
}