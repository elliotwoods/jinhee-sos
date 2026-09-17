/*
=========================================================
 NCT IMMERSIVE DEEP
 Neocore Cube Firmware

 Version : v1.4.1-STABLE-TEST
 Date    : 2026-09-17

 Base:
 - v1.4.0-MAINSHOW-TEST

 이번 변경사항 (필수 수정만):
 - 공통 프로토콜 충돌 수정: MSG_TAG_STATE=7, MSG_SHOW_START=8
 - OTA Wi-Fi 연결/채널 확정 후 ESP-NOW 초기화
 - Wi-Fi 연결 실패 시 현장 고정 채널 2로 ESP-NOW 계속 동작
 - MAINSHOW 입장 상태인 Cube만 SHOW_START 실행
 - 메인쇼 타임라인 종료 후 MAINSHOW 자격 해제 (다음 회차 오동작 방지)
 - 부팅 로그에 FW / Cube ID / MAC / Wi-Fi Channel 명확히 출력

 변경하지 않은 것:
 - NVS 등록정보 구조
 - Zone 색상값
 - LED 최대 출력 100/255
 - 메인쇼 00:00~04:58 타임라인
 - OTA SSID / Password / Hostname 규칙
 - DISCOVER / REGISTER 구조

 Hardware:
 - Seeed Studio XIAO ESP32-C3
 - WS2812 8 LED Ring
 - LED DATA = D10
 - 732530 500mAh LiPo

 ★ 현재 메인쇼 테스트 버전
 ★ 실제 큐시트 2026.09.16 / 영상 타임라인 0913 기준
=========================================================
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoOTA.h>
#include <esp_system.h>
#include <esp_wifi.h>


// =====================================================
// LED
// =====================================================

#define LED_PIN D10
#define NUM_LEDS 8

Adafruit_NeoPixel pixels(
  NUM_LEDS,
  LED_PIN,
  NEO_GRB + NEO_KHZ800
);


// =====================================================
// ★ LED 절대 상한
//
// 255가 WS2812 물리 최대
// 우리는 최대 100까지만 사용
// 약 39% 수준
// =====================================================

#define LED_MAX_LEVEL 100


// =====================================================
// MAIN SHOW FRAME RATE
// 약 50fps
// =====================================================

#define SHOW_FRAME_INTERVAL_MS 20


// =====================================================
// NVS
// =====================================================

Preferences prefs;


// =====================================================
// OTA Wi-Fi
// =====================================================

const char* OTA_SSID =
  "CONFIGURE_LOCALLY";

const char* OTA_PASSWORD =
  "CONFIGURE_LOCALLY";

const char* OTA_UPLOAD_PASSWORD =
  "CONFIGURE_LOCALLY";


// =====================================================
// 메시지 종류
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6,

  // 공통 프로토콜 고정
  MSG_TAG_STATE      = 7,
  MSG_SHOW_START     = 8
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
//
// ★ Packet 구조는 v1.4.0과 동일
//
// MSG_SHOW_START일 때:
// cubeID = showId
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

uint8_t currentZone =
  ZONE_IDLE;


// =====================================================
// OTA
// =====================================================

bool otaReady = false;


// =====================================================
// MAIN SHOW 상태
// =====================================================

bool showRunning = false;

uint32_t showStartMillis = 0;

uint32_t lastShowId = 0;

uint32_t lastShowFrameMillis = 0;


// =====================================================
// 랜덤 네온 구간 상태
// =====================================================

bool randomEffectInitialized = false;

uint8_t randomLevelFrom = 20;
uint8_t randomLevelTo   = 20;

uint32_t randomTransitionStart = 0;
uint32_t randomTransitionDuration = 1000;


// =====================================================
// LED COLORS
// =====================================================

// 최초 / 대기

#define IDLE_R 3
#define IDLE_G 3
#define IDLE_B 3


// 프리쇼

#define PRESHOW_R 20
#define PRESHOW_G 0
#define PRESHOW_B 0


// 사막 Zone 기본색

#define DESERT_R 20
#define DESERT_G 12
#define DESERT_B 0


// 풀 Zone 기본색

#define POOL_R 0
#define POOL_G 2
#define POOL_B 20


// 메인쇼 기본 네온

#define MAINSHOW_R 18
#define MAINSHOW_G 20
#define MAINSHOW_B 1


// =====================================================
// MAIN SHOW 색
// =====================================================

// 일반 흰색

#define SHOW_WHITE_R 20
#define SHOW_WHITE_G 20
#define SHOW_WHITE_B 20


// 밝은 흰색
// ★ 절대 최대 100

#define SHOW_WHITE_MAX_R 100
#define SHOW_WHITE_MAX_G 100
#define SHOW_WHITE_MAX_B 100


// 네온 최대
// #CFFF3B 비율을 낮춘 색

#define SHOW_NEON_MAX_R 81
#define SHOW_NEON_MAX_G 100
#define SHOW_NEON_MAX_B 23


// 결정 3색

#define CRYSTAL_GRAY_R 17
#define CRYSTAL_GRAY_G 17
#define CRYSTAL_GRAY_B 18

#define CRYSTAL_BLUE_R 11
#define CRYSTAL_BLUE_G 16
#define CRYSTAL_BLUE_B 18

#define CRYSTAL_RED_R 18
#define CRYSTAL_RED_G 12
#define CRYSTAL_RED_B 12


// 사막 #DBAB82 계열

#define SHOW_DESERT_R 24
#define SHOW_DESERT_G 18
#define SHOW_DESERT_B 13


// 물 / 풀

#define SHOW_POOL_R 0
#define SHOW_POOL_G 8
#define SHOW_POOL_B 30


// =====================================================
// LED 안전 출력
// =====================================================

uint8_t limitLed(uint16_t value) {

  if (value > LED_MAX_LEVEL) {

    return LED_MAX_LEVEL;
  }

  return (uint8_t)value;
}


// =====================================================
// LED 전체 색상
// =====================================================

void showColor(
  uint8_t r,
  uint8_t g,
  uint8_t b
) {

  r = limitLed(r);
  g = limitLed(g);
  b = limitLed(b);

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
// 기본 대기색
// =====================================================

void showIdleColor() {

  showColor(
    IDLE_R,
    IDLE_G,
    IDLE_B
  );
}


// =====================================================
// 정수형 색상 보간
// =====================================================

uint8_t lerp8(
  uint8_t from,
  uint8_t to,
  uint32_t elapsed,
  uint32_t duration
) {

  if (elapsed >= duration) {

    return to;
  }

  int32_t diff =
    (int32_t)to -
    (int32_t)from;

  return
    from +
    (
      diff *
      (int32_t)elapsed /
      (int32_t)duration
    );
}


// =====================================================
// Fade
// =====================================================

void showFade(
  uint8_t r1,
  uint8_t g1,
  uint8_t b1,

  uint8_t r2,
  uint8_t g2,
  uint8_t b2,

  uint32_t elapsed,
  uint32_t duration
) {

  showColor(

    lerp8(
      r1,
      r2,
      elapsed,
      duration
    ),

    lerp8(
      g1,
      g2,
      elapsed,
      duration
    ),

    lerp8(
      b1,
      b2,
      elapsed,
      duration
    )
  );
}


// =====================================================
// 네온 밝기 레벨
//
// level = Green channel 기준
// 색 비율 유지
// =====================================================

void showNeonLevel(
  uint8_t level
) {

  if (level > LED_MAX_LEVEL) {

    level = LED_MAX_LEVEL;
  }

  uint8_t r =
    (uint16_t)level * 81 / 100;

  uint8_t g =
    level;

  uint8_t b =
    (uint16_t)level * 23 / 100;

  showColor(
    r,
    g,
    b
  );
}


// =====================================================
// Zone → LED
// =====================================================

void setZoneColor(
  uint8_t zone
) {

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

      Serial.print(
        "UNKNOWN ZONE: "
      );

      Serial.println(zone);

      break;
  }
}


// =====================================================
// 등록 성공 표시
// =====================================================

void successBlink() {

  for (int i = 0; i < 2; i++) {

    showColor(
      0,
      12,
      0
    );

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

  showColor(
    15,
    0,
    0
  );
}


// =====================================================
// 등록정보 읽기
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

  addPeer(destination);

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

  addPeer(destination);

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

void startTemporaryOTA() {

  Serial.println();

  Serial.println(
    "TEMP OTA: WIFI CONNECTING..."
  );

  WiFi.begin(
    OTA_SSID,
    OTA_PASSWORD
  );

  unsigned long startTime =
    millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - startTime < 10000
  ) {

    delay(200);
  }


  if (
    WiFi.status() != WL_CONNECTED
  ) {

    Serial.println(
      "TEMP OTA: WIFI FAILED"
    );

    Serial.println(
      "NORMAL CUBE MODE CONTINUES"
    );

    otaReady = false;

    return;
  }


  char hostname[32];

  if (
    myCubeID > 0
  ) {

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
      "NCT-CUBE-TEST"
    );
  }


  ArduinoOTA.setHostname(
    hostname
  );

  ArduinoOTA.setPassword(
    OTA_UPLOAD_PASSWORD
  );


  ArduinoOTA.onStart(
    []() {

      Serial.println(
        "OTA UPDATE START"
      );

      showColor(
        0,
        0,
        15
      );
    }
  );


  ArduinoOTA.onEnd(
    []() {

      Serial.println(
        "OTA UPDATE COMPLETE"
      );

      showColor(
        0,
        15,
        0
      );
    }
  );


  ArduinoOTA.onError(
    [](ota_error_t error) {

      Serial.print(
        "OTA ERROR: "
      );

      Serial.println(
        error
      );

      showError();
    }
  );


  ArduinoOTA.begin();

  otaReady = true;


  Serial.println();

  Serial.println(
    "=========================="
  );

  Serial.print(
    "TEMP OTA READY: "
  );

  Serial.println(
    hostname
  );

  Serial.print(
    "IP: "
  );

  Serial.println(
    WiFi.localIP()
  );

  Serial.println(
    "OTA PASSWORD ENABLED"
  );

  Serial.println(
    "=========================="
  );
}


// =====================================================
// ★ MAIN SHOW 시작
// =====================================================

void startMainShow(
  uint32_t showId
) {

  // 동일한 SHOW_START 반복 패킷 무시

  if (
    showId == lastShowId
  ) {

    Serial.println(
      "SHOW_START DUPLICATE - IGNORED"
    );

    return;
  }


  lastShowId =
    showId;

  showRunning =
    true;

  showStartMillis =
    millis();

  lastShowFrameMillis =
    0;

  randomEffectInitialized =
    false;

  currentZone =
    ZONE_MAINSHOW;


  // 영상 시작 시 최초 네온색

  showColor(
    MAINSHOW_R,
    MAINSHOW_G,
    MAINSHOW_B
  );


  Serial.println();

  Serial.println(
    "=========================="
  );

  Serial.print(
    "MAIN SHOW START / ID = "
  );

  Serial.println(
    showId
  );

  Serial.println(
    "=========================="
  );
}


// =====================================================
// 결정 색 3종 디졸브
//
// 01:19 ~ 01:54
// 3색이 순환하며 부드럽게 변화
// =====================================================

void updateCrystalDissolve(
  uint32_t localTime
) {

  const uint32_t segment =
    3000;

  uint32_t cycle =
    localTime %
    (segment * 3);

  if (cycle < segment) {

    showFade(

      CRYSTAL_GRAY_R,
      CRYSTAL_GRAY_G,
      CRYSTAL_GRAY_B,

      CRYSTAL_BLUE_R,
      CRYSTAL_BLUE_G,
      CRYSTAL_BLUE_B,

      cycle,
      segment
    );

  }
  else if (
    cycle < segment * 2
  ) {

    uint32_t t =
      cycle - segment;

    showFade(

      CRYSTAL_BLUE_R,
      CRYSTAL_BLUE_G,
      CRYSTAL_BLUE_B,

      CRYSTAL_RED_R,
      CRYSTAL_RED_G,
      CRYSTAL_RED_B,

      t,
      segment
    );

  }
  else {

    uint32_t t =
      cycle -
      segment * 2;

    showFade(

      CRYSTAL_RED_R,
      CRYSTAL_RED_G,
      CRYSTAL_RED_B,

      CRYSTAL_GRAY_R,
      CRYSTAL_GRAY_G,
      CRYSTAL_GRAY_B,

      t,
      segment
    );
  }
}


// =====================================================
// 02:04 ~ 02:49
//
// 네온색이 랜덤하게 밝아졌다 어두워짐
// 각 Cube가 조금씩 다르게 움직임
// =====================================================

void updateRandomNeon() {

  uint32_t now =
    millis();


  if (
    !randomEffectInitialized
  ) {

    randomEffectInitialized =
      true;

    randomLevelFrom = 20;

    randomLevelTo =
      random(
        12,
        51
      );

    randomTransitionStart =
      now;

    randomTransitionDuration =
      random(
        700,
        1501
      );
  }


  uint32_t elapsed =
    now -
    randomTransitionStart;


  if (
    elapsed >=
    randomTransitionDuration
  ) {

    randomLevelFrom =
      randomLevelTo;

    randomLevelTo =
      random(
        12,
        51
      );

    randomTransitionStart =
      now;

    randomTransitionDuration =
      random(
        700,
        1501
      );

    elapsed = 0;
  }


  uint8_t level =
    lerp8(
      randomLevelFrom,
      randomLevelTo,
      elapsed,
      randomTransitionDuration
    );


  showNeonLevel(
    level
  );
}


// =====================================================
// ★ MAIN SHOW 타임라인
//
// 기준:
// SHOW_START = 영상 00:00
//
// 종료:
// 04:58 = 298000 ms
// =====================================================

void updateMainShowTimeline() {

  if (
    !showRunning
  ) {

    return;
  }


  uint32_t now =
    millis();


  // LED 업데이트는 약 50fps

  if (
    now -
    lastShowFrameMillis <
    SHOW_FRAME_INTERVAL_MS
  ) {

    return;
  }


  lastShowFrameMillis =
    now;


  uint32_t t =
    now -
    showStartMillis;


  // ===================================================
  // 00:00 ~ 00:31
  // 입장 상태 / 네온 유지
  // ===================================================

  if (
    t < 31000
  ) {

    showColor(
      MAINSHOW_R,
      MAINSHOW_G,
      MAINSHOW_B
    );

    return;
  }


  // ===================================================
  // 00:31 ~ 00:36
  // 본영상 시작 → OFF
  // ===================================================

  if (
    t < 36000
  ) {

    ledOff();

    return;
  }


  // ===================================================
  // 00:36 ~ 01:00
  // 흰색 1초 주기 점멸
  //
  // 0~0.5초 ON
  // 0.5~1초 OFF
  // ===================================================

  if (
    t < 60000
  ) {

    uint32_t phase =
      (t - 36000) %
      1000;

    if (
      phase < 500
    ) {

      showColor(
        SHOW_WHITE_R,
        SHOW_WHITE_G,
        SHOW_WHITE_B
      );

    } else {

      ledOff();
    }

    return;
  }


  // ===================================================
  // 01:00 ~ 01:08
  // 흰색 점점 밝아짐
  // ===================================================

  if (
    t < 68000
  ) {

    showFade(

      SHOW_WHITE_R,
      SHOW_WHITE_G,
      SHOW_WHITE_B,

      SHOW_WHITE_MAX_R,
      SHOW_WHITE_MAX_G,
      SHOW_WHITE_MAX_B,

      t - 60000,
      8000
    );

    return;
  }


  // ===================================================
  // 01:08 ~ 01:14
  // 네온색
  // ===================================================

  if (
    t < 74000
  ) {

    showColor(
      MAINSHOW_R,
      MAINSHOW_G,
      MAINSHOW_B
    );

    return;
  }


  // ===================================================
  // 01:14 순간 네온 플래시
  //
  // 300ms 정도만 밝아짐
  // 최대 100 이하
  // ===================================================

  if (
    t < 74300
  ) {

    uint32_t p =
      t - 74000;


    if (
      p < 120
    ) {

      showFade(

        MAINSHOW_R,
        MAINSHOW_G,
        MAINSHOW_B,

        SHOW_NEON_MAX_R,
        SHOW_NEON_MAX_G,
        SHOW_NEON_MAX_B,

        p,
        120
      );

    } else {

      showFade(

        SHOW_NEON_MAX_R,
        SHOW_NEON_MAX_G,
        SHOW_NEON_MAX_B,

        MAINSHOW_R,
        MAINSHOW_G,
        MAINSHOW_B,

        p - 120,
        180
      );
    }

    return;
  }


  // ===================================================
  // 01:14.3 ~ 01:19
  // 기본 네온 유지
  // ===================================================

  if (
    t < 79000
  ) {

    showColor(
      MAINSHOW_R,
      MAINSHOW_G,
      MAINSHOW_B
    );

    return;
  }


  // ===================================================
  // 01:19 ~ 01:54
  // 결정 3색 디졸브
  // ===================================================

  if (
    t < 114000
  ) {

    updateCrystalDissolve(
      t - 79000
    );

    return;
  }


  // ===================================================
  // 01:54 ~ 01:59
  // 전체 흰색으로 점점 밝아짐
  // ===================================================

  if (
    t < 119000
  ) {

    showFade(

      CRYSTAL_GRAY_R,
      CRYSTAL_GRAY_G,
      CRYSTAL_GRAY_B,

      SHOW_WHITE_MAX_R,
      SHOW_WHITE_MAX_G,
      SHOW_WHITE_MAX_B,

      t - 114000,
      5000
    );

    return;
  }


  // ===================================================
  // 01:59 ~ 02:04
  // 네온 최대 → 기본 밝기로 감소
  // ===================================================

  if (
    t < 124000
  ) {

    showFade(

      SHOW_NEON_MAX_R,
      SHOW_NEON_MAX_G,
      SHOW_NEON_MAX_B,

      MAINSHOW_R,
      MAINSHOW_G,
      MAINSHOW_B,

      t - 119000,
      5000
    );

    return;
  }


  // ===================================================
  // 02:04 ~ 02:49
  // 네온 랜덤 밝기
  // ===================================================

  if (
    t < 169000
  ) {

    updateRandomNeon();

    return;
  }


  // ===================================================
  // 02:49 ~ 03:04
  // OFF
  // ===================================================

  if (
    t < 184000
  ) {

    ledOff();

    return;
  }


  // ===================================================
  // 03:04 ~ 03:12
  // 사막색 Fade In
  // ===================================================

  if (
    t < 192000
  ) {

    showFade(

      0,
      0,
      0,

      SHOW_DESERT_R,
      SHOW_DESERT_G,
      SHOW_DESERT_B,

      t - 184000,
      8000
    );

    return;
  }


  // ===================================================
  // 03:12 ~ 03:41
  // 사막색 천천히 Fade Out
  // ===================================================

  if (
    t < 221000
  ) {

    showFade(

      SHOW_DESERT_R,
      SHOW_DESERT_G,
      SHOW_DESERT_B,

      0,
      0,
      0,

      t - 192000,
      29000
    );

    return;
  }


  // ===================================================
  // 03:41 ~ 03:51
  // OFF
  // ===================================================

  if (
    t < 231000
  ) {

    ledOff();

    return;
  }


  // ===================================================
  // 03:51 ~ 03:54
  // 풀색 Fade In
  // ===================================================

  if (
    t < 234000
  ) {

    showFade(

      0,
      0,
      0,

      SHOW_POOL_R,
      SHOW_POOL_G,
      SHOW_POOL_B,

      t - 231000,
      3000
    );

    return;
  }


  // ===================================================
  // 03:54 ~ 03:57
  // 풀색 Fade Out
  // ===================================================

  if (
    t < 237000
  ) {

    showFade(

      SHOW_POOL_R,
      SHOW_POOL_G,
      SHOW_POOL_B,

      0,
      0,
      0,

      t - 234000,
      3000
    );

    return;
  }


  // ===================================================
  // 03:57 ~ 04:37
  // OFF
  // ===================================================

  if (
    t < 277000
  ) {

    ledOff();

    return;
  }


  // ===================================================
  // 04:37 ~ 04:47
  // 흰색 Fade In
  // ===================================================

  if (
    t < 287000
  ) {

    showFade(

      0,
      0,
      0,

      SHOW_WHITE_R,
      SHOW_WHITE_G,
      SHOW_WHITE_B,

      t - 277000,
      10000
    );

    return;
  }


  // ===================================================
  // 04:47 ~ 04:55
  //
  // 낮은 흰색 유지
  // 약 700ms마다
  // 120ms 강한 플래시
  //
  // ★ 강한 순간에도 최대 100
  // ===================================================

  if (
    t < 295000
  ) {

    uint32_t phase =
      (t - 287000) %
      700;


    if (
      phase < 120
    ) {

      showColor(
        SHOW_WHITE_MAX_R,
        SHOW_WHITE_MAX_G,
        SHOW_WHITE_MAX_B
      );

    } else {

      showColor(
        SHOW_WHITE_R,
        SHOW_WHITE_G,
        SHOW_WHITE_B
      );
    }

    return;
  }


  // ===================================================
  // 04:55 ~ 04:58
  // 흰색 Fade Out
  // ===================================================

  if (
    t < 298000
  ) {

    showFade(

      SHOW_WHITE_R,
      SHOW_WHITE_G,
      SHOW_WHITE_B,

      0,
      0,
      0,

      t - 295000,
      3000
    );

    return;
  }


  // ===================================================
  // 04:58 이후
  // 2부에서는 네오코어 OFF
  // ===================================================

  ledOff();

  showRunning =
    false;

  // 다음 회차 SHOW_START를 다시 받지 않도록
  // 메인쇼 참가 자격만 해제한다. LED는 OFF 유지.
  currentZone =
    ZONE_IDLE;


  Serial.println();

  Serial.println(
    "MAIN SHOW TIMELINE END"
  );

  Serial.println(
    "LED OFF"
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


  // ===================================================
  // LED
  // ===================================================

  pixels.begin();

  ledOff();


  // 각 Cube의 랜덤 움직임 차이를 위해
  // ESP32 하드웨어 랜덤값 사용

  randomSeed(
    esp_random()
  );


  // ===================================================
  // Wi-Fi STA
  // ===================================================

  WiFi.mode(
    WIFI_STA
  );


  delay(100);


  Serial.println();

  Serial.println(
    "================================"
  );

  Serial.println(
    "NCT NEOCORE CUBE"
  );

  Serial.println(
    "FW: v1.4.1-STABLE-TEST"
  );

  Serial.print(
    "Cube MAC: "
  );

  Serial.println(
    WiFi.macAddress()
  );


  // ===================================================
  // 등록정보
  // ===================================================

  loadRegistration();


  if (
    isRegistered
  ) {

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


  // ===================================================
  // Wi-Fi / OTA 먼저 연결
  // ESP-NOW는 Wi-Fi 채널이 확정된 뒤 시작한다.
  // ===================================================

  startTemporaryOTA();

  if (
    WiFi.status() == WL_CONNECTED
  ) {

    Serial.print(
      "WIFI CHANNEL: "
    );

    Serial.println(
      WiFi.channel()
    );

  } else {

    // 현장 공유기 고정 채널 = 2
    // 공유기 접속 실패 시에도 ESP-NOW 기능은 계속 살린다.
    esp_wifi_set_channel(
      2,
      WIFI_SECOND_CHAN_NONE
    );

    Serial.println(
      "WIFI NOT CONNECTED"
    );

    Serial.println(
      "ESP-NOW FALLBACK CHANNEL: 2"
    );
  }


  // ===================================================
  // ESP-NOW
  // ===================================================

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


  // ===================================================
  // 최초 상태
  // ===================================================

  currentZone =
    ZONE_IDLE;

  showIdleColor();

  Serial.print(
    "FW: "
  );
  Serial.println(
    "v1.4.1-STABLE-TEST"
  );

  Serial.print(
    "Cube ID: "
  );

  if (isRegistered) {
    Serial.println(myCubeID);
  } else {
    Serial.println("UNREGISTERED");
  }

  Serial.print(
    "ESP-NOW CHANNEL: "
  );

  Serial.println(
    WiFi.channel()
  );

  Serial.println(
    "Cube READY"
  );

  Serial.println(
    "================================"
  );

}


// =====================================================
// LOOP
// =====================================================

void loop() {

  // ===================================================
  // OTA
  // ===================================================

  if (
    otaReady
  ) {

    ArduinoOTA.handle();
  }


  // ===================================================
  // ★ MAIN SHOW 로컬 재생
  // 패킷이 없어도 계속 실행되어야 함
  // ===================================================

  updateMainShowTimeline();


  // ===================================================
  // ESP-NOW 패킷 없음
  // ===================================================

  if (
    !packetReady
  ) {

    delay(2);

    return;
  }


  packetReady =
    false;


  // ===================================================
  // DISCOVER
  // ===================================================

  if (
    pendingPacket.type ==
    MSG_DISCOVER
  ) {

    sendDiscoverReply(
      senderMac
    );

    return;
  }


  // ===================================================
  // REGISTER
  // ===================================================

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


  // ===================================================
  // SET ZONE
  // ===================================================

  if (
    pendingPacket.type ==
    MSG_SET_ZONE
  ) {

    // Zone 명령이 들어오면
    // Main Show 재생 중단

    showRunning =
      false;


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


  // ===================================================
  // ★ SHOW START
  // ===================================================

  if (
    pendingPacket.type ==
    MSG_SHOW_START
  ) {

    // 메인쇼 입장 태깅을 받은 Cube만 실행
    if (
      currentZone !=
      ZONE_MAINSHOW
    ) {

      Serial.print(
        "SHOW_START IGNORED / ZONE="
      );

      Serial.println(
        currentZone
      );

      return;
    }

    startMainShow(
      pendingPacket.cubeID
    );

    return;
  }
}