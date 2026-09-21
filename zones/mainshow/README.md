# Mainshow Controller app

Makes a cube mainshow-ready and triggers the main show through the Mainshow controller board
(`zones/firmware/MainshowController`). Launch it with `Launch.command`, or run:

```sh
pairing_station/.venv/bin/python zones/mainshow/app.py [--cube 44] [--port /dev/cu.usbmodem101] [--connect]
```

- **Controller**:
  - The port list marks the recorded Mainshow controller, the pairing station and the spare dongles.
  - **Flash controller firmware…** converts a spare ESP32-C3 dongle, such as an ex-cube board running the pairing-station relay. The Zone Database Manager then needs the other dongle. A port that app has open is refused.
- **Cube #**: looked up in `pairing_station/data/devices.sqlite3`. The default is 44.
- **① Mainshow ready** sends `SET_ZONE 4` to that cube, which turns neon.
- **② Trigger mainshow** sends `SHOW_START` (5 times, with a fresh showId) to **this cube only** (the default) or to
  **all cubes** (broadcast, like the show). Only mainshow-ready cubes start.
- **Stop → idle** sends `SET_ZONE 0`, which ends the show on that cube and returns it to idle white.
- **Show clock**: elapsed time and the segment the cube *should* be in, taken from the cube firmware's
  timeline. Cubes report nothing back, so watch the cube.
- **Log**: every result, including triggers from the board's BOOT button or trigger input (D1 to GND), and
  refused triggers inside the 3 s lockout, and trigger-input dropouts (open for less than 1 s) that were ignored.

"Delivered" in the log is the cube radio's acknowledgement only. A broadcast has none.
Tests: `zones/tests/test_mainshow.py`.
