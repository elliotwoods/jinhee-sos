#pragma once
// Cube role: everything that goes to a neocube as a 24-byte Packet.
//
//   - discover / identify / register: the pairing station's state machine, ported as is
//     (pairing_station.ino): three registration attempts two seconds apart, a one-second pause
//     after the cube's acknowledgement so its confirmation blink finishes, identify blinking
//     zone 3/1 every 500 ms, and the host-heartbeat watchdog that returns the target to idle.
//   - set_zone: MSG_SET_ZONE with the zone in Packet.success. Unicast for one cube: the frozen
//     cube firmware checks neither cubeID nor destination, so a broadcast recolours every cube
//     in range, which is why "broadcast" has to be spelled out by the host. Sent three times at
//     0/120/400 ms as the tag plates do (NctTagPlate.h): a cube's mailbox holds one frame and
//     its loop idles on delay(2), so two frames inside one pass leave only the second.
//   - show_start: the Mainshow controller's trigger, MSG_SHOW_START carrying a fresh showId in
//     Packet.cubeID, five sends 30 ms apart, one 3 s lockout. A cube starts its timeline only
//     if it is mainshow-ready (zone 4) and ignores a repeated showId.
//   - show timecode (NctShowProtocol.h, as the Mainshow controller mainshow-1.3.0): while a show
//     runs, SHOW_TIMECODE goes to the start's target once a second, the first right after the
//     burst. A v1.5.0 cube that is ready but missed the start joins; older cubes ignore it. The
//     show length comes from `show_config` (RAM only: the console sends it on connect), 298 s by
//     default; `show_stop` ends the timecode.
#include <string.h>
#include <stdio.h>
#include "GrRadio.h"
#include "GrJson.h"
#include "GrHex.h"
#include <NctShowProtocol.h>

namespace gr {
namespace cube {

enum Mode { IDLE, IDENTIFY, REGISTERING, ACK_PAUSE };
inline const char *const MODE_TEXT[] = {"idle", "identify", "registering", "ack_pause"};

constexpr uint32_t IDENTIFY_BLINK_MS = 500, IDENTIFY_MAX_MS = 60000;
constexpr uint32_t REGISTER_RETRY_MS = 2000, ACK_PAUSE_MS = 1000;
constexpr int REGISTER_ATTEMPTS = 3;
constexpr int ZONE_REPEATS = 3;
constexpr uint32_t ZONE_REPEAT_AT_MS[ZONE_REPEATS] = {0, 120, 400};  // NctTagPlate.h: COLOUR_REPEAT_MS
constexpr int ZONE_JOBS = 8;  // cubes whose colour repeats are still pending
constexpr int SHOW_REPEATS = 5;              // the Core2's burst: 5 sends, 30 ms apart
constexpr uint32_t SHOW_REPEAT_GAP_MS = 30;
constexpr uint32_t LOCKOUT_MS = 3000;        // the Core2's SHOW_LOCK_MS

inline Mode mode = IDLE;
inline bool active = false;  // a target cube is held (identify or registration)
inline uint8_t target[6] = {};
inline Packet registration = {};
inline char operationId[41] = "";
inline uint32_t started = 0, lastBlink = 0, lastAttempt = 0, ackTime = 0, durationMs = 0;
inline int attempts = 0;
inline bool blue = false;

inline uint32_t lastShowId = 0, lastTriggerAt = 0, shows = 0;
inline bool triggered = false;
inline uint8_t showTarget[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
inline uint32_t lastTimecodeAt = 0, timecodes = 0;
inline uint32_t showLengthMs = nctshow::DEFAULT_LENGTH_MS, showVersion = 0, showCrc = 0;

struct ZoneJob { bool valid; uint8_t mac[6]; uint8_t zone; uint8_t sent; uint32_t startedAt; };
inline ZoneJob jobs[ZONE_JOBS] = {};

inline void radioEvent(const uint8_t *mac, uint8_t type, SendResult result) {
  char text[18], fields[96];
  formatMac(mac, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"type\":%u,\"status\":\"%s\"", text, type, SEND_TEXT[result]);
  reply("radio", operationId, fields);
}

// One cube packet, reported to the host as the pairing station reports it: the radio result
// is distinct from a cube application acknowledgement.
inline SendResult sendPacket(const uint8_t *mac, const Packet &packet) {
  SendResult result = sendFrame(mac, &packet, sizeof(packet));
  radioEvent(mac, packet.type, result);
  return result;
}

inline SendResult sendZone(const uint8_t *mac, uint8_t zone) {
  Packet packet = {};
  packet.type = MSG_SET_ZONE;
  packet.success = zone;
  return sendFrame(mac, &packet, sizeof(packet));
}

inline void zoneToTarget(uint8_t value) {
  Packet packet = {};
  packet.type = MSG_SET_ZONE;
  packet.success = value;
  sendPacket(target, packet);
}

// Restore the held cube to idle before the host can start the next operation.
inline void releaseTarget() {
  if (active) zoneToTarget(0);
  active = false;
  mode = IDLE;
}

inline void cancelJobs() { for (ZoneJob &job : jobs) job.valid = false; }

inline void attemptRegistration() {
  attempts++;
  char text[18], fields[64];
  formatMac(target, text);
  snprintf(fields, sizeof(fields), "\"attempt\":%d,\"mac\":\"%s\"", attempts, text);
  reply("attempt", operationId, fields);
  sendPacket(target, registration);
  lastAttempt = millis();
}

inline void registrationResult(bool acknowledged) {
  char text[18], fields[200];
  formatMac(target, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"cube_id\":%lu,\"acknowledged\":%s,\"detail\":\"%s\"", text,
           (unsigned long)registration.cubeID, boolText(acknowledged),
           acknowledged ? "Cube acknowledged; flash persistence not verified" : "No matching acknowledgment after three attempts");
  releaseTarget();
  reply("registered", operationId, fields);
}

// ---- host commands ----

inline void discover(const char *id) {
  if (mode == REGISTERING || mode == ACK_PAUSE) { error(id, "Registration is active"); return; }
  Packet packet = {};
  packet.type = MSG_DISCOVER;
  sendPacket(BROADCAST_MAC, packet);
  reply("discover_sent", id);
}

inline void identify(const char *id, const uint8_t *mac, const char *line) {
  uint32_t duration;
  if (mode != IDLE) { error(id, "Radio busy; stop first"); return; }
  if (!jsonUint(line, "duration_ms", duration)) { error(id, "Invalid duration"); return; }
  if (duration > IDENTIFY_MAX_MS) { error(id, "Duration exceeds 60 seconds"); return; }
  durationMs = duration;
  memcpy(target, mac, 6);
  active = true;
  snprintf(operationId, sizeof(operationId), "%s", id);
  mode = IDENTIFY;
  started = lastBlink = millis();
  blue = false;
  zoneToTarget(1);
  reply("identifying", id);
}

inline void registerCube(const char *id, const uint8_t *mac, const char *line) {
  if (mode == REGISTERING || mode == ACK_PAUSE || (active && memcmp(target, mac, 6))) {
    error(id, "Radio busy with another operation"); return;
  }
  char uid[32] = "";
  uint32_t cubeId = 0;
  Packet packet = {};
  int length = jsonString(line, "uid", uid, sizeof(uid)) ? parseColonHex(uid, packet.uid, 7) : -1;
  if ((length != 4 && length != 7) || !jsonUint(line, "cube_id", cubeId) || cubeId == 0) {
    error(id, "Invalid cube ID or UID (only 4/7-byte tags supported)"); return;
  }
  packet.type = MSG_REGISTER;
  packet.cubeID = cubeId;
  packet.uidLength = uint8_t(length);
  memcpy(target, mac, 6);
  active = true;
  snprintf(operationId, sizeof(operationId), "%s", id);
  registration = packet;
  mode = REGISTERING;
  attempts = 0;
  CubeRx stale;  // a reply to an earlier operation must not count as this cube's acknowledgement
  while (cubeQueue && xQueueReceive(cubeQueue, &stale, 0) == pdTRUE) {}
  attemptRegistration();
}

// `mac` is the six-byte address or the broadcast address; `target` is the host's spelling.
inline void setZone(const char *id, const uint8_t *mac, uint8_t zone) {
  bool broadcast = isBroadcast(mac);
  if (!broadcast && active && !memcmp(target, mac, 6)) { error(id, "That cube is held by identify/register; stop first"); return; }
  uint32_t now = millis();
  SendResult result = sendZone(mac, zone);
  ZoneJob *job = nullptr;
  for (ZoneJob &j : jobs) if (j.valid && !memcmp(j.mac, mac, 6)) job = &j;  // a new colour supersedes pending repeats
  if (!job) for (ZoneJob &j : jobs) if (!j.valid) { job = &j; break; }
  if (job) {
    job->valid = true;
    memcpy(job->mac, mac, 6);
    job->zone = zone;
    job->sent = 1;
    job->startedAt = now;
  }
  char text[18], fields[120];
  if (broadcast) strcpy(text, "broadcast");
  else formatMac(mac, text);
  snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"zone\":%u,\"status\":\"%s\",\"repeats\":%d", text, zone, SEND_TEXT[result],
           job ? ZONE_REPEATS : 1);
  reply("zone_sent", id, fields);
}

inline uint32_t newShowId() {
  uint32_t id;
  do id = esp_random(); while (id == 0 || id == lastShowId);
  return id;
}

inline bool showRunning(uint32_t now) { return triggered && uint32_t(now - lastTriggerAt) < showLengthMs; }

inline void sendTimecode(uint32_t now) {
  nctshow::ShowTimecode frame = nctshow::makeTimecode(lastShowId, uint32_t(now - lastTriggerAt), showVersion, showCrc);
  lastTimecodeAt = now;
  timecodes++;
  sendFrame(showTarget, &frame, sizeof(frame));
}

inline void showConfig(const char *id, const char *line) {
  uint32_t length, version = 0, crc = 0;
  if (!jsonUint(line, "length_ms", length) || length < 1 || length > nctshow::MAX_LENGTH_MS) {
    error(id, "show_config needs length_ms 1-3600000"); return;
  }
  jsonUint(line, "version", version);
  jsonUint(line, "crc", crc);
  showLengthMs = length; showVersion = version; showCrc = crc;
  char fields[100];
  snprintf(fields, sizeof(fields), "\"length_ms\":%lu,\"version\":%lu,\"crc\":%lu", (unsigned long)length,
           (unsigned long)version, (unsigned long)crc);
  reply("show_config", id, fields);
}

inline void showStop(const char *id) {
  bool was = showRunning(millis());
  triggered = false;
  char fields[60];
  snprintf(fields, sizeof(fields), "\"was_running\":%s,\"show_id\":%lu", boolText(was), (unsigned long)lastShowId);
  reply("show_stop", id, fields);
}

// Returns false (and says so) inside the lockout.
inline bool startShow(const char *id, const uint8_t *mac) {
  uint32_t now = millis();
  if (triggered && uint32_t(now - lastTriggerAt) < LOCKOUT_MS) {
    char fields[80];
    snprintf(fields, sizeof(fields), "\"source\":\"usb\",\"retry_ms\":%lu", (unsigned long)(LOCKOUT_MS - uint32_t(now - lastTriggerAt)));
    reply("locked", id, fields);
    return false;
  }
  triggered = true;
  lastTriggerAt = now;
  lastShowId = newShowId();
  memcpy(showTarget, mac, 6);
  shows++;
  Packet packet = {};
  packet.type = MSG_SHOW_START;
  packet.cubeID = lastShowId;  // the cube reads the showId from this field
  bool broadcast = isBroadcast(mac);
  int sent = 0, delivered = 0;
  for (int i = 0; i < SHOW_REPEATS; i++) {
    if (i) delay(SHOW_REPEAT_GAP_MS);
    SendResult result = sendFrame(mac, &packet, sizeof(packet));
    if (result == SEND_DELIVERED || result == SEND_UNCONFIRMED || result == SEND_NO_RESULT) sent++;
    if (result == SEND_DELIVERED) delivered++;
  }
  char text[18], fields[200];
  if (broadcast) strcpy(text, "broadcast");
  else formatMac(mac, text);
  int n = snprintf(fields, sizeof(fields), "\"source\":\"usb\",\"show_id\":%lu,\"target\":\"%s\",\"sent\":%d,\"repeats\":%d",
                   (unsigned long)lastShowId, text, sent, SHOW_REPEATS);
  if (!broadcast && n > 0 && n < int(sizeof(fields))) snprintf(fields + n, sizeof(fields) - n, ",\"delivered\":%d", delivered);
  reply("show_start", id, fields);
  sendTimecode(millis());  // straight after the burst, then once a second (poll)
  return true;
}

inline void stop() {
  releaseTarget();
  operationId[0] = 0;
  cancelJobs();
}

// The host heartbeat is gone while a cube is held: return it to idle, as the station does.
inline void hostLost() {
  if (!active) return;
  releaseTarget();
  reply("watchdog", operationId, "\"detail\":\"Application heartbeat lost; attempted idle\"");
  operationId[0] = 0;
}

inline void pollQueue() {
  CubeRx r;
  for (int count = 0; count < 64 && cubeQueue && xQueueReceive(cubeQueue, &r, 0) == pdTRUE; count++) {
    if (memcmp(r.sender, r.packet.mac, 6)) continue;  // a cube reports its own address; anything else is noise
    if (r.packet.type == MSG_DISCOVER_REPLY) {
      char text[18], fields[40];
      formatMac(r.sender, text);
      snprintf(fields, sizeof(fields), "\"mac\":\"%s\"", text);
      reply("device", "", fields);
    } else if (mode == REGISTERING && r.packet.type == MSG_REGISTER_ACK && r.packet.success == 1 &&
               r.packet.cubeID == registration.cubeID && !memcmp(r.sender, target, 6)) {
      mode = ACK_PAUSE;
      ackTime = millis();
      reply("ack_received", operationId, "\"detail\":\"Allowing cube confirmation blink to finish\"");
    }
  }
}

inline void poll(uint32_t now) {
  pollQueue();
  if (!radioOk) return;
  if (mode == REGISTERING && uint32_t(now - lastAttempt) >= REGISTER_RETRY_MS) {
    if (attempts < REGISTER_ATTEMPTS) attemptRegistration();
    else registrationResult(false);
  } else if (mode == ACK_PAUSE && uint32_t(now - ackTime) >= ACK_PAUSE_MS) {
    registrationResult(true);
  } else if (mode == IDENTIFY) {
    if (durationMs && uint32_t(now - started) >= durationMs) {
      char id[41];
      snprintf(id, sizeof(id), "%s", operationId);
      releaseTarget();
      reply("flash_done", id);
    } else if (uint32_t(now - lastBlink) >= IDENTIFY_BLINK_MS) {
      blue = !blue;
      zoneToTarget(blue ? 3 : 1);
      lastBlink = millis();
    }
  }
  if (showRunning(now) && uint32_t(now - lastTimecodeAt) >= nctshow::TIMECODE_INTERVAL_MS) sendTimecode(now);
  for (ZoneJob &job : jobs) {
    if (!job.valid) continue;
    if (job.sent >= ZONE_REPEATS) { job.valid = false; continue; }
    if (uint32_t(now - job.startedAt) < ZONE_REPEAT_AT_MS[job.sent]) continue;
    SendResult result = sendZone(job.mac, job.zone);
    job.sent++;
    char text[18], fields[120];
    if (isBroadcast(job.mac)) strcpy(text, "broadcast");
    else formatMac(job.mac, text);
    snprintf(fields, sizeof(fields), "\"mac\":\"%s\",\"zone\":%u,\"n\":%u,\"status\":\"%s\"", text, job.zone, job.sent, SEND_TEXT[result]);
    reply("zone_repeat", "", fields);
    if (job.sent >= ZONE_REPEATS) job.valid = false;
  }
}

inline int helloFields(char *out, size_t capacity, uint32_t now) {
  return snprintf(out, capacity,
                  "\"busy\":\"%s\",\"lockout_ms\":%lu,\"last_show_id\":%lu,\"shows\":%lu,\"show_running\":%s,\"show_length_ms\":%lu,"
                  "\"timecode\":true,\"show_elapsed_ms\":%lu,\"show_version\":%lu,\"show_crc\":%lu",
                  MODE_TEXT[mode], (unsigned long)LOCKOUT_MS, (unsigned long)lastShowId, (unsigned long)shows,
                  boolText(showRunning(now)), (unsigned long)showLengthMs,
                  (unsigned long)(showRunning(now) ? uint32_t(now - lastTriggerAt) : 0), (unsigned long)showVersion,
                  (unsigned long)showCrc);
}

}  // namespace cube
}  // namespace gr
