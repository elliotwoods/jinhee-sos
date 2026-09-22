#pragma once
// Minimal JSON for the flat request objects the hosts send, and the one-object-per-line replies.
// Copied from the Mainshow controller: values are plain strings (no escapes) or unsigned
// integers, which is everything the pairing app, the Zone Database Manager, the Mainshow app
// and zones/tools/general_radio.py ever put on the wire. No ArduinoJson, so the sketch builds
// with the zone libraries alone and compiles for the host test harness.
#include <Arduino.h>
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace ws {

inline const char *jsonValue(const char *line, const char *key) {
  char quoted[24];
  int n = snprintf(quoted, sizeof(quoted), "\"%s\"", key);
  if (n <= 0 || n >= int(sizeof(quoted))) return nullptr;
  for (const char *at = strstr(line, quoted); at; at = strstr(at + 1, quoted)) {
    const char *p = at + n;
    while (*p == ' ') p++;
    if (*p != ':') continue;  // the key text appeared as a value
    p++;
    while (*p == ' ') p++;
    return p;
  }
  return nullptr;
}

inline bool jsonString(const char *line, const char *key, char *out, size_t capacity) {
  const char *p = jsonValue(line, key);
  if (!p || *p != '"') return false;
  p++;
  size_t used = 0;
  while (*p && *p != '"') {
    if (*p == '\\' || *p < 0x20 || used + 1 >= capacity) return false;
    out[used++] = *p++;
  }
  if (*p != '"') return false;
  out[used] = 0;
  return true;
}

inline bool jsonUint(const char *line, const char *key, uint32_t &out) {
  const char *p = jsonValue(line, key);
  if (!p || !isdigit((unsigned char)*p)) return false;
  char *end = nullptr;
  unsigned long value = strtoul(p, &end, 10);
  if (end == p || value > 0xFFFFFFFFul) return false;
  out = uint32_t(value);
  return true;
}

// `true`/`false`, or 1/0 as the Mainshow app sends `on`.
inline bool jsonBool(const char *line, const char *key, bool &out) {
  const char *p = jsonValue(line, key);
  if (!p) return false;
  if (!strncmp(p, "true", 4)) { out = true; return true; }
  if (!strncmp(p, "false", 5)) { out = false; return true; }
  if (*p == '0' || *p == '1') { out = *p == '1'; return isdigit((unsigned char)p[1]) == 0; }
  return false;
}

// Replies go to the host as one JSON object per line. `id` is echoed ("" when unsolicited).
inline void reply(const char *event, const char *id, const char *fields = "") {
  Serial.printf("{\"event\":\"%s\",\"id\":\"%s\"%s%s}\n", event, id, *fields ? "," : "", fields);
}

inline void error(const char *id, const char *detail) {
  char fields[200];
  snprintf(fields, sizeof(fields), "\"detail\":\"%s\"", detail);
  reply("error", id, fields);
}

inline const char *boolText(bool value) { return value ? "true" : "false"; }

}  // namespace ws
