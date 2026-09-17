/*
=========================================================
 NCT IMMERSIVE DEEP
 MAIN SHOW ENTRANCE TAGGING PLATE

 Version : v1.0.0
 Date    : 2026-09-16

 변경사항:
 - 프리쇼 입장 태깅플레이트 기준 성공 코드 기반
 - PN532 / ESP-NOW / NFC 판정 방식 그대로 유지
 - 태깅 성공 시 해당 Cube에 ZONE_MAINSHOW 전송
 - Cube는 네온색으로 변경
 - 이후 Core2 SHOW_START 방송을 받을 자격 획득

 Hardware:
 - ESP32-C3 SuperMini
 - PN532 I2C

 Wiring:
 - SDA = GPIO4
 - SCL = GPIO3
 - IRQ / RESET 사용 안 함

 NFC 기준 성공값:
 - NFC CHECK = 30ms
 - NFC READ TIMEOUT = 80ms
 - TAG LEAVE = 700ms

 중요:
 - Cube Firmware v1.4.0-MAINSHOW 대응
=========================================================
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_PN532.h>


// =====================================================
// PN532
// ★ 기존 성공 방식 그대로
// =====================================================

#define SDA_PIN 4
#define SCL_PIN 3

Adafruit_PN532 nfc(-1, -1);


// =====================================================
// NFC 판정값
// ★ 기존 성공값 그대로
// =====================================================

#define NFC_CHECK_INTERVAL 30
#define NFC_READ_TIMEOUT   80
#define TAG_LEAVE_TIMEOUT  700


// =====================================================
// ESP-NOW 메시지
// Cube Firmware와 동일
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6,

  MSG_SHOW_START     = 7
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
// ★ Cube와 정확히 같은 구조
// =====================================================

struct Packet {

  uint8_t type;

  uint32_t cubeID;

  uint8_t mac[6];

  uint8_t uidLength;
  uint8_t uid[7];

  uint8_t success;
};


// =====================================================
// Cube 등록 정보
// =====================================================

struct CubeRecord {

  uint32_t cubeID;

  uint8_t uidLength;
  uint8_t uid[7];

  uint8_t mac[6];
};


// =====================================================
// Cube Table
// 2026-09-15 기준 등록된 32대
//
// ★ 프리쇼 기준 성공 코드의 테이블 그대로 사용
// =====================================================

CubeRecord cubeTable[] = {

  {1,  7, {0x04,0x60,0x35,0x4A,0xB6,0x21,0x91}, {0xAC,0x27,0x6E,0x80,0x37,0xBC}},
  {2,  7, {0x53,0x21,0xD4,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0x60,0x4C}},
  {3,  7, {0x53,0x79,0xD8,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x80,0x30,0x24}},
  {4,  7, {0x53,0xFA,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xDF,0x4C}},
  {5,  7, {0x53,0x02,0xD5,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x83,0x16,0x64}},
  {6,  7, {0x53,0xE9,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xC4,0x44}},
  {7,  7, {0x53,0x2A,0xD4,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0x47,0x7C}},
  {8,  7, {0x53,0x96,0xD4,0xCF,0x33,0x00,0x01}, {0xE0,0x72,0xA1,0x1E,0x0D,0x08}},
  {9,  7, {0x53,0xF9,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xDE,0x04}},
  {10, 7, {0x53,0x22,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF1,0xD2,0xB4}},
  {11, 7, {0x04,0x60,0x3C,0x4A,0xB6,0x21,0x91}, {0xAC,0x27,0x6E,0x81,0xF9,0x38}},
  {12, 7, {0x04,0x60,0x33,0x4A,0xB6,0x21,0x91}, {0x1C,0xDB,0xD4,0xF0,0xCF,0x10}},
  {13, 7, {0x04,0x60,0x34,0x4A,0xB6,0x21,0x91}, {0xAC,0x27,0x6E,0x81,0xF3,0xE8}},
  {14, 7, {0x53,0x20,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xEF,0x7B,0x14}},
  {15, 7, {0x53,0xF4,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xCF,0xA0}},
  {16, 7, {0x53,0xEB,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xC3,0x94}},
  {17, 7, {0x53,0x1F,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xA8,0x30}},
  {18, 7, {0x53,0xEA,0xD4,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x80,0x07,0xDC}},
  {19, 7, {0x53,0x8E,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xD4,0x20}},
  {20, 7, {0x53,0x8C,0xD4,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0x59,0x10}},
  {21, 7, {0x53,0x8D,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xEF,0x43,0x8C}},
  {22, 7, {0x04,0x60,0x32,0x4A,0xB6,0x21,0x91}, {0xAC,0x27,0x6E,0x82,0xAD,0x7C}},
  {23, 7, {0x53,0x97,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xD2,0x5C}},
  {24, 7, {0x53,0xEC,0xD4,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF1,0x47,0x44}},
  {25, 7, {0x53,0x95,0xD8,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF1,0xD0,0x60}},
  {26, 7, {0x53,0x74,0xD8,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xF0,0xCF,0xE8}},
  {27, 7, {0x53,0x8D,0xD8,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0x28,0x30}},
  {28, 7, {0x53,0x7B,0xD8,0xCF,0x33,0x00,0x01}, {0xE0,0x72,0xA1,0x1E,0x0D,0xD4}},
  {29, 7, {0x53,0x73,0xD8,0xCF,0x33,0x00,0x01}, {0x1C,0xDB,0xD4,0xEF,0x70,0x40}},
  {30, 7, {0x53,0x04,0xD5,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0x93,0x84}},
  {31, 7, {0x53,0x97,0xD8,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x83,0x15,0x34}},
  {32, 7, {0x53,0x7A,0xD8,0xCF,0x33,0x00,0x01}, {0xAC,0x27,0x6E,0x82,0xB9,0x44}}
};


const int CUBE_COUNT =
  sizeof(cubeTable) /
  sizeof(cubeTable[0]);


// =====================================================
// NFC 상태
// =====================================================

bool tagPresent = false;

uint8_t currentUid[7];
uint8_t currentUidLength = 0;

unsigned long lastSeenTime = 0;
unsigned long lastNfcCheck = 0;


// =====================================================
// UID 출력
// =====================================================

void printUid(
  const uint8_t *uid,
  uint8_t len
) {

  for (int i = 0; i < len; i++) {

    if (uid[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(
      uid[i],
      HEX
    );

    if (i < len - 1) {
      Serial.print(":");
    }
  }
}


// =====================================================
// UID → Cube 찾기
// =====================================================

int findCube(
  const uint8_t *uid,
  uint8_t uidLength
) {

  for (int i = 0; i < CUBE_COUNT; i++) {

    if (
      cubeTable[i].uidLength !=
      uidLength
    ) {

      continue;
    }


    if (
      memcmp(
        cubeTable[i].uid,
        uid,
        uidLength
      ) == 0
    ) {

      return i;
    }
  }


  return -1;
}


// =====================================================
// ESP-NOW Peer 추가
// =====================================================

bool addPeer(
  const uint8_t *mac
) {

  if (
    esp_now_is_peer_exist(mac)
  ) {

    return true;
  }


  esp_now_peer_info_t peer = {};


  memcpy(
    peer.peer_addr,
    mac,
    6
  );


  peer.channel = 0;
  peer.encrypt = false;


  esp_err_t result =
    esp_now_add_peer(
      &peer
    );


  return (
    result == ESP_OK
  );
}


// =====================================================
// ★ MAIN SHOW READY 명령 전송
//
// 해당 Cube 하나에게만
// ZONE_MAINSHOW = 4 전송
// =====================================================

void sendMainShowCommand(
  const CubeRecord &cube
) {

  if (
    !addPeer(cube.mac)
  ) {

    Serial.println(
      "PEER ADD FAILED"
    );

    return;
  }


  Packet packet = {};


  packet.type =
    MSG_SET_ZONE;


  packet.cubeID =
    cube.cubeID;


  // ★ MAIN SHOW 입장 완료
  packet.success =
    ZONE_MAINSHOW;


  esp_err_t result =
    esp_now_send(
      cube.mac,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (
    result == ESP_OK
  ) {

    Serial.print(
      "MAINSHOW READY SENT -> Cube #"
    );

    Serial.println(
      cube.cubeID
    );

  } else {

    Serial.print(
      "ESP-NOW SEND FAILED: "
    );

    Serial.println(
      result
    );
  }


  // ===================================================
  // Peer 계속 쌓이지 않도록 제거
  // ESP-NOW Peer 개수 제한 방지
  // ★ 기존 성공 구조 유지
  // ===================================================

  delay(30);


  if (
    esp_now_is_peer_exist(
      cube.mac
    )
  ) {

    esp_now_del_peer(
      cube.mac
    );
  }
}


// =====================================================
// TAG ENTER
// =====================================================

void handleTagEnter(
  const uint8_t *uid,
  uint8_t uidLength
) {

  Serial.println();

  Serial.print(
    "TAG ENTER: "
  );


  printUid(
    uid,
    uidLength
  );


  Serial.println();


  int index =
    findCube(
      uid,
      uidLength
    );


  if (
    index < 0
  ) {

    Serial.println(
      "UNKNOWN CUBE"
    );

    return;
  }


  Serial.print(
    "FOUND Cube #"
  );


  Serial.println(
    cubeTable[index].cubeID
  );


  // ★ 프리쇼가 아니라 MAINSHOW
  sendMainShowCommand(
    cubeTable[index]
  );
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(
    115200
  );


  delay(
    500
  );


  Serial.println();

  Serial.println(
    "=========================="
  );

  Serial.println(
    "NCT MAIN SHOW ENTRANCE"
  );

  Serial.println(
    "TAGGING PLATE v1.0.0"
  );

  Serial.println(
    "=========================="
  );


  // ===================================================
  // PN532
  // ★ 기존 성공 방식 그대로
  // ===================================================

  Wire.begin(
    SDA_PIN,
    SCL_PIN
  );


  delay(
    300
  );


  nfc.begin();


  uint32_t version =
    nfc.getFirmwareVersion();


  if (
    !version
  ) {

    Serial.println(
      "PN532 NOT FOUND"
    );


    while (true) {

      delay(
        100
      );
    }
  }


  Serial.println(
    "PN532 FOUND"
  );


  nfc.SAMConfig();


  // ===================================================
  // ESP-NOW
  // ===================================================

  WiFi.mode(
    WIFI_STA
  );


  delay(
    100
  );


  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT ERROR"
    );


    while (true) {

      delay(
        100
      );
    }
  }


  Serial.print(
    "TAG PLATE MAC: "
  );


  Serial.println(
    WiFi.macAddress()
  );


  Serial.print(
    "CUBE COUNT: "
  );


  Serial.println(
    CUBE_COUNT
  );


  Serial.println(
    "READY"
  );
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  unsigned long now =
    millis();


  // ===================================================
  // 30ms 간격 PN532 확인
  // ===================================================

  if (
    now - lastNfcCheck <
    NFC_CHECK_INTERVAL
  ) {

    return;
  }


  lastNfcCheck =
    now;


  uint8_t uid[7];

  uint8_t uidLength;


  // ===================================================
  // NFC 읽기
  // ★ 성공값 timeout = 80ms
  // ===================================================

  bool found =
    nfc.readPassiveTargetID(
      PN532_MIFARE_ISO14443A,
      uid,
      &uidLength,
      NFC_READ_TIMEOUT
    );


  // ===================================================
  // TAG 보임
  // ===================================================

  if (
    found
  ) {

    lastSeenTime =
      now;


    // 새 TAG ENTER
    if (
      !tagPresent
    ) {

      tagPresent =
        true;


      currentUidLength =
        uidLength;


      memcpy(
        currentUid,
        uid,
        uidLength
      );


      handleTagEnter(
        uid,
        uidLength
      );
    }


    return;
  }


  // ===================================================
  // TAG LEAVE
  // 700ms 미감지 후 제거 판정
  // ===================================================

  if (
    tagPresent &&
    now - lastSeenTime >
    TAG_LEAVE_TIMEOUT
  ) {

    tagPresent =
      false;


    Serial.print(
      "TAG LEAVE: "
    );


    printUid(
      currentUid,
      currentUidLength
    );


    Serial.println();
  }
}