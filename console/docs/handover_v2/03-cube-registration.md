> <span color="red">*This document was written by Kimchi and Chips*</span>

## Purpose and equipment | 목적과 준비물

Registration associates the physical cube's **MAC + label number + NFC UID**, sends that mapping to the cube and waits for a matching registration acknowledgment. Use the NCT Console, the USB pairing station with its working PN532 (or a General Radio for the radio half, with the station's reader still needed for the scan), the target powered cube, and a USB data cable if you want the console to identify the cube over USB.
등록은 실물 큐브의 **MAC + 라벨 번호 + NFC UID**를 연결하고 큐브에 전송한 뒤 일치하는 등록 응답을 기다립니다. NCT Console, PN532가 작동하는 USB 등록 스테이션(무선 부분은 General Radio도 가능하지만 스캔에는 스테이션 리더가 필요), 전원이 켜진 대상 큐브, 콘솔이 큐브를 USB로 식별하게 하려면 USB 데이터 케이블이 필요합니다.

Launch `console/Launch.command` on Mac or `console/Launch.bat` on Windows. Plug the station in: the console identifies it without resetting it and opens its session; the device rail shows **NFC scanning** (or **NFC not responding**) next to it. Cube USB identification does not replace the NFC station connection.
Mac은 `console/Launch.command`, Windows는 `console/Launch.bat`를 실행합니다. 스테이션을 꽂으면 콘솔이 리셋 없이 식별하고 세션을 엽니다. 장치 레일에 **NFC scanning**(또는 **NFC not responding**)이 표시됩니다. 큐브 USB 식별은 NFC 등록 스테이션 연결을 대신하지 않습니다.

There are two ways to register. **The Register page (⌘2) is the normal one:** switch it on, then plug the cubes in one after another. It numbers each new cube, asks for its tag and syncs. **The cube card (manual path)** does the same steps one click at a time; use it for a single re-registration, a cube that cannot be plugged in over USB, or when the Register page is waiting on something you need to fix by hand.
등록 방법은 두 가지입니다. **Register 페이지(⌘2)가 기본 방법입니다:** 켜 두고 큐브를 하나씩 꽂으면 새 큐브 번호 부여, 태그 스캔 요청, 동기화까지 진행합니다. **큐브 카드(수동 경로)**는 같은 단계를 한 번에 하나씩 클릭으로 진행합니다. 한 대만 재등록할 때, USB로 연결할 수 없는 큐브, 또는 Register 페이지가 수동으로 해결해야 할 문제로 대기 중일 때 사용합니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console running in simulation (`--simulate --scenario docs`), with isolated demonstration data and simulated boards. Yellow outlines mark the real controls or result to check. The controls are unchanged; example IDs, versions and readings are not site settings.
시뮬레이션(`--simulate --scenario docs`)으로 실행한 콘솔을 격리된 예시 데이터와 시뮬레이션 보드로 촬영했습니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 조작부는 변경하지 않았으며 예시 ID·버전·측정값은 현장 설정값이 아닙니다.

**Register page | Register 페이지**

### 1. Switch on "Register cubes as they are plugged in" | "Register cubes as they are plugged in" 켜기
{{shot:03-A1}}
Register: switch on "Register cubes as they are plugged in" / Register: "Register cubes as they are plugged in" 켜기

### 2. A new cube: NEW NUMBER for its label, then scan its tag | 새 큐브: 라벨용 새 번호, 이어서 태그 스캔
{{shot:03-A2}}
A new cube plugged in: NEW NUMBER for its label, then scan its tag / 새 큐브 연결: 라벨용 새 번호, 이어서 태그 스캔

### 3. Registered and synced | 등록 및 동기화 완료
{{shot:03-A3}}
Registered and synced: unplug it and plug in the next cube / 등록 및 동기화 완료: 분리하고 다음 큐브 연결

**Cube card (manual path) | 큐브 카드(수동 경로)**

### 4. The cube card after USB identification | USB 식별 후 큐브 카드
{{shot:03-1}}
Cube card after USB identification: the pinned cube, its number and tag / USB 식별 후 큐브 카드: 고정된 큐브, 번호와 태그

### 5. Register: one click; the tooltip says what it does | Register: 클릭 한 번, 툴팁이 동작을 설명
{{shot:03-2}}
Register: one click; the tooltip says what it does / 등록: 클릭 한 번, 툴팁이 동작을 설명

### 6. READY TO SCAN | READY TO SCAN
{{shot:03-3}}
READY TO SCAN: the cube flashes, the station waits for a fresh tag / READY TO SCAN: 큐브가 점멸하고 스테이션이 새 태그를 기다림

### 7. TAG DETECTED · REGISTERING | TAG DETECTED · REGISTERING
{{shot:03-4}}
TAG DETECTED · REGISTERING: the mapping is being delivered over the radio / TAG DETECTED · REGISTERING: 매핑이 무선으로 전달되는 중

### 8. REGISTERED | REGISTERED
{{shot:03-5}}
REGISTERED: acknowledged by the cube; the row shows the committed tag / REGISTERED: 큐브가 확인 응답; 행에 확정 태그 표시

## Register cubes as they are plugged in (Register page) | 꽂는 대로 큐브 등록 (Register 페이지)

1. **Open Register** (top bar, second item, ⌘2). The chip under the title must say **Station ready · NFC ok**; plug the pairing station in first. Tick **Register cubes as they are plugged in**. The switch is saved on this computer and is off by default. A cube that is already plugged in starts straight away.<br>상단 두 번째 항목 **Register**(⌘2)를 엽니다. 제목 아래 칩이 **Station ready · NFC ok**여야 하며 먼저 등록 스테이션을 꽂습니다. **Register cubes as they are plugged in**을 체크합니다. 이 설정은 이 컴퓨터에 저장되며 기본값은 꺼짐입니다. 이미 꽂혀 있는 큐브는 바로 시작됩니다.
2. **Plug in a cube over USB.** The steps run in order: **USB** (identified and pinned) → **Number** → **NFC scan** → **Sync**.<br>큐브를 USB로 꽂습니다. **USB**(식별·고정) → **Number** → **NFC scan** → **Sync** 순으로 진행됩니다.
3. **Number.** A cube without a number gets the lowest free number above 32 (never 2, 22, 39 or 43), even in manual-number mode. The page shows a large green **NEW NUMBER: write #N on the cube's label** and a toast appears on any page. **Write it on the label now.** If the cube already has a physical label, type it in **Label says** and press **Set** before scanning. A cube that already has a number keeps it ("This cube already had number #N").<br>번호: 번호가 없는 큐브는 32보다 큰 가장 낮은 미사용 번호(2, 22, 39, 43 제외)를 받습니다(수동 번호 모드에서도 동일). 페이지에 큰 초록색 **NEW NUMBER: write #N on the cube's label**이 표시되고 어느 페이지에서나 알림이 뜹니다. **지금 라벨에 적습니다.** 이미 실물 라벨이 있으면 스캔 전에 **Label says**에 입력하고 **Set**을 누릅니다. 이미 번호가 있는 큐브는 그 번호를 유지합니다.
4. **NFC scan.** The cube flashes and the station banner appears on the page. Clear the reader, wait for **READY TO SCAN**, then hold this cube's tag on the reader until **TAG DETECTED**. The step completes only when the cube's registration ACK is recorded. If the step is waiting, the page says why: no station, station not connected, NFC reader not ready, or station busy.<br>NFC 스캔: 큐브가 점멸하고 페이지에 스테이션 배너가 표시됩니다. 리더를 비우고 **READY TO SCAN**을 기다린 뒤 이 큐브의 태그를 **TAG DETECTED**가 나올 때까지 댑니다. 큐브의 등록 ACK가 기록되어야 단계가 완료됩니다. 대기 중이면 이유가 표시됩니다(스테이션 없음, 미연결, NFC 리더 미준비, 스테이션 사용 중).
5. **Sync.** Lift the tag: one normal Sync runs (inventory both ways, then the zone database publish). If the console is not signed in it waits with **Sign in to sync**. The page then says **Cube #N registered and synced. Unplug it and plug in the next cube.** The **This session** table lists each cube with its number, MAC, new/existing, result and time.<br>동기화: 태그를 떼면 일반 Sync가 한 번 실행됩니다(인벤토리 양방향, 이어서 존 DB 게시). 로그인하지 않았다면 **Sign in to sync**로 대기합니다. 이후 **Cube #N registered and synced. Unplug it and plug in the next cube.**가 표시됩니다. **This session** 표에 큐브별 번호, MAC, 신규/기존, 결과, 시각이 기록됩니다.
6. **Zones.** Registration reaches the zones only once they hold the published database. Automatic zone updates (Settings › Automatic updates, on by default) bring it to zones in range of the relay and to zones plugged in over USB; **Update all** is the manual path (chapter 06). Test the cube at an updated reader and watch its actual light.<br>존: 존이 게시된 DB를 가져야 등록이 반영됩니다. 자동 존 업데이트(Settings › Automatic updates, 기본 켜짐)가 릴레이 범위 안의 존과 USB로 연결된 존에 전달합니다. 수동 경로는 **Update all**입니다(06장). 업데이트된 리더에서 실제 조명을 확인합니다.

**When something goes wrong | 문제가 생기면**

- A failure never retries by itself. **Retry** re-sends the saved registration (or flashes for a new scan, or syncs again, depending on the step that failed); **Start again for this cube** restarts from the number step; **Cancel** stops the flow and the station.<br>실패 시 자동 재시도는 없습니다. **Retry**는 실패한 단계에 따라 저장된 등록 재전송, 새 스캔을 위한 점멸, 또는 동기화 재시도를 합니다. **Start again for this cube**는 번호 단계부터 다시 시작하고, **Cancel**은 흐름과 스테이션을 중지합니다.
- Plugging in a second cube mid-flow switches to it. The first cube is logged as **interrupted** and keeps its retryable pending mapping; finish it later from here or from its cube card.<br>진행 중 다른 큐브를 꽂으면 새 큐브로 전환됩니다. 첫 큐브는 **interrupted**로 기록되고 재시도 가능한 pending 매핑을 유지합니다. 나중에 여기서나 큐브 카드에서 마무리합니다.
- Unticking the switch cancels the cube in progress.<br>스위치를 끄면 진행 중인 큐브가 취소됩니다.
- Every rule of the manual path below applies: the same controller performs the scan (fresh-tag gating, matching MAC/ID ACK, tag takeover with audit).<br>아래 수동 경로의 모든 규칙이 동일하게 적용됩니다. 같은 컨트롤러가 스캔을 수행합니다(새 태그 확인, MAC/ID 일치 ACK, 감사 기록이 남는 태그 이전).

## Register one cube from its card (manual path) | 큐브 카드에서 한 대 등록 (수동 경로)

1. **Plug in the station and read its state.** The Pairing station panel shows connection, radio and NFC readiness separately. Both must be green before Register is offered. The known original station MAC is `3C:0F:02:AD:83:24`; the console never probes or flashes that identity (it is shown as **Protected**). A replacement must be identified and recorded.<br>스테이션을 꽂고 상태를 읽습니다. Pairing station 패널은 연결, 무선, NFC 준비를 따로 표시합니다. Register가 제공되려면 둘 다 초록이어야 합니다. 원 스테이션 MAC은 `3C:0F:02:AD:83:24`이며 콘솔은 이 신원을 절대 프로브·플래싱하지 않습니다(**Protected**로 표시). 교체품은 별도 식별·기록해야 합니다.
2. **Identify the physical cube.** Plug the cube into USB. The console reads its `Cube MAC:` and `FW:` lines without resetting it, reserves the MAC in the inventory, and **pins** the cube: its card opens and stays selected even if a filter or search would hide it. Unplugging keeps the pin; keep the cube powered for radio registration. Alternatively, on the station panel use **Discover cubes** and click a discovered cube's **Flash (identify)** to find it by its blinking.<br>실물 큐브를 식별합니다. 큐브를 USB에 꽂으면 콘솔이 리셋 없이 `Cube MAC:`과 `FW:` 줄을 읽고 인벤토리에 MAC을 예약한 뒤 큐브를 **고정(pin)**합니다. 카드가 열리고 필터·검색과 무관하게 선택 상태가 유지됩니다. USB를 빼도 고정은 유지되며 무선 등록을 위해 큐브 전원은 켜 둡니다. 또는 스테이션 패널의 **Discover cubes**로 발견된 큐브의 **Flash (identify)**를 눌러 점멸로 찾습니다.
3. **Assign the physical label number.** An unnumbered cube shows an inline number field on its card, preselected with the lowest free number above 32 (never 2, 22, 39 or 43); Enter accepts it. Type the actual label instead if one exists. An occupied number is refused with the owning device named.<br>실물 번호를 부여합니다. 미번호 큐브 카드에는 32보다 큰 가장 낮은 미사용 번호(2, 22, 39, 43 제외)가 미리 선택된 번호 입력란이 있으며 Enter로 수락합니다. 기존 라벨이 있으면 그 번호를 입력합니다. 사용 중인 번호는 소유 장비 이름과 함께 거부됩니다.
4. **Start the fresh scan.** Click **Register (scan a tag)** — it is a one-click hardware button with a warning tooltip ("A scanned tag that belongs to another device is transferred to this cube"). The selected cube flashes continuously. Remove all tags from the reader and wait for the **READY TO SCAN** banner on the station panel, then present only that cube's tag.<br>새 스캔을 시작합니다. **Register (scan a tag)**를 누릅니다. 경고 툴팁("다른 장비의 태그를 스캔하면 이 큐브로 이전됨")이 있는 한 번 클릭 하드웨어 버튼입니다. 선택 큐브가 계속 점멸합니다. 리더에서 모든 태그를 치우고 스테이션 패널의 **READY TO SCAN** 배너를 기다린 다음 해당 큐브의 태그만 댑니다.
5. **Wait for completion.** **TAG DETECTED / REGISTERING** is still in progress: the timeline dock shows the attempt, "delivered" (radio only) and then the cube's acknowledgment. Only the **REGISTERED** banner and the green **Registered · ACK** pill on the cube card mean a matching registration ACK was recorded. A radio-delivered message or a saved pending UID is not completion. Remove the tag when asked.<br>완료를 기다립니다. **TAG DETECTED / REGISTERING**은 진행 중입니다. 타임라인 도크에 시도, "delivered"(무선만), 그리고 큐브의 확인 응답이 순서대로 표시됩니다. **REGISTERED** 배너와 큐브 카드의 초록 **Registered · ACK** 칩만 일치하는 등록 ACK 기록을 뜻합니다. 무선 전달 또는 pending UID 저장은 완료가 아닙니다. 안내가 나오면 태그를 뗍니다.
6. **Distribute and prove the result.** Click **Sync** in the top bar (uploads the mapping and publishes the next zone database version), then let the automatic zone updates deliver it (on by default) or update zones by hand (chapter 06 over the air, chapter 07 over USB). The Attention panel will say "Local cube mappings differ from the published zone database" until you do. Then test this cube at an updated reader and observe its actual light. A deliberate power-cycle check is needed if independent persistence verification is required.<br>배포 및 결과 확인: 상단의 **Sync**를 눌러 매핑을 업로드하고 다음 존 DB 버전을 게시한 뒤 자동 존 업데이트(기본 켜짐)가 전달하게 하거나 수동으로 존을 업데이트합니다(06장 무선, 07장 USB). 그 전까지 Attention 패널에 "Local cube mappings differ from the published zone database"가 표시됩니다. 이후 최신 리더에서 해당 큐브의 실제 조명을 확인합니다. 비휘발성 저장을 독립 검증해야 한다면 전원 재시작 후 별도 테스트합니다.
7. Use **Unpin** on the cube card when finished. Unplugging the cube does not remove the pin; a newly identified cube replaces it.<br>완료 후 큐브 카드의 **Unpin**을 사용합니다. USB를 빼는 것만으로는 고정이 풀리지 않으며, 새로 식별된 큐브가 고정을 대체합니다.

## Edge cases | 예외 처리

- **Register unavailable:** the button is disabled and its tooltip gives the reason: "Connect the NFC station to register; cube USB identification alone is not enough", "NFC reader is unavailable", "This device is excluded as a reader or base station", or "An operation is active; use Stop before registering". Use **Stop** on the station panel and wait for the stop to complete before switching cubes.<br>Register 비활성: 버튼이 비활성화되고 툴팁에 이유가 표시됩니다: "Connect the NFC station…", "NFC reader is unavailable", "This device is excluded…", "An operation is active; use Stop…". 스테이션 패널의 **Stop**으로 중지하고 완료를 기다린 뒤 큐브를 바꿉니다.
- **No tag after READY:** remove and present the correct tag again, check sensor position/power, and compare a known-good cube. The station panel's NFC health shows polls and last read time; PN532 initialization alone does not prove actual scanning. If the reader is down the Attention card "Station NFC reader is not responding" offers **Recover the reader**.<br>READY 이후 태그 없음: 올바른 태그를 떼었다 다시 대고 센서 위치·전원 및 정상 큐브를 비교합니다. 스테이션 패널의 NFC 상태에 폴링 횟수와 최근 읽기 시각이 있습니다. PN532 초기화만으로 스캔 성공을 판단하지 않습니다. 리더가 응답하지 않으면 Attention 카드 "Station NFC reader is not responding"에서 **Recover the reader**를 제공합니다.
- **Unconfirmed / pending:** the card shows **Unconfirmed** or **Registering** and the Attention panel raises "Registration not confirmed" with **Retry the saved registration**. Keep the cube powered and use **Send saved mapping** to send the saved tag without scanning, or **Register** again for a new scan; the old pending reservation remains until the new scan is accepted. Do not unregister records to unlock registration.<br>미확인 / 보류: 카드에 **Unconfirmed** 또는 **Registering**이 표시되고 Attention 패널에 "Registration not confirmed" 카드와 **Retry the saved registration**이 나타납니다. 큐브 전원을 유지하고 **Send saved mapping**으로 재스캔 없이 저장 태그를 재전송하거나 **Register**로 새 스캔을 합니다. 새 태그 수락 전까지 이전 pending 예약이 유지됩니다. 등록을 가능하게 하려고 기록을 해제하지 않습니다.
- **Tag belongs to another cube:** an accepted interactive scan transfers ownership atomically, including another cube's pending reservation. The former owner may lose its tag but keeps its number; both devices get an audit event and the timeline says which cube lost the tag. This does not erase the old cube's firmware; isolate/re-register it as appropriate and distribute the new database.<br>다른 큐브 소유 태그: 수락된 인터랙티브 스캔은 다른 큐브의 pending 예약까지 포함해 소유권을 원자적으로 이전합니다. 이전 소유 큐브는 태그를 잃을 수 있지만 번호는 유지합니다. 두 장비 모두 감사 이벤트가 기록되고 타임라인에 태그를 잃은 큐브가 표시됩니다. 이전 큐브 펌웨어는 지워지지 않으므로 필요 시 분리·재등록하고 새 DB를 배포합니다.
- **Wrong number:** the number field on the card renames in place and preserves MAC/tag. An occupied number requires first renaming the other device to an unused number. Renaming is unavailable while a pending registration is open ("Finish or retry the pending registration before renaming"). An offline rename is saved but not sent: reconnect and **Send saved mapping**, then Sync/distribute.<br>잘못된 번호: 카드의 번호 입력란에서 바로 변경하며 MAC·태그를 유지합니다. 이미 사용 중인 번호라면 기존 장비를 미사용 번호로 먼저 변경합니다. pending 등록이 열려 있으면 변경할 수 없습니다("Finish or retry the pending registration before renaming"). 오프라인 번호 변경은 저장만 되므로 재연결 후 **Send saved mapping** 및 Sync·배포가 필요합니다.
- **Original # differs:** original-32 data is historical, not current authority; the card shows it separately. Do not restore old numbers automatically. Inventory › Cubes › **Transmit original 32** is not the normal repair workflow and rejects altered original mappings.<br>Original 번호 불일치: original-32는 과거 자료이며 현재 기준이 아닙니다. 카드에 별도로 표시됩니다. 옛 번호를 자동 복원하지 않습니다. Inventory › Cubes › **Transmit original 32**는 일반 복구 절차가 아니며 원 매핑 변경 시 거부됩니다.
- **Reserved 2, 22, 39, 43:** automatic suggestions skip them; explicit manual entry is allowed for the corresponding labelled physical device.<br>예약 번호 2, 22, 39, 43: 자동 제안에서는 제외하지만 해당 실물 라벨 장비에 명시적으로 입력할 수 있습니다.
- **Another USB cube appears:** the console stops the active pairing operation before moving the pin to the new cube and logs "Stopped the active pairing operation before pinning …". Re-check the selected MAC and start deliberately; an interrupted operation never continues on another cube.<br>다른 USB 큐브 등장: 콘솔은 진행 중인 등록을 중지한 뒤 고정을 새 큐브로 옮기고 "Stopped the active pairing operation before pinning …"을 기록합니다. 선택 MAC을 다시 확인하고 명시적으로 시작합니다. 중단된 작업이 다른 큐브에서 이어지는 일은 없습니다.
- **Wrong/unverified firmware:** the cube card's Firmware tab compares the reported version with the local build (**Version matches** / **Update needed** / **Not verified**). A USB descriptor proves chip identity only; missing response means unverified. Use chapter 04 when appropriate.<br>펌웨어 불일치·미검증: 큐브 카드의 Firmware 탭이 보고 버전과 로컬 빌드를 비교합니다(**Version matches** / **Update needed** / **Not verified**). USB 식별자는 칩 신원만 증명하며 응답 없음은 미검증입니다. 필요 시 04장을 사용합니다.
- **Pair new cubes (auto):** the station panel's **Pair new cubes (auto)** discovers unregistered cubes, flashes each in turn and waits for its tag, assigning numbers automatically. Use **Skip** / **Retry paused** / **Stop** on the same panel. Existing mappings are skipped.<br>Pair new cubes (auto): 스테이션 패널의 **Pair new cubes (auto)**는 미등록 큐브를 찾아 차례로 점멸시키고 태그를 기다리며 번호를 자동 부여합니다. 같은 패널의 **Skip** / **Retry paused** / **Stop**을 사용합니다. 기존 매핑은 건너뜁니다.

**Terminology trap:** on the station panel and the cube card, **Flash (identify)** means blinking LEDs to find a cube; **Flash cube firmware** on the cube's Firmware tab writes firmware. The tooltips say which.
용어 주의: 스테이션 패널과 큐브 카드의 **Flash (identify)**는 식별용 LED 점멸입니다. 큐브 Firmware 탭의 **Flash cube firmware**는 펌웨어 쓰기입니다. 툴팁에 구분이 적혀 있습니다.

## Sources | 근거

`pairing_station/controller.py`, `database.py` (unchanged and reused by the console); `console/hub.py` (USB identification and pinning, stop-before-pin), `console/state.py` (`capabilities`: the reasons shown when Register, Send saved mapping or rename is unavailable), `console/commands.py` (`pairing.*`), `console/sessions/station.py`, `console/regflow.py` and `console/web/panels/RegisterSection.js` (the Register page). Evidence class: code-inspected; the register → READY → TAG DETECTED → REGISTERED sequence and the Register page are simulation-verified (`console/tests/test_docscenes.py`, `console/tests/test_regflow.py`); the Register page has not yet been run with a real cube, station or tag; the real radio was exercised only for discovery and identify with the attached dongle (chapter 15).
위 소스 기준. 근거 구분: 코드 확인. 등록 → READY → TAG DETECTED → REGISTERED 순서와 Register 페이지는 시뮬레이션 확인(`console/tests/test_docscenes.py`, `console/tests/test_regflow.py`). Register 페이지는 아직 실제 큐브·스테이션·태그로 실행하지 않았습니다. 실제 무선은 연결된 동글로 discover·identify만 실행했습니다(15장).

## Related guides | 관련 안내

{{page:00}}
{{page:04}}
{{page:06}}
{{page:05}}
