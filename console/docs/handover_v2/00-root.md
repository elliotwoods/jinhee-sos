<span color="red">*This document was written by Kimchi and Chips*</span>

Kimchi and Chips → Amberin / Engineering Six
김치앤칩스 → 앰버린 / 엔지니어링식스

Documentation baseline: 23 September 2026 (KST), NCT Console 0.1.0 in the working copy after commit 7191c5d. Intervention began Thursday, 17 September 2026. This is **version 2** of the handover: the same sixteen chapters as the original, rewritten for the **NCT Console**, the single window that replaces the ten separate operator apps. The original handover ({{v1-root}}) stays unchanged and still describes the separate apps, which continue to work as a fallback.
문서 기준일: 2026년 9월 23일(한국 시간), 커밋 7191c5d 이후 작업 사본의 NCT Console 0.1.0. 기술 지원 시작일: 2026년 9월 17일 목요일. 이 문서는 인수인계 문서의 **2판**으로, 원본과 같은 16개 장을 열 개의 개별 운영 앱을 대체하는 단일 창 **NCT Console** 기준으로 다시 작성했습니다. 원본 인수인계({{v1-root}})는 변경 없이 유지되며 개별 앱을 계속 설명합니다. 개별 앱은 예비 수단으로 계속 동작합니다.

This handbook describes the repairs, firmware and operating tools implemented by Kimchi and Chips within the exhibition originally developed by Engineering Six. It combines source inspection, simulated console captures and attributed field reports; it is not a new hardware acceptance certificate.
이 문서는 엔지니어링식스가 최초 개발한 전시에서 김치앤칩스가 구현한 수리, 펌웨어 및 운영 도구를 설명합니다. 소스 검토, 시뮬레이션 콘솔 화면, 출처가 명시된 현장 보고를 종합한 자료이며, 새로운 하드웨어 검수 증명서는 아닙니다.

## Reading routes | 읽는 순서

The child pages below contain paired English and Korean instructions. Console control names remain in English so operators can find them on screen.<br>아래 하위 페이지에는 영어와 한국어 설명이 함께 있습니다. 실제 화면에서 찾기 쉽도록 콘솔 조작부 이름은 영어 그대로 표기합니다.

- **Floor operators / 현장 운영자:** start with 01 (visitor journey) and 02 (daily operation), then the relevant zone guide 08–11.<br>현장 운영자는 01·02를 먼저 읽고 해당 존의 08–11 안내를 확인합니다.
- **Cube desk / 큐브 담당:** follow 03 registration → 04 firmware when needed → 06 database distribution. Read 05 to understand the records.<br>큐브 담당은 03 등록 → 필요 시 04 펌웨어 → 06 DB 배포 순으로 진행하고 05에서 데이터 개념을 확인합니다.
- **Receiving engineers / 인수 기술자:** use 07 provisioning, 12 workstation/recovery and 13 engineering reference.<br>인수 기술자는 07 존 설정, 12 PC·복구, 13 기술 참조를 사용합니다.
- **Amberin / project management · 앰버린/프로젝트 관리:** 14 documents the intervention and source evidence; 15 lists remaining decisions and acceptance.<br>14는 개선 이력과 출처, 15는 남은 결정·검수 항목입니다.

## Quick access | 빠른 이동

{{page:02}}
{{page:03}}
{{page:06}}
{{page:15}}
{{page:16}}

## What changed from version 1 | 1판과 달라진 점

- **One window.** Pairing, cube flashing, zone flashing, the cube monitor, the Zone Database Manager, the Mainshow controller, pool calibration, the bench tools (pool light test, preshow cue test, range test), inventory, zone database and web sync are all in the NCT Console (`console/Launch.command` / `Launch.bat`). The console holds every old app's instance lock while it runs, so an old app and the console never share the database at the same time; each refuses to start and names the other.<br>**하나의 창.** 등록, 큐브 플래싱, 존 플래싱, 큐브 모니터, Zone Database Manager, 메인쇼 컨트롤러, 풀존 보정, 벤치 도구(풀존 조명 테스트, 프리쇼 큐 테스트, 거리 테스트), 인벤토리, 존 DB, 웹 동기화가 모두 NCT Console(`console/Launch.command` / `Launch.bat`)에 있습니다. 콘솔은 실행 중 모든 기존 앱의 인스턴스 잠금을 보유하므로 기존 앱과 콘솔이 같은 DB를 동시에 쓰지 않습니다. 서로 실행을 거부하고 상대 앱 이름을 표시합니다.
- **Device-centred.** There are no port pickers. A board plugged into USB is identified without being reset (the console asks `?`, a JSON `hello` or `STATUS`, never an arming command) and appears in the device rail with its role: cube, pairing station or dongle, zone plate, pool radio, preshow plate, Mainshow controller, General Radio, pool central, media bridge, test bridge, range test, or "unidentified board". Tasks start from the device's panel.<br>**장치 중심.** 포트 선택 창이 없습니다. USB에 꽂은 보드는 리셋 없이 식별되어(콘솔은 `?`, JSON `hello` 또는 `STATUS`만 보내고 arming 명령은 보내지 않음) 장치 레일에 역할과 함께 표시됩니다: 큐브, 등록 스테이션/동글, 존 플레이트, 풀존 라디오, 프리쇼 플레이트, 메인쇼 컨트롤러, General Radio, 풀 중앙, 미디어 브리지, 테스트 브리지, 거리 테스트, 또는 "미식별 보드". 작업은 장치 패널에서 시작합니다.
- **Suggestion cards instead of dialogs.** The Attention panel turns what the console knows into non-blocking cards: for example an unknown tag on a plate that this computer knows as cube #44 becomes "Unknown tag on "Preshow 1" is cube #44 — the plate's database is behind" with an **Update database over USB** button. Every card says what it knows, why it matters and what to check, and can be dismissed for this session.<br>**대화상자 대신 제안 카드.** Attention 패널은 콘솔이 아는 정보를 작업을 막지 않는 카드로 보여 줍니다. 예를 들어 이 컴퓨터가 큐브 #44로 알고 있는 태그를 플레이트가 모르면 "Unknown tag on "Preshow 1" is cube #44 — the plate's database is behind" 카드와 **Update database over USB** 버튼이 나타납니다. 모든 카드는 아는 사실, 중요한 이유, 확인할 사항을 적고 이 세션 동안 무시할 수 있습니다.
- **Hardware buttons run on one click with a warning tooltip; destructive actions need a press-and-hold.** Broadcasts to every cube, force flashing and unregistering ask for a hold that the backend enforces with a confirmation token, so the hold is not cosmetic. Nothing runs on its own.<br>**하드웨어 버튼은 경고 툴팁과 함께 한 번 클릭으로 실행되며, 파괴적 동작은 길게 누르기가 필요합니다.** 전체 큐브 브로드캐스트, 강제 플래시, 등록 해제는 백엔드가 확인 토큰으로 강제하는 길게 누르기를 요구하므로 형식적 절차가 아닙니다. 자동으로 실행되는 것은 없습니다.
- **Truth ladder on every outcome.** Sent → Delivered (radio acknowledgment only) → Acknowledged (the device answered) → Verified (read back) → Failed. Delivered is never shown as success.<br>**모든 결과에 진실 사다리 표시.** Sent → Delivered(무선 확인만) → Acknowledged(장치 응답) → Verified(읽기 검증) → Failed. Delivered는 성공으로 표시하지 않습니다.
- **General Radio.** One spare ESP32-C3 dongle (`general-radio-1.0.0`) now covers every host radio job: the pairing relay, zone updates, cube colours, the main show, a leased pool lamp and a leased TouchDesigner cue. It has its own panel.<br>**General Radio.** 예비 ESP32-C3 동글 하나(`general-radio-1.0.0`)가 등록 중계, 존 업데이트, 큐브 색, 메인쇼, 임대 풀 램프, 임대 TouchDesigner 큐 등 모든 호스트 무선 작업을 담당합니다. 전용 패널이 있습니다.
- **Guided recording, Web sync plan, USB intake.** Pool guided recording runs inside the PoolZone panel; Inventory › Web sync shows record by record what a Sync would move; This computer › USB intake replaces the old Arm Auto / Arm auto-flash (always off at launch).<br>**가이드 녹화, Web sync 계획, USB 인테이크.** 풀존 가이드 녹화는 PoolZone 패널 안에서 실행됩니다. Inventory › Web sync는 Sync가 옮길 내용을 레코드별로 보여 줍니다. This computer › USB intake는 기존 Arm Auto / Arm auto-flash를 대체하며 실행 시 항상 꺼져 있습니다.

## The console at a glance | 콘솔 한눈에 보기

{{shot:C-1}}
The console: device rail (left), the selected device's panel (centre), Attention panel and timeline dock / 콘솔: 장치 레일(왼쪽), 선택 장치 패널(가운데), Attention 패널과 타임라인 도크

{{shot:C-3}}
A suggestion card's menu: dismiss for this session, or for good; every card keeps its evidence / 제안 카드 메뉴: 이 세션 동안 또는 영구 무시. 모든 카드는 근거를 유지

## Current handover summary | 현재 인수인계 요약

Preshow, Desert, Pool lighting and Mainshow triggering are reported working following the intervention. Open items include Pool slider label treatment, reported Desert reader alignment, battery endurance, one failed test cube, media interface records, release-package checks and the console's own hardware verification. Chapter 15 keeps these distinct from completed repairs.<br>개선 후 프리쇼·사막·풀존 조명·메인쇼 트리거가 동작한다고 보고되었습니다. 남은 항목은 풀존 이름 표시 처리, 사막 리더 정렬, 배터리 지속 시간, 테스트 실패 큐브 1개, 미디어 연결 기록, 릴리스 점검, 그리고 콘솔 자체의 실물 검증입니다. 15장에서 완료된 개선과 구분합니다.

34 annotated screenshots of the NCT Console are included, captured from the console running in `--simulate --scenario docs` mode with isolated demonstration data and simulated boards. Each workflow pairs English and Korean instructions.<br>NCT Console의 단계별 강조 스크린샷 34개가 포함되어 있습니다. 격리된 예시 데이터와 시뮬레이션 보드로 `--simulate --scenario docs` 모드에서 실행한 콘솔을 촬영했습니다. 각 절차에 영어·한국어 안내를 함께 제공합니다.

## Evidence and scope | 근거와 범위

**Code-inspected** means the behaviour is implemented in the working copy inspected on 23 September (commit 7191c5d plus uncommitted console work). **Simulation-verified** means the console's own headless test suite or a scripted simulation exercised it. **Dongle-verified** means the single attached ESP-NOW dongle exercised it on the real radio. **Field-reported** means Elliot, Hojun or Sangeun reported an on-site result. **To confirm** means the installation or client decision still needs checking. Console captures are simulated: yellow outlines identify real controls and results; example numbers, versions and readings are not site settings. Hardware claims come only from the test report in chapter 15.
**코드 확인**은 9월 23일 검토한 작업 사본(커밋 7191c5d 및 미커밋 콘솔 작업)에 구현된 동작을 뜻합니다. **시뮬레이션 확인**은 콘솔 자체의 헤드리스 테스트 또는 스크립트 시뮬레이션으로 실행한 동작입니다. **동글 확인**은 연결된 ESP-NOW 동글 한 개로 실제 무선에서 실행한 동작입니다. **현장 보고**는 Elliot, Hojun 또는 Sangeun이 전달한 현장 결과입니다. **확인 필요**는 설치 상태 또는 클라이언트 결정을 추가 확인해야 한다는 뜻입니다. 콘솔 화면은 시뮬레이션입니다. 노란 테두리는 실제 조작부와 확인할 결과를 표시하며 예시 번호·버전·측정값은 현장 설정값이 아닙니다. 실물 관련 주장은 15장의 테스트 보고서에서만 나옵니다.

The existing repair report remains separate and unchanged. This handbook does not expand the agreed Kimchi and Chips scope to ongoing cube assembly, testing, maintenance or exhibition operation.
기존 수리 보고서는 별도로 보존합니다. 본 문서는 김치앤칩스의 합의된 업무 범위를 지속적인 큐브 조립·테스트·유지보수·전시 운영으로 확대하지 않습니다.

**Korean text:** the Korean in this version was machine-drafted by the documentation pass alongside the English and should be reviewed by a native speaker before the handover meeting.
**한국어 안내:** 이 판의 한국어는 문서 작업 과정에서 영어와 함께 기계 초안으로 작성되었으므로 인수인계 회의 전에 원어민 검토가 필요합니다.

{{page:01}}
{{page:02}}
{{page:03}}
{{page:04}}
{{page:05}}
{{page:06}}
{{page:07}}
{{page:08}}
{{page:09}}
{{page:10}}
{{page:11}}
{{page:12}}
{{page:13}}
{{page:14}}
{{page:15}}
{{page:16}}

<span color="red">*This document was written by Kimchi and Chips*</span>
