#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// =====================================================
// NCT IMMERSIVE DEEP
// PRESHOW TAGGING PLATE
//
// ESP32-C3 SuperMini
// PN532 I2C
//
// NFC 성공 설정:
// SDA = GPIO4
// SCL = GPIO3
// NFC CHECK = 30ms
// NFC READ TIMEOUT = 80ms
// TAG LEAVE = 700ms
//
// ESP-NOW Channel = 1
// =====================================================


// =====================================================
// ★ 플레이트 번호
// 1 / 2 / 3 / 4
// =====================================================

#define PRESHOW_POINT_ID 1


// =====================================================
// ESP-NOW Channel
// =====================================================

#define ESPNOW_CHANNEL 1


// =====================================================
// Media Bridge MAC
//
// E8:3D:C1:94:6C:9C
// =====================================================

uint8_t MEDIA_BRIDGE_MAC[6] = {

  0xE8,
  0x3D,
  0xC1,
  0x94,
  0x6C,
  0x9C

};


// =====================================================
// PN532
// =====================================================

#define SDA_PIN 4
#define SCL_PIN 3

Adafruit_PN532 nfc(-1, -1);


// =====================================================
// NFC 판정값
// =====================================================

#define NFC_CHECK_INTERVAL 30
#define NFC_READ_TIMEOUT   80
#define TAG_LEAVE_TIMEOUT  700


// =====================================================
// Cube ESP-NOW Message
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
// Cube Packet
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
// Media Packet
// =====================================================

struct PreshowMediaPacket {

  uint8_t pointID;

  uint8_t state;
};


// =====================================================
// Cube Record
// =====================================================

struct CubeRecord {

  uint32_t cubeID;

  uint8_t uidLength;
  uint8_t uid[7];

  uint8_t mac[6];
};


// =====================================================
// Cube Table
// 현재 등록된 32대
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

bool mediaEventActive = false;


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

    Serial.print(uid[i], HEX);

    if (i < len - 1) {
      Serial.print(":");
    }
  }
}


// =====================================================
// UID -> Cube 찾기
// =====================================================

int findCube(
  const uint8_t *uid,
  uint8_t uidLength
) {

  for (int i = 0; i < CUBE_COUNT; i++) {

    if (
      cubeTable[i].uidLength
      != uidLength
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


  peer.channel =
    ESPNOW_CHANNEL;


  peer.encrypt =
    false;


  esp_err_t result =
    esp_now_add_peer(
      &peer
    );


  return (
    result == ESP_OK
  );
}


// =====================================================
// 미디어 이벤트 전송
// =====================================================

void sendMediaEvent(
  uint8_t state
) {

  if (
    !addPeer(
      MEDIA_BRIDGE_MAC
    )
  ) {

    Serial.println(
      "MEDIA BRIDGE PEER FAILED"
    );

    return;
  }


  PreshowMediaPacket packet = {};


  packet.pointID =
    PRESHOW_POINT_ID;


  packet.state =
    state;


  esp_err_t result =
    esp_now_send(
      MEDIA_BRIDGE_MAC,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (
    result == ESP_OK
  ) {

    Serial.print(
      "MEDIA -> POINT "
    );

    Serial.print(
      PRESHOW_POINT_ID
    );


    if (
      state == 1
    ) {

      Serial.println(" ON");

    } else {

      Serial.println(" OFF");
    }

  } else {

    Serial.print(
      "MEDIA SEND ERROR: "
    );

    Serial.println(
      result
    );
  }
}


// =====================================================
// Cube PRESHOW 명령
// =====================================================

void sendPreshowCommand(
  const CubeRecord &cube
) {

  if (
    !addPeer(
      cube.mac
    )
  ) {

    Serial.println(
      "CUBE PEER ADD FAILED"
    );

    return;
  }


  Packet packet = {};


  packet.type =
    MSG_SET_ZONE;


  packet.cubeID =
    cube.cubeID;


  packet.success =
    ZONE_PRESHOW;


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
      "PRESHOW SENT -> Cube #"
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


  // Cube peer는 계속 쌓이지 않도록 제거
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

  mediaEventActive =
    false;


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


  // ===================================================
  // Cube -> PRESHOW 상태
  // ===================================================

  sendPreshowCommand(
    cubeTable[index]
  );


  // ===================================================
  // Media -> ON
  // ===================================================

  sendMediaEvent(
    1
  );


  mediaEventActive =
    true;
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(500);


  Serial.println();
  Serial.println("==========================");
  Serial.println("NCT PRESHOW TAG PLATE");
  Serial.println("==========================");


  Serial.print("POINT ID: ");
  Serial.println(PRESHOW_POINT_ID);


  // ===================================================
  // PN532
  // ===================================================

  Wire.begin(
    SDA_PIN,
    SCL_PIN
  );


  delay(300);


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
      delay(100);
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


  delay(100);


  // ===================================================
  // Channel 1 강제
  // ===================================================

  esp_err_t channelResult =
    esp_wifi_set_channel(
      ESPNOW_CHANNEL,
      WIFI_SECOND_CHAN_NONE
    );


  if (
    channelResult == ESP_OK
  ) {

    Serial.println(
      "CHANNEL SET -> 1"
    );

  } else {

    Serial.print(
      "CHANNEL SET ERROR: "
    );

    Serial.println(
      channelResult
    );
  }


  if (
    esp_now_init()
    != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT ERROR"
    );


    while (true) {
      delay(100);
    }
  }


  // ===================================================
  // Media Bridge 등록
  // ===================================================

  if (
    addPeer(
      MEDIA_BRIDGE_MAC
    )
  ) {

    Serial.println(
      "MEDIA BRIDGE PEER READY"
    );

  } else {

    Serial.println(
      "MEDIA BRIDGE PEER FAILED"
    );
  }


  Serial.print(
    "TAG PLATE MAC: "
  );

  Serial.println(
    WiFi.macAddress()
  );


  Serial.print(
    "ESP-NOW CHANNEL: "
  );

  Serial.println(
    ESPNOW_CHANNEL
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


  if (
    now - lastNfcCheck
    < NFC_CHECK_INTERVAL
  ) {

    return;
  }


  lastNfcCheck =
    now;


  uint8_t uid[7];

  uint8_t uidLength;


  bool found =
    nfc.readPassiveTargetID(
      PN532_MIFARE_ISO14443A,
      uid,
      &uidLength,
      NFC_READ_TIMEOUT
    );


  // ===================================================
  // TAG FOUND
  // ===================================================

  if (
    found
  ) {

    lastSeenTime =
      now;


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
  // ===================================================

  if (
    tagPresent &&
    now - lastSeenTime
    > TAG_LEAVE_TIMEOUT
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


    // 정상 Cube가 ON을 보낸 경우에만 OFF
    if (
      mediaEventActive
    ) {

      sendMediaEvent(
        0
      );


      mediaEventActive =
        false;
    }
  }
}