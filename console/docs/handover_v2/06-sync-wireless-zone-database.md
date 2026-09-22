> <span color="red">*This document was written by Kimchi and Chips*</span>

## When to do this | 실행 시점

After registering, renumbering, replacing or transferring a cube/tag, and after receiving other computers' inventory changes. In the console this is two steps: **Sync** in the top bar (inventory both ways plus zone database publish/pull), then the **Zone relay** tab of the connected pairing station, ESP-NOW dongle or General Radio to bring the zones up to date over the air.
큐브·태그 등록, 번호 변경, 교체, 소유권 이전 또는 다른 컴퓨터의 변경 수신 후 실행합니다. 콘솔에서는 두 단계입니다: 상단의 **Sync**(인벤토리 양방향 + 존 DB 게시/다운로드), 그리고 연결된 등록 스테이션·ESP-NOW 동글·General Radio의 **Zone relay** 탭에서 무선으로 존을 최신화합니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. The capture is offline to protect the live inventory; in normal use complete Sync first. A cached publication can still be distributed offline. The captures show automatic updates switched off so the scenes stay put; on site they are on by default.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 실제 운영 인벤토리를 보호하기 위해 촬영 환경은 오프라인입니다. 정상 운영 시 먼저 Sync를 완료하세요. 캐시된 게시본은 오프라인에서도 배포할 수 있습니다. 화면 유지를 위해 촬영 시 자동 업데이트를 껐으며, 현장 기본값은 켜짐입니다.

### 1. Zone relay: every zone in range | Zone relay: 범위 내 모든 존
{{shot:06-1}}
Zone relay: every zone in range with its database version and signal / Zone relay: 범위 내 모든 존과 데이터베이스 버전, 신호

### 2. Update all: chunks are being sent | Update all: 청크 전송 중
{{shot:06-2}}
Update all: chunks are being sent to the zones that are behind / Update all: 뒤처진 존에 청크 전송 중

### 3. Database v32 confirmed on the plate | 플레이트에서 v32 확인됨
{{shot:06-3}}
Database v32 confirmed on the plate / 플레이트에서 데이터베이스 v32 확인됨

### 4. Auto-update all while walking | 이동 중 Auto-update all
{{shot:06-4}}
Auto-update all while walking the space / 공간을 걸으며 Auto-update all

The Sync button and the Web sync plan are shown in the console-specific captures: {{shot:C-5}} (Sync `↑3 ↓2` and the Web sync plan) and {{shot:C-6}} (sign in once).
Sync 버튼과 Web sync 계획은 콘솔 전용 화면 {{shot:C-5}}(Sync `↑3 ↓2` 및 Web sync 계획)와 {{shot:C-6}}(한 번만 로그인)에 있습니다.

## Standard workflow | 표준 절차

**Automatic updates (default).** Settings › Automatic updates has four switches, all on by default and saved on this computer. With the first two on, a zone that is behind is updated as soon as the console can reach it, with no click: over the air through **one** relay (the pairing station if connected, else a General Radio; never two radios at once), and over USB for any configured zone plugged in (database only, identity and firmware untouched, once per board and publication, independent of Auto-flash zones). A zone reporting the same version with a different CRC (**Newer / differs**) is left alone. The manual steps below remain for a deliberate pass, a check, or when the switches are off. Unit- and simulation-verified only; not yet run against installed zones.
**자동 업데이트(기본).** Settings › Automatic updates에 네 개의 스위치가 있으며 모두 기본 켜짐이고 이 컴퓨터에 저장됩니다. 앞의 두 개가 켜져 있으면 뒤처진 존은 콘솔이 닿는 즉시 클릭 없이 업데이트됩니다. 무선은 **하나의** 릴레이(등록 스테이션이 있으면 스테이션, 없으면 General Radio. 두 무선을 동시에 쓰지 않음)로, USB는 꽂힌 설정 완료 존(DB만, 신원·펌웨어 그대로, 보드·게시본당 한 번, Auto-flash zones와 무관)에 적용됩니다. 같은 버전에 CRC가 다른 존(**Newer / differs**)은 건드리지 않습니다. 아래 수동 절차는 의도적인 점검이나 스위치가 꺼져 있을 때 사용합니다. 단위·시뮬레이션만 확인했으며 설치 존에서는 아직 실행하지 않았습니다.


1. Finish active registrations and flash operations (no job running, the station panel idle). Plug in the identified dongle or General Radio; the console opens its session without resetting it. Other apps must not hold its port: the console names the owner if the port is held elsewhere.<br>등록·플래싱 작업을 끝냅니다(작업 없음, 스테이션 패널 유휴). 식별된 동글 또는 General Radio를 꽂으면 콘솔이 리셋 없이 세션을 엽니다. 다른 앱이 포트를 잡고 있으면 안 되며, 포트가 다른 곳에 잡혀 있으면 콘솔이 소유 앱을 표시합니다.
2. On its panel read the relay firmware and channel 2. Current source is **nct-pairing-1.8-zones** (or **general-radio-1.2.0**). 1.7 supports signal bars but not RX gain control; the Attention card "Relay firmware … is older than …" says what is missing and offers **Write the relay firmware**. 1.6 lacks both.<br>패널에서 중계 펌웨어와 채널 2를 확인합니다. 현재 소스는 **nct-pairing-1.8-zones**(또는 **general-radio-1.2.0**)입니다. 1.7은 신호 막대만 지원하고 RX gain 제어는 없습니다. Attention 카드 "Relay firmware … is older than …"가 빠진 기능을 설명하고 **Write the relay firmware**를 제공합니다. 1.6은 둘 다 없습니다.
3. Click **Sync** in the top bar. The chip shows what it will move (`↑` uploads, `↓` downloads, and whether a zone database publish or pull is included). Enter the shared password once if the sign-in popover appears. Read the outcome in the timeline, including any local device that lost a conflicting number or tag. Downloads wait while a hardware operation runs here.<br>상단의 **Sync**를 누릅니다. 칩에 옮길 내용(`↑` 업로드, `↓` 다운로드, 존 DB 게시/다운로드 포함 여부)이 표시됩니다. 로그인 팝오버가 나오면 공유 비밀번호를 한 번 입력합니다. 충돌로 번호·태그를 잃은 로컬 장비 등 결과를 타임라인에서 읽습니다. 여기서 하드웨어 작업이 진행 중이면 다운로드는 대기합니다.
4. Check **Inventory › Zone database**: the published version, count and CRC, and that no local mapping changes remain unpublished (the Attention card "Local cube mappings differ from the published zone database" with **Sync & publish** means they do). Inventory synchronization and publication are separate stages: if publication failed after sync, the card "The inventory synced but the zone database was not published" offers **Publish zone database**.<br>**Inventory › Zone database**에서 게시 버전·개수·CRC와 미게시 로컬 변경이 없는지 확인합니다(Attention 카드 "Local cube mappings differ from the published zone database"와 **Sync & publish**가 있으면 미게시 변경이 있음). 인벤토리 동기화와 게시는 별도 단계이므로 Sync 후 게시만 실패했다면 카드 "The inventory synced but the zone database was not published"가 **Publish zone database**를 제공합니다.
5. Open the radio board's **Zone relay** tab. Click **Query zones** or switch on **Auto-refresh**. A zone is "in range" when it answered within 20 seconds; the table shows name, kind, point, firmware, database version, state pill and signal bars. Known zones that have not answered are listed as out of range (**Show out of range**); absent readers are not proven current. Reconcile the physical reader list.<br>무선 보드의 **Zone relay** 탭을 엽니다. **Query zones**를 누르거나 **Auto-refresh**를 켭니다. 20초 이내 응답한 존이 통신 범위 내로 표시되며 표에 이름·종류·포인트·펌웨어·DB 버전·상태 칩·신호 막대가 있습니다. 응답하지 않은 알려진 존은 범위 밖으로 표시됩니다(**Show out of range**). 보이지 않는 리더는 최신 확인이 된 것이 아닙니다. 실물 리더 목록과 대조합니다.
6. For one zone, click its **Update database over the air** (unicast announce, broadcast chunks). For every behind zone in range, click **Update all out-of-date zones**; it is a one-click hardware button whose tooltip states the effect. The progress area shows the zone being served and the chunk count; each zone's row turns **Current** when it reports the new version and CRC, and the timeline says "Database v… confirmed on n zone(s)".<br>한 존만 갱신하려면 해당 행의 **Update database over the air**(유니캐스트 안내, 브로드캐스트 청크)를 누릅니다. 범위 내 모든 구버전 존은 **Update all out-of-date zones**를 누릅니다. 툴팁에 효과가 적힌 한 번 클릭 하드웨어 버튼입니다. 진행 영역에 처리 중인 존과 청크 수가 표시되고, 각 존의 행은 새 버전·CRC를 보고하면 **Current**로 바뀌며 타임라인에 "Database v… confirmed on n zone(s)"가 표시됩니다.
7. For a walkaround, make sure **Auto-update all** is on (with Auto-refresh). This box is the same setting as Settings › Automatic updates › zone databases over the air; on a second relay it reads "· another relay is walking". Walk until every required reader has been seen and confirmed; a failed zone is retried after 30 seconds. The option does not update **Newer / differs** zones. The status bar shows that walkaround is on.<br>이동 점검은 **Auto-update all**(Auto-refresh와 함께)이 켜져 있는지 확인합니다. 이 체크박스는 Settings › Automatic updates의 무선 존 DB 설정과 같으며, 두 번째 릴레이에서는 "· another relay is walking"으로 표시됩니다. 필요한 모든 리더를 관측·확인할 때까지 이동합니다. 실패 존은 30초 후 재시도합니다. **Newer / differs** 존은 자동 갱신하지 않습니다. 상태 표시줄에 walkaround 켜짐이 표시됩니다.
8. Click **Stop** to end a manual update; leave **Auto-update all** as agreed for opening hours (on by default). Record exceptions and test a changed cube at representative readers, including previously failing points.<br>수동 업데이트는 **Stop**으로 끝냅니다. **Auto-update all**은 운영 시간에 대한 합의대로 둡니다(기본 켜짐). 예외를 기록하고 이전 실패 지점을 포함한 대표 리더에서 변경 큐브를 테스트합니다.

## Interpret results | 결과 해석

- **Current:** version and CRC match the publication. **Out of date:** older version. **Updating:** staging chunks. **Newer / differs:** higher version or same version with different content; not a routine overwrite case, and shown as a red Attention card "Zone … holds v…, above this computer's v…".<br>Current: 버전·CRC 일치. Out of date: 낮은 버전. Updating: 청크 준비 중. Newer / differs: 높은 버전 또는 동일 버전·다른 내용이며 일반 덮어쓰기 대상이 아닙니다. 빨간 Attention 카드 "Zone … holds v…, above this computer's v…"로 표시됩니다.
- For **Newer / differs**, first receive the correct shared inventory (**Sync (pulls the database)** on the card) and publish with the current software. The server allocates above the highest known version when needed. Do not invent a local version or use a forced downgrade as normal operation.<br>Newer / differs는 올바른 공유 인벤토리를 먼저 받은 뒤(카드의 **Sync (pulls the database)**) 현재 소프트웨어로 게시합니다. 필요 시 서버가 알려진 최고 버전보다 높게 할당합니다. 임의 로컬 버전이나 강제 다운그레이드를 일반 절차로 사용하지 않습니다.
- A transfer finishes only when the zone reports the intended version and CRC. Chunk transmission or radio delivery alone is insufficient; the timeline's "delivered" lines are radio acknowledgments. The relay waits up to 45 seconds; partial staging expires after 60 seconds without chunks; a zone that did not confirm gets the card "Zone … did not confirm database v…".<br>존이 목표 버전·CRC를 보고해야 전송 완료입니다. 청크 송신·무선 전달만으로는 부족하며 타임라인의 "delivered"는 무선 ACK입니다. 릴레이는 최대 45초 대기하며 청크 없이 60초가 지나면 부분 준비 데이터가 만료됩니다. 확인하지 않은 존에는 카드 "Zone … did not confirm database v…"가 표시됩니다.
- If USB drops, the run stops; the console closes the session and re-identifies the board when it returns. Review the relay table after reconnecting instead of assuming all zones finished. Re-announcing the same version can resume valid partial staging.<br>USB가 끊기면 실행이 중지되고 콘솔은 세션을 닫았다가 보드가 돌아오면 다시 식별합니다. 전체 완료를 가정하지 말고 재연결 후 relay 표를 검토합니다. 같은 버전 재안내로 유효한 부분 전송을 재개할 수 있습니다.

## NFC sensitivity is separate from radio strength | NFC 감도와 무선 세기는 별개

**Set RX gain** on a zone's row changes that reader's PN532 gain (18, 23, 33, 38, 43, 48 dB) over the air. It preserves identity/calibration, stores the setting and applies it without reboot. The console waits for the settings report ("Waiting for … to confirm RX gain … dB"); 10 seconds without a reply is unconfirmed, and "stored but the reader did not accept it" is a warning card. "—" can mean unsupported firmware or no report. The same setting is available over USB on the zone's **Firmware & database** tab.
존 행의 **Set RX gain**은 해당 리더의 PN532 게인(18, 23, 33, 38, 43, 48 dB)을 무선으로 변경합니다. 신원·보정값을 유지하고 저장 후 재부팅 없이 적용합니다. 콘솔은 설정 보고를 기다리며("Waiting for … to confirm RX gain … dB") 10초 동안 응답이 없으면 미확인이고, "stored but the reader did not accept it"는 경고 카드입니다. "—"는 미지원 펌웨어 또는 보고 없음을 뜻할 수 있습니다. 같은 설정을 USB로는 존의 **Firmware & database** 탭에서 할 수 있습니다.

All preshow readers were reported set to 48. Higher gain can help weak coupling but can increase noise; positioning is still important. The **Signal** bars instead measure the dongle's reception of a zone's radio: strong at −67 dBm or better, fair down to −80, weak below that. Neither metric proves the complete visitor effect.
프리쇼 리더 전체는 48로 설정되었다고 보고되었습니다. 높은 게인은 약한 결합을 돕지만 노이즈도 늘 수 있어 위치가 중요합니다. 반면 **Signal** 막대는 동글이 받은 존 무선 신호이며 −67 dBm 이상 강함, −80까지 보통, 그 미만 약함입니다. 어느 값도 전체 체험 성공을 증명하지는 않습니다.

Each zone row also offers **Identify** (the plate blinks its reader LED for 10 s so you can find it), **Request log** (the plate's recent tag log) and **Reboot** (over the air, one-click hardware button).
각 존 행에는 **Identify**(플레이트가 10초 동안 리더 LED를 점멸해 위치 확인), **Request log**(플레이트의 최근 태그 기록), **Reboot**(무선, 한 번 클릭 하드웨어 버튼)도 있습니다.

## Provision a replacement dongle or General Radio | 동글·General Radio 교체 준비

Plug in a spare ESP32-C3 intended for relay use. It appears as an **Unidentified board** (or as a cube if it was one); its panel offers **Write the relay firmware**, **Write the Mainshow controller firmware** and **make this a General Radio**. The pipeline refuses known cubes in use, zones, the protected original station and the recorded Mainshow controller unless you deliberately use the force path; it backs up the first-time flash, preserves NVS, verifies and reconnects, then records the board as excluded from cube work. A dongle needs no NFC reader.
중계용으로 지정한 예비 ESP32-C3를 꽂습니다. **Unidentified board**(원래 큐브였다면 큐브)로 표시되며 패널에서 **Write the relay firmware**, **Write the Mainshow controller firmware**, **make this a General Radio**를 제공합니다. 파이프라인은 사용 중인 큐브·존·보호된 원 스테이션·기록된 메인쇼 컨트롤러를 강제 경로를 명시적으로 쓰지 않는 한 거부합니다. 최초 플래시를 백업하고 NVS를 보존·검증·재연결한 뒤 큐브 작업 제외 역할을 기록합니다. 동글에는 NFC 리더가 필요하지 않습니다.

## Sources | 근거

`pairing_station/zone_registry.py`, `sync_all.py`, `zone_publish.py`, `zones/dbmanager/dongle.py` (reused unchanged); `console/sessions/station.py` (registry on the station link), `console/commands.py` (`zones.*`, `sync.*`), `console/jobs/sync.py`, `console/advisor.py` (`zone.db_*`, `sync.*`, `dongle.old`). Evidence class: code-inspected; publish → confirm is simulation-verified; **dongle-verified** for identify, connect, Query zones, Identify, Request log on the real dongle (chapter 15). Screenshot versions/counts are examples, not live inventory.
위 소스 기준. 근거 구분: 코드 확인. 게시 → 확인은 시뮬레이션 확인. 실제 동글로 식별·연결·Query zones·Identify·Request log를 **동글 확인**(15장). 화면의 버전·개수는 실제 인벤토리가 아닌 예시입니다.

## Related guides | 관련 안내

{{page:00}}
{{page:05}}
{{page:07}}
