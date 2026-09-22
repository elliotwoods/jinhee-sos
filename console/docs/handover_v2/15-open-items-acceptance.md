> <span color="red">*This document was written by Kimchi and Chips*</span>

## Handover status | 인수인계 상태

The latest field reports say the exhibition interactions are broadly working. This page records the remaining decisions and the physical checks needed to turn those reports into a signed operating handover, and — new in this version — the checks the NCT Console itself still needs on hardware. Suggested owners below are routing recommendations, not newly agreed contractual assignments.
최신 현장 보고는 전시 인터랙션이 전반적으로 동작한다고 설명합니다. 이 페이지는 보고를 공식 운영 인계로 전환하는 데 필요한 결정·실물 점검, 그리고 이 판에서 새로 추가된 NCT Console 자체의 실물 점검 항목을 기록합니다. 아래 담당 제안은 전달 경로이며 새로 합의된 계약상 업무 배정이 아닙니다.

## Decisions and unresolved evidence | 결정·미확인 근거

- [ ] **Pool printed names:** Amberin/Lotte to confirm covering/removing labels or another visitor-facing treatment. Engineering Six to implement the agreed treatment and check repeatability. Do not mark accepted until the decision is recorded.<br>풀존 인쇄 이름: 앰버린·롯데가 가림·제거 또는 대체 안내를 확인하고 엔지니어링식스가 합의안을 적용·반복 점검합니다. 결정 기록 전 승인 완료로 처리하지 않습니다.
- [ ] **Desert alignment:** Engineering Six/carpentry team to identify the reported Jisung/Jimin positions, record exact physical point IDs and correct mounting where needed. Retest through the finished table surface.<br>사막 정렬: 엔지니어링식스·목공팀이 보고된 지성/지민 위치와 실제 포인트 ID를 확인하고 필요한 장착을 수정합니다. 완성 테이블 표면을 통해 재시험합니다.
- [ ] **Battery endurance:** operator to measure preshow USB-battery runtime and cube turnaround/charging capacity under actual exhibition use. Record approved swap intervals; small LiPo fallback is not established.<br>배터리 지속 시간: 운영사가 실제 전시 조건의 프리쇼 USB 배터리 시간, 큐브 회전·충전 용량을 측정하고 교체 주기를 기록합니다. 소형 LiPo 대안은 확보되지 않았습니다.
- [ ] **Failed mainshow cube:** locate the specific cube from Elliot's 1-of-10 test, record its number/MAC, diagnose, reflash/re-register as needed and retest. Its identity is not supplied in the report.<br>메인쇼 실패 큐브: Elliot의 10개 중 1개 테스트 대상 실물을 찾아 번호/MAC을 기록하고 진단·필요 시 재플래시/재등록·재시험합니다. 보고에 신원은 없습니다.
- [ ] **Cube availability:** reconcile usable, spare, faulty and charging stock against the actual audience/show plan. The original PDF's intended quantity and the repair page's shortage note are not a current stock count.<br>큐브 가용 수량: 실제 관람·쇼 계획과 사용 가능·예비·불량·충전 수량을 대조합니다. 원 PDF 계획 수량과 수리 페이지 부족 언급은 현재 재고 실사가 아닙니다.
- [ ] **Media handover:** media team to record TouchDesigner project/version, Serial DAT identity, points 1–4 routing, startup procedure and the mainshow cue timing.<br>미디어 인계: 미디어팀이 TouchDesigner 프로젝트·버전, Serial DAT, 포인트 1–4 매핑, 시작 절차, 메인쇼 큐 시각을 기록합니다.
- [ ] **Mainshow signal interface:** photograph/document the installed 5V-to-controller interface, connector labels, polarity and pinout before replacement. The code's GPIO3 active-low contract does not document the fitted circuit.<br>메인쇼 신호 변환부: 교체 전 설치된 5V 변환부, 커넥터, 극성, 핀 배열을 기록합니다. 코드의 GPIO3 active-low 규약은 설치 회로도 자체가 아닙니다.
- [ ] **Release package:** engineering team to freeze an agreed source revision/snapshot (including the console and General Radio, uncommitted on 23 September) and matching build artifacts; reconcile the PoolCentral 40 MHz README versus generic build-all target. Record exact installed firmware and database versions per board.<br>릴리스 패키지: 기술팀이 소스 버전·사본(9월 23일 미커밋 상태인 콘솔·General Radio 포함)과 일치하는 빌드를 확정하고 풀 중앙 40 MHz README·일반 build-all 설정 차이를 해결합니다. 보드별 실제 펌웨어·DB 버전을 기록합니다.
- [ ] **Windows:** receiving team to perform hardware acceptance if Windows will be used (console native window needs WebView2; the browser fallback is untested on Windows hardware).<br>Windows: 사용 예정이면 인수팀이 실물 검수합니다(콘솔 네이티브 창은 WebView2 필요, 브라우저 대체는 Windows 실물 미검증).

## Console hardware verification | 콘솔 실물 검증

The console's logic is covered by its headless suite, but each path below has only been exercised against simulated boards and must be proven once on the real board before it replaces the separate app for that job. Until then the separate apps remain the verified route.
콘솔의 로직은 헤드리스 테스트로 검증되었지만 아래 각 경로는 시뮬레이션 보드로만 실행되었으므로 해당 작업에서 개별 앱을 대체하기 전에 실제 보드에서 한 번 검증해야 합니다. 그 전까지는 개별 앱이 검증된 경로입니다.

- [ ] **Registration through the console:** station + real cube: Register → READY → TAG DETECTED → REGISTERED, ACK recorded, Send saved mapping, tag transfer, USB pin replacement stopping an active operation.<br>콘솔 등록: 스테이션 + 실제 큐브: Register → READY → TAG DETECTED → REGISTERED, ACK 기록, Send saved mapping, 태그 이전, 진행 중 작업을 중지하는 USB 고정 교체.
- [ ] **Cube flash through the console** (`console/jobs/cube.py` over the unchanged `flashing_station/backend.py`): verified outcome, NVS preserved, Check boot, receipt in Inventory › Flash runs; USB intake with one cube.<br>콘솔 큐브 플래시(`console/jobs/cube.py`, 변경 없는 `flashing_station/backend.py` 사용): verified 결과, NVS 보존, Check boot, Inventory › Flash runs 영수증. 큐브 한 개로 USB intake.
- [ ] **Zone flash and Update database over USB** on a spare zone board; Cube monitor on a real plate; the unknown-tag card leading to a working tap.<br>예비 존 보드에서 존 플래시 및 Update database over USB. 실제 플레이트에서 Cube monitor. 알 수 없는 태그 카드에서 정상 태그까지.
- [ ] **Over-the-air update of an installed zone from the console** (v32 → the current publication) with confirmation; deliberately not performed for this documentation.<br>콘솔에서 설치 존 무선 업데이트(v32 → 현재 게시본) 및 확인. 본 문서 작업에서는 의도적으로 실행하지 않았습니다.
- [ ] **Pool calibration, guided recording and Apply & save** on a real radio; central telemetry on the Pool central panel.<br>실제 라디오에서 풀존 보정·가이드 녹화·Apply & save. Pool central 패널의 중앙 텔레메트리.
- [ ] **Preshow cue test** through a real plate and bridge (acknowledged in modern mode).<br>실제 플레이트·브리지로 프리쇼 큐 테스트(modern 모드에서 확인 응답).
- [ ] **Mainshow ① / ② / Stop → idle** on one cube through the Mainshow controller and through the General Radio.<br>메인쇼 컨트롤러와 General Radio로 큐브 한 개에 메인쇼 ① / ② / Stop → idle.
- [ ] **Register page** (plug in → number → NFC scan → sync, chapter 03) with a real station, cubes and tags, including an interrupted cube and a failed ACK with Retry. Simulation-verified only.<br>Register 페이지(꽂기 → 번호 → NFC 스캔 → 동기화, 03장)를 실제 스테이션·큐브·태그로 검증합니다. 중단된 큐브, ACK 실패 후 Retry 포함. 시뮬레이션만 확인했습니다.
- [ ] **Automatic updates** (Settings › Automatic updates, all on by default): zone databases over the air through one relay and over USB, the main show over the air, web pulls. Confirm on real zones and the dongle, and agree whether they stay on during opening hours. Unit/simulation-verified only.<br>자동 업데이트(Settings › Automatic updates, 모두 기본 켜짐): 하나의 릴레이를 통한 존 DB 무선·USB 업데이트, 메인쇼 무선 업데이트, 웹 가져오기. 실제 존과 동글로 확인하고 운영 시간 중 켜 둘지 합의합니다. 단위·시뮬레이션만 확인했습니다.
- [ ] **Show editor and the updatable show:** bench-checked on 23 September with cube #17 (v1.5.0 → v1.7.0: wireless update deferred until the show ended, NVS persistence, fanned show, live preview mirroring) and mainshow-1.3.0 timecode on the spare #138 — serial logs only, LEDs not watched. Still to do: flash the fleet to v1.7.0 (currently only #17), decide whether to update controller #134 to mainshow-1.3.0, publish the first site show (above v4), update all cubes and watch them play it across the room. The editor UI itself is simulation-verified; dragging a video in from Finder and audio are untested.<br>Show editor와 업데이트 가능한 쇼: 9월 23일 큐브 #17로 벤치 확인(v1.5.0 → v1.7.0: 쇼 종료까지 보류된 무선 업데이트, NVS 유지, 패닝 쇼, 실시간 미리보기 미러링) 및 예비 #138에서 mainshow-1.3.0 타임코드 확인. 시리얼 로그만, LED 미관찰. 남은 일: 전체 큐브 v1.7.0 플래시(현재 #17만), 컨트롤러 #134의 mainshow-1.3.0 업데이트 여부 결정, 첫 현장 쇼 게시(v4 초과), 전체 큐브 업데이트 후 공간 전체에서 재생 관찰. 에디터 UI는 시뮬레이션 확인이며 Finder에서 영상 끌어오기와 오디오는 미검증입니다.

## Dongle pass, 23 September | 동글 점검, 9월 23일

What the single attached ESP-NOW dongle (`AC:27:6E:82:68:54`, started as `nct-pairing-1.7-zones`, reflashed to `general-radio-1.1.0` by another task mid-pass; the results below are from the rerun on 1.1.0) proved on the real radio through the live console. Delivered means radio acknowledgment; acknowledged means the device answered; verified means read back. Nothing was flashed and no installed zone database was changed.
연결된 ESP-NOW 동글 한 개(`AC:27:6E:82:68:54`, 처음엔 `nct-pairing-1.7-zones`, 점검 중 다른 작업이 `general-radio-1.1.0`으로 재플래시하여 아래 결과는 1.1.0 재실행 기준)가 실제 콘솔로 실제 무선에서 증명한 내용. delivered는 무선 확인, acknowledged는 장치 응답, verified는 읽기 검증입니다. 플래싱과 설치 존 DB 변경은 없었습니다.

{{test-report-table}}

## Acceptance walk | 인수 검수

1. **Inventory:** sample physical labels against MAC/UID in Inventory › Cubes, confirm pending/unknown/excluded states are correctly understood, then demonstrate a new registration and a controlled retry on a designated test cube.<br>인벤토리: Inventory › Cubes에서 실물 번호·MAC·UID를 표본 비교하고 pending·미등록·excluded 의미를 확인한 뒤 지정 테스트 큐브의 새 등록·재시도를 시연합니다.
2. **Firmware:** flash one intended cube through the supported pipeline (console or separate app), retain receipt/NVS verification, confirm boot and actual LEDs. Power-cycle if persistence is part of acceptance.<br>펌웨어: 대상 큐브 한 개를 지원 경로(콘솔 또는 개별 앱)로 업데이트하고 영수증·NVS 검증을 보존하며 부팅·실제 LED를 확인합니다. 저장 지속성이 검수 항목이면 전원 재시작합니다.
3. **Database:** change a test mapping, Sync/publish, update every intended reader and record version/CRC from the Zone relay table. Demonstrate that a reader unseen by the relay is an exception, not an assumed success.<br>DB: 테스트 매핑 변경·Sync·게시 후 모든 대상 리더를 업데이트하고 Zone relay 표의 버전·CRC를 기록합니다. relay에서 미관측 리더는 성공 가정이 아닌 예외임을 확인합니다.
4. **Preshow:** all four points, real NFC through finished enclosure, cube red, correct butterfly cue and release. Repeat after bridge restart during a maintenance window.<br>프리쇼: 4개 포인트 모두 완성 외함을 통한 실제 NFC·큐브 빨강·정확한 나비 큐·해제를 확인합니다. 유지보수 중 브리지 재시작 후 반복합니다.
5. **Desert:** all 23 intended positions, panel and cube response separately; retest the corrected mounting locations. Reconcile the reported seven failures/eight replacements with the physical inventory.<br>사막: 23개 위치의 패널·큐브를 따로 확인하고 수정 장착 위치를 재시험합니다. 보고된 7개 실패·8개 교체를 실물 목록과 대조합니다.
6. **Pool:** all six radios and 23 frames; shared-frame OR, tag removal, communication loss release, stable lamps and agreed visitor interaction. Include sustained operation beyond the earlier reported 10–30 minute heat/flicker window, with duration/results recorded.<br>풀존: 라디오 6개·프레임 23개, 공유 프레임 OR, 태그 제거, 통신 손실 해제, 조명 안정성, 합의된 관람 체험을 확인합니다. 이전 10–30분 발열·점멸 보고 구간을 넘는 지속 테스트를 포함하고 시간·결과를 기록합니다.
7. **Mainshow:** entrance-ready tagging, actual scheduled media trigger and observation across the room; repeated show after rearming; distinguish transmitted trigger from cube playback.<br>메인쇼: 입구 준비 태그·실제 미디어 큐·공간 전역 관찰, 재준비 후 반복 쇼를 확인하고 트리거 송신과 큐브 재생을 구분합니다.
8. **Closeout:** USB intake off, Settings › Automatic updates left as agreed (on by default), every lease released (status bar empty), logs archived privately, spare stock and contact route confirmed, accepted exceptions recorded.<br>종료: USB intake 끄기, Settings › Automatic updates는 합의대로 유지(기본 켜짐), 모든 리스 해제(상태 표시줄 비어 있음), 로그 비공개 보관, 예비 수량·연락 경로 확인, 수용한 예외 기록.

## Sign-off record template | 검수 기록 양식

Date and venue · receiving operator · technical witness · source revision/build manifest · console version · tested board MACs/roles · cube numbers · zone versions/CRC · scenarios and actual results · remaining exceptions · responsible owner and agreed date · acceptance signatures.
일시·장소 · 인수 운영자 · 기술 입회자 · 소스 버전/매니페스트 · 콘솔 버전 · 보드 MAC/역할 · 큐브 번호 · 존 버전/CRC · 시험·실제 결과 · 잔여 예외 · 담당자/합의 일정 · 검수 서명.

Do not fill this template with simulated screenshot values. No acceptance signature has been entered by this documentation task; the only hardware results are the dongle pass above and the show-system bench checks listed under Console hardware verification.
시뮬레이션 화면의 예시 값으로 이 양식을 채우지 않습니다. 본 문서 작업에서는 검수 서명을 입력하지 않았으며 실물 결과는 위 동글 점검과 콘솔 실물 검증에 적은 쇼 시스템 벤치 확인뿐입니다.

## Related guides | 관련 안내

{{page:00}}
{{page:02}}
{{page:14}}
