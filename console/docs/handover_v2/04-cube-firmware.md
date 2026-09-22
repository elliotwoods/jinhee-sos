> <span color="red">*This document was written by Kimchi and Chips*</span>

## Choose this workflow only for cubes | 큐브에만 사용하는 절차

Plug the cube into the console computer with a USB data cable. The console identifies it as a **Cube** by its `Cube MAC:` / `FW:` / `READY` answer, not by its USB connector; a board that answers as a station, dongle, zone or controller opens a different panel and is never offered cube firmware. A board that answers nothing appears as an **Unidentified board**: do not flash cube firmware onto it just because it looks like a cube.
큐브를 USB 데이터 케이블로 콘솔 컴퓨터에 연결합니다. 콘솔은 USB 커넥터가 아니라 `Cube MAC:` / `FW:` / `READY` 응답으로 **Cube**를 식별합니다. 스테이션·동글·존·컨트롤러로 응답하는 보드는 다른 패널이 열리며 큐브 펌웨어를 제공하지 않습니다. 응답이 없는 보드는 **Unidentified board**로 표시되며, 큐브처럼 보인다고 큐브 펌웨어를 쓰지 않습니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. The flash job in these pictures is scripted (no esptool ran); the stages and wording are the real pipeline's.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 화면의 플래시 작업은 스크립트로 연출한 것이며(esptool 미실행) 단계와 문구는 실제 파이프라인과 같습니다.

**Flash page | Flash 페이지**

### 1. Switch on "Flash cubes as they are plugged in" | "Flash cubes as they are plugged in" 켜기
{{shot:04-F1}}
Flash cubes: switch on "Flash cubes as they are plugged in" / Flash cubes: "Flash cubes as they are plugged in" 켜기

### 2. Firmware and show done | 펌웨어와 쇼 완료
{{shot:04-F2}}
A cube plugged in: firmware written and verified, show written and confirmed / 큐브 연결: 펌웨어 쓰기·검증, 쇼 쓰기·확인 완료

**Cube panel (one cube) | 큐브 패널(한 대)**

### 3. Cube › Firmware: the reported version differs | Cube › Firmware: 보고 버전이 다름
{{shot:04-1}}
Cube › Firmware: the reported version differs from the local build / Cube › Firmware: 보고된 버전이 로컬 빌드와 다름

### 4. Flashing | 플래시 중
{{shot:04-2}}
Flashing: the job card shows the stage and progress; the port is held / 플래시 중: 작업 카드에 단계와 진행률 표시, 포트 점유

### 5. Verified | 검증 완료
{{shot:04-3}}
Verified: the cube rebooted and reported the new version / 검증 완료: 큐브가 재부팅 후 새 버전을 보고함

### 6. History and Check boot | History 및 Check boot
{{shot:04-4}}
Cube › History and Check boot / Cube › History 및 Check boot

## Manual update from the cube panel: recommended first cube | 큐브 패널에서 수동 업데이트: 첫 큐브 권장

1. Finish registration operations (the station panel must be idle) and close any serial monitor using the cube port. Keep the **Flash cubes** page off.<br>등록 작업을 끝내고(스테이션 패널이 유휴 상태) 큐브 포트를 사용하는 시리얼 모니터를 닫습니다. **Flash cubes** 페이지는 꺼 둡니다.
2. Connect one intended cube. Its Cube panel opens. Check the current number, MAC and original-number reference on Overview; unassigned is not the same as its original number. Open **Firmware**: it shows the reported version against the local build with a verdict (**Version matches** / **Update needed** / **Not verified**) and the build's manifest state.<br>대상 큐브 한 개를 연결하면 Cube 패널이 열립니다. Overview에서 현재 번호, MAC, 과거 번호를 구분해 확인합니다. 미할당은 과거 번호와 같지 않습니다. **Firmware**를 열면 보고 버전과 로컬 빌드 비교 판정(**Version matches** / **Update needed** / **Not verified**)과 빌드 매니페스트 상태가 표시됩니다.
3. Click **Flash cube firmware** (one click; the tooltip says "Writes the app partition and reboots the cube. NVS is preserved"). The console releases the cube's monitoring session, holds the port for the job, and shows a job card with stages. Keep power and the cable stable throughout. It now also brings the main show up to date, as on the Flash page; the Firmware tab's **Main show** row shows what the cube holds (vN from NVS, the built-in show, or not reported), and **Update show over USB** writes only the show.<br>**Flash cube firmware**를 누릅니다(한 번 클릭, 툴팁: "앱 파티션을 쓰고 큐브를 재부팅함. NVS 보존"). 콘솔은 큐브 모니터 세션을 해제하고 작업을 위해 포트를 잡으며 단계가 있는 작업 카드를 표시합니다. 작업 동안 전원과 케이블을 유지합니다. 이제 Flash 페이지처럼 메인쇼도 최신으로 맞춥니다. Firmware 탭의 **Main show** 행이 큐브의 쇼(NVS의 vN, 내장 쇼, 또는 미보고)를 표시하며, **Update show over USB**는 쇼만 씁니다.
4. Wait for the outcome on the truth ladder: **Verified** means the pipeline checked the uploaded firmware, the preserved NVS registration bytes and the matching MAC/firmware/channel/ready response after reboot. **Delivered · boot not confirmed** means written and verified but no boot message: the Attention card offers **Check boot again**.<br>진실 사다리의 결과를 기다립니다. **Verified**는 파이프라인이 펌웨어, NVS 등록 데이터 보존, 재부팅 후 MAC·펌웨어·채널·준비 응답을 확인했다는 뜻입니다. **Delivered · boot not confirmed**는 쓰기·검증은 됐지만 부팅 메시지가 없다는 뜻이며 Attention 카드가 **Check boot again**을 제공합니다.
5. Disconnect only after completion (the console refuses to close while a write runs). The cube is re-identified and its Firmware tab should now say **Version matches**. Test actual LEDs, registration and zone interaction separately. A newly flashed cube with no tag still needs NFC registration and zone database distribution.<br>완료 후에만 분리합니다(쓰기 중에는 콘솔 종료 거부). 큐브가 다시 식별되고 Firmware 탭에 **Version matches**가 표시되어야 합니다. 실제 LED, 등록, 존 체험은 별도로 테스트합니다. 태그가 없는 신규 큐브는 NFC 등록과 존 DB 배포가 추가로 필요합니다.

## Flash cubes as they are plugged in (Flash page) | 꽂는 대로 큐브 플래시 (Flash 페이지)

For more than one cube, use the **Flash cubes** page (top bar, second item after Devices, ⌘2). It brings each cube's **firmware and main show** up to date over USB, one cube after another.
여러 큐브는 **Flash cubes** 페이지(상단, Devices 다음 두 번째 항목, ⌘2)를 사용합니다. 각 큐브의 **펌웨어와 메인쇼**를 USB로 한 대씩 최신으로 만듭니다.

1. **Clear the bench** of other ESP32 boards you do not want touched (stations, zones and radios are never taken, but only boards that answer as cubes should be in reach). Open **Flash cubes** and switch on the bar **Flash cubes as they are plugged in**. It is off every time the console starts. Every cube already plugged in, and every cube plugged in afterwards, is taken once per plug-in.<br>벤치에서 건드리지 않을 다른 ESP32 보드를 치웁니다(스테이션·존·무선은 절대 대상이 아니지만 큐브로 응답하는 보드만 두는 것이 원칙). **Flash cubes**를 열고 **Flash cubes as they are plugged in** 바를 켭니다. 콘솔을 시작할 때마다 꺼져 있습니다. 이미 꽂혀 있는 큐브와 이후 꽂는 큐브를 꽂을 때마다 한 번씩 처리합니다.
2. **Firmware.** Exactly the supported pipeline of this chapter: NVS backup, write, verify, NVS unchanged, boot check. Skipped when this cube already completed this build.<br>**펌웨어.** 이 장의 지원 파이프라인과 동일합니다: NVS 백업, 쓰기, 검증, NVS 불변 확인, 부팅 확인. 이 큐브가 같은 빌드를 이미 완료했다면 건너뜁니다.
3. **Show.** The cube's NVS is read over USB and compared with the published show cached on this computer. If the cube's show is missing, older or damaged, only the `show` part of NVS is replaced; the number, tag and radio calibration are kept. The written data is read back byte for byte and, after a reset, the cube must answer `SHOW: v=N … src=nvs`. This runs even when the firmware was skipped. A cube holding a newer show than the published one is left alone (warning); firmware older than v1.5.0 cannot take a show. With no published show, only the firmware is written. Nothing goes over the radio.<br>**쇼.** 큐브의 NVS를 USB로 읽어 이 컴퓨터에 저장된 게시 쇼와 비교합니다. 큐브의 쇼가 없거나 오래됐거나 손상되었으면 NVS의 `show` 부분만 교체하며 번호·태그·무선 보정값은 유지합니다. 쓴 데이터를 바이트 단위로 다시 읽어 확인하고, 재시작 후 큐브가 `SHOW: v=N … src=nvs`로 응답해야 합니다. 펌웨어를 건너뛴 경우에도 실행됩니다. 게시본보다 새 쇼를 가진 큐브는 그대로 두고 경고합니다. v1.5.0 이전 펌웨어는 쇼를 받을 수 없습니다. 게시 쇼가 없으면 펌웨어만 씁니다. 무선은 사용하지 않습니다.
4. **Done.** You hear a rising chord (a falling tone on failure; a single tick if nothing needed writing), and a toast on any page says e.g. "Cube #34 …: firmware v1.7.0-USB.1 written and verified, show v5 written and confirmed by the cube. Unplug it and plug in the next cube." The **This session** table lists each cube's firmware result, show result, time and detail.<br>**완료.** 올라가는 화음이 들리고(실패 시 내려가는 음, 쓸 것이 없었으면 짧은 틱) 어느 페이지에서나 예: "Cube #34 …: firmware v1.7.0-USB.1 written and verified, show v5 written and confirmed by the cube. Unplug it and plug in the next cube." 알림이 뜹니다. **This session** 표에 큐브별 펌웨어 결과, 쇼 결과, 시각, 상세가 기록됩니다.
5. **On failure the page stops**; nothing retries by itself. **Retry (rewrite the firmware)** runs it again like the old flasher's manual retry. If a failure happened after the NVS write began, the result is **attention** and the detail names `nvs-show-before.bin` in the run folder, the backup to restore from.<br>**실패 시 페이지가 멈추며** 자동 재시도는 없습니다. **Retry (rewrite the firmware)**는 기존 플래셔의 수동 재시도처럼 다시 실행합니다. NVS 쓰기 시작 후 실패했다면 결과는 **attention**이며 상세에 복원용 백업인 실행 폴더의 `nvs-show-before.bin`이 표시됩니다.

With both Register and Flash on, a new cube is flashed first; the Register page shows "Waiting for the Flash page to finish this cube" and then continues to the NFC scan (chapter 03). **This computer › USB intake**'s old "Auto-flash cubes" button is now a link to this page; zone intake is unchanged.
Register와 Flash를 모두 켜면 새 큐브를 먼저 플래시합니다. Register 페이지는 "Waiting for the Flash page to finish this cube"를 표시한 뒤 NFC 스캔으로 이어집니다(03장). **This computer › USB intake**의 기존 "Auto-flash cubes" 버튼은 이 페이지로 가는 링크가 되었으며 존 intake는 그대로입니다.

{{shot:C-9}}
This computer: USB intake (off at launch), instance locks and firmware builds / 이 컴퓨터: USB intake(실행 시 꺼짐), 인스턴스 잠금과 펌웨어 빌드

**Sounds** (as in the old flasher; switch: Settings › Behaviour › "Audio cues for USB cube flashing", with **Test sound**): a rising two-note start, a short tick at each stage and every 4 s while writing, a rising four-note chord on success, a single tick when the firmware was already current and nothing was written, a falling three-note tone on any failure (including boot not confirmed), and a single note when a new USB port appears while the Flash page is on. They also play for Flash cube firmware and Check boot on the cube panel. A successful MAC/build pair is skipped by automatic flashing even after a restart. Manual flashing permits an intentional repeat. Adapters without a unique serial number should leave the USB location empty for at least two seconds between cubes. Evidence: simulation and unit tests only (`console/tests/test_flashflow.py`); the Flash page and the USB show stage have not yet run on a real cube.
**소리**(기존 플래셔와 동일, 설정: Settings › Behaviour › "Audio cues for USB cube flashing", **Test sound** 버튼): 시작 시 올라가는 두 음, 단계마다 그리고 쓰는 동안 4초마다 짧은 틱, 성공 시 올라가는 네 음 화음, 펌웨어가 이미 최신이라 쓴 것이 없으면 틱 한 번, 모든 실패(부팅 미확인 포함) 시 내려가는 세 음, Flash 페이지가 켜진 동안 새 USB 포트가 나타나면 음 하나. 큐브 패널의 Flash cube firmware와 Check boot에서도 재생됩니다. 성공한 MAC·빌드 조합은 재시작 후에도 자동 플래시에서 건너뜁니다. 수동 플래싱은 의도적 재작업을 허용합니다. 고유 시리얼 번호가 없는 어댑터는 큐브 사이에 USB 위치를 최소 2초 비워 둡니다. 근거: 시뮬레이션·단위 테스트만(`console/tests/test_flashflow.py`). Flash 페이지와 USB 쇼 단계는 아직 실제 큐브에서 실행하지 않았습니다.

## Recovery decisions | 복구 판단

- **boot not confirmed:** the Attention card "written and verified, boot not confirmed" offers **Check boot again**; the Cube › History tab has **Check boot** for a past result while the cube is connected. This checks the reboot without reflashing. If it still cannot confirm, keep the log (job card › log) and investigate power, cable, target and firmware.<br>boot not confirmed: Attention 카드 "written and verified, boot not confirmed"에서 **Check boot again**을, Cube › History 탭에서 연결된 큐브의 과거 결과에 **Check boot**를 사용합니다. 재플래싱 없이 부팅을 확인합니다. 계속 미확인이면 로그(작업 카드 › log)를 보존하고 전원·케이블·대상·펌웨어를 점검합니다.
- **Write/verify failure:** keep the receipt and backup, read the job log and the "failed" card, then use a deliberate manual retry. Do not substitute a full-chip erase; the console has no such command.<br>쓰기·검증 실패: 영수증·백업을 보존하고 작업 로그와 "failed" 카드를 읽은 뒤 수동 재시도합니다. 전체 칩 삭제로 대체하지 않습니다. 콘솔에는 그런 명령이 없습니다.
- **Database-save failure after completed flash:** Inventory › Flash runs › **Recover saved results** imports completed receipts from `flashing_station/data/runs/*/receipt.json`. Read the recovered outcome before deciding whether any hardware operation is needed.<br>완료 후 DB 저장 실패: Inventory › Flash runs › **Recover saved results**가 `flashing_station/data/runs/*/receipt.json`의 완료 영수증을 가져옵니다. 복구된 결과를 읽은 뒤 하드웨어 작업 필요 여부를 판단합니다.
- **Protected board / wrong partition / hash mismatch:** the console refuses with a card ("refused", "wrong flash size", "Cube firmware build needs attention"). Resolve identification or build/partition compatibility; **Rebuild the cube firmware** (This computer › Firmware builds) regenerates the manifest through the maintained build script. Do not bypass protection or edit manifest hashes.<br>보호 장비·잘못된 파티션·해시 불일치: 콘솔이 카드("refused", "wrong flash size", "Cube firmware build needs attention")로 거부합니다. 장비 식별 또는 빌드·파티션 호환성을 해결합니다. **Rebuild the cube firmware**(This computer › Firmware builds)는 유지관리 빌드 스크립트로 매니페스트를 재생성합니다. 보호를 우회하거나 매니페스트 해시를 수정하지 않습니다.

## What is preserved and what is changed | 보존·변경 범위

**Versions on site (2026-09-23).** The fleet runs **v1.4.1-USB.2**, derived from the inherited v1.4.x show firmware: it removes ArduinoOTA and Wi-Fi credential/AP behaviour, keeps ESP-NOW channel 2 and the show timeline, and adds USB identity/readiness plus three short white startup flashes. The console's bundled build is now **v1.7.0-USB.1**, which only cube #17 (`1C:DB:D4:F0:A8:30`) runs. The Attention panel warns "Cube #… runs v1.4.1-USB.2; the local build is v1.7.0-USB.1" when the two differ. That is information, not an instruction to flash: a v1.4.1 cube still plays the original show and works with every zone and controller.
**현장 버전(2026-09-23).** 전체 큐브는 **v1.4.1-USB.2**를 실행합니다. 기존 v1.4.x 쇼 펌웨어 기반이며 ArduinoOTA와 Wi-Fi 자격증명·AP 동작을 제거하고 ESP-NOW 채널 2와 쇼 타임라인을 유지하며 USB 신원·준비 응답과 짧은 흰색 시작 점멸 3회를 추가했습니다. 콘솔 번들 빌드는 이제 **v1.7.0-USB.1**이며 큐브 #17(`1C:DB:D4:F0:A8:30`)만 실행 중입니다. 두 버전이 다르면 Attention 패널에 "Cube #… runs v1.4.1-USB.2; the local build is v1.7.0-USB.1"이 표시되는데, 이는 정보이지 플래시 지시가 아닙니다. v1.4.1 큐브도 원래 쇼를 재생하며 모든 존·컨트롤러와 호환됩니다.

What the newer builds add (each includes the previous one; registration, zones, the 24-byte packet and `MSG_SHOW_START` are unchanged):
새 빌드가 추가하는 기능(각 버전은 이전 버전 포함. 등록, 존, 24바이트 패킷, `MSG_SHOW_START`는 변경 없음):

- **v1.5.0-USB.1 — the show is data.** The compiled-in show renders v1.4.1's timeline exactly. A newer show published from the console arrives over the radio, is checked and kept in NVS namespace `show` (the `cube` registration keys are untouched); a damaged stored show falls back to the compiled-in one. Only a higher version is accepted, and never while a show is running: the update waits for the show to end. A cube that missed the start joins a running show from the controller's `SHOW_TIMECODE` and corrects drift above 100 ms.<br>**v1.5.0-USB.1 — 쇼가 데이터가 됨.** 내장 쇼는 v1.4.1 타임라인을 그대로 재생합니다. 콘솔에서 게시한 새 쇼는 무선으로 도착해 검사 후 NVS `show` 네임스페이스에 저장됩니다(`cube` 등록 키는 그대로). 손상된 저장 쇼는 내장 쇼로 대체됩니다. 더 높은 버전만 받으며 쇼 재생 중에는 절대 적용하지 않고 쇼가 끝날 때까지 기다립니다. 시작 신호를 놓친 큐브는 컨트롤러의 `SHOW_TIMECODE`로 진행 중인 쇼에 합류하고 100 ms 넘는 오차를 보정합니다.
- **v1.6.0-USB.1 — fanning.** A fade, blink, pulse or cycle cue can offset each cube by its registered number (sequential: step × ((n − 1) mod groups); scatter: a fixed pseudo-random offset within the spread), so one show ripples across the cubes while every cube receives the same show. A cube without a number has no offset. v1.5.0 refuses a fanned show and keeps its current one.<br>**v1.6.0-USB.1 — 패닝.** fade·blink·pulse·cycle 큐는 등록 번호에 따라 큐브별로 시간을 어긋나게 할 수 있습니다(순차: step × ((n − 1) mod 그룹 수), 분산: spread 범위 내 고정 의사난수). 모든 큐브가 같은 쇼를 받으면서도 물결처럼 퍼집니다. 번호 없는 큐브는 오프셋이 없습니다. v1.5.0은 패닝된 쇼를 거부하고 현재 쇼를 유지합니다.
- **v1.7.0-USB.1 — live preview on real cubes.** While the Show editor mirrors to real cubes, a General Radio (general-radio-1.2.0) broadcasts each cube number's current colour about 20 times a second (`SHOW_LIVE`). A registered cube that is not playing a show shows its colour for a 600 ms lease, then restores exactly what it showed before. A cube playing a show ignores it; `SET_ZONE`, `SHOW_START` or a timecode join ends live mode.<br>**v1.7.0-USB.1 — 실물 큐브 실시간 미리보기.** Show editor가 실물 큐브로 미러링하는 동안 General Radio(general-radio-1.2.0)가 큐브 번호별 현재 색을 초당 약 20회 방송합니다(`SHOW_LIVE`). 쇼를 재생하지 않는 등록 큐브는 600 ms 리스 동안 그 색을 보여 준 뒤 이전 상태로 정확히 복원합니다. 쇼 재생 중인 큐브는 무시하며 `SET_ZONE`, `SHOW_START`, 타임코드 합류가 실시간 모드를 끝냅니다.

**Moving the fleet:** flash v1.7.0 once over USB with the **Flash cubes** page below (it also writes the published show) (bootloader and partition table are identical to v1.4.1; only the app changes, NVS is preserved). After that, new shows go over the air (chapter 11). Cubes still on v1.4.1 ignore every show frame and keep playing the original show, so a partial rollout is safe but those cubes will not play a newly published show.
**전체 전환:** 아래 **Flash cubes** 페이지로 v1.7.0을 USB로 한 번 씁니다(게시 쇼도 함께 씀)(부트로더·파티션 테이블은 v1.4.1과 동일, 앱만 변경, NVS 보존). 이후 새 쇼는 무선으로 전달됩니다(11장). v1.4.1 큐브는 모든 쇼 프레임을 무시하고 원래 쇼를 재생하므로 부분 적용은 안전하지만, 그 큐브들은 새로 게시한 쇼를 재생하지 않습니다.

NVS at 0x9000, length 0x5000, is backed up and compared during the supported flashing path. The pipeline writes components separately and does not perform a full-chip erase. Unknown partition layouts are rejected; preservation of unrelated old filesystem partitions is not promised when moving to the no-OTA layout.
지원 플래싱 경로는 0x9000부터 길이 0x5000인 NVS를 백업·비교합니다. 구성요소를 분리해서 쓰며 전체 칩 삭제를 하지 않습니다. 알 수 없는 파티션 구조는 거부합니다. no-OTA 구조로 바꿀 때 관계없는 기존 파일시스템 파티션 보존까지 보장하지는 않습니다.

Local evidence: `flashing_station/data/runs/<attempt-id>/` holds receipts/logs/NVS backups; the console reuses that folder and the same `flash_runs` table (Inventory › Flash runs). Keep this private. Firmware results are separate from NFC registration status. "Version matches" is reported-version comparison, not a running-binary hash measurement.
로컬 증빙: 위 runs 폴더에 영수증·로그·NVS 백업이 있으며 콘솔도 같은 폴더와 `flash_runs` 표(Inventory › Flash runs)를 사용합니다. 비공개 보관합니다. 펌웨어 결과는 NFC 등록 상태와 별개입니다. "Version matches"는 보고 버전 비교이지 실행 바이너리 해시 측정이 아닙니다.

## Editing the main-show animation | 메인쇼 애니메이션 수정

Version 1 described Engineering Six's proposed path (develop on one cube in Arduino IDE, hand the code over for a verified distribution build, reflash all cubes over USB). That is no longer needed for a new animation: the console's **Show editor** edits the main show as cues on a timeline, **Publish** gives it the next web-allocated version, and **Update all** / **Auto update** send it over the radio to v1.5.0+ cubes (chapter 11). Changing the compiled-in default (`shows/mainshow.json`) or the show format is still a cube firmware release through this chapter's pipeline.
1판은 엔지니어링식스의 제안 방식(Arduino IDE에서 큐브 한 개로 개발, 검증 빌드로 전체 USB 재플래싱)을 설명했습니다. 이제 새 애니메이션에는 필요하지 않습니다. 콘솔 **Show editor**에서 타임라인의 큐로 메인쇼를 편집하고, **Publish**로 웹에서 다음 버전을 받고, **Update all** / **Auto update**로 v1.5.0+ 큐브에 무선 전송합니다(11장). 내장 기본 쇼(`shows/mainshow.json`)나 쇼 형식을 바꾸는 것은 여전히 이 장의 파이프라인을 거치는 큐브 펌웨어 릴리스입니다.

## Sources | 근거

`flashing_station/backend.py`, `core.py`, `build.py` (reused unchanged by `console/jobs/cube.py`); `console/intake.py` (USB intake), `console/flashflow.py` + `console/web/panels/FlashSection.js` (Flash page), `console/commands_extra.py` (`cube.recover_receipts`), `console/advisor.py` (`flash.*`, `cube.fw_*`, `build.stale` cards). Evidence class: code-inspected and simulation-verified (receipt recovery and the job runner are unit-tested; the flash captures are scripted). No cube was flashed through the console while writing this handover. The show firmware was checked on cube #17 on 2026-09-23 over serial logs only (LEDs not watched): v1.5.0 old-style start, timecode join, wireless update deferred until the show ended, NVS persistence across reboot; v1.6.0 accepted a fanned show; v1.7.0 live start and lease end, other numbers ignored, unicast refused by the radio, a running show ignored live frames. Details: `flashing_station/README.md`.
위 소스 기준. 근거 구분: 코드 확인·시뮬레이션 확인(영수증 복구와 작업 러너는 단위 테스트, 플래시 화면은 스크립트 연출). 본 문서 작성 중 콘솔로 큐브를 플래싱하지 않았습니다. 쇼 펌웨어는 2026-09-23 큐브 #17에서 시리얼 로그로만 확인했습니다(LED 미관찰): v1.5.0 기존 방식 시작, 타임코드 합류, 쇼 종료까지 보류된 무선 업데이트, 재부팅 후 NVS 유지; v1.6.0 패닝 쇼 수락; v1.7.0 실시간 시작·리스 종료, 다른 번호 무시, 무선의 유니캐스트 거부, 재생 중 실시간 프레임 무시. 상세: `flashing_station/README.md`.

## Related guides | 관련 안내

{{page:00}}
{{page:03}}
{{page:11}}
{{page:12}}
