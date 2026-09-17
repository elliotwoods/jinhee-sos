#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// =====================================================
// NCT IMMERSIVE DEEP
// DESERT TAGGING PLATE
//
// ESP32-C3 SuperMini
// PN532 + 1CH MOSFET
//
// PN532
// SDA = GPIO4
// SCL = GPIO3
//
// MOSFET
// TRIG = GPIO1
// =====================================================

#define SDA_PIN      4
#define SCL_PIN      3
#define MOSFET_PIN   1

Adafruit_PN532 nfc(-1, -1);


// =====================================================
// NFC - 기존 성공값 유지
// =====================================================

#define NFC_CHECK_INTERVAL 30
#define NFC_READ_TIMEOUT   80
#define TAG_LEAVE_TIMEOUT  700


// =====================================================
// ESP-NOW Message
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6,

  // 사막 태그가 현재 올라가 있는지 전달
  MSG_TAG_STATE      = 7
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
// Packet
// 기존 구조 유지
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
// Cube 정보
// =====================================================

struct CubeRecord {

  uint32_t cubeID;

  uint8_t uidLength;
  uint8_t uid[7];

  uint8_t mac[6];
};


// =====================================================
// 현재 등록된 Cube 32대
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
  sizeof(cubeTable) / sizeof(cubeTable[0]);


// =====================================================
// 상태
// =====================================================

bool tagPresent = false;

uint8_t currentUid[7];
uint8_t currentUidLength = 0;

int currentCubeIndex = -1;

unsigned long lastSeenTime = 0;
unsigned long lastNfcCheck = 0;


// =====================================================
// UID 출력
// =====================================================

void printUid(const uint8_t *uid, uint8_t len) {

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
// UID → Cube
// =====================================================

int findCube(
  const uint8_t *uid,
  uint8_t uidLength
) {

  for (int i = 0; i < CUBE_COUNT; i++) {

    if (
      cubeTable[i].uidLength != uidLength
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
// ESP-NOW Peer
// =====================================================

bool addPeer(const uint8_t *mac) {

  if (esp_now_is_peer_exist(mac)) {
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

  return (
    esp_now_add_peer(&peer)
    == ESP_OK
  );
}


void removePeer(const uint8_t *mac) {

  delay(30);

  if (
    esp_now_is_peer_exist(mac)
  ) {
    esp_now_del_peer(mac);
  }
}


// =====================================================
// 사막 Zone 전송
// =====================================================

void sendDesertZone(
  const CubeRecord &cube
) {

  if (!addPeer(cube.mac)) {

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

  packet.success =
    ZONE_DESERT;


  esp_err_t result =
    esp_now_send(
      cube.mac,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (result == ESP_OK) {

    Serial.print(
      "DESERT SENT -> Cube #"
    );

    Serial.println(
      cube.cubeID
    );

  } else {

    Serial.println(
      "DESERT SEND FAILED"
    );
  }

  removePeer(cube.mac);
}


// =====================================================
// TAG 상태 전송
// active=true  → 펄스
// active=false → 은은한 노랑
// =====================================================

void sendTagState(
  const CubeRecord &cube,
  bool active
) {

  if (!addPeer(cube.mac)) {

    Serial.println(
      "PEER ADD FAILED"
    );

    return;
  }


  Packet packet = {};

  packet.type =
    MSG_TAG_STATE;

  packet.cubeID =
    cube.cubeID;

  packet.success =
    active ? 1 : 0;


  esp_err_t result =
    esp_now_send(
      cube.mac,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (result == ESP_OK) {

    if (active) {

      Serial.println(
        "TAG ACTIVE SENT"
      );

    } else {

      Serial.println(
        "TAG INACTIVE SENT"
      );
    }

  } else {

    Serial.println(
      "TAG STATE SEND FAILED"
    );
  }

  removePeer(cube.mac);
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


  if (index < 0) {

    Serial.println(
      "UNKNOWN CUBE"
    );

    return;
  }


  currentCubeIndex =
    index;


  Serial.print(
    "FOUND Cube #"
  );

  Serial.println(
    cubeTable[index].cubeID
  );


  // 도광판 ON
  digitalWrite(
    MOSFET_PIN,
    HIGH
  );

  Serial.println(
    "DESERT LIGHT ON"
  );


  // 큐브를 사막색으로
  sendDesertZone(
    cubeTable[index]
  );


  // 태그 중 펄스 시작
  sendTagState(
    cubeTable[index],
    true
  );
}


// =====================================================
// TAG LEAVE
// =====================================================

void handleTagLeave() {

  // 도광판 OFF
  digitalWrite(
    MOSFET_PIN,
    LOW
  );

  Serial.println(
    "DESERT LIGHT OFF"
  );


  // 큐브 펄스 종료
  // 은은한 노란색 유지
  if (
    currentCubeIndex >= 0
  ) {

    sendTagState(
      cubeTable[currentCubeIndex],
      false
    );
  }


  currentCubeIndex =
    -1;
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(500);


  Serial.println();
  Serial.println(
    "=========================="
  );

  Serial.println(
    "NCT DESERT TAG PLATE"
  );

  Serial.println(
    "=========================="
  );


  // MOSFET
  pinMode(
    MOSFET_PIN,
    OUTPUT
  );

  digitalWrite(
    MOSFET_PIN,
    LOW
  );


  // PN532
  Wire.begin(
    SDA_PIN,
    SCL_PIN
  );

  delay(300);

  nfc.begin();


  uint32_t version =
    nfc.getFirmwareVersion();


  if (!version) {

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


  // ESP-NOW
  WiFi.mode(
    WIFI_STA
  );

  delay(100);


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


  Serial.print(
    "DESERT PLATE MAC: "
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


  // ---------------------------------------------------
  // TAG 있음
  // ---------------------------------------------------

  if (found) {

    lastSeenTime =
      now;


    if (!tagPresent) {

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


  // ---------------------------------------------------
  // TAG LEAVE
  // ---------------------------------------------------

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


    handleTagLeave();
  }
}