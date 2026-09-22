> <span color="red">*This document was written by Kimchi and Chips*</span>

## Identify the role before flashing | 플래싱 전 역할 확인

Plug the board into the console. A zone board that runs current firmware answers `?` with its report and is identified without a reset: the device rail shows its name, kind, point, firmware and database version, and the Zone panel opens. A board that does not answer appears as **Unidentified board**; its panel offers **Identify via bootloader** (the tooltip says it resets the board into the bootloader and reboots it afterwards), which reads the database identity, stored zone identity and legacy signatures. Treat that step as maintenance, not passive monitoring.
보드를 콘솔에 꽂습니다. 최신 펌웨어를 실행하는 존 보드는 `?`에 보고로 응답하여 리셋 없이 식별됩니다. 장치 레일에 이름·종류·포인트·펌웨어·DB 버전이 표시되고 Zone 패널이 열립니다. 응답이 없는 보드는 **Unidentified board**로 표시되며 패널의 **Identify via bootloader**(툴팁: 부트로더로 리셋 후 재부팅)가 DB 신원, 저장된 존 신원, 과거 코드 서명을 읽습니다. 이 단계는 단순 모니터링이 아닌 유지보수로 취급합니다.

## Reset Plate zone | 리셋 플레이트 존

**Reset Plate** is a zone firmware. Tagging a cube on a Reset Plate returns it to **idle mode** (low white LED). Use it to park cubes that are in a brighter mode: taking a cube off a visitor and setting it aside in idle mode preserves battery life. Two devices are currently flashed with it, both ESP32 SuperMini boards with an NFC reader attached and **no external antenna**. In the console's provisioning form it is the profile **Reset plate** (kind 5).
Reset Plate는 존 펌웨어입니다. 리셋 플레이트에 큐브를 태그하면 큐브가 idle 모드(약한 흰색 LED)로 돌아갑니다. 밝은 모드인 큐브를 관람객에게서 회수해 따로 둘 때 사용하면 배터리 소모를 줄일 수 있습니다. 현재 이 펌웨어로 플래싱된 장치는 2대이며 둘 다 NFC 리더를 부착한 ESP32 SuperMini 보드, 외부 안테나 없음입니다. 콘솔 프로비저닝 폼에서는 프로파일 **Reset plate**(종류 5)입니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. The zone flash job is scripted (no esptool ran); the stages are the real pipeline's. Keep USB intake off for this one-board workflow.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 존 플래시 작업은 스크립트 연출(esptool 미실행)이며 단계는 실제 파이프라인과 같습니다. 단일 보드 절차에서는 USB intake를 꺼 두세요.

### 1. A blank board: the provisioning form | 빈 보드: 프로비저닝 폼
{{shot:07-1}}
A blank board: Firmware & database with the provisioning form / 빈 보드: 프로비저닝 폼이 있는 Firmware & database

### 2. Flashing the zone | 존 플래시
{{shot:07-2}}
Flashing the zone: firmware, configuration and database in one job / 존 플래시: 펌웨어·설정·데이터베이스를 한 작업으로

### 3. Verified | 검증 완료
{{shot:07-3}}
Verified: the report after reboot matches what was written / 검증 완료: 재부팅 후 보고가 기록 내용과 일치

### 4. Cube monitor | 큐브 모니터
{{shot:07-4}}
Cube monitor: a tag was read and the cube found / 큐브 모니터: 태그를 읽고 큐브를 찾음

The unknown-tag case is in the console-specific capture {{shot:C-2}} (Unknown tag on the plate, known here: **Update database over USB**).
알 수 없는 태그 사례는 콘솔 전용 화면 {{shot:C-2}}(플레이트에서 알 수 없는 태그, 여기서는 알려짐: **Update database over USB**)에 있습니다.

## Replace one reader board | 리더 보드 한 개 교체

1. Record the old physical location, role, point/ID, name, MAC, gain and database version (the old board's Zone panel header and Firmware & database tab show all of them). For Pool also record radio ID and saved calibration/tuning (Calibration tab). Photograph the installed wiring for the local maintenance record.<br>기존 위치·역할·포인트/ID·이름·MAC·게인·DB 버전을 기록합니다(기존 보드의 Zone 패널 헤더와 Firmware & database 탭에 모두 표시). 풀존은 라디오 ID와 저장 보정·튜닝(Calibration 탭)도 기록합니다. 현장 유지보수 기록용 배선 사진을 남깁니다.
2. **Sync** first so the published cube database is current. The Firmware & database tab warns when the local mappings differ from the publication and when the zone build is stale (**Cube firmware build needs attention** / **… firmware: Firmware source changed since the last build**); resolve these before flashing: **Rebuild** on This computer › Firmware builds, and **Sync & publish**.<br>먼저 **Sync**하여 게시 큐브 DB를 최신화합니다. Firmware & database 탭은 로컬 매핑이 게시본과 다르거나 존 빌드가 오래되었을 때(**… firmware: Firmware source changed since the last build**) 경고합니다. 플래싱 전 This computer › Firmware builds의 **Rebuild**와 **Sync & publish**로 해결합니다.
3. Plug in the identified replacement. On **Firmware & database**, the form is prefilled from the board's current identity if it has one; choose the correct profile, point, name and RX gain. Use Preshow points 1–4 and Pool radio IDs 1–6 according to their actual positions. A Mainshow entrance uses TagPlateZone with the mainshow entrance profile, not MainshowController firmware.<br>식별된 교체품을 꽂습니다. **Firmware & database**의 폼은 보드에 신원이 있으면 미리 채워집니다. 올바른 프로파일·포인트·이름·게인을 선택합니다. 프리쇼 1–4, 풀존 1–6은 실제 위치와 맞춥니다. 메인쇼 입구는 입구 프로파일의 TagPlateZone이며 MainshowController 펌웨어가 아닙니다.
4. Click **Flash firmware + identity + database** and read the job card: build check, write, configuration and published database, readback, reboot and report verification. **Verified** means the report after reboot matches what was written. The console does not make a backup of the old firmware for a normal zone flash; arrange an explicit technical backup before repurposing a board whose previous image matters.<br>**Flash firmware + identity + database**를 누르고 작업 카드를 읽습니다: 빌드 확인, 쓰기, 설정·게시 DB, 읽기 검증, 재부팅, 보고 확인. **Verified**는 재부팅 후 보고가 기록 내용과 일치한다는 뜻입니다. 일반 존 플래시에서 콘솔은 기존 펌웨어를 백업하지 않으므로 기존 이미지가 중요한 장비 재사용 전 기술자가 별도 백업해야 합니다.
5. Verify the replacement's role, point, reader pins/gain, current database and real NFC scans on the **Monitor** tab. Test both cube colour and the actual downstream light/media effect. Retire the old board from the same physical role and update the equipment list.<br>**Monitor** 탭에서 교체품의 역할·포인트·리더 핀·게인·최신 DB·실제 NFC 스캔을 확인합니다. 큐브 색과 후단 조명·미디어를 모두 테스트합니다. 기존 보드를 같은 역할에서 제외하고 장비 목록을 갱신합니다.
6. For a batch, **This computer › USB intake › Auto-flash zones** with an intentional set of zone boards only: identified zones are updated in place (identity and gain kept); legacy sketches take the selected zone and point from the intake form; the "unidentified boards" option opts into writing unknown boards as the selected profile. Finish with the switch off (**Stop after current** lets a running write finish).<br>일괄 작업은 지정된 존 보드만 있는 상태에서 **This computer › USB intake › Auto-flash zones**를 사용합니다. 식별된 존은 신원·게인을 유지한 채 갱신되고, 과거 스케치는 인테이크 폼의 존·포인트를 받으며, "unidentified boards" 옵션은 알 수 없는 보드를 선택 프로파일로 쓰는 선택입니다. 완료 후 스위치를 끕니다(**Stop after current**는 진행 중 쓰기를 마치게 함).

## Database only, over USB | USB로 데이터베이스만

**Update database over USB** on the Firmware & database tab writes only the published cube database into the board's database slot; firmware and identity are untouched, the board reboots and reports the new version. It is offered when the board's database is older than the publication, and it is the action on the Attention card "Unknown tag on … is cube #… — the plate's database is behind". Zones only accept a newer version; a board already current is skipped. With Settings › Automatic updates › zone databases over USB on (the default), the console does this by itself when a configured zone that is behind is plugged in, once per board and publication, and the Firmware & database tab shows the result on an **Automatic database update** row. It does not need Auto-flash zones.
Firmware & database 탭의 **Update database over USB**는 게시 큐브 DB만 보드의 DB 슬롯에 씁니다. 펌웨어·신원은 그대로이며 보드가 재부팅 후 새 버전을 보고합니다. 보드 DB가 게시본보다 오래됐을 때 제공되며 Attention 카드 "Unknown tag on … is cube #… — the plate's database is behind"의 동작입니다. 존은 더 새로운 버전만 받으며 이미 최신인 보드는 건너뜁니다. Settings › Automatic updates의 USB 존 DB 설정이 켜져 있으면(기본값) 뒤처진 설정 완료 존을 꽂을 때 콘솔이 보드·게시본당 한 번 자동으로 실행하고, Firmware & database 탭의 **Automatic database update** 행에 결과를 표시합니다. Auto-flash zones가 필요하지 않습니다.

## Avoid accidental repurposing | 의도치 않은 용도 변경 방지

Do not use **Force flash (overwrite)** as a normal remedy for a refused device. It is a press-and-hold action whose tooltip states the consequence: it can deliberately convert a known cube to a zone and release its number/UID/pending association after writing; the already published database may still contain the old mapping until you publish and distribute again. Excluded device records are handled differently. The original pairing station and non-ESP32 devices remain protected.
거부된 장비에 **Force flash (overwrite)**를 일반 해결책으로 사용하지 않습니다. 길게 누르기 동작이며 툴팁에 결과가 적혀 있습니다: 알려진 큐브를 존으로 전환하고 쓰기 후 번호·UID·pending을 해제할 수 있습니다. 이미 게시된 DB에는 이전 매핑이 남을 수 있으므로 다시 게시·배포해야 합니다. excluded 장비 기록은 다르게 처리합니다. 원 등록 스테이션과 비ESP32 장치는 계속 보호됩니다.

PreshowBridge, PoolCentral and MainshowController have different firmware/partition roles; the console opens dedicated panels for them and never offers them zone firmware. PoolCentral and its radios should be maintained as a compatible set, central first. Updated preshow plates and the bridge can be installed in either order because of their legacy transition behaviour, but both must be current for the acknowledged link.
PreshowBridge, PoolCentral, MainshowController는 펌웨어·파티션 역할이 다르므로 콘솔은 전용 패널을 열며 존 펌웨어를 제공하지 않습니다. 풀 중앙과 라디오는 호환 세트로 유지하고 중앙부터 업데이트합니다. 프리쇼는 레거시 전환 지원으로 어느 쪽부터 설치해도 되지만 확인응답 통신에는 양쪽 최신화가 필요합니다.

## Cube monitor | 큐브 모니터

The Zone panel's **Monitor** tab attaches to the identified USB zone and shows the tag UID, cube number/MAC, lookup result, radio delivery and the reader health (NFC scanning / degraded / not responding). Its LED ring draws the commanded colour; use actual observation to confirm light. The history lists recent taps. Unknown tags need registration or a current lookup database, and the Attention panel says which: "Unknown tag on … is cube #… — the plate's database is behind" (**Update database over USB** / **Update database over the air**), "… not yet in the published database" (**Sync & publish**), "… is a pending registration for cube #…" (**Retry the saved registration**), or an unknown tag nobody has registered (**Register at the station**).
Zone 패널의 **Monitor** 탭은 식별된 USB 존에 연결하여 태그 UID·큐브 번호/MAC·조회 결과·무선 전달·리더 상태(NFC scanning / degraded / not responding)를 보여 줍니다. LED 원형 표시는 명령 색상이며 실제 조명은 눈으로 확인합니다. 이력에 최근 태그가 나열됩니다. 알 수 없는 태그는 등록 또는 최신 조회 DB가 필요하며 Attention 패널이 어느 쪽인지 알려 줍니다: "Unknown tag on … is cube #… — the plate's database is behind"(**Update database over USB** / **Update database over the air**), "… not yet in the published database"(**Sync & publish**), "… is a pending registration for cube #…"(**Retry the saved registration**), 아무도 등록하지 않은 태그(**Register at the station**).

**Flash 5 s**, **Clear** (idle white), **Preshow / Desert / Pool / Mainshow** (Set zone) and **Stop flashing** send real cube commands to the cube on this plate; the zone buttons are one-click hardware buttons with tooltips. A real tap takes priority over test flashing. The **Console** tab shows the plate's raw serial lines and accepts commands (`db`, `log`, `?`).
**Flash 5 s**, **Clear**(대기 흰색), **Preshow / Desert / Pool / Mainshow**(Set zone), **Stop flashing**은 이 플레이트의 큐브에 실제 명령을 보냅니다. 존 버튼은 툴팁이 있는 한 번 클릭 하드웨어 버튼입니다. 실제 태그가 테스트 점멸보다 우선합니다. **Console** 탭은 플레이트의 원시 시리얼 줄을 보여 주고 명령(`db`, `log`, `?`)을 받습니다.

## Sources | 근거

`zones/flasher/zone_detect.py`, `zone_flash.py` (incl. `update_database`), `zone_monitor.py`, `zone_build.py` (reused unchanged); `console/sessions/zone_console.py`, `console/jobs/zone.py`, `console/intake.py`, `console/advisor.py` (`tag.*`, `flash.*`, `zone.*`). Evidence class: code-inspected; monitor taps, the unknown-tag cards and the scripted flash are simulation-verified; no zone board was flashed through the console while writing this handover.
위 소스 기준. 근거 구분: 코드 확인. 모니터 태그, 알 수 없는 태그 카드, 스크립트 플래시는 시뮬레이션 확인. 본 문서 작성 중 콘솔로 존 보드를 플래싱하지 않았습니다.

## Related guides | 관련 안내

{{page:00}}
{{page:06}}
{{page:08}}
{{page:10}}
