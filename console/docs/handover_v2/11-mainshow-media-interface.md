> <span color="red">*This document was written by Kimchi and Chips*</span>

## Implemented repair | 구현한 개선

A dedicated ESP32 MainshowController receives the media-server trigger and sends the cube start command. The inherited M5 show starter sent message 7; the maintained cube uses **SHOW_START = 8** (7 is TAG_STATE). This controller fixes that mismatch while retaining the cube's existing animation.
전용 ESP32 MainshowController가 미디어 서버 트리거를 받아 큐브 시작 명령을 보냅니다. 과거 M5 시작 장치는 메시지 7을 보냈지만 현재 큐브는 **SHOW_START = 8**을 사용하며 7은 TAG_STATE입니다. 컨트롤러는 기존 큐브 애니메이션을 유지하면서 이 불일치를 해결합니다.

Elliot reported correct on-site triggering after installing the controller and adapting the media team's 5V signal. One of ten tested cubes failed; reflashing and re-registering that cube was suggested. This sample is not a fleet-wide failure rate or final acceptance of every cube.
Elliot은 컨트롤러 설치와 미디어팀 5V 신호 변환 후 현장 트리거 성공을 보고했습니다. 테스트한 10개 중 1개가 실패하여 해당 큐브 재플래싱·재등록을 제안했습니다. 이는 전체 큐브 불량률이나 전체 검수 완료를 뜻하지 않습니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. This is the single-cube maintenance test: keep it on one cube. Check the physical cube after ① and ②: **delivered** is a radio acknowledgement, and the show clock is an expected timeline, not feedback from the LEDs.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 큐브 한 개 유지보수 테스트이며 한 큐브만 대상으로 합니다. ①과 ② 실행 후 실제 큐브를 확인하세요. **delivered**는 무선 수신 확인이며, 쇼 시계는 LED 피드백이 아닌 예상 타임라인입니다.

### 1. Show section | Show 섹션
{{shot:11-1}}
Show section: the controller, cube number and the two steps / Show 섹션: 컨트롤러, 큐브 번호와 두 단계

### 2. ① Mainshow ready delivered | ① Mainshow ready 전달됨
{{shot:11-2}}
① Mainshow ready delivered: the cube turns neon / ① Mainshow ready 전달됨: 큐브가 네온으로

### 3. ② Trigger mainshow | ② Trigger mainshow
{{shot:11-3}}
② Trigger mainshow: one click; the tooltip says what it does / ② Trigger mainshow: 클릭 한 번, 툴팁이 동작을 설명

### 4. Show running | 쇼 진행 중
{{shot:11-4}}
Show running: the clock counts the expected timeline / 쇼 진행 중: 시계가 예상 타임라인을 셈

## Normal show flow | 정상 쇼 흐름

1. Visitor taps a current **Mainshow entrance TagPlateZone**. It sends SET_ZONE 4; confirm the cube's neon ready colour.<br>관람객이 최신 DB의 메인쇼 입구 TagPlateZone에 태그합니다. SET_ZONE 4를 보내며 큐브 네온 준비색을 확인합니다.
2. The scheduled media-server signal reaches the installed interface and controller. The controller broadcasts a fresh showId five times, 30 ms apart.<br>예정된 미디어 서버 신호가 설치된 변환부와 컨트롤러에 도달합니다. 컨트롤러는 새 showId를 30 ms 간격으로 5회 브로드캐스트합니다.
3. Ready cubes that receive the command play their local timeline, approximately **298 seconds / 4:58**. They leave ready mode when it ends, so another show requires readiness again.<br>명령을 받은 준비 큐브는 약 298초 / 4분 58초의 내부 타임라인을 재생합니다. 종료 시 준비 모드를 벗어나므로 다음 쇼에는 다시 준비해야 합니다.

This synchronizes the start of a local animation. It does not follow the media server's timecode and cubes do not report playback. The show length above is the original show; a published show sets its own length.
로컬 애니메이션의 시작을 맞추는 방식입니다. 미디어 서버 타임코드를 따르지 않으며 큐브가 재생 상태를 회신하지도 않습니다. 위의 쇼 길이는 원래 쇼 기준이며, 게시된 쇼는 자체 길이를 가집니다.

## Show timecode and the updatable show | 쇼 타임코드와 업데이트 가능한 쇼

**Timecode (mainshow-1.3.0).** While a show runs, a mainshow-1.3.0 controller also broadcasts `SHOW_TIMECODE` once a second (the showId and the show time) to the start's target. A mainshow-ready cube on v1.5.0+ that missed the start joins at the right point, and a playing cube corrects drift above 100 ms. The show length (default 298 s) comes from `show_config`, which the console sends after each publish and the controller keeps in NVS. `show_stop` ends the timecode only; it does not stop cubes. Nothing depends on timecode: `MSG_SHOW_START` is unchanged, so mainshow-1.2.0 and cubes before v1.5.0 work exactly as before.
**타임코드(mainshow-1.3.0).** 쇼 재생 중 mainshow-1.3.0 컨트롤러는 시작 대상에게 `SHOW_TIMECODE`(showId와 쇼 시각)를 초당 1회 방송합니다. 시작 신호를 놓친 v1.5.0+ 메인쇼 준비 큐브는 올바른 지점에서 합류하고, 재생 중인 큐브는 100 ms 넘는 오차를 보정합니다. 쇼 길이(기본 298초)는 `show_config`로 정해지며 콘솔이 게시 후 전송하고 컨트롤러가 NVS에 저장합니다. `show_stop`은 타임코드만 끝내며 큐브를 멈추지 않습니다. 타임코드에 의존하는 기능은 없습니다. `MSG_SHOW_START`는 변경되지 않아 mainshow-1.2.0과 v1.5.0 이전 큐브는 그대로 동작합니다.

**State on site (2026-09-23).** The installed controller **#134 still runs mainshow-1.2.0** (no timecode). mainshow-1.3.0 was tested on the spare #138 (a normal start with no drift, and a cube that missed the start joined from the timecode at T = 3132 ms, serial logs only). #138 was then flashed back and is now the General Radio on general-radio-1.2.0. Updating #134 is optional and uses **Write the Mainshow controller firmware**.
**현장 상태(2026-09-23).** 설치된 컨트롤러 **#134는 여전히 mainshow-1.2.0**(타임코드 없음)입니다. mainshow-1.3.0은 예비 보드 #138에서 시험했습니다(정상 시작 시 오차 없음, 시작을 놓친 큐브가 T = 3132 ms에 타임코드로 합류, 시리얼 로그만). 이후 #138은 다시 플래시되어 현재 general-radio-1.2.0 General Radio입니다. #134 업데이트는 선택 사항이며 **Write the Mainshow controller firmware**를 사용합니다.

**Changing the animation.** The console's **Show editor** (top bar, ⌘6) edits the main show as cues (solid, fade, blink, pulse, cycle, random) on a timeline, with a preview that renders exactly what a cube plays and **Preview cubes** to see several cube numbers side by side (fanning, chapter 04). **Publish** gives the show the next version, allocated by the web inventory (versions only increase; the next must be above v4, which cube #17 holds). **Update all** / **Auto update** send it to cubes in range through a General Radio (general-radio-1.1.0+; **Auto update** is also Settings › Automatic updates › main show, on by default). A cube never switches shows mid-show: the update waits for the show to end. Cubes must run v1.5.0+ (chapter 04); older cubes keep the original show. **No show has been published on the site dataset yet**, so every cube currently plays the compiled-in original.
**애니메이션 변경.** 콘솔 **Show editor**(상단, ⌘6)에서 타임라인의 큐(solid, fade, blink, pulse, cycle, random)로 메인쇼를 편집합니다. 미리보기는 큐브가 재생하는 것과 정확히 같으며, **Preview cubes**로 여러 큐브 번호를 나란히 볼 수 있습니다(패닝, 04장). **Publish**는 웹 인벤토리가 할당한 다음 버전을 부여합니다(버전은 증가만 하며, 큐브 #17이 v4를 가지고 있어 다음 버전은 v4보다 커야 함). **Update all** / **Auto update**는 General Radio(general-radio-1.1.0+)로 범위 내 큐브에 전송합니다(**Auto update**는 Settings › Automatic updates › main show와 같으며 기본 켜짐). 큐브는 쇼 도중 쇼를 바꾸지 않고 쇼가 끝날 때까지 기다립니다. 큐브는 v1.5.0+이어야 하며(04장) 이전 큐브는 원래 쇼를 유지합니다. **현장 데이터셋에는 아직 게시된 쇼가 없으므로** 모든 큐브가 내장 원본 쇼를 재생합니다.

## Maintenance test with one cube | 큐브 한 개 유지보수 테스트

Plug in the identified Mainshow controller (or a General Radio: it offers the same verbs and is used when no controller is connected). Open the **Show** section from the top bar. Choose the intended **Cube #** from the inventory list (do not assume a default is your target). Press **① Mainshow ready** (one-click hardware button: "SET_ZONE 4 to this cube"), watch the cube turn neon and read **delivered** in the timeline; then **② Trigger mainshow** (fresh showId ×5 to this cube) and watch playback. The clock under the controller shows where the cube should be in its timeline. **Stop → idle** sends SET_ZONE 0 to the selected cube; it is not an all-cubes emergency stop.
식별된 메인쇼 컨트롤러(또는 같은 명령을 제공하며 컨트롤러가 없을 때 사용하는 General Radio)를 꽂습니다. 상단의 **Show** 섹션을 엽니다. 인벤토리 목록에서 대상 **Cube #**를 선택합니다(기본값을 대상으로 가정하지 않음). **① Mainshow ready**(한 번 클릭 하드웨어 버튼: "이 큐브에 SET_ZONE 4")를 누르고 큐브가 네온으로 바뀌는지, 타임라인의 **delivered**를 확인합니다. 그 다음 **② Trigger mainshow**(이 큐브에 새 showId 5회)를 누르고 재생을 확인합니다. 컨트롤러 아래 시계는 큐브가 타임라인에서 있어야 할 위치를 보여 줍니다. **Stop → idle**은 선택 큐브에 SET_ZONE 0을 보내며 전체 긴급 정지가 아닙니다.

**Trigger the main show on all ready cubes** is a separate press-and-hold button (a broadcast, like the real show, never acknowledged and not undoable); use it only for a deliberate show-wide test agreed with the media team. The show clock is expected timing, not telemetry.
**Trigger the main show on all ready cubes**는 별도의 길게 누르기 버튼입니다(실제 쇼와 같은 브로드캐스트, 확인 응답 없음, 되돌릴 수 없음). 미디어팀과 협의한 전체 테스트에만 사용합니다. 쇼 시계는 예상 시간이며 실측 상태가 아닙니다.

## The General Radio as show host | 쇼 호스트로서의 General Radio

{{shot:C-7}}
General Radio › Cubes & show: Set zone to one cube (unicast, ×3) or, by press-and-hold, to ALL cubes; Start show on this cube / on ALL ready cubes / General Radio › Cubes & show: 큐브 한 개에 Set zone(유니캐스트, 3회) 또는 길게 눌러 전체 큐브, 이 큐브 / 모든 준비 큐브에 쇼 시작

When no Mainshow controller is connected, the Show section uses a connected General Radio for ① and ②. Its own panel adds **Set zone** (idle / preshow / desert / pool / mainshow-ready) to one cube with the plate-style ×3 repeat, **Identify**, and the broadcast variants behind a press-and-hold. Delivered means the cube's radio answered, not that it changed colour; a broadcast is never acknowledged. The General Radio is not recorded as the Mainshow controller and has no trigger input.
메인쇼 컨트롤러가 연결되지 않으면 Show 섹션은 연결된 General Radio로 ①과 ②를 실행합니다. 전용 패널에는 큐브 한 개에 플레이트 방식 3회 재전송으로 **Set zone**(idle / preshow / desert / pool / mainshow-ready), **Identify**, 그리고 길게 누르기 뒤의 브로드캐스트 변형이 있습니다. Delivered는 큐브 무선이 응답했다는 뜻이며 색 변경을 뜻하지 않습니다. 브로드캐스트는 확인 응답이 없습니다. General Radio는 메인쇼 컨트롤러로 기록되지 않으며 트리거 입력이 없습니다.

## Edit, publish and update the show | 쇼 편집·게시·업데이트

{{shot:11-5}}
Show editor: transport, timeline, the previewed cubes and Send to real cubes / Show editor: 트랜스포트, 타임라인, 미리보기 큐브와 Send to real cubes

1. **Open Show editor** (top bar, ⌘6). The working copy is saved on this computer as you edit; the chips under the title say whether it matches the published version.<br>**Show editor**를 엽니다(상단, ⌘6). 편집 내용은 이 컴퓨터에 자동 저장되며, 제목 아래 칩이 게시 버전과 같은지 알려 줍니다.
2. **Edit on the timeline.** Click or drag the ruler/colour band to scrub; click a cue block to select it and change it in the **Cue** inspector below (type, start, colours, parameters, **Fanning**); drag a block to move it, drag its left edge to move its start; double-click the lane to add a cue. The overview strip above zooms (drag its window's edges) and scrolls. Space plays, ←/→ step 0.1 s (⇧ 1 s), ⌘Z / Ctrl+Z undoes.<br>**타임라인에서 편집합니다.** 눈금자·색 띠를 클릭하거나 끌어 이동하고, 큐 블록을 클릭해 선택한 뒤 아래 **Cue** 패널(종류, 시작, 색, 매개변수, **Fanning**)에서 바꿉니다. 블록을 끌면 이동, 왼쪽 가장자리를 끌면 시작만 이동, 레인을 더블클릭하면 큐 추가입니다. 위쪽 개요 띠로 확대(창 가장자리 끌기)·이동합니다. Space 재생, ←/→ 0.1초(⇧ 1초), ⌘Z / Ctrl+Z 되돌리기.
3. **Check it.** **Preview cubes** (One / 1-8 / 1-24, or type numbers) shows several cube numbers side by side, so fanned and random cues can be judged. A reference video can be dragged onto the top-right player; it plays in step with the timeline and is never uploaded. **Send to real cubes** makes those real cubes (v1.7.0 firmware, through a general-radio-1.2.0) follow the playhead until you stop it or leave the page; a cube playing the real show ignores it.<br>**확인합니다.** **Preview cubes**(One / 1-8 / 1-24 또는 번호 입력)로 여러 큐브 번호를 나란히 보며 패닝·랜덤 큐를 판단합니다. 오른쪽 위 플레이어에 참고 영상을 끌어 놓으면 타임라인과 함께 재생되며 업로드되지 않습니다. **Send to real cubes**는 해당 실물 큐브(v1.7.0 펌웨어, general-radio-1.2.0 경유)가 재생 위치를 따라가게 하며, 멈추거나 페이지를 떠나면 끝납니다. 실제 쇼를 재생 중인 큐브는 무시합니다.
4. **Publish.** The web allocates the next version; nothing is sent to cubes yet. **Revert to vN** returns the working copy to the published show (undoable).<br>**Publish**: 웹이 다음 버전을 할당하며 아직 큐브로 보내지 않습니다. **Revert to vN**은 편집본을 게시 쇼로 되돌립니다(되돌리기 가능).
5. **Update the cubes** (Cubes card, below). **Query cubes** lists every cube in range with its firmware, show version and state; **Update all to vN** sends the published show until each confirms it (**Update selected** for ticked rows). With **Auto update** on (the default, Settings › Automatic updates) cubes are updated as they come into range. A cube updates only when it is not playing a show. **Send length to controller** tells a mainshow-1.3.0 controller the new length (also sent automatically after a publish).<br>**큐브를 업데이트합니다**(아래 Cubes 카드). **Query cubes**는 범위 내 큐브의 펌웨어·쇼 버전·상태를 나열합니다. **Update all to vN**은 각 큐브가 확인할 때까지 게시 쇼를 보냅니다(체크한 행은 **Update selected**). **Auto update**가 켜져 있으면(기본값, Settings › Automatic updates) 범위에 들어오는 큐브를 업데이트합니다. 큐브는 쇼를 재생하지 않을 때만 업데이트됩니다. **Send length to controller**는 mainshow-1.3.0 컨트롤러에 새 길이를 알립니다(게시 후 자동 전송도 됨).

{{shot:11-6}}
Cubes: Query cubes, then Update all to the published version / Cubes: Query cubes 후 게시 버전으로 Update all

## Electrical and trigger contract | 전기·트리거 규약

The firmware input is **XIAO D1 = GPIO3**, internally pulled up and activated by a pull to **GND** (contact/open-collector style). The supplied field report says the media system provides 5V and an adapter was fitted. **Do not treat that report as permission to wire 5V directly to GPIO3.** The installed conversion circuit, polarity and connector pinout are not documented in the repository and must be recorded by Engineering Six/media technicians before replacement.
펌웨어 입력은 **XIAO D1 = GPIO3**이며 내부 풀업 상태에서 **GND로 당길 때** 활성화됩니다(접점·오픈컬렉터 방식). 현장 보고에는 미디어 시스템 5V 신호와 변환부 설치가 기재되어 있습니다. **이 보고를 GPIO3에 5V를 직접 연결해도 된다는 뜻으로 해석하지 않습니다.** 실제 변환 회로·극성·커넥터 핀 배열은 저장소에 없으므로 교체 전 엔지니어링식스·미디어 기술자가 기록해야 합니다.

Input behaviour: 50 ms debounce; press/closure only; a held closure fires once. Input must be open for at least **1 second** before rearming, including after power-up. All trigger sources share a **3-second lockout** (the console shows "locked" with the remaining time if you trigger inside it). Brief release glitches under the rearm period do not start another show. A continuously held signal can outlast the cube animation.
입력은 50 ms 디바운스, 눌림·닫힘 시 동작, 계속 닫힘은 1회만 실행합니다. 전원 인가 후를 포함해 다시 활성화하려면 최소 **1초 열림**이 필요합니다. 모든 트리거는 **3초 잠금**을 공유합니다(잠금 중 트리거하면 콘솔에 남은 시간과 함께 "locked" 표시). 재준비 시간보다 짧은 열림 노이즈는 쇼를 다시 시작하지 않습니다. 입력 유지 시간이 큐브 애니메이션보다 길 수 있습니다.

BOOT (GPIO9) also broadcasts a start without a PC. Do not hold BOOT while powering up: it selects the chip bootloader. The controller works without an app heartbeat; the console's Mainshow controller panel shows boot-button and trigger-input starts in the timeline when it is connected.
BOOT(GPIO9)도 PC 없이 시작을 브로드캐스트합니다. 전원 인가 중 누르면 부트로더로 들어가므로 누르지 않습니다. 컨트롤러는 앱 하트비트 없이 동작하며, 연결되어 있으면 콘솔의 Mainshow controller 패널 타임라인에 BOOT 버튼·트리거 입력 시작이 표시됩니다.

## Read indicators correctly | 표시 해석

Faint red scrolling controller LEDs mean waiting; strong green scroll means a trigger occurred within the last 298 seconds. Green does not prove cubes are playing. Unicast "delivered" is radio acknowledgment; broadcast has no per-cube acknowledgment. The console never shows delivered as success: it is the second rung of the truth ladder.
컨트롤러의 약한 빨강 이동은 대기, 강한 초록 이동은 최근 298초 이내 트리거가 있었다는 뜻입니다. 초록은 큐브 재생 증명이 아닙니다. 유니캐스트 delivered는 무선 ACK이며 브로드캐스트는 큐브별 ACK가 없습니다. 콘솔은 delivered를 성공으로 표시하지 않습니다. 진실 사다리의 두 번째 단계입니다.

If nothing starts, check readiness, controller identity/power/channel (the cards "… is not the Mainshow controller" / "controller is on channel …"), input rearm and lockout logs, then the media interface. If only some cubes fail, test their readiness, mapping, battery, firmware and radio reach individually.
아무것도 시작하지 않으면 준비 상태·컨트롤러 신원/전원/채널(카드 "… is not the Mainshow controller" / "controller is on channel …")·입력 재준비·잠금 로그와 미디어 변환부를 확인합니다. 일부만 실패하면 준비·매핑·배터리·펌웨어·무선 도달을 개별 테스트합니다.

Replacement uses **Write the Mainshow controller firmware** on an identified intended spare's Unidentified board panel. The pipeline protects other roles, backs up/preserves NVS and records the new controller identity. It is not a zone flash target. The recorded controller is ex-cube #134; the General Radio dongle is ex-cube #138.
교체는 지정된 예비 보드의 Unidentified board 패널에서 **Write the Mainshow controller firmware**를 사용합니다. 다른 역할 보호·백업·NVS 보존 및 새 컨트롤러 신원 기록을 수행합니다. 존 플래시 대상이 아닙니다. 기록된 컨트롤러는 구 큐브 #134, General Radio 동글은 구 큐브 #138입니다.

## Sources | 근거

`MainshowController.ino` (mainshow-1.3.0: timecode, `show_config`, `show_stop`; `zones/firmware/MainshowController/README.md`), `zones/firmware/libraries/NctShow/src/NctShowProtocol.h`, `console/showedit.py`, `pairing_station/show_registry.py`, `show_publish.py`, `zones/mainshow/app.py` (reused by `console/sessions/mainshow.py`), maintained cube firmware; `console/panels/ShowSection.js`, `console/commands.py` (`mainshow.*`); Elliot's supplied report and existing Repair by Kimchi and Chips page. Evidence class: code-inspected; ① / ② / clock are simulation-verified with a fake controller; the real show path was not exercised while writing this handover. Timecode and wireless show updates were checked on the bench with cube #17 and the spare #138 (serial logs only, LEDs not watched); the Show editor UI is simulation-verified.
위 소스와 Elliot 보고, 기존 수리 페이지 기준. 근거 구분: 코드 확인. ① / ② / 시계는 가짜 컨트롤러로 시뮬레이션 확인. 실제 쇼 경로는 본 문서 작성 중 실행하지 않았습니다. 타임코드와 무선 쇼 업데이트는 큐브 #17과 예비 #138로 벤치에서 확인했습니다(시리얼 로그만, LED 미관찰). Show editor UI는 시뮬레이션 확인입니다.

## Related guides | 관련 안내

{{page:00}}
{{page:04}}
{{page:15}}
