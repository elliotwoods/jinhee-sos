/*
  =========================================================
  NCT IMMERSIVE DEEP
  PRESHOW EXIT / SAFETY TAGGING PLATE

  Version : v1.1-WIFI-CHANNEL-FIX
  Date    : 2026-09-17

  변경점:
  - 기존 PN532 성공 설정 유지
  - 기존 32 Cube 등록표 유지
  - TP-Link_E9E4 접속 후 ESP-NOW 시작
  - OTA Cube와 동일 Wi-Fi 채널 사용
  - 태그하면 ZONE_PRESHOW 전송 -> 큐브 RED

  Hardware:
  - ESP32-C3 SuperMini
  - PN532 I2C
  - SDA = GPIO4
  - SCL = GPIO3
  =========================================================
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// =====================================================
// DEVICE
// =====================================================

#define DEVICE_NAME "PRESHOW EXIT TAG"
#define FW_VERSION  "v1.1-WIFI-CHANNEL-FIX"

#define SDA_PIN 4
#define SCL_PIN 3

#define NFC_CHECK_INTERVAL 30
#define NFC_READ_TIMEOUT   80
#define TAG_LEAVE_TIMEOUT  700

// =====================================================
// 현장 Wi-Fi
// =====================================================

const char* WIFI_SSID     = "CONFIGURE_LOCALLY";
const char* WIFI_PASSWORD = "CONFIGURE_LOCALLY";

Adafruit_PN532 nfc(-1, -1);


// =====================================================
// ESP-NOW PROTOCOL
// =====================================================

enum MessageType : uint8_t {
  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,
  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,
  MSG_ENTER_OTA      = 5,
  MSG_SET_ZONE       = 6
};

enum ZoneType : uint8_t {
  ZONE_IDLE     = 0,
  ZONE_PRESHOW  = 1,
  ZONE_DESERT   = 2,
  ZONE_POOL     = 3,
  ZONE_MAINSHOW = 4
};

struct Packet {
  uint8_t type;
  uint32_t cubeID;
  uint8_t mac[6];
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t success;
};


// =====================================================
// CUBE REGISTRY
// =====================================================

struct CubeRecord {
  uint32_t cubeID;
  uint8_t uidLength;
  uint8_t uid[7];
  uint8_t mac[6];
};

CubeRecord cubeTable[] = {

  {1,7,{0x04,0x60,0x35,0x4A,0xB6,0x21,0x91},{0xAC,0x27,0x6E,0x80,0x37,0xBC}},
  {2,7,{0x53,0x21,0xD4,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0x60,0x4C}},
  {3,7,{0x53,0x79,0xD8,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x80,0x30,0x24}},
  {4,7,{0x53,0xFA,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xDF,0x4C}},
  {5,7,{0x53,0x02,0xD5,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x83,0x16,0x64}},
  {6,7,{0x53,0xE9,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xC4,0x44}},
  {7,7,{0x53,0x2A,0xD4,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0x47,0x7C}},
  {8,7,{0x53,0x96,0xD4,0xCF,0x33,0x00,0x01},{0xE0,0x72,0xA1,0x1E,0x0D,0x08}},
  {9,7,{0x53,0xF9,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xDE,0x04}},
  {10,7,{0x53,0x22,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF1,0xD2,0xB4}},
  {11,7,{0x04,0x60,0x3C,0x4A,0xB6,0x21,0x91},{0xAC,0x27,0x6E,0x81,0xF9,0x38}},
  {12,7,{0x04,0x60,0x33,0x4A,0xB6,0x21,0x91},{0x1C,0xDB,0xD4,0xF0,0xCF,0x10}},
  {13,7,{0x04,0x60,0x34,0x4A,0xB6,0x21,0x91},{0xAC,0x27,0x6E,0x81,0xF3,0xE8}},
  {14,7,{0x53,0x20,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xEF,0x7B,0x14}},
  {15,7,{0x53,0xF4,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xCF,0xA0}},
  {16,7,{0x53,0xEB,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xC3,0x94}},
  {17,7,{0x53,0x1F,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xA8,0x30}},
  {18,7,{0x53,0xEA,0xD4,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x80,0x07,0xDC}},
  {19,7,{0x53,0x8E,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xD4,0x20}},
  {20,7,{0x53,0x8C,0xD4,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0x59,0x10}},
  {21,7,{0x53,0x8D,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xEF,0x43,0x8C}},
  {22,7,{0x04,0x60,0x32,0x4A,0xB6,0x21,0x91},{0xAC,0x27,0x6E,0x82,0xAD,0x7C}},
  {23,7,{0x53,0x97,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xD2,0x5C}},
  {24,7,{0x53,0xEC,0xD4,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF1,0x47,0x44}},
  {25,7,{0x53,0x95,0xD8,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF1,0xD0,0x60}},
  {26,7,{0x53,0x74,0xD8,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xF0,0xCF,0xE8}},
  {27,7,{0x53,0x8D,0xD8,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0x28,0x30}},
  {28,7,{0x53,0x7B,0xD8,0xCF,0x33,0x00,0x01},{0xE0,0x72,0xA1,0x1E,0x0D,0xD4}},
  {29,7,{0x53,0x73,0xD8,0xCF,0x33,0x00,0x01},{0x1C,0xDB,0xD4,0xEF,0x70,0x40}},
  {30,7,{0x53,0x04,0xD5,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0x93,0x84}},
  {31,7,{0x53,0x97,0xD8,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x83,0x15,0x34}},
  {32,7,{0x53,0x7A,0xD8,0xCF,0x33,0x00,0x01},{0xAC,0x27,0x6E,0x82,0xB9,0x44}}

};

const int CUBE_COUNT =
  sizeof(cubeTable) / sizeof(cubeTable[0]);


// =====================================================
// NFC STATE
// =====================================================

bool tagPresent = false;

uint8_t currentUid[7];
uint8_t currentUidLength = 0;

unsigned long lastSeenTime = 0;
unsigned long lastNfcCheck = 0;


// =====================================================
// PRINT UID
// =====================================================

void printUid(const uint8_t *uid, uint8_t len) {

  for (int i = 0; i < len; i++) {

    if (uid[i] < 0x10) Serial.print("0");

    Serial.print(uid[i], HEX);

    if (i < len - 1) Serial.print(":");
  }
}


// =====================================================
// FIND CUBE
// =====================================================

int findCube(
  const uint8_t *uid,
  uint8_t uidLength
) {

  for (int i = 0; i < CUBE_COUNT; i++) {

    if (cubeTable[i].uidLength != uidLength)
      continue;

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
// ADD ESP-NOW PEER
// =====================================================

bool addPeer(const uint8_t *mac) {

  if (esp_now_is_peer_exist(mac))
    return true;

  esp_now_peer_info_t peer = {};

  memcpy(peer.peer_addr, mac, 6);

  // ★ 공유기와 현재 동일한 Wi-Fi 채널 사용
  peer.channel = WiFi.channel();

  peer.encrypt = false;

  return esp_now_add_peer(&peer) == ESP_OK;
}


// =====================================================
// SEND PRESHOW -> RED
// =====================================================

void sendPreshowCommand(
  const CubeRecord &cube
) {

  if (!addPeer(cube.mac)) {

    Serial.println("PEER ADD FAILED");
    return;
  }


  Packet packet = {};

  packet.type =
    MSG_SET_ZONE;

  packet.cubeID =
    cube.cubeID;

  // ★ 핵심
  // Cube에게 PRESHOW = RED
  packet.success =
    ZONE_PRESHOW;


  Serial.print("SEND TO Cube #");
  Serial.println(cube.cubeID);

  Serial.print("ESP-NOW CHANNEL: ");
  Serial.println(WiFi.channel());


  esp_err_t result =
    esp_now_send(
      cube.mac,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (result == ESP_OK) {

    Serial.print(
      "PRESHOW RED SENT -> Cube #"
    );

    Serial.println(
      cube.cubeID
    );

  } else {

    Serial.print(
      "ESP-NOW SEND ERROR: "
    );

    Serial.println(result);
  }


  delay(50);


  if (esp_now_is_peer_exist(cube.mac)) {

    esp_now_del_peer(cube.mac);
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

  Serial.print("TAG ENTER: ");

  printUid(uid, uidLength);

  Serial.println();


  int index =
    findCube(
      uid,
      uidLength
    );


  if (index < 0) {

    Serial.println("UNKNOWN CUBE");

    return;
  }


  Serial.print("FOUND Cube #");

  Serial.println(
    cubeTable[index].cubeID
  );


  sendPreshowCommand(
    cubeTable[index]
  );
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(500);


  Serial.println();
  Serial.println(
    "================================"
  );

  Serial.println(
    "NCT IMMERSIVE DEEP"
  );

  Serial.print("DEVICE : ");
  Serial.println(DEVICE_NAME);

  Serial.print("FW     : ");
  Serial.println(FW_VERSION);

  Serial.println(
    "ROLE   : PRESHOW -> RED"
  );

  Serial.println(
    "================================"
  );


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


  // ===================================================
  // Wi-Fi
  // Cube OTA와 같은 AP
  // ===================================================

  WiFi.mode(WIFI_STA);

  delay(100);


  Serial.print(
    "WIFI CONNECTING: "
  );

  Serial.println(
    WIFI_SSID
  );


  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );


  unsigned long wifiStart =
    millis();


  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - wifiStart < 10000
  ) {

    delay(200);
    Serial.print(".");
  }


  Serial.println();


  if (
    WiFi.status() != WL_CONNECTED
  ) {

    Serial.println(
      "ERROR: WIFI CONNECTION FAILED"
    );

    Serial.println(
      "DO NOT USE THIS TAG PLATE"
    );

    while (true) {
      delay(100);
    }
  }


  Serial.println(
    "WIFI CONNECTED"
  );


  Serial.print(
    "WIFI CHANNEL : "
  );

  Serial.println(
    WiFi.channel()
  );


  Serial.print(
    "TAG PLATE MAC: "
  );

  Serial.println(
    WiFi.macAddress()
  );


  // ===================================================
  // ESP-NOW
  // ===================================================

  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT ERROR"
    );

    while (true) {
      delay(100);
    }
  }


  Serial.print(
    "CUBE COUNT: "
  );

  Serial.println(
    CUBE_COUNT
  );


  Serial.println();
  Serial.println(
    "PRESHOW EXIT READY"
  );

  Serial.println();
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  unsigned long now =
    millis();


  if (
    now - lastNfcCheck <
    NFC_CHECK_INTERVAL
  ) {

    return;
  }


  lastNfcCheck = now;


  uint8_t uid[7];
  uint8_t uidLength = 0;


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

  if (found) {

    lastSeenTime = now;


    if (!tagPresent) {

      tagPresent = true;

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
    now - lastSeenTime >
    TAG_LEAVE_TIMEOUT
  ) {

    tagPresent = false;


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