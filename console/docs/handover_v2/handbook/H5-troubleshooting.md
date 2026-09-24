<span color="red">*This document was written by Kimchi and Chips*</span>

Find the symptom in the index and go to its section. Card titles and buttons are in English, as on screen. Every card and rarer case is in {{page:X11}}.
<kr>목록에서 증상을 찾아 해당 절로 갑니다. 카드 제목과 버튼은 화면과 같이 영어입니다. 모든 카드와 드문 사례는 {{page:X11}}에 있습니다.</kr>

> [!DANGER] Equipment that is hot, smells, is damaged or has unstable power: stop using it and have it checked before it is used again. A software reset does not repair an electrical fault.
> 발열, 냄새, 파손, 전원 불안정이 있는 장비는 사용을 중단하고, 다시 쓰기 전에 점검을 받습니다. 소프트웨어 리셋으로 전기 고장은 고쳐지지 않습니다.

## Symptom index and first response | 증상 목록·초기 대응

| Symptom · 증상 | First check · 첫 점검 | Section · 절 |
|---|---|---|
| A cube is "unknown tag" at a zone · 존에서 큐브가 "unknown tag" | Sync chip **✓ Synced**? Zone **Current** in **Zone relay**? · Sync 칩 **✓ Synced** 여부, 존 **Current** 여부 | 1 |
| One cube fails at several good readers · 한 큐브가 여러 리더에서 실패 | That cube: charge, tag, registration, firmware (USB) · 그 큐브: 충전, 태그, 등록, 펌웨어 | Swap test (below), 4 · 교체 시험(아래), 4 |
| Several good cubes fail at one reader, or it reads nothing · 여러 큐브가 한 리더에서 실패, 또는 아무것도 못 읽음 | That reader: position, power, zone database · 그 리더: 위치, 전원, 존 데이터베이스 | 3 |
| Registration fails · 등록 실패 | Workstation link, its reader, the cube answering · 워크스테이션 연결, 리더, 큐브 응답 | 2 |
| **Register** greyed out · **Register** 비활성 | Hover it: the tooltip gives the reason · 툴팁의 이유 | {{page:H3}} B |
| A cube blinks blue/red, or changes zone, when its tag is laid on the Workstation · 워크스테이션에 태그를 올리면 큐브가 깜박이거나 존이 바뀜 | Intended: on by default. To stop it, switch **Signal the cube when its tag is read** off, or choose **Flash 2 s** under **On each tag** · 의도된 동작(기본 켜짐). 스위치를 끄거나 **Flash 2 s** 선택 | {{page:H3}} B3 |
| Tag is read but the cube's colour does not change · 태그는 읽지만 큐브 색이 그대로 | Cube on, in range, holding its number? · 큐브 켜짐, 범위 안, 번호 보유 여부 | 4 |
| Cube is red at the preshow, but no butterfly · 프리쇼에서 빨강인데 나비 없음 | Bridge port: no other program holding it · 브리지 포트 점유 여부 | 5 |
| The main show does not start, or only on some cubes · 메인쇼 미시작 또는 일부만 재생 | Were the cubes tagged at the entrance? · 입구 태그 여부 | 6 |
| Pool frame lights wrong, flickering or stuck · 풀존 프레임 조명 오류·깜빡임·멈춤 | Pool radio id, calibration, pool central controller · 풀 라디오 id, 보정, 풀 중앙 컨트롤러 | 7 |
| The console will not start, or a USB board is not identified · 콘솔 미실행 또는 USB 보드 미식별 | Another NCT app already open, or another program holds the port · 다른 NCT 앱 실행 중, 또는 다른 프로그램이 포트 점유 | 8 |
| The Sync chip does not reach **✓ Synced**, or a cube lost its number · Sync 칩이 **✓ Synced**가 안 됨 또는 큐브 번호 사라짐 | Password, network, or a newer change elsewhere · 비밀번호, 네트워크, 다른 곳의 새 변경 | 9 |
| The console opens in a web browser · 콘솔이 웹 브라우저에서 열림 | Started without its launcher; WebView2 missing (Windows) · 실행 파일로 시작하지 않음, WebView2 없음(Windows) | 10 |
| A row in **Automatic updates** does not finish · **Automatic updates** 행이 끝나지 않음 | Board in use, a failed flash, a pool board, or missing build tools · 사용 중인 보드, 플래시 실패, 풀 보드, 빌드 도구 없음 | 11 |

A firmware-difference card in **Attention** is information only. The cube still works with every zone.
<kr>**Attention**의 펌웨어 차이 카드는 정보일 뿐입니다. 큐브는 모든 존과 계속 동작합니다.</kr>

Before you fix anything, swap in a charged, known-good cube. If it works, the first cube is at fault: plug it in by USB away from visitors and read its Cube panel. If it fails too, the zone board or the path after it is at fault. Don't re-register a batch or start the show on every cube to diagnose one cube.
<kr>무엇이든 고치기 전에 충전된 정상 큐브로 바꿔 봅니다. 정상 큐브가 동작하면 처음 큐브의 문제이므로 관람객이 없는 곳에서 USB로 꽂고 Cube 패널을 읽습니다. 정상 큐브도 실패하면 존 보드나 그 뒤 경로의 문제입니다. 큐브 하나를 진단하려고 전체 재등록을 하거나 모든 큐브에 쇼를 시작하지 않습니다.</kr>

## 1. A cube is not recognised at a zone | 1. 존이 큐브를 인식하지 못함

> [!INFO] **Symptom:** a recently registered cube does nothing at a zone. The zone board reports "unknown tag", but the console shows the cube as registered.
> **증상:** 최근 등록한 큐브가 존에서 반응이 없습니다. 존 보드는 "unknown tag"라고 하지만 콘솔에서는 큐브가 등록된 것으로 보입니다.

Registering changes only the inventory on this computer. The zone board knows the cube only after a sync (automatic by default) publishes a new zone database and the board receives it.
<kr>등록은 이 컴퓨터의 인벤토리만 바꿉니다. 동기화(기본 자동)가 새 존 데이터베이스를 게시하고 보드가 그것을 받아야 존 보드가 큐브를 압니다.</kr>

1. A known-good cube also fails there? Then it is the reader: section 3. <kr>정상 큐브도 실패하면 리더 문제입니다: 3절.</kr>
2. The Sync chip does not show **✓ Synced**? Click it to sync now, or see section 9. <kr>Sync 칩이 **✓ Synced**가 아니면 눌러서 바로 동기화하거나 9절을 봅니다.</kr>
3. The zone is not **Current** in **Zone relay**? Update its database (procedure A in {{page:H4}}). <kr>**Zone relay**에서 존이 **Current**가 아니면 데이터베이스를 업데이트합니다({{page:H4}} 절차 A).</kr>
4. Still unknown? Read the card (below). <kr>그래도 모르면 아래 카드를 확인합니다.</kr>

Plug the zone board in by USB. Its **Monitor** tab shows the tap as **unknown tag**, and the Attention card names the case:
<kr>존 보드를 USB로 꽂습니다. **Monitor** 탭에 **unknown tag**가 표시되고 Attention 카드가 경우를 알려 줍니다.</kr>

| Card ends with · 카드 끝부분 | Do this · 조치 |
|---|---|
| **… the plate's database is behind** | **Update database over USB** or **Update database over the air** |
| **… not yet in the published database** | **Sync & publish**, then update the zone · 그다음 존 업데이트 |
| **… is a pending registration for cube #n** | **Send the saved mapping to cube #n** |
| **… is not in this computer's inventory** | **Sync first (another computer may know it)**; if still unknown, register it ({{page:H3}}) · 그래도 없으면 등록 |

Tap the cube again: **Monitor** should show **FOUND Cube #n**. Updating every zone is procedure A in {{page:H4}}. (Field-reported, 22 September: a zone held v31, the new tag was only in v32; publishing and updating fixed it.)
<kr>큐브를 다시 태그합니다. **Monitor**에 **FOUND Cube #n**이 나와야 합니다. 모든 존 업데이트는 {{page:H4}}의 절차 A입니다. (Field-reported, 9월 22일: 존이 v31을 가지고 있었고 새 태그는 v32에만 있었습니다. 게시와 업데이트로 해결했습니다.)</kr>

More detail: {{page:X08}}
<kr>자세한 내용: {{page:X08}}</kr>

## 2. Registration fails | 2. 등록 실패

> [!INFO] **Symptom:** the cube is identified by USB, but registration fails when its tag is on the reader. The screen may say it cannot communicate with the ESP32 (the small computer inside the cube).
> **증상:** 큐브는 USB로 식별되지만 태그를 리더에 대면 등록이 실패합니다. 화면에 ESP32(큐브 안의 작은 컴퓨터)와 통신할 수 없다고 나올 수 있습니다.

| # | Check · 점검 | Fix · 조치 |
|---|---|---|
| 1 | Card **Station link is not connected** · 연결 카드 | **Reconnect the station**; if silent, unplug and replug · 무응답이면 뽑았다 다시 꽂기 |
| 2 | Card **Station NFC reader is not responding** · 리더 카드 | **Try a bus clear and re-init**; if it returns, power-cycle the reader and Workstation together · 반복되면 리더와 워크스테이션을 함께 재시작 |
| 3 | Card **Registration not confirmed**, **Log** says **No radio ACK** · 큐브 무응답 | Cube charged and on? Antenna seated? Press the cube's reset button, then **Retry the saved registration** · 충전·안테나 확인, 리셋 후 재시도 |
| 4 | Still fails on the same cube · 같은 큐브가 계속 실패 | Stop. Set it aside as a hardware fault and copy the exact **Log** text · 중단, 하드웨어 결함으로 분리, **Log** 문구 기록 |

A failure never retries by itself; press **Retry**. The console keeps the saved mapping, so a later retry reuses it. (Field-reported, 22 September: reseating the antenna and a reset fixed it.)
<kr>실패해도 자동으로 재시도하지 않으므로 **Retry**를 누릅니다. 콘솔이 저장된 매핑을 유지하므로 나중에 재시도할 때 다시 씁니다. (Field-reported, 9월 22일: 안테나 재결합과 리셋으로 해결했습니다.)</kr>

More detail: {{page:X03}}
<kr>자세한 내용: {{page:X03}}</kr>

## 3. A reader reads nothing | 3. 리더가 아무것도 읽지 않음

> [!INFO] **Symptom:** no cube works at one zone board, not even a known-good cube. Its **Monitor** tab shows no taps.
> **증상:** 정상 큐브를 포함해 어떤 큐브도 한 존 보드에서 동작하지 않습니다. **Monitor** 탭에 태그 기록이 없습니다.

| # | Check · 점검 | Fix · 조치 |
|---|---|---|
| 1 | Board and reader have power (preshow: battery charged) · 보드·리더 전원(프리쇼는 배터리) | Replace the battery or fix the supply · 배터리 교체 또는 전원 수리 |
| 2 | The tag area still meets the reader · 태그 면이 리더와 맞음 | Re-seat the reader · 리더 위치 재조정 |
| 3 | Card **NFC reader on "‹zone›" is not responding** · 리더 무응답 카드 | **Ask the plate to recover the reader** |
| 4 | Recovery does not help · 복구로 해결 안 됨 | Power-cycle the reader and zone board together · 리더와 존 보드를 함께 전원 재시작 |
| 5 | Still no reads · 여전히 못 읽음 | Check the reader wiring, or replace the reader ({{page:X09}}) · 리더 배선 점검 또는 리더 교체 |

> [!WARNING] A higher reader sensitivity (**RX gain**) never fixes a missing zone database entry. If the tag is read but "unknown", go to section 1.
> 리더 감도(**RX gain**)를 올려도 존 데이터베이스 누락은 고쳐지지 않습니다. 태그는 읽지만 "unknown"이면 1절로 갑니다.

The Workstation's own reader works the same way: see section 2, check 2.
<kr>워크스테이션 자체 리더도 같습니다. 2절의 점검 2를 봅니다.</kr>

More detail: {{page:X09}}
<kr>자세한 내용: {{page:X09}}</kr>

## 4. The cube's colour does not change | 4. 큐브 색이 바뀌지 않음

> [!INFO] **Symptom:** **Monitor** shows **FOUND Cube #n**, and the zone's own light may respond, but the cube keeps its colour.
> **증상:** **Monitor**에 **FOUND Cube #n**이 표시되고 존 자체 조명은 반응할 수 있지만 큐브 색은 그대로입니다.

| Card · 카드 | Likely cause · 추정 원인 | Button · 버튼 |
|---|---|---|
| **Cube #n did not acknowledge plate "‹zone›"** | Cube off or out of range · 큐브 꺼짐 또는 범위 밖 | **Discover cubes**, **Flash cube #n to locate it** |
| **Cube #n did not acknowledge the plate — it may not hold its ID** | The cube has not stored its number · 큐브가 번호를 저장하지 않음 | **Send the saved mapping to cube #n** |
| **Plate "‹zone›" addresses cube #n at an old MAC** | The tag moved to another cube · 태그가 다른 큐브로 이전 | **Sync & publish**, then update the zone · 그다음 존 업데이트 |

**Delivered** means only that the cube's radio answered, not that its LEDs changed. If one cube fails everywhere, plug it in by USB; its Cube panel shows its number and firmware ({{page:H3}}).
<kr>**Delivered**는 큐브 무선이 응답했다는 뜻일 뿐 LED가 바뀌었다는 뜻이 아닙니다. 한 큐브가 모든 곳에서 실패하면 USB로 꽂습니다. Cube 패널에 번호와 펌웨어가 표시됩니다({{page:H3}}).</kr>

More detail: {{page:X11}}
<kr>자세한 내용: {{page:X11}}</kr>

## 5. Preshow: the cue does not reach TouchDesigner | 5. 프리쇼: 큐가 터치디자이너에 오지 않음

> [!INFO] **Symptom:** at a preshow point the cube turns red, but no butterfly appears.
> **증상:** 프리쇼 포인트에서 큐브는 빨간색이 되지만 나비가 나오지 않습니다.

| You see · 화면 | Check · 점검 |
|---|---|
| Card **Preshow plate "‹zone›" reported MEDIA FAIL**, or **bridge sees me: no** · MEDIA FAIL 또는 브리지 미수신 | Preshow bridge power, antenna and range · 프리쇼 브리지 전원·안테나·거리 |
| Card **Two preshow plates are flashed as point N** · 포인트 중복 | Reflash one board with a free point · 한 보드를 빈 포인트로 다시 플래시 |
| Bridge plugged into the console computer · 브리지가 콘솔 컴퓨터에 연결됨 | Press **Disconnect** on its panel so TouchDesigner can open the port · 패널에서 **Disconnect** |
| **Cue** says *acknowledged yes* but nothing plays · 확인 응답은 있으나 재생 없음 | Media team: Serial DAT port, **115200** baud, point → effect mapping · 미디어팀: 포트·속도·매핑 |
| Butterfly stays after the cube leaves · 큐브를 치워도 나비 유지 | Switch **Cue override** off on the **Cue test** tab · **Cue test** 탭에서 **Cue override** 끄기 |

A bridge acknowledgement proves the line was written to USB, not that the butterfly played. To test without a cube, use the cue test (procedure B in {{page:H4}}).
<kr>브리지 확인 응답은 USB에 줄이 쓰였다는 뜻이지 나비가 재생되었다는 증거가 아닙니다. 큐브 없이 시험하려면 큐 시험({{page:H4}}의 절차 B)을 씁니다.</kr>

More detail: {{page:X04}}
<kr>자세한 내용: {{page:X04}}</kr>

## 6. The main show does not start | 6. 메인쇼가 시작되지 않음

> [!INFO] **Symptom:** at the media cue no cube plays the main show, or only some do.
> **증상:** 미디어 큐 시점에 어떤 큐브도 메인쇼를 재생하지 않거나 일부만 재생합니다.

A cube plays only if it was **ready** (yellow-green, set at the entrance zone board) when the Mainshow controller sent the start.
<kr>큐브는 메인쇼 컨트롤러가 시작을 보낼 때 **준비** 상태(입구 존 보드에서 설정된 황록색)여야만 재생합니다.</kr>

1. Were the cubes yellow-green before the cue? If not, check the entrance board (section 1). <kr>큐 전에 큐브가 황록색이었나요? 아니면 입구 보드를 확인합니다(1절).</kr>
2. **Some cubes:** test each one in the **Show** section, ① then ② (procedure E in {{page:H4}}). <kr>**일부 큐브:** **Show** 섹션에서 큐브마다 ①, ②를 시험합니다({{page:H4}} 절차 E).</kr>
3. **Trigger not arriving** (controller LEDs not green): the input must be open for 1 s before it fires again, and a trigger within 3 s of the last is refused (**locked**). The media team checks the signal and interface. <kr>**트리거 미도달**(컨트롤러 LED 초록 아님): 입력은 1초 동안 열려야 다시 동작하고, 3초 안의 트리거는 거부됩니다(**locked**). 미디어팀이 신호와 변환부를 확인합니다.</kr>
4. **Controller:** read the card **Mainshow controller problem**. <kr>**컨트롤러:** **Mainshow controller problem** 카드를 읽습니다.</kr>

Green controller LEDs and **Delivered** do not prove that a cube is playing: look at the cubes. A late cube does not join today (#134 runs mainshow-1.2.0).
<kr>컨트롤러의 초록 LED와 **Delivered**는 큐브 재생의 증거가 아닙니다. 큐브를 직접 봅니다. 현재는 늦은 큐브가 합류하지 않습니다(#134는 mainshow-1.2.0).</kr>

More detail: {{page:X07}}
<kr>자세한 내용: {{page:X07}}</kr>

## 7. Pool frame lights wrong or stuck | 7. 풀존 프레임 조명 오류·멈춤

> [!INFO] **Symptom:** a slider lights the wrong frame, lamps flicker, or a frame stays dark or stays on.
> **증상:** 슬라이더가 엉뚱한 프레임을 켜거나, 조명이 깜빡이거나, 프레임이 계속 꺼져 있거나 켜져 있습니다.

| You see · 화면 | Fix · 조치 |
|---|---|
| **Two pool radios share radio id N** (lamps flicker · 깜빡임) | Give each radio its own id 1–6 with **Assign radio id** · 라디오마다 고유 id |
| **Pool radio "‹zone›" has no saved calibration**, or a draft left unsaved (frames dark · 프레임 꺼짐) | Calibrate and **Apply & save to flash**, or **Reload saved** ({{page:H4}}, D) |
| **Pool radio "‹zone›" is not seen by the central controller** / **Pool central lost radio ‹n›** | Power of the Pool central controller or that radio · 전원 확인 |
| A frame stays on with no cube · 큐브 없이 계속 켜짐 | Switch **Override output without a cube** off on the radio's panel, or release the **Pool lamp** on the Workstation panel · 라디오 패널의 오버라이드 끄기 또는 워크스테이션 패널의 **Pool lamp** 해제 |
| Wrong frame for a name · 이름과 다른 프레임 | Re-check the calibration ends; record it if readings wander · 보정 양 끝 재확인, 값이 흔들리면 기록 |

The pool radios and the Pool central controller are a matched set: update them together. Relays, wiring and driver boards are electrical repairs, not console fixes.
<kr>풀 라디오와 풀 중앙 컨트롤러는 한 세트이므로 함께 업데이트합니다. 릴레이, 배선, 드라이버 보드는 전기 수리이며 콘솔로 고칠 수 없습니다.</kr>

More detail: {{page:X06}}
<kr>자세한 내용: {{page:X06}}</kr>

## 8. The console will not start, or a USB board is not identified | 8. 콘솔 미실행 또는 USB 보드 미식별

> [!INFO] **Symptom:** the console refuses to start with "‹App› is already open on this database; close it before starting the NCT Console", or a board plugged in by USB stays unidentified.
> **증상:** 콘솔이 "‹App› is already open on this database; close it before starting the NCT Console"라며 시작을 거부하거나, USB로 꽂은 보드가 식별되지 않습니다.

| You see · 화면 | Fix · 조치 |
|---|---|
| "‹App› is already open on this database; close it before starting the NCT Console" | Intentional: the console and the old apps share one inventory. Close the named app (or the other console window), then start the console. Never delete lock files · 의도된 동작. 표시된 앱을 닫고 콘솔 시작. 잠금 파일 삭제 금지 |
| **‹port› is owned by another application** | Close that program (old app, Arduino Serial Monitor, TouchDesigner), then probe again · 해당 프로그램을 닫고 다시 확인 |
| **Board on ‹port› is not answering on serial** | Wait a few seconds; probe again on the **Unidentified board** panel · 잠시 후 다시 확인 |
| **Zone board on ‹port› has no valid identity** | Flash it with its zone profile ({{page:X09}}) · 존 프로필로 플래시 |

A USB port name is not an identity. Never write firmware to "whatever port appeared".
<kr>USB 포트 이름은 신원이 아닙니다. "새로 나타난 포트"에 펌웨어를 쓰지 않습니다.</kr>

More detail: {{page:X10}}
<kr>자세한 내용: {{page:X10}}</kr>

## 9. Sync problems | 9. 동기화 문제

> [!INFO] **Symptom:** the Sync chip does not reach **✓ Synced**, a sync error card appears, or a cube lost its number or tag after a sync.
> **증상:** Sync 칩이 **✓ Synced**가 되지 않거나, 동기화 오류 카드가 나오거나, 동기화 후 큐브의 번호나 태그가 사라졌습니다.

The console syncs by itself (on by default), so read the Sync chip first. **⟳ Sync in 5 s**: a change uploads soon. **Sync · retry in 2 min**: the last sync failed and it retries by itself. **Sync · offline**: no network; work on. **⟳ Sync · sign in**: the password is missing or was rejected; automatic sync stops until you click the chip and sign in. Clicking the chip always syncs at once. Jobs lists only failed automatic syncs. (Simulation-verified)
<kr>콘솔은 스스로 동기화하므로(기본 켜짐) 먼저 Sync 칩을 읽습니다. **⟳ Sync in 5 s**: 곧 변경을 올립니다. **Sync · retry in 2 min**: 마지막 동기화가 실패했고 자동으로 재시도합니다. **Sync · offline**: 네트워크가 없습니다. 계속 작업합니다. **⟳ Sync · sign in**: 비밀번호가 없거나 거부되었습니다. 칩을 눌러 로그인할 때까지 자동 동기화가 멈춥니다. 칩을 누르면 언제나 바로 동기화합니다. Jobs에는 실패한 자동 동기화만 나옵니다. (Simulation-verified)</kr>

| Card · 카드 | Fix · 조치 |
|---|---|
| **Web sync needs the inventory password** / **The web rejected the stored password** | Click the chip (**⟳ Sync · sign in**) and enter the shared password once (ask the team) · 칩을 눌러 공유 비밀번호 입력(팀에 문의) |
| **Web inventory unreachable; working locally** | Work on; **Check again** when the network is back · 계속 작업, 네트워크 복구 후 **Check again** |
| **The web has a newer zone database vN** | **Sync (pulls the database)** |
| **Sync was interrupted while uploading** | **Sync now** (nothing is lost · 손실 없음) |
| **Cube mappings changed but the zone database was not published** | **Sync & publish** |
| **N downloaded change(s) are waiting to be applied** | Close the other app, then **Apply now** · 다른 앱을 닫고 **Apply now** |
| **A newer change elsewhere took this device's number or tag** | Assign the label number or register again, then **Sync** · 라벨 번호 지정 또는 재등록 후 **Sync** |

Sync never asks you to choose between computers: the newest change wins, and the console tells you what this computer gave up.
<kr>동기화는 컴퓨터 사이에서 고르라고 묻지 않습니다. 가장 새로운 변경이 적용되고, 콘솔이 이 컴퓨터에서 무엇이 바뀌었는지 알려 줍니다.</kr>

More detail: {{page:X08}}
<kr>자세한 내용: {{page:X08}}</kr>

## 10. The console opens in a web browser | 10. 콘솔이 웹 브라우저에서 열림

> [!INFO] **Symptom:** the console opens as a page in the web browser instead of its own window. No error is shown.
> **증상:** 콘솔이 자체 창 대신 웹 브라우저의 페이지로 열립니다. 오류 메시지는 없습니다.

Usual cause: the console was not started through its launcher after Setup. On Windows, the WebView2 runtime may be missing. (Code-checked)
<kr>흔한 원인: Setup 후 실행 파일로 콘솔을 시작하지 않았습니다. Windows에서는 WebView2 런타임이 없을 수 있습니다. (Code-checked)</kr>

1. Close the page and the window the console was started from. Start it again only with `console/Launch.command` (Mac) or `console/Launch.bat` (Windows). <kr>페이지와 콘솔을 시작한 창을 닫습니다. `console/Launch.command`(Mac) 또는 `console/Launch.bat`(Windows)로만 다시 시작합니다.</kr>
2. Still a browser? Run `Setup.command` / `Setup.bat` again, then the launcher. <kr>그래도 브라우저면 `Setup.command` / `Setup.bat`을 다시 실행한 뒤 실행 파일로 시작합니다.</kr>
3. Windows: install the Microsoft Edge WebView2 Runtime, then start again. <kr>Windows: Microsoft Edge WebView2 Runtime을 설치한 뒤 다시 시작합니다.</kr>

The browser page is the same console with the same inventory. You can keep working in it.
<kr>브라우저 페이지도 같은 인벤토리를 쓰는 같은 콘솔입니다. 그대로 작업해도 됩니다.</kr>

More detail: {{page:X10}}
<kr>자세한 내용: {{page:X10}}</kr>

## 11. The Automatic updates panel | 11. Automatic updates 패널

> [!INFO] **Symptom:** the **Automatic updates** panel (top right) does not show **✓ Everything up to date**, and a row stays.
> **증상:** **Automatic updates** 패널(오른쪽 위)에 **✓ Everything up to date**가 나오지 않고 행이 남아 있습니다.

Read the row's state pill and the reason under it. (Simulation-verified; no real board has been upgraded automatically yet.)
<kr>행의 상태 표시와 그 아래 이유를 읽습니다. (Simulation-verified. 실제 보드를 자동으로 업그레이드한 적은 아직 없습니다.)</kr>

| Pill · 상태 | It means · 의미 | Do this · 조치 |
|---|---|---|
| **waiting** (**Starts in N s**, **Waiting: in use…**, **Waiting: Register or Flash is on**) | Normal: it starts when the board and the console are free · 정상: 보드와 콘솔이 비면 시작 | Nothing; or **Skip** · 없음, 또는 **Skip** |
| **needs build** | The firmware is still being built · 펌웨어 빌드 중 | Wait · 기다림 |
| **failed** | The upgrade or build did not finish · 업그레이드나 빌드가 끝나지 않음 | **Retry**, or unplug and replug the board; copy the reason if it fails again · **Retry** 또는 다시 꽂기, 반복되면 이유 기록 |
| **by hand** | Pool radios, pool central controller, preshow bridge, or an unconfigured board: never flashed automatically. Also a board whose firmware is newer than this computer's build ("not downgraded") or cannot be compared with it ("Cannot tell whether…") · 자동 플래시 안 함. 이 컴퓨터의 빌드보다 새 펌웨어이거나 비교할 수 없는 보드도 해당 | Pool set: upgrade radios and central together by hand ({{page:X06}}). A newer board: update this computer's code instead, or leave it · 풀 세트는 함께 수동 업그레이드. 더 새 보드: 이 컴퓨터의 코드를 업데이트하거나 그대로 둠 |
| **no build tools** | This computer cannot build firmware · 이 컴퓨터에서 빌드 불가 | Install arduino-cli with ESP32 core 3.3.11 on this computer ({{page:X10}}) · 이 컴퓨터에 arduino-cli와 ESP32 core 3.3.11 설치 |
| **paused** / **off** | **Pause** was pressed, or the switch is off in Settings › **Automatic updates** · 일시 정지 또는 설정 꺼짐 | **Resume**, or switch it on · **Resume** 또는 켜기 |

Never unplug a board whose row shows **upgrading**. Successful and failed upgrades are listed under **Recent (n)**; only failures appear in Jobs.
<kr>행에 **upgrading**이 표시된 보드는 절대 뽑지 않습니다. 성공과 실패는 **Recent (n)** 아래에 표시되고, Jobs에는 실패만 나옵니다.</kr>

More detail: {{page:X11}}
<kr>자세한 내용: {{page:X11}}</kr>

<span color="red">*This document was written by Kimchi and Chips*</span>
