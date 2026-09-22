#pragma once
// MAC and hex text helpers for the general radio's JSON line protocol. Same formats the
// pairing station and the Mainshow controller use: colon-separated upper-case MACs and UIDs,
// plain upper-case hex for relayed zone frames.
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace gr {

inline void formatMac(const uint8_t *mac, char *out) {  // out: 18 bytes
  snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

// "AA:BB:CC:DD:EE:FF" (any case) -> 6 bytes.
inline bool parseMac(const char *text, uint8_t *mac) {
  if (!text || strlen(text) != 17) return false;
  for (int i = 0; i < 6; i++) {
    char a = text[i * 3], b = text[i * 3 + 1];
    if (!isxdigit((unsigned char)a) || !isxdigit((unsigned char)b) || (i < 5 && text[i * 3 + 2] != ':')) return false;
    char pair[3] = {a, b, 0};
    mac[i] = uint8_t(strtoul(pair, nullptr, 16));
  }
  return true;
}

// Colon-separated hex of any length up to `capacity` bytes (tag UIDs). Returns the byte count or -1.
inline int parseColonHex(const char *s, uint8_t *out, int capacity) {
  if (!s) return -1;
  int length = int(strlen(s));
  if (!length || (length + 1) % 3 || (length + 1) / 3 > capacity) return -1;
  int n = (length + 1) / 3;
  for (int i = 0; i < n; i++) {
    if (!isxdigit((unsigned char)s[i * 3]) || !isxdigit((unsigned char)s[i * 3 + 1]) || (i < n - 1 && s[i * 3 + 2] != ':')) return -1;
    char pair[3] = {s[i * 3], s[i * 3 + 1], 0};
    out[i] = uint8_t(strtoul(pair, nullptr, 16));
  }
  return n;
}

inline void colonHex(const uint8_t *data, int length, char *out, size_t capacity) {
  size_t used = 0;
  out[0] = 0;
  for (int i = 0; i < length && used + 4 <= capacity; i++) used += snprintf(out + used, capacity - used, i ? ":%02X" : "%02X", data[i]);
}

// Plain upper-case hex, as zone frames travel in `zone_send` / `zone_frame`. `out` needs 2*length+1 bytes.
inline void plainHex(const uint8_t *data, int length, char *out) {
  static const char DIGITS[] = "0123456789ABCDEF";
  for (int i = 0; i < length; i++) {
    out[2 * i] = DIGITS[data[i] >> 4];
    out[2 * i + 1] = DIGITS[data[i] & 15];
  }
  out[2 * length] = 0;
}

inline int parsePlainHex(const char *s, uint8_t *out, int capacity) {
  int length = s ? int(strlen(s)) : 0;
  if (!length || length % 2 || length / 2 > capacity) return -1;
  for (int i = 0; i < length / 2; i++) {
    if (!isxdigit((unsigned char)s[2 * i]) || !isxdigit((unsigned char)s[2 * i + 1])) return -1;
    char pair[3] = {s[2 * i], s[2 * i + 1], 0};
    out[i] = uint8_t(strtoul(pair, nullptr, 16));
  }
  return length / 2;
}

}  // namespace gr
