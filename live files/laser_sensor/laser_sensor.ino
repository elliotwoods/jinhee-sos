/*
 * ============================================================
 * NCT IMMERSIVE DEEP - POOL ZONE RADIO
 * Version : v1.2.0
 * Date    : 2026-09-16
 *
 * [기준 성공 기능]
 * - VL53L4CD 슬라이더 1~23 판정
 * - PN532 NFC 감지
 * - NFC 존재 시 12V 직선 LED 스트립 ON
 * - 슬라이더 이동 → 중앙제어기로 ESP-NOW 전송
 * - Heartbeat로 중앙 상태 유지
 *
 * [v1.2.0 추가]
 * - NFC UID → CubeRecord 검색
 * - 등록된 NeoCore Cube MAC 확인
 * - MSG_SET_ZONE / ZONE_POOL 전송
 * - 태깅 시 NeoCore Cube를 풀존(파란색) 상태로 변경
 *
 * ★ 라디오마다 아래 3개만 수정
 *   RADIO_ID
 *   CAL_POS_1_MM
 *   CAL_POS_23_MM
 * ============================================================
 */

#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Adafruit_PN532.h>
#include <VL53L4CD.h>


// ============================================================
// ★ 라디오별 설정
// ============================================================

#define RADIO_ID 4

// ★ 실제 라디오에서 측정한 값으로 변경
#define CAL_POS_1_MM   383.0f
#define CAL_POS_23_MM   43.0f


// ============================================================
// PIN
// ============================================================

#define I2C_SDA 4
#define I2C_SCL 3

// 라디오의 12V 직선 LED 스트립 MOSFET
#define STRIP_LED_PIN 5


// ============================================================
// PN532
// ★ 현장에서 성공한 방식 그대로
// ============================================================

Adafruit_PN532 nfc(-1, -1);

#define NFC_CHECK_INTERVAL_MS 30
#define NFC_READ_TIMEOUT_MS   80
#define TAG_LEAVE_TIMEOUT_MS  700


// ============================================================
// VL53L4CD
// ============================================================

VL53L4CD laser;

#define MEMBER_COUNT 23

#define FILTER_SIZE 2

#define RANGE_INTERVAL_MS   20
#define POSITION_STABLE_MS  50


// ============================================================
// ESP-NOW
// ============================================================

#define ESPNOW_CHANNEL 6

#define HEARTBEAT_MS 150

#define PACKET_MAGIC 0x4E435450


uint8_t broadcastAddress[] = {
  0xFF, 0xFF, 0xFF,
  0xFF, 0xFF, 0xFF
};


// ============================================================
// 중앙제어기용 패킷
// ============================================================

struct __attribute__((packed)) RadioPacket
{
  uint32_t magic;

  uint8_t radioId;

  uint8_t active;

  uint8_t member;

  uint8_t uidLength;

  uint8_t uid[7];
};


// ============================================================
// NeoCore Cube Firmware와 동일한 MessageType
// ============================================================

enum MessageType : uint8_t
{
  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5,

  MSG_SET_ZONE       = 6
};


// ============================================================
// NeoCore Zone
// ============================================================

enum ZoneType : uint8_t
{
  ZONE_IDLE     = 0,
  ZONE_PRESHOW  = 1,
  ZONE_DESERT   = 2,
  ZONE_POOL     = 3,
  ZONE_MAINSHOW = 4
};


// ============================================================
// NeoCore Cube용 ESP-NOW Packet
//
// ★ Cube Firmware와 구조가 같아야 함
// ============================================================

struct Packet
{
  uint8_t type;

  uint32_t cubeID;

  uint8_t mac[6];

  uint8_t uidLength;

  uint8_t uid[7];

  uint8_t success;
};


// ============================================================
// Cube 등록 정보
// ============================================================

struct CubeRecord
{
  uint32_t cubeID;

  uint8_t uidLength;

  uint8_t uid[7];

  uint8_t mac[6];
};


// ============================================================
// Cube Table
//
// 2026-09-15 기준 등록된 32대
// 프리쇼에서 실제 성공했던 동일 테이블
// ============================================================

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


// ============================================================
// STATE
// ============================================================

uint16_t distanceBuffer[FILTER_SIZE] = {0};

uint8_t bufferIndex = 0;
uint8_t bufferCount = 0;

float filteredDistance = 0.0f;

int candidatePosition = -1;
int confirmedPosition = -1;

uint32_t candidateSince = 0;

uint32_t lastRangeRead = 0;
uint32_t lastNfcCheck = 0;
uint32_t lastTagSeen = 0;
uint32_t lastHeartbeat = 0;

bool tagActive = false;

uint8_t currentUID[7] = {0};
uint8_t currentUIDLength = 0;


// ============================================================
// UID 출력
// ============================================================

void printUID(
  const uint8_t *uid,
  uint8_t len
)
{
  for (uint8_t i = 0; i < len; i++)
  {
    if (uid[i] < 0x10)
    {
      Serial.print("0");
    }

    Serial.print(
      uid[i],
      HEX
    );

    if (i < len - 1)
    {
      Serial.print(":");
    }
  }
}


// ============================================================
// UID → Cube 찾기
// ============================================================

int findCube(
  const uint8_t *uid,
  uint8_t uidLength
)
{
  for (int i = 0; i < CUBE_COUNT; i++)
  {
    if (
      cubeTable[i].uidLength !=
      uidLength
    )
    {
      continue;
    }

    if (
      memcmp(
        cubeTable[i].uid,
        uid,
        uidLength
      ) == 0
    )
    {
      return i;
    }
  }

  return -1;
}


// ============================================================
// Cube ESP-NOW Peer 추가
// ============================================================

bool addCubePeer(
  const uint8_t *mac
)
{
  if (
    esp_now_is_peer_exist(mac)
  )
  {
    return true;
  }


  esp_now_peer_info_t peer = {};

  memcpy(
    peer.peer_addr,
    mac,
    6
  );

  // 현재 ESP-NOW 채널 사용
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


// ============================================================
// Cube에 POOL Zone 명령 전송
// ============================================================

void sendPoolCommand(
  const CubeRecord &cube
)
{
  if (
    !addCubePeer(cube.mac)
  )
  {
    Serial.println(
      "[CUBE] PEER ADD FAILED"
    );

    return;
  }


  Packet packet = {};

  packet.type =
    MSG_SET_ZONE;

  packet.cubeID =
    cube.cubeID;

  // ★ 풀존
  packet.success =
    ZONE_POOL;


  esp_err_t result =
    esp_now_send(
      cube.mac,
      (uint8_t *)&packet,
      sizeof(packet)
    );


  if (
    result == ESP_OK
  )
  {
    Serial.print(
      "[CUBE] ZONE_POOL SENT -> Cube #"
    );

    Serial.println(
      cube.cubeID
    );
  }
  else
  {
    Serial.print(
      "[CUBE] SEND FAILED: "
    );

    Serial.println(
      result
    );
  }


  // 프리쇼 성공 방식 그대로:
  // peer 20개 제한 방지

  delay(30);


  if (
    esp_now_is_peer_exist(
      cube.mac
    )
  )
  {
    esp_now_del_peer(
      cube.mac
    );
  }
}


// ============================================================
// DISTANCE FILTER
// ============================================================

float updateDistanceFilter(uint16_t value)
{
  distanceBuffer[bufferIndex] =
    value;

  bufferIndex =
    (bufferIndex + 1)
    % FILTER_SIZE;

  if (
    bufferCount <
    FILTER_SIZE
  )
  {
    bufferCount++;
  }


  uint32_t total = 0;


  for (
    uint8_t i = 0;
    i < bufferCount;
    i++
  )
  {
    total +=
      distanceBuffer[i];
  }


  return
    (float)total /
    bufferCount;
}


// ============================================================
// DISTANCE → MEMBER
// ============================================================

int distanceToMember(float distance)
{
  float step =
    (CAL_POS_23_MM - CAL_POS_1_MM)
    / (MEMBER_COUNT - 1);


  if (
    step == 0.0f
  )
  {
    return -1;
  }


  int member =
    round(
      ((distance - CAL_POS_1_MM)
      / step)
      + 1.0f
    );


  float margin =
    abs(step) *
    0.7f;


  float minimum =
    min(
      CAL_POS_1_MM,
      CAL_POS_23_MM
    )
    - margin;


  float maximum =
    max(
      CAL_POS_1_MM,
      CAL_POS_23_MM
    )
    + margin;


  if (
    distance < minimum ||
    distance > maximum
  )
  {
    return -1;
  }


  return constrain(
    member,
    1,
    MEMBER_COUNT
  );
}


// ============================================================
// 중앙 컨트롤러에 현재 상태 전송
// ============================================================

void sendCentralState(
  bool active
)
{
  RadioPacket packet = {};


  packet.magic =
    PACKET_MAGIC;

  packet.radioId =
    RADIO_ID;


  if (
    active &&
    confirmedPosition >= 1 &&
    confirmedPosition <= MEMBER_COUNT
  )
  {
    packet.active =
      1;

    packet.member =
      confirmedPosition;
  }
  else
  {
    packet.active =
      0;

    packet.member =
      0;
  }


  packet.uidLength =
    min(
      (uint8_t)7,
      currentUIDLength
    );


  memcpy(
    packet.uid,
    currentUID,
    packet.uidLength
  );


  esp_now_send(
    broadcastAddress,
    (uint8_t *)&packet,
    sizeof(packet)
  );
}


// ============================================================
// POSITION UPDATE
// ============================================================

void updatePosition(
  int newPosition
)
{
  if (
    newPosition < 1 ||
    newPosition > MEMBER_COUNT
  )
  {
    return;
  }


  if (
    newPosition !=
    candidatePosition
  )
  {
    candidatePosition =
      newPosition;

    candidateSince =
      millis();

    return;
  }


  if (
    newPosition !=
      confirmedPosition &&

    millis() -
      candidateSince >=
      POSITION_STABLE_MS
  )
  {
    int oldPosition =
      confirmedPosition;


    confirmedPosition =
      newPosition;


    Serial.print(
      "[SLIDER] "
    );

    Serial.print(
      oldPosition
    );

    Serial.print(
      " -> "
    );

    Serial.println(
      confirmedPosition
    );


    // 큐브가 올라가 있으면
    // 슬라이더 이동 즉시 중앙에 전송

    if (
      tagActive
    )
    {
      sendCentralState(
        true
      );

      lastHeartbeat =
        millis();
    }
  }
}


// ============================================================
// SLIDER
// ============================================================

void processSlider()
{
  if (
    millis() -
      lastRangeRead <
      RANGE_INTERVAL_MS
  )
  {
    return;
  }


  lastRangeRead =
    millis();


  uint16_t distance =
    laser
      .readRangeContinuousMillimeters();


  if (
    laser.timeoutOccurred()
  )
  {
    return;
  }


  if (
    distance < 10 ||
    distance > 1000
  )
  {
    return;
  }


  filteredDistance =
    updateDistanceFilter(
      distance
    );


  int member =
    distanceToMember(
      filteredDistance
    );


  updatePosition(
    member
  );


  // 시리얼 출력
  static uint32_t lastPrint = 0;


  if (
    millis() -
      lastPrint >=
      250
  )
  {
    lastPrint =
      millis();


    Serial.print(
      "DIST="
    );

    Serial.print(
      filteredDistance,
      1
    );

    Serial.print(
      "  MEMBER="
    );

    Serial.print(
      confirmedPosition
    );

    Serial.print(
      "  TAG="
    );

    Serial.println(
      tagActive
      ? "ON"
      : "OFF"
    );
  }
}


// ============================================================
// NFC
// ============================================================

void processNFC()
{
  if (
    millis() -
      lastNfcCheck <
      NFC_CHECK_INTERVAL_MS
  )
  {
    return;
  }


  lastNfcCheck =
    millis();


  uint8_t uid[7] =
    {0,0,0,0,0,0,0};

  uint8_t uidLength =
    0;


  bool detected =
    nfc.readPassiveTargetID(
      PN532_MIFARE_ISO14443A,
      uid,
      &uidLength,
      NFC_READ_TIMEOUT_MS
    );


  // ==========================================================
  // TAG 발견
  // ==========================================================

  if (
    detected
  )
  {
    lastTagSeen =
      millis();


    // 처음 올라온 순간
    if (
      !tagActive
    )
    {
      tagActive =
        true;


      currentUIDLength =
        min(
          (uint8_t)7,
          uidLength
        );


      memcpy(
        currentUID,
        uid,
        currentUIDLength
      );


      // ---------------------------------------------
      // 라디오 직선 LED 스트립 ON
      // ---------------------------------------------

      digitalWrite(
        STRIP_LED_PIN,
        HIGH
      );


      Serial.println();

      Serial.println(
        "===== NEOCORE ON ====="
      );


      Serial.print(
        "UID = "
      );

      printUID(
        uid,
        uidLength
      );

      Serial.println();


      Serial.print(
        "MEMBER = "
      );

      Serial.println(
        confirmedPosition
      );


      // ---------------------------------------------
      // 중앙 컨트롤러에 ACTIVE/MEMBER 전송
      // ---------------------------------------------

      sendCentralState(
        true
      );


      lastHeartbeat =
        millis();


      // ---------------------------------------------
      // UID → Cube 찾기
      // ---------------------------------------------

      int cubeIndex =
        findCube(
          uid,
          uidLength
        );


      if (
        cubeIndex >= 0
      )
      {
        Serial.print(
          "[CUBE] FOUND Cube #"
        );

        Serial.println(
          cubeTable[cubeIndex].cubeID
        );


        // -------------------------------------------
        // NeoCore에 풀존 명령
        // -------------------------------------------

        sendPoolCommand(
          cubeTable[cubeIndex]
        );
      }
      else
      {
        // 등록되지 않은 Cube라도
        // 풀존 인터랙션 자체는 계속 동작
        Serial.println(
          "[CUBE] UID NOT IN TABLE"
        );
      }
    }


    return;
  }


  // ==========================================================
  // TAG 제거
  // ==========================================================

  if (
    tagActive &&
    millis() -
      lastTagSeen >
      TAG_LEAVE_TIMEOUT_MS
  )
  {
    tagActive =
      false;


    // 라디오 LED 스트립 OFF

    digitalWrite(
      STRIP_LED_PIN,
      LOW
    );


    Serial.println();

    Serial.println(
      "===== NEOCORE OFF ====="
    );


    // 중앙 액자 해제

    sendCentralState(
      false
    );


    currentUIDLength =
      0;
  }
}


// ============================================================
// HEARTBEAT
// ============================================================

void processHeartbeat()
{
  if (
    !tagActive
  )
  {
    return;
  }


  if (
    millis() -
      lastHeartbeat <
      HEARTBEAT_MS
  )
  {
    return;
  }


  lastHeartbeat =
    millis();


  sendCentralState(
    true
  );
}


// ============================================================
// ESP-NOW SETUP
// ============================================================

void setupEspNow()
{
  WiFi.mode(
    WIFI_STA
  );


  esp_wifi_set_channel(
    ESPNOW_CHANNEL,
    WIFI_SECOND_CHAN_NONE
  );


  if (
    esp_now_init() !=
    ESP_OK
  )
  {
    Serial.println(
      "[ERROR] ESP-NOW INIT"
    );

    return;
  }


  // ---------------------------------------------
  // 중앙제어기용 Broadcast Peer
  // ---------------------------------------------

  esp_now_peer_info_t peer = {};


  memcpy(
    peer.peer_addr,
    broadcastAddress,
    6
  );


  peer.channel =
    ESPNOW_CHANNEL;

  peer.encrypt =
    false;


  if (
    esp_now_add_peer(
      &peer
    ) != ESP_OK
  )
  {
    Serial.println(
      "[ERROR] BROADCAST PEER"
    );
  }
  else
  {
    Serial.println(
      "[OK] ESP-NOW"
    );
  }


  Serial.print(
    "RADIO MAC: "
  );

  Serial.println(
    WiFi.macAddress()
  );
}


// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(
    115200
  );


  delay(
    1200
  );


  Serial.println();

  Serial.println(
    "=== POOL RADIO v1.2.0 ==="
  );


  // ==========================================================
  // LED STRIP
  // ==========================================================

  pinMode(
    STRIP_LED_PIN,
    OUTPUT
  );


  digitalWrite(
    STRIP_LED_PIN,
    LOW
  );


  // ==========================================================
  // I2C
  // ==========================================================

  Wire.begin(
    I2C_SDA,
    I2C_SCL
  );


  // ==========================================================
  // VL53L4CD
  // ==========================================================

  laser.setTimeout(
    250
  );


  if (
    !laser.init()
  )
  {
    Serial.println(
      "[ERROR] VL53L4CD"
    );
  }
  else
  {
    laser.startContinuous();


    Serial.println(
      "[OK] VL53L4CD"
    );
  }


  // ==========================================================
  // PN532
  // ==========================================================

  nfc.begin();


  uint32_t versiondata =
    nfc.getFirmwareVersion();


  if (
    !versiondata
  )
  {
    Serial.println(
      "[ERROR] PN532"
    );
  }
  else
  {
    nfc.SAMConfig();


    Serial.println(
      "[OK] PN532"
    );
  }


  // ==========================================================
  // ESP-NOW
  // ==========================================================

  setupEspNow();


  Serial.print(
    "CUBE TABLE COUNT = "
  );

  Serial.println(
    CUBE_COUNT
  );


  Serial.println();

  Serial.println(
    "=== POOL RADIO READY ==="
  );
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  // 슬라이더
  processSlider();


  // NFC
  processNFC();


  // NFC 처리 직후 슬라이더 다시 확인
  processSlider();


  // 중앙 컨트롤러 heartbeat
  processHeartbeat();
}