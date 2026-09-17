#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// ============================================================
// NCT IMMERSIVE DEEP
// POOL CENTRAL CONTROLLER
// ============================================================


// ------------------------------------------------------------
// I2C
// ------------------------------------------------------------

#define I2C_SDA 8
#define I2C_SCL 9


// ------------------------------------------------------------
// PCA9685
// ------------------------------------------------------------

#define PCA_ADDR_1 0x40
#define PCA_ADDR_2 0x41

#define MODE1_REG 0x00
#define LED0_ON_L 0x06


// ------------------------------------------------------------
// ESP-NOW
// ------------------------------------------------------------

#define ESPNOW_CHANNEL 2  // shared with neocubes, zones (PoolZone radios) and the registry station
#define PACKET_MAGIC 0x4E435450


// ------------------------------------------------------------
// SYSTEM
// ------------------------------------------------------------

#define RADIO_COUNT 6
#define MEMBER_COUNT 23

// 라디오 자체가 죽거나 무선 연결이 끊긴 경우
// heartbeat 150ms 기준으로 충분한 여유
#define RADIO_TIMEOUT_MS 800


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
// RADIO STATE
// ============================================================

struct RadioState {

  bool active;

  uint8_t member;

  uint32_t lastSeen;
};


RadioState radios[
  RADIO_COUNT
];


bool frameState[
  MEMBER_COUNT + 1
];


volatile bool stateDirty =
  false;


// ============================================================
// PCA9685 BASIC
// ============================================================

void writeRegister(
  uint8_t addr,
  uint8_t reg,
  uint8_t value
)
{
  Wire.beginTransmission(
    addr
  );

  Wire.write(
    reg
  );

  Wire.write(
    value
  );

  Wire.endTransmission();
}


// ------------------------------------------------------------

void setChannelON(
  uint8_t addr,
  uint8_t channel
)
{
  Wire.beginTransmission(
    addr
  );

  Wire.write(
    LED0_ON_L +
    4 * channel
  );

  // FULL ON
  Wire.write(0x00);
  Wire.write(0x10);

  Wire.write(0x00);
  Wire.write(0x00);

  Wire.endTransmission();
}


// ------------------------------------------------------------

void setChannelOFF(
  uint8_t addr,
  uint8_t channel
)
{
  Wire.beginTransmission(
    addr
  );

  Wire.write(
    LED0_ON_L +
    4 * channel
  );

  Wire.write(0x00);
  Wire.write(0x00);

  // FULL OFF
  Wire.write(0x00);
  Wire.write(0x10);

  Wire.endTransmission();
}


// ------------------------------------------------------------

void initPCA9685(
  uint8_t addr
)
{
  writeRegister(
    addr,
    MODE1_REG,
    0x20
  );

  delay(10);


  for (
    uint8_t i = 0;
    i < 16;
    i++
  ) {

    setChannelOFF(
      addr,
      i
    );
  }
}


// ============================================================
// MEMBER FRAME
// ============================================================

void setMemberFrame(
  uint8_t member,
  bool on
)
{
  if (
    member < 1 ||
    member > MEMBER_COUNT
  ) {

    return;
  }


  uint8_t addr;
  uint8_t channel;


  // ----------------------------------------------------------
  // MEMBER 1~16
  // ----------------------------------------------------------

  if (member <= 16) {

    addr =
      PCA_ADDR_1;

    channel =
      member - 1;
  }

  // ----------------------------------------------------------
  // MEMBER 17~23
  // ----------------------------------------------------------

  else {

    addr =
      PCA_ADDR_2;

    channel =
      member - 17;
  }


  if (on) {

    setChannelON(
      addr,
      channel
    );

  }
  else {

    setChannelOFF(
      addr,
      channel
    );
  }


  frameState[
    member
  ] = on;


  Serial.print(
    "FRAME "
  );

  Serial.print(
    member
  );

  Serial.println(
    on ? " ON" : " OFF"
  );
}


// ============================================================
// CALCULATE FINAL FRAME STATES
// ============================================================

void refreshFrames()
{
  for (
    uint8_t member = 1;
    member <= MEMBER_COUNT;
    member++
  ) {

    bool shouldBeOn =
      false;


    // 6개 라디오 중
    // 하나라도 이 멤버를 선택하면 ON
    for (
      uint8_t r = 0;
      r < RADIO_COUNT;
      r++
    ) {

      if (
        radios[r].active &&
        radios[r].member ==
          member
      ) {

        shouldBeOn =
          true;

        break;
      }
    }


    // 상태가 실제로 변할 때만 명령
    if (
      frameState[member]
      != shouldBeOn
    ) {

      setMemberFrame(
        member,
        shouldBeOn
      );
    }
  }
}


// ============================================================
// ESP-NOW RECEIVE
// ============================================================

void onDataRecv(
  const esp_now_recv_info_t *info,
  const uint8_t *data,
  int len
)
{
  if (
    len != sizeof(RadioPacket)
  ) {

    return;
  }


  RadioPacket packet;


  memcpy(
    &packet,
    data,
    sizeof(packet)
  );


  if (
    packet.magic !=
    PACKET_MAGIC
  ) {

    return;
  }


  if (
    packet.radioId < 1 ||
    packet.radioId > RADIO_COUNT
  ) {

    return;
  }


  uint8_t index =
    packet.radioId - 1;


  radios[index].lastSeen =
    millis();


  // ----------------------------------------------------------
  // ACTIVE
  // ----------------------------------------------------------

  if (
    packet.active &&
    packet.member >= 1 &&
    packet.member <= MEMBER_COUNT
  ) {

    // 멤버가 실제로 바뀌었을 때 출력
    if (
      !radios[index].active ||
      radios[index].member != packet.member
    ) {

      Serial.print(
        "RADIO "
      );

      Serial.print(
        packet.radioId
      );

      Serial.print(
        " -> MEMBER "
      );

      Serial.println(
        packet.member
      );
    }


    radios[index].active =
      true;

    radios[index].member =
      packet.member;
  }

  // ----------------------------------------------------------
  // RELEASE
  // ----------------------------------------------------------

  else {

    if (
      radios[index].active
    ) {

      Serial.print(
        "RADIO "
      );

      Serial.print(
        packet.radioId
      );

      Serial.println(
        " RELEASE"
      );
    }


    radios[index].active =
      false;

    radios[index].member =
      0;
  }


  stateDirty =
    true;
}


// ============================================================
// RADIO TIMEOUT
// ============================================================

void processRadioTimeout()
{
  bool changed =
    false;


  for (
    uint8_t i = 0;
    i < RADIO_COUNT;
    i++
  ) {

    if (
      radios[i].active &&
      millis() -
      radios[i].lastSeen >
      RADIO_TIMEOUT_MS
    ) {

      Serial.print(
        "RADIO TIMEOUT: "
      );

      Serial.println(
        i + 1
      );


      radios[i].active =
        false;

      radios[i].member =
        0;

      changed =
        true;
    }
  }


  if (changed) {

    stateDirty =
      true;
  }
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
  ) {

    Serial.println(
      "[ERROR] ESP-NOW INIT"
    );

    return;
  }


  esp_now_register_recv_cb(
    onDataRecv
  );


  Serial.println(
    "[OK] ESP-NOW"
  );


  Serial.print(
    "CENTRAL MAC: "
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


  // ----------------------------------------------------------
  // I2C
  // ----------------------------------------------------------

  Wire.begin(
    I2C_SDA,
    I2C_SCL
  );


  // ----------------------------------------------------------
  // PCA9685
  // ----------------------------------------------------------

  initPCA9685(
    PCA_ADDR_1
  );

  initPCA9685(
    PCA_ADDR_2
  );


  // ----------------------------------------------------------
  // RADIO STATE
  // ----------------------------------------------------------

  for (
    int i = 0;
    i < RADIO_COUNT;
    i++
  ) {

    radios[i].active =
      false;

    radios[i].member =
      0;

    radios[i].lastSeen =
      0;
  }


  // ----------------------------------------------------------
  // FRAME STATE
  // ----------------------------------------------------------

  for (
    int i = 1;
    i <= MEMBER_COUNT;
    i++
  ) {

    frameState[i] =
      false;
  }


  // ----------------------------------------------------------
  // ESP-NOW
  // ----------------------------------------------------------

  setupEspNow();


  Serial.println();

  Serial.println(
    "=== POOL CENTRAL READY ==="
  );
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  processRadioTimeout();


  if (stateDirty) {

    stateDirty =
      false;

    refreshFrames();
  }
}