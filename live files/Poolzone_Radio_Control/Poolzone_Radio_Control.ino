#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <VL53L4CD.h>

// ============================================================
// NCT IMMERSIVE DEEP
// POOL RADIO - SLIDER DEBUG VERSION
//
// PN532 사용 안 함
// 큐브가 항상 태그되어 있다고 강제 가정
// ============================================================


// ------------------------------------------------------------
// RADIO
// ------------------------------------------------------------

#define RADIO_ID 1


// ------------------------------------------------------------
// PIN
// ------------------------------------------------------------

#define I2C_SDA 4
#define I2C_SCL 3

#define STRIP_LED_PIN 5


// ------------------------------------------------------------
// ESP-NOW
// ------------------------------------------------------------

#define ESPNOW_CHANNEL 6
#define PACKET_MAGIC 0x4E435450

uint8_t broadcastAddress[] = {
  0xFF, 0xFF, 0xFF,
  0xFF, 0xFF, 0xFF
};


// ------------------------------------------------------------
// SLIDER
// ------------------------------------------------------------

#define MEMBER_COUNT 23

// ★ 실제 라디오 측정값으로 수정
#define CAL_POS_1_MM   380.0f
#define CAL_POS_23_MM   47.0f

#define FILTER_SIZE 3

// 거리 측정 주기
#define RANGE_INTERVAL_MS 20

// 새 위치로 인정하는 안정화 시간
#define POSITION_STABLE_MS 60


// ------------------------------------------------------------
// HEARTBEAT
// ------------------------------------------------------------

#define HEARTBEAT_MS 150


// ============================================================
// SENSOR
// ============================================================

VL53L4CD laser;


// ============================================================
// PACKET
// ============================================================

struct __attribute__((packed)) RadioPacket {

  uint32_t magic;

  uint8_t radioId;

  uint8_t active;

  uint8_t member;

  uint8_t uidLength;

  uint8_t uid[7];
};


// ============================================================
// STATE
// ============================================================

uint16_t distanceBuffer[FILTER_SIZE] = {0};

int bufferIndex = 0;
int bufferCount = 0;

float filteredDistance = 0;

int candidatePosition = -1;
int confirmedPosition = -1;

uint32_t candidateSince = 0;
uint32_t lastRangeRead = 0;
uint32_t lastHeartbeat = 0;


// ============================================================
// DISTANCE FILTER
// ============================================================

float updateDistanceFilter(uint16_t value)
{
  distanceBuffer[bufferIndex] = value;

  bufferIndex =
    (bufferIndex + 1) % FILTER_SIZE;

  if (bufferCount < FILTER_SIZE) {
    bufferCount++;
  }


  uint32_t total = 0;

  for (int i = 0; i < bufferCount; i++) {
    total += distanceBuffer[i];
  }


  return (float)total / bufferCount;
}


// ============================================================
// DISTANCE -> MEMBER
// ============================================================

int distanceToMember(float distance)
{
  float step =
    (CAL_POS_23_MM - CAL_POS_1_MM)
    / (MEMBER_COUNT - 1);


  if (step == 0) {
    return -1;
  }


  float calculated =
    ((distance - CAL_POS_1_MM) / step)
    + 1.0f;


  int member =
    round(calculated);


  float margin =
    abs(step) * 0.7f;


  float minimum =
    min(CAL_POS_1_MM, CAL_POS_23_MM)
    - margin;


  float maximum =
    max(CAL_POS_1_MM, CAL_POS_23_MM)
    + margin;


  if (
    distance < minimum ||
    distance > maximum
  ) {
    return -1;
  }


  return constrain(
    member,
    1,
    MEMBER_COUNT
  );
}


// ============================================================
// ESP-NOW SEND
// ============================================================

void sendCurrentMember()
{
  if (
    confirmedPosition < 1 ||
    confirmedPosition > MEMBER_COUNT
  ) {
    return;
  }


  RadioPacket packet = {};


  packet.magic =
    PACKET_MAGIC;

  packet.radioId =
    RADIO_ID;

  // 디버그에서는 항상 태그 활성 상태
  packet.active = 1;

  packet.member =
    confirmedPosition;

  packet.uidLength = 0;


  esp_now_send(
    broadcastAddress,
    (uint8_t*)&packet,
    sizeof(packet)
  );
}


// ============================================================
// POSITION
// ============================================================

void updatePosition(int newPosition)
{
  if (
    newPosition < 1 ||
    newPosition > MEMBER_COUNT
  ) {
    return;
  }


  // 후보가 바뀜
  if (
    newPosition != candidatePosition
  ) {

    candidatePosition =
      newPosition;

    candidateSince =
      millis();

    return;
  }


  // 같은 후보가 일정 시간 유지됨
  if (
    newPosition != confirmedPosition &&
    millis() - candidateSince
      >= POSITION_STABLE_MS
  ) {

    int oldPosition =
      confirmedPosition;


    confirmedPosition =
      newPosition;


    Serial.print("MEMBER ");

    Serial.print(oldPosition);

    Serial.print(" -> ");

    Serial.println(
      confirmedPosition
    );


    // 위치가 바뀐 즉시 중앙으로 전송
    sendCurrentMember();


    lastHeartbeat =
      millis();
  }
}


// ============================================================
// SLIDER
// ============================================================

void processSlider()
{
  if (
    millis() - lastRangeRead
      < RANGE_INTERVAL_MS
  ) {
    return;
  }


  lastRangeRead =
    millis();


  uint16_t distance =
    laser.readRangeContinuousMillimeters();


  if (
    laser.timeoutOccurred()
  ) {

    Serial.println(
      "[VL53] TIMEOUT"
    );

    return;
  }


  if (
    distance < 10 ||
    distance > 1000
  ) {
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


  // 상태 확인
  static uint32_t lastPrint = 0;


  if (
    millis() - lastPrint >= 200
  ) {

    lastPrint =
      millis();


    Serial.print("DIST=");

    Serial.print(
      filteredDistance,
      1
    );

    Serial.print("mm  MEMBER=");

    Serial.println(
      confirmedPosition
    );
  }
}


// ============================================================
// HEARTBEAT
// ============================================================

void processHeartbeat()
{
  if (
    confirmedPosition < 1
  ) {
    return;
  }


  if (
    millis() - lastHeartbeat
      < HEARTBEAT_MS
  ) {
    return;
  }


  lastHeartbeat =
    millis();


  sendCurrentMember();
}


// ============================================================
// ESP-NOW
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
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "[ERROR] ESP-NOW INIT"
    );

    return;
  }


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
    esp_now_add_peer(&peer)
    != ESP_OK
  ) {

    Serial.println(
      "[ERROR] ADD PEER"
    );

    return;
  }


  Serial.println(
    "[OK] ESP-NOW"
  );


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


  delay(700);


  Serial.println();

  Serial.println(
    "=== POOL SLIDER DEBUG ==="
  );


  // ----------------------------------------------------------
  // 직선 LED 스트립
  //
  // 큐브가 항상 올라가 있다고 가정하므로 항상 ON
  // ----------------------------------------------------------

  pinMode(
    STRIP_LED_PIN,
    OUTPUT
  );


  digitalWrite(
    STRIP_LED_PIN,
    HIGH
  );


  // ----------------------------------------------------------
  // I2C
  // ----------------------------------------------------------

  Wire.begin(
    I2C_SDA,
    I2C_SCL
  );


  // ----------------------------------------------------------
  // VL53L4CD
  // ----------------------------------------------------------

  laser.setTimeout(
    250
  );


  if (!laser.init()) {

    Serial.println(
      "[ERROR] VL53L4CD"
    );

  } else {

    laser.startContinuous();

    Serial.println(
      "[OK] VL53L4CD"
    );
  }


  // ----------------------------------------------------------
  // ESP-NOW
  // ----------------------------------------------------------

  setupEspNow();


  Serial.println();

  Serial.println(
    "TAG FORCED ON"
  );

  Serial.println(
    "MOVE SLIDER..."
  );
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  processSlider();

  processHeartbeat();
}