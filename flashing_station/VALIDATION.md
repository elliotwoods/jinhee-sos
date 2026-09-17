# Validation — 2026-09-17

- Firmware: Arduino-ESP32 3.3.11, XIAO ESP32-C3, CDC enabled, 4 MB, no-OTA partition configuration. Successful build: 962,931 bytes program storage (45%), 36,184 bytes global RAM (11%).
- Flasher automated suite: **16 tests passed**, covering concurrent allocation, preservation of pending and known NFC mappings, independent flash results, interrupted attempts, auto intake and reconnection debounce, shared port ownership, protected station identity, port reuse, corrupt firmware rejection, NVS layout checks, simulated upload failure, boot uncertainty, and successful-build deduplication.
- Existing pairing regression suite: **22 tests passed**. Its HTTP tests require localhost socket permission outside the restricted sandbox.
- Native Tk GUI acceptance: **passed** with simulated devices and a temporary database. Verified automatic and manual workflows, boot recheck, history updates, station protection, shutdown and visible controls at the supported window sizes. A clipped history control found during testing was moved to the history toolbar.
- Supplied manifest and all firmware segment SHA-256 hashes validated.
- Current USB inventory identifies `3C:0F:02:AD:83:24` as the registration station. Only USB enumeration was used; no serial connection, reset, read-flash or upload was performed against it.

Hardware validation remains outstanding on a **separate cube**: actual upload/reset/USB re-enumeration, visible LED behavior, ESP-NOW interaction and NVS registration survival. Simulation and successful compilation do not establish those hardware outcomes. Audio files and nonblocking playback are implemented; audibility depends on the Mac's output routing and volume.

## Performance revision

The first user-run cube upload took 99 seconds and ended `boot_unconfirmed`; its actual main-image write took 3.7 seconds and all write hashes verified. A no-hardware `version` benchmark measured bundled esptool startup at 11.76 seconds versus 0.14 seconds for `python -m esptool` at the same 5.3.1 version. The uploader now uses the Python package, four invocations instead of six, one combined partition/NVS backup read, and retains the flasher stub between commands using `no-reset-stub`/`no-reset`. Final NVS readback resets directly into the application, removing the separate `run` invocation. Per-command durations are logged. Boot checking keeps its serial connection open and reports serial errors instead of silently retrying them. The automated suite verifies four commands, Python entrypoint, reused connection mode and final reset.

### Measured hardware result after optimization

Test cube **AC:27:6E:82:A0:94** completed a full verified upload in **12.58 seconds**, down from 99 seconds (~7.9× faster). Command times: identify 1.72s, combined backup 1.45s, write/verify 6.29s, NVS readback/reset 1.95s. Native USB-Serial/JTAG uses a watchdog reset and the boot monitor opens with DTR/RTS released. Boot reported `v1.4.1-USB`, the matching MAC, cube ID 38, channel 2 and `Cube READY`. NVS bytes matched the backup. Run: `8be180482f004ead8b75a38324c4e9ca`. The registration station was not targeted. The flasher suite now passes **18 tests**, including native-USB reset and control-line regression checks. Radio/LED/show validation remains separate from this USB test.

## White startup marker — USB.2

Built and uploaded `v1.4.1-USB.2` to cube `AC:27:6E:82:A0:94` in 13.36 seconds. Write verification, byte-for-byte NVS preservation and boot/version/MAC/channel checks passed. Boot reports cube ID 38 and channel 2. Run `136e11c4b2d14221876518dc51360aea`. The new three-white-pulse startup marker runs before ESP-NOW initialization. Visual observation and station-driven LED verification are pending the one-cable switch to the registration station. All 18 flasher tests pass.

### Station-driven LED check

Station `3C:0F:02:AD:83:24` running its existing `nct-pairing-1.5-reference` firmware connected on channel 2 with radio and NFC ready. It discovered the battery-powered cube `AC:27:6E:82:A0:94`, and delivered repeated SET_ZONE packets during a 30-second identify test. The user confirmed visible red/blue flashing. The automatic stop completed, with the final idle command reported delivered. Evidence: `data/usb2-radio-test.json` and `data/usb2-stop-test.json`. No registration packets were sent and the station firmware was not changed. The initial startup cue was not observed; a separate battery power-cycle observation was requested.

## GUI tool-launch fix

Attempts `30129f49b0334efb968795e9a5ecf08f` and `8f11c96cebe54f4aa6c76a51aaa2bbdd` logged `No module named esptool` before any connection. Their MAC error was misleading. The dedicated Python entrypoint explicitly loads the pinned project dependencies, subprocess launch passes an explicit environment, a hardware-free version preflight precedes identification, and missing-module output is an error even if a launcher returns zero. 21 automated tests pass, including dependency failure handling and loading with Python automatic site initialization disabled. The native GUI smoke test also exercises the real esptool version command in its worker. MAC identification remains a pre-write bootloader operation, independent of installed application firmware.
