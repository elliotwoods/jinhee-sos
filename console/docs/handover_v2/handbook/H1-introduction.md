<span color="red">*This document was written by Kimchi and Chips*</span>

This page explains what a visitor does, which board does what, and how the NCT Console fits in.
<kr>이 페이지는 관람객이 하는 일, 각 보드의 역할, NCT Console의 위치를 설명합니다.</kr>

## What the visitor carries | 관람객이 들고 다니는 것

Each visitor carries a **cube**: a handheld light with LEDs, a battery, a small radio computer and an NFC **tag** inside.
<kr>관람객은 각자 **큐브**를 들고 다닙니다. 큐브는 LED, 배터리, 작은 무선 컴퓨터, NFC **태그**가 들어 있는 휴대용 조명입니다.</kr>

The cube has two separate paths. The tag tells a nearby reader which cube it is. The radio receives light commands. The tag needs no battery, so a zone can still recognise a cube with a flat battery.
<kr>큐브에는 서로 다른 두 경로가 있습니다. 태그는 가까운 리더에 어떤 큐브인지 알려 줍니다. 무선은 조명 명령을 받습니다. 태그는 배터리가 필요 없으므로 배터리가 떨어진 큐브도 존이 알아볼 수 있습니다.</kr>

Every cube has a **cube number** on its label. The **zone boards** use the **zone database** to turn a tag into that number.
<kr>모든 큐브의 라벨에는 **큐브 번호**가 있습니다. **존 보드**는 **존 데이터베이스**로 태그를 그 번호로 바꿉니다.</kr>

## The visitor journey | 관람객 동선

```mermaid
flowchart LR
  A["Receive cube<br/>큐브 받기"]
  B["Preshow<br/>프리쇼"]
  C["Desert<br/>사막"]
  D["Pool / forest<br/>풀·숲"]
  E["Entrance<br/>입구"]
  F["Main show<br/>메인쇼"]
  G["Return<br/>반납"]
  A --> B --> C --> D --> E --> F --> G
```

1. **Receive a cube.** Staff hand out a charged cube. Its idle light is dim white. <kr>**큐브 받기.** 직원이 충전된 큐브를 나눠 줍니다. 대기 조명은 약한 흰색입니다.</kr>
2. **Preshow (butterfly).** The visitor holds the tag to one of four readers. The cube turns red and TouchDesigner plays that point's butterfly cue. <kr>**프리쇼(나비).** 관람객이 리더 4개 중 하나에 태그를 댑니다. 큐브가 빨간색이 되고 TouchDesigner가 해당 포인트의 나비 큐를 재생합니다.</kr>
3. **Desert.** The visitor holds the tag still at a member position. That member's name panel lights and the cube turns yellow. <kr>**사막.** 관람객이 멤버 위치에 태그를 가만히 댑니다. 해당 멤버의 이름 패널이 켜지고 큐브가 노란색이 됩니다.</kr>
4. **Pool / forest.** The visitor places the cube on a **pool radio** and moves the slider. The cube turns blue and a portrait frame lights. Six pool radios share 23 frame lights. <kr>**풀·숲.** 관람객이 **풀 라디오**에 큐브를 놓고 슬라이더를 움직입니다. 큐브가 파란색이 되고 초상화 프레임이 켜집니다. 풀 라디오 6대가 프레임 조명 23개를 함께 씁니다.</kr>
5. **Main show entrance.** The visitor taps the entrance plate. The cube turns yellow-green: it is ready. <kr>**메인쇼 입구.** 관람객이 입구 플레이트에 태그합니다. 큐브가 황록색이 되며 준비 상태가 됩니다.</kr>
6. **Main show.** At the media server's cue, the **Mainshow controller** starts the show. Every ready cube plays the same animation. <kr>**메인쇼.** 미디어 서버의 큐에 맞춰 **메인쇼 컨트롤러**가 쇼를 시작합니다. 준비된 모든 큐브가 같은 애니메이션을 재생합니다.</kr>
7. **Return.** Staff collect and charge the cubes. A tap on a **Reset plate** returns a cube to idle and saves battery. <kr>**반납.** 직원이 큐브를 회수해 충전합니다. **리셋 플레이트**에 태그하면 큐브가 대기 상태로 돌아가 배터리를 아낍니다.</kr>

> [!WARNING] **Pool wording for visitors:** "Place your cube here and move the slider to explore the portraits." Do not promise that the light matches the printed names exactly. The slider mechanism cannot do that.
> **풀존 관람객 안내 문구:** "이곳에 큐브를 놓고 슬라이더를 움직이며 초상화를 찾아보세요." 조명이 인쇄된 이름과 정확히 맞는다고 약속하지 마십시오. 슬라이더 기구로는 그렇게 할 수 없습니다.

More detail: {{page:H4}}
<kr>자세한 내용: {{page:H4}}</kr>

## The wireless and communication map | 무선·통신 구성도

```mermaid
flowchart TD
  CU["Cube<br/>큐브"]:::dev
  ZB["Zone boards<br/>존 보드"]:::dev
  PC["Pool central controller<br/>풀 중앙 컨트롤러"]:::dev
  FL["23 frame lights<br/>프레임 조명 23개"]:::dev
  PB["Preshow bridge<br/>프리쇼 브리지"]:::dev
  MED["Media system<br/>미디어 시스템"]:::dev
  MC["Mainshow controller<br/>메인쇼 컨트롤러"]:::dev
  WS["Workstation<br/>워크스테이션"]:::dev
  NC["NCT Console computer<br/>NCT 콘솔 컴퓨터"]:::op
  WEB["Web inventory<br/>웹 인벤토리"]:::data
  CU -->|"NFC tag · 태그"| ZB
  ZB -->|"ESP-NOW · 무선"| CU
  ZB -->|"ESP-NOW · 무선"| PC
  ZB -->|"ESP-NOW · 무선"| PB
  PC -->|"wired · 배선"| FL
  PB -->|"USB serial · USB"| MED
  MED -->|"wired cue · 배선"| MC
  MC -->|"ESP-NOW · 무선"| CU
  WS <-->|"ESP-NOW · 무선"| CU
  WS <-->|"ESP-NOW · 무선"| ZB
  NC <-->|"USB"| WS
  NC <-->|"internet · 인터넷"| WEB
  classDef op fill:#fff4d6,stroke:#b58900
  classDef dev fill:#e6f0ff,stroke:#2b6cb0
  classDef data fill:#e8f7ee,stroke:#2f855a
```

| Link · 연결 | Used for · 용도 |
|---|---|
| **NFC** | Cube tag → zone board reader; the tag needs no battery · 큐브 태그 → 존 보드 리더. 태그는 배터리 불필요 |
| **ESP-NOW** · 무선 | The exhibition's own radio, channel 2: cube colours, pool and preshow events, show start and the show clock (once a second), Workstation traffic · 전시 전용 무선(채널 2): 큐브 색, 풀·프리쇼 이벤트, 쇼 시작과 쇼 타임코드(1초마다), 워크스테이션 통신 |
| **USB** | Console computer ↔ Workstation; any board for identifying or flashing; preshow bridge → TouchDesigner (serial) · 콘솔 컴퓨터 ↔ 워크스테이션, 식별·플래시할 보드, 프리쇼 브리지 → TouchDesigner(시리얼) |
| **Internet** · 인터넷 | Sync and publishing (HTTPS) only · 동기화와 게시(HTTPS)에만 사용 |
| **Wired** · 배선 | Pool central → frame lights (PCA9685 → relays); media server cue → Mainshow controller trigger input (closed to GND through an interface fitted on site) · 풀 중앙 → 프레임 조명(PCA9685 → 릴레이), 미디어 서버 큐 → 메인쇼 컨트롤러 트리거 입력(현장 인터페이스로 GND 연결) |

| Board · 보드 | What it does · 하는 일 |
|---|---|
| **Zone boards** · 존 보드 | Tag readers in the zones: preshow plates, tag plates, desert boards, pool radios, Reset plates. They set the cube's colour · 존의 태그 리더. 큐브 색을 정함 |
| **Pool central controller** · 풀 중앙 컨트롤러 | Lights the 23 portrait frames that the six pool radios ask for · 풀 라디오 6대가 요청한 초상화 프레임 23개를 켬 |
| **Preshow bridge** · 프리쇼 브리지 | Passes preshow events to TouchDesigner by USB · 프리쇼 이벤트를 USB로 TouchDesigner에 전달 |
| **Mainshow controller** · 메인쇼 컨트롤러 | Takes the media server's cue and starts the main show on every ready cube · 미디어 서버 큐를 받아 준비된 모든 큐브에서 메인쇼 시작 |
| **Workstation** · 워크스테이션 | The small radio board on the console computer's USB. It reads tags for registration and reaches cubes and zone boards over the air · 콘솔 컴퓨터 USB에 꽂는 작은 무선 보드. 등록용 태그를 읽고 큐브·존 보드와 무선으로 통신 |

Boards talk over **ESP-NOW**, the exhibition's own radio on channel 2. It needs no router and no Wi-Fi network. The internet is used only to **sync** the inventory and to publish zone databases and the main show.
<kr>보드들은 채널 2의 전시 전용 무선인 **ESP-NOW**로 통신합니다. 공유기나 Wi-Fi 네트워크가 필요 없습니다. 인터넷은 인벤토리 **동기화**와 존 데이터베이스·메인쇼 게시에만 씁니다.</kr>

### What the console refuses to flash | 콘솔이 플래시를 거부하는 경우

Not every board is a cube. The console checks a board's role before it writes firmware. (Code-checked)
<kr>모든 보드가 큐브는 아닙니다. 콘솔은 펌웨어를 쓰기 전에 보드의 역할을 확인합니다. (Code-checked)</kr>

| Writing · 쓰는 것 | Refused · 거부 대상 | Override · 우회 |
|---|---|---|
| Cube firmware · 큐브 펌웨어 | Any board whose role is not cube or unknown: "That board is a ‹role›; the cube flasher refuses it" · 역할이 큐브·미확인이 아닌 모든 보드 | None · 없음 |
| Zone firmware · 존 펌웨어 | A board the inventory lists as a cube or an excluded device, or one running Workstation or controller firmware: "REFUSED: ‹label›. Force flashing a cube unregisters it." · 인벤토리에 큐브나 제외 장치로 올라 있는 보드, 워크스테이션·컨트롤러 펌웨어가 든 보드 | **Force flash** (hold to confirm). It overwrites the board; a cube loses its LED firmware and is unregistered · **Force flash**(길게 눌러 확인). 보드를 덮어씀. 큐브는 LED 펌웨어를 잃고 등록이 해제됨 |
| Workstation / Mainshow controller firmware · 워크스테이션·메인쇼 컨트롤러 펌웨어 | Known cubes, known zone boards and the installed pairing station. The board written is recorded as excluded from cube service · 알려진 큐브, 알려진 존 보드, 설치된 등록 스테이션. 쓴 보드는 큐브 서비스에서 제외로 기록됨 | **Override inventory protection…** on the **Unidentified board** panel, then hold **Force write**. A zone board leaves the show; a cube loses its LED firmware · **Unidentified board** 패널의 **Override inventory protection…** 후 **Force write**를 길게 누름. 존 보드는 쇼에서 빠지고, 큐브는 LED 펌웨어를 잃음 |

To move a board into or out of cube service, change its **Role** in the cube panel (**auto (cube)**, **LED · manually assigned**, **Reader / base station (excluded)**). The selector is locked while a station operation runs.
<kr>보드를 큐브 서비스에 넣거나 빼려면 큐브 패널의 **Role**을 바꿉니다(**auto (cube)**, **LED · manually assigned**, **Reader / base station (excluded)**). 스테이션 작업 중에는 선택할 수 없습니다.</kr>

More detail: {{page:X02}}
<kr>자세한 내용: {{page:X02}}</kr>

## The console at a glance | 콘솔 한눈에 보기

The NCT Console is one window on the console computer, a Mac or Windows PC. It replaces ten separate operator apps. Plug a board in by USB: the console identifies it without restarting it and lists it by role.
<kr>NCT Console은 콘솔 컴퓨터(Mac 또는 Windows PC)의 하나의 창입니다. 열 개의 개별 운영 앱을 대체합니다. 보드를 USB로 꽂으면 콘솔이 재시작 없이 식별하고 역할별로 표시합니다.</kr>

{{shot:C-1}}
The console: device rail (left), the selected device's panel (centre), Attention panel (right), Log dock (bottom) / 콘솔: 장치 레일(왼쪽), 선택한 장치의 패널(가운데), Attention 패널(오른쪽), Log 도크(아래)

The **Attention panel** shows **suggestion cards**. Each card says what the console noticed and what to check. A card never blocks your work.
<kr>**Attention 패널**에는 **제안 카드**가 표시됩니다. 각 카드는 콘솔이 알아챈 내용과 확인할 점을 알려 줍니다. 카드는 작업을 막지 않습니다.</kr>

Above Attention, the **Automatic updates** panel shows what the console is bringing up to date by itself. What it does, and how to stop it: {{page:H4}}, "What the console does by itself".
<kr>Attention 위의 **Automatic updates** 패널은 콘솔이 스스로 최신으로 맞추는 것을 보여 줍니다. 하는 일과 멈추는 법: {{page:H4}}의 "콘솔이 스스로 하는 일".</kr>

Every result shows its **result status**: Sent → Delivered → Acknowledged → Verified, or Failed. Only Acknowledged and Verified count as success. Delivered only means the radio got it there.
<kr>모든 결과에는 **결과 상태**가 표시됩니다: Sent → Delivered → Acknowledged → Verified, 또는 Failed. Acknowledged와 Verified만 성공입니다. Delivered는 무선으로 도착했다는 뜻일 뿐입니다.</kr>

Risky buttons (for example a broadcast to every cube) need **hold to confirm**: they show a padlock. Press and hold for about a second, until the fill reaches the end of the button; the padlock stays open while the command runs. A single click does nothing.
<kr>위험한 버튼(예: 모든 큐브에 방송)은 **길게 눌러 확인**해야 하며 자물쇠 표시가 있습니다. 채움이 버튼 끝까지 찰 때까지 1초 정도 길게 누릅니다. 명령이 실행되는 동안 자물쇠는 열려 있습니다. 한 번 클릭으로는 실행되지 않습니다.</kr>

**Language.** Use the **EN | KR** switch at the right of the top bar (also Settings › Appearance). The console remembers the choice on this computer; a console opened in a web browser keeps its own. In Korean mode, buttons also show their English name, so the button names in this handbook match the screen. Suggestion cards, logs and error messages stay in English.
<kr>**언어.** 상단 바 오른쪽의 **EN | KR** 스위치(또는 Settings › Appearance)를 사용합니다. 선택은 이 컴퓨터의 콘솔에 저장됩니다. 웹 브라우저로 연 콘솔은 따로 저장합니다. 한국어 모드에서도 버튼에 영어 이름이 함께 표시되므로 이 핸드북의 버튼 이름과 화면이 일치합니다. 제안 카드, 로그, 오류 메시지는 영어로 유지됩니다.</kr>

More detail: {{page:H4}} · {{page:X11}}
<kr>자세한 내용: {{page:H4}} · {{page:X11}}</kr>

### Installing the console | 콘솔 설치

Install the console as an app from the project's GitHub releases page (github.com/elliotwoods/jinhee-sos/releases, the newest `console-v…` release). No other software is needed; every firmware the console writes is inside the app.
<kr>콘솔은 프로젝트의 GitHub 릴리스 페이지(github.com/elliotwoods/jinhee-sos/releases, 가장 최근 `console-v…` 릴리스)에서 앱으로 설치합니다. 다른 소프트웨어는 필요 없습니다. 콘솔이 쓰는 모든 펌웨어가 앱 안에 들어 있습니다.</kr>

- **Mac** (Apple Silicon): open the `.dmg` file and drag **NCT Console** to Applications. <kr>**Mac**(Apple Silicon): `.dmg` 파일을 열고 **NCT Console**을 Applications로 끌어 놓습니다.</kr>
- **Windows PC**: unzip the `windows-x64.zip` file into a permanent folder, for example `C:\NCT Console`, and start `NCT Console.exe`. The first time, Windows warns *Windows protected your PC*: click **More info**, then **Run anyway**. <kr>**Windows PC**: `windows-x64.zip` 파일을 `C:\NCT Console` 같은 고정 폴더에 풀고 `NCT Console.exe`를 실행합니다. 처음에는 *Windows의 PC 보호* 경고가 나옵니다. **추가 정보**, **실행**을 차례로 누릅니다.</kr>

A new computer starts without the current inventory. Enter the shared web password when the console asks, and the inventory downloads. To update, install the newer release the same way: the inventory, password and flash history stay. New firmware always comes with a new console release.
<kr>새 컴퓨터에는 현재 인벤토리가 없습니다. 콘솔이 물으면 공유 웹 비밀번호를 입력하면 인벤토리를 내려받습니다. 업데이트할 때는 새 릴리스를 같은 방법으로 설치합니다. 인벤토리, 비밀번호, 플래시 기록은 유지됩니다. 새 펌웨어는 항상 새 콘솔 릴리스에 함께 들어옵니다.</kr>

More detail: {{page:X10}}
<kr>자세한 내용: {{page:X10}}</kr>

## The 12 most important names | 가장 중요한 이름 12개

Use these names; the screen and every page use them too.
<kr>아래 이름을 사용합니다. 화면과 모든 페이지도 같은 이름을 씁니다.</kr>

| Name | 이름 | Meaning · 뜻 |
|---|---|---|
| **NCT Console** | NCT 콘솔 | The one operator program on the console computer (Mac or Windows PC) · 콘솔 컴퓨터(Mac 또는 Windows PC)의 단일 운영 프로그램 |
| **Cube** | 큐브 | The glowing object a visitor carries · 관람객이 들고 다니는 빛나는 물체 |
| **Cube number** | 큐브 번호 | The number on the cube's label · 큐브 라벨의 번호 |
| **Tag** | 태그 | The NFC tag inside a cube · 큐브 안의 NFC 태그 |
| **Workstation** | 워크스테이션 | The radio board on the console computer's USB; older kinds: pairing station, General Radio · 콘솔 컴퓨터 USB의 무선 보드. 이전 종류: 등록 스테이션, General Radio |
| **Zone board** | 존 보드 | A tag reader board in a zone · 존의 태그 리더 보드 |
| **Zone database** | 존 데이터베이스 | The tag → cube-number list on every zone board · 모든 존 보드에 저장된 태그 → 큐브 번호 목록 |
| **Inventory** | 인벤토리 | The console's list of every cube · 콘솔의 전체 큐브 목록 |
| **Sync** | 동기화 | Exchanging the inventory with the shared web copy · 인벤토리를 공유 웹 사본과 주고받기 |
| **Main show** | 메인쇼 | The finale animation every cube plays together · 모든 큐브가 함께 재생하는 마지막 애니메이션 |
| **Mainshow controller** | 메인쇼 컨트롤러 | The board that starts the main show · 메인쇼를 시작하는 보드 |
| **Result status** | 결과 상태 | Sent → Delivered → Acknowledged → Verified / Failed |

The full glossary, with every old name, is {{page:X01}}.
<kr>이전 이름을 모두 포함한 전체 용어집은 {{page:X01}}입니다.</kr>

<span color="red">*This document was written by Kimchi and Chips*</span>
