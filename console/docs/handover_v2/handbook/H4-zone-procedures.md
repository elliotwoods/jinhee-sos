<span color="red">*This document was written by Kimchi and Chips*</span>

> [!INFO] **Who:** cube desk and floor technician · **When:** after registering cubes, before opening, or when a zone or the main show needs a test · **You need:** the console, the Workstation, a known-good registered cube, a USB cable
> **누가:** 큐브 담당, 현장 기술 담당 · **언제:** 큐브 등록 후, 개장 전, 존이나 메인쇼를 시험할 때 · **준비물:** 콘솔, 워크스테이션, 정상 등록된 큐브, USB 케이블

This page has six procedures, A to F. The results of all six are in one table at the end. If a step fails, go to {{page:H5}}.
<kr>이 페이지에는 A부터 F까지 여섯 가지 절차가 있습니다. 여섯 절차의 결과는 끝의 표 하나에 모았습니다. 단계가 실패하면 {{page:H5}}로 갑니다.</kr>

## A. Keep zone databases current | A. 존 데이터베이스 최신 유지

Every zone board keeps its own copy of the **zone database**: which tag belongs to which cube number. A newly registered cube stays "unknown tag" at a board until the console publishes a new version and that board receives it. The web inventory hands out the version numbers, and a board accepts only a higher version than the one it holds.
<kr>모든 존 보드는 어떤 태그가 어떤 큐브 번호인지 적힌 **존 데이터베이스**를 따로 가지고 있습니다. 새로 등록한 큐브는 콘솔이 새 버전을 게시하고 그 보드가 받을 때까지 "unknown tag"로 남습니다. 버전 번호는 웹 인벤토리가 정하며, 보드는 자기가 가진 것보다 높은 버전만 받습니다.</kr>

```mermaid
flowchart LR
  A["Register<br/>등록"]:::op --> B["Sync<br/>동기화"]:::op
  B --> C["Web version<br/>웹 버전"]:::data
  C --> D["Radio or USB<br/>무선·USB"]:::dev
  D --> F["Zone boards<br/>존 보드"]:::dev
  classDef op fill:#fff4d6,stroke:#b58900
  classDef dev fill:#e6f0ff,stroke:#2b6cb0
  classDef data fill:#e8f7ee,stroke:#2f855a
```

Most days you click nothing. **Settings › Automatic updates** is on by default: the Workstation updates every out-of-date zone board in radio range, and a zone board plugged in by USB gets the database only (its firmware stays the same). A board marked **Newer / differs** is never overwritten: click **Sync** on its red card. (Simulation-verified; not yet run against the installed zone boards.)
<kr>대부분은 아무것도 누르지 않습니다. **Settings › Automatic updates**는 기본으로 켜져 있습니다. 워크스테이션이 무선 범위 안의 뒤처진 존 보드를 모두 업데이트하고, USB로 꽂은 존 보드에는 데이터베이스만 씁니다(펌웨어는 그대로). **Newer / differs**로 표시된 보드는 덮어쓰지 않습니다. 빨간 카드의 **Sync**를 누릅니다. (Simulation-verified. 설치된 존 보드에서는 아직 실행하지 않았습니다.)</kr>

Do it by hand after a big registration session, for a deliberate check, or when the switches are off:
<kr>많은 큐브를 등록한 뒤, 의도적으로 점검할 때, 또는 스위치가 꺼져 있을 때는 직접 합니다.</kr>

1. Finish any registration or flashing. Check the Sync chip in the top bar shows **✓ Synced** (if it says **⟳ Sync · sign in**, click it and enter the shared web password once). If a card says **Local cube mappings differ from the published zone database**, click its **Sync & publish**. <kr>등록이나 플래싱을 끝냅니다. 상단의 Sync 칩이 **✓ Synced**인지 확인합니다(**⟳ Sync · sign in**이면 눌러서 공유 웹 비밀번호를 한 번 입력). **Local cube mappings differ from the published zone database** 카드가 있으면 **Sync & publish**를 누릅니다.</kr>
2. Open the Workstation panel (rail group **Stations**), tab **Zone relay**. Click **Query zones**, or tick **auto-refresh (3 s)**. Tick **Show out of range** to see boards that have not answered: a board you cannot see is not proven current. <kr>워크스테이션 패널(레일의 **Stations**)에서 **Zone relay** 탭을 엽니다. **Query zones**를 누르거나 **auto-refresh (3 s)**를 켭니다. 응답하지 않은 보드는 **Show out of range**로 봅니다. 보이지 않는 보드는 최신으로 확인된 것이 아닙니다.</kr>

{{shot:06-1}}
Zone relay: each zone with its database version and signal / Zone relay: 존별 데이터베이스 버전과 신호

3. Click **Update all out-of-date zones (n)** and stay near the boards. A board is done when its row says **Current**. For one board: click its name, then **Update database over the air**. <kr>**Update all out-of-date zones (n)**을 누르고 보드 가까이에 있습니다. 행이 **Current**가 되면 끝난 것입니다. 보드 하나만: 이름을 누른 뒤 **Update database over the air**.</kr>
4. For boards far from the Mac, carry the Mac and the Workstation through the space with **auto-update all (walk the space)** ticked (a failed board is retried after 30 s). Write down any board still out of date. <kr>Mac에서 먼 보드는 **auto-update all (walk the space)**를 켠 채 Mac과 워크스테이션을 들고 걷습니다(실패한 보드는 30초 뒤 재시도). 뒤처진 채 남은 보드를 기록합니다.</kr>

> [!WARNING] "delivered" in the **Log** is not success; only **Current** is. If the USB cable drops, the run stops: read the Zone relay table again before you assume anything.
> **Log**의 "delivered"는 성공이 아닙니다. **Current**만 성공입니다. USB 케이블이 빠지면 실행이 멈춥니다. 무엇이든 가정하기 전에 Zone relay 표를 다시 읽습니다.

Evidence: **Query zones** Bench-verified (27 boards heard, 23 September); over-the-air update Simulation-verified only. More detail: {{page:X08}}
<kr>근거: **Query zones**는 Bench-verified(9월 23일, 보드 27개 수신), 무선 업데이트는 Simulation-verified뿐입니다. 자세한 내용: {{page:X08}}</kr>

## B. Test the Preshow zone | B. 프리쇼존 시험

A cube on one of the four preshow points turns red, and the zone board sends a cue over the air. The Preshow bridge writes `PRESHOW,n,ON` to TouchDesigner, which plays the butterfly.
<kr>프리쇼 포인트 네 곳 중 하나에 올린 큐브는 빨간색이 되고, 존 보드가 무선으로 큐를 보냅니다. 프리쇼 브리지가 터치디자이너에 `PRESHOW,n,ON`을 쓰고, 터치디자이너가 나비를 재생합니다.</kr>

> [!WARNING] The cue test raises **real media cues**. Agree it with the media team first, and switch **Cue override** off when you finish.
> 큐 시험은 **실제 미디어 큐**를 발생시킵니다. 먼저 미디어팀과 협의하고, 끝나면 **Cue override**를 끕니다.

1. Plug the preshow zone board in by USB. Open its **Cue test** tab and switch **Cue override** on. <kr>프리쇼 존 보드를 USB로 꽂습니다. **Cue test** 탭을 열고 **Cue override**를 켭니다.</kr>
2. Press **POINT n ON**. The **Cue** line should say *acknowledged yes*. Ask the media team whether the butterfly played. Press **POINT n OFF** to drop the cue. <kr>**POINT n ON**을 누릅니다. **Cue** 줄에 *acknowledged yes*가 나와야 합니다. 미디어팀에 나비가 재생되었는지 묻습니다. **POINT n OFF**로 큐를 내립니다.</kr>

{{shot:08-1}}
Cue test: switch on Cue override, then press a POINT button / Cue test: Cue override를 켠 뒤 POINT 버튼을 누름

3. Switch **Cue override** off. (If the console stops, the board drops the cue by itself within 1.5 seconds.) <kr>**Cue override**를 끕니다. (콘솔이 멈추면 보드가 1.5초 안에 스스로 큐를 내립니다.)</kr>
4. Tap a known-good cube: **Monitor** shows its number, the cube turns red, and the header shows `MEDIA mode=modern` and **bridge sees me: yes**. <kr>정상 큐브를 태그합니다. **Monitor**에 번호가 나오고, 큐브가 빨간색이 되고, 머리글에 `MEDIA mode=modern`과 **bridge sees me: yes**가 표시됩니다.</kr>

Only one program can own the bridge's USB port. TouchDesigner's Serial DAT uses it at **115200** baud. If the bridge is plugged into the console computer, press **Disconnect** on its panel first.
<kr>브리지 USB 포트는 한 프로그램만 쓸 수 있습니다. 터치디자이너의 Serial DAT는 **115200** baud로 씁니다. 브리지가 콘솔 컴퓨터에 꽂혀 있으면 먼저 패널의 **Disconnect**를 누릅니다.</kr>

Evidence: cue test Simulation-verified; through a real board and bridge To confirm. Butterfly cues Field-reported (Elliot, 22 September). More detail: {{page:X04}}
<kr>근거: 큐 시험 Simulation-verified, 실제 보드·브리지로는 To confirm. 나비 큐 Field-reported(Elliot, 9월 22일). 자세한 내용: {{page:X04}}</kr>

## C. Test the Desert zone | C. 사막존 시험

A registered cube on a desert position does two separate things: the board switches on the **local light panel** by wire, and tells the **cube** over the air to turn yellow. They fail for different reasons, so check them separately. Plug the desert zone board in by USB and open its **Monitor** tab: it shows each tap, whether the cube was found, and the radio result.
<kr>등록된 큐브를 사막존 위치에 올리면 두 가지가 따로 일어납니다. 보드가 전선으로 **로컬 조명 패널**을 켜고, 무선으로 **큐브**에 노란색으로 바뀌라고 알립니다. 원인이 서로 다르므로 따로 확인합니다. 사막 존 보드를 USB로 꽂고 **Monitor** 탭을 엽니다. 태그마다 큐브 조회 결과와 무선 결과가 표시됩니다.</kr>

{{shot:07-4}}
Monitor: a tag was read and the cube found / Monitor: 태그를 읽고 큐브를 찾음

1. Place a known-good registered cube on the marked position. <kr>정상 등록된 큐브를 표시된 위치에 올립니다.</kr>
2. Nothing in **Monitor**: the reader did not see the tag. Check its position and power. Tag shown but unknown: the board's zone database is behind (procedure A). <kr>**Monitor**에 아무것도 없음: 리더가 태그를 보지 못했습니다. 위치와 전원을 확인합니다. 태그는 보이나 알 수 없음: 존 데이터베이스가 오래되었습니다(절차 A).</kr>
3. Cube found but the panel stays dark: the light's power, output or wiring. The console cannot see the light. <kr>큐브는 찾았는데 패널이 꺼져 있음: 조명 전원, 출력, 배선 문제입니다. 콘솔은 조명을 볼 수 없습니다.</kr>
4. The cube should turn yellow within about a second. **No radio ACK** means the cube is off or out of range; **Delivered** only means its radio answered. <kr>큐브가 약 1초 안에 노란색이 되어야 합니다. **No radio ACK**는 큐브가 꺼져 있거나 범위 밖이라는 뜻이고, **Delivered**는 큐브 무선이 응답했다는 뜻일 뿐입니다.</kr>
5. Every cube fails at one position: reader or mounting. One cube fails everywhere: take it to the cube desk. <kr>한 위치에서 모든 큐브가 실패: 리더나 장착 문제. 한 큐브가 모든 곳에서 실패: 큐브 데스크로 가져갑니다.</kr>

Evidence: working zone Field-reported (Hojun); Monitor and its cards Simulation-verified. More detail: {{page:X05}}
<kr>근거: 존 동작 Field-reported(Hojun), Monitor와 카드 Simulation-verified. 자세한 내용: {{page:X05}}</kr>

## D. Pool / forest: calibrate a slider | D. 풀존·숲존: 슬라이더 보정

Each of the six pool radios reads one slider with 23 positions (ticks), one per member. Each tick has a stored distance in mm. The radio stores exactly the values you send; ticks you do not send keep their old values. Changes stay a draft until you save them.
<kr>풀 라디오 여섯 대가 각각 슬라이더 하나를 읽습니다. 슬라이더에는 멤버마다 하나씩 23개 위치(눈금)가 있고, 눈금마다 거리 값(mm)이 저장됩니다. 라디오는 보낸 값만 그대로 저장하며, 보내지 않은 눈금은 이전 값을 유지합니다. 변경은 저장하기 전까지 초안입니다.</kr>

> [!WARNING] While a calibration is sent but not saved, the radio lights **no frame**. Never leave an unsaved draft during opening hours: press **Apply & save to flash** or **Reload saved** before you leave. Write down the current **mm** values before you start.
> 보정을 보냈지만 저장하지 않은 동안 라디오는 **어떤 프레임도 켜지 않습니다**. 운영 시간에 저장하지 않은 초안을 남기지 않습니다. 자리를 뜨기 전에 **Apply & save to flash** 또는 **Reload saved**를 누릅니다. 시작 전에 현재 **mm** 값을 기록합니다.

1. Plug the pool radio in by USB. Open its **Calibration** tab. Leave **Override output without a cube** off. <kr>풀 라디오를 USB로 꽂습니다. **Calibration** 탭을 엽니다. **Override output without a cube**는 끈 채로 둡니다.</kr>
2. Move the slider to tick 1 and press **Capture** on row 1. Do the same at tick 23. Capture or type (**Set to**, 10–1000 mm) every other tick whose value is wrong. <kr>슬라이더를 1번 눈금에 두고 1번 행의 **Capture**를 누릅니다. 23번 눈금도 같게 합니다. 값이 틀린 다른 눈금도 캡처하거나 **Set to**에 입력합니다(10–1000 mm).</kr>

{{shot:10-2}}
Capture control point 12 from the live reading / 실시간 값으로 제어점 12 캡처

3. Press **Send control points**, then **Apply & save to flash**. Wait for **saved=true**. <kr>**Send control points**, 이어서 **Apply & save to flash**를 누릅니다. **saved=true**를 기다립니다.</kr>
4. With a cube on the radio, move the slider through several positions in both directions while a second person watches the frames. If the same position gives a different reading each time, record a mechanical fault; do not re-calibrate again and again. <kr>라디오에 큐브를 대고 슬라이더를 양방향으로 여러 위치에 옮기는 동안 다른 사람이 프레임을 봅니다. 같은 위치에서 값이 매번 다르면 기구 문제로 기록합니다. 보정을 반복하지 않습니다.</kr>

**Guided recording** (optional, **Diagnostics** tab) measures every tick for you and proposes filter settings. Write down the current settings first. More detail: {{page:X06}}
<kr>**가이드 녹화**(선택, **Diagnostics** 탭)는 눈금을 모두 측정하고 필터 설정을 제안합니다. 먼저 현재 설정을 기록합니다. 자세한 내용: {{page:X06}}</kr>

Evidence: calibration in the console Simulation-verified; on a real radio To confirm. Field-reported (Hojun, 23 September): relays replaced, frame map re-measured (poolcentral-4.2.2), every slider position 1–23 lit its own lamp.
<kr>근거: 콘솔 보정 Simulation-verified, 실제 라디오 To confirm. Field-reported(Hojun, 9월 23일): 릴레이 교체, 프레임 매핑 재측정(poolcentral-4.2.2), 위치 1–23이 각각 자기 조명을 켬.</kr>

## E. Main show: one-cube test and trigger | E. 메인쇼: 큐브 한 개 시험과 트리거

Before the finale, each visitor taps the cube at the main show entrance: it turns yellow-green and is **ready**. At show time the media server's signal reaches the Mainshow controller, which starts every ready cube. Each cube plays the show from its own memory (about 4 minutes 58 seconds).
<kr>피날레 전에 관람객이 메인쇼 입구에서 큐브를 태그하면 황록색이 되어 **준비** 상태가 됩니다. 쇼 시간에 미디어 서버 신호가 메인쇼 컨트롤러에 도달하고, 컨트롤러가 준비된 모든 큐브를 시작시킵니다. 각 큐브는 자기 메모리의 쇼를 재생합니다(약 4분 58초).</kr>

```mermaid
sequenceDiagram
  participant E as Entrance board<br/>입구 보드
  participant M as Media server<br/>미디어 서버
  participant C as Mainshow controller<br/>메인쇼 컨트롤러
  participant R as Ready cubes<br/>준비된 큐브
  E->>R: Tap: yellow-green<br/>태그: 황록색
  M->>C: Show cue<br/>쇼 큐
  C->>R: Start ×5<br/>시작 5회
```

> [!WARNING] **Not live today.** The installed controller **#134 still runs mainshow-1.2.0** and sends no show clock, so a cube that misses the start does **not** join late. (Late join is Bench-verified only, on the spare #138 with cube #17.)
> **현재 미적용.** 설치된 컨트롤러 **#134는 아직 mainshow-1.2.0**이며 쇼 타임코드를 보내지 않으므로 시작을 놓친 큐브는 늦게 합류하지 **않습니다**. (늦은 합류는 예비 #138과 큐브 #17로 Bench-verified만 되었습니다.)

1. Plug the Mainshow controller in by USB (without it, the console uses a connected Workstation). Open **Show** in the top bar. Type the **Cube #** from the label and check that the row is the cube in your hand. <kr>메인쇼 컨트롤러를 USB로 꽂습니다(없으면 연결된 워크스테이션을 씀). 상단 바에서 **Show**를 엽니다. 라벨의 **Cube #**를 입력하고 표시된 행이 손에 든 큐브인지 확인합니다.</kr>

{{shot:11-1}}
Show section: the controller, the cube number and the two steps / Show 섹션: 컨트롤러, 큐브 번호와 두 단계

2. Press **① Mainshow ready**. The cube turns yellow-green and the result reaches **Delivered**. <kr>**① Mainshow ready**를 누릅니다. 큐브가 황록색이 되고 결과가 **Delivered**에 도달합니다.</kr>
3. Press **② Trigger mainshow**. The cube starts the show (only a ready cube starts). <kr>**② Trigger mainshow**를 누릅니다. 큐브가 쇼를 시작합니다(준비된 큐브만 시작).</kr>
4. Look at the cube: the **Show clock** only counts the expected time, it is not a report from the cube. Press **Stop → idle** to end the show on this cube. <kr>큐브를 직접 봅니다. **Show clock**은 예상 시간을 셀 뿐 큐브의 보고가 아닙니다. **Stop → idle**로 이 큐브의 쇼를 끝냅니다.</kr>

> [!WARNING] **② Trigger all ready cubes** (hold to confirm) starts **every** ready cube in range, like the real show. Nothing answers and it cannot be undone. Use it only for a whole-show test agreed with the media team.
> **② Trigger all ready cubes**(길게 눌러 확인)는 실제 쇼처럼 범위 안의 **모든** 준비된 큐브를 시작합니다. 응답이 없고 되돌릴 수 없습니다. 미디어팀과 협의한 전체 쇼 시험에만 사용합니다.

In the real show the media server's signal arrives through the installed signal interface. The controller's BOOT button also starts all ready cubes, with no computer attached.
<kr>실제 쇼에서는 미디어 서버 신호가 설치된 신호 변환부를 거쳐 들어옵니다. 컨트롤러의 BOOT 버튼으로도 컴퓨터 없이 준비된 모든 큐브를 시작할 수 있습니다.</kr>

> [!DANGER] Never wire the media system's 5 V signal straight to the controller's trigger input. It must go through the installed interface.
> 미디어 시스템의 5 V 신호를 컨트롤러 트리거 입력에 직접 연결하지 않습니다. 반드시 설치된 변환부를 거쳐야 합니다.

Evidence: ① and ② Simulation-verified. The installed controller start is Field-reported (Elliot): one of ten tested cubes failed. More detail: {{page:X07}}
<kr>근거: ①·② Simulation-verified. 설치된 컨트롤러의 시작은 Field-reported(Elliot)이며 시험한 10개 중 1개가 실패했습니다. 자세한 내용: {{page:X07}}</kr>

## F. Change and send the main show | F. 메인쇼 변경·전송

The **Show editor** changes the animation the cubes play. Only cubes on v1.5.0 or later can receive a new show; older cubes keep the built-in original.
<kr>**Show editor**는 큐브가 재생하는 애니메이션을 바꿉니다. v1.5.0 이상 큐브만 새 쇼를 받을 수 있고, 이전 큐브는 내장된 원래 쇼를 유지합니다.</kr>

1. Open **Show editor** (top bar, ⌘6). The chips under the title say whether your working copy matches the published show. <kr>**Show editor**를 엽니다(상단 바, ⌘6). 제목 아래 칩이 작업본이 게시된 쇼와 같은지 알려 줍니다.</kr>
2. Click a cue block on the timeline and change it in the **Cue** panel. Double-click the lane to add a cue. <kr>타임라인의 큐 블록을 클릭해 **Cue** 패널에서 바꿉니다. 레인을 더블클릭하면 큐가 추가됩니다.</kr>
3. Press Space to play. **Preview cubes** shows several cube numbers. **Send to real cubes** makes v1.7.0 cubes follow the preview (about 16 times a second; a cube returns to normal 0.6 s after the last update). <kr>Space로 재생합니다. **Preview cubes**는 여러 큐브 번호를 보여 줍니다. **Send to real cubes**는 v1.7.0 큐브가 미리보기를 따라가게 합니다(초당 약 16회, 마지막 전송 0.6초 뒤 원래대로).</kr>

{{shot:11-5}}
Show editor: timeline, previewed cubes and Send to real cubes / Show editor: 타임라인, 미리보기 큐브, Send to real cubes

4. Press **Publish**. The web gives the show its next version number. Nothing is sent to cubes yet. <kr>**Publish**를 누릅니다. 웹이 쇼에 다음 버전 번호를 줍니다. 아직 큐브로 보내지 않습니다.</kr>
5. In the **Cubes** card, press **Query cubes**, then **Update all to vN**. A cube takes the new show only when it is not playing. With **Auto update** on (the default), cubes update as they come into range. <kr>**Cubes** 카드에서 **Query cubes**, 이어서 **Update all to vN**을 누릅니다. 큐브는 쇼를 재생하지 않을 때만 새 쇼를 받습니다. **Auto update**가 켜져 있으면(기본값) 범위에 들어오는 큐브가 업데이트됩니다.</kr>

> [!INFO] **23 September:** main show **v6** was published at 04:52 KST. By 04:59 the six v1.7.0-USB.1 cubes (#17, #33, #39, #52, #58, #95) reported v6 over the air (Bench-verified, as recorded by the console; LEDs not recorded). The rest of the fleet (v1.4.1-USB.2) plays the built-in original. The next publish is numbered by the web.
> **9월 23일:** 메인쇼 **v6**을 04:52(KST)에 게시했습니다. 04:59까지 v1.7.0-USB.1 큐브 6개(#17, #33, #39, #52, #58, #95)가 무선으로 v6을 보고했습니다(Bench-verified, 콘솔 기록 기준, LED 미기록). 나머지 큐브(v1.4.1-USB.2)는 내장된 원래 쇼를 재생합니다. 다음 게시 번호는 웹이 정합니다.

Evidence: Show editor screens Simulation-verified. More detail: {{page:X07}}
<kr>근거: Show editor 화면 Simulation-verified. 자세한 내용: {{page:X07}}</kr>

## What success looks like | 성공 확인

| You see · 화면 | It means · 뜻 | If not · 아니면 |
|---|---|---|
| A: every Zone relay row says **Current** · 모든 행이 **Current** | Those boards know every published cube · 게시된 큐브를 모두 앎 | **Update all**, or walk · 또는 걷기; {{page:H5}} §1 |
| B: **Cue** says *acknowledged yes*, butterfly plays · 나비 재생 | Board, bridge and TouchDesigner work · 보드·브리지·터치디자이너 정상 | {{page:H5}} §5 |
| C: panel lights and cube turns yellow · 패널 점등, 큐브 노란색 | Reader, light and radio work · 리더·조명·무선 정상 | Steps 2–5 · 단계 2–5 |
| D: **saved=true**, right frame for each name · 이름마다 맞는 프레임 | Calibration is stored and correct · 보정 저장·정확 | Re-check the ends · 양 끝 재확인; {{page:H5}} §7 |
| E: test cube turns yellow-green, then plays · 황록색 후 재생 | Ready and start reach the cube · 준비·시작 도달 | {{page:H5}} §6 |
| F: editor chips say working copy = published · 작업본 = 게시본 | Cubes get the show you edited · 편집한 쇼가 전달됨 | **Publish**, then **Update all to vN** |

<span color="red">*This document was written by Kimchi and Chips*</span>
