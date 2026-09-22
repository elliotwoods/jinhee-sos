/* Neocore v1.7.0-USB.1. Derived from v1.4.1-USB.2 (2026-09-17 v1.4.1-STABLE-TEST lineage).
 * XIAO ESP32-C3 / D10 / eight WS2812 LEDs. Firmware updates over USB only.
 * ESP-NOW fixed channel 2; original registration and SHOW_START behavior preserved.
 *
 * v1.5.0: the main show is data (NctShow library). The compiled-in DefaultShow.h renders
 * the v1.4.1 timeline exactly; a newer show can be sent over ESP-NOW (SHOW_ANNOUNCE/CHUNK)
 * and is kept in NVS namespace "show". SHOW_TIMECODE lets a ready cube that missed
 * SHOW_START join the running show and corrects drift above 100 ms. Old controllers that
 * never send timecode work exactly as before.
 *
 * v1.6.0: fanning. A fade/blink/pulse/cycle cue may offset each cube by its registered number
 * (sequential steps or a fixed scatter), so one show ripples across the cubes. v1.5.0 refuses
 * fanned images (the byte was reserved) and keeps its current show.
 *
 * v1.7.0: live authoring. SHOW_LIVE (0x55), broadcast by the show editor about 20 times a
 * second, lists registered cube numbers and a colour each. A registered cube that finds its
 * number shows that colour for the frame's lease (1..2000 ms); when the lease lapses without a
 * newer frame it restores exactly the colour it showed before live mode began (zone colour,
 * idle, or off after a show end). A cube playing a show, or unregistered, ignores SHOW_LIVE.
 * currentZone is never changed; SET_ZONE, REGISTER, SHOW_START or a timecode join ends live
 * mode and the new command wins. Older cubes drop the frame (unknown type).
 */
#include <WiFi.h>
#include <esp_now.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>
#include <esp_system.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <NctShowProtocol.h>
#include "DefaultShow.h"

#define FW_VERSION "v1.7.0-USB.1"

// A received NctShow frame, handed from the Wi-Fi task to loop(). Declared here, before
// the prototypes the Arduino builder generates for functions that take it.
// data holds the largest accepted frame: a full SHOW_LIVE (247 bytes) exceeds a SHOW_CHUNK (211).
constexpr size_t SHOW_FRAME_MAX =
  sizeof(nctshow::ShowChunk) > nctshow::liveLength(nctshow::LIVE_MAX_ENTRIES)
    ? sizeof(nctshow::ShowChunk)
    : nctshow::liveLength(nctshow::LIVE_MAX_ENTRIES);
static_assert(SHOW_FRAME_MAX <= 255, "ShowFrame.len is one byte");
struct ShowFrame {
  uint8_t src[6];
  uint8_t broadcast;
  uint8_t len;
  uint8_t data[SHOW_FRAME_MAX];
};

void setShowCube(uint32_t cube);  // defined with the show player, used by registration
void endLive(bool restore);       // defined with the live frames, used by every new command


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
// =====================================================

enum MessageType : uint8_t {

  MSG_DISCOVER       = 1,
  MSG_DISCOVER_REPLY = 2,

  MSG_REGISTER       = 3,
  MSG_REGISTER_ACK   = 4,

  MSG_RESERVED_5      = 5,

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
// =====================================================




// =====================================================
// MAIN SHOW 상태
// =====================================================

bool showRunning = false;

uint32_t showStartMillis = 0;

uint32_t lastShowId = 0;

uint32_t lastShowFrameMillis = 0;




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

// What the LEDs show now (after limitLed); live mode restores it.
uint8_t shownR = 0, shownG = 0, shownB = 0;

void showColor(
  uint8_t r,
  uint8_t g,
  uint8_t b
) {

  r = limitLed(r);
  g = limitLed(g);
  b = limitLed(b);

  shownR = r;
  shownG = g;
  shownB = b;

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

  shownR = shownG = shownB = 0;

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

  // Fanned cues offset each cube by its number.
  setShowCube(myCubeID);

  Serial.print(
    "REGISTERED Cube #"
  );

  Serial.println(
    myCubeID
  );
}


// =====================================================
// =====================================================

// =====================================================
// ★ MAIN SHOW DATA (v1.5.0)
//
// The show is data: an NctShow image (NctShowEngine.h), either the one
// published and stored in NVS namespace "show" or the compiled-in
// DEFAULT_SHOW (DefaultShow.h, generated from shows/mainshow.json and
// identical to the v1.4.1 hard-coded timeline).
// =====================================================

uint8_t showImage[nctshow::MAX_IMAGE];
uint16_t showImageSize = 0;
uint32_t showVersion = 0;  // 0 = compiled-in
uint32_t showCrc = 0;
uint8_t showSource = nctshow::SOURCE_BUILTIN;
nctshow::Player showPlayer;

void useBuiltinShow() {
  memcpy(showImage, DEFAULT_SHOW, DEFAULT_SHOW_SIZE);
  showImageSize = DEFAULT_SHOW_SIZE;
  showVersion = 0;
  showCrc = DEFAULT_SHOW_CRC;
  showSource = nctshow::SOURCE_BUILTIN;
  showPlayer.begin(showImage, isRegistered ? myCubeID : 0);
}

// Anything missing, torn or invalid in NVS falls back to the compiled-in show.
void loadStoredShow() {
  prefs.begin("show", true);
  size_t size = prefs.getBytesLength("img");
  uint32_t version = prefs.getUInt("ver", 0);
  uint32_t crc = prefs.getUInt("crc", 0);
  bool ok = version > 0 && size > 0 && size <= sizeof(showImage) &&
            prefs.getBytes("img", showImage, size) == size;
  prefs.end();
  if (ok && nctshow::crc32(showImage, size) == crc && nctshow::validImage(showImage, size)) {
    showImageSize = size;
    showVersion = version;
    showCrc = crc;
    showSource = nctshow::SOURCE_NVS;
    showPlayer.begin(showImage, isRegistered ? myCubeID : 0);
    return;
  }
  useBuiltinShow();
}

void setShowCube(uint32_t cube) {
  showPlayer.setCube(cube);
}

uint32_t showRandom(uint32_t lo, uint32_t hiExclusive, void *) {
  return random(lo, hiExclusive);
}

// Starts (or restarts) the show so that its clock reads tMs now.
void startMainShowAt(
  uint32_t showId,
  uint32_t tMs
) {
  endLive(false);  // the show wins; its first frame is rendered below
  lastShowId = showId;
  showRunning = true;
  showStartMillis = millis() - tMs;
  lastShowFrameMillis = 0;
  showPlayer.restart();
  currentZone = ZONE_MAINSHOW;

  nctshow::Rgb c;
  if (showPlayer.render(tMs, showRandom, nullptr, c)) {
    showColor(c.r, c.g, c.b);
  }
}

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

  startMainShowAt(showId, 0);

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
// ★ MAIN SHOW 타임라인
//
// 기준:
// SHOW_START = 영상 00:00
//
// 종료:
// the show image's length (04:58 = 298000 ms for the default)
// =====================================================

void endMainShow() {

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

  nctshow::Rgb c;

  if (showPlayer.render(t, showRandom, nullptr, c)) {
    showColor(c.r, c.g, c.b);
    return;
  }

  // 쇼 끝: 2부에서는 네오코어 OFF
  endMainShow();
}


// =====================================================
// ★ SHOW FRAMES (NctShowProtocol.h)
//
// The Wi-Fi task only copies frames into showQueue; loop() handles them.
// Legacy 24-byte Packets keep their own path (pendingPacket).
// =====================================================

QueueHandle_t showQueue = nullptr;
// SHOW_LIVE frames bypass showQueue: a one-deep queue the Wi-Fi task overwrites, so a newer
// live frame supersedes an unread older one and ~20 Hz live traffic never crowds out chunks.
QueueHandle_t liveQueue = nullptr;

// Wireless show update: staged in RAM, committed to NVS when complete.
uint8_t stagingImage[nctshow::MAX_IMAGE];
uint32_t stagingVersion = 0;  // 0 = not staging
uint32_t stagingCrc = 0;
uint16_t stagingLength = 0;
uint16_t stagingTotal = 0;
uint16_t stagingReceived = 0;
uint32_t stagingMask = 0;
uint32_t stagingActivity = 0;
bool pendingCommit = false;   // complete and valid, waiting for the show to end
uint8_t showUpdateError = nctshow::ERR_NONE;
uint8_t announcerMac[6] = {0};
bool haveAnnouncer = false;

static_assert(nctshow::MAX_CHUNKS <= 32, "staging mask");

// Replies to SHOW_QUERY, delayed by a random jitter so ~140 cubes do not collide.
struct PendingReply {
  bool used;
  uint8_t mac[6];
  uint32_t due;
  uint32_t nonce;
};

PendingReply pendingReplies[4];

void sendShowStatus(
  const uint8_t *destination,
  uint32_t nonce
) {
  nctshow::ShowStatus s = {};
  nctshow::fillHeader(s.h, nctshow::SHOW_STATUS);
  s.nonce = nonce;
  s.version = showVersion;
  s.crc = showCrc;
  s.length = showImageSize;
  s.stagingVersion = stagingVersion;
  s.stagingChunks = stagingReceived;
  s.stagingTotal = stagingTotal;
  s.cubeId = isRegistered ? myCubeID : 0;
  s.source = showSource;
  s.lastError = showUpdateError;
  s.zone = currentZone;
  s.showRunning = showRunning ? 1 : 0;
  s.pendingCommit = pendingCommit ? 1 : 0;
  s.uptimeS = millis() / 1000;
  strncpy(s.fw, FW_VERSION, sizeof(s.fw));
  addPeer(destination);
  esp_now_send(destination, (uint8_t *)&s, sizeof(s));
}

void scheduleShowStatus(
  const uint8_t *destination,
  uint32_t nonce,
  uint16_t jitterMs
) {
  if (jitterMs > nctshow::MAX_REPLY_JITTER_MS) {
    jitterMs = nctshow::MAX_REPLY_JITTER_MS;
  }
  for (PendingReply &r : pendingReplies) {
    if (r.used && !memcmp(r.mac, destination, 6)) {
      r.nonce = nonce;  // one pending reply per querier
      return;
    }
  }
  for (PendingReply &r : pendingReplies) {
    if (!r.used) {
      r.used = true;
      memcpy(r.mac, destination, 6);
      r.nonce = nonce;
      r.due = millis() + random(0, uint32_t(jitterMs) + 1);
      return;
    }
  }
}

void stopStaging() {
  stagingVersion = 0;
  stagingTotal = 0;
  stagingReceived = 0;
  stagingMask = 0;
  pendingCommit = false;
}

void commitStagedShow() {
  pendingCommit = false;
  prefs.begin("show", false);
  // Image first, then version and CRC: a torn write leaves a CRC mismatch,
  // and loadStoredShow() falls back to the compiled-in show.
  prefs.putUInt("ver", 0);
  size_t written = prefs.putBytes("img", stagingImage, stagingLength);
  prefs.putUInt("crc", stagingCrc);
  prefs.putUInt("ver", stagingVersion);
  prefs.end();

  uint32_t version = stagingVersion;
  stopStaging();
  loadStoredShow();

  if (written != stagingLength || showVersion != version) {
    showUpdateError = nctshow::ERR_COMMIT;
    Serial.println("SHOW UPDATE: NVS WRITE FAILED");
  } else {
    showUpdateError = nctshow::ERR_NONE;
    Serial.print("SHOW UPDATE: v");
    Serial.println(showVersion);
  }

  if (haveAnnouncer) {
    sendShowStatus(announcerMac, 0);
  }
}

void finishStaging() {
  if (nctshow::crc32(stagingImage, stagingLength) != stagingCrc) {
    showUpdateError = nctshow::ERR_CRC;
    stopStaging();
    return;
  }
  if (!nctshow::validImage(stagingImage, stagingLength)) {
    showUpdateError = nctshow::ERR_INVALID;
    stopStaging();
    return;
  }
  pendingCommit = true;
  if (!showRunning) {
    commitStagedShow();
  } else {
    Serial.println("SHOW UPDATE: WAITING FOR SHOW END");
  }
}

void onShowAnnounce(
  const ShowFrame &f
) {
  nctshow::ShowAnnounce a;
  memcpy(&a, f.data, sizeof(a));
  memcpy(announcerMac, f.src, 6);
  haveAnnouncer = true;

  bool force = (a.flags & nctshow::ANNOUNCE_FORCE) && !f.broadcast;
  uint16_t chunks = (a.length + nctshow::CHUNK_DATA - 1) / nctshow::CHUNK_DATA;
  if (a.version == 0 || a.length == 0 || a.length > sizeof(stagingImage) ||
      a.chunkSize != nctshow::CHUNK_DATA || a.chunkCount != chunks) {
    showUpdateError = nctshow::ERR_ANNOUNCE;
    return;
  }
  if (a.version == showVersion && a.crc32 == showCrc) {
    return;  // already current
  }
  if (a.version <= showVersion && !force) {
    return;
  }
  if (stagingVersion == a.version && stagingCrc == a.crc32 && stagingLength == a.length) {
    stagingActivity = millis();  // same update in progress (or complete and pending)
    return;
  }
  if (pendingCommit && a.version < stagingVersion && !force) {
    return;
  }
  stopStaging();
  stagingVersion = a.version;
  stagingCrc = a.crc32;
  stagingLength = a.length;
  stagingTotal = chunks;
  stagingActivity = millis();
  memset(stagingImage, 0, sizeof(stagingImage));
}

void onShowChunk(
  const ShowFrame &f
) {
  nctshow::ShowChunk c;
  memcpy(&c, f.data, sizeof(c));
  if (!stagingVersion || pendingCommit || c.version != stagingVersion || c.index >= stagingTotal) {
    return;
  }
  uint16_t expected = c.index + 1 < stagingTotal
                        ? nctshow::CHUNK_DATA
                        : stagingLength - uint16_t(c.index) * nctshow::CHUNK_DATA;
  if (c.n != expected) {
    return;
  }
  stagingActivity = millis();
  if (stagingMask & (1UL << c.index)) {
    return;
  }
  stagingMask |= 1UL << c.index;
  stagingReceived++;
  memcpy(stagingImage + uint32_t(c.index) * nctshow::CHUNK_DATA, c.data, c.n);
  if (stagingReceived == stagingTotal) {
    finishStaging();
  }
}

// Fallback start and drift correction for a ready cube; SHOW_START is unchanged.
void onShowTimecode(
  const ShowFrame &f
) {
  nctshow::ShowTimecode tc;
  memcpy(&tc, f.data, sizeof(tc));
  if (tc.showId == 0 || tc.tMs >= showPlayer.lengthMs()) {
    return;
  }
  if (showRunning && tc.showId == lastShowId) {
    uint32_t elapsed = millis() - showStartMillis;
    uint32_t drift = elapsed > tc.tMs ? elapsed - tc.tMs : tc.tMs - elapsed;
    if (drift > nctshow::DRIFT_LIMIT_MS) {
      showStartMillis = millis() - tc.tMs;
      Serial.print("TIMECODE RESYNC / DRIFT MS = ");
      Serial.println(drift);
    }
    return;
  }
  if (currentZone != ZONE_MAINSHOW) {
    return;  // not ready (or a show on this cube just ended and dropped eligibility)
  }
  startMainShowAt(tc.showId, tc.tMs);
  Serial.print("MAIN SHOW JOIN BY TIMECODE / ID = ");
  Serial.print(tc.showId);
  Serial.print(" / T = ");
  Serial.println(tc.tMs);
}

// ★ LIVE AUTHORING (v1.7.0)
//
// While live, the LEDs show the editor's colour for this cube; liveRestore is what they showed
// when live mode began. currentZone is never touched.
bool liveActive = false;
uint32_t liveUntil = 0;
uint8_t liveRestore[3] = {0, 0, 0};

void endLive(
  bool restore
) {
  if (!liveActive) {
    return;
  }
  liveActive = false;
  if (restore) {
    showColor(liveRestore[0], liveRestore[1], liveRestore[2]);
  }
  Serial.println(restore ? "LIVE END" : "LIVE END / NEW COMMAND");
}

void onShowLive(
  const ShowFrame &f
) {
  // Never hijack a real show; an unregistered cube has no number to match.
  if (showRunning || !isRegistered || myCubeID == 0 || myCubeID > 0xFFFF) {
    return;
  }
  nctshow::ShowLiveHeader h;
  memcpy(&h, f.data, sizeof(h));
  for (uint8_t i = 0; i < h.n; i++) {
    nctshow::LiveEntry e;
    memcpy(&e, f.data + nctshow::liveLength(i), sizeof(e));
    if (e.cube != myCubeID) {
      continue;
    }
    uint16_t lease = h.leaseMs;
    if (lease < 1) {
      lease = 1;
    }
    if (lease > nctshow::LIVE_LEASE_MAX_MS) {
      lease = nctshow::LIVE_LEASE_MAX_MS;
    }
    if (!liveActive) {
      liveRestore[0] = shownR;
      liveRestore[1] = shownG;
      liveRestore[2] = shownB;
      liveActive = true;
      Serial.println("LIVE START");
    }
    liveUntil = millis() + lease;
    showColor(e.r, e.g, e.b);
    return;  // the first entry for this number wins
  }
  // Not listed in this frame (the editor may split >48 cubes across frames): the lease runs on.
}

void handleLive() {
  ShowFrame f;
  if (liveQueue && xQueueReceive(liveQueue, &f, 0) == pdTRUE &&
      nctshow::frameType(f.data, f.len) == nctshow::SHOW_LIVE) {
    onShowLive(f);
  }
  if (liveActive && int32_t(millis() - liveUntil) >= 0) {
    endLive(true);
  }
}

void handleShowFrames() {
  ShowFrame f;
  while (showQueue && xQueueReceive(showQueue, &f, 0) == pdTRUE) {
    switch (nctshow::frameType(f.data, f.len)) {
      case nctshow::SHOW_ANNOUNCE: onShowAnnounce(f); break;
      case nctshow::SHOW_CHUNK: onShowChunk(f); break;
      case nctshow::SHOW_QUERY: {
        nctshow::ShowQuery q;
        memcpy(&q, f.data, sizeof(q));
        scheduleShowStatus(f.src, q.nonce, q.jitterMs);
        break;
      }
      case nctshow::SHOW_TIMECODE: onShowTimecode(f); break;
      default: break;
    }
  }

  uint32_t now = millis();
  for (PendingReply &r : pendingReplies) {
    if (r.used && int32_t(now - r.due) >= 0) {
      r.used = false;
      sendShowStatus(r.mac, r.nonce);
    }
  }

  if (stagingVersion && !pendingCommit && now - stagingActivity > nctshow::STAGING_TIMEOUT_MS) {
    showUpdateError = nctshow::ERR_TIMEOUT;
    stopStaging();
  }

  if (pendingCommit && !showRunning) {
    commitStagedShow();
  }

  // After the show frames: a timecode join in this pass has already set showRunning.
  handleLive();
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

    // NctShow frames (never 24 bytes) go to loop() through showQueue (SHOW_LIVE: liveQueue).
    uint8_t type = 0;
    if (
      showQueue &&
      liveQueue &&
      len <= (int)sizeof(ShowFrame::data) &&
      (type = nctshow::frameType(data, len))
    ) {

      ShowFrame f;
      memcpy(f.src, info->src_addr, 6);
      f.broadcast = info->des_addr && (info->des_addr[0] & 1);
      f.len = (uint8_t)len;
      memcpy(f.data, data, len);
      if (type == nctshow::SHOW_LIVE) {
        xQueueOverwrite(liveQueue, &f);
      } else {
        xQueueSend(showQueue, &f, 0);
      }
    }

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

// "SHOW: v=<version> crc=<hex> src=builtin|nvs" (version 0 = compiled-in show)
void printShowLine() {
  char line[64];
  snprintf(line, sizeof(line), "SHOW: v=%lu crc=%08lx src=%s", (unsigned long)showVersion,
           (unsigned long)showCrc, showSource == nctshow::SOURCE_NVS ? "nvs" : "builtin");
  Serial.println(line);
}

bool usbReady = false;

void setup() {

  Serial.begin(115200);

  delay(300);


  // ===================================================
  // LED
  // ===================================================

  pixels.begin();

  // USB.2 visual startup signature: three brief white pulses, then normal idle.
  // Runs before ESP-NOW starts so no incoming command is delayed by the cue.
  for (uint8_t pulse = 0; pulse < 3; ++pulse) {
    showColor(30, 30, 30);
    delay(150);
    ledOff();
    delay(150);
  }


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
    "FW: " FW_VERSION
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

  loadStoredShow();


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
  // ESP-NOW는 Wi-Fi 채널이 확정된 뒤 시작한다.
  // ===================================================

  WiFi.setAutoReconnect(false);
  esp_wifi_set_channel(2, WIFI_SECOND_CHAN_NONE);

  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "ESP-NOW INIT ERROR"
    );

    showError();

    return;
  }


  showQueue =
    xQueueCreate(8, sizeof(ShowFrame));

  liveQueue =
    xQueueCreate(1, sizeof(ShowFrame));

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
    FW_VERSION
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

  printShowLine();

  usbReady = true;
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
  if (Serial.available() && Serial.read() == '?' && usbReady) {
    Serial.println("FW: " FW_VERSION);
    Serial.print("Cube MAC: "); Serial.println(WiFi.macAddress());
    Serial.print("ESP-NOW CHANNEL: "); Serial.println(WiFi.channel());
    printShowLine();
    Serial.println("Cube READY");
  }


  // ===================================================
  // ===================================================

  updateMainShowTimeline();

  handleShowFrames();


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

    endLive(false);  // the success blink ends on the idle colour

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

    // Live mode ends; restore first so an unknown zone does not leave the live colour on.
    endLive(true);


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
