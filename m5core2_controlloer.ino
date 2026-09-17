#include <M5Unified.h>
#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_PN532.h>
#include <Preferences.h>

// =====================================================
// NCT IMMERSIVE DEEP
// CORE2 CUBE REGISTRATION CONSOLE
//
// - PN532 NFC
// - ESP-NOW Cube Discover / Register
// - Cube ID 자동 증가
// - 등록정보 NVS 저장
// - 부팅 시 전체 등록목록 Serial 출력
// - 등록 후 ESP-NOW Peer 자동 삭제
// - PN532 부팅 재시도
// =====================================================


// =====================================================
// PN532
// Core2 외부 I2C
// =====================================================

#define I2C_SDA 32
#define I2C_SCL 33

Adafruit_PN532 nfc(-1, -1, &Wire);


// =====================================================
// NVS
// =====================================================

Preferences prefs;


// =====================================================
// ESP-NOW 명령
// Cube 펌웨어와 반드시 동일해야 함
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_ENTER_OTA      = 5
};


// =====================================================
// ESP-NOW Packet
// Cube 펌웨어와 반드시 동일해야 함
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
// Core2에 저장할 등록 데이터
// =====================================================

struct RegistrationRecord {

  uint32_t cubeID;

  uint8_t mac[6];

  uint8_t uidLength;
  uint8_t uid[7];
};


// =====================================================
// ESP-NOW Broadcast
// =====================================================

uint8_t broadcastAddress[6] = {

  0xFF, 0xFF, 0xFF,
  0xFF, 0xFF, 0xFF
};


// =====================================================
// 현재 등록 대상
// =====================================================

uint8_t cubeMac[6];

bool cubeFound = false;


// =====================================================
// NFC
// =====================================================

uint8_t nfcUid[7];

uint8_t nfcUidLength = 0;

bool nfcFound = false;


// =====================================================
// 다음 Cube ID
// =====================================================

uint32_t nextCubeID = 1;


// =====================================================
// ESP-NOW 수신
// =====================================================

Packet pendingPacket;

volatile bool newPacket = false;


// =====================================================
// MAC 문자열
// =====================================================

String macString(const uint8_t *m) {

  char text[18];

  snprintf(
    text,
    sizeof(text),

    "%02X:%02X:%02X:%02X:%02X:%02X",

    m[0],
    m[1],
    m[2],
    m[3],
    m[4],
    m[5]
  );

  return String(text);
}


// =====================================================
// NFC UID 문자열
// =====================================================

String uidString() {

  String s = "";

  for (int i = 0; i < nfcUidLength; i++) {

    if (nfcUid[i] < 0x10) {
      s += "0";
    }

    s += String(
      nfcUid[i],
      HEX
    );

    if (i < nfcUidLength - 1) {

      s += ":";
    }
  }

  s.toUpperCase();

  return s;
}


// =====================================================
// 화면
// =====================================================

void drawScreen(String status = "") {

  M5.Display.fillScreen(BLACK);

  M5.Display.setTextSize(2);


  // ---------------------------------------------------
  // 제목
  // ---------------------------------------------------

  M5.Display.setTextColor(CYAN);

  M5.Display.setCursor(10, 8);

  M5.Display.printf(
    "CUBE REGISTER #%03lu",
    (unsigned long)nextCubeID
  );


  // ---------------------------------------------------
  // MAC
  // ---------------------------------------------------

  M5.Display.setTextColor(WHITE);

  M5.Display.setCursor(10, 45);

  M5.Display.println("MAC:");


  M5.Display.setCursor(10, 68);


  if (cubeFound) {

    M5.Display.setTextColor(GREEN);

    M5.Display.println(
      macString(cubeMac)
    );

  } else {

    M5.Display.setTextColor(RED);

    M5.Display.println(
      "NOT FOUND"
    );
  }


  // ---------------------------------------------------
  // NFC
  // ---------------------------------------------------

  M5.Display.setTextColor(WHITE);

  M5.Display.setCursor(10, 105);

  M5.Display.println("NFC:");


  M5.Display.setCursor(10, 128);


  if (nfcFound) {

    M5.Display.setTextColor(YELLOW);

    M5.Display.println(
      uidString()
    );

  } else {

    M5.Display.setTextColor(RED);

    M5.Display.println(
      "NOT READ"
    );
  }


  // ---------------------------------------------------
  // 상태
  // ---------------------------------------------------

  if (status.length()) {

    M5.Display.setTextColor(GREEN);

    M5.Display.setCursor(10, 165);

    M5.Display.println(status);
  }


  // ---------------------------------------------------
  // 버튼
  // ---------------------------------------------------

  M5.Display.setTextColor(WHITE);

  M5.Display.setCursor(8, 215);

  M5.Display.print("[SCAN]");


  M5.Display.setCursor(105, 215);

  M5.Display.print("[RESET]");


  M5.Display.setCursor(215, 215);

  M5.Display.print("[REG]");
}


// =====================================================
// PN532 안정적인 초기화
// =====================================================

bool initPN532() {

  Serial.println();
  Serial.println("Starting PN532...");


  // 기존 I2C 상태 정리
  Wire.end();

  delay(300);


  // Core2 외부 I2C
  Wire.begin(
    I2C_SDA,
    I2C_SCL
  );


  // PN532는 100kHz로 안정적으로 사용
  Wire.setClock(
    100000
  );


  // PN532 전원 안정화 기다림
  delay(1200);


  // 최대 10번 재시도
  for (
    int attempt = 1;
    attempt <= 10;
    attempt++
  ) {

    Serial.printf(
      "PN532 attempt %d / 10\n",
      attempt
    );


    nfc.begin();

    delay(200);


    uint32_t version =
      nfc.getFirmwareVersion();


    if (version) {

      Serial.println(
        "PN532 FOUND"
      );


      Serial.print(
        "PN532 Firmware: "
      );


      Serial.print(
        (version >> 16) & 0xFF,
        HEX
      );


      Serial.print(".");


      Serial.println(
        (version >> 8) & 0xFF,
        HEX
      );


      // NFC Reader 활성화
      nfc.SAMConfig();


      Serial.println(
        "PN532 READY"
      );


      return true;
    }


    Serial.println(
      "PN532 not responding"
    );


    delay(400);
  }


  return false;
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


  if (
    result == ESP_OK
  ) {

    return true;
  }


  Serial.print(
    "PEER ADD FAILED: "
  );


  Serial.println(
    result
  );


  return false;
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


  newPacket = true;
}


// =====================================================
// Cube 검색
// =====================================================

void scanCube() {

  cubeFound = false;


  drawScreen(
    "SCANNING..."
  );


  Packet p = {};


  p.type =
    MSG_DISCOVER;


  esp_err_t result =
    esp_now_send(
      broadcastAddress,
      (uint8_t *)&p,
      sizeof(p)
    );


  if (
    result != ESP_OK
  ) {

    Serial.println(
      "DISCOVER SEND FAILED"
    );


    drawScreen(
      "SCAN FAILED"
    );
  }
}


// =====================================================
// Cube 등록 명령
// =====================================================

void registerCube() {

  if (!cubeFound) {

    drawScreen(
      "NO CUBE"
    );

    return;
  }


  if (!nfcFound) {

    drawScreen(
      "NO NFC"
    );

    return;
  }


  if (!addPeer(cubeMac)) {

    drawScreen(
      "PEER ERROR"
    );

    return;
  }


  Packet p = {};


  p.type =
    MSG_REGISTER;


  p.cubeID =
    nextCubeID;


  p.uidLength =
    nfcUidLength;


  memcpy(
    p.uid,
    nfcUid,
    nfcUidLength
  );


  esp_err_t result =
    esp_now_send(
      cubeMac,
      (uint8_t *)&p,
      sizeof(p)
    );


  if (
    result == ESP_OK
  ) {

    drawScreen(
      "REGISTER SENT"
    );

  } else {

    Serial.print(
      "REGISTER SEND ERROR: "
    );


    Serial.println(
      result
    );


    drawScreen(
      "SEND FAILED"
    );
  }
}


// =====================================================
// 등록정보 Core2 NVS 저장
// =====================================================

void saveRegistrationRecord() {

  RegistrationRecord record = {};


  record.cubeID =
    nextCubeID;


  memcpy(
    record.mac,
    cubeMac,
    6
  );


  record.uidLength =
    nfcUidLength;


  memcpy(
    record.uid,
    nfcUid,
    nfcUidLength
  );


  char key[10];


  snprintf(
    key,
    sizeof(key),

    "r%03lu",

    (unsigned long)nextCubeID
  );


  prefs.putBytes(
    key,
    &record,
    sizeof(record)
  );


  Serial.println();

  Serial.println(
    "================================"
  );


  Serial.printf(
    "REGISTERED CUBE #%03lu\n",
    (unsigned long)nextCubeID
  );


  Serial.print(
    "MAC : "
  );


  Serial.println(
    macString(cubeMac)
  );


  Serial.print(
    "NFC : "
  );


  Serial.println(
    uidString()
  );


  Serial.println(
    "================================"
  );
}


// =====================================================
// 저장된 전체 Cube 목록 출력
//
// Excel에 그대로 붙여넣기 가능
// =====================================================

void printAllRegistrations() {

  Serial.println();
  Serial.println();

  Serial.println(
    "=========================================="
  );


  Serial.println(
    "NCT CUBE REGISTRATION LIST"
  );


  Serial.println(
    "CubeID,MAC,NFC"
  );


  uint32_t savedNextID =
    prefs.getUInt(
      "nextID",
      1
    );


  int count = 0;


  for (
    uint32_t id = 1;
    id < savedNextID;
    id++
  ) {

    char key[10];


    snprintf(
      key,
      sizeof(key),

      "r%03lu",

      (unsigned long)id
    );


    if (
      !prefs.isKey(key)
    ) {

      continue;
    }


    RegistrationRecord record = {};


    size_t len =
      prefs.getBytes(
        key,
        &record,
        sizeof(record)
      );


    if (
      len != sizeof(record)
    ) {

      continue;
    }


    // Cube ID
    Serial.printf(
      "%03lu,",
      (unsigned long)record.cubeID
    );


    // MAC
    for (
      int i = 0;
      i < 6;
      i++
    ) {

      if (
        record.mac[i] < 0x10
      ) {

        Serial.print("0");
      }


      Serial.print(
        record.mac[i],
        HEX
      );


      if (
        i < 5
      ) {

        Serial.print(":");
      }
    }


    Serial.print(",");


    // NFC
    for (
      int i = 0;
      i < record.uidLength;
      i++
    ) {

      if (
        record.uid[i] < 0x10
      ) {

        Serial.print("0");
      }


      Serial.print(
        record.uid[i],
        HEX
      );


      if (
        i <
        record.uidLength - 1
      ) {

        Serial.print(":");
      }
    }


    Serial.println();


    count++;
  }


  Serial.println(
    "------------------------------------------"
  );


  Serial.print(
    "TOTAL REGISTERED: "
  );


  Serial.println(
    count
  );


  Serial.print(
    "NEXT CUBE ID: "
  );


  Serial.println(
    savedNextID
  );


  Serial.println(
    "=========================================="
  );


  Serial.println();
}


// =====================================================
// NFC 읽기
// =====================================================

void checkNfc() {

  uint8_t uid[7];

  uint8_t len;


  bool ok =
    nfc.readPassiveTargetID(
      PN532_MIFARE_ISO14443A,
      uid,
      &len,
      20
    );


  if (
    !ok
  ) {

    return;
  }


  // UID 길이 이상 방지
  if (
    len == 0 ||
    len > 7
  ) {

    return;
  }


  bool changed =

    !nfcFound ||

    len != nfcUidLength ||

    memcmp(
      uid,
      nfcUid,
      len
    ) != 0;


  if (
    !changed
  ) {

    return;
  }


  nfcUidLength =
    len;


  memcpy(
    nfcUid,
    uid,
    len
  );


  nfcFound =
    true;


  Serial.print(
    "NFC UID: "
  );


  Serial.println(
    uidString()
  );


  drawScreen();
}


// =====================================================
// 등록기 전체 초기화
//
// B 버튼 5초
//
// ★ 주의
// Core2에 저장된 등록목록 전체 삭제
// =====================================================

void factoryResetRegistration() {

  M5.Display.fillScreen(
    RED
  );


  M5.Display.setTextColor(
    WHITE
  );


  M5.Display.setTextSize(
    2
  );


  M5.Display.setCursor(
    25,
    80
  );


  M5.Display.println(
    "RESET REGISTRY"
  );


  M5.Display.setCursor(
    25,
    115
  );


  M5.Display.println(
    "START FROM #001"
  );


  prefs.clear();


  nextCubeID =
    1;


  prefs.putUInt(
    "nextID",
    nextCubeID
  );


  cubeFound =
    false;


  nfcFound =
    false;


  nfcUidLength =
    0;


  Serial.println(
    "REGISTRATION DATABASE RESET"
  );


  delay(
    1500
  );


  drawScreen(
    "RESET COMPLETE"
  );
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  // ---------------------------------------------------
  // Core2 시작
  // ---------------------------------------------------

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


  // ===================================================
  // NVS
  // ===================================================

  prefs.begin(
    "register",
    false
  );


  nextCubeID =
    prefs.getUInt(
      "nextID",
      1
    );


  // ===================================================
  // 화면 초기 표시
  // ===================================================

  M5.Display.fillScreen(
    BLACK
  );


  M5.Display.setTextColor(
    WHITE
  );


  M5.Display.setTextSize(
    2
  );


  M5.Display.setCursor(
    20,
    80
  );


  M5.Display.println(
    "Starting PN532..."
  );


  // ===================================================
  // PN532
  // ===================================================

  bool pn532OK =
    initPN532();


  if (
    !pn532OK
  ) {

    M5.Display.fillScreen(
      BLACK
    );


    M5.Display.setTextColor(
      RED
    );


    M5.Display.setTextSize(
      2
    );


    M5.Display.setCursor(
      20,
      70
    );


    M5.Display.println(
      "PN532 ERROR"
    );


    M5.Display.setTextColor(
      WHITE
    );


    M5.Display.setCursor(
      20,
      110
    );


    M5.Display.println(
      "Check wiring"
    );


    Serial.println();
    Serial.println(
      "PN532 FAILED AFTER 10 ATTEMPTS"
    );


    while (true) {

      M5.update();

      delay(100);
    }
  }


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
    esp_now_init()
    != ESP_OK
  ) {

    M5.Display.fillScreen(
      BLACK
    );


    M5.Display.setTextColor(
      RED
    );


    M5.Display.setTextSize(
      2
    );


    M5.Display.setCursor(
      20,
      80
    );


    M5.Display.println(
      "ESP-NOW ERROR"
    );


    while (true) {

      delay(100);
    }
  }


  esp_now_register_recv_cb(
    onDataRecv
  );


  // Broadcast Peer
  addPeer(
    broadcastAddress
  );


  // ===================================================
  // 정상 화면
  // ===================================================

  drawScreen();


  Serial.println();
  Serial.println(
    "Core2 registration console READY"
  );


  Serial.print(
    "Next Cube ID: "
  );


  Serial.println(
    nextCubeID
  );


  // ===================================================
  // 저장된 목록 자동 출력
  // ===================================================

  printAllRegistrations();
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  M5.update();


  // ===================================================
  // ESP-NOW 응답
  // ===================================================

  if (
    newPacket
  ) {

    newPacket =
      false;


    // -------------------------------------------------
    // Cube 발견
    // -------------------------------------------------

    if (
      pendingPacket.type ==
      MSG_DISCOVER_REPLY
    ) {

      memcpy(
        cubeMac,
        pendingPacket.mac,
        6
      );


      cubeFound =
        true;


      Serial.print(
        "CUBE FOUND: "
      );


      Serial.println(
        macString(cubeMac)
      );


      drawScreen(
        "CUBE FOUND"
      );
    }


    // -------------------------------------------------
    // 등록 완료 ACK
    // -------------------------------------------------

    if (
      pendingPacket.type ==
      MSG_REGISTER_ACK &&

      pendingPacket.success &&

      pendingPacket.cubeID ==
      nextCubeID
    ) {

      // Core2에도 저장
      saveRegistrationRecord();


      drawScreen(
        "REGISTERED!"
      );


      // ===============================================
      // 현재 Cube Peer 제거
      //
      // ESP-NOW 20 Peer 한계 방지
      // ===============================================

      if (
        esp_now_is_peer_exist(
          cubeMac
        )
      ) {

        esp_now_del_peer(
          cubeMac
        );
      }


      // ===============================================
      // 다음 Cube ID
      // ===============================================

      nextCubeID++;


      prefs.putUInt(
        "nextID",
        nextCubeID
      );


      delay(
        800
      );


      // ===============================================
      // 다음 Cube 등록 준비
      // ===============================================

      cubeFound =
        false;


      nfcFound =
        false;


      nfcUidLength =
        0;


      drawScreen();
    }
  }


  // ===================================================
  // NFC 확인
  // ===================================================

  checkNfc();


  // ===================================================
  // A = SCAN
  // ===================================================

  if (
    M5.BtnA.wasPressed()
  ) {

    scanCube();
  }


  // ===================================================
  // C = REGISTER
  // ===================================================

  if (
    M5.BtnC.wasPressed()
  ) {

    registerCube();
  }


  // ===================================================
  // B = 5초 → 등록 DB 전체 초기화
  // ===================================================

  if (
    M5.BtnB.pressedFor(
      5000
    )
  ) {

    factoryResetRegistration();


    while (
      M5.BtnB.isPressed()
    ) {

      M5.update();

      delay(20);
    }
  }


  delay(
    5
  );
}