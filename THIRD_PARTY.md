# Third-party firmware components

The prebuilt cube firmware uses:

- Espressif Arduino-ESP32 **3.3.11**: https://github.com/espressif/arduino-esp32/tree/3.3.11 — LGPL-2.1 and component-specific licenses. The release includes ESP-IDF and its components, with their respective licenses.
- Adafruit NeoPixel **1.15.5**: https://github.com/adafruit/Adafruit_NeoPixel/tree/1.15.5 — LGPL-3.0 and file-specific notices.

The cube application source and build recipe are in `flashing_station/firmware/` and `flashing_station/build.py`. The binary files are separate flash segments, not a device backup, and contain no device NVS data. Dependencies retain their respective licenses; no replacement license is asserted here.

Python tools install pyserial and esptool from their published packages; these dependencies are not vendored.
